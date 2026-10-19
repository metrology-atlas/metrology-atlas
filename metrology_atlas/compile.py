"""Compile a loaded dataset into one JSON document: the whole timing system, for code and other models to read."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from metrology_atlas.code import code_url
from metrology_atlas.load import derived
from metrology_atlas.model import KINDS, SCHEMA_VERSION, Dataset


def _plain(value):
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def to_json(ds: Dataset) -> dict:
    """The dataset as one JSON-ready mapping.

    Each kind maps id -> item as authored, plus ``derived``: the relations stated on the other side (a device's
    signals, a study's parameters, a clock's links ...), so a reader never has to compute them.
    """
    rel = derived(ds)
    doc: dict = {"schema": SCHEMA_VERSION, "dataset": _plain({k: v for k, v in ds.meta.items() if not k.startswith("_")})}
    for kind in KINDS.values():
        doc[kind.folder] = {
            id_: {**_plain(item), "derived": {k: v for k, v in rel[kind.name][id_].items()}}
            for id_, item in sorted(ds.items[kind.name].items())
        }
    for kind in ("study", "observation"):
        for id_, item in doc[KINDS[kind].folder].items():
            if item.get("code"):
                item["derived"]["code_urls"] = {c: code_url(ds, c) for c in item["code"]}
    doc["references"] = {id_: _plain(r) for id_, r in sorted(ds.items["reference"].items())}
    return doc


def write_json(ds: Dataset, path: str | Path) -> Path:
    """Write the whole atlas as one machine-readable JSON file and return its path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_json(ds), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def parameter_text(p: dict) -> str:
    """A parameter's value as a short phrase: its display text, or value, unit and spread."""
    if p.get("display"):
        return p["display"]
    if p.get("value") is None:
        return "not measured"
    unit = p.get("unit") or ""
    sep = "" if unit in {"", "%"} else " "
    text = f"{_num(p['value'])}{sep}{unit}"
    s = p.get("spread") or {}
    parts = []
    if "p10" in s and "p90" in s:
        parts.append(f"p10–p90 {_num(s['p10'])} to {_num(s['p90'], signed=s['p10'] < 0 < s['p90'])}")
    if "q1" in s and "q3" in s:
        parts.append(f"IQR {_num(s['q1'])} to {_num(s['q3'])}")
    if "sd" in s:
        parts.append(f"± {_num(s['sd'])} SD")
    if "min" in s and "max" in s:
        parts.append(f"range {_num(s['min'])} to {_num(s['max'])}")
    if "n" in s:
        parts.append(f"n = {_num(s['n'])}")
    if s.get("text"):
        parts.append(s["text"])
    return text + (f" ({'; '.join(parts)})" if parts else "")


def _num(x, signed: bool = False) -> str:
    if isinstance(x, float) and x.is_integer() and abs(x) >= 100:
        x = int(x)
    s = f"{x:,}" if isinstance(x, int) and abs(x) >= 10000 else str(x)
    if signed and x > 0:
        s = "+" + s
    return s.replace("-", "−")
