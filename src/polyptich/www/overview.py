import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, redirect, request


ENDPOINT_SCHEMA = "polyptich.www.endpoint"
OVERVIEW_ENDPOINT_ID = "polyptich.overview-grid"


def _now():
    return datetime.now(timezone.utc).isoformat()


class OverviewGrid:
    def __init__(
        self,
        path,
        title=None,
        description=None,
        filters=None,
        sorts=None,
        page_size=24,
        overwrite=True,
        required_scope=None,
    ):
        self.path = Path(path)
        self.manifest_path = self.path / "manifest.json"
        self.items_path = self.path / "items.json"
        self.items = []

        if overwrite and self.path.exists():
            shutil.rmtree(self.path)
        self.path.mkdir(parents=True, exist_ok=True)

        self.manifest = {
            "schema": ENDPOINT_SCHEMA,
            "schema_version": 1,
            "endpoint_id": OVERVIEW_ENDPOINT_ID,
            "title": title or self.path.name,
            "description": description,
            "created_at": _now(),
            "updated_at": _now(),
            "data": "items.json",
            "filters": filters or [],
            "sorts": sorts or [],
            "page_size": page_size,
        }
        if required_scope is not None:
            self.manifest["required_scope"] = required_scope
        self.write()

    def add_item(self, title, href, description=None, media=None, badges=None, values=None, **extra):
        item = {
            "title": title,
            "href": href,
            "description": description,
            "media": media,
            "badges": badges or [],
            "values": values or {},
            **extra,
        }
        self.items.append(item)
        self.write()
        return item

    def write(self):
        self.manifest["updated_at"] = _now()
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2))
        self.items_path.write_text(json.dumps(self.items, indent=2))


class OverviewGridEndpoint:
    def __init__(self, path, mount_path, manifest):
        self.path = Path(path)
        self.mount_path = mount_path
        self.manifest = manifest
        self.data_path = self.path / manifest.get("data", "items.json")

    def register(self, app, mount_url, endpoint_name):
        app.add_url_rule(mount_url, endpoint_name + "_redirect", self.redirect_to_slash)
        app.add_url_rule(mount_url + "/", endpoint_name, self.index)
        app.add_url_rule(mount_url + "/items", endpoint_name + "_items", self.items)

    def redirect_to_slash(self):
        return redirect(request.path.rstrip("/") + "/")

    def index(self):
        title = _escape(self.manifest.get("title") or self.path.name)
        description = self.manifest.get("description")
        subtitle = f'<p class="subtitle">{_escape(description)}</p>' if description else ""
        config = json.dumps(
            {
                "title": self.manifest.get("title") or self.path.name,
                "filters": self.manifest.get("filters", []),
                "sorts": self.manifest.get("sorts", []),
                "pageSize": self.manifest.get("page_size", 24),
            }
        )
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="/static/polyptich-www.css">
</head>
<body>
  <main class="overview-shell">
    <header class="report-header">
      <h1>{title}</h1>
      {subtitle}
    </header>
    <section class="overview-controls" id="overview-controls"></section>
    <div class="overview-summary" id="overview-summary"></div>
    <section class="overview-grid" id="overview-grid"></section>
    <button class="www-button www-button-secondary overview-load" id="overview-load" type="button">Load more</button>
  </main>
  <script id="polyptich-overview-config" type="application/json">{config}</script>
  <script src="/static/polyptich-overview.js"></script>
</body>
</html>"""

    def items(self):
        items = self._load_items()
        items = self._filter_items(items)
        items = self._sort_items(items)
        total = len(items)
        limit = _int_arg("limit", self.manifest.get("page_size", 24))
        offset = _int_arg("offset", 0)
        return jsonify({"items": items[offset : offset + limit], "total": total, "offset": offset, "limit": limit})

    def _load_items(self):
        try:
            return json.loads(self.data_path.read_text())
        except FileNotFoundError:
            return []

    def _filter_items(self, items):
        query = request.args.get("q", "").strip().lower()
        filters = self.manifest.get("filters", [])
        if query:
            items = [item for item in items if query in json.dumps(item, sort_keys=True).lower()]
        for definition in filters:
            key = definition.get("key")
            if not key:
                continue
            kind = definition.get("type", "select")
            if kind == "range":
                minimum = request.args.get("min_" + key)
                maximum = request.args.get("max_" + key)
                if minimum not in {None, ""}:
                    items = [item for item in items if _number(_value(item, key)) >= float(minimum)]
                if maximum not in {None, ""}:
                    items = [item for item in items if _number(_value(item, key)) <= float(maximum)]
            else:
                value = request.args.get("f_" + key)
                if value:
                    items = [item for item in items if str(_value(item, key)) == value]
        return items

    def _sort_items(self, items):
        key = request.args.get("sort")
        if not key:
            return items
        reverse = request.args.get("order", "asc") == "desc"
        return sorted(items, key=lambda item: _sort_value(_value(item, key)), reverse=reverse)


def _value(item, key):
    if key in item:
        return item[key]
    return (item.get("values") or {}).get(key)


def _sort_value(value):
    if value is None:
        return (1, "")
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, str(value).lower())


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _int_arg(name, default):
    try:
        return max(0, int(request.args.get(name, default)))
    except (TypeError, ValueError):
        return default


def _escape(value):
    import html

    return html.escape(str(value), quote=True)
