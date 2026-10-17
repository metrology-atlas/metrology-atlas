"""Command line: check a dataset, compile its JSON, write its site.

    python -m metrology_atlas check datasets/vitaldb
    python -m metrology_atlas json  datasets/vitaldb --out build/vitaldb.metrology.json
    python -m metrology_atlas site  datasets/vitaldb --out build/vitaldb      (then: zensical build in that folder)
"""

from __future__ import annotations

import argparse
import sys

from metrology_atlas.compile import write_json
from metrology_atlas.load import AtlasError, load
from metrology_atlas.site import write_site


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="metrology-atlas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "json", "site"):
        p = sub.add_parser(name)
        p.add_argument("dataset")
        if name != "check":
            p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        ds = load(a.dataset)
    except AtlasError as error:
        print(error, file=sys.stderr)
        return 1
    for w in ds.warnings:
        print(f"warning: {w}", file=sys.stderr)
    counts = ", ".join(f"{len(v)} {k}" for k, v in ds.items.items() if v)
    if a.cmd == "check":
        print(f"ok: {counts}")
    elif a.cmd == "json":
        print(f"wrote {write_json(ds, a.out)} ({counts})")
    else:
        print(f"wrote {write_site(ds, a.out)} ({counts}); build it with: zensical build (in that folder)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
