"""Add `sources` to parameter files from a JSON map {parameter id: [source, ...]} (schema 0.5).

The block is appended to each file as YAML; a file that already has `sources` is left alone and reported.

    python tools/add_sources.py datasets/vitaldb sources.json
"""

import json
import sys
from pathlib import Path

import yaml


def main() -> None:
    ds, src = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    for pid, sources in src.items():
        f = ds / "parameters" / f"{pid}.yaml"
        text = f.read_text(encoding="utf-8")
        if "sources" in (yaml.safe_load(text) or {}):
            print(f"{pid}: has sources already, left alone")
            continue
        block = yaml.safe_dump({"sources": sources}, sort_keys=False, allow_unicode=True, width=120)
        f.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8")
        print(f"{pid}: {len(sources)} source(s)")


if __name__ == "__main__":
    main()
