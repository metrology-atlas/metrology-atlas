"""The setup register on pages/setups.md, and per-setup values of the drift parameters.

    python datasets/vitaldb/_import/setups.py <ports.jsonl> <units.csv> [<frame_clock_*.jsonl> ...]

Inputs, both per case and kept on the analysis machine:

- ``ports.jsonl``: each recording's devices and the serial (COM) port each was attached to, read from the device
  records of every .vital file;
- ``units.csv``: the per-case SNUADC and BIS drift behind [[study:drift-units]];
- optionally, the outputs of vitaldb-bench's ``tools/frame_an.py``: the oximeter's frame clock per case, kept where
  the raw PPG peak locks to it (resultant at least 5 times the scan's median) and the recording's two halves agree
  within 3 ppm.

A setup is identified by its *PC key*: the ports of the four core devices (SNUADC, Solar8000, Primus, BIS). The
script writes only aggregates, for keys with at least 5 cases with a drift: the register between the markers in
pages/setups.md, and ``by_setup`` tables for the SNUADC step-mode drift and the BIS drift as generated parameter
overlays (_generated/parameters/). It also prints how much closer each grouping puts a case's drift to its group's
median than to the release's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
PAGE = HERE / "pages" / "setups.md"
GEN = HERE / "_generated" / "parameters"
START, END = "<!-- setups:register -->", "<!-- /setups:register -->"
CORE = ("SNUADC", "Solar8000", "Primus", "BIS")
MIN_N = 5


def closeness(df, val, grp, tol=3.0):
    g = df.dropna(subset=[val, grp])
    keep = g[grp].value_counts()
    g = g[g[grp].isin(keep[keep >= MIN_N].index)]
    med = g.groupby(grp)[val].transform("median")
    return (float((abs(g[val] - med) <= tol).mean()), float((abs(g[val] - g[val].median()) <= tol).mean()),
            int(g[grp].nunique()), len(g))


def by_key(df, val):
    rows = []
    for key, g in df.dropna(subset=[val, "key"]).groupby("key"):
        s = g[val]
        if len(s) >= MIN_N:
            rows.append({"setup": key, "value": round(float(s.median()), 1), "q1": round(float(s.quantile(.25)), 1),
                         "q3": round(float(s.quantile(.75)), 1), "n": int(len(s))})
    return sorted(rows, key=lambda r: -r["n"])


def load_frame(paths) -> dict:
    out = {}
    for path in paths:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            ph = (r.get("phase") or {}).get("peak") or {}
            a, h1, h2 = ph.get("all") or {}, ph.get("half1") or {}, ph.get("half2") or {}
            if (a.get("r_best") and a.get("r_median") and a["r_best"] >= 5 * a["r_median"]
                    and h1.get("best_ppm") is not None and h2.get("best_ppm") is not None
                    and abs(h1["best_ppm"] - h2["best_ppm"]) <= 3):
                out[int(r["case"])] = float(a["best_ppm"])
    return out


def main(ports_jsonl: str, units_csv: str, frame_paths=()) -> None:
    ports = {}
    for line in open(ports_jsonl, encoding="utf-8"):
        r = json.loads(line)
        p = r.get("ports") or {}
        ports[r["case"]] = {**{f"{d}_port": p.get(d) for d in CORE},
                            "key": " · ".join(p[d] for d in CORE) if all(p.get(d) for d in CORE) else None}
    P = pd.DataFrame.from_dict(ports, orient="index")
    u = pd.read_csv(units_csv).set_index("case")
    d = P.join(u[["snuadc_drift_ppm", "bis_drift_ppm"]], how="left")
    frame = load_frame(frame_paths)
    d["frame_ppm"] = pd.Series(frame)
    d["mode"] = np.where(d.snuadc_drift_ppm < -20, "step", np.where(d.snuadc_drift_ppm.notna(), "frequent", None))
    step = d[d["mode"] == "step"].copy()
    step["pair"] = step.SNUADC_port + " + " + step.BIS_port
    c_port, c_pair, c_key = (closeness(step, "snuadc_drift_ppm", g) for g in ("SNUADC_port", "pair", "key"))
    b_port, b_key = closeness(d, "bis_drift_ppm", "BIS_port"), closeness(d, "bis_drift_ppm", "key")
    f_key = closeness(d, "frame_ppm", "key") if frame else None
    keys = d.key.value_counts()
    with_key = int(d.key.notna().sum())
    out = [START, "",
           f"Ports are recorded for almost every device: the four core devices' ports, and so the PC key, are complete "
           f"for {with_key:,} of {len(d):,} recordings ({with_key / len(d):.0%}); the rest lack a BIS or have no port "
           f"for one device. They form {int((keys >= 1).sum())} distinct PC keys, {int((keys >= 20).sum())} of them "
           f"with at least 20 recordings ({int(keys[keys >= 20].sum()):,} recordings).", "",
           "**How much a grouping tells you about a device's drift.** Share of cases whose drift is within 3 ppm of "
           "their group's median, against within 3 ppm of the median of all cases (groups with at least 5 cases):", "",
           "| Device | By its own port | By SNUADC + BIS ports | By PC key | Release median |", "|---|---|---|---|---|",
           f"| SNUADC, step mode | {c_port[0]:.0%} ({c_port[2]} ports) | {c_pair[0]:.0%} ({c_pair[2]} pairs) | "
           f"{c_key[0]:.0%} ({c_key[2]} keys) | {c_port[1]:.0%} |",
           f"| BIS | {b_port[0]:.0%} ({b_port[2]} ports) | — | {b_key[0]:.0%} ({b_key[2]} keys) | {b_port[1]:.0%} |",
           *([f"| Oximeter frame clock | — | — | {f_key[0]:.0%} ({f_key[2]} keys) | {f_key[1]:.0%} |"] if frame else []),
           "", "**Setups with at least 20 recordings**, by PC key (SNUADC · Solar8000 · Primus · BIS port). Drifts "
           "are medians over the cases where they were measured.", "",
           "| PC key | Recordings | SNUADC frequent mode | SNUADC step drift (ppm) | BIS drift (ppm) | Oximeter frame clock (ppm) |",
           "|---|---|---|---|---|---|"]
    for key, n in keys[keys >= 20].items():
        g = d[d.key == key]
        m = g["mode"].dropna()
        sd, bd = g.loc[g["mode"] == "step", "snuadc_drift_ppm"].dropna(), g.bis_drift_ppm.dropna()
        out.append(f"| {key} | {n} | " + (f"{(m == 'frequent').mean():.0%} of {len(m)}" if len(m) else "—")
                   + " | " + (f"{sd.median():.1f} (n={len(sd)})" if len(sd) >= 3 else "—")
                   + " | " + (f"{bd.median():.1f} (n={len(bd)})" if len(bd) >= 3 else "—")
                   + " | " + (f"{g.frame_ppm.dropna().median():+.0f} (n={g.frame_ppm.notna().sum()})"
                              if g.frame_ppm.notna().sum() >= 3 else "—") + " |")
    out += ["", END]
    text = PAGE.read_text(encoding="utf-8")
    a, b = text.index(START), text.index(END) + len(END)
    PAGE.write_text(text[:a] + "\n".join(out) + text[b:], encoding="utf-8")
    GEN.mkdir(parents=True, exist_ok=True)
    jobs = [("snuadc-step-rate", step, "snuadc_drift_ppm"), ("bis-rate", d, "bis_drift_ppm")]
    if frame:
        jobs.append(("pleth-frame-clock-rate", d, "frame_ppm"))
    for pid, df, val in jobs:
        doc = {"id": pid, "setup_key": "PC key: SNUADC · Solar8000 · Primus · BIS serial ports",
               "by_setup": by_key(df, val)}
        (GEN / f"{pid}.yaml").write_text("# Generated by _import/setups.py; do not edit.\n"
                                         + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print({"snuadc": (c_port, c_pair, c_key), "bis": (b_port, b_key), "frame": f_key, "with_key": with_key,
           "keys": len(keys), "frame_cases": len(frame)})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
