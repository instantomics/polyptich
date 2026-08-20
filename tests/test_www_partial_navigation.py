from pathlib import Path

from polyptich.www import AccessIdentity, create_app, render_workspace_document


class FakeVerifier:
    def verify(self, token):
        return AccessIdentity(
            subject="subject",
            email=token,
            issuer="https://access.example.test",
            audience="polyptich",
            expires_at=2**31 - 1,
        )


def auth():
    return {"Cf-Access-Jwt-Assertion": "reader@example.test"}


def test_managed_static_pages_advertise_partial_navigation_protocol(tmp_path: Path):
    page = tmp_path / "www" / "managed"
    page.mkdir(parents=True)
    (page / "index.html").write_text(
        render_workspace_document(
            "Managed",
            '<h2 id="section">Managed content</h2>',
            navigation_id="managed",
            head_html='<meta name="managed-page" content="true">',
            body_end_html='<script src="/static/polyptich-overview.js"></script>',
        ),
        encoding="utf-8",
    )
    app = create_app(tmp_path, access_verifier=FakeVerifier())

    response = app.test_client().get("/files/managed/", headers=auth())

    assert response.status_code == 200
    assert b'data-polyptich-page-version="1"' in response.data
    assert response.data.count(b"data-polyptich-navigation-persistent") == 5
    assert b'id="pt-global-navigation-main"' in response.data
    assert b'id="pt-global-navigation-context"' in response.data
    assert b'<script src="/static/polyptich-overview.js"></script>' in response.data
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_raw_html_stays_outside_partial_navigation_protocol(tmp_path: Path):
    page = tmp_path / "www" / "raw"
    page.mkdir(parents=True)
    (page / "index.html").write_text(
        "<!doctype html><html><body><main>Raw content</main></body></html>",
        encoding="utf-8",
    )
    app = create_app(tmp_path, access_verifier=FakeVerifier())

    response = app.test_client().get("/files/raw/", headers=auth())

    assert response.status_code == 200
    assert b"data-polyptich-navigation-host" not in response.data
    assert b"data-polyptich-page-version" not in response.data
