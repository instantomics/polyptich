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

    response = app.test_client().get("/managed/", headers=auth())

    assert response.status_code == 200
    assert b'data-polyptich-page-version="1"' in response.data
    assert response.data.count(b"data-polyptich-navigation-persistent") == 6
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

    response = app.test_client().get("/raw/", headers=auth())

    assert response.status_code == 200
    assert b"data-polyptich-navigation-host" not in response.data
    assert b"data-polyptich-page-version" not in response.data


def test_partial_navigation_fragment_and_report_initialisation_contracts():
    script_path = (
        Path(__file__).parents[1]
        / "src"
        / "polyptich"
        / "www"
        / "static"
        / "polyptich-navigation.js"
    )
    script = script_path.read_text()

    assert 'const separator = fragment.indexOf("?")' in script
    assert 'return {target: "", params: new URLSearchParams(fragment)}' in script
    assert "decodeFragmentTarget(fragment)" in script
    assert 'return `#${encodedTarget}?${state}`' in script
    assert "formatFragment(entry.id, fragmentState.params)" in script
    assert "const fragment = parseFragment(url.hash)" in script
    assert 'new CustomEvent("polyptich:report-reveal"' in script
    assert "target: fragment.target" in script
    assert "params: new URLSearchParams(fragment.params)" in script

    commit_page = script.split("const commitPage = async", 1)[1].split(
        "const navigate = async", 1
    )[0]
    assert commit_page.index("oldScripts) script.remove()") < commit_page.index(
        "await executeScripts(page)"
    )
    assert commit_page.index("await executeScripts(page)") < commit_page.index(
        "renderToc()"
    )
    assert commit_page.index("renderToc()") < commit_page.index(
        "restorePosition(finalUrl, scrollPosition)"
    )
