import argparse
import ipaddress
import json
import os
import sys
from datetime import datetime
from html import escape
from importlib import metadata
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

from .auth import (
    REPORTS_READ,
    SERVICE_RESTART,
    AccessConfig,
    AccessVerificationError,
    CloudflareAccessVerifier,
    has_scope,
    require_scope,
    scopes_for_email,
)
from .page import SCHEMA

ENDPOINT_SCHEMA = "polyptich.www.endpoint"
ENDPOINT_SCHEMA_VERSION = 1
ENDPOINT_ENTRY_POINT_GROUP = "polyptich.www.endpoints"


def create_app(
    root=".",
    *,
    access_config=None,
    access_verifier=None,
    trusted_proxy=False,
    trusted_viewer_emails=(),
    operator_emails=(),
    endpoint_factories=None,
    external_origin=None,
    restart_callback=None,
):
    if access_verifier is None:
        if access_config is None:
            raise ValueError("Cloudflare Access configuration or an Access verifier is required")
        access_verifier = CloudflareAccessVerifier(access_config)

    workspace_root = Path(root).resolve()
    base_dir = (workspace_root / "www").resolve()
    external_origin = _validate_external_origin(external_origin)
    manifests = _read_initial_manifests(base_dir)

    app = Flask(__name__, static_folder=None)
    if trusted_proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_host=1,
            x_port=1,
            x_prefix=1,
            x_proto=1,
        )

    app.config.update(
        POLYPTICH_WWW_WORKSPACE_ROOT=workspace_root,
        POLYPTICH_WWW_ROOT_PATH=base_dir,
        POLYPTICH_WWW_EXTERNAL_ORIGIN=external_origin,
        POLYPTICH_WWW_RESTART_CALLBACK=restart_callback,
        POLYPTICH_WWW_ENDPOINT_PARENTS={},
        POLYPTICH_WWW_ENDPOINT_SCOPES={},
        POLYPTICH_WWW_SERVICE_RESTART_CONTROL=None,
    )

    def safe_path(subpath=""):
        target = (base_dir / subpath).resolve()
        if target != base_dir and base_dir not in target.parents:
            abort(403)
        if _has_symlink(base_dir, target):
            abort(403)
        return target

    def read_manifest(path):
        manifest_path = path / "manifest.json"
        if not path.is_dir() or not manifest_path.exists():
            return None
        return _read_manifest(manifest_path)

    def report_manifest(path):
        manifest = read_manifest(path)
        if manifest is None or manifest.get("schema") != SCHEMA:
            return None
        return manifest

    def endpoint_manifest(path):
        manifest = read_manifest(path)
        if manifest is None or manifest.get("schema") != ENDPOINT_SCHEMA:
            return None
        return manifest

    def path_scope(path):
        return _required_scope(base_dir, path)

    def report_asset(current, component):
        asset = (current / component["asset"]).resolve()
        if asset != current and current not in asset.parents:
            abort(403)
        if _has_symlink(current, asset):
            abort(403)
        return asset

    @app.before_request
    def authenticate_and_authorize():
        if request.endpoint in {"healthz", "readyz"}:
            return None
        token = request.headers.get("Cf-Access-Jwt-Assertion", "")
        try:
            identity = access_verifier.verify(token)
        except AccessVerificationError as error:
            return jsonify({"error": "access_denied", "message": str(error)}), 401
        g.polyptich_access_identity = identity
        g.polyptich_access_scopes = scopes_for_email(
            identity.email,
            trusted_viewer_emails=trusted_viewer_emails,
            operator_emails=operator_emails,
        )
        required = _endpoint_scope_for_request(
            app.config["POLYPTICH_WWW_ENDPOINT_SCOPES"],
            request.path,
            request.endpoint,
        )
        require_scope(required or REPORTS_READ)
        return None

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/readyz")
    def readyz():
        if not base_dir.is_dir():
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready"})

    @app.route("/")
    @app.route("/browse/")
    @app.route("/browse/<path:subpath>")
    def browse(subpath=""):
        current = safe_path(subpath)
        query = request.args.get("q", "").strip()
        if not current.is_dir():
            abort(404)
        require_scope(path_scope(current))

        manifest = report_manifest(current)
        if manifest is not None and request.args.get("browse") != "1":
            return render_report(subpath)
        endpoint = endpoint_manifest(current)
        if endpoint is not None and request.args.get("browse") != "1":
            return redirect(_endpoint_href(subpath))

        items = []
        for path in sorted(current.iterdir(), key=_sort_key):
            if path.is_symlink() or not has_scope(path_scope(path)):
                continue
            if query and query.lower() not in path.name.lower():
                continue
            rel = path.relative_to(base_dir).as_posix()
            item_manifest = report_manifest(path)
            item_endpoint = endpoint_manifest(path)
            is_dir = path.is_dir()
            is_html = path.is_file() and path.suffix.lower() == ".html"
            items.append(
                {
                    "name": path.name,
                    "path": rel,
                    "display_name": f"{path.name}/" if is_dir else path.name,
                    "is_dir": is_dir,
                    "is_report": item_manifest is not None or item_endpoint is not None,
                    "is_html": is_html,
                    "icon": _item_icon(item_manifest or item_endpoint, is_dir, is_html),
                    "kind": _item_kind(item_manifest, item_endpoint, is_dir, path),
                    "size": _format_size(None if is_dir else path.stat().st_size),
                    "modified": _format_mtime(path),
                    "href": _item_href(rel, item_manifest, item_endpoint, is_dir),
                    "browse_href": url_for("browse", subpath=rel, browse=1)
                    if item_manifest is not None or item_endpoint is not None
                    else None,
                }
            )

        parent = None
        if current != base_dir:
            parent = current.parent.relative_to(base_dir).as_posix()
        return render_template(
            "browser.html",
            items=items,
            subpath=subpath,
            parent=parent,
            breadcrumbs=_build_breadcrumbs(subpath),
            base_dir=base_dir,
            item_count=len(items),
            query=query,
            service_restart_control=(
                app.config["POLYPTICH_WWW_SERVICE_RESTART_CONTROL"]
                if has_scope(SERVICE_RESTART)
                else None
            ),
        )

    @app.route("/files/")
    @app.route("/files/<path:filename>")
    def download(filename=""):
        target = safe_path(filename)
        require_scope(path_scope(target))
        if target.is_dir():
            return browse(filename)
        if not target.exists():
            abort(404)
        return send_from_directory(base_dir, filename, as_attachment=False)

    @app.route("/report/<path:subpath>")
    def render_report(subpath):
        current = safe_path(subpath)
        require_scope(path_scope(current))
        manifest = report_manifest(current)
        if manifest is None:
            abort(404)
        html = current / "index.html"
        if not html.exists() or html.is_symlink():
            abort(404)
        base_href = url_for("download", filename=subpath.rstrip("/") + "/")
        content = html.read_text().replace("<head>", f'<head>\n  <base href="{base_href}">', 1)
        return app.response_class(content, mimetype="text/html")

    @app.route("/report-data/<path:subpath>/<component_id>")
    def report_data(subpath, component_id):
        current = safe_path(subpath)
        require_scope(path_scope(current))
        manifest = report_manifest(current)
        if manifest is None:
            abort(404)
        component = manifest.get("assets", {}).get(component_id)
        if component is None:
            abort(404)
        asset = report_asset(current, component)
        if component["type"] == "table":
            pd = _require_pandas()
            return jsonify(pd.read_parquet(asset).to_dict(orient="records"))
        if component["type"] == "plotly":
            return send_from_directory(
                base_dir,
                str(asset.relative_to(base_dir)),
                as_attachment=False,
            )
        abort(404)

    @app.route("/report-download/<path:subpath>/<component_id>.xlsx")
    def report_download(subpath, component_id):
        current = safe_path(subpath)
        require_scope(path_scope(current))
        manifest = report_manifest(current)
        if manifest is None:
            abort(404)
        component = manifest.get("assets", {}).get(component_id)
        if component is None or component.get("type") != "table":
            abort(404)
        pd = _require_pandas()
        asset = report_asset(current, component)
        output = BytesIO()
        pd.read_parquet(asset).to_excel(output, index=False)
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{component_id}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/static/<path:filename>")
    def static_files(filename):
        response = send_from_directory(
            Path(__file__).parent / "static", filename, as_attachment=False
        )
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.after_request
    def secure_response(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        if (
            response.status_code == 200
            and response.mimetype == "text/html"
            and not response.is_streamed
        ):
            parent = _endpoint_parent_for_request(
                app.config["POLYPTICH_WWW_ENDPOINT_PARENTS"], request.path
            )
            if parent is not None:
                parent_href = url_for("browse", subpath=parent) if parent else url_for("browse")
                parent_label = "/" + parent if parent else "/"
                banner = _endpoint_browser_banner(parent_href, parent_label)
                content = response.get_data(as_text=True)
                if "data-endpoint-browser-banner" not in content:
                    if "<body" in content:
                        marker = content.find(">", content.find("<body")) + 1
                        content = content[:marker] + "\n" + banner + content[marker:]
                    else:
                        content = banner + content
                    response.set_data(content)
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html", path=request.path, root_href=url_for("browse")), 404

    factories = _discover_endpoint_factories(endpoint_factories)
    _register_endpoint_manifests(app, base_dir, manifests, factories)
    return app


def register_service_restart_control(app, *, session_url, restart_url):
    control = {
        "session_url": _local_url(session_url, "session_url"),
        "restart_url": _local_url(restart_url, "restart_url"),
    }
    existing = app.config.get("POLYPTICH_WWW_SERVICE_RESTART_CONTROL")
    if existing is not None and existing != control:
        raise ValueError("A Polyptich service restart control is already registered")
    app.config["POLYPTICH_WWW_SERVICE_RESTART_CONTROL"] = control


def _local_url(value, name):
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        raise ValueError(f"Polyptich service restart {name} must be a local absolute URL")
    return value


def _read_initial_manifests(base_dir):
    if not base_dir.exists():
        return {}
    manifests = {}
    for manifest_path in sorted(base_dir.rglob("manifest.json")):
        manifest = _read_manifest(manifest_path)
        required_scope = manifest.get("required_scope")
        if required_scope is not None and (
            not isinstance(required_scope, str) or not required_scope.strip()
        ):
            raise ValueError(f"{manifest_path} has an invalid required_scope")
        manifests[manifest_path] = manifest
    return manifests


def _read_manifest(manifest_path):
    if manifest_path.is_symlink():
        raise ValueError(f"Manifest must not be a symlink: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read manifest {manifest_path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest {manifest_path} must contain a JSON object")
    return manifest


def _required_scope(base_dir, target):
    target = target.resolve()
    try:
        relative = target.relative_to(base_dir)
    except ValueError:
        abort(403)
    scope = REPORTS_READ
    current = base_dir
    folders = [base_dir]
    parts = relative.parts if target.is_dir() else relative.parts[:-1]
    for part in parts:
        current = current / part
        folders.append(current)
    for folder in folders:
        manifest_path = folder / "manifest.json"
        if manifest_path.exists():
            manifest = _read_manifest(manifest_path)
            required = manifest.get("required_scope")
            if required is not None:
                if not isinstance(required, str) or not required.strip():
                    abort(500, description=f"Invalid required_scope in {manifest_path}")
                scope = required
    return scope


def _discover_endpoint_factories(explicit):
    factories = {}
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        selected = entry_points.select(group=ENDPOINT_ENTRY_POINT_GROUP)
    else:
        selected = entry_points.get(ENDPOINT_ENTRY_POINT_GROUP, ())
    for entry_point in selected:
        if entry_point.name in factories:
            raise ValueError(f"Duplicate Polyptich WWW endpoint ID: {entry_point.name}")
        factories[entry_point.name] = entry_point.load()
    factories.update(explicit or {})
    return factories


def _register_endpoint_manifests(app, base_dir, manifests, factories):
    endpoint_index = 0
    for manifest_path, manifest in manifests.items():
        if manifest.get("schema") != ENDPOINT_SCHEMA:
            continue
        if manifest.get("schema_version") != ENDPOINT_SCHEMA_VERSION:
            raise ValueError(
                f"{manifest_path} must use {ENDPOINT_SCHEMA} schema_version "
                f"{ENDPOINT_SCHEMA_VERSION}"
            )
        if "handler" in manifest:
            raise ValueError(
                f"{manifest_path} uses unsupported handler imports; use endpoint_id instead"
            )
        endpoint_id = manifest.get("endpoint_id")
        if not isinstance(endpoint_id, str) or not endpoint_id.strip():
            raise ValueError(f"{manifest_path} is missing a stable endpoint_id")
        factory = factories.get(endpoint_id)
        if factory is None:
            raise ValueError(
                f"Unknown Polyptich WWW endpoint ID {endpoint_id!r} in {manifest_path}; "
                f"install an entry point in {ENDPOINT_ENTRY_POINT_GROUP!r}"
            )
        path = manifest_path.parent
        rel = path.relative_to(base_dir).as_posix()
        parent = path.parent.relative_to(base_dir).as_posix()
        if parent == ".":
            parent = ""
        endpoint_index += 1
        endpoint_name = f"polyptich_www_endpoint_{endpoint_index}"
        mount_url = _endpoint_href(rel).rstrip("/")
        scope = _required_scope(base_dir, path)
        app.config["POLYPTICH_WWW_ENDPOINT_PARENTS"][_endpoint_href(rel)] = parent
        app.config["POLYPTICH_WWW_ENDPOINT_SCOPES"][endpoint_name] = (mount_url, scope)
        endpoint = factory(path=path, mount_path=rel, manifest=manifest)
        endpoint.register(app, mount_url=mount_url, endpoint_name=endpoint_name)


def _endpoint_scope_for_request(endpoint_scopes, request_path, endpoint_name):
    for name, (prefix, scope) in endpoint_scopes.items():
        if endpoint_name and (endpoint_name == name or endpoint_name.startswith(name + "_")):
            return scope
        if request_path == prefix or request_path.startswith(prefix + "/"):
            return scope
    return None


def _validate_external_origin(origin):
    if origin is None:
        return None
    normalized = origin.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise ValueError("External origin must be an HTTPS origin without a path")
    return normalized


def _validate_loopback(host):
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("Polyptich WWW requires a literal loopback host") from error
    if not address.is_loopback:
        raise ValueError("Polyptich WWW requires a literal loopback host")


def _has_symlink(base_dir, target):
    try:
        relative = target.relative_to(base_dir)
    except ValueError:
        return True
    current = base_dir
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _sort_key(path):
    manifest = path / "manifest.json"
    is_report = path.is_dir() and manifest.exists()
    return (
        not is_report,
        not path.is_dir(),
        0 if path.suffix.lower() == ".html" else 1,
        path.name.lower(),
    )


def _item_icon(manifest, is_dir, is_html):
    if manifest is not None:
        return "report"
    if is_dir:
        return "folder"
    if is_html:
        return "html"
    return "file"


def _item_kind(manifest, endpoint, is_dir, path):
    if manifest is not None:
        return "polyptich report"
    if endpoint is not None:
        return "polyptich endpoint"
    if is_dir:
        return "directory"
    return path.suffix.lower().lstrip(".") or "file"


def _item_href(rel, manifest, endpoint, is_dir):
    if manifest is not None:
        return url_for("render_report", subpath=rel)
    if endpoint is not None:
        return _endpoint_href(rel)
    if is_dir:
        return url_for("browse", subpath=rel)
    return url_for("download", filename=rel)


def _endpoint_href(rel):
    return "/endpoint/" + rel.strip("/") + "/"


def _endpoint_parent_for_request(endpoint_parents, request_path):
    path = request_path if request_path.endswith("/") else request_path + "/"
    for prefix, parent in sorted(
        endpoint_parents.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if path.startswith(prefix):
            return parent
    return None


def _endpoint_browser_banner(parent_href, parent_label):
    return f"""<details class="endpoint-browser-banner" data-endpoint-browser-banner>
  <summary>Endpoint navigation</summary>
  <div class="endpoint-browser-banner-body">
    <span>Parent folder <code>{escape(parent_label)}</code></span>
    <a class="www-button www-button-secondary" href="{escape(parent_href, quote=True)}">Open in file browser</a>
  </div>
</details>"""


def _format_size(size):
    if size is None:
        return "directory"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _format_mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _build_breadcrumbs(subpath):
    breadcrumbs = [{"label": "www", "path": ""}]
    current_parts = []
    for part in Path(subpath).parts:
        if part in {"", "."}:
            continue
        current_parts.append(part)
        breadcrumbs.append({"label": part, "path": "/".join(current_parts)})
    return breadcrumbs


def _require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Install pandas to serve Polyptich WWW tables") from exc
    return pd


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve a secured Polyptich WWW directory.")
    parser.add_argument("--root", default=".", help="Workspace directory containing www/")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5002")))
    parser.add_argument("--trusted-proxy", action="store_true")
    parser.add_argument("--access-issuer", required=True)
    parser.add_argument("--access-audience", required=True)
    parser.add_argument("--trusted-viewer-email", action="append", default=[])
    parser.add_argument("--operator-email", action="append", default=[])
    parser.add_argument("--external-origin")
    args = parser.parse_args(argv)

    _validate_loopback(args.host)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    access_config = AccessConfig(issuer=args.access_issuer, audience=args.access_audience)
    app = create_app(
        args.root,
        access_config=access_config,
        trusted_proxy=args.trusted_proxy,
        trusted_viewer_emails=args.trusted_viewer_email,
        operator_emails=args.operator_email,
        external_origin=args.external_origin,
    )
    from waitress import serve

    serve(app, host=args.host, port=args.port, threads=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
