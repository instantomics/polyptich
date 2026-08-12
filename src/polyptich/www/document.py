import json
from html import escape

from flask import current_app, url_for

PAGE_CONTEXT_SCHEMA = "polyptich.www.page-context"
PAGE_CONTEXT_SCHEMA_VERSION = 1
PAGE_PROTOCOL_VERSION = 1


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
    stylesheet_html = "\n".join(
        f'  <link rel="stylesheet" href="{escape(str(url), quote=True)}" '
        'data-polyptich-page-resource>'
        for url in stylesheets
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
  <link rel="stylesheet" href="{escape(navigation_stylesheet_url, quote=True)}"
        data-polyptich-navigation-persistent>
{stylesheet_html}{head_html}
</head>
<body data-polyptich-navigation-host data-polyptich-page-version="{PAGE_PROTOCOL_VERSION}">
  <a class="pt-global-navigation__skip" href="#pt-global-navigation-main">Skip to content</a>
  <div id="pt-global-navigation-shell" data-polyptich-navigation-shell
       data-navigation-url="{escape(navigation_url, quote=True)}">
    <button class="pt-global-navigation__toggle" type="button"
            aria-controls="pt-global-navigation-sidebar"
            aria-expanded="false">Navigation</button>
    <button class="pt-global-navigation__overlay" type="button"
            aria-label="Close navigation" tabindex="-1"></button>
    <aside id="pt-global-navigation-sidebar" class="pt-global-navigation__sidebar"
           aria-label="Global navigation">
      <div class="pt-global-navigation__body">
        <div class="pt-global-navigation__heading" data-pt-navigation-title>Navigation</div>
        <nav class="pt-global-navigation__nav" aria-label="Site" data-pt-navigation-list>
          <p class="pt-global-navigation__status">Loading navigation…</p>
        </nav>
        <nav class="pt-global-navigation__toc" aria-label="On this page"
             data-pt-navigation-toc hidden></nav>
      </div>
      <div class="pt-global-navigation__actions" aria-label="Workspace actions"
           data-pt-navigation-actions hidden></div>
    </aside>
  </div>
  <script id="pt-global-navigation-context" type="application/json">{context}</script>
  <main id="pt-global-navigation-main"{main_class_attr} tabindex="-1">
{content_html}
  </main>
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
    )
    return current_app.response_class(content, content_type="text/html; charset=utf-8")


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
