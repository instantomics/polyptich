import json
import re
import shutil
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

    def add_matplotlib(self, figure, title=None, format="svg", close=True, **savefig_kwargs):
        return self._add_component(
            self.page._store_matplotlib(figure, title, format, close, savefig_kwargs)
        )

    def add_plotly(self, figure, title=None, config=None):
        return self._add_component(self.page._store_plotly(figure, title, config))

    def add_table(self, dataframe, title=None, visible_columns=None):
        return self._add_component(self.page._store_table(dataframe, title, visible_columns))

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

    def _store_matplotlib(self, figure, title, format, close, savefig_kwargs):
        suffix = format.lower().lstrip(".")
        if suffix not in {"svg", "png"}:
            raise ValueError("Matplotlib format must be 'svg' or 'png'.")
        asset = self._asset_name(title or "figure", suffix)
        kwargs = {"transparent": True, **savefig_kwargs}
        figure.savefig(self.assets_path / asset, format=suffix, **kwargs)
        if close:
            try:
                import matplotlib.pyplot as plt

                plt.close(figure)
            except Exception:  # noqa: BLE001, S110 -- closing is best-effort cleanup.
                pass
        return {"type": "matplotlib", "title": title, "asset": asset, "format": suffix}

    def _store_plotly(self, figure, title, config):
        plotly = _import_optional("plotly", "Plotly figures")
        graph_objects = __import__("plotly.graph_objects", fromlist=["Figure"])
        if not isinstance(figure, graph_objects.Figure):
            raise TypeError("add_plotly() only accepts plotly.graph_objects.Figure instances.")
        asset = self._asset_name(title or "plotly", "json")
        (self.assets_path / asset).write_text(plotly.io.to_json(figure, validate=True))
        return {"type": "plotly", "title": title, "asset": asset, "config": config or {}}

    def _store_table(self, dataframe, title, visible_columns):
        _import_optional("pyarrow", "parquet-backed dataframe tables")
        asset = self._asset_name(title or "table", "parquet")
        table = dataframe.reset_index()
        table.columns = [
            " | ".join(map(str, col)) if isinstance(col, tuple) else str(col)
            for col in table.columns
        ]
        table.to_parquet(self.assets_path / asset, index=False)
        return {
            "type": "table",
            "title": title,
            "asset": asset,
            "columns": list(table.columns),
            "visible_columns": visible_columns,
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
                    in {"type", "title", "asset", "format", "config", "columns", "visible_columns"}
                }
            assets.update(self._asset_manifest(component.get("children", [])))
            for tab in component.get("tabs", []):
                assets.update(self._asset_manifest(tab.get("children", [])))
        return assets

    def _render_html(self):
        title = str(self.manifest.get("title") or self.path.name)
        title_html = escape(title)
        description = self.manifest.get("description")
        body = "\n".join(self._render_components(self.components))
        subtitle = f'<p class="subtitle">{escape(str(description))}</p>' if description else ""
        content = f"""    <header class="report-header">
      <h1>{title_html}</h1>
      {subtitle}
    </header>
    <div id="report-root">
      {body}
    </div>"""
        body_end = """  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <script src="https://unpkg.com/tabulator-tables@6.3.1/dist/js/tabulator.min.js"></script>
  <script src="/static/polyptich-www.js"></script>"""
        return render_workspace_document(
            title,
            content,
            navigation_id=self.manifest.get("navigation_id"),
            stylesheets=[
                "https://unpkg.com/tabulator-tables@6.3.1/dist/css/tabulator.min.css",
                "/static/polyptich-www.css",
            ],
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
            return f'<section class="section" id="{id_attr}"><h2>{title}</h2>{children}</section>'
        if type == "collapsible":
            open_attr = "" if component.get("collapsed") else " open"
            return f'<details class="component collapsible card" id="{id_attr}"{open_attr}><summary>{title}</summary>{children}</details>'
        if type == "card":
            heading = f'<h3 class="component-title">{title}</h3>' if component.get("title") else ""
            href = component.get("href")
            if href:
                return f'<a class="component card linked-card" id="{id_attr}" href="{escape(str(href), quote=True)}">{heading}{children}</a>'
            return f'<article class="component card" id="{id_attr}">{heading}{children}</article>'
        if type == "tabs":
            return self._render_tabs(component)

        heading = (
            f'<h3 class="component-title">{escape(str(component["title"]))}</h3>'
            if component.get("title")
            else ""
        )
        if type == "matplotlib":
            src = escape(component["asset"], quote=True)
            content = f'<img class="plot-image" src="{src}" alt="{title}">'
        elif type == "plotly":
            asset = escape(component["asset"], quote=True)
            config = escape(json.dumps(component.get("config") or {}), quote=True)
            content = f'<div class="plotly" data-component-id="{id_attr}" data-asset="{asset}" data-config="{config}"></div>'
        elif type == "table":
            columns = escape(json.dumps(component.get("columns") or []), quote=True)
            visible = escape(json.dumps(component.get("visible_columns")), quote=True)
            content = (
                f'<div><div class="table-actions"><a data-table-download="{id_attr}" href="#">Download Excel</a></div>'
                f'<div class="table" data-component-id="{id_attr}" data-columns="{columns}" data-visible-columns="{visible}"></div></div>'
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
            content = f"<p>Unsupported component: {escape(str(type))}</p>"
        return f'<article class="component card" id="{id_attr}">{heading}{content}</article>'

    def _render_tabs(self, component):
        id_attr = escape(component.get("id", ""), quote=True)
        title = (
            f'<h3 class="component-title">{escape(str(component["title"]))}</h3>'
            if component.get("title")
            else ""
        )
        buttons = []
        panels = []
        for index, tab in enumerate(component.get("tabs", [])):
            active = " active" if index == 0 else ""
            selected = "true" if index == 0 else "false"
            tab_id = escape(tab.get("id", ""), quote=True)
            tab_title = escape(str(tab.get("title") or "Tab"))
            buttons.append(
                f'<button class="tab-button{active}" type="button" role="tab" aria-selected="{selected}" data-tab="{tab_id}">{tab_title}</button>'
            )
            panel = "\n".join(self._render_components(tab.get("children", [])))
            panels.append(
                f'<div class="tab-panel{active}" id="{tab_id}" role="tabpanel">{panel}</div>'
            )
        return f'<section class="component tabs" id="{id_attr}">{title}<div class="tab-buttons" role="tablist">{"".join(buttons)}</div><div class="tab-panels">{"".join(panels)}</div></section>'

    def _title(self, component):
        return str(component.get("title") or component.get("type") or "Item")
