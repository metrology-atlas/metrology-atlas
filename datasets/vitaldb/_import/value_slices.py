"""Worked examples and joint maps for the fitted value models: aggregates from the pinned vitaldb-resolution.

    python datasets/vitaldb/_import/value_slices.py <vitaldb-resolution repo> <VitalDB release folder>

For each variable with a fitted model, evaluates the library at the snapshot's commit (extracted with git archive,
so uncommitted changes in the repository are never used) for every row of clinical_data.csv, and writes only
aggregates:

- **Slices.** The distribution of the true value minus the recorded one, averaged over all records that share a
  recorded value (for charted times: the same minute of the hour). Up to four are kept as worked examples: the
  commonest recorded value, the widest and the narrowest, then whichever is most unlike those (in width, in how
  evenly its rounding modes share it, and in where its centre sits), dropping any too like one already kept.
- **Joint map.** Probability mass over (recorded, true) bins, summed over records: an image in figures/joint/.

Output: _sources/vitaldb-resolution/slices.json and figures/joint/<atlas id>.png. Only groups with at least 20
records are kept, and no record values or identifiers are written. Resumable: one variable at a time within a time
budget; run until it reports nothing left.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tarfile
import io
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
SNAP = HERE / "_sources" / "vitaldb-resolution"
OUT = SNAP / "slices.json"
JOINT = HERE / "figures" / "joint"
BUDGET = 60
MIN_N = 20
NG = 241          # grid points for a slice
TIMES = {"anestart", "opstart", "aneend", "opend"}   # charted clock times: group by minute of the hour
ATLAS_ID = {}     # filled from the generated variables (source_name -> atlas id)


def pinned(repo: str, commit: str) -> Path:
    dest = Path.home() / "vr_pinned_" / commit[:10]
    if not (dest / "vitaldb_resolution").is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        tar = subprocess.run(["git", "-C", repo, "archive", commit], capture_output=True, check=True).stdout
        tarfile.open(fileobj=io.BytesIO(tar)).extractall(dest, filter="data")
    return dest


def clock_minute(x: float, row: dict) -> int:
    """Minute of the hour of a charted time, by the library's own clock rule (engine.TimestampModel)."""
    clock = ((-float(row["adm"]) + math.ceil(x / 60 - 1e-9) * 60) % 86400) / 60
    return int(round(clock)) % 60


def comp_entropy(d) -> float:
    w = np.array([c.weight for c in d.components], float)
    w = w[w > 0] / w.sum()
    return float(-(w * np.log(w)).sum() / math.log(len(w))) if len(w) > 1 else 0.0


def main(repo: str, release: str) -> None:
    import pandas as pd
    import yaml

    commit = yaml.safe_load((SNAP / "SOURCE.yaml").read_text())["commit"]
    sys.path.insert(0, str(pinned(repo, commit)))
    import vitaldb_resolution as vr

    for f in (HERE / "_generated" / "variables").glob("*.yaml"):
        g = yaml.safe_load(f.read_text(encoding="utf-8"))
        if g and g.get("source_name"):
            ATLAS_ID[g["source_name"]] = g["id"]
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    if done.get("commit") != commit:
        done = {"commit": commit, "variables": {}}
    reg = vr.load()
    variables = json.loads((pinned(repo, commit) / "vitaldb_resolution/data/registry.json").read_text())["variables"]
    todo = [n for n, v in variables.items() if v["method"] in ("model", "timestamp_model") or (v["method"] == "derived" and v.get("model"))]
    clinical = pd.read_csv(Path(release) / "clinical_data.csv")
    t0 = time.time()
    for name in todo:
        if name in done["variables"]:
            continue
        if time.time() - t0 > BUDGET:
            break
        rows = clinical.to_dict("records")

        def chunks():
            """(row index, distribution) for every usable record, 400 rows at a time, so that the distributions (which
            can hold large tables) are never all in memory at once."""
            for i in range(0, len(clinical), 400):
                for j, d in enumerate(reg.distributions(name, clinical.iloc[i:i + 400])):
                    if getattr(d, "status", None) == "ok" and d.components:
                        yield i + j, d

        # pass 1: the support of every record, to fix one grid for the variable
        ok, rec_l, lo_l, hi_l, unit = [], [], [], [], ""
        for i, d in chunks():
            x = float(d.recorded_value)
            ok.append(i); rec_l.append(x); unit = unit or (d.unit or "")
            lo_l.append(min(c.lower for c in d.components) - x)
            hi_l.append(max(c.upper for c in d.components) - x)
        if not ok:
            done["variables"][name] = {"error": "no distributions"}
            continue
        scale, shown = (60.0, "min") if name in TIMES and unit in ("s", "sec") else (1.0, unit)
        rec = np.array(rec_l)
        a, b = np.percentile(np.array(lo_l), 0.5), np.percentile(np.array(hi_l), 99.5)
        pad = 0.05 * (b - a)
        edges = np.linspace(a - pad, b + pad, NG + 1)
        mids = (edges[:-1] + edges[1:]) / 2
        # pass 2: each record's mass on the grid, grouped by recorded value (or minute of the hour)
        groups: dict = {}
        masses = []
        for k, (i, d) in enumerate(chunks()):
            x, r = rec[k], rows[i]
            key = f":{clock_minute(x, r):02d}" if name in TIMES else f"{x:g}"
            m = np.diff(d.cdf(x + edges))
            masses.append(m)
            g = groups.setdefault(key, {"n": 0, "mass": np.zeros(NG), "ent": [], "w": {}, "idx": []})
            g["n"] += 1
            g["idx"].append(k)
            g["mass"] += m
            g["ent"].append(comp_entropy(d))
            for c in d.components:
                g["w"][c.label] = g["w"].get(c.label, 0.0) + c.weight / sum(cc.weight for cc in d.components)
        cand = []
        for key, g in groups.items():
            if g["n"] < MIN_N or g["mass"].sum() <= 0:
                continue
            p = g["mass"] / g["mass"].sum()
            mu = float((p * mids).sum())
            sd = float(math.sqrt(max((p * (mids - mu) ** 2).sum(), 0)))
            cdf = np.cumsum(p)
            q = [float(np.interp(t, cdf, mids)) for t in (0.025, 0.5, 0.975)]
            cand.append({"recorded": key, "n": g["n"], "idx": g["idx"], "pdf": (p / np.diff(edges)).tolist(), "mean": mu, "sd": sd,
                         "q": q, "mixing": float(np.mean(g["ent"])),
                         "weights": {k: v / g["n"] for k, v in sorted(g["w"].items(), key=lambda kv: -kv[1])}})
        picks = []
        if cand:
            def dist(c, p):
                return math.sqrt(math.log((c["sd"] + 1e-9) / (p["sd"] + 1e-9)) ** 2 + (c["mixing"] - p["mixing"]) ** 2
                                 + ((c["q"][1] - p["q"][1]) / max(c["sd"], p["sd"], 1e-9)) ** 2)
            smin = min(c["sd"] for c in cand)
            narrow = max((c for c in cand if c["sd"] <= 1.05 * smin), key=lambda c: c["n"])
            for c, w in ((max(cand, key=lambda c: c["n"]), "the commonest recorded value"),
                         (max(cand, key=lambda c: c["sd"]), "the widest"), (narrow, "the narrowest")):
                if all(dist(c, p) > 0.3 for p in picks):
                    picks.append({**c, "why": w})
            while len(picks) < 4:   # then whatever is most unlike the cases already shown, if anything is
                rest = [c for c in cand if all(c["recorded"] != p["recorded"] for p in picks)]
                if not rest:
                    break
                c = max(rest, key=lambda c: min(dist(c, p) for p in picks))
                if min(dist(c, p) for p in picks) <= 0.3:
                    break
                picks.append({**c, "why": "unlike the others"})
        for p in picks:   # each example again on its own fine grid, so narrow ones are not drawn from a few points
            c = np.cumsum(p["pdf"] * np.diff(edges))
            c = c / c[-1]
            lo_, hi_ = mids[min(np.searchsorted(c, 0.001), NG - 1)], mids[min(np.searchsorted(c, 0.999), NG - 1)]
            half = max(abs(lo_), abs(hi_), (edges[-1] - edges[0]) / 400) * 1.3
            fe = np.linspace(-half, half, 402)
            fm = np.zeros(401)
            sel = [ok[k] for k in p["idx"]]
            for i in range(0, len(sel), 400):
                part = sel[i:i + 400]
                for k, d in zip(part, reg.distributions(name, clinical.iloc[part])):
                    if getattr(d, "status", None) == "ok" and d.components:
                        fm += np.diff(d.cdf(float(d.recorded_value) + fe))
            fm = fm / max(fm.sum(), 1e-12)
            p["fine"] = (((fe[:-1] + fe[1:]) / 2).tolist(), (fm / np.diff(fe)).tolist())
        # joint map: recorded value (or minute of the hour) across, true minus recorded up
        if name in TIMES:
            xk = np.array([clock_minute(x, rows[i]) for i, x in zip(ok, rec)])
            xedges = np.arange(-0.5, 60.5, 1.0)
        else:
            xk = rec
            xa, xb = np.percentile(rec, 0.5), np.percentile(rec, 99.5)
            xedges = np.linspace(xa, xb, 121)
        H = np.zeros((len(xedges) - 1, NG))
        for m, k in zip(masses, xk):
            j = np.searchsorted(xedges, k, side="right") - 1
            if 0 <= j < H.shape[0]:
                H[j] += m
        aid = ATLAS_ID.get(name, name.replace("_", "-"))
        JOINT.mkdir(parents=True, exist_ok=True)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LogNorm
        fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
        Hm = np.ma.masked_less_equal(H.T / max(H.sum(), 1e-12), 1e-7)
        im = ax.pcolormesh(xedges, edges / scale, Hm, norm=LogNorm(vmin=max(Hm.min(), 1e-7), vmax=Hm.max()), cmap="viridis",
                           shading="flat")
        ax.axhline(0, color="0.5", lw=0.6)
        ax.set_xlabel("recorded minute of the hour" if name in TIMES else f"recorded value ({unit})")
        ax.set_ylabel(f"true minus recorded ({shown})")
        fig.colorbar(im, ax=ax, label="share of all probability (log)")
        fig.tight_layout()
        fig.savefig(JOINT / f"{aid}.png")
        plt.close(fig)
        done["variables"][name] = {
            "unit": shown, "records": len(ok), "grid": (mids / scale).tolist(), "scale": scale,
            "examples": [{**{k: p[k] for k in ("recorded", "n", "why", "weights", "mixing")},
                          "grid": [v / scale for v in p["fine"][0]], "pdf": [v * scale for v in p["fine"][1]], "mean": p["mean"] / scale, "sd": p["sd"] / scale,
                          "q": [v / scale for v in p["q"]]} for p in picks],
            "joint": f"joint/{aid}.png", "groups": len(cand),
            "by": "minute of the hour" if name in TIMES else "recorded value"}
        OUT.write_text(json.dumps(done) + "\n", encoding="utf-8")
        print(name, len(ok), "records,", len(cand), "groups,", len(picks), "examples")
    left = [n for n in todo if n not in done["variables"]]
    OUT.write_text(json.dumps(done) + "\n", encoding="utf-8")
    print(f"{len(done['variables'])} done, {len(left)} left: {', '.join(left)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
