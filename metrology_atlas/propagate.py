"""Propagation along the links between variables (schema 0.4): support, availability and the GUM law of propagation.

A derived variable names the variables it was derived from (``derived_from``). Along every ``computed-from`` link
the inputs constrain the derived value, whatever it computes:

- **support**: the derived value describes at least every interval its inputs describe, so its support is at least
  as long as the longest of theirs;
- **availability**: it cannot exist before its latest input has arrived. If its support has length ``S`` and an
  input arrives ``L_i`` after its own close, the derived value's stamp must sit at least ``L_i - S`` after the
  derived value's close; the bound is the largest over the inputs;
- **real time**: if any input's form uses data from after its stamp, so does the derived value.

These are necessary conditions, true of any derivation. :func:`time_floor` works them out, through chains of derived
inputs, and :func:`time_conflicts` lists where a derived variable's own timing forms claim less.

On the value side, a variable whose ``propagation`` method is ``law`` and whose value model has a ``formula`` gets
its standard uncertainty by the GUM law of propagation (GUM 5.1-5.2): sensitivity coefficients from the formula,
each input's standard uncertainty from its value budget (resolution as a rectangular component, plus any named
components), and covariances from the components two inputs share (the same ``shared_with``), taken as fully
correlated, as the planner does for times. Biases propagate by the same coefficients. A formula that is not linear
needs the point at which to evaluate it (``propagation.at``). Same-source links carry nothing: the derived value
was not computed from the stored input.

Monte Carlo propagation (GUM Supplement 1) is not part of schema 0.4: features defined by code take their
uncertainty from the study that measured it (``propagation.method: study``).
"""

from __future__ import annotations

import ast
import math

from metrology_atlas.timing import SQ12, bias_range, default, forms

FUNCTIONS = {"sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp, "abs": abs, "min": min,
             "max": max, "pi": math.pi}
_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant, ast.Add, ast.Sub,
          ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)


class FormulaError(ValueError):
    """A formula that cannot be read, or that names something other than its inputs and the allowed functions."""


def symbol(entry: dict) -> str:
    """An input's name in its derived variable's formula: its ``symbol``, or its id with hyphens as underscores."""
    return entry.get("symbol") or str(entry["variable"]).replace("-", "_")


def computed_inputs(v: dict) -> list[dict]:
    """The derived_from entries a value was computed from (same-source links carry no propagation)."""
    return [d for d in v.get("derived_from") or [] if isinstance(d, dict) and d.get("relation") == "computed-from"]


def compile_formula(formula: str, symbols: set[str]):
    """The formula as a function of a mapping symbol -> value. Only arithmetic, the inputs and FUNCTIONS are allowed."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as error:
        raise FormulaError(f"cannot be read ({error.msg})") from None
    for node in ast.walk(tree):
        if not isinstance(node, _NODES):
            raise FormulaError(f"uses {type(node).__name__}, which is not allowed")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS):
            raise FormulaError("calls something other than " + ", ".join(sorted(k for k in FUNCTIONS if k != "pi")))
        if isinstance(node, ast.Name) and node.id not in symbols and node.id not in FUNCTIONS:
            raise FormulaError(f"names '{node.id}', which is not one of its inputs")
    code = compile(tree, "<formula>", "eval")
    return lambda values: float(eval(code, {"__builtins__": {}}, {**FUNCTIONS, **values}))  # noqa: S307 (checked above)


# -- the time side --------------------------------------------------------------------------------------------------

def _form(src: dict, entry: dict) -> dict | None:
    if entry.get("form"):
        return next((f for f in forms(src) if f["id"] == entry["form"]), None)
    return default(src)


def time_floor(ds, vid: str, _path: tuple[str, ...] = ()) -> dict:
    """What a derived variable's inputs imply for its time, through chains of derived inputs.

    Returns ``support_min_s`` (its support is at least this long), ``input_latency_s`` (the latest any input arrives
    after its own close), ``uses_future``, ``inputs`` (one row per computed-from input: the form used and what it
    contributes) and ``unstated`` (inputs, at any depth, whose timing the atlas does not describe).
    """
    v = ds.get("variable", vid) or {}
    out = {"support_min_s": 0.0, "input_latency_s": 0.0, "uses_future": False, "inputs": [], "unstated": []}
    for d in computed_inputs(v):
        src = ds.get("variable", d["variable"])
        if src is None or d["variable"] in _path + (vid,):
            continue
        f = _form(src, d)
        if f is not None:
            row = {"variable": d["variable"], "form": f["id"], "support_min_s": float((f["support"] or [0, 0])[0]),
                   "latency_s": float(f["latency_s"]), "uses_future": f["uses_future"]}
        elif computed_inputs(src):
            sub = time_floor(ds, d["variable"], _path + (vid,))
            row = {"variable": d["variable"], "form": None, "support_min_s": sub["support_min_s"],
                   "latency_s": sub["input_latency_s"], "uses_future": sub["uses_future"]}
            out["unstated"] += [u for u in sub["unstated"] if u not in out["unstated"]]
        else:
            out["unstated"].append(d["variable"])
            continue
        out["inputs"].append(row)
        out["support_min_s"] = max(out["support_min_s"], row["support_min_s"])
        out["input_latency_s"] = max(out["input_latency_s"], row["latency_s"])
        out["uses_future"] = out["uses_future"] or row["uses_future"]
    return out


def time_conflicts(ds, vid: str) -> list[str]:
    """Where a derived variable's own timing forms claim less than its inputs allow: a shorter support, an earlier
    availability, or real-time use of inputs that need future data."""
    v = ds.get("variable", vid) or {}
    if not computed_inputs(v) or not v.get("timing"):
        return []
    floor = time_floor(ds, vid)
    if not floor["inputs"]:
        return []
    out = []
    for f in forms(v):
        s_hi = float((f["support"] or [0, 0])[1])
        if s_hi < floor["support_min_s"]:
            out.append(f"timing '{f['id']}': its support (at most {s_hi:g} s) is shorter than an input's "
                       f"({floor['support_min_s']:g} s)")
        need = floor["input_latency_s"] - s_hi
        if need > 0 and f["latency_s"] < need:
            out.append(f"timing '{f['id']}': available {f['latency_s']:g} s after its close, but its inputs arrive up "
                       f"to {floor['input_latency_s']:g} s after theirs, so at least {need:g} s (availability rule)")
        if floor["uses_future"] and not f["uses_future"]:
            out.append(f"timing '{f['id']}': an input's form uses data after its stamp, so this form does too "
                       "('uses_future')")
    return out


# -- the value side -------------------------------------------------------------------------------------------------

def value_budget(v: dict) -> tuple[list[dict], float]:
    """A variable's value uncertainty components (resolution as a rectangular component, plus the named ones) and its
    value bias (the middle of its range), in its own unit."""
    val = v.get("value") or {}
    comps = []
    if isinstance(val.get("step"), (int, float)) and val["step"] > 0:
        comps.append({"name": "resolution", "u": float(val["step"]) / SQ12, "shared_with": None})
    for c in ((val.get("uncertainty") or {}).get("components")) or []:
        if not c.get("included_in"):
            comps.append({"name": c["name"], "u": float(c["u_s"]),
                          "shared_with": c.get("shared_with") if c.get("scope") == "shared" else None})
    return comps, bias_range(val.get("bias"))[1]


def _gradient(fn, point: dict[str, float]) -> dict[str, float]:
    grad = {}
    for k, x in point.items():
        h = 1e-6 * max(abs(x), 1.0)
        grad[k] = (fn({**point, k: x + h}) - fn({**point, k: x - h})) / (2 * h)
    return grad


def law(ds, vid: str) -> dict:
    """The GUM law of propagation for a variable whose value is a formula of its inputs.

    Returns ``u`` (combined standard uncertainty, in the variable's unit), ``bias``, ``linear``, ``at`` (the point
    used, for a formula that is not linear), ``terms`` (per input: symbol, coefficient, standard uncertainty and
    share of the variance), ``shared`` (the components two inputs share, which add covariance) and ``problems``.
    ``u`` is None when it cannot be worked out, and ``problems`` says why.
    """
    v = ds.get("variable", vid) or {}
    formula = (v.get("value") or {}).get("formula")
    entries = computed_inputs(v)
    out = {"u": None, "bias": None, "linear": None, "at": None, "terms": [], "shared": [], "problems": []}
    if not formula or not entries:
        out["problems"].append("no formula, or no inputs it is computed from")
        return out
    syms = {symbol(d): d for d in entries}
    try:
        fn = compile_formula(formula, set(syms))
    except FormulaError as error:
        out["problems"].append(f"the formula {error}")
        return out
    budgets = {}
    for s, d in syms.items():
        src = ds.get("variable", d["variable"]) or {}
        comps, b = value_budget(src)
        if not comps:
            out["problems"].append(f"'{d['variable']}' has no value uncertainty to propagate (no step, no components)")
        budgets[s] = (comps, b)
    if out["problems"]:
        return out
    at = {a["symbol"]: float(a["value"]) for a in (v.get("propagation") or {}).get("at") or []}
    try:
        g1 = _gradient(fn, {s: 1.0 for s in syms})
        g2 = _gradient(fn, {s: 7.3 for s in syms})
    except (ArithmeticError, ValueError, TypeError):
        g1, g2 = None, None
    linear = g1 is not None and all(math.isclose(g1[s], g2[s], rel_tol=1e-6, abs_tol=1e-9) for s in syms)
    out["linear"] = linear
    if linear:
        c = g1
    else:
        missing = sorted(set(syms) - set(at))
        if missing:
            out["problems"].append("the formula is not linear: give the point to evaluate it at ('propagation.at') "
                                   "for " + ", ".join(missing))
            return out
        try:
            c = _gradient(fn, {s: at[s] for s in syms})
        except (ArithmeticError, ValueError, TypeError) as error:
            out["problems"].append(f"the formula cannot be evaluated at the point given ({error})")
            return out
        out["at"] = {s: at[s] for s in syms}
    var = {s: sum(x["u"] ** 2 for x in budgets[s][0]) for s in syms}
    total = sum(c[s] ** 2 * var[s] for s in syms)
    names = sorted(syms)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for ca in budgets[a][0]:
                for cb in budgets[b][0]:
                    if ca["shared_with"] and ca["shared_with"] == cb["shared_with"]:
                        cov = ca["u"] * cb["u"]
                        total += 2 * c[a] * c[b] * cov
                        out["shared"].append({"inputs": [syms[a]["variable"], syms[b]["variable"]],
                                              "shared_with": ca["shared_with"], "covariance": cov})
    out["u"] = math.sqrt(max(total, 0.0))
    out["bias"] = sum(c[s] * budgets[s][1] for s in syms)
    plain = sum(c[s] ** 2 * var[s] for s in syms) or 1.0
    out["terms"] = [{"symbol": s, "variable": syms[s]["variable"], "coefficient": c[s], "u": math.sqrt(var[s]),
                     "share": c[s] ** 2 * var[s] / plain} for s in names]
    return out


def propagated(ds, vid: str) -> dict | None:
    """Everything propagation says about one variable, for the JSON and the pages; None for one with no inputs."""
    v = ds.get("variable", vid) or {}
    if not computed_inputs(v):
        return None
    out = {"time": time_floor(ds, vid), "time_conflicts": time_conflicts(ds, vid)}
    if (v.get("propagation") or {}).get("method") == "law":
        out["value"] = law(ds, vid)
    return out
