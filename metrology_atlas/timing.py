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

:func:`resolve` turns a form into one normalised dict, which the planner, the pages and the chart read, so the
arithmetic lives here and only here. The pre-reframe fields (delay_s, interval_s, corrected_delay_s) were retired in
schema 0.3 once every form had been migrated (29 Oct 2026).
"""

from __future__ import annotations

import math

SQ12 = math.sqrt(12.0)
KINDS = ("as_stored", "fixed_shift", "per_recording")
SCOPES = ("independent", "structured", "recording", "shared", "release", "unknown")
POSITIONS = ("close", "open", "centre", "instant", "unknown")
DISTRIBUTIONS = ("normal", "rectangular", "empirical", "mixture", "unknown")
CORRELATIONS = ("exponential", "rectangular", "triangular", "bell", "unknown")


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
            "correlation": c.get("correlation", "exponential" if c.get("scope") == "structured" else None),
            "shared_with": c.get("shared_with"), "status": c.get("status"), "evidence": c.get("evidence"),
            "included_in": c.get("included_in")}


def _common(t: dict) -> dict:
    return {"id": t["id"], "name": t["name"], "default": bool(t.get("default")), "status": t["status"],
            "evidence": t["evidence"], "domain": t["domain"], "studies": list(t.get("studies") or []),
            "corrects": list(t.get("corrects") or []), "correction": t.get("correction")}


def resolve(t: dict) -> dict:
    """One timing form, normalised. Keys:

    ``kind`` as_stored / fixed_shift / per_recording; ``uses_future``;
    ``support`` [lo, hi] s or None; ``stamp_position``; ``look_ahead`` [lo, hi] s of lead, or None;
    ``bias`` {lo, mid, hi, scope, name}: the displacement left in the form as used (0 after a correction);
    ``shift_s``: what to subtract from the stamps (fixed_shift only; None for a per-recording correction, 0 otherwise);
    ``removes`` [lo, hi] s: the bias a correction removed (it still counts towards latency);
    ``components``, ``u_c``, ``interval95``, ``upper_bound``, ``likely_u``;
    ``latency_s``: how long after the close the stored data can arrive (the availability rule).
    """
    out = _common(t)
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
    late = max(hi, 0.0) + (max(removes[1], 0.0) if removes else 0.0)  # an early stamp adds no latency
    la = t.get("look_ahead")
    return out | {
        "kind": kind,
        "uses_future": bool(t.get("uses_future", False)),
        "support": t.get("support_s"), "stamp_position": t.get("stamp_position", "unknown"), "grid_s": t.get("grid_s"),
        "look_ahead": la["lead_s"] if la and la.get("basis", "real") == "real" else None,
        "look_ahead_note": (la or {}).get("note") if la else None,
        "look_ahead_apparent": bool(la and la.get("basis") == "apparent"),
        "bias": {"lo": lo, "mid": mid, "hi": hi, "scope": (t.get("bias_s") or {}).get("scope"),
                 "name": (t.get("bias_s") or {}).get("name")},
        "shift_s": shift, "removes": removes, "components": comps, "u_c": combine(comps),
        "interval95": unc.get("interval95_s"), "upper_bound": bool(unc.get("upper_bound")),
        "likely_u": unc.get("likely_u_s"), "latency_s": late,
    }


def forms(signal: dict) -> list[dict]:
    """All of a signal's timing forms, normalised."""
    return [resolve(t) for t in signal.get("timing") or []]


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


def correlation(c: dict, dt: float) -> float:
    """Correlation of a component's error between two stamps dt seconds apart, from its scope and shape."""
    if c["scope"] in ("recording", "release", "shared"):
        return 1.0
    if c["scope"] != "structured" or not c.get("length_s"):
        return 1.0 if dt == 0 else 0.0
    L, x, shape = float(c["length_s"]), abs(dt), c.get("correlation") or "exponential"
    if shape == "rectangular":
        return 1.0 if x < L else 0.0       # same block assumed when closer than one block length
    if shape == "triangular":
        return max(0.0, 1.0 - x / L)
    if shape == "bell":
        return float(math.exp(-0.5 * (x / L) ** 2))
    if shape == "exponential":
        return float(math.exp(-x / L))
    return float("nan")
