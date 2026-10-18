"""Generate the scale-factor and resolution tables on the device pages from the signal survey's tables.

    python datasets/vitaldb/_import/device_tracks.py C:/vitalDB/work/signal_survey

Reads (made by vitaldb-bench tools, kept in the work folder, not in the atlas):
  tables/meta_*.parquet            gain and offset of every waveform track in every recording (signal_events_collect)
  agg_events/resolution.json       observed span and step of every waveform (signal_events_agg resolution)
  records/<case>.npz               units of waveform tracks (record_scan)
  numeric_agg/numerics.csv         numeric tracks: unit, format, recordings, median interval (numeric_agg merge)
  numeric_agg/numeric_resolution.csv   numeric grids and robust ranges (numeric_agg resolution)
Writes _generated/devices/<device>.yaml with `id` and `tracks` only; the hand-written device file supplies the rest.
Converter estimates, corrections and rounding results are stated below, each with its evidence.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1]
DEVICE = {"SNUADC": "snuadc", "Primus": "primus", "BIS": "bis", "CardioQ": "cardioq", "Solar8000": "solar8000",
          "Orchestra": "orchestra", "EV1000": "ev1000", "Vigileo": "vigileo", "Vigilance": "vigilance",
          "Invos": "invos", "FMS": "fms"}

SNU = "every code of 0–1023 used by ECG, none above; documented as 12-bit ([[observation:snuadc-ten-bit-codes]])"
CONVERTER = {
    "SNUADC/ECG_II": ("10 bits", SNU), "SNUADC/ECG_V5": ("10 bits", SNU),
    "SNUADC/ART": ("10 bits", "the SNUADC converter (see ECG)"), "SNUADC/CVP": ("10 bits", "the SNUADC converter (see ECG)"),
    "SNUADC/FEM": ("10 bits", "the SNUADC converter (see ECG)"), "SNUADC/PLETH": ("10 bits", "the SNUADC converter (see ECG)"),
    "Primus/CO2": ("probably 12 bits", "rare values up to code 4046 in CO2 and AWP, inside 0–4095"),
    "Primus/AWP": ("probably 12 bits", "rare values up to code 4046 in CO2 and AWP, inside 0–4095"),
    "BIS/EEG1_WAV": ("16 bits", "all 65,536 steps of 0.05 µV between −1476.70 and +1800.05 used, none outside"),
    "BIS/EEG2_WAV": ("16 bits", "all 65,536 steps of 0.05 µV between −1476.70 and +1800.05 used, none outside"),
    "CardioQ/FLOW": ("unknown", "a 9-bit segmented code, steps 1, 2 and 4 ([[observation:cardioq-flow-segmented]])"),
    "CardioQ/ABP": ("unknown, at least 10 bits", "whole mmHg over 515 values: a display resolution"),
}
STEP_NOTE = {"CardioQ/FLOW": "1 (0–255), 2 (256–510), 4 (512–1016)"}
# (track, stored gain, stored offset) -> (gain, offset, why)
CORRECTION = {
    ("Primus/CO2", 0.1, 0.0): (0.075, 0.0, "ETCO2 check ([[observation:primus-waveform-gains|evidence]])"),
    ("Primus/AWP", 0.1064, -22.0): (0.1, -20.0, "PIP check ([[observation:primus-waveform-gains|evidence]])"),
    ("Primus/AWP", 0.01, 0.0): (0.1, -20.0, "PIP check ([[observation:primus-waveform-gains|evidence]])"),
    ("SNUADC/ART", 0.394983, -198.2504): (0.987457, -495.626,
                                          "PLETH factors ([[observation:art-with-pleth-factors|evidence]])"),
}
ROUNDING = {"Solar8000/HR": "truncate ([[observation:hr-truncated]])",
            "Primus/RR_CO2": "round ([[study:numeric-derivation-pilot]])",
            "Primus/ETCO2": "round, likely ([[study:track-value-resolution]])",
            "Primus/PIP_MBAR": "round, likely ([[study:track-value-resolution]])",
            "Primus/MAWP_MBAR": "round, likely ([[study:track-value-resolution]])"}


def plain(v):
    """numpy scalars to plain Python, for YAML."""
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def sig(x: float) -> float:
    return float(f"{x:.6g}")


def waveform_units(root: Path) -> dict:
    units = {}
    for f in sorted((root / "records").glob("*.npz"))[:200]:
        z = np.load(f)
        for k in z.files:
            if k.endswith("|meta"):
                m = json.loads(str(z[k]))
                if "fs" in m:
                    units.setdefault(k[:-5].replace("__", "/"), m.get("unit"))
    return units


def main(root: Path) -> None:
    meta = pd.concat([pd.read_parquet(f) for f in glob.glob(str(root / "tables" / "meta_*.parquet"))])
    meta = meta[~meta.track.str.contains("#")]
    meta["track"] = meta.track.str.replace("__", "/")
    meta["g"] = meta.gain.map(sig); meta["o"] = meta.offset.map(sig)
    res = json.loads((root / "agg_events" / "resolution.json").read_text())
    units = waveform_units(root)
    out: dict[str, list] = {}
    for (tr, g, o), grp in meta.groupby(["track", "g", "o"]):
        r = res.get(tr.replace("/", "__"), {})
        dev = DEVICE.get(tr.split("/")[0])
        if dev is None:
            continue
        key = next((k for k in CORRECTION if k[0] == tr and sig(k[1]) == g and sig(k[2]) == o), None)
        g_true = CORRECTION[key][0] if key else g   # the step in physical units uses the corrected gain
        step = STEP_NOTE.get(tr) or (f"{sig(r['step'] * g_true):g}" + (" (corrected)" if key else "")
                                     if r.get("step") else None)
        conv, ev = CONVERTER.get(tr, (None, None))
        e = {"track": tr.split("/", 1)[1], "kind": "waveform", "unit": units.get(tr) or None,
             "format": str(grp.format.iloc[0]), "rate": f"{grp.fs.median():g} Hz", "gain": g, "offset": o,
             "recordings": int(grp.case.nunique()),
             "step": step,
             "span": (f"codes {r['core_min']:g}–{r['core_max']:g} ({r['core_codes_used']:,} used)"
                      + (f"; {r['outlier_samples']} corrupt samples outside" if r.get("outlier_samples") else ""))
             if r else None,
             "bits_to_store": r.get("bits_to_store_span"), "converter": conv, "evidence": ev}
        if tr == "CardioQ/FLOW":
            e["bits_to_store"] = 9
            e["span"] = "values 0–1016 (509 used): codes of a 9-bit segmented scale"
        if key:
            cg, co, why = CORRECTION[key]
            e.update(corrected_gain=cg, corrected_offset=co, correction=why)
        out.setdefault(dev, []).append({k: plain(v) for k, v in e.items() if v is not None})
    nm = pd.read_csv(root / "numeric_agg" / "numerics.csv")
    nr = pd.read_csv(root / "numeric_agg" / "numeric_resolution.csv").set_index("track")
    for _, t in nm.iterrows():
        tr = t.track
        dev = DEVICE.get(tr.split("/")[0])
        if dev is None or tr not in nr.index:
            continue
        q = nr.loc[tr]
        rng = f"{q.q_lo:g} to {q.q_hi:g}"
        span = max(abs(q.q_hi - q.q_lo), 1)
        bad = []
        if q["min"] < q.q_lo - 10 * span:
            bad.append(f"{q['min']:.3g}")
        if q["max"] > q.q_hi + 10 * span:
            bad.append(f"{q['max']:.3g}")
        e = {"track": tr.split("/", 1)[1], "kind": "numeric", "unit": t.unit if isinstance(t.unit, str) else None,
             "format": t.format, "rate": f"{t.median_interval_s:.3g} s", "recordings": int(t.cases),
             "grid": float(q.resolution) if pd.notna(q.resolution) else None,
             "coarser_share": float(q.share_one_step_coarser) if pd.notna(q.share_one_step_coarser) else None,
             "rounding": ROUNDING.get(tr), "range": rng,
             "note": ("corrupt values to " + " and ".join(bad)) if bad else None}
        out.setdefault(dev, []).append({k: plain(v) for k, v in e.items() if v is not None})
    gen = HERE / "_generated" / "devices"
    gen.mkdir(parents=True, exist_ok=True)
    for dev, rows in out.items():
        if not (HERE / "devices" / f"{dev}.yaml").exists():
            continue
        rows.sort(key=lambda e: (e["kind"] != "waveform", -e.get("recordings", 0) if e["kind"] == "numeric" else 0,
                                 e["track"], -e.get("recordings", 0)))
        (gen / f"{dev}.yaml").write_text(
            "# Generated by _import/device_tracks.py; do not edit (the hand-written devices/ file supplies the rest).\n"
            + yaml.safe_dump({"id": dev, "tracks": rows}, sort_keys=False, allow_unicode=True, width=120),
            encoding="utf-8")
        print(dev, len(rows))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
