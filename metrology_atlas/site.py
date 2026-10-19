"""Write a dataset as a Zensical (Material-style) site: one Markdown page per item, plus index pages."""

from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

from metrology_atlas.chart import AXES, CHART_JS, chart_forms
from metrology_atlas.code import CODE_XREF, code_url, split
from metrology_atlas.compile import parameter_text, to_json
from metrology_atlas.load import XREF, derived
from metrology_atlas.model import KINDS, QUESTION_KIND_TITLES, QUESTION_KINDS, Dataset
from metrology_atlas.planner import planner_page

OPEN_QUESTIONS_MARK = "<!-- atlas:open-questions -->"
"""In a free page, replaced by the list of open questions (all kinds except next steps)."""
ANCHOR_ORDER = ("open", "assumption", "convention", "tested")
ANCHOR_BASIS_LABEL = {"tested": "tested", "convention": "convention", "assumption": "assumption", "open": "open"}
QUESTION_LABEL = {"phenomenon": "unexplained phenomenon", "hypothesis": "weakly supported hypothesis",
                  "assumption": "untestable assumption", "conflict": "conflict between studies",
                  "next step": "next step"}

STATUS_NOTE = {
    "measured": "Measured in a study.",
    "derived": "Calculated from measured values.",
    "estimated": "Estimated from related measurements or documentation; not measured directly.",
    "assumed": "Set by assumption; not measured here.",
    "withdrawn": "Withdrawn: shown for the record, do not use.",
    "superseded": "Superseded by a later value.",
}


OBS_ORDER = ["established", "likely", "open", "withdrawn"]
OBS_NOTE = {
    "established": "shown on many cases, with a control.",
    "likely": "consistent, with a known gap.",
    "open": "seen, not explained.",
    "withdrawn": "claimed earlier, not supported.",
}


class Site:
    """Renders every page of the atlas website as Markdown from a loaded dataset.

    One instance per build. `start` sets the page being written (its item and its path back to the site root);
    the per-kind methods (`clock`, `variable`, `study`, ...) return a page's Markdown."""
    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.rel = derived(ds)
        self.base = "../"
        self.item: dict | None = None
        self.placed: set[str] = set()

    # -- links -----------------------------------------------------------------------------------------------
    def name(self, kind: str, id_: str) -> str:
        """Display name of an item (a short citation for a reference); the id if the item is missing."""
        item = self.ds.get(kind, id_)
        if kind == "reference":
            return short_citation(item.get("citation", "")) if item else id_ or id_
        return item.get("name", id_) if item else id_

    def href(self, kind: str, id_: str) -> str:
        """Relative link from the current page to an item's page."""
        if kind == "reference":
            return f"{self.base}references.md#{id_}"
        return f"{self.base}{KINDS[kind].folder}/{id_}.md"

    def a(self, kind: str, id_: str, label: str | None = None) -> str:
        """Markdown link to an item, labelled with its name unless a label is given."""
        return f"[{label or self.name(kind, id_)}]({self.href(kind, id_)})"

    def kind_of(self, id_: str, kinds=("clock", "device", "variable", "link", "parameter", "study")) -> str:
        """Which kind an id belongs to, searching the given kinds in order."""
        return next(k for k in kinds if id_ in self.ds.items[k])

    def summ(self, text: str | None) -> str:
        """A one-line summary with its [[...]] references resolved (summaries go in tables and page heads)."""
        return self.prose(text).replace("\n", " ").strip() if text else ""

    def prose(self, text: str | None) -> str:
        """Render atlas prose: `[[kind:id]]` and `[[code:...]]` references become links, named records become record
        links.
        """
        if not text:
            return ""

        rec = (self.ds.meta.get("records") or {})
        def sub(m) -> str:
            if m.group(1) == rec.get("name"):
                label = m.group(3) or (rec.get("label") or rec["name"] + " {id}").format(id=m.group(2))
                return f"[{label}]({self.base}records.md#{rec['name']}-{m.group(2)})"
            if m.group(1) == "figure":
                fig = next(f for f in (self.item or {}).get("figures", []) if f["id"] == m.group(2))
                self.placed.add(fig["id"])
                return "\n\n" + self.figure(fig) + "\n\n"
            return self.a(m.group(1), m.group(2), m.group(3))

        parts = re.split(r"(`[^`\n]*`)", text.strip())  # leave inline code as written
        return "".join(p if p.startswith("`") and p.endswith("`") and len(p) > 1 else
                       CODE_XREF.sub(lambda m: self.code_link(m.group(1), m.group(2)), XREF.sub(sub, p))
                       for p in parts)

    def code_link(self, ref: str, label: str | None = None) -> str:
        """A code reference as a link into its repository (plain code text when the repository is unpublished)."""
        name, path = split(ref)
        if not label and path:
            segs = path.rstrip("/").split("/")
            short = path if len(segs) <= 2 else "…/" + "/".join(segs[-2:]) + ("/" if path.endswith("/") else "")
            label = f"`{short}`"
        text = label or self.name("software", name)
        url = code_url(self.ds, ref)
        return f"[{text}]({url})" if url else text

    @staticmethod
    def _base(path: str) -> str:
        last = path.rstrip("/").split("/")[-1]
        return f"`{last}/`" if path.endswith("/") else f"`{last}`"

    def code_list(self, refs) -> str:
        """A study's or observation's code, grouped by software, each software linking to its atlas page."""
        groups: dict[str, list[str]] = {}
        for ref in refs or []:
            groups.setdefault(split(ref)[0], []).append(split(ref)[1])
        out = []
        for name, paths in groups.items():
            sw = self.ds.get("software", name) or {}
            files = ", ".join(self.code_link(f"{name}/{p}") for p in paths if p)
            where = "" if sw.get("repo") else (" (not yet released)" if sw.get("visibility") == "not yet released"
                                               else " (not published)")
            out.append(f"- **{self.a('software', name)}**{where}" + (f": {files}" if files else ""))
        return "\n".join(out)

    def figure(self, f: dict) -> str:
        """Markdown/HTML for one figure: the image (an interactive SVG as an object), caption and alt text."""
        src = f"{self.base}figures/{f['file']}"
        note = "<em>Placeholder figure.</em> " if f.get("placeholder") else ""
        caption = _inline_html(self.prose(f["caption"]).replace("\n", " "))
        if f["file"].endswith(".svg") and f.get("interactive"):
            # an SVG with links: embedded as an object so its links work (an <img> would make them inert)
            ar = ""
            svgf = Path(self.ds.folder) / "figures" / f["file"]
            m = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svgf.read_text(encoding="utf-8")[:2000]) if svgf.is_file() else None
            if m:
                ar = f";aspect-ratio:{float(m.group(1)):.0f}/{float(m.group(2)):.0f}"
            return (f'<figure id="fig-{f["id"]}" style="width:100%">\n  <object data="{src}" type="image/svg+xml" style="width:100%{ar}" '
                    f'aria-label="{f["alt"]}">{f["alt"]}</object>\n'
                    f"  <figcaption>{note}{caption}</figcaption>\n</figure>")
        return (f'<figure markdown="span" id="fig-{f["id"]}">\n  [![{f["alt"]}]({src})]({src})\n'
                f"  <figcaption>{note}{caption}</figcaption>\n</figure>")

    def start(self, item: dict | None, base: str = "../") -> None:
        """Begin a page: set its item and its relative path to the site root, and reset the figures placed so far."""
        self.item, self.base, self.placed = item, base, set()

    def rest_figures(self) -> str:
        """A Figures section with the item's figures not already placed inline."""
        rest = [f for f in (self.item or {}).get("figures", []) if f["id"] not in self.placed]
        return self.section("Figures", "\n\n".join(self.figure(f) for f in rest)) if rest else ""

    def many(self, kind: str, ids) -> str:
        """Comma-separated links to several items of one kind, or a dash."""
        return ", ".join(self.a(kind, i) for i in ids or []) or "—"

    # -- building blocks ---------------------------------------------------------------------------------------
    def glance(self, rows: list[tuple[str, str]]) -> str:
        """The at-a-glance table at the top of a page; empty rows are left out."""
        rows = [(k, v) for k, v in rows if v not in (None, "", "—")]
        if not rows:
            return ""
        return "| | |\n|---|---|\n" + "\n".join(f"| **{k}** | {v} |" for k, v in rows) + "\n"

    def section(self, title: str, body: str) -> str:
        """A level-2 section, or nothing when the body is empty."""
        return f"\n## {title}\n\n{body.strip()}\n" if body and body.strip() not in ("", "—") else ""

    def params_table(self, ids) -> str:
        """Table of parameters: value, status and the study each came from."""
        ids = list(ids or [])
        if not ids:
            return ""
        out = "| Parameter | Value | Status | From |\n|---|---|---|---|\n"
        for pid in ids:
            p = self.ds.get("parameter", pid)
            src = self.a("study", p["study"]) if p.get("study") else "—"
            out += f"| {self.a('parameter', pid)} | {parameter_text(p)} | {p['status']} | {src} |\n"
        return out

    def observations_table(self, ids) -> str:
        """Table of observations, ordered by status then name."""
        ids = sorted(ids or [], key=lambda o: (OBS_ORDER.index(self.ds.get("observation", o)["status"]),
                                               self.ds.get("observation", o)["name"]))
        if not ids:
            return ""
        out = "| Observation | Status | Summary |\n|---|---|---|\n"
        for oid in ids:
            o = self.ds.get("observation", oid)
            out += f"| {self.a('observation', oid)} | {o['status']} | {self.summ(o['summary'])} |\n"
        return out

    def observation(self, i: str, o: dict) -> str:
        """The page for one observation."""
        r = self.rel["observation"][i]
        note = ""
        if o["status"] == "withdrawn":
            by = r.get("superseded_by")
            note = '!!! danger "Withdrawn"\n    ' + (f"Superseded by {self.many('observation', by)}." if by else
                                                    "Kept for the record; it does not stand.") + "\n\n"
        body = (self.section("What it means", self.prose(o.get("consequence")))
                + self.section("What is done about it", self.prose(o.get("handling"))
                               + ("\n\n" + self.code_list(o.get("code")) if o.get("code") else ""))
                + self.section("Detail", self.prose(o.get("description")))
                + self.section("Parameters", self.params_table(r.get("parameters")))
                + self.section("Evidence", self.studies_table(o.get("studies")))
                + self.section("References", self.refs(o.get("references"))))
        return note + self.page(o, self.glance([
            ("Status", f"{o['status']}: {OBS_NOTE[o['status']]}"), ("Clocks", self.many("clock", o.get("clocks"))),
            ("Devices", self.many("device", o.get("devices"))), ("Variables", self.many("variable", o.get("variables"))),
            ("Supersedes", self.many("observation", o.get("supersedes")))]), body)

    def studies_table(self, ids) -> str:
        """Table of studies, newest first."""
        ids = sorted(ids or [], key=lambda s: str(self.ds.get("study", s)["date"]), reverse=True)
        if not ids:
            return ""
        out = "| Study | Date | Status | Summary |\n|---|---|---|---|\n"
        for sid in ids:
            s = self.ds.get("study", sid)
            out += f"| {self.a('study', sid)} | {s['date']} | {s['status']} | {self.summ(s['summary'])} |\n"
        return out

    def refs(self, ids) -> str:
        """Bulleted reference list with links to the references page."""
        return "\n".join(f"- {self.ds.get('reference', r)['citation']} [↗]({self.href('reference', r)})"
                         for r in ids or [])

    def page(self, item: dict, glance: str, body: str) -> str:
        """Assemble a page: title, summary, stub note, at-a-glance table, body, remaining figures and tags."""
        tags = item.get("tags")
        head = f"# {item['name']}\n\n{self.summ(item.get('summary'))}\n\n"
        stub = ("!!! note \"Stub\"\n    Imported from the time-source table; the full page is still to be written.\n\n"
                if tags and "stub" in tags else "")
        return head + stub + glance + body + self.rest_figures() + (f"\n*Tags: {', '.join(tags)}*\n" if tags else "")

    # -- pages per kind ----------------------------------------------------------------------------------------
    def clock(self, i: str, c: dict) -> str:
        """The page for one clock: its modes, links, route to UTC and the variables it stamps."""
        r = self.rel["clock"][i]
        modes = "\n".join(f"- **{m['name']}** (`{m['id']}`): {self.prose(m.get('description'))}"
                          for m in c.get("modes") or [])
        links = ""
        if r.get("links"):
            links = "| Link | Clock | Against | Modes | Rate | Corrected every | Status |\n|---|---|---|---|---|---|---|\n"
            for lid in r["links"]:
                l = self.ds.get("link", lid)
                rate = parameter_text(self.ds.get("parameter", l["rate"])) if l.get("rate") else "—"
                per = (l.get("correction") or {}).get("period")
                per = parameter_text(self.ds.get("parameter", per)) if per else "—"
                links += (f"| {self.a('link', lid)} | {self.a('clock', l['clock'])} | {self.a('clock', l['against'])}"
                          f" | {', '.join(l.get('modes') or []) or 'all'} | {rate} | {per} | {l['status']} |\n")
        body = (self.section("Description", self.prose(c.get("description")))
                + self.section("Route to UTC", self.utc_route(i, c)) + self.section("Modes", modes)
                + self.section("Links to other clocks", links)
                + self.section("Variables stamped by this clock", self.many("variable", r.get("stamps")))
                + self.section("Variables spaced by this clock", self.many("variable", r.get("spaces")))
                + self.section("Parameters", self.params_table(r.get("parameters")))
                + self.section("Observations", self.observations_table(r.get("observations")))
                + self.section("Studies", self.studies_table(r.get("studies")))
                + self.section("References", self.refs(c.get("references"))))
        return self.page(c, self.glance([("Type", c["type"]), ("Nominal", c.get("nominal")),
                                         ("Kept by", self.many("device", r.get("devices")))]), body)

    def device(self, i: str, d: dict) -> str:
        """The page for one device: its variables, clocks and scale factors."""
        r = self.rel["device"][i]
        sig = ""
        if r.get("variables"):
            sig = "| Variable | Type | Stamped by | Spaced by |\n|---|---|---|---|\n" + "".join(
                f"| {self.a('variable', s)} | {self.ds.get('variable', s)['type']} | "
                f"{self.a('clock', self.ds.get('variable', s)['stamp_clock'])} | "
                f"{self.a('clock', self.ds.get('variable', s)['sample_clock']) if self.ds.get('variable', s).get('sample_clock') else '—'} |\n"
                for s in r["variables"])
        docs = "\n".join(f"- [{x['title']}]({x['url']})" for x in d.get("docs") or [])
        body = (self.section("Description", self.prose(d.get("description")))
                + self.section("Device documentation", docs) + self.section("Variables", sig)
                + self.section("Scale factors and resolution", self.track_tables(d.get("tracks")))
                + self.section("Parameters", self.params_table(r.get("parameters")))
                + self.section("Observations", self.observations_table(r.get("observations")))
                + self.section("Studies", self.studies_table(r.get("studies")))
                + self.section("References", self.refs(d.get("references"))))
        return self.page(d, self.glance([("Type", d["type"]), ("Manufacturer", d.get("manufacturer")),
                                         ("Model", d.get("model")), ("Clocks", self.many("clock", d.get("clocks")))]),
                         body)

    @staticmethod
    def _num(x, digits: int = 7) -> str:
        if x is None or x == "":
            return "—"
        if isinstance(x, (int, float)):
            return f"{x:,.0f}" if float(x).is_integer() and abs(x) >= 1000 else f"{x:.{digits}g}"
        return str(x)

    def track_tables(self, tracks: list[dict] | None) -> str:
        """Scale factors and resolution: waveforms (one row per stored configuration), then numerics."""
        if not tracks:
            return ""
        n = self._num

        def cell(t):
            return self.prose(t).replace("\n", " ").strip() if t else "—"

        out = []
        wav = [t for t in tracks if t["kind"] == "waveform"]
        num = [t for t in tracks if t["kind"] == "numeric"]
        if wav:
            rows = []
            for t in wav:
                corr = (f"**{n(t.get('corrected_gain'))} / {n(t.get('corrected_offset'))}**: {cell(t.get('correction'))}"
                        if t.get("corrected_gain") is not None else "—")
                rows.append(f"| `{t['track']}` | {t.get('unit') or '—'} | {t.get('format') or '—'} | {t.get('rate') or '—'} | "
                            f"{n(t.get('gain'))} / {n(t.get('offset'))} | {n(t.get('recordings'))} | {corr} |\n")
            out.append("**Waveform scale factors.** Physical value = offset + stored code × gain, one row per stored "
                       "configuration. A factor shown wrong has its correction in **Corrected to**.\n\n"
                       "| Track | Unit | Stored as | Rate | Gain / offset | Recordings | Corrected to |\n"
                       "|---|---|---|---|---|---:|---|\n" + "".join(rows))
            seen, rows = set(), []
            for t in sorted(wav, key=lambda t: t.get("corrected_gain") is not None):  # an uncorrected row first
                if t["track"] in seen:
                    continue
                seen.add(t["track"])
                rows.append(f"| `{t['track']}` | {t.get('step') or '—'} | {t.get('span') or '—'} | {n(t.get('bits_to_store'))} | "
                            f"{t.get('converter') or '—'} | {cell(t.get('evidence'))} |\n")
            out.append("**Waveform resolution.** *Observed span* is what the data reach, and the whole bits needed to "
                       "store it; *converter* is our estimate of the device's resolution (never less than the span), "
                       "with its evidence. The step is in the physical unit, with the corrected gain where the stored one is wrong.\n\n"
                       "| Track | Step | Observed span (codes used) | Bits to store span | Converter (estimate) | Evidence |\n"
                       "|---|---|---|---:|---|---|\n" + "".join(rows))
        if num:
            rows = [f"| `{t['track']}` | {t.get('unit') or '—'} | {t.get('format') or '—'} | {t.get('rate') or '—'} | "
                    f"{n(t.get('recordings'))} | {n(t.get('grid'))} | {n(t.get('coarser_share'), 2)} | "
                    f"{cell(t.get('rounding'))} | {t.get('range') or '—'} | {cell(t.get('note'))} |\n" for t in num]
            out.append("**Numerics.** Stored as floats with gain 1. *Grid* is the coarsest decimal step holding 99% of "
                       "records; the share on the next coarser grid shows heaping (by chance about 1/2, 1/5 or 1/10).\n\n"
                       "| Track | Unit | Stored as | Interval | Recordings | Grid | Share one step coarser | Rounding | "
                       "Observed range | Note |\n|---|---|---|---|---:|---:|---:|---|---|---|\n" + "".join(rows))
        return "\n\n".join(out)

    # -- a clock's route back to UTC ---------------------------------------------------------------------------
    STATUS_COST = {"measured": 1.0, "derived": 1.2, "estimated": 2.0, "assumed": 3.0, "superseded": 6.0, "withdrawn": 9.0}

    def _graph(self) -> dict[str, list[tuple[str, str]]]:
        g: dict[str, list[tuple[str, str]]] = {}
        for lid, l in self.ds.items["link"].items():
            if l["status"] in ("withdrawn", "superseded"):
                continue
            g.setdefault(l["clock"], []).append((l["against"], lid))
            g.setdefault(l["against"], []).append((l["clock"], lid))
        return g

    def routes(self, start: str, root: str = "utc", limit: int = 4) -> list[list[tuple[str, str | None]]]:
        """Every simple route from a clock to the root through clock links, cheapest first (status-weighted)."""
        g, out = self._graph(), []

        def walk(node, path, seen):
            if node == root:
                out.append(path)
                return
            if len(path) > limit:
                return
            for nxt, lid in g.get(node, []):
                if nxt not in seen:
                    walk(nxt, path + [(nxt, lid)], seen | {nxt})

        walk(start, [(start, None)], {start})
        cost = lambda r: sum(self.STATUS_COST[self.ds.get("link", lid)["status"]] for _, lid in r[1:])
        return sorted(out, key=lambda r: (cost(r), len(r)))

    def _hop(self, lid: str) -> str:
        l = self.ds.get("link", lid)
        bits = []
        if l.get("rate"):
            bits.append("drift " + parameter_text(self.ds.get("parameter", l["rate"])))
        per = (l.get("correction") or {}).get("period")
        if per:
            bits.append("corrected every " + parameter_text(self.ds.get("parameter", per)))
        return (f'<span class="tc-kind">link</span> <span class="tc-st tc-{l["status"]}">{l["status"]}</span> '
                + _inline_html(self.a("link", lid)) + (": " + "; ".join(bits) if bits else ""))

    def shared_utc_links(self) -> set[str]:
        """Links on every clock's best route to UTC (they set every absolute time alike and cancel between clocks)."""
        if not hasattr(self, "_shared"):
            shared = None
            for cid in self.ds.items["clock"]:
                r = self.routes(cid) if cid != "utc" and "utc" in self.ds.items["clock"] else []
                if r:
                    links = {lid for _, lid in r[0][1:]}
                    shared = links if shared is None else shared & links
            self._shared = shared or set()
        return self._shared

    def utc_route(self, i: str, c: dict) -> str:
        """How a clock is traced to UTC: each route through the timing graph, with the links on it."""
        if "utc" not in self.ds.items["clock"]:
            return self.prose(c.get("utc_plan"))
        if i == "utc":
            return "Every route ends here: UTC is the time scale each clock is traced back to."
        routes = self.routes(i)
        plan = self.prose(c.get("utc_plan"))
        if not routes:
            return ('!!! warning "No route to UTC yet"\n    No chain of clock links joins this clock to UTC.\n\n'
                    + (f"**Plan.** {plan}\n" if plan else ""))
        best = routes[0]
        rows = ""
        for k, (node, _) in enumerate(best):
            name = self.name("clock", node)
            node_html = f'<a href="{self.href("clock", node).replace(".md", ".html")}">{name}</a>'
            nxt = self._hop(best[k + 1][1]) if k + 1 < len(best) else "Where every route ends."
            rows += f'<div class="tc-row"><div class="tc-node">{node_html}</div><div class="tc-txt">{nxt}</div></div>'
        shared = self.shared_utc_links()
        own = [self.ds.get("link", lid)["status"] for _, lid in best[1:] if lid not in shared]
        n = len(best) - 1
        if own:
            weakest = max(own, key=lambda st: self.STATUS_COST[st])
            note = (f"its weakest link is **{weakest}**" + (" apart from the link to UTC that every clock shares"
                                                             if len(own) < n else ""))
        else:
            note = "it is the link to UTC that every clock shares"
        out = (f"The route the atlas trusts most ({n} link{'s' if n > 1 else ''}; {note}):\n\n"
               + '<div class="tc tc-route">' + rows + "</div>\n\n")
        if len(routes) > 1:
            def via(r):
                hops = [self.a("clock", r[0][0])]
                for n, lid in r[1:]:
                    hops.append(f"({self.a('link', lid)}) → " + self.a("clock", n))
                return " ".join(hops)
            alt = "\n".join("- " + via(r) for r in routes[1:4])
            out += (f"**Independent checks.** {len(routes) - 1} other route{'s' if len(routes) > 2 else ''} reach "
                    f"UTC; where they meet, the offsets must close around the loop:\n\n{alt}\n\n")
        if plan:
            out += f"**Plan.** {plan}\n"
        return out

    # -- the chain from UTC to a signal's stamp ------------------------------------------------------------------
    AX = (-6, 4)  # log10 seconds shown on the step bars: 1 us to 10,000 s

    def _bar(self, step: dict) -> str:
        x0, x1 = self.AX
        w, h = 240, 18
        sx = lambda v: (math.log10(max(v, 10 ** x0)) - x0) / (x1 - x0) * w
        out = f'<svg viewBox="0 0 {w} {h}" class="tc-bar" aria-hidden="true">'
        for k in range(x0, x1 + 1):
            out += f'<line x1="{sx(10 ** k):.1f}" x2="{sx(10 ** k):.1f}" y1="0" y2="{h}" class="tc-tick"/>'
        dash = ' stroke-dasharray="3 2"' if step["status"] in ("estimated", "assumed") else ""
        for key, cls in (("offset_s", "tc-off"), ("residual_s", "tc-res")):
            r = step.get(key)
            if r:
                a, b = sx(r[0]) if r[0] > 0 else 0.0, sx(r[1])
                if b - a < 3:
                    a, b = max(a - 1.5, 0), min(b + 1.5, w)
                y, hh = (3, 12) if cls == "tc-off" else (6, 6)
                out += f'<rect x="{a:.1f}" y="{y}" width="{b - a:.1f}" height="{hh}" rx="2" class="{cls}"{dash}/>'
        if not step.get("offset_s") and not step.get("residual_s"):
            out += f'<text x="{w / 2}" y="13" class="tc-na">not measured</text>'
        return out + "</svg>"

    def _axis(self) -> str:
        x0, x1 = self.AX
        labels = {-6: "1 µs", -3: "1 ms", 0: "1 s", 3: "1000 s"}
        w = 240
        out = f'<svg viewBox="0 0 {w} 14" class="tc-bar" aria-hidden="true">'
        for k, lab in labels.items():
            x = (k - x0) / (x1 - x0) * w
            anchor = "start" if k == x0 else "middle"
            out += f'<text x="{x:.1f}" y="11" class="tc-ax" text-anchor="{anchor}">{lab}</text>'
        return out + "</svg>"

    def _step_html(self, step: dict) -> str:
        node = step["node"]
        if step.get("clock"):
            node = f'<a href="{self.href("clock", step["clock"])}">{node}</a>'.replace(".md", ".html")
        bits = [_inline_html(self.prose(step["effect"]).replace("\n", " "))]
        if step.get("drift"):
            bits.append(f"<em>Drift:</em> {step['drift']}.")
        refs = []
        if step.get("link"):
            refs.append(self.a("link", step["link"], "clock link"))
        if step.get("parameter"):
            refs.append(self.a("parameter", step["parameter"], "parameter"))
        refs += [self.a("study", x) for x in step.get("studies") or []]
        rng = ""
        if step.get("offset_s"):
            rng += f"{_rng(step['offset_s'])}"
        if step.get("residual_s"):
            rng += f" → {_rng(step['residual_s'])} after correction"
        meta = f'<span class="tc-kind">{step["kind"]}</span> <span class="tc-st tc-{step["status"]}">{step["status"]}</span>'
        if rng:
            meta += f' <span class="tc-rng">{rng}</span>'
        if refs:
            meta += " · " + _inline_html(", ".join(refs))
        return (f'<div class="tc-row"><div class="tc-node">{node}</div><div>{self._bar(step)}</div>'
                f'<div class="tc-txt"><div class="tc-meta">{meta}</div>{" ".join(bits)}</div></div>')

    def auto_chain(self, s: dict) -> list[dict]:
        """A chain from UTC to a variable's stored stamp, derived from its default timing form when none is written."""
        t = next((x for x in s.get("timing") or [] if x.get("default")), (s.get("timing") or [None])[0])
        if t is None:
            return []
        steps = []
        clock = s.get("sample_clock") or s.get("stamp_clock")
        name = self.name("clock", clock) if clock else "Device"
        if t.get("corrected_delay_s"):
            steps.append({"node": name, "clock": clock, "kind": "clock", "status": t["status"],
                          "effect": f"Delay or clock offset to the stamp; removed by the {t.get('correction', 'correction')}.",
                          "offset_s": t["corrected_delay_s"], "residual_s": t["delay_s"]})
        else:
            steps.append({"node": name, "clock": clock, "kind": "transport", "status": t["status"],
                          "effect": "Delay from the end of the interval a value describes to its stamp.",
                          "offset_s": t["delay_s"]})
        steps.append({"node": "Stored time stamp", "kind": "window", "status": t["status"],
                      "effect": "The width of the interval one value or sample stands for.", "offset_s": t["interval_s"]})
        return steps

    def chain(self, s: dict) -> str:
        """The chain section of a variable page: each step from UTC to the stored time stamp."""
        first = self.ds.meta.get("utc_step")
        steps = s.get("chain") or self.auto_chain(s)
        if not steps:
            return ""
        note = "" if s.get("chain") else ("*Derived from this signal's timing table; a written chain is still to come.*\n\n")
        # a chain that starts with its own sync step (another root clock) replaces the dataset's UTC step
        own_root = bool(s.get("chain")) and s["chain"][0]["kind"] == "sync"
        rows = ([first] if first and not own_root else []) + steps
        html = ('<div class="tc"><div class="tc-row tc-head"><div></div><div>' + self._axis() +
                '</div><div class="tc-txt">The clock path first (UTC to the clock that stamps or spaces the samples), then '
                'the signal\'s own path to its stored time. Each bar: the time shift or error the step introduces (pale) '
                'and what is left after the atlas\'s correction (solid), on a log scale; dashed when estimated or '
                'assumed.</div></div>'
                '<div class="tc-row tc-start"><div class="tc-node"><a href="' + self.href("clock", "utc").replace(".md", ".html")
                + '">UTC</a></div><div></div><div class="tc-txt">The reference every chain starts from.</div></div>'
                if "utc" in self.ds.items["clock"] else '<div class="tc">')
        html += "".join(self._step_html(x) for x in rows) + "</div>"
        return note + html

    def _lag(self, x: dict) -> str:
        val = parameter_text(self.ds.get("parameter", x["parameter"])) if x.get("parameter") else ""
        link = f" ({self.a('parameter', x['parameter'], val)})" if val else ""
        return f"**{x['name']}**{link}: {self.prose(x.get('description'))}"

    def variable(self, i: str, s: dict) -> str:
        """The page for one variable: measurand, time side, value side, chain and evidence."""
        r = self.rel["variable"][i]
        delays = "\n".join(f"- {self._lag(x)}" for x in s.get("delays") or [])
        window = self._lag(s["window"]) if s.get("window") else ""
        rate = f"{s['rate_hz']} Hz" if s.get("rate_hz") else None
        timing = ""
        if s.get("timing"):
            doms = {d["id"]: d for d in self.ds.meta.get("domains") or []}
            timing = ("Against the working reference. Delay: from the end of the interval a value describes to its "
                      "stamp. Interval: how wide that interval is.\n\n"
                      "| Form | Delay | Interval | Clock domain | Status | Evidence |\n|---|---|---|---|---|---|\n")
            for t in s["timing"]:
                d = doms.get(t["domain"], {})
                dn = self.a("clock", d["clock"], d["name"]) if d.get("clock") else d.get("name", t["domain"])
                studies = ", ".join(self.a("study", x) for x in t.get("studies") or [])
                timing += (f"| {t['name']}{' (default)' if t.get('default') else ''} | {_rng(t['delay_s'])} | "
                           f"{_rng(t['interval_s'])} | {dn} | {t['status']} | {t['evidence']}"
                           f"{'; ' + studies if studies else ''} |\n")
            timing += f"\nCombine it with other signals in the [synchronisation planner]({self.base}planner.md?s={i}).\n"
        time_side = (self.sub("From UTC to the stored time stamp", self.chain(s)) + self.sub("Timing", timing)
                     + self.sub("Delays", delays) + self.sub("Averaging window", window))
        if not time_side.strip():
            time_side = ("This variable carries no time of its own in the dataset." if not s.get("stamp_clock") else
                         "Its time side is still to be described.")
        coupling = s.get("coupling") or {}
        body = (self.section("What it measures", self.prose(s.get("measurand")))
                + self.section("Description", self.prose(s.get("description")))
                + self.section("Measurement space", self.measurement_space(i, s))
                + self.section("Time", time_side)
                + self.section("Value", self.value_side(s))
                + self.section("Time and value together", (f"**{coupling['status'].capitalize()}.** " if coupling else "")
                               + self.prose(coupling.get("note")))
                + self.section("Parameters", self.params_table(r.get("parameters")))
                + self.section("Observations", self.observations_table(r.get("observations")))
                + self.section("Studies", self.studies_table(r.get("studies")))
                + self.section("Worked examples", self.examples_table(r.get("examples")))
                + self.section("References", self.refs(s.get("references"))))
        return self.page(s, self.glance([
            ("Name in the dataset", f"`{s['source_name']}`" if s.get("source_name") else None), ("Type", s["type"]),
            ("Stored in", s.get("source")),
            ("Device", self.a("device", s["device"]) if s.get("device") else None),
            ("Stamped by", self.a("clock", s["stamp_clock"]) if s.get("stamp_clock") else None),
            ("Spaced by", self.a("clock", s["sample_clock"]) if s.get("sample_clock") else None),
            ("Rate", rate), ("Unit", s.get("unit"))]), body)

    def sub(self, title: str, body: str) -> str:
        """A level-3 subsection, or nothing when the body is empty."""
        return f"\n### {title}\n\n{body.strip()}\n" if body and body.strip() not in ("", "—") else ""

    def value_side(self, s: dict) -> str:
        """The value side of a variable page: resolution, accuracy and its value model, if any."""
        v = s.get("value") or {}
        if not v:
            return "Its value side is still to be described."
        out = self.glance([("Model kind", v.get("kind")), ("Resolution", v.get("resolution")),
                           ("Native step", f"{v['step']} {s.get('unit') or ''}".strip() if v.get("step") else None),
                           ("Accuracy (1 SD)", f"{v['accuracy_sd']} {s.get('unit') or ''}".strip()
                            if v.get("accuracy_sd") is not None else None),
                           ("Anchor", self.anchor_label(v)),
                           ("Status", v.get("status")), ("Studies", self.many("study", v.get("studies")))])
        if v.get("inputs") or v.get("formula"):
            out += self.sub("Derived from", (
                ("Computed from " + " and ".join(self.a("variable", x) for x in v.get("inputs") or []) + ". " if v.get("inputs") else "")
                + (f"Formula: `{v['formula']}`. " if v.get("formula") else "")
                + (f"Uncertainty: {v['combination']}." if v.get("combination") else "")))
        if v.get("spread"):
            out += self.sub("In this release", self.spread_text(v["spread"], s.get("unit") or ""))
        if self.anchor_label(v):
            out += self.sub("Anchor", self.prose(self.anchor_basis(v)[1]) + " See [what an anchor is](../terms.md#anchors) "
                            "and [every variable's anchor](../anchors.md).")
        out += self.sub("Accuracy", self.prose(v.get("accuracy")))
        if v.get("model"):
            out += self.sub("Value model", self.model_summary(v["model"]))
        return out

    def anchor_basis(self, v: dict) -> tuple[str | None, str]:
        """The basis and note of a value's anchor, falling back to the dataset's default when only an anchor is given.
        """
        if v.get("anchor_basis"):
            return v["anchor_basis"], v.get("anchor_note") or ""
        d = self.ds.meta.get("anchor_default") or {}
        if v.get("anchor") and d:
            return d["basis"], d["note"]
        return None, ""

    def anchor_label(self, v: dict) -> str | None:
        """How a variable's rounding interval sits around the recorded value, with the basis for it."""
        basis, _ = self.anchor_basis(v)
        if not (v.get("anchor") or basis):
            return None
        return f"{v.get('anchor') or 'counting rule'} ({ANCHOR_BASIS_LABEL[basis]})" if basis else v.get("anchor")

    @staticmethod
    def anchors_figure() -> str:
        """A schematic of the three anchors, and of a time window stamped at its end."""
        W, L, R = 640, 150, 20
        rows = [("nearest", -0.5, 0.5, "true value within half a step either side"),
                ("floor", 0.0, 1.0, "true value at or above the record (completed years)"),
                ("ceiling", -1.0, 0.0, "true value at or below the record"),
                ("time window", -1.0, 0.0, "stamped at its end: the window lies before the stamp")]
        H = 46 * len(rows) + 40
        X = lambda v: L + (v + 1.6) / 3.2 * (W - L - R)
        o = [f'<svg viewBox="0 0 {W} {H}" class="ms" role="img" aria-label="The three anchors, and a time window '
             'stamped at its end">']
        for k, (name, a, b, note) in enumerate(rows):
            y = 22 + 46 * k
            o.append(f'<text x="8" y="{y + 14}" class="ms-lab">{name}</text>')
            o.append(f'<line x1="{L}" x2="{W - R}" y1="{y + 10}" y2="{y + 10}" class="ms-zero"/>')
            for t in (-1.0, 0.0, 1.0):
                o.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{y + 5}" y2="{y + 15}" class="ms-zero"/>')
            cls = "ms-time" if name == "time window" else "ms-val"
            op = "" if name == "time window" else ' fill-opacity=".35"'
            o.append(f'<rect x="{X(a):.1f}" y="{y + 3}" width="{X(b) - X(a):.1f}" height="14" class="{cls}"{op}/>')
            o.append(f'<circle cx="{X(0):.1f}" cy="{y + 10}" r="4.5" fill="#e65100"/>')
            o.append(f'<text x="{X(0):.1f}" y="{y + 32}" class="ms-tick" text-anchor="middle">{note}</text>')
        y = 22 + 46 * len(rows)
        for t, lab in ((-1.0, "−1 step"), (0.0, "recorded value (or stamp)"), (1.0, "+1 step")):
            o.append(f'<text x="{X(t):.1f}" y="{y + 4}" class="ms-tick" text-anchor="middle">{lab}</text>')
        return '<div class="ms-fig">' + "".join(o) + "</svg></div>\n\n"

    def anchors_concept(self) -> str:
        """The anchors section of the Aim and terms page: what an anchor is, with the figure."""
        return ("\n## Anchors\n\n" + self.anchors_figure()
                + "A recorded value stands for an interval of true values. The **anchor** says where the recorded value "
                "sits in that interval: at the nearest step (the interval is centred on it), at the floor (the true value "
                "lies at or above it, as for completed years or a clock that truncates), or at the ceiling (at or below "
                "it). A wrong anchor shifts every value by up to half a step, always the same way, so it biases averages "
                "rather than adding noise. For a count, the counting rule plays the same role.\n\n"
                "**Windows of time are always anchored at their end.** A value that summarises a stretch of time (an "
                "averaged numeric, a duration, a beat-to-beat estimate over 30 s) is stamped when its window ends: the "
                "data lie before the stamp, never after it, so no value is placed before the data it was made from "
                "existed. The atlas keeps to this for every derived value, and its timing results say how far each "
                "device's stamps depart from it.\n\n"
                "Every variable's anchor, and whether it is tested, a convention, an assumption or open, is listed under "
                "[Anchor decisions](anchors.md).\n")

    def anchors_page(self) -> str:
        """Every anchor decision in one table, the best-supported (tested) first."""
        PAGE_ORDER = ("tested", "convention", "assumption", "open")
        rows = []
        for vid, v in self.ds.items["variable"].items():
            val = v.get("value") or {}
            basis, note = self.anchor_basis(val)
            if not (val.get("anchor") or basis):
                continue
            rows.append((PAGE_ORDER.index(basis) if basis in PAGE_ORDER else 9, v.get("group") or "", v["name"], vid,
                         val, basis, note))
        rows.sort(key=lambda r: r[:3])
        n = {b: sum(1 for r in rows if r[5] == b) for b in ANCHOR_ORDER}
        out = ("# Anchor decisions\n\nEvery variable's anchor, and how well it is supported. What an anchor is, with a "
               "figure, is under [Aim and terms](terms.md#anchors).\n\n"
               "Each anchor below has a basis:\n\n"
               "- **Tested:** the data show it.\n"
               "- **Convention:** the usual rule, not tested; its largest possible effect is half a step.\n"
               "- **Assumption:** relied on, but the data in the release cannot test it; outside evidence could.\n"
               "- **Open:** an alternative is plausible and could matter; the study says what would settle it.\n\n"
               + ", ".join(f"{n[b]} {ANCHOR_BASIS_LABEL[b]}" for b in PAGE_ORDER if n[b]) + ". The tested ones, "
               "the best supported, come first; the unsettled ones (assumption and open) last, in bold. The anchors themselves are read from the value models' pinned "
               "snapshot; the basis is the atlas's judgement and can be challenged like any other result "
               "([how to contribute](contributing.md)).\n\n"
               "| Variable | Group | Step | Anchor | Basis | Why |\n|---|---|---|---|---|---|\n")
        default = (self.ds.meta.get("anchor_default") or {})
        explicit = [r for r in rows if r[4].get("anchor_basis")]
        rest = [r for r in rows if not r[4].get("anchor_basis")]
        def step_of(vid, val):
            return f"{val['step']:g} {self.ds.get('variable', vid).get('unit') or ''}".strip() if val.get("step") else "—"
        for _, grp, _, vid, val, basis, note in explicit:
            why = " ".join(self.prose(note).split()).replace("|", "\\|")
            label = ANCHOR_BASIS_LABEL.get(basis, "—")
            out += (f"| {self.a('variable', vid)} | {grp.split('/')[-1]} | {step_of(vid, val)} | "
                    f"{val.get('anchor') or 'counting rule'} | {('**' + label + '**') if basis in ('open', 'assumption') else label} "
                    f"| {why} |\n")
        if rest:
            out += (f"\n## The other {len(rest)}: the default\n\n{self.prose(default.get('note'))}\n\n"
                    "| Variable | Group | Step | Anchor |\n|---|---|---|---|\n")
            for _, grp, _, vid, val, basis, note in sorted(rest, key=lambda r: (r[1], r[2])):
                out += f"| {self.a('variable', vid)} | {grp.split('/')[-1]} | {step_of(vid, val)} | {val.get('anchor')} |\n"
        return out

    def spread_text(self, ref: str, unit: str) -> str:
        """One sentence on how wide a value model's distributions are across the release."""
        from metrology_atlas.readers import spread
        sp = spread(self.ds, ref)
        if not sp:
            return ""
        def r3(x):
            return f"{x:.3g}"
        def row(name, key):
            a = sp.get(key) or {}
            return (f"| {name} | {r3(a['median'])} {unit} | {r3(a['p10'])} to {r3(a['p90'])} {unit} |\n" if a else "")
        out = (f"How wide the true-value distribution is, record by record, over {sp['with_distribution']:,} of "
               f"{sp['records']:,} records ({sp.get('rows', 'rows')}) that have one. Computed with the pinned model, "
               "aggregates only.\n\n| | Median | p10 to p90 |\n|---|---|---|\n"
               + row("Standard deviation", "sd") + row("95% interval width", "width95")
               + row("Mean minus recorded", "mean_minus_recorded"))
        return out

    def model_summary(self, ref: str) -> str:
        """Summary of a pinned value model: its kind, fitted numbers and the snapshot it was read from."""
        from metrology_atlas.code import source_of
        from metrology_atlas.readers import summarise
        m = summarise(self.ds, ref)
        src = source_of(self.ds, ref) or {}
        pin = (f" Read from the pinned snapshot of {self.a('software', src['software'])}"
               + (f" at commit `{src['commit'][:10]}`" if src.get("commit") else "")
               + (f" ({src['date']})" if src.get("date") else "") + ".") if src else ""
        head = f"Model file: {self.code_link(ref)}.{pin}\n\n"
        if not m:
            return head
        out = head
        if m["modes"]:
            approx = any(md.get("approx") for md in m["modes"])
            out += ("How a true value becomes the recorded one. The rules are tried in order: a record not taken by an "
                    "earlier rule is taken by this one with the probability shown (where its condition holds); the last "
                    "rule takes the rest. " + ("Shares of all records depend on the conditions and the true value, so "
                    "the model must be evaluated for them; the probabilities below are the fitted ones."
                    if approx else "With no conditions, the shares follow directly.") + "\n\n"
                    "| Order | Rule | Rounds to | Probability if reached | " + ("Applies when" if approx else "Share of records")
                    + " |\n|---|---|---|---|---|\n")
            for k, md in enumerate(m["modes"], 1):
                step = (f"{md['step']:g} {m['unit'] or ''} ({md['anchor']})" if md["step"] is not None else md["anchor"])
                last = md is m["modes"][-1]
                q = "the rest" if last else f"{100 * md['p']:.1f} %"
                tail = (md["condition"] or "always") if approx else f"{100 * md['weight']:.1f} %"
                out += f"| {k} | {md['label']} | {step} | {q} | {tail} |\n"
            notes = [f"**{md['label']}:** {md['note']}" for md in m["modes"] if md.get("note")]
            out += "".join(f"\n- {x}" for x in notes) + ("\n" if notes else "")
        facts = [("Recorded resolution", m["resolution"]), ("True-value density", m["latent"]),
                 ("Covariates", ", ".join(m["covariates"]) if m["covariates"] else None),
                 ("Fitted on", f"{m['fit']['n']:,} records" + (f" ({m['fit']['source']})" if m["fit"].get("source") else "")
                  if m["fit"].get("n") else None),
                 ("BIC", f"{m['fit']['bic']:,.0f}" if m["fit"].get("bic") else None), ("Fitted", m["fit"].get("date"))]
        out += "\n" + self.glance(facts)
        if m["notes"]:
            out += "\n" + "\n".join(f"- {n}" for n in m["notes"]) + "\n"
        if m.get("references"):
            out += "\nSources the model cites:\n\n" + "\n".join(f"- {r}" for r in m["references"]) + "\n"
        return out

    def measurement_space(self, i: str, s: dict) -> str:
        """Where the true value can lie, given a recorded one: vertical slices through the measurement space.

        A variable with a fitted model shows up to four worked examples (the distribution of true minus recorded,
        averaged over every record with that recorded value) and a joint map of recorded against true, both read
        from the pinned snapshot's slices.json. Any other variable shows one slice built from its rounding rules
        and accuracy. The time side is given in a line of text below.
        """
        from metrology_atlas.readers import summarise
        v = s.get("value") or {}
        m = summarise(self.ds, v["model"]) if v.get("model") else None
        unit = (m or {}).get("unit") or s.get("unit") or ""
        t = next((x for x in s.get("timing") or [] if x.get("default")), (s.get("timing") or [None])[0])
        time_line = ""
        if t:
            lo, hi = -(t["delay_s"][1] + t["interval_s"][1]), -t["delay_s"][0]
            time_line = (f"\n\n**Time side** ({t['name']}): the true time lies between {lo:g} s and {hi:g} s from the "
                         "stamp: the delay range plus the interval one value describes.")
        sl = self.slices(v)
        if sl and sl.get("examples"):
            return self.slice_examples(s, sl) + time_line
        bands = []
        if m and m["modes"]:
            for md in m["modes"]:
                if md["step"] is not None:
                    st = float(md["step"])
                    lo, hi = {"ceiling": (-st, 0.0), "floor": (0.0, st)}.get(md["anchor"], (-st / 2, st / 2))
                    bands.append((lo, hi, md["weight"]))
        elif v.get("step"):
            st = float(v["step"])
            lo, hi = {"ceiling": (-st, 0.0), "floor": (0.0, st)}.get(v.get("anchor") or "nearest", (-st / 2, st / 2))
            bands.append((lo, hi, 1.0))
        acc = v.get("accuracy_sd") if v.get("accuracy_sd") is not None else (m or {}).get("accuracy_sd")
        if not bands and acc is None:
            return time_line.strip()
        xs = [b[0] for b in bands] + [b[1] for b in bands] + ([-3 * acc, 3 * acc] if acc else [])
        a, b = min(xs + [0.0]), max(xs + [0.0])
        pad = 0.15 * (b - a) or 1.0
        grid = [a - pad + (b - a + 2 * pad) * k / 400 for k in range(401)]
        tot = sum(w for _, _, w in bands) or 1.0
        dens = []
        for x in grid:
            y = sum(w / tot / (hi - lo) for lo, hi, w in bands if lo <= x < hi and hi > lo)
            if acc:
                y = y if bands else math.exp(-x * x / (2 * acc * acc)) / (acc * math.sqrt(2 * math.pi))
            dens.append(y)
        shape = ("uniform" if len(bands) == 1 and not acc else "a mixture of uniforms" if bands and not acc
                 else "normal" if not bands else "uniform, plus accuracy")
        svg = self.slice_svg(grid, dens, f"true minus recorded ({unit})", None, 640, 220)
        note = (f"*A vertical slice through the measurement space: how the true value is spread around any one "
                f"recorded value. Its shape is {shape}"
                + (", one block per rounding rule, weighted by how often it is used" if len(bands) > 1 else "")
                + (f". The instrument accuracy ({acc:g} {unit} per SD) is not yet combined with the rounding here"
                   if acc and bands else "") + ".*")
        return f'<div class="ms-fig">{svg}</div>\n\n{note}{time_line}'

    def slices(self, v: dict) -> dict | None:
        """The model's worked examples, from slices.json next to the spread entry the value points at."""
        from metrology_atlas.readers import spread
        ref = v.get("slices") or (v.get("spread") or "").replace("spread.json", "slices.json")
        return spread(self.ds, ref) if ref and "slices.json" in ref else None

    def slice_svg(self, grid, dens, xlabel, title, W=300, H=190, zoom=False) -> str:
        """One small SVG panel of a distribution of the true value given a record (optionally zoomed to its mass)."""
        if zoom:   # each panel at its own scale: symmetric about zero, wide enough for 99.8% of the mass
            dx = [b - a for a, b in zip(grid, grid[1:])] + [grid[-1] - grid[-2]]
            mass = [y * d for y, d in zip(dens, dx)]
            tot, c, lo, hi = sum(mass) or 1.0, 0.0, grid[0], grid[-1]
            for x, mm in zip(grid, mass):
                c += mm / tot
                if c < 0.001:
                    lo = x
                if c < 0.999:
                    hi = x
            half = max(abs(lo), abs(hi), (grid[-1] - grid[0]) / 200) * 1.25
            keep = [(x, y) for x, y in zip(grid, dens) if -half <= x <= half]
            grid, dens = [-half] + [x for x, _ in keep] + [half], [0.0] + [y for _, y in keep] + [0.0]
        L, R, T, B = 34, 10, 24 if title else 10, 34
        pw, ph = W - L - R, H - T - B
        x0, x1 = grid[0], grid[-1]
        y1 = max(dens) * 1.08 or 1.0
        X = lambda x: L + (x - x0) / (x1 - x0) * pw
        Y = lambda y: T + (y1 - y) / y1 * ph
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(grid, dens))
        o = [f'<svg viewBox="0 0 {W} {H}" class="ms" role="img" aria-label="{title or "slice"}">',
             f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" class="ms-frame"/>',
             f'<polygon points="{X(x0):.1f},{Y(0):.1f} {pts} {X(x1):.1f},{Y(0):.1f}" class="ms-val" fill-opacity=".35"/>']
        if x0 < 0 < x1:
            o.append(f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{T}" y2="{T + ph}" class="ms-zero"/>')
        raw = (x1 - x0) / 4
        mag = 10 ** math.floor(math.log10(raw))
        step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
        k = math.ceil(x0 / step)
        while k * step <= x1 + 1e-12:
            xv = 0.0 if abs(k * step) < step * 1e-6 else k * step
            o.append(f'<text x="{X(xv):.1f}" y="{T + ph + 13}" class="ms-tick" text-anchor="middle">{xv:g}</text>')
            k += 1
        o.append(f'<text x="{L + pw / 2}" y="{H - 4}" class="ms-lab" text-anchor="middle">{xlabel}</text>')
        if title:
            o.append(f'<text x="{L}" y="15" class="ms-lab">{title}</text>')
        o.append(f'<text x="12" y="{T + ph / 2}" class="ms-tick" text-anchor="middle" '
                 f'transform="rotate(-90 12 {T + ph / 2})">density</text>')
        return "".join(o) + "</svg>"

    def slice_examples(self, s: dict, sl: dict) -> str:
        """Worked examples of a value model: one panel per recorded value."""
        unit, by = sl.get("unit") or "", sl.get("by", "recorded value")
        panels, notes = [], []
        for n, e in enumerate(sl["examples"], 1):
            rec = e["recorded"] + ("" if by != "recorded value" else f" {unit}")
            label = f"{n}. recorded {rec}" if by == "recorded value" else f"{n}. recorded at {rec} past the hour"
            panels.append(self.slice_svg(e.get("grid") or sl["grid"], e["pdf"], f"true minus recorded ({unit})", label, zoom=True))
            top = ", ".join(f"{k} {w:.0%}" for k, w in list(e["weights"].items())[:3] if w >= 0.01)
            notes.append(f"**{rec}** ({e['why']}; {e['n']:,} records): mean {e['mean']:+.3g} {unit}, SD "
                         f"{e['sd']:.3g} {unit}, 95% between {e['q'][0]:+.3g} and {e['q'][2]:+.3g}. Rounding: {top}.")
        out = ('<div class="ms-fig ms-grid">' + "".join(panels) + "</div>\n\n"
               f"*Vertical slices through the measurement space: how the true value is spread around a recorded "
               f"one, for {len(panels)} recorded {'values' if by == 'recorded value' else 'minutes of the hour'} chosen "
               f"to show the different cases. Each panel has its own scale. Each is averaged over every record with that "
               f"{'value' if by == 'recorded value' else 'minute'} in the release, from the pinned model; groups of "
               f"fewer than 20 records are not shown.*\n\n" + "\n".join(f"{k}. {x}" for k, x in enumerate(notes, 1)) + "\n")
        if sl.get("joint"):
            src = f"{self.base}figures/{sl['joint']}"
            xl = "the recorded minute of the hour" if by != "recorded value" else "the recorded value"
            out += (f'\n<figure markdown="span" id="fig-joint">\n  [![Joint map of recorded against true value for '
                    f'{s["name"]}]({src})]({src})\n  <figcaption>Joint map: across, {xl}; up, the true value minus '
                    f'the recorded one. Colour is the share of all probability in the release ({sl["records"]:,} '
                    "records), on a log scale. Each column is a slice like those above; tall columns are values "
                    "people round to, narrow ones values written as measured.</figcaption>\n</figure>\n")
        return out

    def link(self, i: str, l: dict) -> str:
        """The page for one clock link: correction rule, drift, period and size, with their evidence."""
        r = self.rel["link"][i]
        corr = l.get("correction") or {}
        pt = lambda p: self.a("parameter", p, parameter_text(self.ds.get("parameter", p))) if p else None
        evidence = sorted({self.ds.get("parameter", p)["study"] for p in r.get("parameters", [])
                           if self.ds.get("parameter", p).get("study")})
        body = (self.section("Correction", self.prose(corr.get("rule")))
                + self.section("Description", self.prose(l.get("description")))
                + self.section("Parameters", self.params_table(r.get("parameters")))
                + self.section("Evidence", self.studies_table(evidence))
                + self.section("References", self.refs(l.get("references"))))
        return self.page(l, self.glance([
            ("Clock", self.a("clock", l["clock"])), ("Measured against", self.a("clock", l["against"])),
            ("Modes", ", ".join(l.get("modes") or []) or "all"), ("Status", l["status"]), ("Drift", pt(l.get("rate"))),
            ("Corrected every", pt(corr.get("period"))), ("Correction size", pt(corr.get("size")))]), body)

    def parameter(self, i: str, p: dict) -> str:
        """The page for one parameter: value, status, the study that produced it and where it is used."""
        used = []
        for lid, l in self.ds.items["link"].items():
            corr = l.get("correction") or {}
            for role, pid in (("drift", l.get("rate")), ("correction period", corr.get("period")),
                              ("correction size", corr.get("size"))):
                if pid == i:
                    used.append(f"- {role} of {self.a('link', lid)}")
        for sid, s in self.ds.items["variable"].items():
            for x in (s.get("delays") or []) + ([s["window"]] if s.get("window") else []):
                if x.get("parameter") == i:
                    used.append(f"- {x['name']} of {self.a('variable', sid)}")
        about = ", ".join(self.a(self.kind_of(x, ("clock", "device", "variable", "link", "observation")), x) for x in p["about"])
        by = ""
        if p.get("by_setup"):
            u = p.get("unit") or ""
            by = (f"Per recording setup ({p.get('setup_key') or 'setup'}; see [Recording setups]({self.base}setups.md)). "
                  "For a recording whose setup is known, use its row: the spread within a setup is far smaller than "
                  f"over all recordings.\n\n| Setup | Value ({u}) | IQR | Cases | Note |\n|---|---|---|---|---|\n" + "".join(
                      f"| {r['setup']} | {r['value']:g} | "
                      + (f"{r['q1']:g} to {r['q3']:g}" if r.get("q1") is not None else "—")
                      + f" | {int(r['n']) if r.get('n') else '—'} | {r.get('note') or ''} |\n" for r in p["by_setup"]))
        body = (self.section("By setup", by) + self.section("Notes", self.prose(p.get("notes")))
                + self.section("Used in", "\n".join(used)))
        return f"# {p['name']}\n\n{p['quantity']}\n\n" + self.glance([
            ("Value", parameter_text(p)), ("Status", f"{p['status']}: {STATUS_NOTE[p['status']]}"),
            ("From", self.a("study", p["study"]) if p.get("study") else None), ("About", about),
            ("Superseded by", self.a("parameter", p["superseded_by"]) if p.get("superseded_by") else None),
            ("Date", str(p["date"]) if p.get("date") else None)]) + body

    def study(self, i: str, s: dict) -> str:
        """The page for one study: status note, data, method, results, discussion, open questions and code."""
        r = self.rel["study"][i]
        note = ""
        if s["status"] in {"withdrawn", "superseded", "draft", "open"}:
            kind = {"withdrawn": "danger", "superseded": "warning", "draft": "note", "open": "info"}[s["status"]]
            by = r.get("superseded_by")
            note = f'!!! {kind} "{s["status"].capitalize()}"\n    ' + (
                f"Superseded by {self.many('study', by)}." if by else
                {"withdrawn": "Kept for the record; its conclusions do not stand.",
                 "superseded": "A later study replaces it.", "draft": "Not yet written up in full.",
                 "open": "Work in progress: results may change."}[s["status"]]) + "\n\n"
        code = self.code_list(s.get("code"))
        body = (self.section("Background", self.prose(s.get("background")))
                + self.section("Data", self.prose(s.get("data")))
                + self.section("Method", self.prose(s.get("method")))
                + self.section("Results", self.prose(s.get("results")) + "\n\n" + self.params_table(r.get("parameters")))
                + self.section("Discussion", self.prose(s.get("discussion")))
                + self.section("Observations it supports", self.observations_table(r.get("observations")))
                + self.section("Limitations", self.prose(s.get("limitations")))
                + self.section("Open questions", self.questions(s.get("open_questions")))
                + self.section("Description", self.prose(s.get("description")))
                + self.section("Model", self.model_summary(s["model"]) if s.get("model") else "")
                + self.section("Worked examples", self.examples_table(r.get("examples")))
                + self.section("Code", code) + self.section("References", self.refs(s.get("references"))))
        return note + self.page(s, self.glance([
            ("Date", str(s["date"])), ("Status", s["status"]), ("Methods", self.many("method", s["methods"])),
            ("Techniques", self.many("technique", s.get("techniques"))), ("Clocks", self.many("clock", s.get("clocks"))),
            ("Devices", self.many("device", s.get("devices"))), ("Variables", self.many("variable", list(dict.fromkeys((s.get("variables") or []) + r.get("variables", []))))),
            ("Supersedes", self.many("study", s.get("supersedes")))]), body)

    def method(self, i: str, m: dict) -> str:
        """The page for one method: its techniques, studies and the observations they produced."""
        r = self.rel["method"][i]
        techs = "\n".join(f"- **{self.a('technique', t)}**: {self.summ(self.ds.get('technique', t)['summary'])}"
                          for t in m.get("techniques") or [])
        obs = sorted({o for st in r.get("studies", []) for o in self.rel["study"][st].get("observations", [])})
        body = (self.section("Studies", self.studies_table(r.get("studies")))
                + self.section("Observations from these studies", self.observations_table(obs))
                + self.section("The approach", self.prose(m.get("description")))
                + self.section("Techniques", techs)
                + self.section("References", self.refs(m.get("references"))))
        return self.page(m, self.glance([("Techniques", self.many("technique", m.get("techniques")))]), body)

    def technique(self, i: str, t: dict) -> str:
        """The page for one technique."""
        r = self.rel["technique"][i]
        body = (self.section("Description", self.prose(t.get("description")))
                + self.section("Studies", self.studies_table(r.get("studies")))
                + self.section("References", self.refs(t.get("references"))))
        return self.page(t, self.glance([("Methods", self.many("method", r.get("methods")))]), body)

    ERROR_KIND = {"random": "Random: cancels over a cohort", "systematic": "Systematic: does not cancel",
                  "both": "Both: part cancels, part does not"}

    def levels_box(self, lv) -> str:
        """The example's effect on a cohort and on one patient, as a box after the results."""
        if not lv:
            return ""
        body = (f"**{self.ERROR_KIND[lv['error']]}.**\n\n| | |\n|---|---|\n"
                f"| **The cohort** | {self.prose(lv['population']).strip().replace(chr(10), ' ')} |\n"
                f"| **Each patient** | {self.prose(lv['individual']).strip().replace(chr(10), ' ')} |\n")
        return '!!! abstract "Population and individual"\n\n' + "\n".join("    " + x for x in body.splitlines()) + "\n\n"

    def levels_table(self, ids) -> str:
        """Table of how each worked example's error acts on a cohort and on each patient."""
        rows = [(x, self.ds.get("example", x)) for x in ids if self.ds.get("example", x).get("levels")]
        if not rows:
            return ""
        out = ("## Population and individual\n\nThe same measurement error can vanish from a cohort's estimate and still "
               "decide one patient's value or label. Errors that are independent and symmetric cancel over many "
               "patients; systematic ones do not.\n\n| Example | Error | The cohort | Each patient |\n|---|---|---|---|\n")
        for x, e in sorted(rows, key=lambda r: r[1]["name"]):
            lv = e["levels"]
            out += (f"| [{e['name']}]({x}.md) | {lv['error']} | {self.summ(lv['population'])} | "
                    f"{self.summ(lv['individual'])} |\n")
        return out + "\n"

    def example(self, i: str, e: dict) -> str:
        """The page for one worked example."""
        note = {"planned": '!!! note "Planned"\n    Not yet worked through; the page says what it will show.\n\n',
                "draft": '!!! info "Draft"\n    Worked through on a few cases; numbers may change.\n\n'}.get(e["status"], "")
        inputs = "".join(f"| {self.a('variable', v)} | {self.ds.get('variable', v).get('unit') or ''} | "
                         f"{self.summ(self.ds.get('variable', v)['summary'])} |\n" for v in e.get("variables") or [])
        if inputs:
            inputs = ("Each input links to its measurement page: how it is timed, how its value was recorded, and "
                      "how uncertain both are.\n\n| Input | Unit | What it is |\n|---|---|---|\n" + inputs)
        body = (self.section("The question", self.prose(e.get("question")))
                + self.section("Inputs", inputs)
                + self.section("Why the atlas changes the answer", self.prose(e.get("why")))
                + self.section("Description", self.prose(e.get("description")))
                + self.section("Data", self.prose(e.get("data")))
                + self.section("Steps", self.prose(e.get("steps")))
                + self.section("Results", self.prose(e.get("results")))
                + self.levels_box(e.get("levels"))
                + self.section("Takeaways", self.prose(e.get("takeaways")))
                + self.section("Limitations", self.prose(e.get("limitations")))
                + self.section("Open questions and future work", self.questions(e.get("open_questions")))
                + self.section("Studies it relies on", self.studies_table(e.get("studies")))
                + self.section("Observations it relies on", self.observations_table(e.get("observations")))
                + self.section("Reproduce it", self.code_list(e.get("code")) + "\n\n" + self.prose(e.get("reproduce")))
                + self.section("References", self.refs(e.get("references"))))
        return note + self.page(e, self.glance([
            ("Side", e["side"]), ("Status", e["status"]), ("Variables", self.many("variable", e.get("variables"))),
            ("Studies", self.many("study", e.get("studies"))),
            ("Observations", self.many("observation", e.get("observations")))]), body)

    def examples_table(self, ids) -> str:
        """Table of worked examples."""
        ids = sorted(ids or [], key=lambda x: self.ds.get("example", x)["name"])
        if not ids:
            return ""
        return "| Example | Side | Status | Summary |\n|---|---|---|---|\n" + "".join(
            f"| {self.a('example', x)} | {self.ds.get('example', x)['side']} | {self.ds.get('example', x)['status']} | "
            f"{self.summ(self.ds.get('example', x)['summary'])} |\n" for x in ids)

    def software(self, i: str, w: dict) -> str:
        """The page for one software item: repository, visibility, role and the code the atlas links to."""
        r = self.rel["software"][i]
        note = ""
        if w.get("visibility") == "private":
            note = ('!!! info "Private repository"\n    Links into this repository work only for people who have been '
                    "given access to it.\n\n")
        elif w.get("visibility") == "not yet released":
            note = ('!!! info "Not yet released"\n    This repository will be made public later; until then its '
                    "paths are shown, not linked.\n\n")
        elif not w.get("repo"):
            note = ('!!! info "Not published"\n    This code is kept on the analysis machine; paths are shown, '
                    "not linked.\n\n")
        parts = ""
        groups: dict[str, list[dict]] = {}
        for p in w.get("parts") or []:
            groups.setdefault(p.get("group") or "", []).append(p)
        for g, ps in groups.items():
            if g:
                parts += f"\n### {g}\n\n"
            parts += "| | |\n|---|---|\n" + "".join(
                f"| {self.code_link(i + '/' + p['path'], p.get('name') or self._base(p['path']))} | "
                f"{self.prose(p['summary']).replace(chr(10), ' ')} |\n" for p in ps)
        uses = ""
        for sid in sorted(r.get("studies") or [], key=lambda x: self.ds.get("study", x)["name"]):
            st = self.ds.get("study", sid)
            files = [split(c)[1] for c in st.get("code") or [] if split(c)[0] == i and split(c)[1]]
            uses += (f"| {self.a('study', sid)} | " + (", ".join(self.code_link(f"{i}/{f}") for f in files) or "—")
                     + f" | {self.summ(st['summary'])} |\n")
        if uses:
            uses = "| Study | Code | Summary |\n|---|---|---|\n" + uses
        mentions = [m.split(":", 1) for m in r.get("mentioned_in") or []]
        mentions = "\n".join(f"- {KINDS[k].title.removesuffix('s')}: "
                             f"{self.a(k, x)}" for k, x in sorted(mentions, key=lambda m: (m[0], m[1])))
        repo = f"[{w['repo'].removeprefix('https://')}]({w['repo']})" if w.get("repo") else (
            "not yet released" if w.get("visibility") == "not yet released" else "not published")
        body = (self.section("What it is", self.prose(w.get("description")))
                + self.section("Its part in the atlas", self.prose(w.get("role")))
                + self.section("Install", self.prose(w.get("install")))
                + self.section("What is in it", parts)
                + self.section("Studies that use it", uses)
                + self.section("Observations it handles", self.observations_table(r.get("observations")))
                + self.section("Worked examples", self.examples_table(r.get("examples")))
                + self.section("Mentioned in", mentions)
                + self.section("References", self.refs(w.get("references"))))
        return note + self.page(w, self.glance([
            ("Repository", repo), ("Branch", w.get("branch") if w.get("repo") else None),
            ("Visibility", w.get("visibility")), ("Licence", w.get("licence")), ("Language", w.get("language")),
            ("Home page", f"[{w['url']}]({w['url']})" if w.get("url") else None),
            ("Documentation", f"[{w['docs']}]({w['docs']})" if w.get("docs") else None),
            ("Related", self.many("software", w.get("related")))]), body)

    def value_page(self) -> str:
        """The value side at a glance: every variable with a value description, by how its value is modelled."""
        rows: dict[str, list[str]] = {}
        for vid, v in sorted(self.ds.items["variable"].items(), key=lambda x: x[1]["name"]):
            val = v.get("value")
            if not val:
                continue
            kind = (val.get("kind") or "not described").split(":")[0]
            st = ", ".join(self.a("study", x) for x in val.get("studies") or []) or "—"
            rows.setdefault(kind, []).append(f"| {self.a('variable', vid)} | {v.get('unit') or ''} | "
                                             f"{val.get('resolution') or '—'} | {st} |")
        out = ("# Value\n\nThe value side of every variable: how far the recorded number can be from the true one. "
               "Two things set that. **Resolution** is how the value was written down: the step it was recorded at, and "
               "the coarser values people round to (heaping). **Accuracy** is how far the instrument or method is from "
               "the truth before any rounding.\n\nMost of what is here is resolution, from fitted rounding models "
               f"({self.a('method', 'value-resolution', 'the method')}). Accuracy is described where it is known; for most "
               "instruments it is still to be added.\n\n") if "value-resolution" in self.ds.items["method"] else "# Value\n\n"
        order = ["model", "timestamp_model", "derived", "source_dependent", "decimal_dependent", "uniform", "neighbours",
                 "triangular_count", "age", "colloid_rules", "exact", "not_applicable"]
        for kind in sorted(rows, key=lambda k: order.index(k) if k in order else 99):
            label = {"model": "Fitted rounding models (heaped values)", "timestamp_model": "Charted times (fitted)",
                     "derived": "Derived from other variables", "source_dependent": "Resolution set by the source",
                     "decimal_dependent": "Resolution set by the decimal", "uniform": "One resolution",
                     "neighbours": "Computed values", "triangular_count": "Counts with an unknown rule",
                     "age": "Age", "colloid_rules": "Rule sets", "exact": "Exact",
                     "not_applicable": "Categories (no numeric value)"}.get(kind, kind)
            out += f"## {label}\n\n| Variable | Unit | Resolution | Model study |\n|---|---|---|---|\n" + "\n".join(rows[kind]) + "\n\n"
        return out.replace("\n## ", "\nWhat an anchor is: [Aim and terms](terms.md#anchors). Every variable's anchor, and which are unsettled: [Anchor decisions](anchors.md).\n\n## ", 1)

    # -- indexes -----------------------------------------------------------------------------------------------
    def kind_index(self, kind: str) -> str:
        """The index page for one kind of item (studies grouped by method)."""
        k = KINDS[kind]
        items = self.ds.items[kind]
        out = f"# {k.title}\n\n{k.help}\n\n"
        if kind == "study":
            for mid, m in sorted(self.ds.items["method"].items(), key=lambda x: (x[1].get("order", 99), x[1]["name"])):
                out += f"## {m['name']}\n\n{self.summ(m['summary'])} {self.a('method', mid, 'About this method')}\n\n"
                out += self.studies_table(self.rel["method"][mid].get("studies")).replace("](../studies/", "](") or "No studies yet.\n"
                out += "\n"
            return out
        if kind == "variable":
            placed = placed_variables(self.ds)
            out += "| Section | Groups |\n|---|---|\n" + "".join(
                f"| [{sec}](#{_anchor(sec)}) | " + ", ".join(f"[{g}](#{_anchor(g)}) ({len(v)})" for g, v in groups.items())
                + " |\n" for sec, groups in placed.items()) + "\n"
            for sec, groups in placed.items():
                out += f"## {sec}\n\n"
                for g, vs in groups.items():
                    out += f"### {g}\n\n| Variable | Time | Value | Summary |\n|---|---|---|---|\n"
                    for id_, item in vs:
                        t = "chain" if item.get("chain") else ("timing" if item.get("timing") else
                                                              ("stamped" if item.get("stamp_clock") else "—"))
                        v = item.get("value") or {}
                        v = "model" if v.get("model") else ("resolution" if v.get("resolution") or v.get("step") else "—")
                        out += f"| [{item['name']}]({id_}.md) | {t} | {v} | {self.summ(item['summary'])} |\n"
                    out += "\n"
            return out
        if kind == "observation":
            return out + self.observations_table(list(items)).replace("](../observations/", "](")
        if kind == "example":
            intro = self.prose(self.ds.meta.get("examples_intro") or "")
            out += (intro + "\n\n" if intro else "")
            for side, title in (("time", "Time side: when clocks are misaligned"),
                                ("value", "Value side: when inputs are rounded"), ("both", "Both sides")):
                ids = [x for x, e in items.items() if e["side"] == side]
                if ids:
                    out += f"## {title}\n\n" + self.examples_table(ids).replace("](../examples/", "](") + "\n"
            return out + self.levels_table(list(items))
        if kind == "parameter":
            return out + self.params_table(sorted(items, key=lambda p: items[p]["name"])).replace("](../parameters/", "](")
        out += "| | |\n|---|---|\n"
        for id_, item in sorted(items.items(), key=lambda x: x[1]["name"]):
            out += f"| [{item['name']}]({id_}.md) | {self.summ(item['summary'])} |\n"
        return out

    def home(self, json_name: str) -> str:
        """The home page: summary, notice, working reference, timing graph, synchronisation figures and citation."""
        m = self.ds.meta
        figs = {f["id"]: f for f in m.get("figures") or []}
        out = f"---\nhide:\n  - navigation\n---\n\n# {m['name']}\n\n"
        if m.get("notice"):
            out += '!!! warning "Work in progress"\n\n' + "\n".join(
                ("    " + l) if l else "" for l in self.prose(m["notice"]).strip().splitlines()) + "\n\n"
        out += f"{self.summ(m['summary'])}\n\n{self.prose(m.get('description'))}\n\n"
        if m.get("overview") or "system-overview" in figs:
            out += "## System overview\n\n" + self.prose(m.get("overview")) + "\n\n"
            if "system-overview" in figs and "system-overview" not in self.placed:
                out += self.figure(figs["system-overview"]) + "\n\n"
                self.placed.add("system-overview")
                if figs["system-overview"].get("file") == "timing-graph.svg":
                    from metrology_atlas.overview import overview_table
                    out += ("??? info \"The links in the timing graph\"\n\n"
                            + "\n".join("    " + ln for ln in overview_table(
                                self.ds, href=lambda kind, id_: f"{KINDS[kind].folder}/{id_}.md").splitlines())
                            + "\n\n")
        out += self.axes_table()
        out += self.time_chart()
        if m.get("reference"):
            out += "## The working reference\n\n" + self.prose(m["reference"]) + "\n\n"
        if "synchronisation-demo" in figs and "synchronisation-demo" not in self.placed:
            out += "## What synchronising the clocks does\n\n" + self.figure(figs["synchronisation-demo"]) + "\n\n"
            self.placed.add("synchronisation-demo")
        if "synchronisation-census" in figs and "synchronisation-census" not in self.placed:
            out += ("Across the whole release, for every link a shared signal can check:\n\n"
                    + self.figure(figs["synchronisation-census"]) + "\n\n")
            self.placed.add("synchronisation-census")
        if m.get("references"):
            out += ("## Citing\n\nIf you use the atlas, please also cite the data:\n\n"
                    + "\n".join(f"- {self.ds.get('reference', r)['citation']}"
                                 + (f" doi:[{self.ds.get('reference', r)['doi']}](https://doi.org/{self.ds.get('reference', r)['doi']})"
                                    if self.ds.get('reference', r).get('doi') else "") for r in m["references"]) + "\n\n")
            if any(pg["id"] == "data-and-licence" for pg in m.get("pages") or []):
                out += ("The data's licence, what the atlas contains and how the atlas may be reused are on "
                        "[Data and licence](data-and-licence.md).\n\n")
        heads = sorted(p for p, v in self.ds.items["parameter"].items() if v.get("headline"))
        if heads:
            out += "## Key numbers\n\n" + self.params_table(heads) + "\n"
        out += ("## Plan a multi-signal analysis\n\nThe [synchronisation planner](planner.md) takes the variables an "
                "analysis uses and reports how well their times line up, how we know, and what window sizes keep "
                "cross-modal features meaningful.\n\n")
        out += "## What is in the atlas\n\n| | | |\n|---|---|---|\n"
        for k in KINDS.values():
            out += f"| [{k.title}]({k.folder}/index.md) | {len(self.ds.items[k.name])} | {k.help} |\n"
        out += (f"\nThe whole atlas is also one machine-readable file: [{json_name}](data/{json_name}). "
                "Every number carries its status (measured, derived, estimated or assumed), its spread and the study "
                "it came from.\n")
        rest = [f for f in figs.values() if f["id"] not in self.placed]
        if rest:
            out += "\n## Figures\n\n" + "\n\n".join(self.figure(f) for f in rest) + "\n"
        return out

    def time_chart(self) -> str:
        """The accuracy-against-resolution chart of every time stamp, with its data embedded."""
        if not any(s.get("timing") for s in self.ds.items["variable"].values()):
            return ""
        data = chart_forms(self.ds)
        data.update(AXES, aria=f"Accuracy against resolution of every time stamp in {self.ds.meta['name']}")
        return ("## Every time stamp: accuracy and resolution\n\n"
                "Each kind of time stamp in the dataset, placed by how far it lies after the end of the interval its "
                "value describes, against the working reference (across), and by how wide that interval is (up). "
                "Drawn from the atlas data each time the site is built, so it follows every update; the same data "
                "drives the [synchronisation planner](planner.md).\n\n"
                '<div id="atlas-chart"></div>\n<script src="js/atlas-chart.js"></script>\n<script>\n'
                "const ATLAS_CHART = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";\n"
                "AtlasChart(document.getElementById('atlas-chart'), ATLAS_CHART).draw(ATLAS_CHART.items.map((it) => "
                "({...it, href: it.hrefs.length === 1 ? it.hrefs[0] : null})), ATLAS_CHART.arrows);\n</script>\n\n")

    def time_page(self) -> str:
        """The time side at a glance: clocks and how each reaches UTC, then the time stamps and the planner."""
        m = self.ds.meta
        out = ("# Time\n\nThe time side of every variable: how far a recorded time can be from when the thing it "
               "describes happened. **Accuracy**: the clock that made the stamp drifts and is corrected in jumps, and "
               "the value often describes a window that ended before its stamp. **Resolution**: the grid the stamp "
               "sits on, and the width of the interval one value stands for.\n\n")
        if m.get("reference"):
            out += "## The working reference\n\n" + self.prose(m["reference"]) + "\n\n"
        ref = m.get("reference_clock")
        has_utc = "utc" in self.ds.items["clock"]
        # links every clock's best route to UTC passes through: they set every absolute time alike
        weak = sorted(lk for lk in self.shared_utc_links() if self.ds.get("link", lk)["status"] not in ("measured", "derived"))
        if weak:
            out += ("Every clock's route to UTC passes through " + " and ".join(self.a("link", lk) for lk in weak) + ", "
                    + " and ".join(f"**{self.ds.get('link', lk)['status']}**" for lk in weak) + ". That shared link sets "
                    "the absolute accuracy of every time in the dataset alike, so it cancels whenever times are compared "
                    "with each other, which is what synchronising variables needs. The table therefore follows each clock "
                    "to the working reference instead; each clock's page also draws its full route to UTC.\n\n")
        rows = ""
        target = ref if ref in self.ds.items["clock"] else ("utc" if has_utc else None)
        for cid, c in sorted(self.ds.items["clock"].items(), key=lambda x: x[1]["name"]):
            if cid == target:
                route = "the working reference" if target == ref else "—"
            elif cid == "utc":
                route = "— (outside the release)"
            else:
                routes = self.routes(cid, root=target) if target else []
                if routes:
                    st = [self.ds.get("link", lid)["status"] for _, lid in routes[0][1:]]
                    route = (f"{len(routes[0]) - 1} link{'s' if len(routes[0]) > 2 else ''}, weakest "
                             f"{max(st, key=lambda x: self.STATUS_COST[x])}")
                else:
                    route = "no route yet"
            n = len(self.rel["clock"][cid].get("stamps", [])) + len(self.rel["clock"][cid].get("spaces", []))
            rows += f"| {self.a('clock', cid)} | {c['type']} | {route} | {n} |\n"
        col = "Route to the working reference" if ref else "Route to UTC"
        out += ("## Clocks\n\nEvery clock in the dataset, how it is linked to the "
                + ("working reference" if ref else "UTC") + " (a [traceability chain](terms.md): only as strong as its "
                "weakest link), and how many variables it stamps or spaces. Each clock's page lists its "
                "[links](links/index.md) to other clocks.\n\n"
                f"| Clock | Type | {col} | Variables |\n|---|---|---|---|\n" + rows + "\n")
        out += self.time_chart()
        out += ("## Plan a multi-variable analysis\n\nThe [synchronisation planner](planner.md) takes the variables an "
                "analysis combines and reports how well their times line up, how we know, and what window sizes keep "
                "cross-modal features meaningful.\n\n"
                "The [devices](devices/index.md) that keep the clocks and produce the variables have pages of their own.\n")
        return out

    def evidence_page(self) -> str:
        """Where the numbers come from: studies by method, observations, parameters and techniques."""
        ds = self.ds
        out = ("# Evidence\n\nEvery number in the atlas comes from somewhere. **Studies** are short reports of one piece of "
               "work each; they produce **parameters** (the numbers, each with its status and spread) and support "
               "**observations** (general facts about the data). Studies are grouped by **method**, the way they get "
               "at the answer, and share **techniques**.\n\n"
               "| | | |\n|---|---|---|\n")
        for k in ("study", "observation", "parameter", "method", "technique"):
            out += f"| [{KINDS[k].title}]({KINDS[k].folder}/index.md) | {len(ds.items[k])} | {KINDS[k].help} |\n"
        out += "\n## Methods\n\n| Method | Studies | What it does |\n|---|---|---|\n"
        for mid, mth in sorted(ds.items["method"].items(), key=lambda x: (x[1].get("order", 99), x[1]["name"])):
            out += f"| {self.a('method', mid)} | {len(self.rel['method'][mid].get('studies', []))} | {self.summ(mth['summary'])} |\n"
        counts = {}
        for o in ds.items["observation"].values():
            counts[o["status"]] = counts.get(o["status"], 0) + 1
        out += ("\n## How sure\n\nObservations: " + ", ".join(f"{counts[s]} {s}" for s in OBS_ORDER if s in counts)
                + ". Parameters: " + ", ".join(f"{n} {st}" for st, n in sorted(
                    {p["status"]: sum(1 for q in ds.items["parameter"].values() if q["status"] == p["status"])
                     for p in ds.items["parameter"].values()}.items(), key=lambda x: -x[1])) + ".\n")
        return out

    def questions(self, qs) -> str:
        """A study's open questions, each with its kind."""
        out = []
        for q in qs or []:
            label = QUESTION_LABEL[q["kind"]]
            out.append(f"- **{q['title']}** *({label})*. {self.prose(q['summary']).strip()}")
        return "\n".join(out)

    def question_list(self, kinds=None, heading="##") -> str:
        """Every open question of the given kinds, grouped by kind: a title linked to its study and the summary."""
        out = ""
        for kind in kinds or QUESTION_KINDS:
            rows = sorted(((q, sid, src) for src in ("study", "example") for sid, st in self.ds.items.get(src, {}).items()
                           if st.get("status") not in ("superseded", "withdrawn")
                           for q in st.get("open_questions") or [] if q["kind"] == kind),
                          key=lambda x: x[0]["title"].lower())
            if not rows:
                continue
            out += f"{heading} {QUESTION_KIND_TITLES[kind]}\n\n"
            for q, sid, src in rows:
                anchor = "open-questions" if src == "study" else "open-questions-and-future-work"
                out += (f"- **[{q['title']}]({self.href(src, sid)}#{anchor})** · "
                        f"*{self.name(src, sid)}*  \n  {self.prose(q['summary']).strip()}\n")
            out += "\n"
        return out

    def open_questions_page(self) -> str:
        """The open questions page, gathered from every study."""
        out = ("# Open questions\n\nWhat the studies left open, gathered from every study and grouped by kind: results "
               "nobody can yet explain, explanations the evidence only weakly supports, assumptions the data cannot "
               "test, and places where two studies disagree. The last group lists checks still to run and decisions "
               "still to make. Settling any of them is a good way to contribute.\n\n")
        body = self.question_list()
        return out + (body or "None recorded yet.\n")

    def records_page(self) -> str:
        """The page listing every record (for VitalDB, case) named in the atlas, with the pages that name it."""
        rec = self.ds.meta.get("records") or {}
        name = rec.get("name", "record")
        rows = self.rel.get("record", {})
        out = f"# {name.capitalize()}s discussed\n\n" + (self.prose(rec.get("policy")) + "\n\n" if rec.get("policy") else "")
        if not rows:
            return out + f"No {name}s are named yet.\n"
        out += f"| {name.capitalize()} | Discussed in |\n|---|---|\n"
        for rid in sorted(rows, key=int):
            where = ", ".join(self.a(*m.split(":", 1)) for m in rows[rid].get("mentioned_in", []))
            url = rec.get("url")
            lab = (rec.get("label") or name + " {id}").format(id=rid)
            lab = f"[{lab}]({url.format(id=rid)})" if url else lab
            out += f'| <a id="{name}-{rid}"></a>{lab} | {where} |\n'
        return out

    def figures_page(self) -> str:
        """Every figure in the atlas, grouped by theme, each linking to the page it belongs to."""
        order = self.ds.meta.get("figure_themes") or []
        groups: dict[str, list] = {}
        for kind in KINDS:
            for id_, item in sorted(self.ds.items[kind].items(), key=lambda x: x[1]["name"]):
                for f in item.get("figures") or []:
                    groups.setdefault(f.get("theme") or "Other", []).append((kind, id_, f))
        out = ("# Figures\n\nEvery figure in the atlas, grouped by what it shows. Each links to the page it belongs "
               "to.\n\n")
        for g in sorted(groups, key=lambda x: (order.index(x) if x in order else 99, x)):
            out += f"## {g[0].upper() + g[1:]}\n\n<div class=\"fig-grid\">\n"
            for kind, id_, f in groups[g]:
                src = f"figures/{f['file']}"
                href = self.href(kind, id_).replace(".md", ".html")
                out += (f'<a class="fig-card" href="{href}"><img src="{src}" alt="{f["alt"]}" loading="lazy">'
                        f'<span>{self.name(kind, id_)}</span></a>\n')
            out += "</div>\n\n"
        return out

    def axes_table(self) -> str:
        """The two axes (time, value) by the two kinds of error (accuracy, resolution), with what the atlas holds."""
        V = self.ds.items["variable"].values()
        timed = sum(1 for v in V if v.get("timing"))
        chains = sum(1 for v in V if v.get("chain"))
        models = sum(1 for v in V if (v.get("value") or {}).get("model"))
        valued = sum(1 for v in V if (v.get("value") or {}).get("resolution") or (v.get("value") or {}).get("step"))
        acc = sum(1 for v in V if (v.get("value") or {}).get("accuracy") or (v.get("value") or {}).get("accuracy_sd") is not None)
        clocks, links = len(self.ds.items["clock"]), len(self.ds.items["link"])
        return ("## Measurement space: two axes, two kinds of error\n\n"
                "Every variable is described on two axes, **time** and **value**, and on each by its **accuracy** (how far "
                "the record is from the truth: bias, drift, delay, instrument error) and its **resolution** (how finely it "
                "was recorded: sampling, rounding, heaping). Each variable page draws the four together.\n\n"
                "| | Accuracy | Resolution |\n|---|---|---|\n"
                f"| **Time** | {clocks} [clocks](clocks/index.md) and {links} [links](links/index.md) between them; "
                f"{chains} variables with a written chain from UTC, {timed} with timing against the working reference | "
                "the interval each value describes, the stamp grids (chart below) |\n"
                f"| **Value** | {(str(acc) + ' variables so far') if acc else 'Not yet described for any variable: it needs the instruments’ calibration records ([why](studies/instrument-calibration.md))'} | {valued} variables, {models} with fitted rounding models "
                "([Value](value.md)) |\n\n")

    def references_page(self) -> str:
        """The references page, grouped, each entry with the pages that cite it."""
        out = ("# References\n\nEverything the atlas cites: standards, the data and how it was recorded, the literature "
               "behind each model, and the software the work was done with. Each entry lists the pages that cite it.\n\n")
        order = self.ds.meta.get("reference_groups") or []
        groups: dict[str, list] = {}
        for rid, ref in sorted(self.ds.items["reference"].items(), key=lambda x: x[1]["citation"].lower()):
            groups.setdefault(ref.get("group") or "Other", []).append((rid, ref))
        for g in sorted(groups, key=lambda x: (order.index(x) if x in order else 99, x)):
            out += f"## {g}\n\n"
            for rid, ref in groups[g]:
                link = f" [{ref['url'].removeprefix('https://')}]({ref['url']})" if ref.get("url") else ""
                doi = f" doi:[{ref['doi']}](https://doi.org/{ref['doi']})" if ref.get("doi") else ""
                cited = self.rel["reference"][rid].get("cited_by", [])
                cites = ", ".join("[home page](index.md)" if c == "dataset:" else
                                  self.a(*c.split(":", 1)).replace("](../", "](") for c in cited)
                note = f"  \n*{ref['note']}*" if ref.get("note") else ""
                out += (f'<a id="{rid}"></a>\n{ref["citation"]}{doi}{link}{note}'
                        + (f"  \nCited by: {cites}" if cites else "") + "\n\n")
        return out


def _inline_html(md: str) -> str:
    """Inline Markdown to HTML, for text inside raw HTML (figure captions): links, bold, italics, code."""
    md = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{re.sub(r"[.]md(?=$|#|[?])", ".html", m.group(2))}">{m.group(1)}</a>', md)
    md = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", md)
    md = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", md)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", md)


def _rng(r) -> str:
    def one(x: float) -> str:
        if x < 1:
            return f"{x * 1000:.3g} ms"
        if x < 120:
            return f"{x:.3g} s"
        if x < 7200:
            return f"{x / 60:.3g} min"
        return f"{x / 3600:.3g} h"
    return one(r[0]) if r[0] == r[1] else f"{one(r[0])} – {one(r[1])}"


def _vim(n: str, term: str) -> str:
    return f"[{term}](https://jcgm.bipm.org/vim/en/{n}.html) (VIM {n})"


TERMS_PAGE = f"""# Aim and terms

This atlas is written in the language of metrology: the International Vocabulary of Metrology
([VIM](https://jcgm.bipm.org/vim/en), JCGM 200) and the Guide to the Expression of Uncertainty in Measurement
([GUM](https://www.bipm.org/en/publications/guides/gum.html), JCGM 100 and its supplements). This page states its aim
in those terms and says how each part of the atlas maps onto them.

## The aim

For every variable in the dataset, the atlas states

1. the **{_vim('2.3', 'measurand')}**: the quantity a record is meant to represent. A record has two: the time of what
   it describes and the value of it. For a numeric that summarises a window of signal, the measurand is the value
   over that window, so its time is an interval, not an instant;
2. the **{_vim('2.48', 'measurement model')}** that links the measurand to the recorded pair (recorded time, recorded
   value): clocks, delays and windows on the time side; rounding, heaping and instrument error on the value side;
3. what is known about the measurand given a record, as a **probability distribution**: in the GUM's terms, the
   state of knowledge about the output quantities. Because there are two output quantities, time and value, and
   they are not always independent, this is the multivariate case of GUM Supplement 2 (JCGM 102:2011);
4. the evidence for every part of the model: the studies, with how each number was evaluated.

With the distribution known, the {_vim('2.26', 'measurement uncertainty')} of anything computed from the data can be
found by **propagating distributions**, as in GUM Supplement 1 (JCGM 101:2008, by Monte Carlo): draw true times and
values from each record's distribution, compute, and read the spread of the result.

This is a metrology of **recorded data**. Classical metrology designs and calibrates a measurement before it is made;
here the measurements were made long ago, so each part of the model is reconstructed from the records themselves.

## How the atlas maps onto the vocabulary

| In the atlas | Metrology | Note |
|---|---|---|
| A variable's "What it measures" | {_vim('2.3', 'measurand')} | Includes, for windowed values, the window: a vague window is {_vim('2.27', 'definitional uncertainty')}. |
| Time accuracy: clock offset, drift, delay | {_vim('2.17', 'systematic measurement error')}, {_vim('2.18', 'measurement bias')}, {_vim('4.21', 'instrumental drift')} | Corrections remove the known part; what is left is uncertainty. |
| Time and value resolution: sampling grids, stamp grids, rounding, heaping | {_vim('4.14', 'resolution')} | Heaping is a mixture of resolutions, each with its share of the records. |
| Value accuracy: instrument error | {_vim('2.13', 'measurement accuracy')}, {_vim('2.14', 'measurement trueness')}, {_vim('2.15', 'measurement precision')} | Mostly still to be described. |
| A clock's "Route to UTC" | {_vim('2.42', 'metrological traceability chain')} | Each link adds uncertainty. Where a link is assumed, the chain is broken and the time is not {_vim('2.41', 'metrologically traceable')}. |
| Status **measured** | {_vim('2.28', 'Type A evaluation')} | Evaluated from the data by a study. |
| Status **estimated** or **assumed** | {_vim('2.29', 'Type B evaluation')} | From documentation, the literature or judgement. |
| Status **derived** | propagation | Computed from other evaluated quantities. |
| The measurement-space figure | the joint distribution of the output quantities | A schematic: each part drawn as uniform over its range. |
| The synchronisation planner | a screening uncertainty budget | Combines standard uncertainties of the time side for several variables (uniform parts, independent). |

## Words used here

- **Accuracy** and **resolution** are used as the two kinds of error on each axis: how far the record is from the
  truth (bias, drift, delay, instrument error), and how finely it was recorded (sampling, rounding, heaping).
  The VIM uses *accuracy* as a qualitative term; where a number is given, it is a bias or a standard uncertainty
  and the page says which.
- **True value**: the value of the measurand. The GUM treats it as unknowable and describes knowledge of it by a
  distribution; so does the atlas.
- **Working reference**: the clock that times are compared against in the planner. It is a practical reference,
  not a {_vim('5.18', 'reference quantity value')} in the strict sense.
"""

TYPE_PLACE = {"waveform": ("Monitoring", "Waveforms"), "numeric": ("Monitoring", "Numerics"),
              "event": ("Monitoring", "Events"), "text": ("Monitoring", "Events"),
              "time": ("Clinical record", "Times and durations"), "clinical": ("Clinical record", "Other fields"),
              "lab": ("Laboratory", "Other results")}
SECTION_ORDER = ["Monitoring", "Clinical record", "Laboratory"]


def _anchor(title: str) -> str:
    """The id Zensical gives a heading."""
    return re.sub(r"[^\w\- ]", "", title.lower()).strip().replace(" ", "-")


def variable_place(item: dict) -> tuple[str, str]:
    """(section, group) a variable is listed under: from its ``group`` ('Group' or 'Section/Group') and type."""
    section, group = TYPE_PLACE.get(item.get("type"), ("Other", "Other"))
    g = item.get("group")
    if g:
        section, group = g.split("/", 1) if "/" in g else (section, g)
    return section, group


def placed_variables(ds) -> dict[str, dict[str, list[tuple[str, dict]]]]:
    """section -> group -> [(id, item)], each level in reading order."""
    order = ds.meta.get("variable_groups") or []
    out: dict[str, dict[str, list]] = {}
    for id_, item in sorted(ds.items["variable"].items(), key=lambda x: x[1]["name"].lower()):
        sec, grp = variable_place(item)
        out.setdefault(sec, {}).setdefault(grp, []).append((id_, item))
    key_s = lambda x: (SECTION_ORDER.index(x) if x in SECTION_ORDER else 99, x)
    key_g = lambda x: (order.index(x) if x in order else 99, x)
    return {sec: {g: out[sec][g] for g in sorted(out[sec], key=key_g)} for sec in sorted(out, key=key_s)}


def write_site(ds: Dataset, out: str | Path) -> Path:
    """Write ``docs/`` and ``zensical.toml`` for the dataset into ``out``. Returns ``out``."""
    out = Path(out)
    docs = out / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    site = Site(ds)
    json_name = f"{ds.meta['id']}.metrology.json"
    (docs / "data").mkdir(parents=True)
    (docs / "data" / json_name).write_text(json.dumps(to_json(ds), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if (Path(ds.folder) / "figures").is_dir():
        # the timing graph is generated from the atlas on every build (and refreshed in the dataset's folder)
        from metrology_atlas.overview import overview_svg
        svg = overview_svg(ds, href=lambda kind, id_: f"../{KINDS[kind].folder}/{id_}.html")
        (Path(ds.folder) / "figures" / "timing-graph.svg").write_text(svg, encoding="utf-8")
        shutil.copytree(Path(ds.folder) / "figures", docs / "figures")
    (docs / "css").mkdir()
    (docs / "css" / "atlas.css").write_text(ATLAS_CSS, encoding="utf-8")
    (docs / "js").mkdir()
    (docs / "js" / "atlas-chart.js").write_text(CHART_JS, encoding="utf-8")
    site.start(ds.meta, base="")
    (docs / "index.md").write_text(site.home(json_name), encoding="utf-8")
    site.start(None, base="")
    (docs / "references.md").write_text(site.references_page(), encoding="utf-8")
    (docs / "planner.md").write_text(planner_page(ds, site), encoding="utf-8")
    entries: dict[str, list] = {}
    for kind in KINDS.values():
        folder = docs / kind.folder
        folder.mkdir()
        site.start(None)
        (folder / "index.md").write_text(site.kind_index(kind.name), encoding="utf-8")
        pages = []
        for id_, item in sorted(ds.items[kind.name].items(), key=lambda x: (x[1].get("order", 99), x[1]["name"])):
            site.start(item)
            (folder / f"{id_}.md").write_text(getattr(site, kind.name)(id_, item), encoding="utf-8")
            pages.append((item, {item["name"]: f"{kind.folder}/{id_}.md"}))
        if kind.name == "variable":  # many: sections, then groups
            entries[kind.name] = [f"{kind.folder}/index.md"] + [
                {sec: [{g: [{item["name"]: f"{kind.folder}/{id_}.md"} for id_, item in vs]} for g, vs in groups.items()]}
                for sec, groups in placed_variables(ds).items()]
        else:
            entries[kind.name] = [f"{kind.folder}/index.md"] + [e for _, e in pages]
    site.start(None, base="")
    (docs / "value.md").write_text(site.value_page(), encoding="utf-8")
    site.start(None, base="")
    (docs / "anchors.md").write_text(site.anchors_page(), encoding="utf-8")
    site.start(None, base="")
    (docs / "terms.md").write_text(TERMS_PAGE.rstrip() + "\n" + site.anchors_concept(), encoding="utf-8")
    about = [{"Aim and terms": "terms.md"}]
    section_pages: dict[str, list] = {}
    for pg in ds.meta.get("pages") or []:
        site.start(None, base="")
        text = site.prose(ds.meta["_page_text"][pg["id"]])
        if OPEN_QUESTIONS_MARK in text:
            text = text.replace(OPEN_QUESTIONS_MARK,
                                site.question_list(("phenomenon", "hypothesis", "assumption", "conflict"), "###"))
        (docs / f"{pg['id']}.md").write_text(text, encoding="utf-8")
        section_pages.setdefault(pg.get("section") or "About", []).append({pg["title"]: f"{pg['id']}.md"})
    about += section_pages.pop("About", [])
    site.start(None, base="")
    (docs / "time.md").write_text(site.time_page(), encoding="utf-8")
    site.start(None, base="")
    (docs / "evidence.md").write_text(site.evidence_page(), encoding="utf-8")
    site.start(None, base="")
    (docs / "open-questions.md").write_text(site.open_questions_page(), encoding="utf-8")
    site.start(None, base="")
    (docs / "figures.md").write_text(site.figures_page(), encoding="utf-8")
    rec_name = (ds.meta.get("records") or {}).get("name")
    if rec_name:
        site.start(None, base="")
        (docs / "records.md").write_text(site.records_page(), encoding="utf-8")
    nav = [{"Home": "index.md"}, {"Variables": entries.pop("variable")},
           {"Time": ["time.md", *section_pages.get("Time", []), {"Synchronisation planner": "planner.md"}, {"Clocks": entries.pop("clock")},
                     {"Clock links": entries.pop("link")}, {"Devices": entries.pop("device")}]},
           {"Value": ["value.md", *section_pages.get("Value", [])] if section_pages.get("Value") else "value.md"},
           {"Evidence": ["evidence.md", {"Open questions": "open-questions.md"}, {"Anchor decisions": "anchors.md"},
                         {"Figures": "figures.md"}]
                        + ([{f"{rec_name.capitalize()}s discussed": "records.md"}] if rec_name else [])
                        + [{KINDS[k].title: entries.pop(k)}
                           for k in ("study", "observation", "parameter", "method", "technique")]}]
    if "example" in entries:
        nav.append({KINDS["example"].title: entries.pop("example")})
    for k in list(entries):
        nav.append({KINDS[k].title: entries.pop(k)})
    nav.append({"References": "references.md"})
    nav.append({"About": about})
    for f in docs.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        t2 = chem_subscripts(t)
        if t2 != t:
            f.write_text(t2, encoding="utf-8")
    brand = Path(__file__).resolve().parents[1] / "brand"
    if brand.is_dir():
        # the logo kit (light touch): favicon, and the line-only mark in the header
        dst = docs / "assets" / "brand"
        dst.mkdir(parents=True, exist_ok=True)
        for f in ("icon/favicon.svg", "icon/favicon.ico", "png/apple-touch-icon.png", "logo/metrology-atlas-mark-mono-white.svg",
                  "logo/metrology-atlas-mark-color.svg", "logo/metrology-atlas-logo-horizontal-color.svg"):
            if (brand / f).is_file():
                shutil.copy2(brand / f, dst / Path(f).name)
    (out / "zensical.toml").write_text(chem_subscripts(_toml(ds.meta, nav, brand.is_dir())), encoding="utf-8")
    return out


def short_citation(citation: str) -> str:
    """'Eytan D, Mazwi ML, ... 2019 ...' -> 'Eytan et al. 2019' (inline reference text); empty if it cannot tell."""
    head = citation.split(".")[0]
    authors = [x.strip() for x in head.split(",") if x.strip()]
    if not authors:
        return ""
    first = authors[0].split()[0] if " " in authors[0] else authors[0]
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", citation)
    who = first if len(authors) == 1 else (f"{first} and {authors[1].split()[0]}" if len(authors) == 2 else f"{first} et al.")
    return f"{who} {m.group(1)}" if m else who


_CHEM = re.compile(r"(?<![A-Za-z]/)(?<![\w`])(SaO|SpO|PaO|PaCO|PvO|PvCO|SvO|ScvO|FiO|FeO|EtO|EtCO|ETCO|FiCO|PCO|PO|CO|O)2(?![\w`])")
_SKIP = re.compile(r"```.*?```|`[^`\n]*`|\]\([^)]*\)|<[^>\n]+>|https?://\S+", re.DOTALL)


def chem_subscripts(md: str) -> str:
    """Gas names with a subscript 2 (SpO2 -> SpO₂, PaCO2 -> PaCO₂, CO2 -> CO₂) in page text and titles.

    Code spans and blocks, link targets, HTML tags and URLs are left alone, and so are device track names such as
    Primus/ETCO2 (a name after a slash), so identifiers keep the spelling of the data.
    """
    out, last = [], 0
    for m in _SKIP.finditer(md):
        out.append(_CHEM.sub(lambda g: g.group(1) + "₂", md[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_CHEM.sub(lambda g: g.group(1) + "₂", md[last:]))
    return "".join(out)


def _toml(meta: dict, nav: list, brand: bool = False) -> str:
    q = json.dumps
    def navs(entries) -> str:
        parts = []
        for e in entries:
            if isinstance(e, str):
                parts.append(q(e))
            else:
                (k, v), = e.items()
                parts.append("{ " + q(k) + " = " + (q(v) if isinstance(v, str) else "[" + navs(v) + "]") + " }")
        return ", ".join(parts)
    site = meta.get("site") or {}
    lines = [
        "[project]",
        f"site_name = {q(site.get('title') or meta['name'])}",
        f"site_description = {q(meta['summary'])}",
        "use_directory_urls = false",
        'docs_dir = "docs"',
    ]
    if site.get("repo_url"):
        lines += [f"repo_url = {q(site['repo_url'])}"]
    if site.get("copyright"):
        lines += [f"copyright = {q(site['copyright'])}"]
    lines += ['extra_css = ["css/atlas.css"]', "nav = [" + navs(nav) + "]", ""]
    lines += [
        "[project.theme]",
        'features = ["navigation.tabs", "navigation.sections", "navigation.top", '
        '"navigation.indexes", "toc.follow", "search.highlight", "search.suggest"]',
    ] + ([
        'logo = "assets/brand/metrology-atlas-mark-color.svg"',
        'favicon = "assets/brand/favicon.svg"',
        "",
    ] if brand else [
        "",
        "[project.theme.icon]",
        'logo = "lucide/clock"',
        "",
    ]) + [
        "[project.theme.palette]",
        'scheme = "default"',
        'primary = "indigo"',
        'accent = "indigo"',
        "",
        "[project.extra]",
        "generator = false",
        "",
        "[project.plugins.search]",
        "",
        "[project.markdown_extensions.admonition]",
        "[project.markdown_extensions.attr_list]",
        "[project.markdown_extensions.footnotes]",
        "[project.markdown_extensions.md_in_html]",
        "[project.markdown_extensions.tables]",
        "[project.markdown_extensions.pymdownx.details]",
        "[project.markdown_extensions.pymdownx.superfences]",
        "[project.markdown_extensions.pymdownx.arithmatex]",
        "generic = true",
        "[project.markdown_extensions.toc]",
        "permalink = true",
        "",
    ]
    return "\n".join(lines)


ATLAS_CSS = """
.fig-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: .8rem; }
.fig-card { display: flex; flex-direction: column; border: 1px solid #e0e0e0; border-radius: 4px; padding: .4rem;
  text-decoration: none; font-size: .7rem; color: inherit; background: #fff; }
.fig-card img { width: 100%; height: 130px; object-fit: contain; background: #fafafa; }
.fig-card span { margin-top: .3rem; }
.ms-fig { margin: .5rem 0 1rem; }
.ms { width: 100%; max-width: 640px; height: auto; font-family: inherit; }
.ms-frame { fill: #fafafa; stroke: #c5c5c5; }
.ms-time { fill: #26a69a; fill-opacity: .14; stroke: #26a69a; stroke-dasharray: 4 3; }
.ms-val { fill: #3f51b5; stroke: #3f51b5; stroke-opacity: .5; }
.ms-acc { fill: none; stroke: #e65100; stroke-width: 1.5; stroke-dasharray: 5 3; }
.ms-zero { stroke: #616161; stroke-width: .8; }
.ms-tick { font-size: 10px; fill: #616161; }
.ms-lab { font-size: 11px; fill: #424242; }
.ms-legend { font-size: .7rem; color: #555; margin-top: .25rem; }
.ms-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .5rem; }
.ms-grid svg { max-width: 340px; }
.ms-key { display: inline-block; width: .9em; height: .9em; vertical-align: -.1em; border-radius: 2px; }
.ms-key-time { background: rgba(38,166,154,.25); border: 1px dashed #26a69a; }
.ms-key-val { background: rgba(63,81,181,.5); }
.ms-key-acc { border: 1.5px dashed #e65100; }
.md-typeset td:first-child code { white-space: nowrap; word-break: normal; overflow-wrap: normal; }
.tc { margin: .6rem 0 1.2rem; font-size: .7rem; }
.tc-row { display: grid; grid-template-columns: 12rem minmax(0, 1fr); gap: .2rem 1rem; align-items: start; padding: .45rem 0;
  border-top: 1px solid var(--md-default-fg-color--lightest); }
.tc-row > .tc-txt { grid-column: 2; }
.tc-head { border-top: none; padding-bottom: 0; color: var(--md-default-fg-color--light); font-size: .62rem; }
@media (max-width: 40rem) { .tc-row { grid-template-columns: 1fr; } .tc-row > .tc-txt { grid-column: 1; } }
.tc-node { font-weight: 700; position: relative; padding-left: 1rem; }
.tc-route .tc-row > .tc-txt { grid-column: 2; }
.tc-node::before { content: ""; position: absolute; left: .2rem; top: .35rem; width: .5rem; height: .5rem; border-radius: 50%;
  background: var(--md-accent-fg-color); }
.tc-row:not(.tc-head):not(:last-child) .tc-node::after { content: ""; position: absolute; left: .42rem; top: .9rem; height: calc(100% + .5rem);
  border-left: 2px solid var(--md-default-fg-color--lightest); }
.tc-bar { width: 100%; max-width: 18rem; height: auto; display: block; margin-top: .2rem; }
.tc-tick { stroke: var(--md-default-fg-color--lightest); stroke-width: 1; }
.tc-off { fill: var(--md-accent-fg-color); fill-opacity: .25; stroke: var(--md-accent-fg-color); stroke-width: 1; }
.tc-res { fill: var(--md-accent-fg-color); stroke: var(--md-accent-fg-color); stroke-width: 1; }
.tc-na, .tc-ax { fill: var(--md-default-fg-color--light); font-size: 9px; text-anchor: middle; }
.tc-meta { margin-bottom: .15rem; }
.tc-kind { text-transform: uppercase; letter-spacing: .04em; font-size: .58rem; font-weight: 700; color: var(--md-default-fg-color--light); }
.tc-st { font-size: .58rem; padding: 0 .3rem; border-radius: .2rem; border: 1px solid var(--md-default-fg-color--lighter); }
.tc-measured { border-style: solid; }
.tc-estimated, .tc-assumed { border-style: dashed; }
.tc-rng { font-weight: 600; }
"""
