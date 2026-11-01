"""Mechanical checks of studies: arithmetic in the prose and consistency of their parameters.

    python tools/study_checks.py datasets/vitaldb [--studies a,b,c]

With [[value:...]] resolved, the prose is searched for
  - shares:   'A of B ... (C%)' or 'A/B (C%)': C must be 100 A / B to the precision it is written;
  - centres:  'median X (IQR a-b)', 'X (p10-p90 a-b)', 'X (5th-95th percentile a-b)', 'X (95% a-b)': a <= X <= b.
Parameters of each study: the value inside its own spread (p10-p90, q1-q3, min-max), counts whole and positive,
the study 'current', and the parameter named in its study's text (a value nobody explains is a finding).
Every hit is a question for a person, not a verdict.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrology_atlas import load  # noqa: E402
from metrology_atlas.load import XREF, _strings, bare  # noqa: E402
from metrology_atlas.values import VALUE_XREF, value_text  # noqa: E402

NUM = r"[−-]?\d[\d,]*(?:\.\d+)?"
SHARE = re.compile(rf"({NUM})\s*(?:of|/|out of)\s*(?:the\s+)?({NUM})\b[^()%\n]{{0,60}}?\(\s*({NUM})\s*%")
CENTRE = re.compile(rf"({NUM})\s*(?:[a-zA-Z%/·°]+\s*){{0,2}}\((?:[^()]{{0,30}}?)(?:IQR|p10[–-]p90|p5[–-]p95|5th[–-]95th(?: percentile)?|10th[–-]90th(?: percentile)?|95%(?: interval| CI)?|interquartile range)[:;,]?\s*({NUM})\s*(?:[a-zA-Z%/]+\s*)?(?:–|-|to)\s*({NUM})")


def f(s: str) -> float:
    return float(s.replace("−", "-").replace(",", ""))


def dec(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def check_text(text):
    out = []
    for m in SHARE.finditer(text):
        a, b, c = m.groups()
        try:
            A, B, C = f(a), f(b), f(c)
        except ValueError:
            continue
        if B <= 0 or A > B:
            continue
        exp = 100 * A / B
        tol = 0.5 * 10 ** -dec(c) + 1e-9
        if abs(exp - C) > tol:
            out.append(f"share: {a} of {b} is {exp:.{max(dec(c), 1) + 1}f}%, written {c}%: ...{m.group(0)[:120]}...")
    for m in CENTRE.finditer(text):
        x, lo, hi = m.groups()
        try:
            X, L, H = f(x), f(lo), f(hi)
        except ValueError:
            continue
        if L > H:
            L, H = H, L  # written high to low
        if not L <= X <= H:
            out.append(f"centre outside its range: {x} not in {lo} to {hi}: ...{m.group(0)[:120]}...")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset")
    ap.add_argument("--studies")
    a = ap.parse_args()
    ds = load(a.dataset)
    P = ds.items["parameter"]
    want = a.studies.split(",") if a.studies else sorted(ds.items["study"])
    n = 0
    for sid in want:
        st = ds.items["study"][sid]
        res = lambda t: VALUE_XREF.sub(lambda m: value_text(P[m.group(1)], m.group(2)), t)  # noqa: E731
        texts = [res(t) for t in _strings({k: v for k, v in st.items() if k not in {"id"}})]
        hits = [h for t in texts for h in check_text(t)]
        named = {ref for t in _strings(st) for k, ref, _ in XREF.findall(bare(t)) if k in {"parameter", "value"}}
        for pid, p in sorted(P.items()):
            if p.get("study") != sid:
                continue
            v, s = p.get("value"), p.get("spread") or {}
            for lo, hi in (("p10", "p90"), ("q1", "q3"), ("min", "max"), ("p5", "p95")):
                if isinstance(v, (int, float)) and lo in s and hi in s and not min(s[lo], s[hi]) <= v <= max(s[lo], s[hi]):
                    hits.append(f"parameter {pid}: value {v} outside its {lo}-{hi} {s[lo]} to {s[hi]}")
            if "n" in s and (not isinstance(s["n"], int) or s["n"] <= 0):
                hits.append(f"parameter {pid}: n = {s['n']}")
            if pid not in named:
                hits.append(f"parameter {pid}: not named in its study's text")
            for t in _strings({k: p[k] for k in p if k not in {"id", "value"}}):
                hits += [f"parameter {pid}: {h}" for h in check_text(res(t))]
        if st.get("status") != "current":
            hits.append(f"status is '{st.get('status')}'")
        if hits:
            print(f"\n== {sid}")
            for h in hits:
                print("  - " + h)
            n += len(hits)
    print(f"\n{n} questions in {len(want)} studies", file=sys.stderr)


if __name__ == "__main__":
    main()
