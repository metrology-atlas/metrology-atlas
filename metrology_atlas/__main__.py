"""Command line: check a dataset, compile its JSON, write its site.

    python -m metrology_atlas check datasets/vitaldb
    python -m metrology_atlas json  datasets/vitaldb --out build/vitaldb.metrology.json
    python -m metrology_atlas site  datasets/vitaldb --out build/vitaldb      (then: zensical build in that folder)
    add --release to json/site for the public build: links into repositories that are not public are left out
"""

from __future__ import annotations

import argparse
import sys

from metrology_atlas.compile import write_json
from metrology_atlas.load import AtlasError, load
from metrology_atlas.site import write_site


def todo(ds) -> str:
    """Maintainer's list of gaps, for the work plan; never published on the site."""
    out = []
    bare = sorted((st["name"], i) for i, st in ds.items["study"].items()
                  if st.get("status") not in ("superseded", "withdrawn")
                  and (not st.get("figures") or all(f.get("placeholder") for f in st["figures"])))
    out.append(f"Studies without a figure ({len(bare)} of {len(ds.items['study'])}):")
    out += [f"  - {name} ({i})" for name, i in bare]
    planned = sorted((e["name"], i, e["status"]) for i, e in ds.items.get("example", {}).items() if e["status"] != "current")
    out.append(f"Worked examples not yet current ({len(planned)}):")
    out += [f"  - {name} ({i}): {st}" for name, i, st in planned]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """Command line: check, json, site or todo for a dataset folder; returns the exit code."""
    ap = argparse.ArgumentParser(prog="metrology-atlas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "json", "site", "todo"):
        p = sub.add_parser(name)
        p.add_argument("dataset")
        if name not in ("check", "todo"):
            p.add_argument("--out", required=True)
        if name in ("json", "site"):
            p.add_argument("--release", action="store_true",
                           help="public build: software that is not public is shown as not yet released, unlinked")
    a = ap.parse_args(argv)
    try:
        ds = load(a.dataset)
    except AtlasError as error:
        print(error, file=sys.stderr)
        return 1
    for w in ds.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if getattr(a, "release", False):
        for w in ds.items.get("software", {}).values():
            if w.get("visibility") in ("private", "unpublished"):
                w.pop("repo", None)
                w["visibility"] = "not yet released"
    counts = ", ".join(f"{len(v)} {k}" for k, v in ds.items.items() if v)
    if a.cmd == "check":
        print(f"ok: {counts}")
    elif a.cmd == "todo":
        print(todo(ds))
    elif a.cmd == "json":
        print(f"wrote {write_json(ds, a.out)} ({counts})")
    else:
        print(f"wrote {write_site(ds, a.out)} ({counts}); build it with: zensical build (in that folder)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
