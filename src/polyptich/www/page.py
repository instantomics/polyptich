import json
import re
import shutil
import struct
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from uuid import uuid4

from .document import render_workspace_document

SCHEMA = "polyptich.www.report"
SCHEMA_VERSION = 1


def _now():
    return datetime.now(timezone.utc).isoformat()


def _slugify(value):
    value = str(value or "item").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "item"


def _import_optional(module, purpose):
    try:
        return __import__(module)
    except ImportError as exc:
        raise ImportError(f"Install {module!r} to use {purpose}.") from exc


def _display_mode(value):
    value = str(value or "intrinsic")
    if value not in {"intrinsic", "responsive", "full-width"}:
        raise ValueError("Plot display must be 'intrinsic', 'responsive', or 'full-width'.")
    return value


def _png_dimensions(path, dpi):
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", header[16:24])
    dpi = float(dpi or 96)
    return {
        "width_css_px": round(width / dpi * 96, 2),
        "height_css_px": round(height / dpi * 96, 2),
        "pixel_width": width,
        "pixel_height": height,
        "dpi": dpi,
    }


def _svg_length(value):
    match = re.fullmatch(r"\s*([0-9.]+)\s*(px|pt|in|cm|mm)?\s*", value or "")
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "px"
    factors = {"px": 1, "pt": 96 / 72, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4}
    return number * factors[unit]


def _svg_dimensions(path):
    root = path.read_text(errors="replace")[:4096]
    width_match = re.search(r"\bwidth=[\"']([^\"']+)", root)
    height_match = re.search(r"\bheight=[\"']([^\"']+)", root)
    width = _svg_length(width_match.group(1)) if width_match else None
    height = _svg_length(height_match.group(1)) if height_match else None
    if width is None or height is None:
        return None
    return {"width_css_px": round(width, 2), "height_css_px": round(height, 2)}


class _SlugRegistry:
    def __init__(self, existing=None):
        self._counts = {}
        for slug in existing or []:
            self.add_existing(slug)

    def add_existing(self, slug):
        base = re.sub(r"-\d+$", "", slug)
        suffix = slug[len(base) :].lstrip("-")
        number = int(suffix) if suffix.isdigit() else 1
        self._counts[base] = max(self._counts.get(base, 0), number)

    def make(self, title):
        base = _slugify(title)
        count = self._counts.get(base, 0) + 1
        self._counts[base] = count
        return base if count == 1 else f"{base}-{count}"


class ComponentContainer:
    def __init__(self, page, component):
        self.page = page
        self.component = component

    def section(self, title, collapsed=False):
        return self._add_container("section", title=title, collapsed=collapsed)

    def collapsible(self, title, collapsed=True):
        return self._add_container("collapsible", title=title, collapsed=collapsed)

    def tabs(self, title=None):
        return Tabs(self.page, self._add_component({"type": "tabs", "title": title, "tabs": []}))

    def card(self, title=None, href=None):
        return self._add_container("card", title=title, href=href)

    def add_matplotlib(
        self,
        figure,
        title=None,
        format="svg",
        close=True,
        caption=None,
        display="intrinsic",
        **savefig_kwargs,
    ):
        return self._add_component(
            self.page._store_matplotlib(
                figure, title, format, close, caption, display, savefig_kwargs
            )
        )

    def add_plotly(
        self, figure, title=None, config=None, caption=None, display="intrinsic"
    ):
        return self._add_component(
            self.page._store_plotly(figure, title, config, caption, display)
        )

    def add_table(
        self,
        dataframe,
        title=None,
        visible_columns=None,
        options=None,
        column_options=None,
    ):
        """Add an interactive TanStack table.

        ``options`` supports ``pagination``, ``page_size``, ``page_size_options``,
        ``searchable``, ``sortable``, ``column_filters``, ``column_visibility``,
        ``data_mode``, ``density``, ``url_state``, and ``pinned_columns``. Per-column
        labels, formatting, alignment, width, sorting, filtering, and safe ``href``
        templates such as ``"/gene/{gene}"`` can be supplied through
        ``column_options``.
        """
        return self._add_component(
            self.page._store_table(
                dataframe, title, visible_columns, options or {}, column_options or {}
            )
        )

    def add_html(self, html, title=None):
        return self._add_component({"type": "html", "title": title, "html": str(html)})

    def add_card(self, html=None, title=None, href=None):
        card = self.card(title=title, href=href)
        if html is not None:
            card.add_html(html)
        return card

    def add_button(self, label, href=None, title=None, variant="primary"):
        return self._add_component(
            {"type": "button", "title": title, "label": label, "href": href, "variant": variant}
        )

    def _add_container(self, type, title, **extra):
        component = {"type": type, "title": title, "children": [], **extra}
        return ComponentContainer(self.page, self._add_component(component))

    def _children(self):
        return self.component.setdefault("children", [])

    def _add_component(self, component):
        if "id" not in component:
            component["id"] = self.page._next_slug(component.get("title") or component.get("type"))
        self._children().append(component)
        self.page._save_manifest()
        return component


class Tab(ComponentContainer):
    pass


class Tabs:
    def __init__(self, page, component):
        self.page = page
        self.component = component

    def add_tab(self, title="Tab"):
        tab = {"id": self.page._next_slug(title), "title": title, "children": []}
        self.component.setdefault("tabs", []).append(tab)
        self.page._save_manifest()
        return Tab(self.page, tab)


class Page(ComponentContainer):
    def __init__(
        self,
        path,
        title=None,
        description=None,
        author=None,
        overwrite=True,
        required_scope=None,
        navigation_id=None,
        breadcrumbs=None,
        provenance=None,
        source_url=None,
        previous=None,
        next=None,
    ):
        self.path = Path(path)
        self.assets_path = self.path
        self.manifest_path = self.path / "manifest.json"
        self.html_path = self.path / "index.html"

        if overwrite and self.path.exists():
            shutil.rmtree(self.path)

        self.path.mkdir(parents=True, exist_ok=True)

        if self.manifest_path.exists() and not overwrite:
            self.manifest = json.loads(self.manifest_path.read_text())
            if self.manifest.get("schema") != SCHEMA:
                raise ValueError(f"{self.manifest_path} is not a polyptich www manifest")
        else:
            self.manifest = {
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "title": title or self.path.name,
                "description": description,
                "author": author,
                "created_at": _now(),
                "updated_at": _now(),
                "assets": {},
            }
            if required_scope is not None:
                self.manifest["required_scope"] = required_scope
            if navigation_id is not None:
                self.manifest["navigation_id"] = navigation_id
            if breadcrumbs is not None:
                self.manifest["breadcrumbs"] = breadcrumbs
            if provenance is not None:
                self.manifest["provenance"] = provenance
            if source_url is not None:
                self.manifest["source_url"] = source_url
            if previous is not None:
                self.manifest["previous"] = previous
            if next is not None:
                self.manifest["next"] = next
            self.components = []

        if not hasattr(self, "components"):
            self.components = self.manifest.pop("components", [])

        self._slugs = _SlugRegistry(self._iter_ids(self.components))
        super().__init__(self, {"children": self.components})
        self._save_manifest()

    def write(self):
        self._save_manifest()

    def _children(self):
        return self.components

    def _save_manifest(self):
        self.manifest["updated_at"] = _now()
        self.manifest["assets"] = self._asset_manifest(self.components)
        self.manifest.pop("components", None)
        self.path.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2, sort_keys=False))
        self.html_path.write_text(self._render_html())

    def _next_slug(self, title):
        return self._slugs.make(title)

    def _asset_name(self, title, suffix):
        stem = _slugify(title or "asset")
        return f"{stem}-{uuid4().hex[:8]}.{suffix.lstrip('.')}"

    def _store_matplotlib(
        self, figure, title, format, close, caption, display, savefig_kwargs
    ):
        suffix = format.lower().lstrip(".")
        if suffix not in {"svg", "png"}:
            raise ValueError("Matplotlib format must be 'svg' or 'png'.")
        asset = self._asset_name(title or "figure", suffix)
        kwargs = {"transparent": True, "bbox_inches": "tight", **savefig_kwargs}
        path = self.assets_path / asset
        figure.savefig(path, format=suffix, **kwargs)
        dpi = kwargs.get("dpi")
        if dpi in {None, "figure"}:
            dpi = getattr(figure, "dpi", 96)
        dimensions = None
        if path.exists():
            dimensions = _png_dimensions(path, dpi) if suffix == "png" else _svg_dimensions(path)
        if close:
            try:
                import matplotlib.pyplot as plt

                plt.close(figure)
            except Exception:  # noqa: BLE001, S110 -- closing is best-effort cleanup.
                pass
        return {
            "type": "matplotlib",
            "title": title,
            "caption": caption,
            "asset": asset,
            "format": suffix,
            "display": {"mode": _display_mode(display), **(dimensions or {})},
            "downloads": [
                {
                    "asset": asset,
                    "format": suffix,
                    "media_type": "image/svg+xml" if suffix == "svg" else "image/png",
                }
            ],
        }

    def _store_plotly(self, figure, title, config, caption, display):
        plotly = _import_optional("plotly", "Plotly figures")
        graph_objects = __import__("plotly.graph_objects", fromlist=["Figure"])
        if not isinstance(figure, graph_objects.Figure):
            raise TypeError("add_plotly() only accepts plotly.graph_objects.Figure instances.")
        asset = self._asset_name(title or "plotly", "json")
        (self.assets_path / asset).write_text(plotly.io.to_json(figure, validate=True))
        width = figure.layout.width or 700
        height = figure.layout.height or 450
        return {
            "type": "plotly",
            "title": title,
            "caption": caption,
            "asset": asset,
            "config": config or {},
            "display": {
                "mode": _display_mode(display),
                "width_css_px": width,
                "height_css_px": height,
            },
            "downloads": [
                {"asset": asset, "format": "json", "media_type": "application/json"}
            ],
        }

    def _store_table(self, dataframe, title, visible_columns, options, column_options):
        pyarrow = _import_optional("pyarrow", "parquet-backed dataframe tables")
        parquet = __import__("pyarrow.parquet", fromlist=["write_table"])
        asset = self._asset_name(title or "table", "parquet")
        table = dataframe.reset_index()
        table.columns = [
            " | ".join(map(str, col)) if isinstance(col, tuple) else str(col)
            for col in table.columns
        ]
        columns = list(table.columns)
        if len(columns) != len(set(columns)):
            raise ValueError("Table columns must be unique after converting them to strings.")
        unknown_visible = set(visible_columns or []) - set(columns)
        unknown_options = set(column_options) - set(columns)
        if unknown_visible:
            raise ValueError(f"Unknown visible table columns: {sorted(unknown_visible)!r}")
        if unknown_options:
            raise ValueError(f"Unknown table column options: {sorted(unknown_options)!r}")
        data_mode = options.get("data_mode", "auto")
        if data_mode not in {"auto", "client", "server"}:
            raise ValueError("Table data_mode must be 'auto', 'client', or 'server'.")
        page_size = options.get("page_size", 25)
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("Table page_size must be a positive integer.")
        if page_size > 1000:
            options["page_size"] = 1000
        arrow_table = pyarrow.Table.from_pandas(table, preserve_index=False)
        parquet.write_table(arrow_table, self.assets_path / asset)
        from .tables import dataframe_column_types

        return {
            "type": "table",
            "title": title,
            "asset": asset,
            "columns": columns,
            "visible_columns": visible_columns,
            "options": options,
            "column_options": column_options,
            "row_count": len(table),
            "uncompressed_bytes": arrow_table.nbytes,
            "column_types": dataframe_column_types(table),
        }

    def _iter_ids(self, components):
        for component in components:
            if "id" in component:
                yield component["id"]
            yield from self._iter_ids(component.get("children", []))
            for tab in component.get("tabs", []):
                if "id" in tab:
                    yield tab["id"]
                yield from self._iter_ids(tab.get("children", []))

    def _asset_manifest(self, components):
        assets = {}
        for component in components:
            if component.get("asset"):
                assets[component["id"]] = {
                    key: value
                    for key, value in component.items()
                    if key
                    in {
                        "type",
                        "title",
                        "asset",
                        "format",
                        "config",
                        "caption",
                        "display",
                        "downloads",
                        "columns",
                        "visible_columns",
                        "options",
                        "column_options",
                        "row_count",
                        "uncompressed_bytes",
                        "column_types",
                    }
                }
            assets.update(self._asset_manifest(component.get("children", [])))
            for tab in component.get("tabs", []):
                assets.update(self._asset_manifest(tab.get("children", [])))
        return assets

    def _render_html(self):
        title = str(self.manifest.get("title") or self.path.name)
        description = self.manifest.get("description")
        body = "\n".join(self._render_components(self.components))
        subtitle = f'<p class="subtitle">{escape(str(description))}</p>' if description else ""
        breadcrumbs = self._render_breadcrumbs()
        provenance = self._render_provenance()
        report_navigation = self._render_report_navigation()
        title_heading = self._heading("h1", title, "report-title")
        content = f"""    {breadcrumbs}
    <header class="report-header" id="report-title">
      {title_heading}
      {subtitle}
    </header>
    <nav class="report-toolbar" aria-label="Report tools">
      {report_navigation}
      <button type="button" data-report-action="expand">Expand all</button>
      <button type="button" data-report-action="collapse">Collapse all</button>
      <button type="button" data-report-action="copy">Copy report link</button>
      <button type="button" data-report-action="print">Print</button>
    </nav>
    <div id="report-root">
      {body}
    </div>
    {provenance}
    <button class="report-back-to-top" type="button" data-report-action="top" hidden>Back to top</button>"""
        body_end = """  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" data-polyptich-script="once"></script>
  <script src="https://unpkg.com/@tanstack/table-core@8.21.3/build/umd/index.production.js" data-polyptich-script="once"></script>
  <script src="/static/polyptich-www.js"></script>"""
        return render_workspace_document(
            title,
            content,
            navigation_id=self.manifest.get("navigation_id"),
            stylesheets=["/static/polyptich-www.css"],
            body_end_html=body_end,
            main_class="report",
            toc=True,
        )

    def _render_components(self, components):
        for component in components:
            yield self._render_component(component)

    def _render_component(self, component):
        type = component.get("type")
        id_attr = escape(component.get("id", ""), quote=True)
        title = escape(self._title(component))
        children = "\n".join(self._render_components(component.get("children", [])))
        if type == "section":
            heading = self._heading("h2", self._title(component), component.get("id", ""))
            return f'<section class="section" id="{id_attr}">{heading}{children}</section>'
        if type == "collapsible":
            open_attr = "" if component.get("collapsed") else " open"
            return f'<details class="component collapsible card" id="{id_attr}"{open_attr}><summary>{title}</summary>{children}</details>'
        if type == "card":
            heading = ""
            if component.get("title"):
                heading = self._heading(
                    "h3", component["title"], component.get("id", ""), "component-title"
                )
            href = component.get("href")
            if href:
                heading = f'<h3 class="component-title">{title}</h3>'
                return f'<a class="component card linked-card" id="{id_attr}" href="{escape(str(href), quote=True)}">{heading}{children}</a>'
            return f'<article class="component card" id="{id_attr}">{heading}{children}</article>'
        if type == "tabs":
            return self._render_tabs(component)

        heading = ""
        if component.get("title"):
            heading = self._heading(
                "h3", component["title"], component.get("id", ""), "component-title"
            )
        if type == "matplotlib":
            src = escape(component["asset"], quote=True)
            content = self._render_plot(component, f'<img class="plot-image" src="{src}" alt="{title}">')
        elif type == "plotly":
            asset = escape(component["asset"], quote=True)
            config = escape(json.dumps(component.get("config") or {}), quote=True)
            plot = (
                f'<div class="plotly" data-component-id="{id_attr}" data-asset="{asset}" '
                f'data-config="{config}"></div>'
            )
            content = self._render_plot(component, plot, loading=True)
        elif type == "table":
            columns = escape(json.dumps(component.get("columns") or []), quote=True)
            visible = escape(json.dumps(component.get("visible_columns")), quote=True)
            options = escape(json.dumps(component.get("options") or {}), quote=True)
            column_options = escape(json.dumps(component.get("column_options") or {}), quote=True)
            content = (
                f'<div><div class="table-actions"><button type="button" data-table-export="{id_attr}" data-format="csv">Download CSV</button>'
                f'<button type="button" data-table-export="{id_attr}" data-format="xlsx">Download Excel</button></div>'
                f'<div class="data-table" data-component-id="{id_attr}" data-columns="{columns}" '
                f'data-visible-columns="{visible}" data-options="{options}" '
                f'data-column-options="{column_options}"></div></div>'
            )
        elif type == "html":
            content = f"<div>{component.get('html') or ''}</div>"
        elif type == "button":
            label = escape(str(component.get("label") or component.get("title") or "Button"))
            variant = escape(str(component.get("variant") or "primary"), quote=True)
            href = component.get("href")
            if href:
                content = f'<a class="www-button www-button-{variant}" href="{escape(str(href), quote=True)}">{label}</a>'
            else:
                content = f'<button class="www-button www-button-{variant}" type="button">{label}</button>'
        else:
            content = f'<p>Unsupported component: {escape(str(type))}</p>'
        if type == "button":
            return f'<div class="component component-button" id="{id_attr}">{content}</div>'
        if type == "html" and not component.get("title"):
            return f'<div class="component component-html" id="{id_attr}">{content}</div>'
        return f'<article class="component card component-{type}" id="{id_attr}">{heading}{content}</article>'

    def _render_tabs(self, component):
        id_attr = escape(component.get("id", ""), quote=True)
        title = ""
        label_attr = ' aria-label="Tabs"'
        if component.get("title"):
            title = self._heading(
                "h3", component["title"], component.get("id", ""), "component-title"
            )
            label_attr = f' aria-labelledby="{id_attr}-title"'
            title = title.replace("<h3 ", f'<h3 id="{id_attr}-title" ', 1)
        buttons = []
        panels = []
        for index, tab in enumerate(component.get("tabs", [])):
            active = " active" if index == 0 else ""
            selected = "true" if index == 0 else "false"
            tabindex = "0" if index == 0 else "-1"
            hidden = "" if index == 0 else " hidden"
            tab_id = escape(tab.get("id", ""), quote=True)
            button_id = f"{tab_id}-tab"
            tab_title = escape(str(tab.get("title") or "Tab"))
            buttons.append(
                f'<button class="tab-button{active}" id="{button_id}" type="button" '
                f'role="tab" aria-selected="{selected}" aria-controls="{tab_id}" '
                f'tabindex="{tabindex}" data-tab="{tab_id}">{tab_title}</button>'
            )
            panel = "\n".join(self._render_components(tab.get("children", [])))
            panels.append(
                f'<div class="tab-panel{active}" id="{tab_id}" role="tabpanel" '
                f'aria-labelledby="{button_id}" tabindex="0"{hidden}>{panel}</div>'
            )
        return f'<section class="component tabs" id="{id_attr}">{title}<div class="tab-buttons" role="tablist"{label_attr}>{"".join(buttons)}</div><div class="tab-panels">{"".join(panels)}</div></section>'

    def _heading(self, tag, title, target_id, class_name=None):
        title_text = str(title)
        class_attr = f' class="{class_name}"' if class_name else ""
        href = escape(f"#{target_id}", quote=True)
        label = escape(f"Permalink to {title_text}", quote=True)
        return (
            f"<{tag}{class_attr}>{escape(title_text)}"
            f'<a class="anchor-link" href="{href}" aria-label="{label}">#</a>'
            f"</{tag}>"
        )

    def _render_plot(self, component, plot, loading=False):
        display = component.get("display") or {}
        mode = escape(str(display.get("mode") or "intrinsic"), quote=True)
        width = display.get("width_css_px")
        height = display.get("height_css_px")
        style_parts = []
        if width:
            style_parts.append(f"--plot-width:{float(width):.2f}px")
        if height:
            style_parts.append(f"--plot-height:{float(height):.2f}px")
        style = f' style="{";".join(style_parts)}"' if style_parts else ""
        download = (component.get("downloads") or [{}])[0]
        asset = escape(str(download.get("asset") or component.get("asset")), quote=True)
        format_name = escape(str(download.get("format") or "file").upper())
        component_id = escape(component.get("id", ""), quote=True)
        status = (
            '<div class="plot-status" role="status">Loading interactive plot...</div>'
            if loading
            else ""
        )
        caption = component.get("caption")
        caption_html = f"<figcaption>{escape(str(caption))}</figcaption>" if caption else ""
        return (
            f'<figure class="report-figure" data-plot-display="{mode}"{style}>'
            '<div class="plot-actions">'
            '<button type="button" data-plot-fullscreen>Fullscreen</button>'
            f'<a href="{asset}" download>Download {format_name}</a>'
            f'<button type="button" data-copy-component-link="{component_id}">Copy link</button>'
            "</div>"
            f'<div class="plot-frame">{status}{plot}</div>{caption_html}</figure>'
        )

    def _render_breadcrumbs(self):
        breadcrumbs = self.manifest.get("breadcrumbs")
        if not breadcrumbs:
            return '<nav class="report-breadcrumbs" aria-label="Breadcrumb" data-auto-breadcrumbs></nav>'
        items = []
        for index, item in enumerate(breadcrumbs):
            if isinstance(item, dict):
                label, href = item.get("label"), item.get("href")
            else:
                label, href = item[0], item[1] if len(item) > 1 else None
            label = escape(str(label))
            if index == len(breadcrumbs) - 1 or not href:
                items.append(f'<li aria-current="page">{label}</li>')
            else:
                items.append(f'<li><a href="{escape(str(href), quote=True)}">{label}</a></li>')
        return f'<nav class="report-breadcrumbs" aria-label="Breadcrumb"><ol>{"".join(items)}</ol></nav>'

    def _render_provenance(self):
        values = {
            "Author": self.manifest.get("author"),
            "Created": self.manifest.get("created_at"),
            "Generated": self.manifest.get("updated_at"),
            **(self.manifest.get("provenance") or {}),
        }
        if self.manifest.get("source_url"):
            values["Source"] = {
                "label": "Open source notebook",
                "href": self.manifest["source_url"],
            }
        rows = []
        for label, value in values.items():
            if value is None:
                continue
            if isinstance(value, dict) and value.get("href"):
                rendered = (
                    f'<a href="{escape(str(value["href"]), quote=True)}">'
                    f'{escape(str(value.get("label") or value["href"]))}</a>'
                )
            else:
                rendered = escape(str(value))
            rows.append(f"<dt>{escape(str(label))}</dt><dd>{rendered}</dd>")
        rows.append('<dt>Manifest</dt><dd><a href="manifest.json">manifest.json</a></dd>')
        return (
            '<details class="report-provenance"><summary>Report provenance</summary>'
            f'<dl>{"".join(rows)}</dl></details>'
        )

    def _render_report_navigation(self):
        links = []
        for key, default_label in (("previous", "Previous report"), ("next", "Next report")):
            value = self.manifest.get(key)
            if not value:
                continue
            if isinstance(value, dict):
                href = value.get("href")
                label = value.get("label") or default_label
            else:
                href, label = value, default_label
            if href:
                links.append(
                    f'<a class="report-{key}" href="{escape(str(href), quote=True)}">'
                    f"{escape(str(label))}</a>"
                )
        source = self.manifest.get("source_url")
        if source:
            links.append(
                f'<a class="report-source" href="{escape(str(source), quote=True)}">Source</a>'
            )
        return "".join(links)

    def _title(self, component):
        return str(component.get("title") or component.get("type") or "Item")
