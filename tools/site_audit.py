"""Automated checks of a built atlas site (the HTML zensical writes), for a release.

Finds what a reader would trip over without reading every page:
  - internal links to pages, files or anchors that do not exist; images that do not exist;
  - atlas markup left unrendered ([[...]], {{...}}, markdown link or table syntax in text);
  - words that should not reach a reader: None, nan, NaN, TODO, FIXME, Traceback, undefined;
  - machine paths (/sessions/, /mnt/c, C:\\, /home/) and work-folder paths ($W/) outside code;
  - numbers with float noise (0.30000000000000004, 12.999999);
  - headings with nothing under them, and pages with almost no text;
  - duplicate element ids on a page.

    python tools/site_audit.py SITE_DIR [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

WORDS = re.compile(r"\b(None(?! (?:of|is|undoes|yet|needed|from|of)\b)(?=[\s.,;)|]|$)|nan|NaN|TODO|FIXME|Traceback|undefined)\b")
MARKUP = re.compile(r"\[\[[a-z]+:|\]\]|\{\{|\}\}|\]\((?:\.\./|https?:|[\w-]+\.md)")
PATHS = re.compile(r"/sessions/|/mnt/c/|[A-Z]:\\\\|/home/\w+")
WORK = re.compile(r"\$W/")
NOISE = re.compile(r"\b\d+\.\d*?(?:0{6,}[1-9]|9{6,}\d?)\b")
TABLE = re.compile(r"^\s*\|.*\|\s*$|\|---")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.imgs, self.ids, self.text, self.heads = [], [], [], [], []
        self.skip = 0          # inside script, style, code, pre, svg
        self.in_main = False
        self.cur_head = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag in ("script", "style", "code", "pre", "svg", "nav", "header", "footer"):
            self.skip += 1
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("img", "object") and (a.get("src") or a.get("data")):
            self.imgs.append(a.get("src") or a.get("data"))
        if tag == "article":
            self.in_main = True
        if self.in_main and tag in ("h2", "h3"):
            self.heads.append([tag, "", 0])
            self.cur_head = self.heads[-1]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "code", "pre", "svg", "nav", "header", "footer") and self.skip:
            self.skip -= 1
        if tag in ("h2", "h3"):
            self.cur_head = None
        if tag == "article":
            self.in_main = False

    def handle_data(self, data):
        if self.skip or not self.in_main:
            return
        if self.cur_head is not None:
            self.cur_head[1] += data
            return
        if data.strip() and self.heads:
            self.heads[-1][2] += len(data.strip())
        self.text.append(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--out")
    a = ap.parse_args()
    root = Path(a.site).resolve()
    pages = sorted(root.rglob("*.html"))
    parsed, ids = {}, {}
    for p in pages:
        pg = Page()
        pg.feed(p.read_text(encoding="utf-8", errors="replace"))
        parsed[p] = pg
        ids[p] = set(pg.ids)
    issues = defaultdict(list)
    for p, pg in parsed.items():
        rel = p.relative_to(root).as_posix()
        if rel.startswith("assets/") or rel == "404.html":
            continue
        for kind, refs in (("link", pg.links), ("image", pg.imgs)):
            for h in refs:
                u = urlparse(h)
                if u.scheme or h.startswith(("mailto:", "#")) and kind == "link" and not h[1:]:
                    continue
                if u.scheme:
                    continue
                target = p if not u.path else (p.parent / unquote(u.path)).resolve()
                if u.path and target.is_dir():
                    target = target / "index.html"
                if u.path and not target.exists():
                    issues["broken " + kind].append(f"{rel}: {h}")
                elif kind == "link" and u.fragment and target.suffix == ".html" and target in ids \
                        and unquote(u.fragment) not in ids[target]:
                    issues["missing anchor"].append(f"{rel}: {h}")
        text = " ".join(pg.text)
        for name, rx in (("unrendered markup", MARKUP), ("words", WORDS), ("machine path", PATHS),
                         ("float noise", NOISE)):
            for m in rx.finditer(text):
                s = text[max(0, m.start() - 50):m.end() + 40].replace("\n", " ")
                issues[name].append(f"{rel}: ...{s}...")
        n_work = len(WORK.findall(text))
        if n_work:
            issues["work-folder path in prose"].append(f"{rel}: {n_work}x")
        for line in text.splitlines():
            if TABLE.search(line):
                issues["markdown table syntax"].append(f"{rel}: {line.strip()[:120]}")
        for i, (tag, title, n) in enumerate(pg.heads):
            if tag != "h2":
                continue
            j = i + 1           # an h2 is empty only if neither it nor its h3s hold text
            while j < len(pg.heads) and pg.heads[j][0] == "h3":
                j += 1
            if n == 0 and all(h[2] == 0 for h in pg.heads[i + 1:j]):
                issues["empty section"].append(f"{rel}: {title.strip()[:80]}")
        if len(text.strip()) < 200:
            issues["near-empty page"].append(f"{rel}: {len(text.strip())} characters")
        dup = [i for i, c in Counter(pg.ids).items() if c > 1]
        if dup:
            issues["duplicate ids"].append(f"{rel}: {', '.join(dup[:5])}")
    summary = {k: len(v) for k, v in sorted(issues.items())}
    print(json.dumps({"pages": len(pages), "issues": summary}, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps({"pages": len(pages), "issues": summary, "detail": issues}, indent=1),
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
