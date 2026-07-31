import json
import sys
from types import SimpleNamespace

import pytest
from flask import jsonify

from polyptich.www import (
    AccessConfig,
    AccessIdentity,
    current_identity,
    current_scopes,
    require_scope,
)
from polyptich.www.auth import AccessVerificationError
from polyptich.www import server


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
    (report / "index.html").write_text("<html><head></head><body>private report</body></html>")
    (report / "plot.json").write_text('{"data": []}')
    (report / "table.parquet").write_bytes(b"table")
    write_manifest(
        www / "unsafe-report",
        {
            "schema": "polyptich.www.report",
            "schema_version": 1,
            "assets": {
                "plot": {"type": "plotly", "asset": "../private/report/plot.json"}
            },
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
    rendered = client.get("/report/private/report", headers=viewer)
    assert rendered.status_code == 200
    assert b'<base href="/files/private/report/">' in rendered.data
    assert client.get("/report-data/private/report/plot", headers=viewer).data == b'{"data": []}'
    download = client.get("/report-download/private/report/table.xlsx", headers=viewer)
    assert download.status_code == 200
    assert download.data == b"xlsx-data"


def test_trusted_endpoint_factory_gets_context_scope_helpers_and_banner(tmp_path):
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
    assert b"data-endpoint-browser-banner" in viewer.data
    assert b'href="/browse/private"' in viewer.data
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
