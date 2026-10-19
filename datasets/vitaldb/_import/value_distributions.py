"""Distribution figures for the clinical and lab variables, and observed-against-model figures for the value models.

    python datasets/vitaldb/_import/value_distributions.py <vitaldb-resolution repo> <VitalDB release folder>

Writes, aggregates only:

- figures/distributions/<variable id>.png: the recorded values of each clinical and lab variable in the release.
  Numeric values one bar per possible recorded value, at the adopted resolution or the finest gap actually used
  (coarser bins only when that would exceed 4,000), cut to the 0.5-99.5th
  percentiles with the counts outside stated; categories as bars (the 12 most common).
- figures/models/<variable id>.png for each fitted value model: the recorded values against what the model
  predicts they should be (its rounding rules applied to its true-value density), so heaps show as spikes the
  model reproduces; for charted times, the minute past the hour.
- figures/distributions/manifest.json: per figure, its file, n and summary numbers (read by _import/resolution.py,
  which adds the figures to the generated variable and study pages).

Run _import/resolution.py afterwards. No record values or identifiers are written beyond binned counts.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
OUT_D = HERE / "figures" / "distributions"
OUT_M = HERE / "figures" / "models"
INDIGO, ORANGE, GREY = "#3f51b5", "#e65100", "#9e9e9e"


def atlas_id(name: str) -> str:
    """The atlas id for a vitaldb-resolution variable name."""
    return {"caseend": "case-end"}.get(name, re.sub(r"[^a-z0-9]+", "-", name.lower().replace("%", "-pct")).strip("-"))


def finest_step(x) -> float | None:
    """The smallest gap between distinct recorded values: the finest resolution actually used."""
    u = np.unique(np.round(x[np.isfinite(x)], 6))
    d = np.diff(u)
    d = d[d > 1e-9]
    return float(np.round(d.min(), 6)) if d.size else None


def numeric_hist(ax, x, step, unit, plt):
    """Counts at the variable's resolution, one bar per possible recorded value, so heaping shows as spikes.

    The bin width is the adopted resolution (registry, or the model's base step), or else the finest gap between
    recorded values. Only when that would give more than 4,000 bins (a time in seconds, say) are coarser bins used.
    """
    x = x[np.isfinite(x)]
    lo, hi = np.percentile(x, [0.5, 99.5])
    inside = x[(x >= lo) & (x <= hi)]
    step = step or finest_step(inside)
    if step and step > 0 and (hi - lo) / step <= 4000:
        k = np.round(inside / step).astype(np.int64)
        k0 = k.min()
        counts = np.bincount(k - k0)
        centres = (np.arange(counts.size) + k0) * step
        nz = counts > 0
        if nz.sum() <= 150:
            ax.bar(centres[nz], counts[nz], width=step * 0.8, color=INDIGO, linewidth=0)
        else:
            ax.vlines(centres[nz], 0, counts[nz], color=INDIGO, lw=0.7)
        ax.set_ylim(0, counts.max() * 1.05)
        binning = step
    else:
        ax.hist(inside, bins=np.histogram_bin_edges(inside, bins=120), color=INDIGO, linewidth=0)
        binning = None
    ax.axvline(np.median(x), color=ORANGE, lw=1, ls="--", label=f"median {np.median(x):.4g}")
    ax.set_xlabel(f"recorded value ({unit})" if unit else "recorded value")
    ax.set_ylabel("records" + (f" per {binning:g} {unit}".rstrip() if binning else ""))
    ax.legend(frameon=False, fontsize=7)
    return {"n": int(x.size), "median": float(np.median(x)), "p05": float(lo), "p995": float(hi),
            "outside": int(x.size - inside.size), "bin": binning}


def main(repo: str, release: str) -> None:
    """Draw the recorded-value distribution figures for the variable pages (aggregates only)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    sys.path.insert(0, repo)
    from vitaldb_resolution.engine import Model, load_model

    plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
    OUT_D.mkdir(parents=True, exist_ok=True)
    OUT_M.mkdir(parents=True, exist_ok=True)
    reg = json.loads((Path(repo) / "vitaldb_resolution/data/registry.json").read_text())["variables"]
    clinical = pd.read_csv(Path(release) / "clinical_data.csv")
    lab = pd.read_csv(Path(release) / "lab_data.csv", usecols=["name", "result"])
    manifest = {"variables": {}, "models": {}}
    for name, v in reg.items():
        if v["type"] == "identifier":
            continue
        vid = atlas_id(name)
        unit = v.get("unit") or ""
        if v["source"] == "lab":
            x = pd.to_numeric(lab.loc[lab["name"] == name, "result"], errors="coerce").to_numpy(float)
        elif name in clinical:
            x = clinical[name]
        else:
            continue  # derived intervals are not stored; their inputs are
        fig, ax = plt.subplots(figsize=(6, 2.6))
        if v["method"] == "not_applicable" or v["type"] in ("categorical", "binary"):
            vc = pd.Series(x).dropna().astype(str).value_counts()
            top = vc.head(12)[::-1]
            ax.barh([t[:40] for t in top.index], top.values, color=INDIGO)
            ax.set_xlabel("records")
            info = {"n": int(vc.sum()), "categories": int(vc.size), "shown": int(top.size)}
            title = f"{name}: {info['n']:,} records, {info['categories']} categories" + (
                " (12 most common shown)" if vc.size > 12 else "")
        else:
            xs = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy(float)
            if v.get("zero_status"):
                xs = xs[xs != 0]
            xs = xs[np.isfinite(xs)]
            if xs.size < 20:
                plt.close(fig)
                continue
            step = v.get("resolution") if isinstance(v.get("resolution"), (int, float)) else None
            if step is None and v.get("model"):   # the model's base step: its record unit
                try:
                    mm = load_model(str(Path(repo) / "vitaldb_resolution/data/models" / v["model"]))
                    step = getattr(mm, "spec", {}).get("record_unit") if not isinstance(mm, dict) else None
                except Exception:  # noqa: BLE001
                    step = None
            if v["type"] in ("timestamp", "device_time", "date"):
                step = None
            info = numeric_hist(ax, xs, step, unit, plt)
            title = f"{name}: {info['n']:,} records" + (f" ({info['outside']:,} outside the 0.5–99.5th percentiles not shown)"
                                                        if info["outside"] else "")
        ax.set_title(title, fontsize=8, loc="left")
        fig.tight_layout()
        fig.savefig(OUT_D / f"{vid}.png", dpi=130)
        plt.close(fig)
        manifest["variables"][vid] = {"file": f"distributions/{vid}.png", "source": v["source"], **info}

        if not v.get("model"):
            continue
        m = load_model(str(Path(repo) / "vitaldb_resolution/data/models" / v["model"]))
        xs = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy(float)
        xs = xs[np.isfinite(xs)]
        fig, ax = plt.subplots(figsize=(6.5, 2.8))
        if isinstance(m, Model):
            spec = m.spec
            ru = spec.get("record_unit", 1)
            if spec.get("truncation", {}).get("exclude_recorded_zero"):
                xs = xs[xs > 0]
            k = np.round(xs / ru).astype(int)
            covs = [c.get("name") for c in json.loads(json.dumps(spec)).get("latent", {}).get("covariates", [])] \
                if isinstance(spec.get("latent"), dict) else []
            names = set(spec.get("required_covariates") or []) | set(covs)
            if names:
                rows = clinical.dropna(subset=[c for c in names if c in clinical]).sample(n=min(400, len(clinical)),
                                                                                       random_state=0)
                q = None
                for _, row in rows.iterrows():
                    try:
                        p = m.pmf(cov={c: row[c] for c in names if c in row})
                    except Exception:  # noqa: BLE001
                        continue
                    q = p if q is None else q[: p.size] + p[: q.size]
                q = q / q.sum() if q is not None else None
            else:
                q = m.pmf()
            lo, hi = np.percentile(k, [0.5, 99.5]).astype(int)
            idx = np.arange(lo, hi + 1)
            kin = k[(k >= lo) & (k <= hi)]                      # values outside are left out, not piled at the ends
            obs = np.bincount(kin - lo, minlength=idx.size)[: idx.size]
            ax.vlines(idx * ru, 0, obs, color=INDIGO, lw=0.8, label="recorded")
            if q is not None:
                pred = q[idx] / q[idx].sum() * obs.sum()
                keep = pred > 0.02 * max(pred.max(), 1e-12)        # values the model can produce
                ax.plot((idx * ru)[keep], pred[keep], ".", ms=2.5, color=ORANGE,
                        label="model: rounding rules on the true-value density")
            ax.set_xlabel(f"recorded value ({spec.get('unit', unit)})")
            ax.set_ylabel("records")
            ax.set_title(f"{name}: {kin.size:,} of {k.size:,} records (0.5–99.5th percentiles) against the fitted model",
                         fontsize=8,
                         loc="left")
            ax.legend(frameon=False, fontsize=7)
        elif isinstance(m, dict):  # derived: no separate figure
            plt.close(fig)
            continue
        else:  # timestamp: minute past the hour of the charted clock time (seconds from casestart + the case clock)
            # the charted clock minute: (-adm + 60 * ceil(t / 60)) mod 1 day, t in seconds from casestart
            tod = (-clinical["adm"] + 60 * np.ceil(clinical[name] / 60)) % 86400
            minute = ((tod // 60) % 60).dropna().astype(int)
            counts = np.bincount(minute, minlength=60)
            ax.bar(np.arange(60), counts, color=[ORANGE if i % 5 == 0 else INDIGO for i in range(60)], width=0.8)
            ax.set_xlabel("minute past the hour of the charted time (multiples of 5 in orange)")
            ax.set_ylabel("records")
            ax.set_title(f"{name}: {int(counts.sum()):,} charted times; a flat clock would put 1/60 on each minute",
                         fontsize=8, loc="left")
        fig.tight_layout()
        fig.savefig(OUT_M / f"{vid}.png", dpi=130)
        plt.close(fig)
        manifest["models"][vid] = {"file": f"models/{vid}.png"}
    (OUT_D / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(len(manifest["variables"]), "distribution figures;", len(manifest["models"]), "model figures")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
