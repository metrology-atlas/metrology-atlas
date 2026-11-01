"""List numbers a study types that equal one of its own parameters' values, with context, for migration to
[[value:id]].

    python tools/value_hits.py datasets/vitaldb [--study ID] [--json hits.json]

Each hit: study, field path, the parameter, the typed text, whether the parameter's unit follows the number (a strong
sign it is the same quantity), and 60 characters either side. Nothing is changed: tools/apply_values.py rewrites only
the hits listed in a reviewed JSON file.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrology_atlas import load  # noqa: E402
from metrology_atlas.values import _NUMBER, _SKIP, _parse, unit_follows, written_decimals  # noqa: E402


def walk(v, path=""):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            if k not in {"id", "name"}:
                yield from walk(x, f"{path}.{k}" if path else k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk(x, f"{path}[{i}]")


def hits(ds, only=None):
    own = defaultdict(dict)
    for pid, p in ds.items["parameter"].items():
        if p.get("study") and isinstance(p.get("value"), (int, float)) and not isinstance(p["value"], bool):
            own[p["study"]][pid] = p
    from metrology_atlas.load import XREF, _strings, bare
    for sid, st in ds.items["study"].items():  # and the parameters each study links to
        for text in _strings(st):
            for kind, ref, _ in XREF.findall(bare(text)):
                p = ds.items["parameter"].get(ref)
                if kind in {"parameter", "value"} and p and isinstance(p.get("value"), (int, float)) \
                        and not isinstance(p.get("value"), bool):
                    own[sid].setdefault(ref, p)
    out = []
    for sid in sorted(own):
        if only and sid != only or sid not in ds.items["study"]:
            continue
        for path, text in walk(ds.items["study"][sid]):
            masked = _SKIP.sub(lambda m: " " * len(m.group(0)), text)
            for m in _NUMBER.finditer(masked):
                parsed = _parse(m.group(1))
                if parsed is None:
                    continue
                v, dec = parsed
                if dec == 0 and abs(v) < 10:
                    continue
                for pid, p in own[sid].items():
                    pv = float(p["value"])
                    if round(pv, dec) == v and (dec > 0 or pv.is_integer()  # more precise copies are listed
                                                or unit_follows(masked, m.end(), p.get("unit"))):
                        unit = (p.get("unit") or "").strip()
                        after = text[m.end():m.end() + len(unit) + 2].lstrip("  ")
                        out.append({"study": sid, "field": path, "parameter": pid, "typed": m.group(1),
                                    "value": p["value"], "unit": unit,
                                    "unit_follows": bool(unit) and after.startswith(unit),
                                    "exact": dec == written_decimals(p["value"]),
                                    "context": text[max(0, m.start() - 60):m.end() + 60].replace("\n", " "),
                                    "start": m.start(), "end": m.end()})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset")
    ap.add_argument("--study")
    ap.add_argument("--json")
    a = ap.parse_args()
    hs = hits(load(a.dataset), a.study)
    if a.json:
        Path(a.json).write_text(json.dumps(hs, indent=1, ensure_ascii=False), encoding="utf-8")
    for h in hs:
        flag = ("U" if h["unit_follows"] else "-") + ("E" if h["exact"] else "r")
        print(f"{flag} {h['study']} {h['field']} {h['parameter']}={h['value']}{h['unit'] and ' ' + h['unit']}: "
              f"...{h['context']}...")
    print(f"{len(hs)} hits", file=sys.stderr)


if __name__ == "__main__":
    main()
