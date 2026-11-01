"""Rewrite typed copies of a study's own parameter values as [[value:id]], where that is unambiguous.

    python tools/apply_values.py datasets/vitaldb [--exclude STUDY:PARAMETER:TYPED ...] [--write]

From tools/value_hits.py's hits, a copy is rewritten only when the parameter's unit follows the number, only one of
the study's parameters matches it, and the study file holds exactly as many copies of that number-and-unit as there
are hits. A copy typed to fewer decimals than the parameter becomes [[value:id|.N]]; one typed to more decimals than
the parameter holds (3.60 for 3.6) is left and listed, since the parameter may be the one rounded. Everything else is
listed for a person to decide.

After rewriting, every study is loaded again and each text field is compared with its old self, with the tokens
resolved: what a reader sees must not change beyond number formatting (8192 to 8,192). Without --write nothing is
saved and the plan is printed.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrology_atlas import load  # noqa: E402
from metrology_atlas.values import VALUE_XREF, value_text, written_decimals  # noqa: E402
from value_hits import hits, walk  # noqa: E402


def decimals(x) -> int:
    return written_decimals(x)


def plan(ds):
    hs = hits(ds)
    by = defaultdict(list)
    for h in hs:
        by[(h["study"], h["field"], h["start"])].append(h)
    auto, left = [], []
    for key, group in by.items():
        if len(group) > 1 and sum(x["unit_follows"] for x in group) == 1:
            group = [x for x in group if x["unit_follows"]]  # the unit says which
        h = group[0]
        typed_dec = len(h["typed"].split(".")[1]) if "." in h["typed"] else 0
        if len(group) > 1:
            left += [dict(x, why="several parameters match") for x in group]
        elif not h["unit_follows"]:
            left.append(dict(h, why="the unit does not follow"))
        elif typed_dec > decimals(h["value"]):
            left.append(dict(h, why="typed more precisely than the parameter"))
        else:
            spec = "" if typed_dec == decimals(h["value"]) else f"|.{typed_dec}"
            auto.append(dict(h, token=f"[[value:{h['parameter']}{spec}]]"))
    return auto, left


def resolved(ds, sid):
    out = {}
    for path, text in walk(ds.items["study"][sid]):
        out[path] = VALUE_XREF.sub(lambda m: value_text(ds.items["parameter"][m.group(1)], m.group(2)), text)
    return out


def norm(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3})", "", re.sub(r"\s+", " ", s)).replace(" ", " ").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--exclude", action="append", default=[],
                    help="STUDY:PARAMETER:TYPED, a copy that only looks like the value (a nominal 0.5 s, say)")
    a = ap.parse_args()
    folder = Path(a.dataset)
    ds = load(folder)
    auto, left = plan(ds)
    ex = {tuple(e.split(":", 2)) for e in a.exclude}
    left += [dict(h, why="excluded") for h in auto if (h["study"], h["parameter"], h["typed"]) in ex]
    auto = [h for h in auto if (h["study"], h["parameter"], h["typed"]) not in ex]
    before = {sid: resolved(ds, sid) for sid in {h["study"] for h in auto}}
    files = {}
    done, skipped = [], []
    groups = defaultdict(list)
    for h in auto:
        groups[(h["study"], h["typed"], h["unit"], h["token"])].append(h)
    for (sid, typed, unit, token), group in groups.items():
        path = folder / "studies" / f"{sid}.yaml"
        text = files.setdefault(path, path.read_text(encoding="utf-8"))
        rx = re.compile(r"(?<![\w.\-−])" + re.escape(typed) + r"(?:[   ]?)" + re.escape(unit) + r"(?![\w])")
        n = len(rx.findall(text))
        if n != len(group):
            skipped += [dict(h, why=f"{n} copies of '{typed} {unit}' in the file for {len(group)} hits") for h in group]
            continue
        files[path] = rx.sub(token, text)
        done += group
    for h in done:
        print(f"rewrite {h['study']} {h['field']}: {h['typed']} {h['unit']} -> {h['token']}")
    for h in skipped + left:
        print(f"left    {h['study']} {h['field']} {h['parameter']}={h['value']} {h['unit']}: {h['why']}: ...{h['context']}...")
    print(f"{len(done)} rewritten, {len(skipped) + len(left)} left", file=sys.stderr)
    if not a.write:
        return
    old = {p: p.read_text(encoding="utf-8") for p in files}
    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    try:
        ds2 = load(folder)
        bad = []
        for sid, fields in before.items():
            now = resolved(ds2, sid)
            for k, v in fields.items():
                if norm(v) != norm(now.get(k, "")):
                    bad.append((sid, k, v, now.get(k)))
        if bad:
            for sid, k, v, w in bad:
                print(f"CHANGED {sid} {k}:\n  was {v[:300]}\n  now {(w or '')[:300]}", file=sys.stderr)
            raise SystemExit("what a reader sees changed: the files were restored")
    except BaseException:
        for p, t in old.items():
            p.write_text(t, encoding="utf-8")
        raise
    print(f"wrote {len(files)} study files; every study reads as before", file=sys.stderr)


if __name__ == "__main__":
    main()
