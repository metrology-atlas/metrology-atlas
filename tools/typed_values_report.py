"""Where studies type a parameter's value: each hit with its context, for deciding [[value:id]] or typed_ok.

The same matching as the engine's warning (load._check_typed_values, values.typed_copies).

    python tools/typed_values_report.py datasets/vitaldb [--study ID]
"""
import argparse
import sys
from collections import defaultdict

from metrology_atlas.load import XREF, _strings, bare, load
from metrology_atlas.values import _NUMBER, _SKIP, _parse, norm_number, unit_follows, written_decimals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--study")
    a = ap.parse_args()
    ds = load(a.dataset)
    own = defaultdict(dict)
    for pid, p in ds.items["parameter"].items():
        if p.get("study"):
            own[p["study"]][pid] = p
    for sid, st in sorted(ds.items["study"].items()):
        if a.study and sid != a.study:
            continue
        params = dict(own.get(sid) or {})
        for text in _strings(st):
            for kind, ref, _ in XREF.findall(bare(text)):
                if kind in {"parameter", "value"} and ref in ds.items["parameter"]:
                    params.setdefault(ref, ds.items["parameter"][ref])
        ok = {(e.get("parameter"), norm_number(e.get("text", ""))) for e in st.get("typed_ok") or []
              if isinstance(e, dict) and e.get("text") is not None}
        vals = {pid: float(p["value"]) for pid, p in params.items()
                if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)}
        for text in _strings({k: v for k, v in st.items() if k not in {"id", "name", "typed_ok"}}):
            masked = _SKIP.sub(lambda m: " " * len(m.group(0)), text)
            for m in _NUMBER.finditer(masked):
                parsed = _parse(m.group(1))
                if parsed is None:
                    continue
                v, dec = parsed
                if dec == 0 and abs(v) < 10:
                    continue
                for pid, pv in vals.items():
                    wd = written_decimals(params[pid]["value"])
                    if dec <= wd and round(pv, dec) == v and (
                            dec > 0 or pv.is_integer() or unit_follows(masked, m.end(), params[pid].get("unit"))):
                        if (pid, norm_number(m.group(1))) in ok:
                            continue
                        ctx = text[max(0, m.start() - 90):m.end() + 60].replace("\n", " ")
                        print(f"{sid} | {pid} = {params[pid]['value']} {params[pid].get('unit', '')} | "
                              f"'{m.group(1)}' | ...{ctx}...")


if __name__ == "__main__":
    sys.exit(main())
