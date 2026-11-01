"""Numbers written once: ``[[value:parameter-id]]`` in prose shows a parameter's value, as a paper's facts do.

A study's results usually quote numbers that the atlas also holds as parameters. Typed twice, the two copies can
drift apart when the parameter is revised. Written as ``[[value:id]]``, the prose shows the parameter's current value
and unit, linked to its page, and the JSON carries the rendered text beside the token, so a reader of either sees
the same number. :func:`typed_copies` finds numbers still typed in an item's prose that equal one of its own
parameters, for the engine to warn about.
"""

from __future__ import annotations

import re

import yaml

class Written(float):
    """A number as written in the YAML: a float that remembers its text, so 3.60 is not read back as 3.6.

    The trailing zero is a statement of precision. YAML would drop it on reading; this keeps it for every page, the
    JSON's rendered values and any file written back (:func:`yaml_loader`, :data:`SafeDumper`)."""

    text: str

    def __new__(cls, value: float, text: str):
        obj = super().__new__(cls, value)
        obj.text = text
        return obj

    def __reduce__(self):
        return (Written, (float(self), self.text))


def written_decimals(x) -> int:
    """How many decimals a number was written with (from its text if it remembers one)."""
    t = getattr(x, "text", None) or repr(x)
    t = t.replace("_", "")
    if "e" in t.lower() or "." not in t:
        return 0 if float(x).is_integer() else len(repr(float(x)).split(".")[1])
    return len(t.split(".")[1])


def _float(loader, node):
    value = yaml.SafeLoader.construct_yaml_float(loader, node)
    text = loader.construct_scalar(node)
    return Written(value, text) if isinstance(value, float) and value == value and abs(value) != float("inf") else value


class SafeLoader(yaml.SafeLoader):
    """yaml.SafeLoader, with floats that remember how they were written."""


SafeLoader.add_constructor("tag:yaml.org,2002:float", _float)


class SafeDumper(yaml.SafeDumper):
    """yaml.SafeDumper that writes a remembered float as it was written."""


SafeDumper.add_representer(Written, lambda d, x: d.represent_scalar("tag:yaml.org,2002:float", x.text))


def safe_load(text: str):
    return yaml.load(text, Loader=SafeLoader)  # noqa: S506 (a SafeLoader subclass)


VALUE_XREF = re.compile(r"\[\[value:([a-z0-9][a-z0-9-]*)(?:\|([^\]]+))?\]\]")
_NUMBER = re.compile(r"(?<![\w.\-−])([−-]?\d{1,3}(?:,\d{3})+|[−-]?\d+(?:\.\d+)?)(?![\w.]*\d)")
_SKIP = re.compile(r"`[^`\n]*`|\[\[[^\]]*\]\]")


SPEC = re.compile(r"^(?:\.(\d))?(?:\s*(number))?$")
"""After the bar: ``.N`` rounds to N decimals (a rounded copy, 'about 1.9 s'), ``number`` leaves the unit out (a
table cell whose column names it); both may be given, ``.1 number``. Nothing else: a value is never retyped."""


def parse_spec(label: str | None) -> tuple[int | None, bool]:
    """(decimals or None, show the unit) from the text after the bar; ValueError for anything else."""
    if not label:
        return None, True
    m = SPEC.match(label.strip())
    if not m or not label.strip():
        raise ValueError(f"'{label}' is not a value format (use .N for N decimals, 'number' to leave out the unit)")
    return (int(m.group(1)) if m.group(1) else None), not m.group(2)


def _fmt(x: float, decimals: int | None = None) -> str:
    if decimals is not None:
        x = round(float(x), decimals)
        if decimals == 0:
            x = int(x)
        s = f"{x:,.{decimals}f}" if abs(x) >= 1000 else f"{x:.{decimals}f}"
    elif isinstance(x, Written):
        d = written_decimals(x)
        s = f"{float(x):,.{d}f}" if abs(x) >= 1000 else f"{float(x):.{d}f}"
    else:
        if isinstance(x, float) and x.is_integer() and abs(x) >= 100:
            x = int(x)
        s = f"{x:,}" if isinstance(x, int) and abs(x) >= 1000 else str(x)
    return s.replace("-", "−")


def value_text(p: dict, label: str | None = None) -> str:
    """A parameter's value as it reads inline: the number and its unit (or its display text when it has no value),
    formatted by the spec after the bar (:func:`parse_spec`)."""
    if p.get("value") is None:
        return p.get("display") or "not measured"
    decimals, with_unit = parse_spec(label)
    unit = (p.get("unit") or "") if with_unit else ""
    sep = "" if unit in {"", "%"} else " "
    return f"{_fmt(p['value'], decimals)}{sep}{unit}"


def _parse(tok: str) -> tuple[float, int] | None:
    t = tok.replace("−", "-").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v, (len(t.split(".")[1]) if "." in t else 0)


def unit_follows(text: str, end: int, unit: str | None) -> bool:
    """Whether a unit is written straight after a number ending at ``end`` (a space or thin space between)."""
    unit = (unit or "").strip()
    return bool(unit) and text[end:end + len(unit) + 2].lstrip("\u2009\u00a0 ").startswith(unit)


def typed_copies(texts, params: dict[str, dict]) -> dict[str, int]:
    """Parameter id -> how many times its value is typed in the texts (outside [[...]] and inline code), matched at
    the precision it is typed to. Small whole numbers (under 10) are skipped: too many coincide by chance."""
    out: dict[str, int] = {}
    vals = {pid: float(p["value"]) for pid, p in params.items()
            if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)}
    if not vals:
        return out
    wd = {pid: written_decimals(params[pid]["value"]) for pid in vals}
    for text in texts:
        masked = _SKIP.sub(lambda m: " " * len(m.group(0)), text)
        for m in _NUMBER.finditer(masked):
            parsed = _parse(m.group(1))
            if parsed is None:
                continue
            v, dec = parsed
            if dec == 0 and abs(v) < 10:
                continue
            for pid, pv in vals.items():
                if dec <= wd[pid] and round(pv, dec) == v and (
                        dec > 0 or pv.is_integer() or unit_follows(masked, m.end(), params[pid].get("unit"))):
                    out[pid] = out.get(pid, 0) + 1
    return out
