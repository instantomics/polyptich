import json
from datetime import date
from decimal import Decimal
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from werkzeug.datastructures import MultiDict

from polyptich.www import AccessIdentity, server
from polyptich.www.auth import AccessVerificationError
from polyptich.www.tables import (
    DataFrameCache,
    TableQueryError,
    apply_query,
    dataframe_column_types,
    normalize_json,
    parse_query,
    table_statistics,
)


class FakeVerifier:
    def verify(self, token):
        if not token:
            raise AccessVerificationError("test token is invalid")
        return AccessIdentity(
            subject="test-subject",
            email="reader@example.test",
            issuer="https://access.example.test",
            audience="polyptich",
            expires_at=2**31 - 1,
        )


@pytest.fixture
def table_app(tmp_path):
    pytest.importorskip("pyarrow")
    report = tmp_path / "www" / "report"
    report.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "name": ["Alpha", "bravo", "CHARLIE", "delta", "echo", "Foxtrot"],
            "category": ["x", "x", "y", "y", "y", "x"],
            "score": pd.array([2, 2, 3, 1, None, 2], dtype="Int64"),
            "when": pd.to_datetime(
                [
                    "2025-01-01T10:00:00Z",
                    "2025-01-02T10:00:00Z",
                    "2025-01-03T10:00:00Z",
                    "2025-01-04T10:00:00Z",
                    "2025-01-05T10:00:00Z",
                    "2025-01-06T10:00:00Z",
                ]
            ),
            "danger": ["=2+2", "+cmd", "safe", " @hidden", "-1+2", "plain"],
            "big": [2**60, 1, 2, 3, 4, 5],
            "measurement": [1.5, np.nan, 2.5, 3.5, 4.5, 5.5],
        }
    )
    asset = report / "table.parquet"
    frame.to_parquet(asset, index=False)
    (report / "plot.json").write_text('{"data": [{"x": [1]}]}')
    (report / "index.html").write_text("<html><body>report</body></html>")
    manifest = {
        "schema": "polyptich.www.report",
        "schema_version": 1,
        "assets": {
            "table": {
                "type": "table",
                "asset": "table.parquet",
                "columns": list(frame.columns),
                "visible_columns": ["name", "score"],
                "column_options": {"score": {"label": "Result", "precision": 1}},
                "row_count": len(frame),
                "uncompressed_bytes": 1024,
            },
            "plot": {"type": "plotly", "asset": "plot.json"},
        },
    }
    (report / "manifest.json").write_text(json.dumps(manifest))
    app = server.create_app(tmp_path, access_verifier=FakeVerifier())
    app.config.update(TESTING=True)
    return app, report, frame


def get(client, path, **kwargs):
    headers = kwargs.pop("headers", {})
    return client.get(path, headers={"Cf-Access-Jwt-Assertion": "reader", **headers}, **kwargs)


def test_legacy_data_and_plotly_responses_are_unchanged(table_app):
    app, _, frame = table_app
    client = app.test_client()

    table = get(client, "/report-data/report/table")
    plot = get(client, "/report-data/report/plot?protocol=1")

    assert table.status_code == 200
    assert isinstance(table.get_json(), list)
    assert len(table.get_json()) == len(frame)
    assert table.get_json()[0]["name"] == "Alpha"
    assert table.get_json()[1]["measurement"] is None
    assert b"NaN" not in table.data
    assert plot.status_code == 200
    assert plot.get_json() == {"data": [{"x": [1]}]}


def test_protocol_auto_modes_use_manifest_and_old_parquet_metadata(table_app):
    app, report, frame = table_app
    client = app.test_client()

    manifest_path = report / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["assets"]["table"].pop("row_count")
    manifest["assets"]["table"].pop("uncompressed_bytes")
    manifest_path.write_text(json.dumps(manifest))

    rows, size = table_statistics(report / "table.parquet", manifest["assets"]["table"])
    assert rows == len(frame)
    assert size > 0

    app.config["POLYPTICH_WWW_TABLE_CLIENT_MAX_ROWS"] = len(frame)
    app.config["POLYPTICH_WWW_TABLE_CLIENT_MAX_BYTES"] = size
    client_response = get(client, "/report-data/report/table?protocol=1").get_json()
    assert client_response["mode"] == "client"
    assert len(client_response["rows"]) == len(frame)

    app.config["POLYPTICH_WWW_TABLE_CLIENT_MAX_ROWS"] = len(frame) - 1
    server_response = get(client, "/report-data/report/table?protocol=1").get_json()
    assert server_response["mode"] == "server"
    assert server_response["page_size"] == 100
    forced_client = get(
        client,
        "/report-data/report/table?protocol=1&data_mode=client",
    ).get_json()
    assert forced_client["mode"] == "server"


def test_server_mode_clamps_pages_after_filtering(table_app):
    app, _, _ = table_app
    payload = get(
        app.test_client(),
        "/report-data/report/table",
        query_string={
            "protocol": 1,
            "data_mode": "server",
            "page": 999,
            "page_size": 2,
            "q": "Alpha",
        },
    ).get_json()

    assert payload["filtered_count"] == 1
    assert payload["page"] == 1
    assert payload["page_count"] == 1
    assert payload["rows"][0]["name"] == "Alpha"


def test_server_filter_sort_page_projection_counts_and_metadata(table_app):
    app, _, _ = table_app
    client = app.test_client()
    query = {
        "protocol": "1",
        "data_mode": "server",
        "filters": json.dumps(
            [
                {"id": "name", "operator": "contains", "value": "A"},
                {"id": "score", "operator": "between", "value": [1, 3]},
            ]
        ),
        "sort": json.dumps(
            [
                {"id": "score", "desc": True},
                {"id": "name", "desc": False},
            ]
        ),
        "columns": json.dumps(["name", "score"]),
        "page": 2,
        "page_size": 2,
    }

    response = get(client, "/report-data/report/table", query_string=query)
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["schema"] == "polyptich.www.table"
    assert payload["schema_version"] == 1
    assert payload["component_id"] == "table"
    assert payload["mode"] == "server"
    assert payload["total_count"] == 6
    assert payload["filtered_count"] == 4
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["page_count"] == 2
    assert payload["has_previous"] is True
    assert payload["has_next"] is False
    assert payload["rows"] == [
        {"name": "bravo", "score": 2},
        {"name": "delta", "score": 1},
    ]
    assert [column["id"] for column in payload["columns"]] == ["name", "score"]
    assert payload["columns"][1] == {
        "id": "score",
        "label": "score",
        "type": "integer",
        "visible": True,
        "config": {"label": "Result", "precision": 1},
        "operators": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "is_null", "not_null"],
    }
    assert payload["capabilities"]["pagination"] is True

    nulls_last = get(
        client,
        "/report-data/report/table",
        query_string={
            "protocol": 1,
            "data_mode": "server",
            "sort": json.dumps([{"id": "score", "desc": True}]),
        },
    ).get_json()
    assert nulls_last["rows"][-1]["score"] is None

    global_filter = get(
        client,
        "/report-data/report/table",
        query_string={"protocol": 1, "data_mode": "server", "q": "+CMD"},
    ).get_json()
    assert [row["name"] for row in global_filter["rows"]] == ["bravo"]


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({"protocol": "2"}, "protocol"),
        ({"protocol": "1", "data_mode": "remote"}, "data_mode"),
        ({"protocol": "1", "page": "zero"}, "page"),
        ({"protocol": "1", "page_size": "1001"}, "page_size"),
        ({"protocol": "1", "q": "x" * 501}, "q"),
        ({"protocol": "1", "sort": "not-json"}, "sort"),
        ({"protocol": "1", "sort": json.dumps([{"id": "missing"}])}, "sort[0].id"),
        (
            {
                "protocol": "1",
                "filters": json.dumps(
                    [{"id": "score", "operator": "contains", "value": "2"}]
                ),
            },
            "filters",
        ),
        ({"protocol": "1", "columns": json.dumps(["missing"])}, "columns[0]"),
        ({"protocol": "1", "unexpected": "yes"}, "unexpected"),
    ],
)
def test_protocol_validation_returns_json_400(table_app, query, field):
    app, _, _ = table_app
    response = get(
        app.test_client(),
        "/report-data/report/table",
        query_string=query,
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "invalid_table_query"
    assert response.get_json()["field"] == field
    assert response.get_json()["message"]


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("eq", "ALPHA", ["Alpha"]),
        ("ne", "alpha", ["bravo", "CHARLIE"]),
        ("contains", "AR", ["CHARLIE"]),
        ("starts_with", "BR", ["bravo"]),
        ("ends_with", "lie", ["CHARLIE"]),
        ("gt", "bravo", ["CHARLIE"]),
        ("gte", "bravo", ["bravo", "CHARLIE"]),
        ("lt", "bravo", ["Alpha"]),
        ("lte", "bravo", ["Alpha", "bravo"]),
        ("between", ["alpha", "bravo"], ["Alpha", "bravo"]),
        ("is_null", None, []),
        ("not_null", None, ["Alpha", "bravo", "CHARLIE"]),
    ],
)
def test_literal_case_insensitive_column_filter_operators(operator, value, expected):
    frame = pd.DataFrame({"name": ["Alpha", "bravo", "CHARLIE"]})
    item = {"id": "name", "operator": operator}
    if operator not in {"is_null", "not_null"}:
        item["value"] = value
    query = parse_query(
        MultiDict([("filters", json.dumps([item]))]),
        dataframe_column_types(frame),
    )

    assert apply_query(frame, query)["name"].tolist() == expected


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("eq", 2, [2]),
        ("ne", 2, [1, 3]),
        ("gt", 2, [3]),
        ("gte", 2, [2, 3]),
        ("lt", 2, [1]),
        ("lte", 2, [1, 2]),
        ("between", [2, 3], [2, 3]),
        ("is_null", None, [None]),
        ("not_null", None, [1, 2, 3]),
    ],
)
def test_numeric_filter_operators_are_type_aware(operator, value, expected):
    frame = pd.DataFrame({"value": pd.array([1, 2, 3, None], dtype="Int64")})
    item = {"id": "value", "operator": operator}
    if operator not in {"is_null", "not_null"}:
        item["value"] = value
    query = parse_query(
        MultiDict([("filters", json.dumps([item]))]),
        dataframe_column_types(frame),
    )

    actual = apply_query(frame, query)["value"].tolist()
    assert [None if pd.isna(value) else value for value in actual] == expected


def test_boolean_and_datetime_filters_are_type_aware():
    frame = pd.DataFrame(
        {
            "enabled": [True, False, True],
            "when": pd.to_datetime(
                ["2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z", "2025-01-03T00:00:00Z"]
            ),
        }
    )
    filters = [
        {"id": "enabled", "operator": "eq", "value": "true"},
        {"id": "when", "operator": "gte", "value": "2025-01-02T00:00:00+00:00"},
    ]
    query = parse_query(
        MultiDict([("filters", json.dumps(filters))]),
        dataframe_column_types(frame),
    )

    assert apply_query(frame, query)["when"].tolist() == [pd.Timestamp("2025-01-03T00:00:00Z")]


def test_json_normalization_is_portable():
    value = {
        "missing": pd.NA,
        "timestamp": pd.Timestamp("2025-01-02T03:04:05Z"),
        "date": date(2025, 1, 2),
        "decimal": Decimal("12.340"),
        "big": np.int64(2**60),
        "nested": [np.float64("nan"), np.float64("inf"), {"value": np.int64(2)}],
    }

    assert normalize_json(value) == {
        "missing": None,
        "timestamp": "2025-01-02T03:04:05+00:00",
        "date": "2025-01-02",
        "decimal": "12.340",
        "big": str(2**60),
        "nested": [None, None, {"value": 2}],
    }


def test_filtered_csv_and_xlsx_exports_are_safe_and_ignore_paging(table_app):
    load_workbook = pytest.importorskip("openpyxl").load_workbook
    app, _, _ = table_app
    client = app.test_client()
    query = {
        "protocol": 1,
        "filters": json.dumps([{"id": "category", "operator": "eq", "value": "X"}]),
        "sort": json.dumps([{"id": "name", "desc": False}]),
        "columns": json.dumps(["name", "danger", "when"]),
        "page": 2,
        "page_size": 1,
    }

    csv_response = get(
        client,
        "/report-download/report/table.csv",
        query_string=query,
    )
    assert csv_response.status_code == 200
    assert csv_response.data.startswith(b"\xef\xbb\xbf")
    csv_text = csv_response.data.decode("utf-8-sig")
    assert csv_text.splitlines()[0] == "name,danger,when"
    assert [line.split(",", 1)[0] for line in csv_text.splitlines()[1:]] == [
        "Alpha",
        "bravo",
        "Foxtrot",
    ]
    assert "'=2+2" in csv_text
    assert "'+cmd" in csv_text
    assert "+00:00" not in csv_text

    xlsx_response = get(
        client,
        "/report-download/report/table.xlsx",
        query_string=query,
    )
    workbook = load_workbook(BytesIO(xlsx_response.data), read_only=True, data_only=False)
    rows = list(workbook.active.iter_rows(values_only=True))
    assert rows[0] == ("name", "danger", "when")
    assert [row[0] for row in rows[1:]] == ["Alpha", "bravo", "Foxtrot"]
    assert rows[1][1] == "'=2+2"
    assert rows[2][1] == "'+cmd"
    assert rows[1][2].tzinfo is None

    old_download = get(client, "/report-download/report/table.xlsx")
    old_workbook = load_workbook(BytesIO(old_download.data), read_only=True)
    assert old_workbook.active.max_row == 7


def test_cache_is_bounded_invalidated_and_queries_do_not_mutate_cached_frame(tmp_path):
    pytest.importorskip("pyarrow")
    path = tmp_path / "table.parquet"
    frame = pd.DataFrame({"name": ["b", "a"]})
    frame.to_parquet(path)
    calls = []
    cache = DataFrameCache(max_entries=1, max_bytes=1024 * 1024)

    def load(asset):
        calls.append(asset)
        return pd.read_parquet(asset)

    first = cache.get(path, load)
    query = parse_query(
        MultiDict([("sort", json.dumps([{"id": "name", "desc": False}]))]),
        dataframe_column_types(first),
    )
    assert apply_query(first, query)["name"].tolist() == ["a", "b"]
    assert cache.get(path, load)["name"].tolist() == ["b", "a"]
    assert len(calls) == 1

    pd.DataFrame({"name": ["changed"]}).to_parquet(path)
    assert cache.get(path, load)["name"].tolist() == ["changed"]
    assert len(calls) == 2


def test_table_routes_preserve_auth_manifest_and_asset_path_security(table_app):
    app, report, _ = table_app
    client = app.test_client()
    assert client.get("/report-data/report/table?protocol=1").status_code == 401
    assert get(client, "/report-data/report/missing?protocol=1").status_code == 404
    assert get(client, "/report-download/report/missing.csv").status_code == 404

    manifest_path = report / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["assets"]["unsafe"] = {"type": "table", "asset": "../outside.parquet"}
    manifest_path.write_text(json.dumps(manifest))
    assert get(client, "/report-data/report/unsafe?protocol=1").status_code == 403


def test_parse_query_rejects_duplicate_arguments():
    with pytest.raises(TableQueryError, match="provided once"):
        parse_query(
            MultiDict([("q", "one"), ("q", "two")]),
            {"name": "string"},
        )
