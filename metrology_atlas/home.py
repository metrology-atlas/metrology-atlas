"""The home page: an opening, the timing network, ways in, how a record is described, what affects analyses, every
kind of timestamp as an interactive chart, what synchronising does, and how to use and cite the atlas.

Everything below the opening is drawn from the atlas on each build. The longer explanation that used to open the home
page is on the About page (:func:`about_page`); the working reference, the census of synchronisation errors and the
table of clock links are on the Time page.
"""
from __future__ import annotations

import json
from pathlib import Path

from metrology_atlas.timing import forms

TYPE_COLOUR = {"waveform": "#2a78d6", "numeric": "#eb6834", "event": "#1baf7a"}
TYPE_LABEL = {"waveform": "waveform samples", "numeric": "numeric values", "event": "records, lab and clinical times"}
ASSETS = Path(__file__).resolve().parent / "assets"


def _short(text: str | None, limit: int = 150) -> str:
    """The first clause of an evidence note, for a hover box."""
    t = (text or "").strip()
    for sep in (";", ". "):
        if sep in t:
            t = t.split(sep)[0]
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def bias_points(ds) -> list[dict]:
    """Every kind of timestamp as stored (the forms of the paper's bias-uncertainty figure): one point per distinct
    form, with the variables that share it."""
    clocks, devices = ds.items["clock"], ds.items["device"]
    pts: dict[tuple, dict] = {}
    for vid, v in sorted(ds.items["variable"].items(), key=lambda x: x[1]["name"]):
        fv = forms(v)
        raw = any(f["kind"] == "as_stored" and f["name"].startswith("raw stamps") for f in fv)
        for f in fv:
            if f["u_c"] <= 0:                       # labels stored over an interval: no stamp error to show
                continue
            if f["kind"] != "as_stored" or (raw and not f["name"].startswith("raw stamps")):
                continue
            name = f["name"].removeprefix("raw stamps").lstrip(", ")
            if name in ("as stamped", "as recorded", "") or name.lower() in v["name"].lower():
                name = ""
            key = (f["id"], round(f["bias"]["mid"], 4), round(f["u_c"], 4), name)
            c = clocks.get(v.get("stamp_clock") or "") or {}
            d = devices.get(v.get("device") or "") or {}
            p = pts.setdefault(key, {
                "names": [], "hrefs": [], "form": name, "type": v["type"],
                "bias": {k: f["bias"][k] for k in ("lo", "mid", "hi")}, "u": f["u_c"], "status": f["status"],
                "upper": bool(f.get("upper_bound")), "clock": c.get("name") or v.get("stamp_clock") or "",
                "device": d.get("name") or v.get("device") or "", "note": _short(f.get("evidence"))})
            p["names"].append(v["name"])
            p["hrefs"].append(f"variables/{vid}.html")
    return sorted(pts.values(), key=lambda p: p["u"])


def bias_chart(ds) -> str:
    """The interactive bias-uncertainty chart (SVG drawn in the page from the embedded data)."""
    data = bias_points(ds)
    if not data:
        return ""
    key = " &nbsp; ".join(f'<span style="color:{TYPE_COLOUR[t]}">●</span> {TYPE_LABEL[t]}'
                          for t in TYPE_LABEL if any(p["type"] == t for p in data))
    return ('<div id="ma-bias" class="ma-chart"></div>\n'
            f'<p class="ma-cap">{key}. Filled points are measured, hollow ones estimated. Left of zero, the stamp comes '
            'before the interval it describes ends.</p>\n'
            '<script src="js/bias-chart.js"></script>\n<script>\nBiasChart(document.getElementById("ma-bias"), '
            + json.dumps({"points": data, "colours": TYPE_COLOUR}, ensure_ascii=False).replace("</", "<\\/")
            + ");\n</script>\n")


BIAS_JS = r"""
(function () {
  if (window.BiasChart) return;
  function fmt(s) {
    var a = Math.abs(s), m = s < 0 ? "−" : "";
    if (a === 0) return "0";
    if (a < 1) return m + (a * 1000).toFixed(a < 0.01 ? 1 : 0) + " ms";
    if (a < 120) return m + a.toFixed(a < 10 ? 2 : 1).replace(/\.?0+$/, "") + " s";
    if (a < 7200) return m + (a / 60).toFixed(1).replace(/\.0$/, "") + " min";
    return m + (a / 3600).toFixed(1).replace(/\.0$/, "") + " h";
  }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  window.BiasChart = function (host, opt) {
    var P = opt.points, col = opt.colours, W = 1100, H = 470, m = {l: 74, r: 20, t: 14, b: 56};
    var L = 1e-3, sx = function (x) { var a = Math.abs(x); return Math.sign(x) * (a <= L ? a / L * 0.3 : 0.3 + Math.log10(a / L)); };
    var x0 = sx(-3), x1 = sx(7200), y0 = Math.log10(6e-4), y1 = Math.log10(1e5);
    var X = function (x) { return m.l + (sx(x) - x0) / (x1 - x0) * (W - m.l - m.r); };
    var Y = function (y) { return H - m.b - (Math.log10(y) - y0) / (y1 - y0) * (H - m.t - m.b); };
    var g = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img" aria-label="Bias against standard uncertainty for every kind of timestamp">';
    for (var d = -3; d <= 4; d++) for (var k = 2; k <= 9; k++) {
      var v = k * Math.pow(10, d);
      [1, -1].forEach(function (s) { var x = s * v; if (x > -3 && x < 7200) g += '<line class="ma-minor" x1="' + X(x) + '" x2="' + X(x) + '" y1="' + m.t + '" y2="' + (H - m.b) + '"/>'; });
      if (v > 6e-4 && v < 1e5) g += '<line class="ma-minor" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/>';
    }
    var xt = [[-1, "−1 s"], [-0.1, "−100 ms"], [-0.01, "−10 ms"], [0, "0"], [0.01, "10 ms"], [0.1, "100 ms"], [1, "1 s"], [10, "10 s"], [60, "1 min"], [600, "10 min"], [3600, "1 h"]];
    xt.forEach(function (t) { var x = X(t[0]); g += '<line class="' + (t[0] === 0 ? "ma-zero" : "ma-major") + '" x1="' + x + '" x2="' + x + '" y1="' + m.t + '" y2="' + (H - m.b) + '"/><text class="ma-tick" x="' + x + '" y="' + (H - m.b + 18) + '" text-anchor="middle">' + t[1] + '</text>'; });
    [[1e-3, "1 ms"], [1e-2, "10 ms"], [0.1, "100 ms"], [1, "1 s"], [10, "10 s"], [100, "100 s"], [1e3, "1,000 s"], [1e4, "10,000 s"]].forEach(function (t) {
      var y = Y(t[0]); g += '<line class="ma-major" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y + '" y2="' + y + '"/><text class="ma-tick" x="' + (m.l - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + t[1] + '</text>'; });
    g += '<text class="ma-axis" x="' + ((W + m.l) / 2) + '" y="' + (H - 12) + '" text-anchor="middle">bias: the stamp minus the end of the interval it describes (median between recordings)</text>';
    g += '<text class="ma-axis" transform="translate(16,' + ((H - m.b + m.t) / 2) + ') rotate(-90)" text-anchor="middle">standard uncertainty</text>';
    P.forEach(function (p, i) {
      var c = col[p.type] || "#888", fill = p.status === "measured" ? c : "var(--md-default-bg-color, #fff)";
      g += '<a href="' + p.hrefs[0] + '"><circle class="ma-pt" data-i="' + i + '" cx="' + X(p.bias.mid) + '" cy="' + Y(p.u) + '" r="7" fill="' + fill + '" stroke="' + c + '" stroke-width="2"/></a>';
    });
    g += "</svg>";
    host.innerHTML = g + '<div class="ma-tip"></div>';
    var tip = host.querySelector(".ma-tip");
    function show(el) {
      var p = P[+el.getAttribute("data-i")], b = p.bias;
      var range = b.lo !== b.hi ? " (5th to 95th percentile " + fmt(b.lo) + " to " + fmt(b.hi) + ")" : "";
      tip.innerHTML = "<b>" + esc(p.names.join(", ")) + "</b>" + (p.form ? ' <span class="ma-mut">(' + esc(p.form) + ")</span>" : "") + "<br>" +
        '<span class="ma-mut">Device</span> ' + esc(p.device) + '<br><span class="ma-mut">Stamped by</span> ' + esc(p.clock) + "<br>" +
        '<span class="ma-mut">Bias</span> ' + fmt(b.mid) + range + '<br><span class="ma-mut">Standard uncertainty</span> ' + fmt(p.u) + (p.upper ? ", an upper bound" : "") + "<br>" +
        '<span class="ma-mut">Status</span> ' + esc(p.status) + (p.note ? '<br><span class="ma-mut ma-small">' + esc(p.note) + "</span>" : "") +
        '<br><span class="ma-small ma-go">' + (p.hrefs.length > 1 ? "Click to open the first variable" : "Click to open the variable") + "</span>";
      var r = el.getBoundingClientRect(), R = host.getBoundingClientRect(), x = r.left - R.left + 16, y = r.top - R.top - 10;
      if (x > R.width - 370) x = r.left - R.left - 376;
      tip.style.left = x + "px"; tip.style.top = y + "px"; tip.style.display = "block";
    }
    host.querySelectorAll(".ma-pt").forEach(function (el) {
      el.addEventListener("mouseenter", function () { show(el); });
      el.addEventListener("focus", function () { show(el); });
      el.addEventListener("mouseleave", function () { tip.style.display = "none"; });
    });
  };
})();
"""

RECORD_SVG = """<svg class="ma-rec" viewBox="0 0 800 330" width="100%" role="img" aria-label="One heart-rate record as a region of true time and true value: wide in time from the record alone, narrower with the atlas">
<defs><linearGradient id="ma-gw" x1="0" x2="1"><stop offset="0" stop-color="#2a78d6" stop-opacity="0"/><stop offset=".25" stop-color="#2a78d6" stop-opacity=".28"/><stop offset=".75" stop-color="#2a78d6" stop-opacity=".28"/><stop offset="1" stop-color="#2a78d6" stop-opacity="0"/></linearGradient>
<linearGradient id="ma-gn" x1="0" x2="1"><stop offset="0" stop-color="#2a78d6" stop-opacity="0"/><stop offset=".3" stop-color="#2a78d6" stop-opacity=".85"/><stop offset=".7" stop-color="#2a78d6" stop-opacity=".85"/><stop offset="1" stop-color="#2a78d6" stop-opacity="0"/></linearGradient></defs>
<line class="ma-ax" x1="80" y1="270" x2="700" y2="270"/><line class="ma-ax" x1="80" y1="40" x2="80" y2="270"/>
<text class="ma-axis" x="390" y="305" text-anchor="middle">true time, relative to the stamp</text>
<text class="ma-axis" transform="translate(28,155) rotate(-90)" text-anchor="middle">true heart rate</text>
<text class="ma-tick" x="66" y="194" text-anchor="end">72</text><text class="ma-tick" x="66" y="114" text-anchor="end">73</text>
<line class="ma-ax" x1="74" y1="190" x2="80" y2="190"/><line class="ma-ax" x1="74" y1="110" x2="80" y2="110"/>
<text class="ma-tick" x="640" y="290" text-anchor="middle">stamp</text><line class="ma-ax" x1="640" y1="264" x2="640" y2="276"/>
<rect x="150" y="110" width="400" height="80" fill="url(#ma-gw)"/><rect x="250" y="110" width="150" height="80" fill="url(#ma-gn)"/>
<circle cx="640" cy="190" r="7" class="ma-dot"/>
<text class="ma-strong" x="655" y="185">the record</text><text class="ma-tick" x="655" y="204">72 bpm,</text><text class="ma-tick" x="655" y="221">at its stamp</text>
<text x="150" y="100" fill="#2a78d6">the record alone</text><text x="252" y="212" fill="#1a4f99" font-weight="600">with the atlas</text>
<text class="ma-tick" x="150" y="58">The value lies anywhere from 72 up to 73, because the monitor truncates.</text>
<text class="ma-tick" x="150" y="250">The time is a window of beats that closed seconds before the stamp.</text>
</svg>"""


def home(site, json_name: str) -> str:
    """The home page."""
    ds, m = site.ds, site.ds.meta
    h = m.get("home") or {}
    figs = {f["id"]: f for f in m.get("figures") or []}
    out = "---\nhide:\n  - navigation\n  - toc\n---\n\n"
    out += f'<div class="ma-hero" markdown>\n\n# {m["name"]}\n\n'
    if h.get("subtitle"):
        out += f'<p class="ma-sub">{h["subtitle"]}</p>\n\n'
    out += f'<div class="ma-lead" markdown>\n{site.prose(h.get("mission") or m["summary"])}\n</div>\n\n'
    paper = h.get("paper") or {}
    out += ('<div class="ma-btns" markdown>\n'
            + (f'[Read the paper ({paper.get("label", "preprint")})]({paper["url"]}){{ .md-button .md-button--primary }} '
               if paper.get("url") else "")
            + "[Plan a multi-signal analysis](planner.md){ .md-button } "
            + "[Start with a worked example](examples/index.md){ .md-button }\n</div>\n\n")
    if h.get("status"):
        out += f'<div class="ma-status" markdown>\n{site.prose(h["status"])}\n</div>\n\n'
    out += "</div>\n\n"

    if "system-overview" in figs:
        f = dict(figs["system-overview"])
        if h.get("graph_caption"):
            f["caption"] = h["graph_caption"]
        out += site.figure(f) + "\n\n"
        site.placed.add("system-overview")
    studies = ds.items["study"].values()
    cur = sum(1 for s in studies if s.get("status") == "current")
    stats = ([(f'{h["cases"]:,}', "surgical cases")] if h.get("cases") else []) + [
        (str(len(ds.items["variable"])), "variables"), (str(len(ds.items["device"])), "devices"),
        (str(len(ds.items["clock"])), "clocks"), (str(cur), "current studies, each with its code")]
    out += '<div class="ma-stats">' + "".join(f"<div><b>{n}</b><span>{lab}</span></div>" for n, lab in stats) + "</div>\n\n"

    cards = [
        ("Align signals from different devices", "The planner takes the variables an analysis uses and reports how "
         "well their times line up, and on what time grid they can be combined.", "Synchronisation planner", "planner.md"),
        ("What each variable measures", "Each variable's measurand, its measurement model, the interval each value "
         "describes, and its bias and uncertainty.", f"Browse {len(ds.items['variable'])} variables", "variables/index.md"),
        ("How accurate the timestamps are", "Every kind of timestamp, placed by its delay and the interval it "
         "describes, with the clocks behind it.", "Time", "time.md"),
        ("How exact the values are", "Resolution, rounding and hand-charted heaping, with what each recorded number "
         "could have been.", "Value", "value.md"),
        ("Worked examples", "Analyses rerun with the atlas, each from committed code with a record of every run.",
         "Worked examples", "examples/index.md"),
        ("The evidence behind each number", "The studies behind every number, each saved with the code that ran it, "
         "and the questions still open.", "Evidence", "evidence.md"),
    ]
    out += "## Ways into the atlas\n\n" + '<div class="ma-grid" markdown>\n' + "".join(
        f'<div class="ma-card" markdown>\n<p class="ma-q">{q}</p>\n\n{t}\n\n[{lab} →]({href})\n</div>\n' for q, t, lab, href in cards
    ) + "</div>\n\n"

    out += "## How a record is described\n\n"
    if h.get("model_text"):
        out += site.prose(h["model_text"]) + "\n\n"
    if (ASSETS / "measurement-model.svg").is_file():
        out += ('<div class="ma-wide"><img src="assets/measurement-model.svg" alt="How a record was made: the '
                "measurement model forward from the true time and value to the recorded pair, step by step, and the "
                'atlas\'s correction back from the recorded pair towards the truth."></div>\n\n')
    out += ('<div class="ma-two" markdown>\n<div class="ma-panel">\n' + RECORD_SVG + "\n</div>\n"
            f'<div markdown>\n{site.prose(h.get("record_text") or "")}\n\n'
            "[The full example, step by step](worked-example-heart-rate.md) · [About the atlas](about.md)\n</div>\n</div>\n\n")

    props = h.get("properties") or []
    if props:
        out += ("## What affects analyses of " + m["name"].replace(" metrology atlas", "") + "\n\n"
                '<p class="ma-subtle">Properties of the recording system that change how the data should be used. '
                "Each is described on the page of the study that measured it.</p>\n\n"
                '<div class="ma-grid ma-grid2" markdown>\n' + "".join(
                    f'<div class="ma-card ma-soft" markdown>\n<p class="ma-q">{p["title"]}</p>\n\n{site.prose(p["text"])}'
                    + (f" ({site.a('study', p['study'], 'study')})" if p.get("study") else "") + "\n</div>\n" for p in props)
                + "</div>\n\n")

    chart = bias_chart(ds)
    if chart:
        out += ("## Every kind of timestamp, as stored\n\n"
                '<p class="ma-subtle">Each point is one kind of timestamp in the release, placed by its bias (the stamp '
                "minus the end of the interval its value describes, against the working reference) and its standard "
                "uncertainty. Hover over a point for its details, and click to open its variable.</p>\n\n" + chart + "\n")

    if "synchronisation-demo" in figs:
        out += "## What synchronising the clocks does\n\n" + site.figure(figs["synchronisation-demo"]) + "\n\n"
        site.placed.add("synchronisation-demo")
        out += ("The working reference is " + (site.a("clock", m["reference_clock"]) if m.get("reference_clock") else "one clock")
                + " after its stamps are modelled. [Read about the working reference](time.md#the-working-reference).\n\n")

    out += "## Use and cite\n\n" + '<div class="ma-grid" markdown>\n'
    if paper.get("url"):
        out += (f'<div class="ma-card" markdown>\n<p class="ma-q">The paper</p>\n\n{site.prose(paper.get("citation") or "")} '
                f'[{paper.get("label", "preprint")}]({paper["url"]})\n</div>\n')
    from metrology_atlas.site import short_citation
    cites = "; ".join(f"[{short_citation(ds.get('reference', r)['citation'])}](references.md)" for r in m.get("references") or [])
    out += (f'<div class="ma-card" markdown>\n<p class="ma-q">The data and the atlas file</p>\n\nPlease also cite the data '
            f"({cites}). The whole atlas is one machine-readable file, [{json_name}](data/{json_name}), with every number, "
            "its status and its study. [Data and licence](data-and-licence.md)\n</div>\n")
    out += ('<div class="ma-card" markdown>\n<p class="ma-q">The software</p>\n\nThe tools that measured and correct the '
            "timing are open source, with every correction versioned. [Software](software/index.md)\n</div>\n</div>\n")
    return out


def about_page(site, json_name: str) -> str:
    """About the atlas: what used to open the home page (the notice in full, the description, the overview, the two
    axes, and what is in the atlas)."""
    from metrology_atlas.site import KINDS
    m = site.ds.meta
    out = "# About the atlas\n\n"
    if m.get("notice"):
        out += '!!! note "Status of this version"\n\n' + "\n".join(
            ("    " + l) if l else "" for l in site.prose(m["notice"]).strip().splitlines()) + "\n\n"
    out += f"{site.summ(m['summary'])}\n\n{site.prose(m.get('description'))}\n\n"
    if m.get("overview"):
        out += "## System overview\n\n" + site.prose(m["overview"]) + "\n\n"
    out += site.axes_table()
    out += "## What is in the atlas\n\n| | | |\n|---|---|---|\n"
    for k in KINDS.values():
        out += f"| [{k.title}]({k.folder}/index.md) | {len(site.ds.items[k.name])} | {k.help} |\n"
    out += (f"\nThe whole atlas is also one machine-readable file: [{json_name}](data/{json_name}). Every number carries "
            "its status (measured, derived, documented, estimated or assumed), its spread and the study it came from. "
            "[Aim and terms](terms.md) states the atlas's aim in full and maps it onto the international vocabulary.\n")
    return out


HOME_CSS = """
.ma-hero { max-width: 46rem; margin-bottom: .6rem; }
.ma-hero h1 { margin-bottom: .2rem; }
.ma-sub { color: var(--md-accent-fg-color); font-weight: 600; margin-top: 0; }
.ma-lead { font-size: .95rem; line-height: 1.6; }
.ma-btns { margin: .6rem 0 .2rem; }
.ma-btns .md-button { margin: .2rem .4rem .2rem 0; }
.ma-status { font-size: .72rem; color: var(--md-default-fg-color--light); }
.ma-status p { margin: .2rem 0; }
.ma-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: .4rem; margin: .4rem 0 1.4rem; }
.ma-stats div { padding: .6rem .8rem; border-right: 1px solid var(--md-default-fg-color--lightest); }
.ma-stats div:last-child { border-right: none; }
.ma-stats b { display: block; font-size: 1.25rem; }
.ma-stats span { font-size: .68rem; color: var(--md-default-fg-color--light); }
.ma-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; margin: .4rem 0 1rem; }
.ma-grid2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 50rem) { .ma-grid, .ma-grid2 { grid-template-columns: 1fr; } }
.ma-card { border: 1px solid var(--md-default-fg-color--lightest); border-radius: .4rem; padding: .7rem .9rem; font-size: .72rem; }
.ma-card p { margin: .3rem 0; }
.ma-card .ma-q { font-weight: 700; font-size: .78rem; margin-top: 0; }
.ma-soft { background: var(--md-code-bg-color); border-color: transparent; }
.ma-subtle { color: var(--md-default-fg-color--light); }
.ma-two { display: grid; grid-template-columns: 1.2fr 1fr; gap: 1.4rem; align-items: center; margin: 1rem 0; }
@media (max-width: 50rem) { .ma-two { grid-template-columns: 1fr; } }
.ma-panel { border: 1px solid var(--md-default-fg-color--lightest); border-radius: .4rem; padding: .4rem; }
.ma-wide { margin: .8rem 0 1.2rem; }
.ma-wide img { display: block; width: 100%; max-width: 52rem; height: auto; }
.ma-rec text, .ma-chart text { font-family: inherit; }
.ma-rec { font-size: 15px; }
.ma-ax { stroke: var(--md-default-fg-color--lighter); }
.ma-dot { fill: var(--md-default-bg-color); stroke: var(--md-default-fg-color); stroke-width: 2.5; }
.ma-strong { fill: var(--md-default-fg-color); font-weight: 600; }
.ma-axis { fill: var(--md-default-fg-color); font-size: 12px; }
.ma-tick { fill: var(--md-default-fg-color--light); font-size: 12px; }
.ma-rec .ma-tick, .ma-rec .ma-axis { font-size: 15px; }
.ma-chart { position: relative; border: 1px solid var(--md-default-fg-color--lightest); border-radius: .4rem; padding: .4rem .4rem 0; }
.ma-minor { stroke: var(--md-default-fg-color--lightest); stroke-opacity: .45; }
.ma-major { stroke: var(--md-default-fg-color--lightest); }
.ma-zero { stroke: var(--md-default-fg-color--lighter); }
.ma-pt { cursor: pointer; }
.ma-pt:hover { stroke-width: 3.5; }
.ma-tip { position: absolute; display: none; max-width: 22rem; background: var(--md-default-bg-color); border: 1px solid var(--md-default-fg-color--lighter);
  border-radius: .4rem; box-shadow: 0 .2rem .7rem rgba(0,0,0,.12); padding: .5rem .6rem; font-size: .66rem; line-height: 1.45; pointer-events: none; z-index: 2; }
.ma-mut { color: var(--md-default-fg-color--light); }
.ma-small { font-size: .6rem; }
.ma-go { color: var(--md-typeset-a-color); }
.ma-cap { font-size: .66rem; color: var(--md-default-fg-color--light); }
"""
