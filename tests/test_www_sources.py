import json
from io import BytesIO

from test_www_file_controls import FakeVerifier, auth

from polyptich.www import create_app
from polyptich.www.page import SCHEMA


def published_source(tmp_path):
    source = tmp_path / "drafts"
    source.mkdir()
    www = tmp_path / "www"
    www.mkdir()
    (www / "sources.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.sources",
                "schema_version": 1,
                "mounts": {"documents": "drafts"},
            }
        )
    )
    (www / "sidebar.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.sidebar",
                "schema_version": 1,
            }
        )
    )
    app = create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        operator_emails=["operator@example.test"],
    )
    app.testing = True
    client = app.test_client()
    client.environ_base["HTTP_CF_ACCESS_JWT_ASSERTION"] = "operator@example.test"
    return source, www, app, client


def test_source_edits_atomic_replacement_and_navigation_are_live(tmp_path):
    source, www, _app, client = published_source(tmp_path)
    draft = source / "draft.md"
    draft.write_text("# Original\n\n![Figure](figure.svg)")
    (source / "figure.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    # A former publication must never win over an edited or deleted source.
    stale = www / "documents"
    stale.mkdir()
    (stale / "draft.md").write_text("# Stale copy")
    (stale / "sidebar.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.sidebar.folder",
                "schema_version": 1,
                "label": "Live drafts",
            }
        )
    )
    generated = www / "report"
    generated.mkdir()
    (generated / "index.html").write_text("Generated report")

    assert b"Original" in client.get("/documents/draft.md").data
    before = client.get("/api/v1/document-revision/documents/draft.md").json
    replacement = source / "replacement.md"
    replacement.write_text("# Revised\n\nSaved without publishing")
    replacement.replace(draft)
    after = client.get("/api/v1/document-revision/documents/draft.md").json
    assert before != after
    assert b"Saved without publishing" in client.get("/documents/draft.md").data
    assert client.get("/documents/draft.md?raw=1").data == draft.read_bytes()
    assert client.get("/documents/figure.svg").data == (source / "figure.svg").read_bytes()
    assert client.get("/report/").data == b"Generated report"
    assert b"Live drafts" in client.get("/api/v1/navigation").data

    draft.rename(source / "renamed.md")
    assert client.get("/documents/draft.md").status_code == 404
    items = client.get("/api/v1/navigation/collections/www/documents").json["items"]
    assert [item["label"] for item in items] == ["renamed.md"]
    assert b"renamed.md" in client.get("/documents/").data
    (source / "renamed.md").unlink()
    assert client.get("/documents/renamed.md").status_code == 404
    assert client.get("/api/v1/navigation/collections/www/documents").json["items"] == []


def test_source_boundaries_scopes_and_web_writes(tmp_path):
    source, _www, app, client = published_source(tmp_path)
    (source / "draft.md").write_text("# Draft")
    (source / ".hidden.md").write_text("hidden")
    (source / "escape.md").symlink_to(tmp_path / "private.md")
    (tmp_path / "private.md").write_text("private")
    token = app.config["POLYPTICH_WWW_FILE_CONTROL_TOKEN"]
    for url in (
        "/sources.json",
        "/documents/.hidden.md",
        "/documents/escape.md",
        "/documents/../../private.md",
    ):
        assert client.get(url).status_code in {403, 404}
    assert (
        client.post(
            "/upload/documents",
            data={
                "csrf_token": token,
                "files": (BytesIO(b"new"), "new.md"),
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/delete/documents/draft.md",
            data={
                "csrf_token": token,
                "confirmed": "yes",
            },
        ).status_code
        == 403
    )
    assert (source / "draft.md").exists()
    assert not (source / "new.md").exists()
    assert b"escape.md" not in client.get("/documents/").data

    (source / "manifest.json").write_text(json.dumps({"required_scope": "dashboard:control"}))
    for url in (
        "/documents/draft.md",
        "/documents/draft.md?raw=1",
        "/api/v1/document-revision/documents/draft.md",
    ):
        assert client.get(url, headers=auth("reader@example.test")).status_code == 403
    assert (
        b"documents"
        not in client.get("/api/v1/navigation", headers=auth("reader@example.test")).data
    )


def test_generated_reports_can_live_inside_source_folders(tmp_path):
    source, www, _, _ = published_source(tmp_path)
    (source / "study").mkdir()
    (source / "study" / "README.md").write_text("# Study")
    report = www / "documents" / "study" / "report"
    report.mkdir(parents=True)
    (report / "manifest.json").write_text(json.dumps({"schema": SCHEMA, "schema_version": 1}))
    (report / "index.html").write_text("Generated study report")
    client = create_app(tmp_path, access_verifier=FakeVerifier()).test_client()
    client.environ_base["HTTP_CF_ACCESS_JWT_ASSERTION"] = "reader@example.test"
    assert client.get("/documents/study/report/").data == b"Generated study report"
    assert b"Study" in client.get("/documents/study/README.md").data
    items = client.get("/api/v1/navigation/collections/www/documents/study").json["items"]
    assert {item["label"] for item in items} == {"README.md", "report"}
    (report / "index.html").write_text("Regenerated study report")
    assert client.get("/documents/study/report/").data == b"Regenerated study report"
