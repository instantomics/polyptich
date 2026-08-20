# ruff: noqa: TRY004 -- malformed persisted declarations consistently raise ValueError.

import json
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

SCHEMA = "polyptich.www.navigation"
SCHEMA_VERSION = 1
COLLECTION_SCHEMA = "polyptich.www.navigation.collection"
COLLECTION_SCHEMA_VERSION = 1

_NODE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
NAVIGATION_ICONS = frozenset(
    {
        "home",
        "collection",
        "database",
        "chart",
        "play",
        "question",
        "history",
        "folder",
        "document",
        "agent",
        "tasks",
        "sources",
        "task",
        "overview",
        "evidence",
        "metrics",
        "examples",
        "releases",
        "release",
    }
)
_NODE_KEYS = {"id", "label", "type", "href", "children", "favorite", "collection", "icon"}
_COLLECTION_KEYS = {"type", "path", "href", "placeholder", "favorites"}
_HIDDEN_NAMES = {"assets", ".assets", "manifest.json", "navigation.json"}


def load_navigation(base_dir, manifests):
    """Load, validate, and assemble the global declaration and endpoint contributions."""
    navigation_path = base_dir / "navigation.json"
    if navigation_path.exists():
        declaration = _read_json_object(navigation_path)
        _validate_declaration(declaration, navigation_path)
    else:
        declaration = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "title": "Navigation",
            "items": [],
        }

    ids = {}
    items = [
        _validate_node(item, navigation_path, ids, base_dir=base_dir, mount_url=None, scope=None)
        for item in declaration["items"]
    ]
    parent_of = {}
    _record_existing_parents(items, parent_of)
    contributions = []

    for manifest_path, manifest in manifests.items():
        contribution = manifest.get("navigation")
        if contribution is None:
            continue
        if manifest.get("schema") != "polyptich.www.endpoint":
            raise ValueError(f"{manifest_path} navigation is only supported for endpoint manifests")
        if not isinstance(contribution, dict) or set(contribution) != {"parent_id", "items"}:
            raise ValueError(f"{manifest_path} navigation must contain only parent_id and items")
        parent_id = contribution.get("parent_id")
        contributed = contribution.get("items")
        if not isinstance(parent_id, str) or not _NODE_ID.fullmatch(parent_id):
            raise ValueError(f"{manifest_path} navigation parent_id is invalid")
        if not isinstance(contributed, list):
            raise ValueError(f"{manifest_path} navigation items must be a list")
        endpoint_path = manifest_path.parent
        mount = endpoint_path.relative_to(base_dir).as_posix()
        mount_url = "/endpoint/" + mount.strip("/") + "/"
        scope = _required_scope_value(base_dir, endpoint_path)
        nodes = [
            _validate_node(
                item,
                manifest_path,
                ids,
                base_dir=base_dir,
                mount_url=mount_url,
                scope=scope,
                inherited_path=endpoint_path,
            )
            for item in contributed
        ]
        _record_existing_parents(nodes, parent_of)
        contributions.append((manifest_path, parent_id, nodes))

    for manifest_path, parent_id, nodes in contributions:
        if parent_id not in ids:
            raise ValueError(f"{manifest_path} navigation has unknown parent_id {parent_id!r}")
        for node in nodes:
            parent_of[node["id"]] = parent_id
    _reject_parent_cycles(parent_of)
    for _manifest_path, parent_id, nodes in contributions:
        ids[parent_id].setdefault("children", []).extend(nodes)

    endpoint_paths = []
    for manifest_path, manifest in manifests.items():
        if manifest.get("schema") == "polyptich.www.endpoint":
            path = manifest_path.parent
            endpoint_paths.append(("/endpoint/" + path.relative_to(base_dir).as_posix(), path))
    for node in items:
        _assign_paths(node, base_dir, endpoint_paths)

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "title": declaration["title"],
        "items": items,
        "nodes": ids,
    }


def serialize_navigation(navigation, *, can_access, collection_href, script_root=""):
    items = []
    for node in navigation["items"]:
        serialized = _serialize_node(
            node,
            can_access=can_access,
            collection_href=collection_href,
            script_root=script_root,
        )
        if serialized is not None:
            items.append(serialized)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "title": navigation["title"],
        "items": items,
    }


def serialize_service_restart_action(control, *, health_url, script_root=""):
    return {
        "id": "service.restart",
        "type": "service_restart",
        "label": "Restart server",
        "session_url": prefix_local_url(control["session_url"], script_root),
        "restart_url": prefix_local_url(control["restart_url"], script_root),
        "health_url": health_url,
    }


def is_hidden_name(name):
    return name.startswith(".") or name.casefold() in _HIDDEN_NAMES


def directory_has_navigation_content(path, *, can_access=lambda _path: True):
    """Return whether a non-index directory contains a navigable document."""
    if not path.is_dir() or path.is_symlink():
        return False
    for name in ("index.html", "index.htm"):
        index = path / name
        if index.is_file() and not index.is_symlink():
            return True
    manifest = path / "manifest.json"
    if manifest.is_file() and not manifest.is_symlink():
        try:
            schema = json.loads(manifest.read_text()).get("schema")
        except (AttributeError, OSError, json.JSONDecodeError):
            schema = None
        if schema == "polyptich.www.endpoint":
            return True
    try:
        children = path.iterdir()
    except OSError:
        return False
    for child in children:
        if child.is_symlink() or is_hidden_name(child.name):
            continue
        if not can_access(child):
            continue
        if child.is_file() and child.suffix.casefold() in {".html", ".htm"}:
            return True
        if child.is_dir() and directory_has_navigation_content(child, can_access=can_access):
            return True
    return False


def _validate_declaration(value, path):
    allowed = {"schema", "schema_version", "title", "items"}
    if set(value) != allowed:
        raise ValueError(f"{path} must contain exactly schema, schema_version, title, and items")
    if value.get("schema") != SCHEMA or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path} must use {SCHEMA} schema_version {SCHEMA_VERSION}")
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        raise ValueError(f"{path} title must be a non-empty string")
    if not isinstance(value.get("items"), list):
        raise ValueError(f"{path} items must be a list")


def _validate_node(
    value,
    source,
    ids,
    *,
    base_dir,
    mount_url,
    scope,
    inherited_path=None,
):
    if not isinstance(value, dict) or not set(value).issubset(_NODE_KEYS):
        raise ValueError(f"{source} contains a malformed navigation node")
    node_id = value.get("id")
    label = value.get("label")
    node_type = value.get("type")
    if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
        raise ValueError(f"{source} contains an invalid navigation node ID")
    if node_id in ids:
        raise ValueError(f"Duplicate navigation node ID: {node_id!r}")
    if not isinstance(label, str) or not label.strip() or len(label) > 200:
        raise ValueError(f"Navigation node {node_id!r} has an invalid label")
    if node_type not in {"section", "page", "collection"}:
        raise ValueError(f"Navigation node {node_id!r} has an invalid type")
    favorite = value.get("favorite", False)
    if type(favorite) is not bool:
        raise ValueError(f"Navigation node {node_id!r} favorite must be a boolean")
    icon = value.get("icon")
    if "icon" in value and icon not in NAVIGATION_ICONS:
        raise ValueError(f"Navigation node {node_id!r} has an invalid icon")
    href = value.get("href")
    if href is not None:
        href = _normalize_href(href, mount_url=mount_url)
    if node_type == "page" and href is None:
        raise ValueError(f"Navigation page {node_id!r} requires href")
    if node_type != "collection" and "collection" in value:
        raise ValueError(f"Navigation node {node_id!r} cannot define collection")
    collection = None
    if node_type == "collection":
        collection = _validate_collection(
            value.get("collection"), node_id, source, base_dir=base_dir, mount_url=mount_url
        )
    children = value.get("children", [])
    if not isinstance(children, list):
        raise ValueError(f"Navigation node {node_id!r} children must be a list")

    node = {"id": node_id, "label": label.strip(), "type": node_type}
    ids[node_id] = node
    if href is not None:
        node["href"] = href
    if favorite:
        node["favorite"] = True
    if "icon" in value:
        node["icon"] = icon
    if collection is not None:
        node["collection"] = collection
    if scope is not None:
        node["_scope"] = scope
    if inherited_path is not None:
        node["_contributor_path"] = inherited_path
    node["children"] = [
        _validate_node(
            child,
            source,
            ids,
            base_dir=base_dir,
            mount_url=mount_url,
            scope=scope,
            inherited_path=inherited_path,
        )
        for child in children
    ]
    return node


def _validate_collection(value, node_id, source, *, base_dir, mount_url):
    if not isinstance(value, dict) or not set(value).issubset(_COLLECTION_KEYS):
        raise ValueError(f"Navigation collection {node_id!r} in {source} is malformed")
    collection_type = value.get("type")
    placeholder = value.get("placeholder")
    if placeholder is not None and (
        not isinstance(placeholder, str)
        or not placeholder.strip()
        or len(placeholder) > 200
    ):
        raise ValueError(f"Navigation collection {node_id!r} has an invalid placeholder")
    if collection_type == "directory":
        if mount_url is not None or set(value) - {"type", "path", "placeholder", "favorites"}:
            raise ValueError(f"Navigation collection {node_id!r} has invalid directory options")
        path_value = _safe_relative_path(value.get("path"), f"collection {node_id!r} path")
        favorites = value.get("favorites", [])
        if not isinstance(favorites, list) or any(
            not isinstance(item, str)
            or not item
            or "/" in item
            or "\\" in item
            or is_hidden_name(item)
            for item in favorites
        ):
            raise ValueError(f"Navigation collection {node_id!r} favorites are invalid")
        if len(set(favorites)) != len(favorites):
            raise ValueError(f"Navigation collection {node_id!r} favorites must be unique")
        target = (base_dir / path_value).resolve()
        if target != base_dir and base_dir not in target.parents:
            raise ValueError(f"Navigation collection {node_id!r} escapes www")
        collection = {
            "type": "directory",
            "path": path_value,
            "favorites": favorites,
        }
        if placeholder is not None:
            collection["placeholder"] = placeholder.strip()
        return collection
    if collection_type == "endpoint":
        if set(value) - {"type", "href", "placeholder"}:
            raise ValueError(f"Navigation collection {node_id!r} has invalid endpoint options")
        href = _normalize_href(value.get("href"), mount_url=mount_url)
        if mount_url is None and not urlsplit(href).path.startswith("/endpoint/"):
            raise ValueError(
                f"Navigation collection {node_id!r} must use a local endpoint href"
            )
        collection = {
            "type": "endpoint",
            "href": href,
        }
        if placeholder is not None:
            collection["placeholder"] = placeholder.strip()
        return collection
    raise ValueError(f"Navigation collection {node_id!r} has an invalid type")


def _normalize_href(value, *, mount_url):
    if not isinstance(value, str) or not value or len(value) > 2048 or "\\" in value:
        raise ValueError("Navigation href must be a non-empty local URL")
    if any(ord(character) < 32 for character in value):
        raise ValueError("Navigation href must not contain control characters")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        raise ValueError(f"Navigation href must be same-origin: {value!r}")
    decoded_parts = PurePosixPath(unquote(parsed.path)).parts
    if ".." in decoded_parts:
        raise ValueError(f"Navigation href must not traverse: {value!r}")
    base = mount_url or "/"
    normalized = urljoin(base, value)
    if mount_url is not None:
        normalized_path = urlsplit(normalized).path
        if normalized_path != mount_url.rstrip("/") and not normalized_path.startswith(mount_url):
            raise ValueError(f"Endpoint navigation href escapes its mount: {value!r}")
    return normalized


def _safe_relative_path(value, label):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"Navigation {label} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Navigation {label} must not traverse")
    return path.as_posix()


def _serialize_node(node, *, can_access, collection_href, script_root):
    if not can_access(node):
        return None
    children = []
    for child in node.get("children", []):
        serialized = _serialize_node(
            child,
            can_access=can_access,
            collection_href=collection_href,
            script_root=script_root,
        )
        if serialized is not None:
            children.append(serialized)
    if node["type"] == "section" and node.get("children") and not children:
        return None
    result = {key: node[key] for key in ("id", "label", "type")}
    if "icon" in node:
        result["icon"] = node["icon"]
    if "href" in node:
        result["href"] = prefix_local_url(node["href"], script_root)
    if node.get("favorite"):
        result["favorite"] = True
    if children:
        result["children"] = children
    collection = node.get("collection")
    if collection is not None:
        if collection["type"] == "directory":
            href = collection_href(node["id"])
        else:
            href = prefix_local_url(collection["href"], script_root)
        result["collection"] = {
            "type": collection["type"],
            "href": href,
        }
        if "placeholder" in collection:
            result["collection"]["placeholder"] = collection["placeholder"]
    return result


def prefix_local_url(value, script_root):
    if not script_root:
        return value
    if value == script_root or value.startswith(script_root + "/"):
        return value
    return script_root.rstrip("/") + value


def _assign_paths(node, base_dir, endpoint_paths):
    collection = node.get("collection")
    if collection is not None and collection["type"] == "directory":
        node["_collection_path"] = (base_dir / collection["path"]).resolve()
    elif collection is not None and collection["type"] == "endpoint":
        node["_collection_path"] = _path_for_href(collection["href"], base_dir, endpoint_paths)
        if node["_collection_path"] is None:
            raise ValueError(
                f"Navigation collection {node['id']!r} does not target a registered endpoint"
            )
    if "href" in node:
        node["_path"] = _path_for_href(node["href"], base_dir, endpoint_paths)
    for child in node.get("children", []):
        _assign_paths(child, base_dir, endpoint_paths)


def _path_for_href(href, base_dir, endpoint_paths):
    path = urlsplit(href).path
    for prefix in ("/files/", "/browse/", "/report/"):
        if path.startswith(prefix):
            return (base_dir / unquote(path[len(prefix) :])).resolve()
    if path in {"/", "/browse", "/browse/", "/files", "/files/"}:
        return base_dir
    for prefix, endpoint_path in sorted(
        endpoint_paths, key=lambda item: len(item[0]), reverse=True
    ):
        if path == prefix or path.startswith(prefix + "/"):
            return endpoint_path
    return None


def _required_scope_value(base_dir, target):
    scope = "dashboard.read"
    relative = target.resolve().relative_to(base_dir)
    current = base_dir
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        manifest_path = current / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = _read_json_object(manifest_path)
        required = manifest.get("required_scope")
        if required is not None:
            if not isinstance(required, str) or not required.strip():
                raise ValueError(f"{manifest_path} has an invalid required_scope")
            scope = required
    return scope


def _record_existing_parents(nodes, parent_of, parent=None):
    for node in nodes:
        if parent is not None:
            parent_of[node["id"]] = parent
        _record_existing_parents(node.get("children", []), parent_of, node["id"])


def _reject_parent_cycles(parent_of):
    for start in parent_of:
        seen = set()
        current = start
        while current in parent_of:
            if current in seen:
                raise ValueError("Endpoint navigation contributions contain a parent cycle")
            seen.add(current)
            current = parent_of[current]


def _read_json_object(path):
    if path.is_symlink():
        raise ValueError(f"Navigation metadata must not be a symlink: {path}")
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read navigation metadata {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Navigation metadata {path} must contain a JSON object")
    return value
