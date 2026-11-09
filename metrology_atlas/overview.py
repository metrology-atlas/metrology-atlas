"""The timing graph as a diagram, generated from the atlas's clocks, links and parameters.

Every clock is placed by its distance from the root reference (UTC): a link from clock A against clock B puts A one
row below B. Each link carries a numbered badge; its line is coloured by status (measured, estimated, assumed). The
detail of each link (drift, correction, status) is in a table keyed by those numbers (overview_table) and in an
information panel that opens on hover; clicking a clock or a link opens its page. Nothing is typed in by hand.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import escape, quoteattr

STATUS_COL = {"measured": "#1b7f4b", "derived": "#1b7f4b", "documented": "#1f5fa8", "estimated": "#b26b00", "assumed": "#7a7a7a",
              "superseded": "#bbbbbb", "withdrawn": "#bbbbbb"}
STATUS_DASH = {"estimated": "8,5", "assumed": "2,5"}
FONT = "Inter, Helvetica, Arial, sans-serif"
NODE_W, NODE_H, ROW_H, MARGIN = 250, 60, 190, 40
# The print layout (print_=True), for a figure set at a page's text width (about 455 pt): narrower boxes, wrapped
# labels and type about twice the screen size, so that the smallest text prints at about 6 pt. No hover, no script.
SCREEN = dict(node_w=NODE_W, node_h=NODE_H, row_h=ROW_H, gap=34, margin=MARGIN, min_w=1000, t=15, s=11.5, n=12, k=12,
              r=11, wrap=False)
PRINT = dict(node_w=190, node_h=100, row_h=150, gap=30, margin=20, min_w=0, t=18, s=15, n=14, k=16, r=12, wrap=True)


def _param_text(ds, pid):
    if not pid:
        return ""
    p = ds.items["parameter"].get(pid)
    if not p:
        return ""
    v, u = p.get("value"), p.get("unit") or ""
    txt = (f"{v:+g} {u}".strip() if u == "ppm" else f"{v:,g} {u}".strip()) if v is not None else ""
    if p.get("display"):
        disp = " ".join(str(p["display"]).split())
        num = f"{v:,g}" if v is not None else None
        # the display already states the value (or a range for it): use it alone
        if not txt or (num and (num in disp or num.replace(",", "") in disp)) or ("ppm" in disp and "ppm" in txt):
            txt = disp
        else:
            txt = f"{txt} ({disp})"
    return " ".join(str(txt).split())


def _short(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _lines(text, size, width, bold=False):
    """Wrap text to a box width, estimating Inter's advance as 0.54 (semibold) or 0.53 of the font size per character."""
    n = max(int(width / (size * (0.54 if bold else 0.53))), 8)
    out, line = [], ""
    for w in str(text).split():
        if line and len(line) + 1 + len(w) > n:
            out.append(line); line = w
        else:
            line = f"{line} {w}".strip()
    return out + [line] if line else out


def graph(ds, root="utc", L=SCREEN):
    """Layout: rows by distance from the root; deeper clocks centred under the clock they are measured against."""
    clocks, links = ds.items["clock"], ds.items["link"]
    live = {k: l for k, l in links.items() if l.get("status") not in ("withdrawn", "superseded")}
    depth = {root: 0}
    changed = True
    while changed:
        changed = False
        for l in live.values():
            a, b = l["clock"], l["against"]
            if b in depth and (a not in depth or depth[a] > depth[b] + 1):
                depth[a] = depth[b] + 1; changed = True
    for c in clocks:
        depth.setdefault(c, max(depth.values()) + 1)
    rows = {}
    for c, d in depth.items():
        rows.setdefault(d, []).append(c)
    kids = {}
    for l in live.values():
        if depth.get(l["clock"]) == depth.get(l["against"], -9) + 1:
            kids.setdefault(l["against"], [])
            if l["clock"] not in kids[l["against"]]:
                kids[l["against"]].append(l["clock"])
    parent = {k: p for p, ks in kids.items() for k in ks}
    gap = L["node_w"] + L["gap"]
    xpos = {}

    def centre_out(cs):
        ranked = sorted(cs, key=lambda c: (-len(kids.get(c, [])), clocks[c]["name"]))
        out = []
        for i, c in enumerate(ranked):
            out.append(c) if i % 2 else out.insert(0, c)
        return out

    for d in sorted(rows):
        row = rows[d]
        if d > 0 and all(c in parent for c in row):
            groups = {}
            for c in row:
                groups.setdefault(parent[c], []).append(c)
            for pnt, grp in sorted(groups.items(), key=lambda kv: xpos[kv[0]]):
                grp = centre_out(grp)
                for i, c in enumerate(grp):
                    xpos[c] = xpos[pnt] + (i - (len(grp) - 1) / 2) * gap
        else:
            for i, c in enumerate(centre_out(row)):
                xpos[c] = (i - (len(row) - 1) / 2) * gap
    lo, hi = min(xpos.values()), max(xpos.values())
    width = max(hi - lo + L["node_w"] + 2 * L["margin"], L["min_w"])
    top = 60 if L is SCREEN else 20
    height = top + 10 + max(rows) * L["row_h"] + L["node_h"] + 30
    off = (width - (hi - lo)) / 2 - lo
    xy = {c: (xpos[c] + off, top + depth[c] * L["row_h"] + L["node_h"] / 2) for c in depth}
    pairs = {}
    for lid, l in sorted(live.items(), key=lambda kv: (depth.get(kv[1]["clock"], 9), xy.get(kv[1]["clock"], (0, 0))[0])):
        pairs.setdefault((l["clock"], l["against"]), []).append(lid)
    numbers = {}
    for n, ((a, b), ids) in enumerate(pairs.items(), 1):
        for lid in ids:
            numbers[lid] = n
    return dict(clocks=clocks, live=live, depth=depth, xy=xy, pairs=pairs, numbers=numbers, width=width, height=height)


def link_rows(ds, g):
    """One row per link: number, name, drift, correction interval and size, rule, status."""
    rows = []
    for (a, b), ids in g["pairs"].items():
        for lid in ids:
            l = g["live"][lid]; c = l.get("correction") or {}
            rows.append(dict(n=g["numbers"][lid], id=lid, name=l["name"], clock=a, against=b,
                             modes=", ".join(l.get("modes") or []), status=l.get("status", ""),
                             rate=_param_text(ds, l.get("rate")), period=_param_text(ds, c.get("period")),
                             size=_param_text(ds, c.get("size")), rule=" ".join(str(c.get("rule") or "").split()),
                             summary=" ".join(str(l.get("summary") or "").split())))
    return rows


def overview_svg(ds, root="utc", href=lambda kind, id_: "", print_=False):
    """Draw the timing graph as an SVG: every clock below the clock it is measured against, links labelled with drift
    and correction interval; `href` gives each box's link. `print_` gives the layout for a printed page (PRINT).
    """
    L = PRINT if print_ else SCREEN
    NODE_W, NODE_H = L["node_w"], L["node_h"]
    g = graph(ds, root, L)
    clocks, xy, depth = g["clocks"], g["xy"], g["depth"]
    info = {r["id"]: r for r in link_rows(ds, g)}
    W, H = g["width"], g["height"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}" role="img" '
           f'aria-label="The atlas timing graph: clocks and the links measured between them">',
           f"<style>.t{{font-size:{L['t']}px;font-weight:600;fill:#14213d}}.s{{font-size:{L['s']}px;fill:#555}}"
           f".n{{font-size:{L['n']}px;font-weight:700;fill:#fff}}.k{{font-size:{L['k']}px;fill:#444}}"
           ".hit{cursor:pointer}.hit:hover .box{stroke-width:2.6}.hit:hover .line{stroke-width:4.5}"
           "#tip text{font-size:12.5px;fill:#14213d}#tip .h{font-weight:700}</style>"]
    # links
    for (a, b), ids in g["pairs"].items():
        if a not in xy or b not in xy:
            continue
        n = g["numbers"][ids[0]]
        st = g["live"][ids[0]].get("status", "assumed")
        col = STATUS_COL.get(st, "#7a7a7a"); dash = STATUS_DASH.get(st)
        (x1, y1), (x2, y2) = xy[a], xy[b]
        if depth[a] == depth[b] and abs(x1 - x2) <= NODE_W + 40:
            # neighbours in one row: a short straight link across the gap, badge in the middle
            sx = 1 if x2 > x1 else -1
            d = f"M{x1 + sx * NODE_W / 2:.0f},{y1:.0f} L{x2 - sx * NODE_W / 2:.0f},{y2:.0f}"
            bx, by = (x1 + x2) / 2, y1
        elif depth[a] == depth[b]:
            my = y1 + NODE_H / 2 + 70
            d = f"M{x1:.0f},{y1 + NODE_H / 2:.0f} Q{(x1 + x2) / 2:.0f},{my:.0f} {x2:.0f},{y2 + NODE_H / 2:.0f}"
            bx, by = (x1 + x2) / 2, (y1 + NODE_H / 2 + my) / 2
        else:
            d = f"M{x1:.0f},{y1 - NODE_H / 2:.0f} L{x2:.0f},{y2 + NODE_H / 2:.0f}"
            by = y1 - NODE_H / 2 - (26 if L is SCREEN else 22)
            f = (y1 - NODE_H / 2 - by) / max(y1 - y2 - NODE_H, 1)
            bx = x1 + f * (x2 - x1)
        lines = []
        for lid in ids:
            r = info[lid]
            lines += [f"{n}. {r['name']}" + (f" ({r['modes']})" if r["modes"] and r["modes"] not in r["name"] else ""),
                      *(x for x in (r["rate"] and "Drift: " + r["rate"], r["period"] and "Corrected every " + r["period"],
                                    r["size"] and "Correction size: " + r["size"], "Status: " + r["status"]) if x)]
        url = href("link", ids[0])
        out.append(f'<a class="hit" href="{url}" target="_top" data-tip={quoteattr(json.dumps(lines))}>'
                   f'<path class="line" d="{d}" fill="none" stroke="{col}" stroke-width="2.6"'
                   + (f' stroke-dasharray="{dash}"' if dash else "") + "/>"
                   f'<path d="{d}" fill="none" stroke="transparent" stroke-width="14"/>'
                   f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="{L["r"]}" fill="{col}"/>'
                   f'<text x="{bx:.0f}" y="{by + L["n"] * 0.35:.0f}" text-anchor="middle" class="n">{n}</text>'
                   f"<title>{escape(chr(10).join(lines))}</title></a>")
    # clocks
    for c, (x, y) in xy.items():
        cl = clocks.get(c, {"name": c})
        lines = [cl["name"], _short(cl.get("summary") or "", 90)]
        if cl.get("nominal"):
            lines.append("Nominal: " + _short(cl["nominal"], 80))
        url = href("clock", c)
        if L["wrap"]:
            # title and nominal wrapped to the box, the block centred in it
            tl = _lines(cl["name"], L["t"], NODE_W - 14, bold=True)
            sl = _lines(_short(cl.get("nominal") or "", 40), L["s"], NODE_W - 14)
            lh_t, lh_s = L["t"] * 1.15, L["s"] * 1.2
            y0 = y - (len(tl) * lh_t + len(sl) * lh_s + 4) / 2 + L["t"] * 0.85
            texts = "".join(f'<text x="{x:.0f}" y="{y0 + i * lh_t:.0f}" text-anchor="middle" class="t">{escape(t)}</text>'
                            for i, t in enumerate(tl))
            ys = y0 + (len(tl) - 1) * lh_t + 4 + lh_s
            texts += "".join(f'<text x="{x:.0f}" y="{ys + i * lh_s:.0f}" text-anchor="middle" class="s">{escape(t)}</text>'
                             for i, t in enumerate(sl))
        else:
            texts = (f'<text x="{x:.0f}" y="{y - 3:.0f}" text-anchor="middle" class="t">{escape(cl["name"])}</text>'
                     f'<text x="{x:.0f}" y="{y + 16:.0f}" text-anchor="middle" class="s">{escape(_short(cl.get("nominal") or "", 36))}</text>')
        out.append(f'<a class="hit" href="{url}" target="_top" data-tip={quoteattr(json.dumps(lines))}>'
                   f'<rect class="box" x="{x - NODE_W / 2:.0f}" y="{y - NODE_H / 2:.0f}" width="{NODE_W}" height="{NODE_H}" '
                   f'rx="8" fill="#f5f7fb" stroke="#14213d" stroke-width="1.4"/>' + texts +
                   f"<title>{escape(chr(10).join(lines))}</title></a>")
    # legend
    lx = L["margin"]
    for i, (st, lab) in enumerate((("measured", "measured"), ("estimated", "estimated"), ("assumed", "assumed"))):
        x = lx + i * (150 if L is SCREEN else 170)
        out.append(f'<line x1="{x}" y1="{H - 18}" x2="{x + 36}" y2="{H - 18}" stroke="{STATUS_COL[st]}" stroke-width="2.6"'
                   + (f' stroke-dasharray="{STATUS_DASH[st]}"' if st in STATUS_DASH else "") + "/>"
                   f'<text x="{x + 44}" y="{H - 14}" class="k">{lab}</text>')
    if print_:
        out.append("</svg>")
        return "\n".join(out)
    out.append(f'<text x="{lx + 470}" y="{H - 14}" class="k">Numbers: the links in the table below. '
               f'Hover for detail; click to open a page.</text>')
    # hover panel
    out.append('<g id="tip" visibility="hidden" pointer-events="none"><rect rx="6" fill="#ffffff" stroke="#14213d" '
               'stroke-width="1" opacity="0.97"/></g>')
    out.append("""<script><![CDATA[
(function(){
  var svg=document.documentElement, tip=document.getElementById('tip'), box=tip.firstChild, NS='http://www.w3.org/2000/svg';
  function wrap(s,n){var w=s.split(' '),o=[],l='';w.forEach(function(x){if((l+' '+x).trim().length>n){o.push(l.trim());l=x;}else{l+=' '+x;}});if(l.trim())o.push(l.trim());return o;}
  function show(ev){
    var lines=JSON.parse(this.getAttribute('data-tip')), out=[];
    lines.forEach(function(s,i){wrap(s,60).forEach(function(t,j){out.push([t,i===0&&j===0]);});});
    while(tip.childNodes.length>1)tip.removeChild(tip.lastChild);
    out.forEach(function(p,i){var t=document.createElementNS(NS,'text');t.setAttribute('x',12);t.setAttribute('y',20+i*17);
      if(p[1])t.setAttribute('class','h');t.textContent=p[0];tip.appendChild(t);});
    var w=0;for(var i=1;i<tip.childNodes.length;i++){w=Math.max(w,tip.childNodes[i].getComputedTextLength());}
    box.setAttribute('width',w+24);box.setAttribute('height',out.length*17+14);
    var pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;var p=pt.matrixTransform(svg.getScreenCTM().inverse());
    var vb=svg.viewBox.baseVal, x=Math.min(p.x+14, vb.width-w-34), y=Math.min(p.y+14, vb.height-out.length*17-24);
    tip.setAttribute('transform','translate('+x+','+y+')');tip.setAttribute('visibility','visible');
  }
  function hide(){tip.setAttribute('visibility','hidden');}
  Array.prototype.forEach.call(document.querySelectorAll('[data-tip]'),function(a){a.addEventListener('mousemove',show);a.addEventListener('mouseleave',hide);});
})();
]]></script>""")
    out.append("</svg>")
    return "\n".join(out)


def overview_table(ds, href=lambda kind, id_: "", root="utc") -> str:
    """Markdown table of the links, keyed by the figure's numbers."""
    g = graph(ds, root)
    rows = link_rows(ds, g)
    name = lambda c: g["clocks"].get(c, {"name": c})["name"]
    out = ["| # | Link | Clock | Against | Drift | Corrected every | Correction size | Status |",
           "|---:|---|---|---|---|---|---|---|"]
    for r in rows:
        nm = r["name"] + (f" ({r['modes']})" if r["modes"] and r["modes"] not in r["name"] else "")
        out.append(f"| {r['n']} | [{nm}]({href('link', r['id'])}) | {name(r['clock'])} | {name(r['against'])} | "
                   f"{r['rate'] or '—'} | {r['period'] or '—'} | {r['size'] or '—'} | {r['status']} |")
    return "\n".join(out)
