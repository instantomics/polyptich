import json

import pytest

from polyptich.www import AccessIdentity, create_app, render_workspace_document
from polyptich.www.auth import AccessVerificationError


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


def auth(email="reader@example.test"):
    return {"Cf-Access-Jwt-Assertion": email}


def write_manifest(path, value):
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(json.dumps(value))


def test_workspace_document_browser_and_raw_directory_index_contracts(tmp_path):
    document = render_workspace_document(
        "Workspace <title>",
        '<h2 id="intro">Trusted content</h2>',
        navigation_id="tasks",
    )
    assert document.count("data-polyptich-navigation-shell") == 1
    assert 'data-polyptich-page-version="1"' in document
    assert document.count("data-polyptich-navigation-persistent") == 5
    assert 'href="/static/bootstrap-5.3.8.min.css"' in document
    assert 'href="/static/polyptich-ui.css"' in document
    assert 'href="/static/polyptich-navigation.css"' in document
    assert document.index("bootstrap-5.3.8.min.css") < document.index("polyptich-ui.css")
    assert document.index("polyptich-ui.css") < document.index("polyptich-navigation.css")
    assert 'src="/static/bootstrap-5.3.8.bundle.min.js"' in document
    assert 'src="/static/polyptich-navigation.js"' in document
    assert 'data-navigation-url="/api/v1/navigation"' in document
    assert '"navigation_id":"tasks"' in document
    assert 'id="pt-global-navigation-sidebar"' in document
    assert 'id="pt-global-navigation-toc-sidebar"' in document
    assert 'class="pt-global-navigation__toc-toggle btn btn-light"' in document

    styled = render_workspace_document(
        "Styled", "content", stylesheets=("/page.css",), head_html="<style>main { color: red; }</style>"
    )
    assert 'href="/page.css" data-polyptich-page-resource' in styled
    deduplicated = render_workspace_document(
        "Deduplicated",
        "content",
        stylesheets=("/static/polyptich-ui.css", "/page.css", "/page.css"),
    )
    assert deduplicated.count('href="/static/polyptich-ui.css"') == 1
    assert deduplicated.count('href="/page.css"') == 1

    docs = tmp_path / "www" / "docs"
    docs.mkdir(parents=True)
    raw = b"<html><head><title>Docs</title></head><body><h2 id='intro'>Intro</h2></body></html>"
    (docs / "index.html").write_bytes(raw)
    (docs / "style.css").write_text("body {}")
    (docs / "O'Brien.html").write_text("<html><body>quoted filename</body></html>")
    app = create_app(tmp_path, access_verifier=FakeVerifier())
    client = app.test_client()

    redirect = client.get("/files/docs", headers=auth())
    assert redirect.status_code == 302
    assert redirect.headers["Location"].endswith("/files/docs/")
    page = client.get("/files/docs/", headers=auth())
    assert page.status_code == 200
    assert page.data == raw
    assert b"data-polyptich-navigation-shell" not in page.data
    browser = client.get("/browse/docs?browse=1", headers=auth())
    assert browser.status_code == 200
    assert b"polyptich www: /docs" in browser.data
    assert browser.data.count(b"data-polyptich-navigation-shell") == 1
    assert b"onclick=" not in browser.data
    assert "O'Brien.html" in browser.get_data(as_text=True).replace("&#39;", "'")
    files_root = client.get("/files/", headers=auth())
    assert files_root.status_code == 200
    assert files_root.data.count(b"data-polyptich-navigation-shell") == 1
    prefixed = client.get(
        "/browse/docs?browse=1",
        headers=auth(),
        environ_overrides={"SCRIPT_NAME": "/gateway"},
    )
    assert b'href="/gateway/static/polyptich-navigation.css"' in prefixed.data
    assert b'href="/gateway/static/bootstrap-5.3.8.min.css"' in prefixed.data
    assert b'src="/gateway/static/bootstrap-5.3.8.bundle.min.js"' in prefixed.data
    assert b'data-navigation-url="/gateway/api/v1/navigation"' in prefixed.data


def test_directory_collection_favorites_search_paging_and_scope_filtering(tmp_path):
    www = tmp_path / "www"
    tasks = www / "tasks"
    tasks.mkdir(parents=True)
    for name in ["annotation", "alpha", "beta", "gamma"]:
        path = tasks / name
        path.mkdir()
        (path / "index.html").write_text(f"<html><body>{name}</body></html>")
    evidence = tasks / "alpha" / "evidence"
    evidence.mkdir()
    (evidence / "metrics.html").write_text("<html><body>metrics</body></html>")
    (tasks / "index.html").write_text("<html><body>tasks</body></html>")
    (tasks / "index.htm").write_text("<html><body>legacy tasks</body></html>")
    (tasks / "guide.html").write_text("<html><body>guide</body></html>")
    (tasks / ".hidden").mkdir()
    (tasks / ".hidden" / "index.html").write_text("hidden")
    (tasks / "assets").mkdir()
    (tasks / "assets" / "logo.png").write_bytes(b"png")
    (tasks / "raw-data").mkdir()
    (tasks / "raw-data" / "values.json").write_text("{}")
    write_manifest(
        tasks / "private",
        {
            "schema": "polyptich.www.folder",
            "schema_version": 1,
            "required_scope": "private.read",
        },
    )
    (tasks / "private" / "index.html").write_text("<html><body>private</body></html>")
    (www / "navigation.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.navigation",
                "schema_version": 1,
                "title": "Iomix",
                "items": [
                    {
                        "id": "tasks",
                        "label": "Tasks",
                        "type": "collection",
                        "icon": "tasks",
                        "href": "/files/tasks/",
                        "collection": {
                            "type": "directory",
                            "path": "tasks",
                            "placeholder": "Find a task",
                            "favorites": ["annotation"],
                        },
                    },
                    {
                        "id": "restricted",
                        "label": "Restricted",
                        "type": "section",
                        "children": [
                            {
                                "id": "private-task",
                                "label": "Private task",
                                "type": "page",
                                "href": "/files/tasks/private/",
                            }
                        ],
                    },
                ],
            }
        )
    )
    app = create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        trusted_viewer_emails=["viewer@example.test"],
    )
    client = app.test_client()

    skeleton = client.get("/api/v1/navigation", headers=auth()).get_json()
    assert skeleton["schema"] == "polyptich.www.navigation"
    assert [item["id"] for item in skeleton["items"]] == ["tasks"]
    assert skeleton["items"][0]["icon"] == "tasks"
    collection_href = skeleton["items"][0]["collection"]["href"]
    assert client.get("/api/v1/navigation", headers=auth()).headers["Cache-Control"] == "no-store"

    first = client.get(collection_href + "?q=a&page=1&page_size=1", headers=auth()).get_json()
    second = client.get(collection_href + "?q=a&page=2&page_size=1", headers=auth()).get_json()
    assert first["schema"] == "polyptich.www.navigation.collection"
    assert [item["label"] for item in first["favorites"]] == ["annotation"]
    assert [item["label"] for item in second["favorites"]] == ["annotation"]
    assert first["page"] == 1 and first["page_size"] == 1
    assert first["total"] == 3 and first["has_more"] is True
    assert first["items"] != second["items"]

    all_items = client.get(collection_href + "?page_size=100", headers=auth()).get_json()
    labels = {item["label"] for item in all_items["items"]}
    assert labels == {"alpha", "beta", "gamma", "guide.html"}
    assert "index.html" not in labels and "index.htm" not in labels
    assert "private" not in labels
    assert "assets" not in labels
    assert "raw-data" not in labels
    alpha = next(item for item in all_items["items"] if item["label"] == "alpha")
    assert alpha["type"] == "collection"
    assert alpha["icon"] == "folder"
    assert alpha["href"].endswith("/files/tasks/alpha/")
    nested = client.get(alpha["collection"]["href"], headers=auth()).get_json()
    assert "placeholder" not in alpha["collection"]
    evidence_item = nested["items"][0]
    assert evidence_item["label"] == "evidence"
    assert evidence_item["type"] == "collection"
    leaf = client.get(evidence_item["collection"]["href"], headers=auth()).get_json()
    assert leaf["items"] == [
        {
            "href": "/files/tasks/alpha/evidence/metrics.html",
            "icon": "document",
            "id": leaf["items"][0]["id"],
            "label": "metrics.html",
            "type": "page",
        }
    ]

    viewer_tree = client.get("/api/v1/navigation", headers=auth("viewer@example.test")).get_json()
    assert [item["id"] for item in viewer_tree["items"]] == ["tasks", "restricted"]


@pytest.mark.parametrize(
    "icon", [None, "<svg>", "https://example.test/icon", "Tasks", "folder red"]
)
def test_navigation_rejects_non_allowlisted_icons(tmp_path, icon):
    www = tmp_path / "www"
    www.mkdir()
    (www / "navigation.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.navigation",
                "schema_version": 1,
                "title": "Iomix",
                "items": [
                    {
                        "id": "tasks",
                        "label": "Tasks",
                        "type": "section",
                        "icon": icon,
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="invalid icon"):
        create_app(tmp_path, access_verifier=FakeVerifier())


def test_global_endpoint_collection_must_target_registered_endpoint(tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    (www / "navigation.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.navigation",
                "schema_version": 1,
                "title": "Iomix",
                "items": [
                    {
                        "id": "tasks",
                        "label": "Tasks",
                        "type": "collection",
                        "collection": {
                            "type": "endpoint",
                            "href": "/endpoint/missing/api/navigation",
                        },
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="registered endpoint"):
        create_app(tmp_path, access_verifier=FakeVerifier())


def test_collection_search_is_enabled_only_by_an_explicit_placeholder(tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    (www / "navigation.json").write_text(
        json.dumps(
            {
                "schema": "polyptich.www.navigation",
                "schema_version": 1,
                "title": "Iomix",
                "items": [
                    {
                        "id": "plain",
                        "label": "Plain",
                        "type": "collection",
                        "collection": {
                            "type": "endpoint",
                            "href": "/endpoint/reports/api/navigation",
                        },
                    },
                    {
                        "id": "searchable",
                        "label": "Searchable",
                        "type": "collection",
                        "collection": {
                            "type": "endpoint",
                            "href": "/endpoint/reports/api/searchable",
                            "placeholder": "Find a report",
                        },
                    },
                ],
            }
        )
    )
    write_manifest(
        www / "reports",
        {
            "schema": "polyptich.www.endpoint",
            "schema_version": 1,
            "endpoint_id": "tests.navigation",
        },
    )

    class Endpoint:
        def __init__(self, **_kwargs):
            pass

        def register(self, _app, **_kwargs):
            pass

    app = create_app(
        tmp_path,
        access_verifier=FakeVerifier(),
        endpoint_factories={"tests.navigation": Endpoint},
    )

    items = app.test_client().get("/api/v1/navigation", headers=auth()).get_json()["items"]

    assert "placeholder" not in items[0]["collection"]
    assert items[1]["collection"]["placeholder"] == "Find a report"
