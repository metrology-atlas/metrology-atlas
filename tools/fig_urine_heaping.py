# SPDX-License-Identifier: MIT
"""Figure 3 of the paper and the atlas page "Worked example: a rounded urine volume": the recorded intraoperative urine
volumes in VitalDB against the true volumes the value model infers (A), and what two recorded values mean (B).

    python tools/fig_urine_heaping.py RESOLUTION_REPO RELEASE --summary SUMMARY.json OUT [OUT ...]

RESOLUTION_REPO is the vitaldb-resolution repository (its engine and the fitted model
vitaldb_resolution/data/models/intraop_uo.model.json); RELEASE is the VitalDB folder holding clinical_data.csv. Each OUT
is written in the format its extension names (PNG at 200 dpi), at print size (160 mm wide). SUMMARY.json holds every
number the page and the paper quote: the records counted, the shares on multiples of 50 and 100 mL, and for each of
the two recorded values its 95% interval, mean and the weight of each rounding mode. Aggregates only.

A: positive recorded values per 5 mL up to 400 mL, with the model's density of true volumes (averaged over the
recordings' anaesthesia durations, as the model's marginal) scaled to the same number of records. B: the posterior
of the true volume for a recorded 100 mL and a recorded 260 mL, department unknown (the model's department shares),
stacked by the rounding mode that could have produced it.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

RECORDED = (100, 260)
XMAX = 400
ORDER = ["100 mL", "50 mL", "10 mL", "5 mL (base)"]
COL = {"100 mL": "#d7ece3", "50 mL": "#97cdb6", "10 mL": "#3f9f7d", "5 mL (base)": "#17604a"}
LAB = {"100 mL": "rounded to 100 mL", "50 mL": "rounded to 50 mL", "10 mL": "read to 10 mL", "5 mL (base)": "read to 5 mL"}
INK, MUTED, LAT, BAR = "#1b2333", "#5a6170", "#c0392b", "0.62"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("resolution", type=Path)
    ap.add_argument("release", type=Path)
    ap.add_argument("out", nargs="+")
    ap.add_argument("--summary", type=Path, required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(a.resolution))
    from vitaldb_resolution.engine import load_model
    M = load_model(str(a.resolution / "vitaldb_resolution" / "data" / "models" / "intraop_uo.model.json"))

    vals = []
    with open(a.release / "clinical_data.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            s = (r.get("intraop_uo") or "").strip()
            if s:
                vals.append(float(s))
    vals = np.array(vals)
    pos = vals[vals > 0]
    n = int(pos.size)
    cnt = np.bincount(np.round(pos).astype(int))

    # the model: density of true volumes (marginal over duration) and the posterior for each recorded value
    w = M.latent(M.spec["latent"].get("coefficients"), None, M.spec)
    dens = w / M.dx * n * 5                               # expected records per 5 mL with no rounding
    post = {}
    for v in RECORDED:
        comps, tot = [], 0.0
        for lab, rec, take in M.components(None, None):
            wm = w * take * (np.round(rec / M.ru) == v)
            if wm.sum() > 0:
                comps.append((lab, wm)); tot += wm.sum()
        p = M.posterior(v)
        post[v] = {"density": {lab: wm / tot / M.dx for lab, wm in comps}, "ci95": p["ci95"], "mean": p["mean"],
                   "components": p["components"]}

    summary = {
        "source": "clinical_data.csv intraop_uo; vitaldb-resolution intraop_uo model "
                  f"v{M.spec.get('model_version', M.spec.get('version', '?'))}",
        "records": int(vals.size), "positive": n, "zero": int((vals == 0).sum()),
        "shown_up_to_400_ml": int((pos <= XMAX).sum()),
        "share_on_multiples_of_100_pct": round(100 * float(np.mean(np.isclose(pos % 100, 0))), 1),
        "share_on_multiples_of_50_not_100_pct": round(100 * float(np.mean(np.isclose(pos % 50, 0) & ~np.isclose(pos % 100, 0))), 1),
        "recorded": {str(v): {"ci95_ml": [round(x, 1) for x in post[v]["ci95"]], "mean_ml": round(post[v]["mean"], 1),
                              "modes": [{"mode": c["component"], "weight_pct": round(100 * c["weight"], 1),
                                         "true_from_ml": c["lower"], "true_to_ml": c["upper"]}
                                        for c in post[v]["components"]]} for v in RECORDED},
    }
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    a.summary.write_text(json.dumps(summary, indent=1) + "\n")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 6.5, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
                         "ytick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
                         "axes.labelpad": 2, "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.labelcolor": INK})
    W, H = 6.3, 3.95
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([0.6 / W, 2.3 / H, 3.95 / W, 1.35 / H])
    v = np.arange(5, XMAX + 1, 5)
    c5 = np.array([cnt[i] if i < cnt.size else 0 for i in v])
    ax.bar(v, c5, width=3.6, color=BAR, lw=0)
    for r in RECORDED:
        ax.bar(r, cnt[r], width=3.6, color=INK, lw=0)
    m = (M.X >= 5) & (M.X <= XMAX)                       # from the smallest positive record (5 mL) up
    ax.plot(M.X[m], dens[m], color=LAT, lw=1)
    ax.set_xlim(0, XMAX + 5); ax.set_ylabel("records per 5 mL"); ax.set_xlabel("urine volume (mL)")
    ax.set_title("A  Recorded urine volumes in VitalDB, and the true volumes the model infers", loc="left", fontsize=7.2,
                 pad=3, color=INK)
    k150 = 150
    ax.annotate("digit preference: values\npile up on multiples of 50 mL", (k150, cnt[k150]), (185, c5.max() * 0.9),
                fontsize=6, color=INK, arrowprops=dict(arrowstyle="->", lw=0.6, color=INK))

    ax2 = fig.add_axes([0.6 / W, 0.5 / H, 3.95 / W, 1.2 / H], sharex=ax)
    x = M.X
    for r in RECORDED:
        mm = (x >= r - 60) & (x <= r + 60)
        base = np.zeros(mm.sum())
        for k in ORDER:
            if k in post[r]["density"]:
                y = post[r]["density"][k][mm]
                ax2.fill_between(x[mm], base, base + y, color=COL[k], lw=0, step="mid")
                base = base + y
        ax2.plot(x[mm], base, color=INK, lw=0.6, drawstyle="steps-mid")
        for a_ in (ax, ax2):
            a_.axvline(r, color=INK, lw=0.5, ls=":", zorder=0)
    yt = ax2.get_ylim()[1]
    lo, hi = post[100]["ci95"]
    ax2.text(100, yt * 0.55, f"recorded 100 mL\n{lo:.0f}–{hi:.0f} mL (95%)", ha="center", va="bottom", fontsize=6,
             color=INK, bbox=dict(fc="white", ec="none", pad=0.5))
    lo, hi = post[260]["ci95"]
    ax2.text(272, yt * 0.75, f"recorded 260 mL\n{lo:.0f}–{hi:.0f} mL (95%)", ha="left", va="center", fontsize=6,
             color=INK)
    ax2.set_yticks([]); ax2.set_ylabel("PDF of the\ntrue volume"); ax2.set_xlabel("urine volume (mL)")
    ax2.tick_params(labelbottom=True)
    ax2.set_title("B  What two recorded values mean: the PDF of the true volume, by how it was charted", loc="left",
                  fontsize=7.2, pad=3, color=INK)
    fig.legend(handles=[Patch(color=BAR, label="recorded values"), Patch(color=INK, label="the two values in B"),
                        Line2D([], [], color=LAT, lw=1, label="true volumes (model)")]
               + [Patch(color=COL[k], label=LAB[k]) for k in ORDER],
               loc="upper left", bbox_to_anchor=(4.7 / W, 3.6 / H), frameon=False, fontsize=6, handlelength=1.6)
    for out in a.out:
        fig.savefig(out, dpi=200 if out.endswith(".png") else None)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
