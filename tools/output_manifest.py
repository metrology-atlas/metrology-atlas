# SPDX-License-Identifier: MIT
"""The saved outputs an atlas cites, with checksums: the list for its data deposit (plan item C5).

    python tools/output_manifest.py datasets/vitaldb --work $W --repos .. --out $W/manifest/outputs.json [--csv FILE]

Reads every YAML file of the dataset and collects the paths it cites as outputs: $W/... and work/... paths, and
backticked or bare relative paths ending in .json, .jsonl, .csv, .txt, .md, .npz, .parquet or .png that exist in the
work folder. A path is looked up in the work folder, then (for tool outputs kept in a code repository, such as
vitaldb-resolution's tools/precision_results.json) in the repositories next to this one. A cited folder stands for
its summary files (summary*.json, *_summary.json, agg/summary.json) and is listed with its file count. Globs
(part_*.jsonl) are expanded.

Each entry: path (relative to the work folder, or repo:path), where it was found, size, SHA-256 (left out for
per-recording files over 100 MB), the items that cite it, and a class:

* aggregate: summaries and tables without record identifiers; these go in the deposit;
* aggregate (example cases): summaries that name up to 60 example recordings (public VitalDB case numbers, as the
  atlas does); these go in the deposit too;
* per-recording: rows per recording, case or event (jsonl, parquet, npz, part files, caches, CSV files with a case
  column, JSON lists of cases); these stay on the analysis machine (project rule) and are listed for provenance;
* code: a script kept with the outputs (to be moved into a repository);
* in-repository: found in a code repository, published with it;
* missing: cited but not found (to be fixed in the atlas or regenerated).

Writes the manifest as JSON (and CSV with --csv) and prints counts.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
from pathlib import Path

import yaml

EXT = r"(?:json|jsonl|csv|txt|md|npz|parquet|png)"
PREFIXED = re.compile(r"(?:\$W/|(?<![\w/])work/)([A-Za-z0-9_.*{}\-/]+)")
RELATIVE = re.compile(r"(?<![\w/$.])([a-z0-9_][A-Za-z0-9_\-]*(?:/[A-Za-z0-9_.*\-]+)+\." + EXT + r")\b")
EXAMPLES = 60         # a summary may name up to this many example cases (public identifiers) and stay an aggregate
BIG = 100_000_000      # per-recording files larger than this are listed without a checksum
PER_RECORD_NAME = re.compile(r"(^part|_part|cache_|\.jsonl$|\.npz$|\.parquet$|cases|labels|per_recording)", re.I)


def strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)
    elif isinstance(x, str):
        yield x


def cited(dataset: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(dataset.rglob("*.yaml")):
        if "_generated" in f.parts:
            continue
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        item = f"{f.parent.name}/{f.stem}"
        for s in strings(d):
            for m in PREFIXED.finditer(s):
                path = m.group(1).rstrip("./)")
                if path.endswith(("_", "-")):        # cut short by a shell variable ($p, $K)
                    path += "*"
                out.setdefault(path, set()).add(item)
            for m in RELATIVE.finditer(s):
                out.setdefault("?" + m.group(1), set()).add(item)
    return out


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def klass(p: Path) -> str:
    n = p.name
    if PER_RECORD_NAME.search(n):
        return "per-recording"
    if n.endswith(".csv"):
        try:
            head = p.open(encoding="utf-8", errors="replace").readline().lower().split(",")
            if {"case", "caseid", "case_id", "recording"} & {h.strip() for h in head}:
                return "per-recording"
        except OSError:
            pass
    if n.endswith(".py"):
        return "code"
    if n.endswith(".json"):
        try:
            if p.stat().st_size < 50_000_000:
                k = id_count(json.loads(p.read_text(encoding="utf-8")))
                if k > EXAMPLES:
                    return "per-recording"
                if k:
                    return "aggregate (example cases)"
        except (OSError, ValueError):
            pass
    return "aggregate"


def id_count(d, depth: int = 0) -> int:
    """How many record identifiers sit near the top: keys that are case numbers (in dicts with 20 or more keys,
    mostly numeric), rows with a case field, and case numbers listed under a key naming cases, records or examples."""
    if depth > 4:
        return 0
    n = 0
    if isinstance(d, dict):
        keys = list(d)
        if len(keys) >= 20 and sum(k.isdigit() for k in keys) >= 0.5 * len(keys):
            n += sum(k.isdigit() for k in keys)
        for k, v in d.items():
            if k.lower() in ("case", "caseid", "case_id") and isinstance(v, int):
                n += 1
            elif re.search(r"cases|records|examples", k, re.I) and isinstance(v, list) \
                    and v and all(isinstance(x, int) for x in v[:20]):
                n += len(v)
            elif isinstance(v, (dict, list)):
                n += id_count(v, depth + 1)
    elif isinstance(d, list):
        n += sum(id_count(x, depth + 1) for x in d)
    return n


def entry(p: Path, root: Path, where: str, by: set[str]) -> dict:
    k, n = (klass(p) if where == "work" else "in-repository"), p.stat().st_size
    return {"path": str(p.relative_to(root)) if where == "work" else f"{where}:{p.relative_to(root)}",
            "found_in": where, "bytes": n, "sha256": sha(p) if k.startswith("aggregate") or n <= BIG else None,
            "class": k, "cited_by": sorted(by)}


def add(rows: dict, p: Path, base: Path, where: str, by: set[str]) -> None:
    k = str(p)
    if k not in rows:
        rows[k] = entry(p, base, where, set())
    rows[k]["cited_by"] = sorted(set(rows[k]["cited_by"]) | by)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--repos", type=Path, help="folder holding the code repositories (searched recursively, depth 2)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--csv", type=Path)
    a = ap.parse_args()
    W = a.work
    repos = [p for p in (a.repos.glob("*") if a.repos else []) if (p / ".git").exists()]
    if a.repos:
        repos += [p for p in a.repos.glob("*/*") if (p / ".git").exists()]
    rows, missing, folders = {}, [], []
    for ref, by in sorted(cited(a.dataset).items()):
        bare = ref.lstrip("?")
        optional = ref.startswith("?")              # a bare relative path: only counts if it exists somewhere
        hits = []
        for base, where in [(W, "work")] + [(r, r.name) for r in repos]:
            pat = re.sub(r"\{[^}]*\}", "*", bare).replace("partK", "part*").replace("_K.", "_*.")
            for g in sorted(glob.glob(str(base / pat))):
                hits.append((Path(g), base, where))
            if hits:
                break
        if not hits:
            if not optional:
                missing.append({"path": bare, "cited_by": sorted(by)})
            continue
        for p, base, where in hits:
            if p.is_dir():
                summ = [q for q in p.glob("*.json") if "summary" in q.name] + list(p.glob("agg/summary*.json"))
                folders.append({"path": str(p.relative_to(base)), "found_in": where,
                                "files": sum(1 for _ in p.rglob("*") if _.is_file()), "cited_by": sorted(by),
                                "summaries": [str(q.relative_to(base)) for q in summ]})
                for q in summ:
                    add(rows, q, base, where, by)
            else:
                add(rows, p, base, where, by)
    files = sorted(rows.values(), key=lambda r: r["path"])
    out = {"dataset": str(a.dataset), "work": str(W), "files": files, "folders": folders, "missing": missing,
           "counts": {k: sum(r["class"] == k for r in files)
                      for k in ("aggregate", "aggregate (example cases)", "per-recording", "code", "in-repository")} | {
                      "folders": len(folders), "missing": len(missing),
                      "aggregate_bytes": sum(r["bytes"] for r in files if r["class"].startswith("aggregate"))}}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1) + "\n")
    if a.csv:
        with a.csv.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["path", "found_in", "class", "bytes", "sha256", "cited_by"])
            for r in files:
                w.writerow([r["path"], r["found_in"], r["class"], r["bytes"], r["sha256"], " ".join(r["cited_by"])])
    print(json.dumps(out["counts"]))
    for m in missing:
        print("missing:", m["path"], "<-", ", ".join(m["cited_by"]))


if __name__ == "__main__":
    main()
