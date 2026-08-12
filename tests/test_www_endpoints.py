import json
import sys
from types import SimpleNamespace

import pytest
from flask import jsonify

from polyptich.www import (
    AccessConfig,
    AccessIdentity,
    OverviewGrid,
    current_identity,
    current_scopes,
    register_service_restart_control,
    render_workspace_document,
    require_scope,
    server,
)
from polyptich.www.auth import AccessVerificationError
from polyptich.www.overview import OverviewGridEndpoint


class FakeVerifier:
    def verify(self, token):
        if not token or "@" not in token:
            raise AccessVerificationError("test token is invalid")
        return AccessIdentity(
            subject="subject-" + token,
            email=token,
            issuer="https://access.example.test",
            audience="polyptich",
            expires_at=2**31 - 1,
        )


def auth(email):
    return {"Cf-Access-Jwt-Assertion": email}


def write_manifest(path, value):
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps(value))


def test_access_and_inherited_scopes_cover_browser_report_files_and_assets(tmp_path, monkeypatch):
    www = tmp_path / "www"
    www.mkdir()
    (www / "public.txt").write_text("public")
    report = www / "private" / "report"
    write_manifest(
        www / "private",
        {"schema": "polyptich.www.folder", "schema_version": 1, "required_scope": "private.read"},
    )
    write_manifest(
        report,
        {
            "schema": "polyptich.www.report",
            "schema_version": 1,
            "title": "Private report",
            "assets": {
                "plot": {"type": "plotly", "asset": "plot.json"},
                "table": {"type": "table", "asset": "table.parquet"},
            },
        },
    )
    (report / "index.html").write_text(
        render_workspace_document("Private report", "private report")
    )
    (report / "plot.json").write_text('{"data": []}')
    (report / "table.parquet").write_bytes(b"table")
    write_manifest(
        www / "unsafe-report",
        {
            "schema": "polyptich.www.report",
            "schema_version": 1,
            "assets": {"plot": {"type": "plotly", "asset": "../private/report/plot.json"}},
        },
    )
    (www / "unsafe-report" / "index.html").write_text("<html><head></head></html>")

    class Frame:
        def to_excel(self, output, index=False):
            output.write(b"xlsx-data")

    monkeypatch.setattr(
        server, "_require_pandas", lambda: SimpleNamespace(read_parquet=lambda _: Frame())
    )
    app = server.create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        trusted_viewer_emails=["viewer@example.test"],
    )
    client = app.test_client()

    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/readyz").get_json() == {"status": "ready"}
    for path in ["/", "/files/public.txt", "/static/polyptich-www.css"]:
        assert client.get(path).status_code == 401

    regular = auth("reader@example.test")
    assert client.get("/health", headers=regular).status_code == 404
    assert client.post("/restart", headers=regular).status_code == 404
    assert client.post("/delete/public.txt", headers=regular).status_code == 404
    root_page = client.get("/", headers=regular)
    assert root_page.status_code == 200
    assert "default-src 'self'" in root_page.headers["Content-Security-Policy"]
    assert b"public.txt" in root_page.data
    assert b"private/" not in root_page.data
    assert client.get("/report-data/unsafe-report/plot", headers=regular).status_code == 403
    for path in [
        "/browse/private",
        "/report/private/report",
        "/files/private/report/plot.json",
        "/report-data/private/report/plot",
        "/report-download/private/report/table.xlsx",
    ]:
        assert client.get(path, headers=regular).status_code == 403

    viewer = auth("viewer@example.test")
    rendered = client.get("/report/private/report/", headers=viewer)
    assert rendered.status_code == 200
    assert rendered.data.count(b"data-polyptich-navigation-shell") == 1
    assert b"<base " not in rendered.data
    assert client.get("/report/private/report/plot.json", headers=viewer).data == b'{"data": []}'
    assert client.get("/report-data/private/report/plot", headers=viewer).data == b'{"data": []}'
    download = client.get("/report-download/private/report/table.xlsx", headers=viewer)
    assert download.status_code == 200
    assert download.data == b"xlsx-data"


def test_navigation_exposes_registered_restart_action_only_to_operators(tmp_path):
    (tmp_path / "www").mkdir()
    app = server.create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        operator_emails=["operator@example.test"],
    )
    register_service_restart_control(
        app,
        session_url="/endpoint/agent/api/v1/session",
        restart_url="/endpoint/agent/api/v1/service/restart",
    )
    client = app.test_client()

    viewer = client.get(
        "/api/v1/navigation", headers=auth("viewer@example.test")
    ).get_json()
    operator = client.get(
        "/api/v1/navigation",
        headers=auth("operator@example.test"),
        environ_overrides={"SCRIPT_NAME": "/gateway"},
    ).get_json()

    assert viewer["actions"] == []
    assert operator["actions"] == [
        {
            "id": "service.restart",
            "type": "service_restart",
            "label": "Restart server",
            "session_url": "/gateway/endpoint/agent/api/v1/session",
            "restart_url": "/gateway/endpoint/agent/api/v1/service/restart",
            "health_url": "/gateway/healthz",
        }
    ]


def test_overview_endpoint_uses_workspace_document(tmp_path):
    OverviewGrid(tmp_path / "www" / "overview", title="Datasets", navigation_id="datasets")
    app = server.create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        endpoint_factories={"polyptich.overview-grid": OverviewGridEndpoint},
    )

    response = app.test_client().get("/endpoint/overview/", headers=auth("reader@example.test"))

    assert response.status_code == 200
    assert response.data.count(b"data-polyptich-navigation-shell") == 1
    assert b"polyptich-navigation.css" in response.data
    assert b"polyptich-overview.js" in response.data
    assert b'"navigation_id":"datasets"' in response.data


def test_endpoint_contributions_require_destination_and_collection_source_scope(tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    (www / "navigation.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.navigation",
                "schema_version": 1,
                "title": "Iomix",
                "items": [{"id": "agent", "label": "Agent", "type": "section"}],
            }
        )
    )
    write_manifest(
        www / "public",
        {
            "schema": "polyptich.www.endpoint",
            "schema_version": 1,
            "endpoint_id": "tests.scoped-navigation",
            "navigation": {
                "parent_id": "agent",
                "items": [
                    {
                        "id": "private-page",
                        "label": "Secret page",
                        "type": "page",
                        "href": "private/",
                    },
                    {
                        "id": "private-collection",
                        "label": "Secret collection",
                        "type": "collection",
                        "href": ".",
                        "collection": {
                            "type": "endpoint",
                            "href": "private/api/v1/navigation/items",
                            "placeholder": "Find a secret",
                        },
                    },
                ],
            },
        },
    )
    write_manifest(
        www / "public" / "private",
        {
            "schema": "polyptich.www.endpoint",
            "schema_version": 1,
            "endpoint_id": "tests.scoped-navigation",
            "required_scope": "private.read",
        },
    )

    class Endpoint:
        def __init__(self, path, mount_path, manifest):
            pass

        def register(self, app, mount_url, endpoint_name):
            app.add_url_rule(mount_url + "/", endpoint_name, lambda: "endpoint")

    app = server.create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        trusted_viewer_emails=["viewer@example.test"],
        endpoint_factories={"tests.scoped-navigation": Endpoint},
    )
    client = app.test_client()

    regular = client.get("/api/v1/navigation", headers=auth("reader@example.test"))
    assert regular.get_json()["items"] == []
    assert b"Secret page" not in regular.data
    assert b"Secret collection" not in regular.data

    trusted = client.get("/api/v1/navigation", headers=auth("viewer@example.test")).get_json()
    assert [item["id"] for item in trusted["items"][0]["children"]] == [
        "private-page",
        "private-collection",
    ]


def test_trusted_endpoint_factory_gets_context_scope_helpers_and_global_navigation(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "navigation.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.navigation",
                "schema_version": 1,
                "title": "Iomix",
                "items": [
                    {"id": "agent", "label": "Agent", "type": "section", "icon": "agent"},
                    {
                        "id": "global-agent-runs",
                        "label": "All agent runs",
                        "type": "collection",
                        "collection": {
                            "type": "endpoint",
                            "href": "/endpoint/private/agent/api/v1/navigation/agent-runs",
                            "placeholder": "Find an agent run",
                        },
                    },
                ],
            }
        )
    )
    write_manifest(
        tmp_path / "www" / "private",
        {"schema": "polyptich.www.folder", "schema_version": 1, "required_scope": "private.read"},
    )
    endpoint_path = tmp_path / "www" / "private" / "agent"
    write_manifest(
        endpoint_path,
        {
            "schema": "polyptich.www.endpoint",
            "schema_version": 1,
            "endpoint_id": "tests.agent",
            "title": "Agent",
            "navigation": {
                "parent_id": "agent",
                "items": [
                    {
                        "id": "agent-runs",
                        "label": "Agent runs",
                        "type": "collection",
                        "href": ".",
                        "collection": {
                            "type": "endpoint",
                            "href": "api/v1/navigation/agent-runs",
                            "placeholder": "Find an agent run",
                        },
                    }
                ],
            },
        },
    )
    observed = {}

    class AgentEndpoint:
        def __init__(self, path, mount_path, manifest):
            observed.update(path=path, mount_path=mount_path, manifest=manifest)

        def register(self, app, mount_url, endpoint_name):
            observed.update(
                workspace=app.config["POLYPTICH_WWW_WORKSPACE_ROOT"],
                root_path=app.config["POLYPTICH_WWW_ROOT_PATH"],
                external_origin=app.config["POLYPTICH_WWW_EXTERNAL_ORIGIN"],
                restart_callback=app.config["POLYPTICH_WWW_RESTART_CALLBACK"],
            )
            app.add_url_rule(mount_url + "/", endpoint_name, self.index)
            app.add_url_rule(mount_url + "/control", endpoint_name + "_control", self.control)

        def index(self):
            return (
                "<html><body>"
                + current_identity().email
                + " "
                + ",".join(sorted(current_scopes()))
                + "</body></html>"
            )

        def control(self):
            require_scope("agent.control")
            return jsonify({"controlled_by": current_identity().email})

    def restart():
        return None

    app = server.create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        trusted_viewer_emails=["viewer@example.test"],
        operator_emails=["operator@example.test"],
        endpoint_factories={"tests.agent": AgentEndpoint},
        external_origin="https://www.example.test/",
        restart_callback=restart,
    )
    client = app.test_client()

    assert (
        client.get("/endpoint/private/agent/", headers=auth("reader@example.test")).status_code
        == 403
    )
    viewer = client.get("/endpoint/private/agent/", headers=auth("viewer@example.test"))
    assert viewer.status_code == 200
    assert b"private.read" in viewer.data
    assert b"data-polyptich-navigation-shell" not in viewer.data
    assert b"data-endpoint-browser-banner" not in viewer.data
    regular_navigation = client.get(
        "/api/v1/navigation", headers=auth("reader@example.test")
    ).get_json()
    assert regular_navigation["items"] == []
    viewer_navigation = client.get(
        "/api/v1/navigation", headers=auth("viewer@example.test")
    ).get_json()
    contributed = viewer_navigation["items"][0]["children"][0]
    assert viewer_navigation["items"][0]["icon"] == "agent"
    assert contributed["href"] == "/endpoint/private/agent/"
    assert contributed["collection"] == {
        "type": "endpoint",
        "href": "/endpoint/private/agent/api/v1/navigation/agent-runs",
        "placeholder": "Find an agent run",
    }
    global_collection = viewer_navigation["items"][1]
    assert global_collection["id"] == "global-agent-runs"
    assert global_collection["collection"]["href"] == (
        "/endpoint/private/agent/api/v1/navigation/agent-runs"
    )
    assert (
        client.get(
            "/endpoint/private/agent/control", headers=auth("viewer@example.test")
        ).status_code
        == 403
    )
    controlled = client.get(
        "/endpoint/private/agent/control", headers=auth("operator@example.test")
    )
    assert controlled.get_json() == {"controlled_by": "operator@example.test"}
    operator_page = client.get("/endpoint/private/agent/", headers=auth("operator@example.test"))
    for scope in [
        b"reports.read",
        b"agent.read",
        b"private.read",
        b"agent.control",
        b"service.restart",
    ]:
        assert scope in operator_page.data
    assert observed["path"] == endpoint_path
    assert observed["mount_path"] == "private/agent"
    assert observed["workspace"] == tmp_path
    assert observed["root_path"] == tmp_path / "www"
    assert observed["external_origin"] == "https://www.example.test"
    assert observed["restart_callback"] is restart


def test_unknown_endpoint_id_fails_startup_without_importing_a_handler(tmp_path):
    write_manifest(
        tmp_path / "www" / "unknown",
        {
            "schema": "polyptich.www.endpoint",
            "schema_version": 1,
            "endpoint_id": "publisher.unknown",
        },
    )

    with pytest.raises(ValueError, match="Unknown Polyptich WWW endpoint ID 'publisher.unknown'"):
        server.create_app(tmp_path, access_verifier=FakeVerifier(), endpoint_factories={})


def test_production_cli_requires_loopback_and_runs_waitress(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(server, "create_app", lambda root, **kwargs: (root, kwargs))
    monkeypatch.setitem(
        sys.modules,
        "waitress",
        SimpleNamespace(serve=lambda app, **kwargs: captured.update(app=app, serve=kwargs)),
    )
    arguments = [
        "--root",
        str(tmp_path),
        "--host",
        "127.0.0.1",
        "--port",
        "5100",
        "--trusted-proxy",
        "--access-issuer",
        "https://access.example.test",
        "--access-audience",
        "polyptich-audience",
        "--trusted-viewer-email",
        "viewer@example.test",
        "--operator-email",
        "operator@example.test",
        "--external-origin",
        "https://www.example.test",
    ]

    assert server.main(arguments) == 0
    assert captured["serve"] == {"host": "127.0.0.1", "port": 5100, "threads": 8}
    root, options = captured["app"]
    assert root == str(tmp_path)
    assert isinstance(options["access_config"], AccessConfig)
    assert options["trusted_proxy"] is True
    assert options["operator_emails"] == ["operator@example.test"]
    non_loopback = list(arguments)
    non_loopback[3] = "0.0.0.0"
    with pytest.raises(ValueError, match="literal loopback"):
        server.main(non_loopback)
