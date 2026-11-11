"""Form numbers written once: a timing form or chain step takes a parameter's value instead of a typed copy.

A form's support, bias, uncertainty components and chain spans are numbers that a study measured and a parameter
holds. Typed into the form as well, the two copies drift apart when the parameter is revised. Written as a link,

    bias_s: {median: {parameter: hr-delay-late}, p5: 3.55, p95: 5.1}
    support_s: {parameter: hr-window-span, use: p10-p90}
    u_s: {parameter: lab-access-length, rectangular: true}

the form takes the parameter's current value when the atlas is loaded. :func:`resolve_links` replaces every link by
its number before any check or calculation runs, so the timing, planner and propagation code never sees a link, and
records where each came from (``Dataset.links``) for the JSON and the pages.

A link's keys:

- ``parameter`` (required): the parameter's id;
- ``use``: which of its numbers: ``value`` (default), a spread entry (``p5``, ``p10``, ``q1``, ``q3``, ``p90``,
  ``p95``, ``min``, ``max``, ``sd``), a pair for a range field (``p10-p90``, ``p5-p95``, ``q1-q3``, ``min-max``), or
  ``n``, the count behind it (a form's ``n``: taken as it is, no unit);
- ``scale``: a multiplier, applied after the unit conversion (needed when the parameter's unit is not a time);
- ``rectangular``: true when the number is a full width to be turned into a standard uncertainty (divided by
  sqrt(12));
- ``plus``: a number of seconds, or another link to one number, added after the rest (for a bias that is a measured
  delay plus a known share of another quantity, such as half of a polling gap:
  ``{parameter: hr-label-delay, plus: {parameter: solar8000-poll-gap, scale: 0.5}}``).

Form fields are in seconds; a parameter in ms, min or h is converted. :func:`typed_form_copies` lists form numbers
typed where a parameter of a study the form cites holds the same number, for the engine to warn about; a typed
count (``n``) that equals such a parameter's n is listed too.
"""

from __future__ import annotations

import copy
import math

from metrology_atlas.values import written_decimals

KEYS = {"parameter", "use", "scale", "rectangular", "plus"}
TIME_UNITS = {"s": 1.0, "ms": 1e-3, "min": 60.0, "h": 3600.0}
SPREAD_KEYS = {"p5", "p10", "q1", "q3", "p90", "p95", "min", "max", "sd"}
PAIRS = {"p10-p90": ("p10", "p90"), "p5-p95": ("p5", "p95"), "q1-q3": ("q1", "q3"), "min-max": ("min", "max")}


def is_link(x) -> bool:
    return isinstance(x, dict) and "parameter" in x and set(x) <= KEYS


def _number(p: dict, key: str):
    if key == "value":
        return p.get("value")
    return (p.get("spread") or {}).get(key)


def _value(link: dict, ds, where: str, problems: list[str]):
    """The number (or [low, high]) a link stands for, in seconds; None after recording a problem."""
    pid = link["parameter"]
    p = ds.items["parameter"].get(pid)
    if p is None:
        problems.append(f"{where}: link to parameter '{pid}', which does not exist")
        return None
    use = link.get("use", "value")
    if use == "n":
        n = (p.get("spread") or {}).get("n")
        if not isinstance(n, (int, float)) or isinstance(n, bool):
            problems.append(f"{where}: link to '{pid}': the parameter has no n")
            return None
        return int(n) if float(n).is_integer() else n
    keys = PAIRS.get(use) or ((use,) if use == "value" or use in SPREAD_KEYS else None)
    if keys is None:
        problems.append(f"{where}: link to '{pid}': 'use' must be value, a spread entry or a pair, not '{use}'")
        return None
    nums = [_number(p, k) for k in keys]
    if any(not isinstance(n, (int, float)) or isinstance(n, bool) for n in nums):
        problems.append(f"{where}: link to '{pid}': the parameter has no {use}")
        return None
    unit = (p.get("unit") or "").strip()
    if "scale" in link:
        factor = TIME_UNITS.get(unit, 1.0) * float(link["scale"])
    elif unit in TIME_UNITS:
        factor = TIME_UNITS[unit]
    else:
        problems.append(f"{where}: link to '{pid}': its unit '{unit}' is not a time, so give a 'scale' to seconds")
        return None
    out = [float(n) * factor / (math.sqrt(12.0) if link.get("rectangular") else 1.0) for n in nums]
    if "plus" in link:
        extra = link["plus"]
        if is_link(extra):
            extra = _value(extra, ds, f"{where} (plus)", problems)
            if extra is None:
                return None
        if isinstance(extra, list) or not isinstance(extra, (int, float)) or isinstance(extra, bool):
            problems.append(f"{where}: link to '{pid}': 'plus' must be a number of seconds or a link to one number")
            return None
        out = [x + float(extra) for x in out]
    return out if len(out) == 2 else out[0]


def resolve_links(ds, problems: list[str]) -> None:
    """Replace every link in the variables' timing forms and chain steps by its number; record each on ds.links."""
    ds.links = getattr(ds, "links", {})

    def walk(node, path, vid, where):
        if isinstance(node, dict):
            for k, v in list(node.items()):
                p = f"{path}.{k}" if path else k
                if is_link(v):
                    val = _value(v, ds, f"{where}: {p}", problems)
                    if val is not None:
                        ds.links.setdefault(vid, []).append({"field": p, **v, "resolved": val})
                        node[k] = val
                else:
                    walk(v, p, vid, where)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                p = f"{path}[{i}]"
                if is_link(v):
                    val = _value(v, ds, f"{where}: {p}", problems)
                    if val is not None:
                        ds.links.setdefault(vid, []).append({"field": p, **v, "resolved": val})
                        node[i] = val
                else:
                    walk(v, p, vid, where)

    for vid, v in ds.items["variable"].items():
        rel = ds.sources.get(("variable", vid), f"variables/{vid}.yaml")
        # YAML anchors share one object between forms; copy each form so a link is resolved (and recorded) in each
        for key in ("timing", "chain"):
            if isinstance(v.get(key), list):
                v[key] = [copy.deepcopy(x) for x in v[key]]
        for i, form in enumerate(v.get("timing") or []):
            if isinstance(form, dict):
                walk(form, f"timing[{form.get('id', i)}]", vid, rel)
        for i, step in enumerate(v.get("chain") or []):
            if isinstance(step, dict):
                walk(step, f"chain[{i}]", vid, rel)


def _numbers(node, path=""):
    """(path, number) for every number in a form, skipping linked ones (already resolved) by the caller."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in {"n", "id", "status", "scope", "type", "distribution", "domain"}:
                continue
            yield from _numbers(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _numbers(v, f"{path}[{i}]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield path, node


def _counts(node, path=""):
    """(path, number) for every count (a key named n) in a form."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if k == "n" and isinstance(v, (int, float)) and not isinstance(v, bool):
                yield p, v
            else:
                yield from _counts(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _counts(v, f"{path}[{i}]")


def typed_form_copies(ds) -> list[str]:
    """Form numbers typed where a parameter of a study the form cites (or the step's own parameter) holds the same
    number at the precision it is typed, as warnings: link it instead."""
    own: dict[str, dict[str, dict]] = {}
    for pid, p in ds.items["parameter"].items():
        if p.get("study"):
            own.setdefault(p["study"], {})[pid] = p
    linked = {(vid, l["field"]) for vid, ls in getattr(ds, "links", {}).items() for l in ls}
    out = []
    for vid, v in sorted(ds.items["variable"].items()):
        ok = {(e.get("field"), e.get("parameter")) for e in v.get("typed_ok") or [] if isinstance(e, dict)}
        used = set()
        units = [(f"timing[{f.get('id', i)}]", f, set(f.get("studies") or []))
                 for i, f in enumerate(v.get("timing") or []) if isinstance(f, dict)]
        units += [(f"chain[{i}]", s, set(s.get("studies") or []))
                  for i, s in enumerate(v.get("chain") or []) if isinstance(s, dict)]
        for base, unit, studies in units:
            params = {pid: p for st in studies for pid, p in own.get(st, {}).items()}
            if isinstance(unit.get("parameter"), str) and unit["parameter"] in ds.items["parameter"]:
                params[unit["parameter"]] = ds.items["parameter"][unit["parameter"]]
            cands = []
            for pid, p in params.items():
                f = TIME_UNITS.get((p.get("unit") or "").strip())
                if f is None:
                    continue
                for key in ("value", *sorted(SPREAD_KEYS)):
                    n = _number(p, key)
                    if isinstance(n, (int, float)) and not isinstance(n, bool):
                        cands.append((pid, key, float(n) * f, written_decimals(n) + {1.0: 0, 1e-3: 3, 60.0: 0, 3600.0: 0}[f]))
            for path, x in _numbers(unit):
                full = f"{base}.{path}"
                if any(vid == lv and (full == lf or full.startswith(lf + "[") or full.startswith(lf + "."))
                       for lv, lf in linked) or x == 0:
                    continue
                d = written_decimals(x)
                if d == 0 and abs(x) < 10:
                    continue  # small whole numbers coincide by chance, as in prose
                for pid, key, val, pd in cands:
                    if d <= pd and round(val, d) == round(float(x), d) and abs(val) >= 0.01:
                        if (full, pid) in ok:
                            used.add((full, pid))
                            break
                        out.append(f"variable '{vid}': {full} = {x:g} is typed; parameter {pid} ({key}) holds it: "
                                   f"link it ({{parameter: {pid}{'' if key == 'value' else ', use: ' + key}}})")
                        break
            # counts: a typed n equal to the n of a cited parameter
            for path, x in _counts(unit):
                full = f"{base}.{path}"
                if any(vid == lv and full == lf for lv, lf in linked) or not x or x < 10:
                    continue
                for pid, p in sorted(params.items()):
                    if (p.get("spread") or {}).get("n") == x:
                        if (full, pid) in ok:
                            used.add((full, pid))
                            break
                        out.append(f"variable '{vid}': {full} = {x:g} is typed; parameter {pid} (n) holds it: "
                                   f"link it ({{parameter: {pid}, use: n}})")
                        break
        for f, pid in sorted(ok - used, key=str):
            out.append(f"variable '{vid}': typed_ok entry ({f}, {pid}) matches no typed form number now; remove it")
    return out
