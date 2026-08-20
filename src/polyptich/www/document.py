import json
from html import escape

from flask import current_app, url_for

PAGE_CONTEXT_SCHEMA = "polyptich.www.page-context"
PAGE_CONTEXT_SCHEMA_VERSION = 1
PAGE_PROTOCOL_VERSION = 1
APP_BOOTSTRAP_SCHEMA = "polyptich.www.app-bootstrap"
APP_BOOTSTRAP_SCHEMA_VERSION = 1
BOOTSTRAP_STYLESHEET_URL = "/static/bootstrap-5.3.8.min.css"
BOOTSTRAP_ICONS_STYLESHEET_URL = "/static/bootstrap-icons-1.13.1.min.css"
BOOTSTRAP_SCRIPT_URL = "/static/bootstrap-5.3.8.bundle.min.js"
POLYPTICH_STYLESHEET_URL = "/static/polyptich-ui.css"


def render_workspace_document(
    title,
    content_html,
    *,
    navigation_id=None,
    stylesheets=(),
    head_html="",
    body_end_html="",
    toc=True,
    main_class=None,
    navigation_url="/api/v1/navigation",
    navigation_stylesheet_url="/static/polyptich-navigation.css",
    navigation_script_url="/static/polyptich-navigation.js",
    bootstrap_stylesheet_url=BOOTSTRAP_STYLESHEET_URL,
    bootstrap_icons_stylesheet_url=BOOTSTRAP_ICONS_STYLESHEET_URL,
    bootstrap_script_url=BOOTSTRAP_SCRIPT_URL,
    polyptich_stylesheet_url=POLYPTICH_STYLESHEET_URL,
):
    """Render trusted HTML fragments in Polyptich's complete workspace document.

    Default navigation URLs assume a root-mounted static publication. Callers
    publishing under another mount may provide deployment-specific URLs.
    """
    if navigation_id is not None and (
        not isinstance(navigation_id, str) or not navigation_id.strip()
    ):
        raise ValueError("navigation_id must be a non-empty string or None")
    if type(toc) is not bool:
        raise TypeError("toc must be a boolean")

    title_text = str(title)
    title_html = escape(title_text)
    main_class_attr = (
        f' class="{escape(str(main_class), quote=True)}"' if main_class is not None else ""
    )
    persistent_stylesheets = _ordered_unique_urls(
        (
            bootstrap_stylesheet_url,
            bootstrap_icons_stylesheet_url,
            polyptich_stylesheet_url,
            navigation_stylesheet_url,
        )
    )
    page_stylesheets = _ordered_unique_urls(stylesheets, exclude=persistent_stylesheets)
    persistent_stylesheet_html = "\n".join(
        f'  <link rel="stylesheet" href="{escape(url, quote=True)}" '
        "data-polyptich-navigation-persistent>"
        for url in persistent_stylesheets
    )
    stylesheet_html = "\n".join(
        f'  <link rel="stylesheet" href="{escape(str(url), quote=True)}" '
        'data-polyptich-page-resource>'
        for url in page_stylesheets
    )
    if stylesheet_html:
        stylesheet_html += "\n"
    context = _json_script_value(
        {
            "schema": PAGE_CONTEXT_SCHEMA,
            "schema_version": PAGE_CONTEXT_SCHEMA_VERSION,
            "navigation_id": navigation_id,
            "toc": toc,
        }
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_html}</title>
{persistent_stylesheet_html}
{stylesheet_html}{head_html}
</head>
<body data-polyptich-navigation-host data-polyptich-page-version="{PAGE_PROTOCOL_VERSION}">
  <a class="pt-global-navigation__skip" href="#pt-global-navigation-main">Skip to content</a>
  <div id="pt-global-navigation-shell" data-polyptich-navigation-shell
       data-navigation-url="{escape(navigation_url, quote=True)}">
    <div class="pt-global-navigation__mobile-controls">
      <button class="pt-global-navigation__toggle btn btn-light" type="button"
              aria-controls="pt-global-navigation-sidebar"
              aria-expanded="false">Navigation</button>
      <button class="pt-global-navigation__toc-toggle btn btn-light" type="button"
              aria-controls="pt-global-navigation-toc-sidebar"
              aria-expanded="false" hidden>On this page</button>
    </div>
    <button class="pt-global-navigation__overlay" type="button"
             aria-label="Close navigation" tabindex="-1"></button>
    <aside id="pt-global-navigation-sidebar" class="pt-global-navigation__sidebar"
           aria-label="Global navigation">
      <div class="pt-global-navigation__body">
        <div class="pt-global-navigation__drawer-header">
          <div class="pt-global-navigation__heading" data-pt-navigation-title>Navigation</div>
          <button class="pt-global-navigation__drawer-close btn btn-light" type="button"
                  aria-label="Close navigation">Close</button>
        </div>
        <nav class="pt-global-navigation__nav" aria-label="Site" data-pt-navigation-list>
          <p class="pt-global-navigation__status">Loading navigation…</p>
        </nav>
      </div>
      <div class="pt-global-navigation__actions" aria-label="Workspace actions"
           data-pt-navigation-actions hidden></div>
    </aside>
    <aside id="pt-global-navigation-toc-sidebar" class="pt-global-navigation__toc-sidebar"
           aria-label="On this page" hidden>
      <div class="pt-global-navigation__drawer-header pt-global-navigation__drawer-header--mobile">
        <div class="pt-global-navigation__heading">On this page</div>
        <button class="pt-global-navigation__drawer-close btn btn-light" type="button"
                aria-label="Close table of contents">Close</button>
      </div>
      <nav class="pt-global-navigation__toc" data-pt-navigation-toc></nav>
    </aside>
  </div>
  <script id="pt-global-navigation-context" type="application/json">{context}</script>
  <main id="pt-global-navigation-main"{main_class_attr} tabindex="-1">
{content_html}
  </main>
  <script src="{escape(bootstrap_script_url, quote=True)}"
          data-polyptich-navigation-persistent></script>
{body_end_html}
  <script src="{escape(navigation_script_url, quote=True)}" defer
          data-polyptich-navigation-persistent></script>
</body>
</html>
"""


def render_workspace_page(
    title,
    content_html,
    *,
    navigation_id=None,
    stylesheets=(),
    head_html="",
    body_end_html="",
    toc=True,
    main_class=None,
):
    """Render a workspace document with request-prefix-aware Polyptich URLs."""
    content = render_workspace_document(
        title,
        content_html,
        navigation_id=navigation_id,
        stylesheets=stylesheets,
        head_html=head_html,
        body_end_html=body_end_html,
        toc=toc,
        main_class=main_class,
        navigation_url=url_for("navigation_tree"),
        navigation_stylesheet_url=url_for("static_files", filename="polyptich-navigation.css"),
        navigation_script_url=url_for("static_files", filename="polyptich-navigation.js"),
        bootstrap_stylesheet_url=url_for(
            "static_files", filename="bootstrap-5.3.8.min.css"
        ),
        bootstrap_icons_stylesheet_url=url_for(
            "static_files", filename="bootstrap-icons-1.13.1.min.css"
        ),
        bootstrap_script_url=url_for(
            "static_files", filename="bootstrap-5.3.8.bundle.min.js"
        ),
        polyptich_stylesheet_url=url_for("static_files", filename="polyptich-ui.css"),
    )
    return current_app.response_class(content, content_type="text/html; charset=utf-8")


def render_workspace_app(
    title,
    *,
    app_id,
    mount_id,
    bootstrap,
    bootstrap_id="pt-app-bootstrap",
    stylesheets=(),
    module_scripts=(),
    navigation_id=None,
    toc=False,
    main_class=None,
):
    """Render a framework-neutral application mount in the workspace shell."""
    app_id = _required_identifier(app_id, "app_id")
    mount_id = _required_identifier(mount_id, "mount_id")
    bootstrap_id = _required_identifier(bootstrap_id, "bootstrap_id")
    envelope = _json_script_value(
        {
            "schema_id": APP_BOOTSTRAP_SCHEMA,
            "schema_version": APP_BOOTSTRAP_SCHEMA_VERSION,
            "app_id": app_id,
            "bootstrap": bootstrap,
        }
    )
    content = (
        f'<div id="{escape(mount_id, quote=True)}" '
        f'data-polyptich-app="{escape(app_id, quote=True)}" '
        f'data-polyptich-bootstrap="{escape(bootstrap_id, quote=True)}"></div>'
        f'<script id="{escape(bootstrap_id, quote=True)}" '
        f'type="application/json">{envelope}</script>'
    )
    scripts = "".join(
        f'<script type="module" src="{escape(str(url), quote=True)}" '
        'data-polyptich-script="once"></script>'
        for url in _ordered_unique_urls(module_scripts)
    )
    return render_workspace_page(
        title,
        content,
        navigation_id=navigation_id,
        stylesheets=stylesheets,
        body_end_html=scripts,
        toc=toc,
        main_class=main_class,
    )


def json_script_value(value):
    """Serialize data so it cannot terminate an HTML script-data element."""
    return _json_script_value(value)


def _json_script_value(value):
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _ordered_unique_urls(urls, *, exclude=()):
    excluded = {str(url) for url in exclude}
    result = []
    seen = set(excluded)
    for url in urls:
        value = str(url)
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _required_identifier(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value
