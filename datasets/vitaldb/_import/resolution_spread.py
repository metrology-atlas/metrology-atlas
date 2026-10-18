"""How wide each variable's true-value distribution is in the release: aggregates from the pinned vitaldb-resolution.

    python datasets/vitaldb/_import/resolution_spread.py <vitaldb-resolution repo> <VitalDB release folder>

Evaluates every registry variable for every row of clinical_data.csv (and every lab_data.csv row of 600 cases
drawn at random with a fixed seed, so panels stay whole) with the library at the snapshot's commit, and writes, per variable, only aggregates: how
many records have a distribution, the median and p10-p90 of its standard deviation, of its 95% interval width,
and of its mean minus the recorded value. Output: _sources/vitaldb-resolution/spread.json. Resumable: a run that
hits its time budget keeps what it has and the next run continues. No record values or identifiers are written.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "_sources" / "vitaldb-resolution" / "spread.json"
BUDGET = 90


def agg(x) -> dict:
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], float)
    if not x.size:
        return {}
    return {"median": float(np.median(x)), "p10": float(np.percentile(x, 10)), "p90": float(np.percentile(x, 90))}


def _stats(d):
    """(sd, 95% width, mean minus recorded) of one distribution, or None; the distribution itself is dropped."""
    if getattr(d, "status", None) != "ok":
        return None
    try:
        lo, hi = d.interval(0.95)
        rec = d.recorded_value
        return (d.std(), hi - lo, d.mean() - float(rec) if isinstance(rec, (int, float)) else None)
    except Exception:  # noqa: BLE001
        return None


def main(repo: str, release: str) -> None:
    import pandas as pd

    sys.path.insert(0, repo)
    import vitaldb_resolution as vr

    commit = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%H"], capture_output=True, text=True).stdout.strip()
    import yaml

    snap = yaml.safe_load((HERE / "_sources" / "vitaldb-resolution" / "SOURCE.yaml").read_text())["commit"]
    if commit != snap:
        sys.exit(f"the repository is at {commit[:10]}, the snapshot at {snap[:10]}: refresh the snapshot first")
    done = json.loads(OUT.read_text()) if OUT.exists() else {"commit": commit, "variables": {}}
    if done.get("commit") != commit:
        done = {"commit": commit, "variables": {}}
    reg = vr.load()
    clinical = pd.read_csv(Path(release) / "clinical_data.csv")
    lab = pd.read_csv(Path(release) / "lab_data.csv", usecols=["caseid", "dt", "name", "result"])
    keep = lab["caseid"].drop_duplicates().sample(n=600, random_state=0)
    lab = lab[lab["caseid"].isin(keep)].reset_index(drop=True)   # whole panels of 600 random cases
    lab_by_name: dict[str, list] | None = None
    variables = json.loads((Path(repo) / "vitaldb_resolution/data/registry.json").read_text())["variables"]
    t0 = time.time()
    for name, v in variables.items():
        if name in done["variables"] or v["method"] == "not_applicable":
            continue
        if time.time() - t0 > BUDGET:
            break
        sd, width, shift, n_all, n_ok = [], [], [], 0, 0
        try:
            if v["source"] == "lab":
                if lab_by_name is None:
                    lab_by_name = {}
                    for nm, d in zip(lab["name"], reg.lab_distributions(lab)):
                        lab_by_name.setdefault(nm, []).append(_stats(d))
                chunks = [lab_by_name.get(name, [])]
            else:
                chunks = ([_stats(d) for d in reg.distributions(name, clinical.iloc[i:i + 400])]
                          for i in range(0, len(clinical), 400))
            for chunk in chunks:
                for st in chunk:
                    n_all += 1
                    if st is None:
                        continue
                    n_ok += 1
                    sd.append(st[0]); width.append(st[1]); shift.append(st[2])
        except Exception as ex:  # noqa: BLE001 - recorded, not fatal
            done["variables"][name] = {"error": f"{type(ex).__name__}: {ex}"[:200]}
            continue
        done["variables"][name] = {"records": n_all, "with_distribution": n_ok, "sd": agg(sd),
                                   "width95": agg(width), "mean_minus_recorded": agg(shift),
                                   "rows": "every lab row of 600 random cases" if v["source"] == "lab" else "all clinical rows"}
    OUT.write_text(json.dumps(done, indent=1) + "\n", encoding="utf-8")
    left = sum(1 for n, v in variables.items() if n not in done["variables"] and v["method"] != "not_applicable")
    print(f"{len(done['variables'])} variables done, {left} left")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
