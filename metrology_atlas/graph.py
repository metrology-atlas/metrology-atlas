"""The provenance graph: parameters' sources joined with the run records, and what is stale.

Each parameter may name the saved outputs its numbers come from (``sources``, schema 0.5). Each output folder may
hold run records (``_runs/run_*.json``, written by ``provenance.py``) saying which command made which files from
which inputs and code. Joining the two gives a graph from every number to its code and data; walking it answers
"if this changes, what has to be rerun?" and "is anything behind this number out of date?".

For each source the check reports, worst first:

- ``missing``:   the output is not there;
- ``differs``:   the number at ``key`` does not round to the parameter's value (or spread n);
- ``stale``:     an input, the script or an upstream run changed after the run that made the output, or the output
                 itself changed after its run (overwritten by hand or by an unrecorded run), or the run failed;
- ``untraced``:  no run record lists the output (reconstructed records count as traced, marked as such);
- ``ok``.

Parameters without sources are listed apart: by status, as only measured and derived numbers need one.

Paths in records and sources are ``ROOT:path`` against the named roots (``provenance.py``: METROLOGY_ATLAS_ROOTS
or the roots file); absolute paths in older records are mapped back through the roots' aliases.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from metrology_atlas import provenance as pv

LEVELS = ("missing", "differs", "stale", "untraced", "ok")
ROOTED = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(.*)$")
NEEDS_SOURCE = ("measured", "derived")
BASIS = re.compile(r"\[\[(reference|parameter|study):")


@dataclass
class Finding:
    parameter: str
    output: str
    level: str
    reasons: list[str] = field(default_factory=list)
    kind: str = ""
    """The run record's kind (recorded, reconstructed), when one was found."""
    used_by: list[str] = field(default_factory=list)
    """The timing forms and chain steps that take the parameter's numbers (``variable:id field``)."""

    def text(self) -> str:
        why = "; ".join(self.reasons)
        use = f"; used by {', '.join(self.used_by)}" if self.used_by and self.level != "untraced" else ""
        return f"{self.parameter}: {self.level}: {self.output}" + (f" ({why})" if why else "") + use


class Graph:
    """Run records found next to outputs, with a cached staleness verdict per record."""

    def __init__(self, roots: pv.Roots):
        self.roots = roots
        self.scanned: set[Path] = set()
        self.by_output: dict[str, list[tuple[dict, Path]]] = {}
        self.verdicts: dict[Path, list[str]] = {}
        self.hashes: dict[Path, dict] = {}

    # paths -----------------------------------------------------------------------------------------------
    def norm(self, s: str) -> str:
        """A record's or source's path as ROOT:path (absolute paths through the roots and their aliases)."""
        if ROOTED.match(s) and not re.match(r"^[A-Za-z]:[\\/]", s):
            return s
        return self.roots.portable(Path(s), resolve=False)

    def local(self, s: str) -> Path | None:
        return self.roots.resolve(self.norm(s))

    # records ---------------------------------------------------------------------------------------------
    def scan(self, folder: Path) -> None:
        """Index the run records in folder/_runs and in the _runs of its parents, up to the root."""
        f = folder
        for _ in range(6):
            if f in self.scanned:
                break
            self.scanned.add(f)
            runs = f / pv.RUNS
            if runs.is_dir():
                for p in sorted(runs.glob("run_*.json")):
                    try:
                        rec = json.loads(p.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    for o in rec.get("outputs") or []:
                        if o.get("path"):
                            self.by_output.setdefault(self.norm(o["path"]), []).append((rec, p))
            if f.parent == f or self.roots.is_root(f):
                break
            f = f.parent

    def producers(self, portable: str) -> list[tuple[dict, Path]]:
        """Records listing this output, or (for a folder) any file under it; latest first."""
        loc = self.roots.resolve(portable)
        if loc is not None:
            self.scan(loc if loc.is_dir() else loc.parent)
        hits = list(self.by_output.get(portable, []))
        if loc is not None and loc.is_dir():
            pre = portable.rstrip("/") + "/"
            hits += [r for k, v in self.by_output.items() if k.startswith(pre) for r in v]
        seen, out = set(), []
        for rec, p in sorted(hits, key=lambda x: (_epoch(x[0]), x[1].name), reverse=True):
            if p not in seen:
                seen.add(p)
                out.append((rec, p))
        return out

    def current(self, p: Path, like: dict, skip: Path | None = None) -> dict | None:
        """The file's or folder's identity now, in the form of the recorded one (cached). skip: the run's own output
        folder, left out of an input folder that contains it, as the recorder did."""
        key = (p, skip)
        if key in self.hashes:
            return self.hashes[key]
        try:
            if like.get("sha256") or like.get("tree_sha256"):
                d = pv.describe(p, skip=skip)
            else:                      # a fingerprint was recorded: compare the fingerprint, no hashing
                d = pv.describe(p, hash_limit=0, tree_limit=0, skip=skip)
        except OSError:
            d = None
        self.hashes[key] = d
        return d

    def changed(self, rec_item: dict, started: float | None = None, skip: Path | None = None) -> str | None:
        """Why a recorded input or output no longer matches (None if it does, or cannot be compared).

        A folder whose tree hash differs only because files were added after the run (a summary written next to the
        parts it read) still matches: the tree of the files no newer than the run's start is compared too."""
        if rec_item.get("kind") == "root" or self.norm(rec_item.get("path", "")).split(":", 1)[-1] in ("", "."):
            return None                # a whole root (--work $W): its files are checked where they are named
        loc = self.local(rec_item.get("path", ""))
        if loc is None:
            return None                # outside the configured roots: cannot check here
        if not loc.exists():
            return "gone"
        now = self.current(loc, rec_item, skip if skip is not None and loc in skip.parents else None)
        if now is None:
            return None
        if rec_item.get("sha256"):
            return None if now.get("sha256") == rec_item["sha256"] else "content changed"
        if rec_item.get("tree_sha256"):
            if now.get("tree_sha256") == rec_item["tree_sha256"]:
                return None
            if started is not None and tree_before(loc, started, skip) == rec_item["tree_sha256"]:
                return None
            return "content changed"
        if "files" in rec_item and now.get("files") != rec_item["files"]:
            return f"{rec_item['files']} -> {now.get('files')} files"
        if "bytes" in rec_item and now.get("bytes") != rec_item["bytes"]:
            return "size changed"
        return None                    # modification times are local to each machine: not compared

    def verdict(self, rec: dict, path: Path, depth: int = 0) -> list[str]:
        """Reasons the run is out of date (empty: up to date as far as can be checked)."""
        if path in self.verdicts:
            return self.verdicts[path]
        self.verdicts[path] = []      # cycle guard
        why = []
        if rec.get("kind") == "recorded" and (rec.get("exit_code") not in (0, None) or not rec.get("finished")):
            why.append(f"run {path.name} {'failed' if rec.get('exit_code') else 'did not finish'}")
        s = rec.get("script") or {}
        if s.get("path") and s.get("sha256"):
            loc = self.local(s["path"])
            if loc is not None and loc.is_file() and pv.sha256(loc) != s["sha256"]:
                why.append(f"code changed: {self.norm(s['path'])}")
        t0 = None
        try:
            t0 = dt.datetime.fromisoformat(rec["started"]).timestamp() if rec.get("started") else None
        except (TypeError, ValueError):
            pass
        out = self.local(rec["out"]) if rec.get("out") else None
        ins = rec.get("inputs") or []
        locs = [self.local(i.get("path", "")) for i in ins]
        for i, li in zip(ins, locs):
            # a folder named on the command line that holds other, narrower inputs of the same run (--survey DIR with
            # --input DIR/steps_agg): the narrower ones say what is read, so the folder itself is not compared
            if li is not None and any(lj is not None and li in lj.parents for lj in locs):
                continue
            c = self.changed(i, t0, out)
            if c:
                why.append(f"input {self.norm(i['path'])}: {c}")
                continue
            if depth < 12 and i.get("path") and i.get("kind") != "root" \
                    and self.norm(i["path"]).split(":", 1)[-1] not in ("", "."):
                for up, up_path in self.producers(self.norm(i["path"]))[:1]:
                    v = self.verdict(up, up_path, depth + 1)
                    if v:
                        why.append(f"upstream {self.norm(i['path'])}: {v[0]}")
        self.verdicts[path] = why
        return why


def _epoch(rec: dict) -> float:
    """When a run started, as epoch seconds (records carry their machine's offset; names do not sort across machines)."""
    for k in ("started", "finished"):
        try:
            return dt.datetime.fromisoformat(rec[k]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
    return 0.0


def tree_before(p: Path, t: float, skip: Path | None = None) -> str | None:
    """Tree hash (as provenance.describe) of the folder's files last modified no later than t."""
    h, n = hashlib.sha256(), 0
    try:
        for q in sorted(p.rglob("*")):
            parts = q.relative_to(p).parts
            if pv.RUNS in parts or ".git" in parts or "__pycache__" in parts or not q.is_file() \
                    or (skip is not None and skip in q.parents):
                continue
            if q.stat().st_mtime > t + 1:
                continue
            h.update(f"{q.relative_to(p).as_posix()}\0{pv.sha256(q)}\n".encode())
            n += 1
    except OSError:
        return None
    return h.hexdigest() if n else None


# values ----------------------------------------------------------------------------------------------------
def lookup(doc, key: str):
    """The value at key (parts joined by dots; a dict key may itself contain dots)."""
    parts = key.split(".")
    x, i = doc, 0
    while i < len(parts):
        if isinstance(x, list):
            try:
                x = x[int(parts[i])]
            except (ValueError, IndexError):
                raise KeyError(key) from None
            i += 1
            continue
        if not isinstance(x, dict):
            raise KeyError(key)
        for j in range(len(parts), i, -1):     # longest key first
            k = ".".join(parts[i:j])
            if k in x:
                x, i = x[k], j
                break
        else:
            raise KeyError(key)
    return x


def tolerance(v) -> float:
    exp = Decimal(str(v)).normalize().as_tuple().exponent
    return 0.5 * 10 ** min(int(exp), 0) + 1e-9 if isinstance(exp, int) else 0.5


def agrees(target, found, scale: float) -> bool:
    if isinstance(found, bool):
        return False
    if isinstance(found, (int, float)):
        return abs(found * scale - target) <= tolerance(target)
    if isinstance(found, str):                 # e.g. a winning candidate 'rmean|8|15'
        nums = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", found)]
        return any(abs(n * scale - target) <= tolerance(target) for n in nums)
    return False


def check_value(p: dict, sources: list[dict], g: Graph) -> dict[int, str]:
    """Index of source -> why its number disagrees with the parameter."""
    bad: dict[int, str] = {}
    total, parts = 0.0, []
    for i, s in enumerate(sources):
        if not s.get("key"):
            continue
        what = s.get("field", "value")
        if what not in ("value", "sum", "n"):
            continue
        loc = g.local(s["output"])
        if loc is None or not loc.is_file() or loc.suffix != ".json":
            continue
        try:
            found = lookup(json.loads(loc.read_text(encoding="utf-8")), s["key"])
        except (OSError, ValueError, KeyError):
            bad[i] = f"no key {s['key']}"
            continue
        scale = float(s.get("scale", 1))
        if what == "sum":
            if isinstance(found, (int, float)) and not isinstance(found, bool):
                total += found * scale
                parts.append(i)
            continue
        target = p.get("value") if what == "value" else (p.get("spread") or {}).get("n")
        if target is None:
            continue
        if not agrees(target, found, scale):
            bad[i] = f"{s['key']} = {found!r}" + (f" x {scale:g}" if scale != 1 else "") + f", parameter {target}"
    if parts and p.get("value") is not None and abs(total - p["value"]) > tolerance(p["value"]):
        for i in parts:
            bad[i] = f"sum of {len(parts)} keys = {total:.6g}, parameter {p['value']}"
    return bad


def check(ds, roots: pv.Roots | None = None) -> tuple[list[Finding], dict[str, list[str]]]:
    """Every source of every parameter, and the parameters without sources by status."""
    roots = roots or pv.Roots.load()
    g = Graph(roots)
    findings: list[Finding] = []
    unsourced: dict[str, list[str]] = {}
    used: dict[str, list[str]] = {}
    for vid, links in (getattr(ds, "links", None) or {}).items():
        for l in links:
            for pid in _linked(l):
                used.setdefault(pid, []).append(f"variable:{vid} {l.get('field', '')}")
    for pid, p in sorted(ds.items.get("parameter", {}).items()):
        if p.get("status") in ("withdrawn", "superseded"):
            continue
        sources = p.get("sources") or []
        if not sources:
            st = p.get("status", "?")
            unsourced.setdefault(st, []).append(pid)
            # an assumed, documented or estimated number needs no output, but it should say where it comes from
            if st not in NEEDS_SOURCE and not p.get("study") and not BASIS.search(str(p)):
                unsourced.setdefault("no basis", []).append(pid)
            continue
        bad = check_value(p, sources, g)
        for i, s in enumerate(sources):
            out = g.norm(s["output"])
            f = Finding(pid, out, "ok", used_by=used.get(pid, []))
            loc = g.local(out)
            if loc is None:
                f.level, f.reasons = "untraced", [f"root '{out.split(':', 1)[0]}' is not configured here"]
            elif not loc.exists():
                f.level = "missing"
            else:
                prods = g.producers(out)
                if i in bad:
                    f.level, f.reasons = "differs", [bad[i]]
                if not prods:
                    if f.level == "ok":
                        f.level = "untraced"
                else:
                    # prefer the record whose output hash matches the file as it is now
                    chosen = None
                    for rec, path in prods:
                        o = next((x for x in rec.get("outputs") or [] if g.norm(x.get("path", "")) == out), None)
                        if o is None or g.changed(o) is None:
                            chosen = (rec, path, o)
                            break
                    why = []
                    if chosen is None:
                        rec, path = prods[0]
                        chosen = (rec, path, None)
                        why.append(f"output changed after run {path.name}")
                    rec, path, _ = chosen
                    f.kind = rec.get("kind", "")
                    why += g.verdict(rec, path)
                    if why and f.level == "ok":
                        f.level = "stale"
                    f.reasons += why
            findings.append(f)
    findings.sort(key=lambda x: (LEVELS.index(x.level), x.parameter))
    return findings, unsourced


def _linked(link: dict) -> list[str]:
    """The parameters a form link reads (its own and any in a nested 'plus')."""
    out = [link["parameter"]] if isinstance(link.get("parameter"), str) else []
    if isinstance(link.get("plus"), dict):
        out += _linked(link["plus"])
    return out


def report(findings: list[Finding], unsourced: dict[str, list[str]]) -> str:
    """Plain-text report: counts, then every finding that is not ok."""
    counts = {lv: sum(1 for f in findings if f.level == lv) for lv in LEVELS}
    rec = sum(1 for f in findings if f.level == "ok" and f.kind == "reconstructed")
    lines = ["provenance: " + ", ".join(f"{n} {lv}" + (f" ({rec} on reconstructed records)" if lv == "ok" and rec else "")
                                        for lv, n in counts.items() if n)
             + f" (sources of {len({f.parameter for f in findings})} parameters)"]
    need = sum(len(v) for k, v in unsourced.items() if k in NEEDS_SOURCE)
    kinds = {k: v for k, v in unsourced.items() if k != "no basis"}
    if kinds:
        lines.append("provenance: no sources: " + ", ".join(f"{len(v)} {k}" for k, v in sorted(kinds.items()))
                     + f" ({need} measured or derived)")
    for k in sorted(v for k, v in kinds.items() if k in NEEDS_SOURCE for v in v):
        lines.append(f"provenance: {k}: no sources")
    for k in unsourced.get("no basis", []):
        lines.append(f"provenance: {k}: no sources and no study, reference or parameter cited")
    lines += [f"provenance: {f.text()}" for f in findings if f.level != "ok"]
    return "\n".join(lines)
