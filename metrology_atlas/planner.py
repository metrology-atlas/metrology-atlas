"""The synchronisation planner: a page where a reader picks the signals an analysis uses and reads off how well
their times line up, how we know, and what window sizes suit cross-modal features.

A screening tool, not a fit. Every number comes from :func:`metrology_atlas.timing.forms`, which turns each timing
form into a bias and a standard uncertainty (framework spec of 28 Oct 2026):

- a corrected form is not shifted (bias 0, D5); a fixed shift subtracts the release median, known in advance; an
  as-stored form is not shifted and its bias stays as a systematic offset, reported apart from the spread;
- for each pair of signals, ``sqrt(u_a^2 + u_b^2 - 2 cov)``, where ``cov`` sums the products of the components they share
  (the same ``shared_with``: one clock, one correction), which cancel (GUM 5.2); ``sigma`` is the largest pair;
- coherent band ``0.1325 / sigma``; finest useful shared grid ``sqrt(12) * sigma``;
- latency floor: the latest the data can arrive after the close of what they describe (the availability rule);
- signals in one clock domain share their drift; across domains the longest window before drift adds another
  ``sigma`` is ``sigma / |drift_a - drift_b|``, unknown when a drift is unknown;
- real-time use leaves out corrections fitted on data after the stamp (``uses_future``).

Window advice: a feature window at least as long as the longest interval a chosen value describes and at least
``sigma / tolerance``, no longer than the drift limit, stepped by at least the finest grid.
"""

from __future__ import annotations

import json

from metrology_atlas.chart import AXES, chart_forms, chart_xy
from metrology_atlas.timing import forms as timing_forms


def planner_form(f: dict, ds) -> dict:
    """What the page's script needs of one resolved timing form."""
    x, y = chart_xy(f)
    return {"id": f["id"], "name": f["name"], "default": f["default"], "kind": f["kind"], "uses_future": f["uses_future"],
            "bias": f["bias"], "shift": f["shift_s"],
            "removes": f["removes"], "u_c": f["u_c"], "upper_bound": f["upper_bound"], "likely": f["likely_u"],
            "latency": f["latency_s"], "support_hi": (f["support"] or [0, 0])[1], "domain": f["domain"],
            "status": f["status"], "evidence": f["evidence"], "correction": f["correction"], "corrects": f["corrects"],
            "delay": x, "interval": y, "chart_key": f["id"] + "|" + json.dumps([x, y]),
            "shared": {k: round(sum(c["u_s"] ** 2 for c in f["components"] if c.get("shared_with") == k and not c.get("included_in")) ** 0.5, 6)
                       for k in {c.get("shared_with") for c in f["components"] if c.get("shared_with")}},
            "unknown_scope": sum(1 for c in f["components"] if c["scope"] == "unknown" and not c.get("shared_with")),
            "studies": [{"name": ds.items["study"][x]["name"], "href": f"studies/{x}.html"} for x in f["studies"]]}

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
    Each value describes an interval of time; its time is the **end** of that interval, the moment the value could
    first exist. For each signal's chosen form the atlas holds a **bias** (how late the stamp sits after that end,
    systematic within a recording) and a **standard uncertainty** built from named components.

    - **Corrected forms are not shifted**: the correction has already removed the bias. A **fixed shift** subtracts
      the release median, known in advance, so it also works in real time. A form **as stored** is not shifted: its
      bias stays, shown apart as a systematic offset.
    - **Relative timing uncertainty** of two signals: `√(u_a² + u_b² − 2·cov)`, where the covariance comes from the
      error components they share (one clock, one correction), which cancel. σ is the largest over the chosen pairs.
      Components whose sharing is unknown are taken as independent. Where a correction's uncertainty is an upper
      bound, σ is one too.
    - **Coherent band** `0.1325 / σ`: the −3 dB frequency of a Gaussian timing blur. Cross-modal structure faster
      than this is smeared.
    - **Finest useful grid** `√12 · σ`: a shared time grid finer than this adds no cross-channel information.
    - **Latency floor**: the latest the data can arrive after the end of what they describe, including any delay a
      correction removed. A feature vector at time *t* can only hold windows that ended this long before *t*.
    - **Real-time use** leaves out corrections fitted on the whole recording: they use data from after the stamp.
    - **Drift limit** `σ / |Δ drift|`: between clock domains, how long a window can be before drift adds another σ.
      Signals in one domain share their drift, which cancels.
    - **Window advice:** at least the longest interval a chosen value describes, at least `σ / tolerance`, at most the drift limit;
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
    if (x < 1) return (x * 1000).toPrecision(3).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '') + ' ms';
    if (x < 120) return x.toPrecision(3).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '') + ' s';
    if (x < 7200) return (x / 60).toPrecision(3).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '') + ' min';
    return (x / 3600).toPrecision(3).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '') + ' h';
  };
  const hz = (f) => f === Infinity ? 'unlimited' : (f >= 1 ? f.toPrecision(3) + ' Hz' : (60 * f).toPrecision(3) + ' per min');
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const byId = Object.fromEntries(D.signals.map((s) => [s.id, s]));
  const params = new URLSearchParams(location.search);
  const chosen = new Map();
  let realtime = params.get('rt') === '1';
  const usable = (s) => s.forms.filter((f) => !realtime || !f.uses_future);
  const best = (s) => { const u = usable(s); return (u.find((f) => f.default) || u.find((f) => f.kind === 'fixed_shift') || u[0]).id; };
  (params.get('s') || '').split(',').filter((x) => byId[x]).forEach((x) => chosen.set(x, best(byId[x])));

  const devices = [];
  D.signals.forEach((s) => { let d = devices.find((x) => x.name === s.device); if (!d) devices.push(d = {name: s.device, signals: []}); d.signals.push(s); });

  root.innerHTML = '<div class="tp-grid"><div id="tp-pick"></div><div id="tp-out"></div></div>';
  const pick = root.querySelector('#tp-pick'), out = root.querySelector('#tp-out');

  function drawPicker() {
    pick.innerHTML = '<label class="tp-rt"><input type="checkbox" id="tp-rt"' + (realtime ? ' checked' : '') + '> <b>Real-time use</b>: only data and corrections available at the time (leaves out corrections fitted on the whole recording)</label>' + devices.map((d) => '<fieldset><legend>' + esc(d.name) + '</legend>' + d.signals.map((s) => {
      const on = chosen.has(s.id);
      const fs = usable(s);
      const sel = on && fs.length > 1 ? '<select data-s="' + s.id + '">' + fs.map((f) =>
        '<option value="' + f.id + '"' + (chosen.get(s.id) === f.id ? ' selected' : '') + '>' + esc(f.name) + (f.uses_future ? ' (whole-recording fit)' : '') + '</option>').join('') + '</select>' : '';
      return '<label><input type="checkbox" data-s="' + s.id + '"' + (on ? ' checked' : '') + '> ' + esc(s.name) + '</label>' + sel;
    }).join('') + '</fieldset>').join('');
    pick.querySelectorAll('input[type=checkbox]').forEach((el) => el.addEventListener('change', () => {
      const s = byId[el.dataset.s];
      if (el.checked) chosen.set(s.id, best(s)); else chosen.delete(s.id);
      drawPicker(); drawOut();
    }));
    pick.querySelector('#tp-rt').addEventListener('change', (e) => {
      realtime = e.target.checked;
      [...chosen.keys()].forEach((sid) => { const f = byId[sid].forms.find((g) => g.id === chosen.get(sid)); if (realtime && f.uses_future) chosen.set(sid, best(byId[sid])); });
      drawPicker(); drawOut();
    });
    pick.querySelectorAll('select').forEach((el) => el.addEventListener('change', () => { chosen.set(el.dataset.s, el.value); drawOut(); }));
  }

  let tol = 0.1, resolveMs = '';
  function drawOut() {
    const rows = [...chosen].map(([sid, fid]) => ({s: byId[sid], f: byId[sid].forms.find((f) => f.id === fid)}));
    const controls = '<div class="tp-controls"><span>Timing error allowed, as a share of the window: ' +
      [0.05, 0.1, 0.2].map((t) => '<label><input type="radio" name="tp-tol" value="' + t + '"' + (t === tol ? ' checked' : '') + '> ' + (t * 100) + '%</label>').join(' ') +
      '</span><span><label>Timing difference to resolve (ms, optional): <input id="tp-res" type="number" min="0" step="1" style="width:5rem" value="' + resolveMs + '"></label></span></div>';
    if (rows.length < 2) {
      out.innerHTML = controls + '<p>Choose at least two signals on the left. Each signal comes in the forms this atlas knows (as stored, shifted by the release median, corrected per recording ...); the default is the best-corrected form.</p>' +
        '<label style="font-size:.7rem"><input type="checkbox" id="tp-bg"' + (showAll ? ' checked' : '') + '> show every other time source faintly</label><div id="tp-chart"></div>';
      bind(); drawChart(rows); return;
    }
    const terms = rows.map(({s, f}) => ({s, f, sd: f.u_c, bias: f.bias.mid, v: f.u_c * f.u_c}));
    // relative uncertainty of two signals: errors they share (same clock, correction ...) cancel (GUM 5.2)
    const shared = (a, b) => Object.keys(a.f.shared).filter((k) => k in b.f.shared).reduce((c, k) => c + a.f.shared[k] * b.f.shared[k], 0);
    const pairSd = (a, b) => Math.sqrt(Math.max(a.v + b.v - 2 * shared(a, b), 0));
    let sigma = 0, cancelled = [];
    for (let i = 0; i < terms.length; i++) for (let j = i + 1; j < terms.length; j++) {
      sigma = Math.max(sigma, pairSd(terms[i], terms[j]));
      const ks = Object.keys(terms[i].f.shared).filter((k) => k in terms[j].f.shared);
      if (ks.length) cancelled.push(esc(terms[i].s.name) + ' and ' + esc(terms[j].s.name) + ' share ' + ks.map(esc).join(', '));
    }
    const unknownShare = rows.reduce((a, r) => a + r.f.unknown_scope, 0);
    const tv = terms.reduce((a, t) => a + t.v, 0);
    const band = sigma > 0 ? 0.1325 / sigma : Infinity, grid = SQ12 * sigma;
    const latency = Math.max(...rows.map((r) => r.f.latency));
    const oldest = Math.max(...rows.map((r) => r.f.latency + r.f.support_hi));
    const slowest = Math.max(...rows.map((r) => r.f.support_hi));
    const mids = rows.map((r) => r.f.bias.mid);
    const offset = Math.max(...mids) - Math.min(...mids);
    const upper = rows.some((r) => r.f.upper_bound);
    const doms = [...new Set(rows.map((r) => r.f.domain))];
    let drift = Infinity, driftNote = 'all in one clock domain: drift cancels';
    if (doms.length > 1) {
      const ppm = doms.map((d) => D.domains[d]?.drift_ppm);
      if (ppm.some((p) => p === null || p === undefined)) {
        drift = null;
        driftNote = 'drift unknown for ' + doms.filter((d, i) => ppm[i] === null || ppm[i] === undefined).map((d) => D.domains[d]?.name || d).join(', ');
      } else {
        // largest relative drift over the pairs of domains: the rates' difference and their spreads between recordings
        const uu = doms.map((d) => D.domains[d]?.drift_u_ppm || 0);
        let dp = 0;
        for (let i = 0; i < doms.length; i++) for (let j = i + 1; j < doms.length; j++)
          dp = Math.max(dp, Math.round(Math.sqrt((ppm[i] - ppm[j]) ** 2 + uu[i] ** 2 + uu[j] ** 2)));
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
    const raw = rows.filter((r) => r.s.forms.length > 1 && !r.f.default && !(realtime && r.s.forms.find((g) => g.default)?.uses_future));
    if (raw.length) warn.push('Using a less-corrected form for ' + raw.map((r) => esc(r.s.name)).join(', ') + '; the default form lines up better.');
    if (offset > 0) warn.push('Stamps used as stored keep their bias: a systematic offset of up to ' + fmt(offset) + ' between these signals, not included in σ. Shift them (fixed shift) or correct them to remove it.');
    if (realtime) warn.push('Real-time use: corrections fitted on the whole recording are left out.');
    if (cancelled.length) warn.push('Shared errors cancel between signals: ' + cancelled.join('; ') + '.');
    if (unknownShare) warn.push(unknownShare + ' error component' + (unknownShare > 1 ? 's' : '') + ' with unknown sharing are taken as independent, so σ may be an overestimate.');
    let res = '';
    if (resolveMs) { const n = Math.ceil(Math.pow(sigma / (resolveMs / 1000), 2)); res = '<div class="tp-card"><b>' + n + '</b><span>events to average to resolve ' + resolveMs + ' ms (random part only; a bias does not average away)</span></div>'; }

    out.innerHTML = controls +
      '<div class="tp-verdict"><strong>These signals line up to about ' + fmt(sigma) + ' (1 SD' + (upper ? ', an upper bound' : '') + ')</strong>' + (offset > 0 ? ', plus a systematic offset of up to ' + fmt(offset) + ' from stamps used as stored' : '') + '; good enough for ' + tier + '.</div>' +
      '<div class="tp-cards">' +
      card(fmt(sigma), 'relative timing uncertainty (1 SD)') + (offset > 0 ? card(fmt(offset), 'systematic offset left (as stored)') : '') + card(hz(band), 'coherent cross-modal band') +
      card(fmt(grid), 'finest useful shared grid') + card(fmt(latency), 'latency floor (availability rule)') +
      card(fmt(oldest), 'oldest data in a feature vector') + card(fmt(drift), 'longest window before drift adds another σ') + res + '</div>' +
      warn.map((w) => '<div class="tp-warn">' + w + '</div>').join('') +
      '<h3>Where these signals sit</h3><label style="font-size:.7rem"><input type="checkbox" id="tp-bg"' + (showAll ? ' checked' : '') + '> show every other time source faintly</label><div id="tp-chart"></div>' +
      '<h3>Window sizing for cross-modal features</h3><ul>' +
      '<li><strong>Window length: at least ' + fmt(wMin) + '.</strong> ' + (slowest >= sigma / tol ? 'Set by the slowest signal, whose values each describe ' + fmt(slowest) + '.' : 'Set by the timing error: σ is then ' + (tol * 100) + '% of the window.') + '</li>' +
      '<li><strong>At most ' + fmt(drift) + '</strong> without re-synchronising (' + esc(driftNote) + ').</li>' +
      '<li><strong>Step at least ' + fmt(grid) + '.</strong> A finer shared grid adds no cross-channel information.</li>' +
      '<li><strong>Latency:</strong> a feature at time <em>t</em> can only use windows that ended ' + fmt(latency) + ' before <em>t</em>.</li>' +
      '<li><strong>Line each signal up first:</strong> ' + terms.map((t) => esc(t.s.name) + ': ' + (
        t.f.kind === 'per_recording' ? 'apply its ' + esc(t.f.correction || 'correction') + (t.f.removes ? ' (it removes ' + fmt(t.f.removes[0]) + '–' + fmt(t.f.removes[1]) + (t.f.uses_future ? '; fitted on the whole recording' : '') + ')' : (t.f.uses_future ? ' (fitted on the whole recording)' : '')) :
        t.f.kind === 'fixed_shift' ? (t.f.shift < 0 ? 'shift forward by ' + fmt(-t.f.shift) : 'shift back by ' + fmt(t.f.shift)) + ' (' + esc(t.f.correction || 'a fixed shift') + ')' :
        (t.f.bias.mid > 0 ? 'no shift: its stamps are late by ' + fmt(t.f.bias.lo) + '–' + fmt(t.f.bias.hi) + ', median ' + fmt(t.f.bias.mid) :
         t.f.bias.mid < 0 ? 'no shift: its stamps come early by ' + fmt(-t.f.bias.hi) + '–' + fmt(-t.f.bias.lo) + ', median ' + fmt(-t.f.bias.mid) + ' (look-ahead)' : 'no shift'))).join('; ') + '.</li></ul>' +
      '<h3>Where the error comes from, and how we know</h3>' +
      '<table><thead><tr><th>Signal</th><th>Form</th><th>Bias left</th><th>Uncertainty (1 SD)</th><th>Share of the variance</th><th>Real time</th><th>Clock domain</th><th>Evidence</th></tr></thead><tbody>' +
      terms.sort((a, b) => b.v - a.v).map((t) => '<tr><td><a href="' + t.s.href + '">' + esc(t.s.name) + '</a></td><td>' + esc(t.f.name) +
        (t.f.status !== 'measured' ? ' <em>(' + t.f.status + ')</em>' : '') + '</td><td>' + (t.f.bias.mid !== 0 ? fmt(t.f.bias.mid) : '0') + '</td><td>' + (t.f.upper_bound ? '≤ ' : '') + fmt(t.sd) + (t.f.likely ? ' (likely ' + fmt(t.f.likely) + ')' : '') + '</td><td>' +
        (tv > 0 ? Math.round(100 * t.v / tv) : 0) + '%</td><td>' + (t.f.uses_future ? 'no' : 'yes') + '</td><td>' + (D.domains[t.f.domain]?.href ? '<a href="' + D.domains[t.f.domain].href + '">' + esc(D.domains[t.f.domain].name) + '</a>' : esc(D.domains[t.f.domain]?.name || t.f.domain)) +
        '</td><td>' + esc(t.f.evidence) + (t.f.studies.length ? '<br>' + t.f.studies.map((x) => '<a href="' + x.href + '">' + esc(x.name) + '</a>').join(', ') : '') + '</td></tr>').join('') +
      '</tbody></table>' + pairs(terms);
    bind();
    drawChart(rows);
    history.replaceState(null, '', '?s=' + [...chosen.keys()].join(',') + (realtime ? '&rt=1' : ''));
  }
  let showAll = true, chart = null;
  function drawChart(rows) {
    const host = out.querySelector('#tp-chart');
    if (!host || !window.AtlasChart) return;
    chart = AtlasChart(host, {...D.chart, stack: true, filename: 'planner-timing'});
    const items = [], arrows = [], mine = new Set();
    rows.forEach(({s, f}) => {
      s.forms.forEach((g) => {
        const key = s.id + '|' + g.id;
        mine.add(g.chart_key);
        items.push({key, group: s.type, delay: g.delay, interval: g.interval, estimated: g.status !== 'measured', status: g.status,
          evidence: g.evidence, label: s.name + ' (' + g.name + ')' + (g.id === f.id ? '' : ': not chosen'), href: s.href, emph: g.id === f.id ? 1 : 0.35});
        g.corrects.filter((c) => s.forms.some((h) => h.id === c)).forEach((c) => arrows.push([s.id + '|' + c, key]));
      });
    });
    if (showAll) D.chart.items.forEach((it) => { if (!mine.has(it.key)) items.push({...it, bg: true}); });
    chart.draw(items, arrows, 'Choose signals to place them on the chart.');
  }
  function card(v, label) { return '<div class="tp-card"><b>' + v + '</b><span>' + label + '</span></div>'; }
  function pairs(terms) {
    if (terms.length < 3) return '';
    const ts = [...terms].sort((a, b) => a.s.name.localeCompare(b.s.name));
    return '<h3>Pair by pair</h3><p>Relative timing uncertainty (1 SD) for each pair alone, shared errors cancelled. σ above is the largest of these.</p><table><thead><tr><th></th>' +
      ts.map((t) => '<th>' + esc(t.s.name) + '</th>').join('') + '</tr></thead><tbody>' +
      ts.map((a) => '<tr><th>' + esc(a.s.name) + '</th>' + ts.map((b) => '<td>' + (a === b ? '—' : fmt(Math.sqrt(Math.max(a.v + b.v - 2 * Object.keys(a.f.shared).filter((k) => k in b.f.shared).reduce((c, k) => c + a.f.shared[k] * b.f.shared[k], 0), 0)))) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
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
            "forms": [planner_form(f, ds) for f in timing_forms(s)],
        })
    domains = {d["id"]: {"name": d["name"], "drift_ppm": d.get("drift_ppm"), "drift_u_ppm": d.get("drift_u_ppm"), "drift_status": d.get("drift_status"),
                         "href": f"clocks/{d['clock']}.html" if d.get("clock") else None}
               for d in ds.meta.get("domains") or []}
    chart = chart_forms(ds)
    chart.update(AXES, aria="Timing of the chosen signals")
    data = json.dumps({"signals": signals, "domains": domains, "chart": chart}, ensure_ascii=False).replace("</", "<\\/")
    ref = site.prose(ds.meta.get("reference") or "").replace("\n", "\n    ")
    return PAGE.format(data=data, code=CODE, reference=ref)
