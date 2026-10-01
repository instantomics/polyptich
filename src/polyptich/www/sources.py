"""Read-only source mounts with stable WWW-relative paths.

URL paths stay in the publication tree; only file reads resolve into a source
tree. This lets navigation and scope inheritance use the same paths as reports.
"""

import json
import os
from pathlib import Path


class SourceTree:
    def __init__(self, workspace, root, *, reports=()):
        self.root = root
        self.mounts = {}
        self.reports = tuple(reports)
        declaration = root / "sources.json"
        if declaration.exists():
            if declaration.is_symlink():
                raise ValueError("sources.json must not be a symlink")
            value = json.loads(declaration.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema") != "polyptich.www.sources"
                or value.get("schema_version") != 1
                or set(value) != {"schema", "schema_version", "mounts"}
                or not isinstance(value["mounts"], dict)
            ):
                raise ValueError("Invalid Polyptich source declaration")
            for relative, source in value["mounts"].items():
                path = Path(relative)
                if (
                    not relative
                    or path.is_absolute()
                    or path.as_posix() != relative
                    or any(part.startswith(".") for part in path.parts)
                    or relative in {"sources.json", "sidebar.json", "navigation.json"}
                    or not isinstance(source, str)
                    or not source
                ):
                    raise ValueError(f"Invalid source mount: {relative!r}")
                target = (workspace / source).resolve()
                if target == root or root in target.parents or target in root.parents:
                    raise ValueError("Source mounts must not overlap the publication root")
                self.mounts[root / path] = target
            for left in self.mounts:
                if any(left in right.parents for right in self.mounts):
                    raise ValueError("Source mounts must not overlap each other")

    def path(self, logical):
        return SourcePath(self, Path(logical))

    def mount(self, logical):
        if any(logical == report or report in logical.parents for report in self.reports):
            return None
        for mount, source in self.mounts.items():
            if logical == mount or mount in logical.parents:
                return mount, source
        return None

    def children(self, logical):
        for path in (*self.mounts, *self.reports):
            if logical in path.parents:
                yield path.relative_to(logical).parts[0]

    def physical(self, logical):
        relative = logical.relative_to(self.root)
        if ".." in relative.parts:
            raise PermissionError("Path escapes publication root")
        mount = self.mount(logical)
        # Presentation metadata belongs to www, even for a source-backed folder.
        if logical.name == "sidebar.json" and logical.is_file():
            mount = None
        if mount is None:
            boundary, target = self.root, logical
        else:
            boundary, source = mount
            suffix = logical.relative_to(boundary)
            if any(part.startswith(".") or part == "__pycache__" for part in suffix.parts):
                raise PermissionError("Hidden source paths are not published")
            target = source / suffix
            boundary = source
        current = target
        while current != boundary:
            if current.is_symlink():
                raise PermissionError("Symlinks inside a publication are not supported")
            current = current.parent
        if boundary.is_symlink():
            raise PermissionError("Source root was replaced by a symlink")
        return target


class SourcePath(os.PathLike):
    """A logical publication path whose reads use an explicitly mounted source."""

    def __init__(self, tree, logical):
        self.tree = tree
        self.logical = logical

    def __fspath__(self):
        return str(self.logical)

    def __str__(self):
        return str(self.logical)

    def __hash__(self):
        return hash(self.logical)

    def __eq__(self, other):
        return isinstance(other, (SourcePath, Path)) and self.logical == Path(other)

    def __lt__(self, other):
        return self.logical < Path(other)

    def __truediv__(self, other):
        return self.tree.path(self.logical / other)

    @property
    def parent(self):
        return self.tree.path(self.logical.parent)

    @property
    def parents(self):
        return tuple(self.tree.path(path) for path in self.logical.parents)

    @property
    def name(self):
        return self.logical.name

    @property
    def suffix(self):
        return self.logical.suffix

    @property
    def physical(self):
        return self.tree.physical(self.logical)

    @property
    def source_backed(self):
        return self.tree.mount(self.logical) is not None

    def resolve(self):
        # Do not turn a URL path into a source path during scope/navigation checks.
        return self.tree.path(Path(os.path.abspath(self.logical)))

    def relative_to(self, other):
        return self.logical.relative_to(Path(other))

    def joinpath(self, *parts):
        return self.tree.path(self.logical.joinpath(*parts))

    def is_symlink(self):
        try:
            self.tree.physical(self.logical)
        except PermissionError:
            return True
        return False

    def exists(self):
        return self.physical.exists() or any(self.tree.children(self.logical))

    def is_file(self):
        return self.physical.is_file()

    def is_dir(self):
        return self.physical.is_dir() or any(self.tree.children(self.logical))

    def stat(self):
        if not self.physical.exists() and any(self.tree.children(self.logical)):
            return self.tree.root.stat()
        return self.physical.stat()

    def read_text(self, *args, **kwargs):
        return self.physical.read_text(*args, **kwargs)

    def read_bytes(self):
        return self.physical.read_bytes()

    def iterdir(self):
        names = {path.name for path in self.physical.iterdir()} if self.physical.is_dir() else set()
        names.update(self.tree.children(self.logical))
        for name in sorted(names):
            child = self / name
            if not child.is_symlink() and child.exists():
                yield child

    def open(self, *args, **kwargs):
        if self.source_backed:
            raise PermissionError("Source-backed files are read-only")
        return self.physical.open(*args, **kwargs)

    def unlink(self, *args, **kwargs):
        if self.source_backed:
            raise PermissionError("Source-backed files are read-only")
        return self.physical.unlink(*args, **kwargs)


def physical_path(path):
    return path.physical if isinstance(path, SourcePath) else path


def source_backed(path):
    return isinstance(path, SourcePath) and path.source_backed
