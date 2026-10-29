"""Timing forms in VIM/GUM terms (framework spec of 28 Oct 2026, decisions D1-D10).

Every value describes an interval of true time, its *support*. The time measurand is the support's *close*: the
earliest moment the value could exist (the availability rule, D10). A timing form says how the stored stamp sits
against that close:

- a **bias** (VIM 2.18): the systematic displacement ``stamp - close``, positive when the stamp is late; per recording,
  stored across the release as a distribution (D2);
- a **standard uncertainty** built from named **components**, each with a Type (A/B), a distribution and a **scope**
  saying what shares it (D9); combined here, never typed;
- for a corrected form (``kind`` fixed_shift or per_recording) the bias is 0 by construction (D5) unless a named
  remaining bias is given; its headline uncertainty is an upper bound with an empirical 95% interval (D3);
- whether the form uses data from after the stamp (``uses_future``: a whole-recording fit), so real-time use can
  leave it out (option C of 28 Oct).

A form is written either in these fields or in the legacy ones (``delay_s``, ``interval_s``, ``corrected_delay_s``)
that predate the reframe. :func:`resolve` turns either into one normalised dict, which the planner, the pages and the
chart read, so the arithmetic lives here and only here. Legacy forms keep today's numbers (a range read as uniform)
and are flagged until stage 3 migrates them.
"""

from __future__ import annotations

import math

SQ12 = math.sqrt(12.0)
KINDS = ("as_stored", "fixed_shift", "per_recording")
SCOPES = ("independent", "structured", "recording", "shared", "release", "unknown")
POSITIONS = ("close", "open", "centre", "instant", "unknown")
DISTRIBUTIONS = ("normal", "rectangular", "empirical", "mixture", "unknown")


def bias_range(b: dict | None) -> tuple[float, float, float]:
    """(low, middle, high) of a bias entry: a single ``value``, or a release distribution (``median``, ``p5``, ``p95``)."""
    if not b:
        return 0.0, 0.0, 0.0
    if b.get("value") is not None:
        v = float(b["value"])
        return v, v, v
    mid = float(b["median"])
    return float(b.get("p5", mid)), mid, float(b.get("p95", mid))


def combine(components: list[dict]) -> float:
    """Combined standard uncertainty: root sum of squares of the components not already included in another (GUM 5.1)."""
    return math.sqrt(sum(c["u_s"] ** 2 for c in components if not c.get("included_in")))


def _component(c: dict) -> dict:
    return {"name": c["name"], "type": c.get("type", "B"), "distribution": c.get("distribution", "unknown"),
            "u_s": float(c["u_s"]), "scope": c.get("scope", "unknown"), "length_s": c.get("length_s"),
            "shared_with": c.get("shared_with"), "status": c.get("status"), "evidence": c.get("evidence"),
            "included_in": c.get("included_in")}


def _common(t: dict) -> dict:
    return {"id": t["id"], "name": t["name"], "default": bool(t.get("default")), "status": t["status"],
            "evidence": t["evidence"], "domain": t["domain"], "studies": list(t.get("studies") or []),
            "corrects": list(t.get("corrects") or []), "correction": t.get("correction")}


def resolve(t: dict) -> dict:
    """One timing form, normalised. Keys:

    ``kind`` as_stored / fixed_shift / per_recording; ``uses_future``; ``legacy``; ``synthetic``;
    ``support`` [lo, hi] s or None; ``stamp_position``; ``look_ahead`` [lo, hi] s of lead, or None;
    ``bias`` {lo, mid, hi, scope, name}: the displacement left in the form as used (0 after a correction);
    ``shift_s``: what to subtract from the stamps (fixed_shift only; None for a per-recording correction, 0 otherwise);
    ``removes`` [lo, hi] s: the bias a correction removed (it still counts towards latency);
    ``components``, ``u_c``, ``interval95``, ``upper_bound``, ``likely_u``;
    ``latency_s``: how long after the close the stored data can arrive (the availability rule).
    """
    out = _common(t)
    if t.get("delay_s") is not None:
        return out | _legacy(t)
    kind = t["kind"]
    lo, mid, hi = bias_range(t.get("bias_s"))
    removes = None
    if t.get("removes_bias_s"):
        rl, _, rh = bias_range(t["removes_bias_s"])
        removes = [rl, rh]
    unc = t.get("uncertainty") or {}
    comps = [_component(c) for c in unc.get("components") or []]
    shift = 0.0
    if kind == "fixed_shift":
        shift = bias_range(t.get("removes_bias_s"))[1]
    elif kind == "per_recording":
        shift = None
    late = max(hi, 0.0) + (removes[1] if removes else 0.0)
    la = t.get("look_ahead")
    return out | {
        "kind": kind, "legacy": False, "synthetic": False,
        "uses_future": bool(t.get("uses_future", False)),
        "support": t.get("support_s"), "stamp_position": t.get("stamp_position", "unknown"), "grid_s": t.get("grid_s"),
        "look_ahead": (la or {}).get("lead_s") if la else None,
        "bias": {"lo": lo, "mid": mid, "hi": hi, "scope": (t.get("bias_s") or {}).get("scope"),
                 "name": (t.get("bias_s") or {}).get("name")},
        "shift_s": shift, "removes": removes, "components": comps, "u_c": combine(comps),
        "interval95": unc.get("interval95_s"), "upper_bound": bool(unc.get("upper_bound")),
        "likely_u": unc.get("likely_u_s"), "latency_s": late,
    }


def _legacy(t: dict) -> dict:
    """A form in the pre-reframe fields. Today's numbers are kept: the delay range read as uniform, the interval as an
    unsplit grid-or-window component. Raw forms are taken as stored (no shift); forms that correct another (with or
    without ``corrected_delay_s``) have bias 0 (the D5 fix) and are assumed to use the whole recording."""
    d, iv = t["delay_s"], t["interval_s"]
    ty = "A" if t["status"] == "measured" else "B"
    interval = {"name": "interval one value stands for (grid or window, not yet split)", "type": "B",
                "distribution": "rectangular", "u_s": iv[1] / SQ12, "scope": "independent", "length_s": None,
                "shared_with": None, "status": t["status"], "evidence": "legacy interval_s", "included_in": None}
    common = {"legacy": True, "synthetic": False, "support": iv, "legacy_xy": [list(d), list(iv)], "stamp_position": "close", "grid_s": None,
              "look_ahead": None, "interval95": None, "upper_bound": False, "likely_u": None}
    if t.get("corrected_delay_s") is not None or t.get("corrects"):
        comps = [{"name": "correction (legacy range read as uniform; not yet re-evaluated)", "type": ty,
                  "distribution": "rectangular", "u_s": (d[1] - d[0]) / SQ12, "scope": "unknown", "length_s": None,
                  "shared_with": None, "status": t["status"], "evidence": t["evidence"], "included_in": None}, interval]
        rem = t.get("corrected_delay_s")
        return common | {"kind": "per_recording", "uses_future": True,
                         "bias": {"lo": 0.0, "mid": 0.0, "hi": 0.0, "scope": None, "name": None},
                         "shift_s": None, "removes": list(rem) if rem else None, "components": comps,
                         "u_c": combine(comps), "latency_s": (rem[1] if rem else 0.0) + d[1]}
    comps = [{"name": "spread of the delay between recordings (legacy range read as uniform)", "type": ty,
              "distribution": "rectangular", "u_s": (d[1] - d[0]) / SQ12, "scope": "recording", "length_s": None,
              "shared_with": None, "status": t["status"], "evidence": t["evidence"], "included_in": None}, interval]
    return common | {"kind": "as_stored", "uses_future": False,
                     "bias": {"lo": d[0], "mid": (d[0] + d[1]) / 2, "hi": d[1], "scope": "recording", "name": None},
                     "shift_s": 0.0, "removes": None, "components": comps, "u_c": combine(comps), "latency_s": d[1]}


def fixed_shift_of(r: dict) -> dict:
    """The fixed-shift form derived from an as-stored form: subtract the release median, known in advance (option C).
    Used for legacy forms until stage 3 writes them; the uncertainty is the same, the bias is gone."""
    b = r["bias"]
    return r | {"id": r["id"] + "-shift", "name": r["name"] + ", shifted by the release median", "kind": "fixed_shift",
                "synthetic": True, "default": False, "corrects": [r["id"]], "correction": "release median",
                "shift_s": b["mid"], "removes": [b["lo"], b["hi"]],
                "bias": {"lo": 0.0, "mid": 0.0, "hi": 0.0, "scope": None, "name": None}}


def forms(signal: dict) -> list[dict]:
    """All of a signal's timing forms, normalised, with a fixed-shift form added beside each legacy as-stored form that
    has no written fixed-shift sibling. When the default is such a form and the signal has no correction, the derived
    fixed shift becomes the default (it is what the planner did before option C, now named)."""
    rs = [resolve(t) for t in signal.get("timing") or []]
    has_fixed = any(r["kind"] == "fixed_shift" for r in rs)
    has_corr = any(r["kind"] != "as_stored" for r in rs)
    out = []
    for r in rs:
        out.append(r)
        if r["legacy"] and r["kind"] == "as_stored" and not has_fixed and r["bias"]["hi"] > 0:
            f = fixed_shift_of(r)
            if r["default"] and not has_corr:
                r["default"], f["default"] = False, True
            out.append(f)
    return out


def default(signal: dict) -> dict | None:
    """The form an analysis should use."""
    fs = forms(signal)
    return next((f for f in fs if f["default"]), fs[0] if fs else None)


def describe_bias(b: dict) -> str:
    """The bias in words, for tables: '0', '0.53 s', or '0.53-1.05 s (p5-p95)'."""
    from metrology_atlas.site import _rng  # late import: site imports this module
    if b["lo"] == b["hi"]:
        return "0" if b["mid"] == 0 else _rng([b["mid"], b["mid"]])
    return f"{_rng([b['lo'], b['hi']])}, median {_rng([b['mid'], b['mid']])}"
