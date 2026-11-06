# SPDX-License-Identifier: MIT
"""Before-and-after check of the timing forms and the planner's results (Phase 2 1/2, step 3).

    python tools/form_snapshot.py snapshot datasets/vitaldb --out build/forms_before.json
    ... edit the dataset ...
    python tools/form_snapshot.py snapshot datasets/vitaldb --out build/forms_after.json
    python tools/form_snapshot.py compare build/forms_before.json build/forms_after.json [--tol 1e-9] [--out diff.json]

snapshot: every timing form of every timed variable, resolved as the planner resolves it
(metrology_atlas.planner.planner_form, after parameter links are filled in): bias, shift, what it removes, combined
standard uncertainty and its upper-bound and likely forms, latency, support, domain, status, the chart position,
the uncertainty shared by clock or correction, and each component's u. Then the planner's pair numbers for every
pair of variables' default forms: sigma = sqrt(u_a^2 + u_b^2 - 2 cov), cov summing the products of the components
they share (as the page's script), the coherent band 0.1325 / sigma and the finest shared grid sqrt(12) sigma.

compare: what changed between two snapshots: forms added or removed, and every number (or text field) that moved by
more than --tol, with old and new values; pairs whose sigma moved. Prints a summary and writes --out if given. Exit
code 0 whatever changed: it reports, it does not judge.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrology_atlas.load import load  # noqa: E402
from metrology_atlas.planner import planner_form  # noqa: E402
from metrology_atlas.timing import forms as timing_forms  # noqa: E402

KEEP = ("default", "kind", "uses_future", "bias", "shift", "removes", "u_c", "upper_bound", "likely", "latency",
        "support_hi", "domain", "status", "delay", "interval", "shared", "unknown_scope", "corrects")


def snapshot(a) -> None:
    ds = load(a.dataset)
    forms, defaults = {}, {}
    for vid, v in sorted(ds.items["variable"].items()):
        if not v.get("timing"):
            continue
        for f in timing_forms(v):
            p = planner_form(f, ds)
            rec = {k: p.get(k) for k in KEEP}
            rec["components"] = {c.get("name", str(i)): c.get("u_s") for i, c in enumerate(f.get("components") or [])}
            forms[f"{vid}/{f['id']}"] = rec
            if f["default"]:
                defaults[vid] = rec
    pairs = {}
    for x, y in itertools.combinations(sorted(defaults), 2):
        fa, fb = defaults[x], defaults[y]
        if fa["u_c"] is None or fb["u_c"] is None:
            continue
        cov = sum(fa["shared"][k] * fb["shared"][k] for k in set(fa["shared"]) & set(fb["shared"]))
        s = math.sqrt(max(fa["u_c"] ** 2 + fb["u_c"] ** 2 - 2 * cov, 0.0))
        pairs[f"{x}|{y}"] = {"sigma": round(s, 6), "band_hz": round(0.1325 / s, 4) if s else None,
                             "grid_s": round(math.sqrt(12) * s, 6)}
    out = {"dataset": str(a.dataset), "forms": forms, "pairs": pairs}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    print(f"{len(forms)} forms of {len({k.split('/')[0] for k in forms})} variables, {len(pairs)} pairs -> {a.out}")


def flat(x, pre=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from flat(v, f"{pre}.{k}" if pre else str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from flat(v, f"{pre}[{i}]")
    else:
        yield pre, x


def moved(a, b, tol) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) > tol
    return a != b


def compare(a) -> None:
    A, B = (json.loads(Path(p).read_text()) for p in (a.before, a.after))
    fa, fb = A["forms"], B["forms"]
    res = {"added": sorted(set(fb) - set(fa)), "removed": sorted(set(fa) - set(fb)), "changed": {}, "pairs": {}}
    for k in sorted(set(fa) & set(fb)):
        x, y = dict(flat(fa[k])), dict(flat(fb[k]))
        ch = {f: [x.get(f), y.get(f)] for f in sorted(set(x) | set(y)) if moved(x.get(f), y.get(f), a.tol)}
        if ch:
            res["changed"][k] = ch
    for k in sorted(set(A["pairs"]) | set(B["pairs"])):
        s0, s1 = (A["pairs"].get(k) or {}).get("sigma"), (B["pairs"].get(k) or {}).get("sigma")
        if moved(s0, s1, a.tol):
            res["pairs"][k] = [s0, s1]
    print(f"forms: {len(res['added'])} added, {len(res['removed'])} removed, {len(res['changed'])} changed; "
          f"pairs with a new sigma: {len(res['pairs'])}")
    for k in res["added"]:
        print(f"  + {k}")
    for k in res["removed"]:
        print(f"  - {k}")
    for k, ch in res["changed"].items():
        print(f"  ~ {k}")
        for f, (u, v) in ch.items():
            print(f"      {f}: {u} -> {v}")
    big = sorted(res["pairs"].items(), key=lambda kv: -abs((kv[1][1] or 0) - (kv[1][0] or 0)))[:20]
    for k, (u, v) in big:
        print(f"  pair {k}: sigma {u} -> {v}")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("snapshot")
    s.add_argument("dataset")
    s.add_argument("--out", required=True)
    c = sp.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--tol", type=float, default=1e-9)
    c.add_argument("--out")
    a = ap.parse_args()
    snapshot(a) if a.cmd == "snapshot" else compare(a)


if __name__ == "__main__":
    main()
