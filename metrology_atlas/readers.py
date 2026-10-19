"""Readers for model files held in a pinned snapshot. Each turns one file format into a common summary that the
site renders and the measurement-space figure draws, so the numbers stay in the model file and are never copied.

A summary is a dict:

- ``kind``: what the model describes (e.g. ``value``, ``timestamp``, ``derived``);
- ``unit``; ``resolution`` (text);
- ``modes``: rounding modes in allocation order, each ``{label, step, anchor, p, weight, condition, note}``.
  Allocation is sequential: a record not taken by an earlier mode is taken by this one with probability ``p``
  (where ``condition`` holds). ``weight`` is the share this gives when no mode has a condition; with conditions
  it is only a guide (``approx`` is set);
- ``latent``: the family of the true-value density, in words;
- ``covariates``: names; ``fit``: ``{n, bic, date, source}``; ``notes``: list of strings.
"""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path


@cache
def read_json(path: str) -> dict:
    """Read a JSON file (UTF-8)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def vitaldb_resolution(model: dict) -> dict:
    """vitaldb-resolution model files (schema 0.3-0.4): sequential (stick-breaking) allocation to rounding modes."""
    res = model.get("resolution") or {}
    rr = model.get("recorded_rounding") or {}
    if not res and isinstance(rr, dict) and rr.get("resolution") is not None:   # derived models: rounding of the stored value
        res_text = f"{rr['resolution']:g} ({rr.get('anchor') or 'nearest'}), as stored"
        notes = []
    elif isinstance(res, dict):
        eff = res.get("effective")
        res_text = res.get("observed")
        res_text = f"{res_text}" + (f" (modelled at {eff})" if eff not in (None, res.get("observed")) else "")
        notes = [res["justification"]] if res.get("justification") else []
    else:
        res_text, notes = str(res), []
    modes, remaining, exact = [], 1.0, True
    for a in model.get("allocation") or []:
        mode = a.get("mode") or {}
        p = a.get("prob")
        cond = []
        if a.get("capture_window") is not None:
            cw = a["capture_window"]
            cond.append(f"recorded minus true in [{cw['lo']:g}, {cw['hi']:g})" if isinstance(cw, dict)
                        else f"true value within {cw:g} of the rounded one")
        if a.get("applies_below") is not None:
            cond.append(f"true value below {a['applies_below']:g}")
        if a.get("window") is not None:
            cond.append(f"true clock minute in [{a['window'][0]:g}, {a['window'][1]:g})")
        if a.get("applies_if_ref_in") is not None:
            cond.append(f"reference clock minute in [{a['applies_if_ref_in'][0]:g}, {a['applies_if_ref_in'][1]:g})")
        if p is None:
            q = 1.0
        else:
            q = _sig(p["logit"])
            if p.get("covariates"):
                cond.append("varies with " + ", ".join(sorted({c["name"] for c in p["covariates"]})))
            if p.get("form") not in (None, "constant"):
                cond.append("varies with the value (shown at " + f"{p.get('centre', '')})".replace(" )", ")"))
        if cond:
            exact = False
        w = remaining * q
        remaining -= w
        if a.get("kind") == "nominal":
            step, anchor = None, f"written as {a.get('recorded_value')}"
        else:
            step, anchor = mode.get("resolution"), mode.get("anchor") or a.get("anchor") or "nearest"
        modes.append({"label": a.get("label"), "step": step, "anchor": anchor, "p": q, "weight": w,
                      "condition": "; ".join(cond), "note": a.get("note") or ""})
    if not exact:
        for m in modes:
            m["approx"] = True
    latent = model.get("latent")
    if isinstance(latent, dict):
        fam = latent.get("family", "")
    else:
        fam = str(latent or "")
        fam = fam.split("'family': '")[1].split("'")[0] if "'family': '" in fam else ""
    fit = model.get("fit") or {}
    kind = model.get("kind") or "value"
    if kind == "derived":
        notes.append("Derived: " + str(model.get("formula", "")))
    mv = model.get("measurement_variability")
    if isinstance(mv, dict) and isinstance(mv.get("measured"), dict):
        me = mv["measured"]
        sd = (f"{me['sd']:g} {me.get('unit') or model.get('unit') or ''}".strip() if me.get("sd") is not None
              else f"{100 * me['sd_relative']:g}% of the value" if me.get("sd_relative") is not None else "not given")
        line = f"Measurement variability (beyond rounding): SD {sd}"
        wi = mv.get("written_in")
        if isinstance(wi, dict) and wi.get("sd") is not None:
            line += f"; for written-in values, SD {wi['sd']:g} {wi.get('unit') or model.get('unit') or ''}".rstrip()
        notes.append(line + (f" ({mv['status']})." if mv.get("status") else "."))
    return {
        "kind": kind, "unit": model.get("unit"), "resolution": res_text, "modes": modes, "latent": fam,
        "covariates": model.get("required_covariates") or [],
        "fit": {"n": fit.get("n"), "bic": fit.get("bic"), "date": fit.get("date") or fit.get("fitted"),
                "source": fit.get("source") or fit.get("data")},
        "accuracy_sd": (mv or {}).get("measured", {}).get("sd") if isinstance(mv, dict) else None,
        "notes": notes,
        "references": list(dict.fromkeys(_refs(model))),
    }


def _refs(value):
    """Every string in any 'references' list, anywhere in a model file."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "references" and isinstance(v, list):
                yield from (r for r in v if isinstance(r, str))
            else:
                yield from _refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from _refs(v)


READERS = {"vitaldb-resolution": vitaldb_resolution}


def summarise(ds, ref: str) -> dict | None:
    """Summary of the model a code reference points at, read from the snapshot with its source's reader."""
    from metrology_atlas.code import snapshot_path, source_of

    path, src = snapshot_path(ds, ref), source_of(ds, ref)
    if path is None or src is None or not path.is_file():
        return None
    reader = READERS.get(src.get("format") or src.get("software"))
    return reader(read_json(str(path))) if reader else None


def spread(ds, ref: str) -> dict | None:
    """The aggregate spread entry 'software-id/path.json#key' points at, from the pinned snapshot."""
    from metrology_atlas.code import snapshot_path

    path, _, key = ref.partition("#")
    snap = snapshot_path(ds, path)
    if snap is None or not snap.is_file():
        return None
    doc = read_json(str(snap))
    entry = (doc.get("variables") or {}).get(key)
    return {**entry, "commit": doc.get("commit")} if entry else None
