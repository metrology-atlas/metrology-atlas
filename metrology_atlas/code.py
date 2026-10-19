"""Code references: ``software-id/path`` in a study's ``code`` list, or ``[[code:software-id/path|label]]`` in prose.

The first path segment names a software item; the rest is a path inside its repository. A software item with a
``repo`` turns each path into a link to that file on its branch. With a ``local`` copy present, the checker also
confirms that each path exists, and warns about files the copy's git does not track yet (their links fail until
they are committed and pushed).
"""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path

CODE_XREF = re.compile(r"\[\[code:([^\]|\s]+)(?:\|([^\]]+))?\]\]")


def split(ref: str) -> tuple[str, str]:
    """``'vitaldb-bench/tools/x.py'`` -> ``('vitaldb-bench', 'tools/x.py')``."""
    sw, _, path = ref.partition("/")
    return sw, path


def local_root(ds, sw: dict) -> Path | None:
    """The local checkout of a software item (its `local` path, relative to the dataset folder), if it exists."""
    if not sw.get("local"):
        return None
    root = (Path(ds.folder) / sw["local"]).resolve()
    return root if root.is_dir() else None


@cache
def _tracked(root: str) -> frozenset[str] | None:
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return frozenset(p for p in out.stdout.decode("utf-8", "replace").split("\0") if p)


def code_url(ds, ref: str) -> str | None:
    """Web address of a code reference, or None when its software has no published repository."""
    name, path = split(ref)
    sw = ds.get("software", name)
    if not sw or not sw.get("repo"):
        return None
    base = sw["repo"].rstrip("/").removesuffix(".git")
    if not path:
        return base
    root = local_root(ds, sw)
    is_dir = path.endswith("/") or bool(root and (root / path.rstrip("/")).is_dir())
    return f"{base}/{'tree' if is_dir else 'blob'}/{sw.get('branch') or 'main'}/{path.rstrip('/')}"


def check_code(ds, ref: str, where: str, problems: list[str], warnings: list[str]) -> None:
    """Check one `software-id/path` code reference: known software, path present in the local checkout, committed;
    appends to problems or warnings.
    """
    name, path = split(ref)
    sw = ds.get("software", name)
    if sw is None:
        problems.append(f"{where}: code '{ref}': '{name}' is not a known software item")
        return
    root = local_root(ds, sw)
    if root is None or not path:
        return
    target = root / path.rstrip("/")
    if not target.exists():
        problems.append(f"{where}: code '{ref}': {path} is not in the local copy of {name} ({root})")
        return
    tracked = _tracked(str(root))
    if tracked is None or not sw.get("repo"):
        return
    p = path.rstrip("/")
    if p not in tracked and not any(t.startswith(p + "/") for t in tracked):
        warnings.append(f"{where}: code '{ref}' is not committed in {name} yet; its link will fail until it is pushed")


def snapshot_path(ds, ref: str) -> Path | None:
    """Where a code reference's file sits in the dataset's pinned snapshot of its software, if it has one."""
    name, path = split(ref)
    for src in ds.meta.get("sources") or []:
        if src.get("software") == name:
            return Path(ds.folder) / src["folder"] / path
    return None


def source_of(ds, ref: str) -> dict | None:
    """The pinned snapshot entry in dataset.yaml `sources` for the software a code reference names, if any."""
    name, _ = split(ref)
    return next((s for s in ds.meta.get("sources") or [] if s.get("software") == name), None)
