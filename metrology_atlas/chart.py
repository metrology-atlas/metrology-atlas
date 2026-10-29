"""The timing chart (bias against standard uncertainty), drawn in the browser from the atlas data (decision D4).

Every timing form is an ellipse: across, its bias, the displacement of the stamp from the end of the interval a value
describes, on a symmetric log axis so that zero and early stamps (negative, look-ahead) can show; the ellipse spans the
spread of that bias between recordings (p5-p95). Up, its combined standard uncertainty (log axis). A corrected form
sits at zero bias (or its named remaining bias). A solid outline is measured, a dashed one estimated or assumed; an
arrow joins a form to the corrected form that improves on it. The home page shows the forms as stored (D4: raw time
sources); the planner shows every form of the signals a reader picks.
"""

from __future__ import annotations

import json
import math

from metrology_atlas.timing import forms

GROUP_LABELS = {
    "waveform": "Waveform samples",
    "numeric": "Numeric values (the interval they describe)",
    "event": "Records, lab and clinical times",
    "text": "Text",
}


SYMLOG = 1e-3
"""Bias axis: linear within +-1 ms, logarithmic beyond: t(v) = sign(v) log10(1 + |v| / SYMLOG)."""


def chart_xy(f: dict) -> tuple[list[float], list[float]]:
    """Where a resolved timing form sits: x the bias range (p5-p95, or the single value), y its standard uncertainty."""
    b = f["bias"]
    return [b["lo"], b["hi"]], [f["u_c"], f["u_c"]]


def _t(v: float) -> float:
    return math.copysign(math.log10(1 + abs(v) / SYMLOG), v)


def chart_forms(ds, kinds: tuple[str, ...] | None = None) -> dict:
    """Every distinct timing form (of the given kinds; all when None), with arrows and the axis extent, ready for the chart."""
    items: dict[str, dict] = {}
    by_form: dict[tuple[str, str], str] = {}
    for sid, s in sorted(ds.items["variable"].items(), key=lambda x: x[1]["name"]):
        for t in forms(s):
            if kinds and t["kind"] not in kinds:
                continue
            x, y = chart_xy(t)
            key = t["id"] + "|" + json.dumps([x, y])
            it = items.setdefault(key, {
                "key": key, "form": t["name"], "signals": [], "group": s["type"], "delay": x,
                "interval": y, "estimated": t["status"] != "measured", "status": t["status"],
                "evidence": t["evidence"], "hrefs": [],
            })
            it["signals"].append(s["name"])
            it["hrefs"].append(f"variables/{sid}.html")
            by_form[(sid, t["id"])] = key
    arrows = set()
    for sid, s in ds.items["variable"].items():
        for t in forms(s):
            for c in t["corrects"]:
                if (sid, c) in by_form and (sid, t["id"]) in by_form:
                    arrows.add((by_form[(sid, c)], by_form[(sid, t["id"])]))
    lo = lambda v: math.log10(max(v, 1e-6))
    xs = [_t(v) for it in items.values() for v in it["delay"]] + [0.0]
    ys = [lo(v) for it in items.values() for v in it["interval"] if v > 0]
    ext = {"x": [math.floor(min(xs)) - (0.3 if min(xs) < 0 else 0.5), math.ceil(max(xs) + 0.3)],
           "y": [math.floor(min(ys, default=-3)), math.ceil(max(ys, default=1) + 0.3)], "symlog": SYMLOG}
    for it in items.values():
        it["label"] = ", ".join(it["signals"]) + f" ({it['form']})"
    return {"items": list(items.values()), "arrows": sorted(arrows), "extent": ext, "groups": GROUP_LABELS}


CHART_JS = r"""
(function () {
  if (window.AtlasChart) return;
  const css = `
  .ac { display: grid; grid-template-columns: minmax(0, 3fr) minmax(14rem, 2fr); gap: 1rem; align-items: start; margin: .5rem 0 1rem; }
  @media (max-width: 60rem) { .ac { grid-template-columns: 1fr; } }
  .ac.ac-stack { grid-template-columns: 1fr; }
  .ac.ac-stack ol { columns: 2 18rem; max-height: none; }
  .ac.ac-stack ol li { break-inside: avoid; }
  .ac .ac-dl { font-size: .62rem; margin-left: .6rem; }
  .ac svg { width: 100%; height: auto; color: var(--md-default-fg-color); font-family: inherit; }
  .ac .ac-grid { stroke: var(--md-default-fg-color--lightest); stroke-width: 1; }
  .ac .ac-minor { stroke: var(--md-default-fg-color--lightest); stroke-width: .5; opacity: .6; }
  .ac .ac-zero { stroke: var(--md-default-fg-color); stroke-width: 1.6; opacity: .75; }
  .ac .ac-axis { stroke: var(--md-default-fg-color--light); stroke-width: 1; }
  .ac text { fill: var(--md-default-fg-color--light); font-size: 11px; }
  .ac .ac-title { fill: var(--md-default-fg-color); font-size: 12px; }
  .ac g.ac-e { cursor: default; }
  .ac g.ac-e.hot ellipse { stroke-width: 3.2; }
  .ac .ac-badge circle { fill: var(--md-default-bg-color); stroke-width: 1.3; }
  .ac .ac-badge text { fill: var(--md-default-fg-color); font-size: 10px; font-weight: 700; text-anchor: middle; dominant-baseline: central; }
  .ac ol { list-style: none; margin: 0; padding: 0; font-size: .66rem; max-height: 36rem; overflow: auto; }
  .ac ol li { margin: 0 0 .35rem; padding: .1rem .3rem; border-radius: .2rem; display: grid; grid-template-columns: 1.6rem 1fr; }
  .ac ol li.hot { background: var(--md-accent-fg-color--transparent); }
  .ac ol li.ac-h { font-weight: 700; margin-top: .6rem; display: flex; gap: .4rem; align-items: center; }
  .ac ol li.ac-h i { width: .7rem; height: .7rem; display: inline-block; border-radius: .1rem; }
  .ac ol li b { font-weight: 700; }
  .ac ol li small { display: block; color: var(--md-default-fg-color--light); }
  .ac .ac-key { font-size: .62rem; color: var(--md-default-fg-color--light); margin: .2rem 0 0; }
  `;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const COL = {waveform: '#2a78d6', numeric: '#eb6834', event: '#1baf7a', text: '#8a6fd1'};
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const lg = (v) => Math.log10(Math.max(v, 1e-6));
  let C = 1e-3;
  const tx = (v) => Math.sign(v) * Math.log10(1 + Math.abs(v) / C);
  let uid = 0;

  window.AtlasChart = function (host, opt) {
    const W = 720, H = 600, M = {l: 66, r: 14, t: 14, b: 66};
    const [x0, x1] = opt.extent.x, [y0, y1] = opt.extent.y;
    C = opt.extent.symlog || 1e-3;
    const sx = (l) => M.l + (l - x0) / (x1 - x0) * (W - M.l - M.r);
    const sy = (l) => H - M.b - (l - y0) / (y1 - y0) * (H - M.t - M.b);
    const id = 'ac' + (++uid);
    function draw(items, arrows, emptyText) {
      if (!items.length) { host.innerHTML = '<p class="ac-key">' + (emptyText || '') + '</p>'; return; }
      const groups = Object.keys(opt.groups);
      const shown = items.filter((it) => !it.bg);
      shown.sort((a, b) => groups.indexOf(a.group) - groups.indexOf(b.group) ||
        (lg(a.interval[0]) + lg(a.interval[1])) - (lg(b.interval[0]) + lg(b.interval[1])));
      shown.forEach((it, i) => { it.n = i + 1; });
      const geo = (it) => {
        const cx = (tx(it.delay[0]) + tx(it.delay[1])) / 2, cy = (lg(it.interval[0]) + lg(it.interval[1])) / 2;
        const w = Math.max(tx(it.delay[1]) - tx(it.delay[0]), 0.2), h = Math.max(lg(it.interval[1]) - lg(it.interval[0]), 0.2);
        return {cx: sx(cx), cy: sy(cy), rx: (sx(x0 + w) - sx(x0)) / 2, ry: (sy(y0) - sy(y0 + h)) / 2};
      };
      let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opt.aria || 'Timing of time stamps') + '">';
      s += '<defs><marker id="' + id + 'm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor" opacity=".7"/></marker></defs>';
      const TICKS = [[1e-3, '1 ms'], [1e-2, '10 ms'], [0.1, '100 ms'], [1, '1 s'], [10, '10 s'], [60, '1 min'], [600, '10 min'],
        [3600, '1 h'], [36000, '10 h'], [86400, '1 d']];
      for (let k = -3; k <= 5; k++) for (let m = 2; m <= 9; m++) for (const sg of [1, -1]) {
        const v = sg * m * Math.pow(10, k); if (Math.abs(v) < C) continue;
        const X = tx(v); if (X < x0 || X > x1) continue;
        s += '<line class="ac-minor" x1="' + sx(X) + '" x2="' + sx(X) + '" y1="' + M.t + '" y2="' + (H - M.b) + '"/>';
      }
      for (let k = Math.floor(y0); k <= y1; k++) for (let m = 2; m <= 9; m++) {
        const Y = k + Math.log10(m); if (Y < y0 || Y > y1) continue;
        s += '<line class="ac-minor" y1="' + sy(Y) + '" y2="' + sy(Y) + '" x1="' + M.l + '" x2="' + (W - M.r) + '"/>';
      }
      const xt = [[0, '0']]; TICKS.forEach(([v, l]) => { if (v >= C) { xt.push([v, l], [-v, '−' + l]); } });
      xt.sort((a, b) => a[0] - b[0]);
      let lastX = -1e9;
      xt.forEach(([v, l]) => {
        const X = tx(v); if (X < x0 || X > x1) return;
        s += '<line class="' + (v === 0 ? 'ac-zero' : 'ac-grid') + '" x1="' + sx(X) + '" x2="' + sx(X) + '" y1="' + M.t + '" y2="' + (H - M.b) + '"/>';
        if (Math.abs(v) !== C && sx(X) - lastX >= 30) { s += '<text x="' + sx(X) + '" y="' + (H - M.b + 16) + '" text-anchor="middle">' + l + '</text>'; lastX = sx(X); }
      });
      for (let k = Math.ceil(y0); k <= y1; k++) {
        s += '<line class="ac-grid" y1="' + sy(k) + '" y2="' + sy(k) + '" x1="' + M.l + '" x2="' + (W - M.r) + '"/>';
        s += '<text x="' + (M.l - 6) + '" y="' + (sy(k) + 4) + '" text-anchor="end">10<tspan dy="-5" font-size="8">' + k + '</tspan></text>';
      }
      s += '<rect class="ac-axis" fill="none" x="' + M.l + '" y="' + M.t + '" width="' + (W - M.l - M.r) + '" height="' + (H - M.t - M.b) + '"/>';
      s += '<text class="ac-title" x="' + ((M.l + W - M.r) / 2) + '" y="' + (H - 18) + '" text-anchor="middle">' + esc(opt.xlabel) + '</text>';
      s += '<text class="ac-title" transform="translate(16,' + ((M.t + H - M.b) / 2) + ') rotate(-90)" text-anchor="middle">' + esc(opt.ylabel) + '</text>';
      items.filter((it) => it.bg).forEach((it) => {
        const g = geo(it);
        s += '<ellipse cx="' + g.cx + '" cy="' + g.cy + '" rx="' + g.rx + '" ry="' + g.ry + '" fill="currentColor" fill-opacity=".05" stroke="currentColor" stroke-opacity=".18"' + (it.estimated ? ' stroke-dasharray="4 3"' : '') + '><title>' + esc(it.label) + '</title></ellipse>';
      });
      shown.forEach((it) => {
        const g = geo(it), c = COL[it.group] || '#888', e = it.emph === undefined ? 1 : it.emph;
        s += '<g class="ac-e" data-n="' + it.n + '" opacity="' + e + '"><ellipse cx="' + g.cx + '" cy="' + g.cy + '" rx="' + g.rx + '" ry="' + g.ry + '" fill="' + c + '" fill-opacity=".18" stroke="' + c + '" stroke-width="1.8"' + (it.estimated ? ' stroke-dasharray="5 4"' : '') + '/><title>' + it.n + '. ' + esc(it.label) + '\n' + esc(it.evidence) + '</title></g>';
      });
      const pos = Object.fromEntries(shown.map((it) => [it.key, geo(it)]));
      arrows.forEach(([a, b]) => {
        if (!pos[a] || !pos[b]) return;
        const A = pos[a], B = pos[b], dx = B.cx - A.cx, dy = B.cy - A.cy, d = Math.hypot(dx, dy) || 1;
        if (d < 24) return;
        s += '<line x1="' + (A.cx + dx / d * 10) + '" y1="' + (A.cy + dy / d * 10) + '" x2="' + (B.cx - dx / d * 12) + '" y2="' + (B.cy - dy / d * 12) + '" stroke="currentColor" stroke-opacity=".6" stroke-width="1.2" stroke-dasharray="5 3" marker-end="url(#' + id + 'm)"/>';
      });
      const placed = [];
      shown.forEach((it) => {
        const g = geo(it); let bx = g.cx, by = g.cy;
        const cand = [[0, 0]];
        for (const r of [16, 26, 36]) for (let a = 0; a < 360; a += 45) cand.push([r * Math.cos(a * Math.PI / 180), r * Math.sin(a * Math.PI / 180)]);
        for (const [dx, dy] of cand) { if (placed.every(([px, py]) => Math.hypot(px - g.cx - dx, py - g.cy - dy) > 17)) { bx = g.cx + dx; by = g.cy + dy; break; } }
        placed.push([bx, by]);
        const c = COL[it.group] || '#888', e = it.emph === undefined ? 1 : it.emph;
        if (bx !== g.cx || by !== g.cy) s += '<line x1="' + g.cx + '" y1="' + g.cy + '" x2="' + bx + '" y2="' + by + '" stroke="' + c + '" stroke-width="1" opacity="' + e + '"/>';
        s += '<g class="ac-badge ac-e" data-n="' + it.n + '" opacity="' + e + '"><circle cx="' + bx + '" cy="' + by + '" r="8" stroke="' + c + '"/><text x="' + bx + '" y="' + by + '">' + it.n + '</text><title>' + esc(it.label) + '</title></g>';
      });
      s += '</svg>';
      let leg = '';
      groups.forEach((gname) => {
        const its = shown.filter((it) => it.group === gname);
        if (!its.length) return;
        leg += '<li class="ac-h"><i style="background:' + COL[gname] + '"></i>' + esc(opt.groups[gname]) + '</li>';
        its.forEach((it) => {
          const name = it.href ? '<a href="' + it.href + '">' + esc(it.label) + '</a>' : esc(it.label);
          leg += '<li data-n="' + it.n + '"><b>' + it.n + '</b><span>' + name + (it.estimated ? ' <em>(' + esc(it.status) + ')</em>' : '') + '<small>' + esc(it.evidence) + '</small></span></li>';
        });
      });
      host.innerHTML = '<div class="ac' + (opt.stack ? ' ac-stack' : '') + '"><div>' + s + '<p class="ac-key">Across: bias (symmetric log axis; left of zero, the stamp comes early). Up: standard uncertainty. Solid outline: measured. Dashed: estimated or assumed. Dashed arrow: a form to the corrected form that improves on it. Hover for details.<a class="ac-dl" href="#">Download SVG</a></p></div><ol>' + leg + '</ol></div>';
      host.querySelector('.ac-dl').addEventListener('click', (ev) => {
        ev.preventDefault();
        const svg = host.querySelector('svg').cloneNode(true);
        svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        const cs = getComputedStyle(host);
        svg.querySelectorAll('text').forEach((t) => { t.setAttribute('fill', cs.color); t.setAttribute('font-family', 'sans-serif'); });
        svg.querySelectorAll('.ac-grid').forEach((l) => l.setAttribute('stroke', '#ddd'));
        svg.querySelectorAll('.ac-minor').forEach((l) => { l.setAttribute('stroke', '#eee'); l.setAttribute('stroke-width', '.5'); });
        svg.querySelectorAll('.ac-zero').forEach((l) => { l.setAttribute('stroke', '#333'); l.setAttribute('stroke-width', '1.6'); });
        svg.querySelectorAll('.ac-axis').forEach((l) => l.setAttribute('stroke', '#999'));
        svg.querySelectorAll('.ac-badge circle').forEach((c) => c.setAttribute('fill', '#fff'));
        svg.setAttribute('style', 'color:#222;background:#fff');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], {type: 'image/svg+xml'}));
        a.download = (opt.filename || 'timing-chart') + '.svg'; a.click();
      });
      const hot = (n, on) => host.querySelectorAll('[data-n="' + n + '"]').forEach((el) => el.classList.toggle('hot', on));
      host.querySelectorAll('[data-n]').forEach((el) => {
        el.addEventListener('mouseenter', () => hot(el.dataset.n, true));
        el.addEventListener('mouseleave', () => hot(el.dataset.n, false));
      });
    }
    return {draw};
  };
})();
"""

AXES = {
    "xlabel": "Bias: stamp minus the end of the interval a value describes (negative = early)",
    "ylabel": "Standard uncertainty, 1 SD (s)",
}
