"""Suggest `sources` for parameters: the saved JSON outputs and keys that hold their numbers.

For each parameter, every JSON file among the candidates (files, or folders searched two levels down, at most
20 MB each) is walked, and every number that equals the parameter's value as written (to the value's own last
digit, under scales 1, 100, 1000, 0.001, 0.01 and -1, -1000 for sign conventions) is listed, with how many of the parameter's spread numbers (p5, p95,
n, ...) the same file also holds. The suggestions are for a person to choose from; nothing is written to the atlas.

    python tools/find_sources.py datasets/vitaldb --ids a,b,c --candidates cands.csv [--roots "W=...;R=..."] --out s.json

cands.csv: rows of parameter id, output (ROOT:path or a path); a row with id '*' applies to every parameter.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from decimal import Decimal
from pathlib import Path

import yaml

SCALES = (1, 1000, 100, 0.001, 0.01, -1, -1000)
LIMIT = 20 * 2**20


def roots(spec: str) -> dict[str, Path]:
    out = {}
    for part in (spec or os.environ.get("METROLOGY_ATLAS_ROOTS", "")).split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = Path(v.strip())
    return out


def local(p: str, R: dict[str, Path]) -> Path:
    if ":" in p and p.split(":", 1)[0] in R:
        k, rest = p.split(":", 1)
        return R[k] / rest
    return Path(p)


def rooted(p: Path, R: dict[str, Path]) -> str:
    for k, r in sorted(R.items(), key=lambda x: -len(str(x[1]))):
        try:
            return f"{k}:{p.resolve().relative_to(r.resolve()).as_posix()}"
        except ValueError:
            continue
    return p.as_posix()


def half_ulp(v: float) -> float:
    d = Decimal(str(v)).normalize().as_tuple().exponent
    return 0.5 * 10 ** min(int(d), 0) if isinstance(d, int) else 0.5


def leaves(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(x, list):
        if len(x) > 50:
            return
        for i, v in enumerate(x):
            yield from leaves(v, f"{path}.{i}" if path else str(i))
    elif isinstance(x, (int, float)) and not isinstance(x, bool):
        yield path, float(x)


def json_files(p: Path):
    if p.is_file():
        if p.suffix == ".json" and p.stat().st_size <= LIMIT:
            yield p
    elif p.is_dir():
        for q in sorted(p.glob("*.json")) + sorted(p.glob("*/*.json")):
            if "_runs" not in q.parts and q.stat().st_size <= LIMIT:
                yield q


def matches(v: float, x: float) -> list[float]:
    tol = half_ulp(v)
    return [s for s in SCALES if abs(x * s - v) <= tol + 1e-12]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset")
    ap.add_argument("--ids", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--roots", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = roots(a.roots)
    cands: dict[str, list[str]] = {}
    for row in csv.reader(open(a.candidates, encoding="utf-8")):
        if len(row) >= 2 and row[0] != "id":
            cands.setdefault(row[0], []).append(row[1])
    res = {}
    cache: dict[Path, object] = {}
    for pid in a.ids.split(","):
        p = yaml.safe_load(open(Path(a.dataset) / "parameters" / f"{pid}.yaml", encoding="utf-8"))
        v = p.get("value")
        sp = {k: x for k, x in (p.get("spread") or {}).items() if isinstance(x, (int, float))}
        hits = []
        seen = set()
        for c in cands.get(pid, []) + cands.get("*", []):
            for f in json_files(local(c, R)):
                if f in seen:
                    continue
                seen.add(f)
                if f not in cache:
                    try:
                        cache[f] = json.loads(f.read_text(encoding="utf-8"))
                    except (ValueError, OSError):
                        cache[f] = None
                if cache[f] is None:
                    continue
                L = list(leaves(cache[f]))
                if v is None:
                    continue
                for path, x in L:
                    for s in matches(float(v), x):
                        also = sorted(k for k, y in sp.items() if any(matches(float(y), z) for _, z in L))
                        hits.append({"output": rooted(f, R), "key": path, "scale": s, "found": x, "spread_also": also})
        hits.sort(key=lambda h: (-len(h["spread_also"]), h["scale"] != 1, len(h["key"])))
        res[pid] = {"value": v, "spread": sp, "hits": hits[:12]}
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: len(r["hits"]) for k, r in res.items()}))


if __name__ == "__main__":
    main()
