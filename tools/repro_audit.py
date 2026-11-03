"""Can each study be reproduced from public code? An audit of the atlas's code lists and figure sources.

    python tools/repro_audit.py datasets/vitaldb [--json out.json]

Per study: each entry of its `code` list resolved to a software item (software/*.yaml) and a path in that
software's local checkout; whether the software is public, the path exists, and it is committed (git ls-files).
Each figure's `source`: a script in a public repository, or ad hoc / the unpublished analysis workspace. Each
listed Python script (a file under tools/, scripts/ or examples/): whether its docstring gives a command to run it
("python " or "bash "). Library modules and tests are not run on their own: a study listing them needs an entry
point, either a listed script with a command or a command in the study's own text ("python ", "pytest" or "bash ");
studies without one are reported.
Categories: ok (all code public, present and committed; figures from public scripts); no-code (no code list);
unpublished (code or a figure from the analysis workspace or ad hoc); missing (a listed path is absent or not
committed). This checks the code is there, not that rerunning it gives the numbers: that is reproduce.py's job.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrology_atlas.load import load  # noqa: E402


def tracked(repo: Path, rel: str) -> bool:
    r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), "ls-files", "--error-unmatch", rel],
                       capture_output=True, text=True)
    return r.returncode == 0


SCRIPT_DIRS = {"tools", "scripts", "examples"}


def is_script(path: str) -> bool:
    return bool(SCRIPT_DIRS & set(Path(path).parts[:-1]))


def documented(p: Path) -> bool | None:
    if p.suffix != ".py" or not p.is_file():
        return None
    try:
        d = ast.get_docstring(ast.parse(p.read_text(encoding="utf-8", errors="replace"))) or ""
    except SyntaxError:
        return False
    return "python " in d or "bash " in d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset"); ap.add_argument("--json")
    a = ap.parse_args()
    root = Path(a.dataset).resolve()
    ds = load(root)
    soft = ds.items["software"]
    rows = []
    for sid, st in sorted(ds.items["study"].items()):
        code = st.get("code") or []
        issues, ok_paths, undocumented, library, scripts_ok = [], 0, [], [], 0
        for c in code:
            sw, _, path = c.partition("/")
            s = soft.get(sw)
            if s is None:
                issues.append(f"unknown software {sw}"); continue
            if s.get("visibility") != "public":
                issues.append(f"unpublished: {c}"); continue
            if not path:
                ok_paths += 1; continue
            if not s.get("local"):
                ok_paths += 1; continue  # e.g. a PyPI package: not checkable here
            repo = (root / "software" / s["local"]).resolve() if not Path(s["local"]).is_absolute() else Path(s["local"])
            repo = (root / s["local"]).resolve() if not repo.exists() else repo
            p = repo / path
            if not p.exists():
                issues.append(f"missing: {c}"); continue
            if not tracked(repo, path):
                issues.append(f"not committed: {c}"); continue
            ok_paths += 1
            if not is_script(path):
                library.append(c)
            elif documented(p) is False:
                undocumented.append(c)
            elif documented(p):
                scripts_ok += 1
        figs = []
        for f in st.get("figures") or []:
            src = str(f.get("source") or "")
            if not src or "ad hoc" in src or "analysis-workspace" in src or "workspace" in src:
                figs.append(f"{f.get('id')}: {src or 'no source'}")
        if not code:
            cat = "no-code"
        elif any(i.startswith(("missing", "not committed", "unknown")) for i in issues):
            cat = "missing"
        elif issues or figs:
            cat = "unpublished"
        else:
            cat = "ok"
        rows.append({"study": sid, "status": st.get("status"), "category": cat, "code": len(code), "issues": issues,
                     "figures_not_from_public_scripts": figs, "scripts_without_a_run_command": undocumented,
                     "library_without_entry_point": library if library and not scripts_ok and not any(
                         k in json.dumps(st, ensure_ascii=False, default=str) for k in ("python ", "pytest", "bash ")) else []})
    from collections import Counter
    print("by category:", dict(Counter(r["category"] for r in rows)))
    print("by status x category:", dict(Counter((r["status"], r["category"]) for r in rows)))
    for cat in ("missing", "unpublished", "no-code"):
        print(f"\n== {cat}")
        for r in rows:
            if r["category"] == cat:
                print(f"  {r['study']} ({r['status']}): " + "; ".join(r["issues"] + r["figures_not_from_public_scripts"]))
    nd = [(r["study"], c) for r in rows for c in r["scripts_without_a_run_command"]]
    print(f"\nscripts without a run command in their docstring: {len(nd)}")
    for sid, c in nd:
        print(f"  {sid}: {c}")
    ne = [(r["study"], r["library_without_entry_point"]) for r in rows if r["library_without_entry_point"]]
    print(f"\nstudies listing library code with no entry point (no documented script, no command): {len(ne)}")
    for sid, c in ne:
        print(f"  {sid}: {', '.join(c)}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
