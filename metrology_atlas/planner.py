"""The synchronisation planner: a page where a reader picks the signals an analysis uses and reads off how well
their times line up, how we know, and what window sizes suit cross-modal features.

The model is a screening tool, not a fit (after vitaldb-bench's ``pair_timing_budget.py``). For each signal's
chosen timing form, ``delay_s = [lo, hi]`` and ``interval_s = [.., y_hi]``:

- the delay is corrected to the middle of its range; what is left is uniform: ``sd = (hi - lo) / sqrt(12)``;
- where in its interval a value's time lies is uniform: ``sr = y_hi / sqrt(12)``;
- signals are taken as independent: ``sigma = sqrt(sum(sd^2 + sr^2))``;
- coherent band ``0.1325 / sigma``; finest useful shared grid ``sqrt(12) * sigma``;
- latency floor ``max(hi)``, oldest data ``max(hi + y_hi)`` (the availability rule);
- signals in one clock domain share their drift; across domains the longest window before drift adds another
  ``sigma`` is ``sigma / |drift_a - drift_b|``, unknown when a drift is unknown.

Window advice: a feature window at least as long as the slowest signal's interval and at least ``sigma / tolerance``
(so the timing error is at most that fraction of the window), no longer than the drift limit, stepped by at least
the finest grid.
"""

from __future__ import annotations

import json

from metrology_atlas.chart import AXES, chart_forms

PAGE = r"""---
hide:
  - navigation
  - toc
---

# Synchronisation planner

Pick the signals your analysis combines. The planner reports how well their times line up against each other,
how we know, and what window sizes keep cross-modal features meaningful. It is a screening tool built from the
timing of each signal in this atlas, not a fit to your data.

<div id="planner" class="tp"><p><em>The planner needs JavaScript.</em></p></div>

??? info "How the numbers are worked out"
    For each signal, the delay from the end of the interval a value describes to its stamp lies in a range
    `[lo, hi]` against the working reference, and the interval itself is up to `y_hi` wide.

    - **Shift each signal by the middle of its delay range.** What is left is treated as uniform: spread
      `(hi − lo) / √12`. Where in its interval a value's time lies adds `y_hi / √12`.
    - **Relative timing error** `σ = √(Σ spread² + Σ interval²)`, over all chosen signals, taken as independent.
    - **Coherent band** `0.1325 / σ`: the −3 dB frequency of a Gaussian timing blur. Cross-modal structure faster
      than this is smeared.
    - **Finest useful grid** `√12 · σ`: a shared time grid finer than this adds no cross-channel information.
    - **Latency floor** `max hi` (plus the delay a correction removed, for corrected forms): a feature vector at
      time *t* can only hold windows that ended this long before *t*.
    - **Drift limit** `σ / |Δ drift|`: between clock domains, how long a window can be before drift adds another σ.
      Signals in one domain share their drift, which cancels.
    - **Window advice:** at least the slowest signal's interval, at least `σ / tolerance`, at most the drift limit;
      step by at least the finest grid.

    {reference}

<style>
.tp {{ margin: 1rem 0 2rem; }}
.tp .tp-grid {{ display: grid; grid-template-columns: minmax(16rem, 1fr) 2fr; gap: 1.5rem; }}
@media (max-width: 60rem) {{ .tp .tp-grid {{ grid-template-columns: 1fr; }} }}
.tp fieldset {{ border: 1px solid var(--md-default-fg-color--lightest); border-radius: .3rem; margin: 0 0 .8rem; padding: .3rem .7rem .6rem; }}
.tp legend {{ font-weight: 600; font-size: .75rem; padding: 0 .3rem; }}
.tp label {{ display: block; font-size: .72rem; line-height: 1.5; cursor: pointer; }}
.tp select {{ font-size: .68rem; margin: 0 0 .25rem 1.4rem; max-width: 92%; }}
.tp .tp-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr)); gap: .6rem; margin: .5rem 0 1rem; }}
.tp .tp-card {{ border: 1px solid var(--md-default-fg-color--lightest); border-radius: .3rem; padding: .5rem .7rem; }}
.tp .tp-card b {{ display: block; font-size: 1rem; }}
.tp .tp-card span {{ font-size: .62rem; color: var(--md-default-fg-color--light); }}
.tp .tp-verdict {{ border-left: .2rem solid var(--md-accent-fg-color); padding: .4rem .8rem; margin: .5rem 0 1rem; background: var(--md-code-bg-color); }}
.tp .tp-warn {{ color: var(--md-typeset-color); border-left: .2rem solid #e6a100; padding: .3rem .8rem; margin: .4rem 0; font-size: .7rem; }}
.tp table {{ font-size: .68rem; }}
.tp .tp-controls {{ display: flex; flex-wrap: wrap; gap: 1rem; font-size: .72rem; margin-bottom: .5rem; }}
.tp .tp-controls label {{ display: inline; }}
</style>

<script src="js/atlas-chart.js"></script>
<script>
const ATLAS_PLANNER = {data};
{code}
</script>
"""

CODE = r"""
(function () {
  const D = ATLAS_PLANNER, root = document.getElementById('planner');
  if (!root) return;
  const SQ12 = Math.sqrt(12);
  const fmt = (x) => {
    if (x === null || x === undefined || Number.isNaN(x)) return 'unknown';
    if (x === Infinity) return 'unlimited';
    if (x < 1) return (x * 1000).toPrecision(3).replace(/\.?0+$/, '') + ' ms';
    if (x < 120) return x.toPrecision(3).replace(/\.?0+$/, '') + ' s';
    if (x < 7200) return (x / 60).toPrecision(3).replace(/\.?0+$/, '') + ' min';
    return (x / 3600).toPrecision(3).replace(/\.?0+$/, '') + ' h';
  };
  const hz = (f) => f === Infinity ? 'unlimited' : (f >= 1 ? f.toPrecision(3) + ' Hz' : (60 * f).toPrecision(3) + ' per min');
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const byId = Object.fromEntries(D.signals.map((s) => [s.id, s]));
  const params = new URLSearchParams(location.search);
  const chosen = new Map();
  (params.get('s') || '').split(',').filter((x) => byId[x]).forEach((x) => chosen.set(x, byId[x].forms.find((f) => f.default)?.id || byId[x].forms[0].id));

  const devices = [];
  D.signals.forEach((s) => { let d = devices.find((x) => x.name === s.device); if (!d) devices.push(d = {name: s.device, signals: []}); d.signals.push(s); });

  root.innerHTML = '<div class="tp-grid"><div id="tp-pick"></div><div id="tp-out"></div></div>';
  const pick = root.querySelector('#tp-pick'), out = root.querySelector('#tp-out');

  function drawPicker() {
    pick.innerHTML = devices.map((d) => '<fieldset><legend>' + esc(d.name) + '</legend>' + d.signals.map((s) => {
      const on = chosen.has(s.id);
      const sel = on && s.forms.length > 1 ? '<select data-s="' + s.id + '">' + s.forms.map((f) =>
        '<option value="' + f.id + '"' + (chosen.get(s.id) === f.id ? ' selected' : '') + '>' + esc(f.name) + '</option>').join('') + '</select>' : '';
      return '<label><input type="checkbox" data-s="' + s.id + '"' + (on ? ' checked' : '') + '> ' + esc(s.name) + '</label>' + sel;
    }).join('') + '</fieldset>').join('');
    pick.querySelectorAll('input[type=checkbox]').forEach((el) => el.addEventListener('change', () => {
      const s = byId[el.dataset.s];
      if (el.checked) chosen.set(s.id, (s.forms.find((f) => f.default) || s.forms[0]).id); else chosen.delete(s.id);
      drawPicker(); drawOut();
    }));
    pick.querySelectorAll('select').forEach((el) => el.addEventListener('change', () => { chosen.set(el.dataset.s, el.value); drawOut(); }));
  }

  let tol = 0.1, resolveMs = '';
  function drawOut() {
    const rows = [...chosen].map(([sid, fid]) => ({s: byId[sid], f: byId[sid].forms.find((f) => f.id === fid)}));
    const controls = '<div class="tp-controls"><span>Timing error allowed, as a share of the window: ' +
      [0.05, 0.1, 0.2].map((t) => '<label><input type="radio" name="tp-tol" value="' + t + '"' + (t === tol ? ' checked' : '') + '> ' + (t * 100) + '%</label>').join(' ') +
      '</span><span><label>Timing difference to resolve (ms, optional): <input id="tp-res" type="number" min="0" step="1" style="width:5rem" value="' + resolveMs + '"></label></span></div>';
    if (rows.length < 2) {
      out.innerHTML = controls + '<p>Choose at least two signals on the left. Each signal comes in the forms this atlas knows (raw stamps, after a correction ...); the default is the best-corrected form.</p>' +
        '<label style="font-size:.7rem"><input type="checkbox" id="tp-bg"' + (showAll ? ' checked' : '') + '> show every other time source faintly</label><div id="tp-chart"></div>';
      bind(); drawChart(rows); return;
    }
    const terms = rows.map(({s, f}) => {
      const sd = (f.delay[1] - f.delay[0]) / SQ12, sr = f.interval[1] / SQ12;
      return {s, f, sd, sr, bias: (f.delay[0] + f.delay[1]) / 2, v: sd * sd + sr * sr};
    });
    const sigma = Math.sqrt(terms.reduce((a, t) => a + t.v, 0));
    const band = sigma > 0 ? 0.1325 / sigma : Infinity, grid = SQ12 * sigma;
    const late = (f) => f.delay[1] + (f.corrected ? f.corrected[1] : 0);
    const latency = Math.max(...rows.map((r) => late(r.f)));
    const oldest = Math.max(...rows.map((r) => late(r.f) + r.f.interval[1]));
    const slowest = Math.max(...rows.map((r) => r.f.interval[1]));
    const doms = [...new Set(rows.map((r) => r.f.domain))];
    let drift = Infinity, driftNote = 'all in one clock domain: drift cancels';
    if (doms.length > 1) {
      const ppm = doms.map((d) => D.domains[d]?.drift_ppm);
      if (ppm.some((p) => p === null || p === undefined)) {
        drift = null;
        driftNote = 'drift unknown for ' + doms.filter((d, i) => ppm[i] === null || ppm[i] === undefined).map((d) => D.domains[d]?.name || d).join(', ');
      } else {
        const dp = Math.max(...ppm) - Math.min(...ppm);
        drift = dp ? sigma / (dp * 1e-6) : Infinity;
        driftNote = 'relative drift ' + dp + ' ppm between ' + doms.map((d) => D.domains[d].name).join(' and ') +
          (doms.some((d) => D.domains[d].drift_status === 'assumed') ? ' (partly assumed)' : '');
      }
    }
    const wMin = Math.max(slowest, sigma / tol);
    const tooLong = drift !== null && drift !== Infinity && wMin > drift;
    const tier = sigma < 0.005 ? 'within-beat timing (for example pulse arrival time)' : sigma < 0.05 ? 'beat-to-beat alignment' :
      sigma < 1 ? 'breath-level alignment' : sigma < 10 ? 'trends over tens of seconds' : 'trends over minutes or longer';
    const warn = [];
    const est = rows.filter((r) => r.f.status !== 'measured');
    if (est.length) warn.push('Estimated, not measured: ' + est.map((r) => esc(r.s.name) + ' (' + esc(r.f.name) + ')').join(', ') + '.');
    if (drift === null) warn.push('The drift between some of these clocks is not known, so a safe window length cannot be bounded: ' + esc(driftNote) + '.');
    if (tooLong) warn.push('The shortest sensible window (' + fmt(wMin) + ') is longer than the drift limit (' + fmt(drift) + '): correct the drift (synchronise those signals) or loosen the tolerance.');
    const raw = rows.filter((r) => r.s.forms.length > 1 && !r.f.default);
    if (raw.length) warn.push('Using a less-corrected form for ' + raw.map((r) => esc(r.s.name)).join(', ') + '; the default form lines up better.');
    let res = '';
    if (resolveMs) { const n = Math.ceil(Math.pow(sigma / (resolveMs / 1000), 2)); res = '<div class="tp-card"><b>' + n + '</b><span>events to average to resolve ' + resolveMs + ' ms (random part only; a bias does not average away)</span></div>'; }

    out.innerHTML = controls +
      '<div class="tp-verdict"><strong>These signals line up to about ' + fmt(sigma) + ' (1 SD)</strong>, good enough for ' + tier + '.</div>' +
      '<div class="tp-cards">' +
      card(fmt(sigma), 'relative timing error (1 SD)') + card(hz(band), 'coherent cross-modal band') +
      card(fmt(grid), 'finest useful shared grid') + card(fmt(latency), 'latency floor (availability rule)') +
      card(fmt(oldest), 'oldest data in a feature vector') + card(fmt(drift), 'longest window before drift adds another σ') + res + '</div>' +
      warn.map((w) => '<div class="tp-warn">' + w + '</div>').join('') +
      '<h3>Where these signals sit: accuracy and resolution</h3><label style="font-size:.7rem"><input type="checkbox" id="tp-bg"' + (showAll ? ' checked' : '') + '> show every other time source faintly</label><div id="tp-chart"></div>' +
      '<h3>Window sizing for cross-modal features</h3><ul>' +
      '<li><strong>Window length: at least ' + fmt(wMin) + '.</strong> ' + (slowest >= sigma / tol ? 'Set by the slowest signal, whose values already describe ' + fmt(slowest) + ' each.' : 'Set by the timing error: σ is then ' + (tol * 100) + '% of the window.') + '</li>' +
      '<li><strong>At most ' + fmt(drift) + '</strong> without re-synchronising (' + esc(driftNote) + ').</li>' +
      '<li><strong>Step at least ' + fmt(grid) + '.</strong> A finer shared grid adds no cross-channel information.</li>' +
      '<li><strong>Latency:</strong> a feature at time <em>t</em> can only use windows that ended ' + fmt(latency) + ' before <em>t</em>.</li>' +
      '<li><strong>Line each signal up first:</strong> ' + terms.map((t) => esc(t.s.name) + ': ' + (t.f.corrected ?
        'apply its ' + esc(t.f.correction || 'correction') + ' (it removes ' + fmt(t.f.corrected[0]) + '–' + fmt(t.f.corrected[1]) + ')' :
        (t.bias < 0.0005 ? 'no shift' : 'shift back by ' + fmt(t.bias)))).join('; ') + '.</li></ul>' +
      '<h3>Where the error comes from, and how we know</h3>' +
      '<table><thead><tr><th>Signal</th><th>Form</th><th>Delay spread</th><th>Interval</th><th>Share of σ²</th><th>Clock domain</th><th>Evidence</th></tr></thead><tbody>' +
      terms.sort((a, b) => b.v - a.v).map((t) => '<tr><td><a href="' + t.s.href + '">' + esc(t.s.name) + '</a></td><td>' + esc(t.f.name) +
        (t.f.status !== 'measured' ? ' <em>(' + t.f.status + ')</em>' : '') + '</td><td>' + fmt(t.sd) + '</td><td>' + fmt(t.sr) + '</td><td>' +
        Math.round(100 * t.v / (sigma * sigma)) + '%</td><td>' + (D.domains[t.f.domain]?.href ? '<a href="' + D.domains[t.f.domain].href + '">' + esc(D.domains[t.f.domain].name) + '</a>' : esc(D.domains[t.f.domain]?.name || t.f.domain)) +
        '</td><td>' + esc(t.f.evidence) + (t.f.studies.length ? '<br>' + t.f.studies.map((x) => '<a href="' + x.href + '">' + esc(x.name) + '</a>').join(', ') : '') + '</td></tr>').join('') +
      '</tbody></table>' + pairs(terms);
    bind();
    drawChart(rows);
    history.replaceState(null, '', '?s=' + [...chosen.keys()].join(','));
  }
  let showAll = true, chart = null;
  function drawChart(rows) {
    const host = out.querySelector('#tp-chart');
    if (!host || !window.AtlasChart) return;
    chart = AtlasChart(host, {...D.chart, stack: true, filename: 'planner-accuracy-resolution'});
    const items = [], arrows = [], mine = new Set();
    rows.forEach(({s, f}) => {
      s.forms.forEach((g) => {
        const key = s.id + '|' + g.id;
        mine.add(g.id + '|' + JSON.stringify([g.delay, g.interval]));
        items.push({key, group: s.type, delay: g.delay, interval: g.interval, estimated: g.status !== 'measured', status: g.status,
          evidence: g.evidence, label: s.name + ' (' + g.name + ')' + (g.id === f.id ? '' : ': not chosen'), href: s.href, emph: g.id === f.id ? 1 : 0.35});
        g.corrects.forEach((c) => arrows.push([s.id + '|' + c, key]));
      });
    });
    if (showAll) D.chart.items.forEach((it) => { if (!mine.has(it.key)) items.push({...it, bg: true}); });
    chart.draw(items, arrows, 'Choose signals to place them on the chart.');
  }
  function card(v, label) { return '<div class="tp-card"><b>' + v + '</b><span>' + label + '</span></div>'; }
  function pairs(terms) {
    if (terms.length < 3) return '';
    const ts = [...terms].sort((a, b) => a.s.name.localeCompare(b.s.name));
    return '<h3>Pair by pair</h3><p>Relative timing error (1 SD) for each pair alone.</p><table><thead><tr><th></th>' +
      ts.map((t) => '<th>' + esc(t.s.name) + '</th>').join('') + '</tr></thead><tbody>' +
      ts.map((a) => '<tr><th>' + esc(a.s.name) + '</th>' + ts.map((b) => '<td>' + (a === b ? '—' : fmt(Math.sqrt(a.v + b.v))) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
  }
  function bind() {
    out.querySelectorAll('input[name=tp-tol]').forEach((el) => el.addEventListener('change', () => { tol = +el.value; drawOut(); }));
    const bg = out.querySelector('#tp-bg');
    if (bg) bg.addEventListener('change', () => { showAll = bg.checked; drawOut(); });
    const r = out.querySelector('#tp-res');
    if (r) r.addEventListener('change', () => { resolveMs = r.value && +r.value > 0 ? +r.value : ''; drawOut(); });
  }
  drawPicker(); drawOut();
})();
"""


def planner_page(ds, site) -> str:
    """The planner page, with the timing of every signal embedded (no fetch, so it also works from a file)."""
    site.start(None, base="")
    signals = []
    timed = {k: v for k, v in ds.items["variable"].items() if v.get("timing") and v.get("device")}
    for sid, s in sorted(timed.items(), key=lambda x: (ds.items["device"][x[1]["device"]]["name"], x[1]["name"])):
        signals.append({
            "id": sid, "name": s["name"], "device": ds.items["device"][s["device"]]["name"], "type": s["type"],
            "href": f"variables/{sid}.md".replace(".md", ".html"),
            "forms": [{
                "id": t["id"], "name": t["name"], "default": bool(t.get("default")), "delay": t["delay_s"],
                "interval": t["interval_s"], "domain": t["domain"], "status": t["status"], "evidence": t["evidence"],
                "corrected": t.get("corrected_delay_s"), "correction": t.get("correction"),
                "corrects": t.get("corrects") or [],
                "studies": [{"name": ds.items["study"][x]["name"], "href": f"studies/{x}.html"} for x in t.get("studies") or []],
            } for t in s["timing"]],
        })
    domains = {d["id"]: {"name": d["name"], "drift_ppm": d.get("drift_ppm"), "drift_status": d.get("drift_status"),
                         "href": f"clocks/{d['clock']}.html" if d.get("clock") else None}
               for d in ds.meta.get("domains") or []}
    chart = chart_forms(ds)
    chart.update(AXES, aria="Accuracy against resolution of the chosen signals")
    data = json.dumps({"signals": signals, "domains": domains, "chart": chart}, ensure_ascii=False).replace("</", "<\\/")
    ref = site.prose(ds.meta.get("reference") or "").replace("\n", "\n    ")
    return PAGE.format(data=data, code=CODE, reference=ref)
