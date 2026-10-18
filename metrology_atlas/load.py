"""Load a dataset folder, check it, and derive the relations each item does not state itself."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from metrology_atlas.code import CODE_XREF, check_code, snapshot_path, split
from metrology_atlas.model import DATASET, KINDS, REFERENCE, Dataset, Field, Kind

XREF = re.compile(r"\[\[([a-z]+):([a-z0-9][a-z0-9-]*)(?:\|([^\]]+))?\]\]")
"""``[[kind:id]]`` or ``[[kind:id|label]]`` in prose."""
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CODE_SPAN = re.compile(r"`[^`\n]*`")
"""Inline code in prose: shown as written, so [[...]] inside it is not a reference."""


def record_xref(ds_or_meta) -> re.Pattern | None:
    """``[[case:1234]]`` or ``[[case:1234|label]]``, for the dataset's record word."""
    meta = getattr(ds_or_meta, "meta", ds_or_meta) or {}
    name = (meta.get("records") or {}).get("name")
    return re.compile(r"\[\[" + re.escape(name) + r":(\d+)(?:\|([^\]]+))?\]\]") if name else None


def bare(text: str) -> str:
    """Prose with inline code removed, for finding references."""
    return CODE_SPAN.sub("", text)


class AtlasError(Exception):
    """The dataset breaks a rule. ``problems`` lists every one found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"{len(problems)} problem(s):\n" + "\n".join(f"  - {p}" for p in problems))
        self.problems = problems


def load(folder: str | Path) -> Dataset:
    """Read and check a dataset folder.

    Raises:
        AtlasError: Listing every problem: bad YAML, missing or unknown fields, wrong types, dangling references,
            and text that matches one of the dataset's forbidden patterns (such as record identifiers).
    """
    folder = Path(folder)
    problems: list[str] = []
    meta_path = folder / "dataset.yaml"
    if not meta_path.exists():
        raise AtlasError([f"{folder}: no dataset.yaml"])
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    ds = Dataset(meta=meta, folder=str(folder), items={k: {} for k in KINDS} | {"reference": {}})

    for kind in KINDS.values():
        generated = sorted((folder / "_generated" / kind.folder).glob("*.yaml"))
        for path in generated + sorted((folder / kind.folder).glob("*.yaml")):
            rel = str(path.relative_to(folder)).replace("\\", "/")
            try:
                item = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as error:
                problems.append(f"{rel}: not valid YAML ({error})")
                continue
            if item is None and rel.startswith("_generated/"):
                continue  # emptied by its import script
            if not isinstance(item, dict):
                problems.append(f"{rel}: must be a mapping")
                continue
            if item.get("id") != path.stem:
                problems.append(f"{rel}: id '{item.get('id')}' must equal the file name '{path.stem}'")
            _store(ds, kind, item, rel, problems)
    refs_path = folder / "references.yaml"
    if refs_path.exists():
        for item in yaml.safe_load(refs_path.read_text(encoding="utf-8")) or []:
            _store(ds, REFERENCE, item, "references.yaml", problems)

    for (kind_name, id_), rel in ds.sources.items():
        kind = KINDS.get(kind_name, REFERENCE)
        item = ds.items[kind_name][id_]
        _check_fields(ds, kind.fields, item, f"{rel}", problems)
        if kind_name == "link":
            _check_link_modes(ds, item, rel, problems)
        if kind_name == "variable":
            _check_timing(ds, item, rel, problems)
        if kind_name == "software":
            for k, part in enumerate(item.get("parts") or []):
                if isinstance(part, dict) and isinstance(part.get("path"), str):
                    check_code(ds, f"{id_}/{part['path']}", f"{rel}: 'parts'[{k}]", problems, ds.warnings)
        _check_figures(ds, item, rel, problems)
    for k, src in enumerate(meta.get("sources") or []):
        if isinstance(src, dict) and src.get("folder") and not (folder / src["folder"]).is_dir():
            problems.append(f"dataset.yaml: sources[{k}]: no folder {src['folder']}")
    for (kind_name, id_), rel in ds.sources.items():
        item = ds.items[kind_name][id_]
        if kind_name == "study":
            refs = [item.get("model")]
        elif kind_name == "variable" and isinstance(item.get("value"), dict):
            refs = [item["value"].get("model")]
            sp = item["value"].get("spread")
            if isinstance(sp, str):
                path, _, key = sp.partition("#")
                snap = snapshot_path(ds, path)
                if snap is None or not snap.is_file():
                    problems.append(f"{rel}: spread '{sp}': not in a snapshot")
                elif key not in json.loads(snap.read_text(encoding="utf-8")).get("variables", {}):
                    problems.append(f"{rel}: spread '{sp}': no entry '{key}'")
        else:
            continue
        for ref in refs:
            if isinstance(ref, str):
                check_code(ds, ref, f"{rel}: model", problems, ds.warnings)
                snap = snapshot_path(ds, ref)
                if snap is None:
                    problems.append(f"{rel}: model '{ref}': its software has no snapshot in dataset.yaml sources")
                elif not snap.is_file():
                    problems.append(f"{rel}: model '{ref}': not in the snapshot ({snap})")
    for k, pg in enumerate(meta.get("pages") or []):
        if isinstance(pg, dict) and pg.get("file"):
            f = folder / "pages" / pg["file"]
            if not f.is_file():
                problems.append(f"dataset.yaml: pages[{k}]: no file pages/{pg['file']}")
            else:
                text = f.read_text(encoding="utf-8")
                meta.setdefault("_page_text", {})[pg["id"]] = text
                for kind, ref, _ in XREF.findall(bare(text)):
                    if kind == (meta.get("records") or {}).get("name"):
                        continue
                    if kind != "figure" and (kind not in ds.items or ref not in ds.items[kind]):
                        problems.append(f"pages/{pg['file']}: [[{kind}:{ref}]] does not exist")
                for ref, _ in CODE_XREF.findall(bare(text)):
                    check_code(ds, ref, f"pages/{pg['file']}", problems, ds.warnings)
    _check_fields(ds, DATASET, {k: v for k, v in meta.items() if not k.startswith("_")}, "dataset.yaml", problems)
    _check_figures(ds, meta, "dataset.yaml", problems)
    _check_forbidden(ds, problems)
    if problems:
        raise AtlasError(problems)
    return ds


def _store(ds: Dataset, kind: Kind, item: dict, rel: str, problems: list[str]) -> None:
    id_ = item.get("id")
    if not isinstance(id_, str) or not ID.match(id_):
        problems.append(f"{rel}: id {id_!r} must be lower-case letters, digits and hyphens")
        return
    prior = ds.sources.get((kind.name, id_), "")
    if prior.startswith("_generated/") and not rel.startswith("_generated/"):
        # a hand-written file over a generated one: its fields win; mappings merge one level deep
        base = ds.items[kind.name][id_]
        for key, value in item.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = {**base[key], **value}
            else:
                base[key] = value
        ds.sources[(kind.name, id_)] = rel
        return
    if id_ in ds.items[kind.name]:
        problems.append(f"{rel}: {kind.name} '{id_}' is defined twice (also in {ds.sources[(kind.name, id_)]})")
        return
    ds.items[kind.name][id_] = item
    ds.sources[(kind.name, id_)] = rel


def _kinds_of(f: Field) -> tuple[str, ...]:
    if not f.ref:
        return (*KINDS, "reference")
    return (f.ref,) if isinstance(f.ref, str) else f.ref


def _resolve(ds: Dataset, kinds: tuple[str, ...], value: object) -> bool:
    return isinstance(value, str) and any(value in ds.items.get(k, {}) for k in kinds)


def _check_fields(ds: Dataset, fields: tuple[Field, ...], item: dict, where: str, problems: list[str]) -> None:
    known = {f.name for f in fields}
    for key in item:
        if key not in known:
            problems.append(f"{where}: unknown field '{key}'")
    for f in fields:
        value = item.get(f.name)
        if value is None:
            if f.required:
                problems.append(f"{where}: '{f.name}' is required")
            continue
        at = f"{where}: '{f.name}'"
        if f.type in {"str", "text"}:
            if not isinstance(value, str):
                problems.append(f"{at} must be text")
            elif f.type == "text":
                rx = record_xref(ds)
                if rx:
                    for rid, _ in rx.findall(bare(value)):
                        mx = (ds.meta.get("records") or {}).get("max")
                        if mx and not 0 < int(rid) <= mx:
                            problems.append(f"{at}: record {rid} is out of range (1-{int(mx)})")
                for kind, ref, _ in XREF.findall(bare(value)):
                    if kind == "figure" or kind == (ds.meta.get("records") or {}).get("name"):
                        continue  # figures are checked per item, against its own figures
                    if kind not in ds.items:
                        problems.append(f"{at}: [[{kind}:{ref}]] names an unknown kind")
                    elif ref not in ds.items[kind]:
                        problems.append(f"{at}: [[{kind}:{ref}]] does not exist")
                for ref, _ in CODE_XREF.findall(bare(value)):
                    check_code(ds, ref, at, problems, ds.warnings)
        elif f.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"{at} must be a number")
        elif f.type == "bool":
            if not isinstance(value, bool):
                problems.append(f"{at} must be true or false")
        elif f.type == "range":
            ok = (isinstance(value, list) and len(value) == 2
                  and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))
            if not ok or value[0] > value[1]:
                problems.append(f"{at} must be [low, high], two numbers with low <= high")
        elif f.type == "date":
            if not isinstance(value, dt.date):
                problems.append(f"{at} must be a date (YYYY-MM-DD)")
        elif f.type == "enum":
            if value not in f.choices:
                problems.append(f"{at} must be one of {', '.join(f.choices)}")
        elif f.type == "ref":
            if not _resolve(ds, _kinds_of(f), value):
                problems.append(f"{at}: '{value}' is not a known {' or '.join(_kinds_of(f))}")
        elif f.type == "ints":
            if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
                problems.append(f"{at} must be a list of whole numbers")
        elif f.type in {"refs", "strs"}:
            if not isinstance(value, list):
                problems.append(f"{at} must be a list")
                continue
            for v in value:
                if f.type == "refs" and not _resolve(ds, _kinds_of(f), v):
                    problems.append(f"{at}: '{v}' is not a known {' or '.join(_kinds_of(f))}")
                if f.type == "strs" and not isinstance(v, str):
                    problems.append(f"{at}: {v!r} must be text")
                elif f.name == "code" and isinstance(v, str):
                    check_code(ds, v, at, problems, ds.warnings)
        elif f.type == "obj":
            if not isinstance(value, dict):
                problems.append(f"{at} must be a mapping")
            else:
                _check_fields(ds, f.fields, value, at, problems)
        elif f.type == "objs":
            if not isinstance(value, list):
                problems.append(f"{at} must be a list")
            else:
                for i, v in enumerate(value):
                    if isinstance(v, dict):
                        _check_fields(ds, f.fields, v, f"{at}[{i}]", problems)
                    else:
                        problems.append(f"{at}[{i}] must be a mapping")


def _check_link_modes(ds: Dataset, link: dict, rel: str, problems: list[str]) -> None:
    clock = ds.get("clock", link.get("clock", ""))
    if clock is None:
        return
    modes = {m.get("id") for m in clock.get("modes") or []}
    for m in link.get("modes") or []:
        if m not in modes:
            problems.append(f"{rel}: mode '{m}' is not a mode of clock '{link['clock']}'")


def _check_timing(ds: Dataset, signal: dict, rel: str, problems: list[str]) -> None:
    domains = {d.get("id") for d in ds.meta.get("domains") or []}
    forms = signal.get("timing") or []
    for t in forms:
        if isinstance(t, dict) and t.get("domain") not in domains:
            problems.append(f"{rel}: timing '{t.get('id')}': domain '{t.get('domain')}' is not in dataset.yaml domains")
    ids = {t.get("id") for t in forms if isinstance(t, dict)}
    for t in forms:
        for c in (t.get("corrects") or []) if isinstance(t, dict) else []:
            if c not in ids or c == t.get("id"):
                problems.append(f"{rel}: timing '{t.get('id')}' corrects '{c}', which is not another form of this signal")
    if sum(1 for t in forms if isinstance(t, dict) and t.get("default")) > 1:
        problems.append(f"{rel}: more than one timing form is marked default")


def _check_figures(ds: Dataset, item: dict, rel: str, problems: list[str]) -> None:
    figs = [f for f in item.get("figures") or [] if isinstance(f, dict)]
    ids = [f.get("id") for f in figs]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"{rel}: figure id '{dup}' is used twice")
    for f in figs:
        if f.get("file") and not (Path(ds.folder) / "figures" / f["file"]).is_file():
            problems.append(f"{rel}: figure '{f.get('id')}': no file figures/{f['file']}")
    for text in _strings(item):
        for kind, ref, _ in XREF.findall(bare(text)):
            if kind == "figure" and ref not in ids:
                problems.append(f"{rel}: [[figure:{ref}]] is not one of this item's figures")


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _check_forbidden(ds: Dataset, problems: list[str]) -> None:
    rules = [(re.compile(r["pattern"]), r.get("why", "")) for r in ds.meta.get("forbidden_patterns") or []]
    if not rules:
        return
    every = [(ds.meta, "dataset.yaml")] + [(ds.items[k][i], rel) for (k, i), rel in ds.sources.items()]
    rec = record_xref(ds)
    for item, rel in every:
        for text in _strings(item):
            if rec:
                text = rec.sub("", text)   # deliberate references are allowed
            for rule, why in rules:
                m = rule.search(text)
                if m:
                    problems.append(f"{rel}: '{m.group(0)}' matches a forbidden pattern ({why})")


def derived(ds: Dataset) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Relations stated on the other side: kind -> id -> relation name -> ids."""
    out: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    def add(kind: str, id_: str, rel: str, other: str) -> None:
        if other not in out[kind][id_][rel]:
            out[kind][id_][rel].append(other)

    for sid, s in ds.items["variable"].items():
        if s.get("device"):
            add("device", s["device"], "variables", sid)
        if s.get("stamp_clock"):
            add("clock", s["stamp_clock"], "stamps", sid)
        for st in (s.get("value") or {}).get("studies") or []:
            add("study", st, "variables", sid)
        if s.get("sample_clock"):
            add("clock", s["sample_clock"], "spaces", sid)
    for did, d in ds.items["device"].items():
        for c in d.get("clocks") or []:
            add("clock", c, "devices", did)
    for lid, link in ds.items["link"].items():
        add("clock", link["clock"], "links", lid)
        add("clock", link["against"], "links", lid)
    for pid, p in ds.items["parameter"].items():
        if p.get("study"):
            add("study", p["study"], "parameters", pid)
        for target in p.get("about") or []:
            for kind in ("clock", "device", "variable", "link", "observation"):
                if target in ds.items[kind]:
                    add(kind, target, "parameters", pid)
    for stid, st in ds.items["study"].items():
        for m in st.get("methods") or []:
            add("method", m, "studies", stid)
        for t in st.get("techniques") or []:
            add("technique", t, "studies", stid)
        for kind, key in (("clock", "clocks"), ("device", "devices"), ("variable", "variables")):
            for x in st.get(key) or []:
                add(kind, x, "studies", stid)
        for x in st.get("supersedes") or []:
            add("study", x, "superseded_by", stid)
    for oid, o in ds.items["observation"].items():
        for kind, key in (("clock", "clocks"), ("device", "devices"), ("variable", "variables"), ("study", "studies")):
            for x in o.get(key) or []:
                add(kind, x, "observations", oid)
        for x in o.get("supersedes") or []:
            add("observation", x, "superseded_by", oid)
    for eid, e in ds.items.get("example", {}).items():
        for kind, key in (("variable", "variables"), ("study", "studies"), ("observation", "observations")):
            for x in e.get(key) or []:
                add(kind, x, "examples", eid)
    for mid, m in ds.items["method"].items():
        for t in m.get("techniques") or []:
            add("technique", t, "methods", mid)
    for kind in ("study", "observation", "example"):
        for id_, item in ds.items.get(kind, {}).items():
            for ref in item.get("code") or []:
                if ref.split("/")[0] in ds.items["software"]:
                    add("software", split(ref)[0], {"study": "studies", "observation": "observations", "example": "examples"}[kind], id_)
    for (kind, id_) in ds.sources:
        if kind == "reference":
            continue
        for text in _strings(ds.items[kind][id_]):
            names = {split(r)[0] for r, _ in CODE_XREF.findall(bare(text))}
            names |= {ref for k, ref, _ in XREF.findall(bare(text)) if k == "software"}
            for n in names:
                if n in ds.items["software"] and (kind, id_) != ("software", n):
                    add("software", n, "mentioned_in", f"{kind}:{id_}")
    for kind in (*KINDS, "reference"):
        for id_, item in ds.items[kind].items():
            for r in item.get("references") or []:
                add("reference", r, "cited_by", f"{kind}:{id_}")
    for r in ds.meta.get("references") or []:
        add("reference", r, "cited_by", "dataset:")
    rx = record_xref(ds)
    if rx:
        for (kind, id_) in ds.sources:
            item = ds.items[kind][id_]
            ids = {int(r) for t in _strings(item) for r, _ in rx.findall(t)}
            ids |= {r for f in item.get("figures") or [] if isinstance(f, dict) for r in f.get("records") or []}
            for r in sorted(ids):
                add("record", str(r), "mentioned_in", f"{kind}:{id_}")
    return out
