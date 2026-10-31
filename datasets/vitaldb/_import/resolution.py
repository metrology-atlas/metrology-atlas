"""Import vitaldb-resolution into the atlas: pin a snapshot, and generate its variables and model studies.

    python datasets/vitaldb/_import/resolution.py ../vitaldb/vitaldb-resolution

1. Copies the library's registry and model files into ``_sources/vitaldb-resolution/`` (same paths as in the
   repository) and records the commit in ``_sources/vitaldb-resolution/SOURCE.yaml``. The snapshot is never
   edited by hand; run this again to refresh it, then update ``sources`` in dataset.yaml from SOURCE.yaml.
2. Writes ``_generated/variables/<id>.yaml`` for every registry variable (identifiers left out) and
   ``_generated/studies/value-model-<id>.yaml`` for every fitted model. These are rewritten on every run: add or
   change prose with a hand-written file of the same id in ``variables/`` or ``studies/``, whose fields win.

Model numbers (rounding modes, shares, fits) are not copied into YAML: pages read them from the snapshot.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1]))
from metrology_atlas.readers import vitaldb_resolution as summarise

SNAP = HERE / "_sources" / "vitaldb-resolution"
GEN = HERE / "_generated"
DATA = "vitaldb_resolution/data"


ALIASES = {"caseend": "case-end"}
"""Registry names whose atlas variable already exists under another id (the generated file merges into it)."""
TIME_GROUP = {"anestart": "emr-events", "opstart": "emr-events", "aneend": "emr-events", "opend": "emr-events",
              "adm": "admission-discharge", "dis": "admission-discharge"}
"""Variables whose time is described, for now, on a shared page."""


_G = {
    "Clinical record/Times and durations": "casestart caseend anestart opstart aneend opend adm dis ind_to_incision "
                                           "op_duration ane_duration emergence",
    "Clinical record/Patient": "age sex height weight bmi asa emop",
    "Clinical record/Outcome": "death_inhosp los icu_days",
    "Clinical record/Operation and anaesthesia": "department optype dx opname approach position ane_type",
    "Clinical record/Preoperative history": "preop_htn preop_dm preop_ecg preop_pft",
    "Clinical record/Airway and lines": "cormack airway tubesize dltubesize lmasize iv1 iv2 aline1 aline2 cline1 cline2",
    "Clinical record/Fluids and blood": "intraop_uo intraop_ebl intraop_crystalloid intraop_colloid intraop_rbc intraop_ffp",
    "Clinical record/Drugs": "intraop_ppf intraop_ftn intraop_eph intraop_phe intraop_ca intraop_rocu intraop_mdz "
                             "intraop_vecu intraop_epi",
    "Laboratory/Preoperative labs": "preop_hb preop_plt preop_pt preop_aptt preop_na preop_k preop_gluc preop_alb "
                                    "preop_ast preop_alt preop_bun preop_cr preop_ph preop_hco3 preop_be preop_pao2 "
                                    "preop_paco2 preop_sao2",
    "Laboratory/Blood gas": "ph pco2 po2 hco3 be sao2 lac",
    "Laboratory/Electrolytes and glucose": "na k cl ica p gluc",
    "Laboratory/Haematology": "hb hct plt wbc esr",
    "Laboratory/Coagulation": "aptt pt% ptinr ptsec fib",
    "Laboratory/Chemistry": "alb alt ast ammo bun ccr cr crp gfr tbil tprot",
    "Laboratory/Result times": "lab_dt",
}
GROUP = {name: g for g, names in _G.items() for name in names.split()}
"""Where each registry variable is listed on the site."""



LAB = "laboratory result (lab table)"
PREOP = "preoperative laboratory result, copied into the clinical table"
GAS_NOTE = ("The lab table does not record the sample site; intraoperative gases are taken mostly from the arterial "
            "line (to check per record).")
MEASURES = {   # registry name -> the measurand it measures (schema 0.4), with its method and any note
    **{k: (m, LAB) for k, m in (("hb", "haemoglobin"), ("hct", "haematocrit"), ("alb", "albumin"), ("alt", "alt"),
                                ("ast", "ast"), ("aptt", "aptt"), ("be", "base-excess"), ("bun", "bun"),
                                ("cr", "creatinine"), ("gluc", "glucose"), ("hco3", "bicarbonate"), ("k", "potassium"),
                                ("na", "sodium"), ("ph", "ph"), ("plt", "platelet-count"))},
    **{"preop_" + k: (m, PREOP) for k, m in (("hb", "haemoglobin"), ("alb", "albumin"), ("alt", "alt"), ("ast", "ast"),
                                             ("aptt", "aptt"), ("be", "base-excess"), ("bun", "bun"),
                                             ("cr", "creatinine"), ("gluc", "glucose"), ("hco3", "bicarbonate"),
                                             ("k", "potassium"), ("na", "sodium"), ("ph", "ph"),
                                             ("plt", "platelet-count"), ("pao2", "arterial-o2-tension"),
                                             ("paco2", "arterial-co2-tension"))},
    "po2": ("arterial-o2-tension", "blood gas (lab table)", GAS_NOTE),
    "pco2": ("arterial-co2-tension", "blood gas (lab table)", GAS_NOTE),
    "sao2": ("arterial-o2-saturation", "blood gas (lab table)", GAS_NOTE),
    "preop_sao2": ("arterial-o2-saturation", PREOP,
                   "VitalDB describes it as SpO2, but it is recorded to 0.1 % like the lab data, and sits with the "
                   "preoperative blood-gas values; a pulse oximeter shows whole percent. Taken as SaO2."),
}
MEASURES_EXTRA = {"preop_plt": {"unit": "x1000/mcL", "conversion": "none: the same unit, written with an x"}}

TITLE_FIX = {"icu_days": "ICU days", "preop_ecg": "Preoperative ECG"}   # registry descriptions without proper capitals

def atlas_id(name: str) -> str:
    """The atlas id for a vitaldb-resolution variable name."""
    if name in ALIASES:
        return ALIASES[name]
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("%", "-pct")).strip("-")


def resolution_text(v: dict) -> str | None:
    """A short text for a variable's resolution (step and rounding anchor), or None."""
    m, unit = v["method"], v.get("unit") or ""
    if m == "uniform" and v.get("resolution") is not None:
        return f"{v['resolution']:g} {unit}, {v.get('anchor', 'nearest')}".replace("  ", " ")
    if m == "exact":
        return "exact"
    if m == "source_dependent":
        return "by analyser: " + ", ".join(f"{k} {r:g} {unit}" for k, r in v["resolution_by_source"].items())
    if m == "decimal_dependent":
        return f"{v['resolution_if_decimal']:g} {unit} when a decimal is recorded, else {v['resolution_if_whole']:g} {unit}"
    if m == "triangular_count":
        return f"whole {unit}, counting rule unknown (±{v.get('half_width', 1)})"
    if m == "age":
        return "completed years; tenths for infants; top-coded"
    if m == "neighbours":
        return "computed value: interval to the neighbouring reachable values"
    if m in ("model", "timestamp_model"):
        return "heaped: a mixture of rounding modes (see the value model)"
    if m == "derived":
        return "derived from " + ", ".join(v.get("inputs") or [])
    return None


def main(repo: str) -> None:
    """Snapshot vitaldb-resolution at `repo` into _sources and regenerate the variables and value-model studies."""
    repo = Path(repo).resolve()
    commit = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%H %cs"], capture_output=True,
                            text=True, check=True).stdout.split()
    (SNAP / DATA / "models").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / DATA / "registry.json", SNAP / DATA / "registry.json")
    for f in sorted((repo / DATA / "models").glob("*.json")):
        shutil.copy2(f, SNAP / DATA / "models" / f.name)
    if (repo / DATA / "models" / "archive").is_dir():          # earlier versions of each model (from v0.6.0)
        (SNAP / DATA / "models" / "archive").mkdir(parents=True, exist_ok=True)
        for f in sorted((repo / DATA / "models" / "archive").glob("*.json")):
            shutil.copy2(f, SNAP / DATA / "models" / "archive" / f.name)
    for lock in (repo / "models.lock", repo / DATA / "models.lock", repo / DATA / "models" / "models.lock"):
        if lock.is_file():
            shutil.copy2(lock, SNAP / lock.relative_to(repo))
    (SNAP / "SOURCE.yaml").write_text(yaml.safe_dump({"software": "vitaldb-resolution", "commit": commit[0],
                                                      "date": dt.date.fromisoformat(commit[1])}, sort_keys=False), encoding="utf-8")
    full = json.loads((SNAP / DATA / "registry.json").read_text(encoding="utf-8"))
    reg, methods = full["variables"], full.get("methods") or {}
    for kind in ("variables", "studies"):
        (GEN / kind).mkdir(parents=True, exist_ok=True)
        for old in (GEN / kind).glob("*.yaml"):
            old.write_text("", encoding="utf-8")  # emptied, not deleted (deletion may not be allowed here)
    sp = SNAP / "spread.json"   # written by resolution_spread.py; kept across refreshes of the same commit
    spread_doc = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    spread = spread_doc.get("variables", {}) if spread_doc.get("commit") == commit[0] else {}
    if sp.exists() and not spread:
        print("spread.json is from another commit: run resolution_spread.py again")
    mf = HERE / "figures" / "distributions" / "manifest.json"   # written by value_distributions.py
    figs = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {"variables": {}, "models": {}}
    n_var = n_study = 0
    for name, v in reg.items():
        if v["type"] == "identifier":
            continue
        vid = atlas_id(name)
        title = (v.get("description") or "").split(";")[0].strip() or name.replace("_", " ")
        title = title if title[1:2].isupper() else title[0].upper() + title[1:]   # keep "pH"
        title = TITLE_FIX.get(name, title)
        timed = v["type"] in ("timestamp", "device_time", "date")
        item = {
            "id": vid, "name": title,
            "summary": (v.get("description") or title) + f" ({v['source']} table).",
            "type": "time" if timed else ("lab" if v["source"] == "lab" else "clinical"),
            "source_name": name,
            "group": GROUP.get(name),
            "source": {"clinical": "clinical_data.csv", "lab": "lab_data.csv"}.get(v["source"], v["source"]),
            "unit": v.get("unit") or None,
            "value": {"kind": f"{v['method']}: {methods[v['method']]}" if v["method"] in methods else v["method"], "resolution": resolution_text(v),
                      "step": v.get("resolution") if isinstance(v.get("resolution"), (int, float)) else None,
                      "anchor": v.get("anchor") if v.get("anchor") in ("nearest", "floor", "ceiling") else None,
                      "anchor_basis": v.get("anchor_basis") if v.get("anchor_basis") in ("tested", "convention", "assumption", "open") else None,
                      "anchor_note": v.get("anchor_note") or None},
            "tags": ["generated", "vitaldb-resolution"],
        }
        desc = [v["evidence"]] if v.get("evidence") else []
        if name in TIME_GROUP:
            desc.append(f"How its time was recorded is described with [[variable:{TIME_GROUP[name]}]].")
        elif v["source"] == "lab":
            desc.append("Its time is the lab system's result time: see [[variable:lab-blood-gas]] and "
                        "[[variable:lab-central]].")
        if desc:
            item["description"] = "\n\n".join(desc)
        if v["source"] == "lab" or v["type"] == "timestamp":
            item["stamp_clock"] = "hospital-records"
        elif v["type"] == "device_time":
            item["stamp_clock"] = "recorder-pc"
        if timed:
            item["coupling"] = {"status": "coupled", "note": "The value is itself a time: its value side and its "
                                                            "time side are the same uncertainty."}
        fv = figs["variables"].get(vid)
        if fv:
            if "categories" in fv:
                cap = (f"Recorded values in the release: {fv['n']:,} records in {fv['categories']} categories"
                       + (f" ({fv['shown']} most common shown)." if fv["categories"] > fv["shown"] else "."))
            else:
                cap = (f"Recorded values in the release: {fv['n']:,} records, median {fv['median']:.4g}"
                       + (f" {v.get('unit')}" if v.get("unit") else "") + "; "
                       + (f"{fv['outside']:,} outside the 0.5–99.5th percentiles are not shown." if fv["outside"]
                          else "all shown."))
            item["figures"] = [{"id": "distribution", "file": fv["file"], "theme": "distributions of recorded values",
                                "source": "metrology-atlas datasets/vitaldb/_import/value_distributions.py",
                                "caption": cap, "alt": f"Histogram of the recorded values of {name}."}]
        if v["method"] == "derived":
            item["origin"] = "derived"
            item["derived_from"] = [{"variable": atlas_id(x), "relation": "computed-from"} for x in v.get("inputs") or []]
            item["value"]["formula"] = v.get("formula")
            item["value"]["combination"] = v.get("distribution")
        if name in MEASURES:
            m, method, *note = MEASURES[name]
            item["measures"] = [{"measurand": m, "method": method, **MEASURES_EXTRA.get(name, {}),
                                 **({"note": note[0]} if note else {})}]
        if name in spread:
            item["value"]["spread"] = f"vitaldb-resolution/spread.json#{name}"
        if v.get("model"):
            ref = f"vitaldb-resolution/{DATA}/models/{v['model']}"
            sid = f"value-model-{vid}"
            item["value"]["model"] = ref
            item["value"]["status"] = "measured"
            item["value"]["studies"] = [sid]
            m = summarise(json.loads((SNAP / DATA / "models" / v["model"]).read_text(encoding="utf-8")))
            modes = [x["label"] for x in m["modes"]]
            if m["kind"] == "derived":
                study_name, summary = (f"{title}, derived from its inputs",
                                       f"{title} computed from the posteriors of {', '.join(v.get('inputs') or [])}.")
            elif m["kind"] == "timestamp":
                study_name = f"How the {title.lower()} was charted"
                summary = (f"The charted {title.lower()} is a mixture of {len(modes)} ways of writing a clock "
                           f"time ({', '.join(modes)}), modelled as an offset from a device time.")
            else:
                study_name = f"Rounding and heaping of {title.lower()}"
                summary = (f"Recorded {title.lower()} is a mixture of {len(modes)} rounding modes "
                           f"({', '.join(modes)}); the model gives the true value's distribution for each record.")
            study = {
                "id": sid, "name": study_name, "summary": summary, "date": dt.date.fromisoformat(str(m["fit"]["date"] or commit[1])[:10]),
                "status": "current", "methods": ["value-resolution"] + (["clinical-time"] if m["kind"] == "timestamp" else []),
                "variables": [vid], "model": ref,
                "data": f"{m['fit']['n']:,} records of {name}" + (f" ({m['fit']['source']})" if m["fit"].get("source") else "")
                        if m["fit"].get("n") else None,
                "code": ["vitaldb-resolution/vitaldb_resolution/engine.py"],
                "tags": ["generated", "vitaldb-resolution"],
            }
            fm = figs["models"].get(vid)
            if fm:
                timed_model = m["kind"] == "timestamp"
                study["figures"] = [{
                    "id": "observed-vs-model", "file": fm["file"], "theme": "heaping",
                    "source": "metrology-atlas datasets/vitaldb/_import/value_distributions.py",
                    "caption": ("The minute past the hour of every charted time: the heaps on multiples of 5, and at "
                                "the standard first-case times, are the rounding modes the model fits." if timed_model else
                                "Every recorded value (blue lines) against what the fitted model predicts (orange dots): "
                                "its rounding rules applied to its true-value density. Heaps on round numbers are the "
                                "rounding modes."),
                    "alt": ("Bar chart of charted times by minute past the hour, with tall bars on multiples of five."
                            if timed_model else "Spike histogram of recorded values with model predictions overlaid; "
                            "spikes on round numbers.")}]
            if fm:
                study["results"] = "[[figure:observed-vs-model]]"
            study = {k: x for k, x in study.items() if x is not None}
            (GEN / "studies" / f"{sid}.yaml").write_text(yaml.safe_dump(study, sort_keys=False, allow_unicode=True,
                                                                        width=118), encoding="utf-8")
            n_study += 1
        item["value"] = {k: x for k, x in item["value"].items() if x is not None}
        item = {k: x for k, x in item.items() if x is not None}
        (GEN / "variables" / f"{vid}.yaml").write_text(yaml.safe_dump(item, sort_keys=False, allow_unicode=True,
                                                                     width=118), encoding="utf-8")
        n_var += 1
    print(f"snapshot {commit[0][:10]} ({commit[1]}); {n_var} variables, {n_study} model studies")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(HERE.parents[2] / "vitaldb" / "vitaldb-resolution"))
