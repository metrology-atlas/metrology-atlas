"""Provenance graph (metrology_atlas.graph): sources joined with run records."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from metrology_atlas import graph
from metrology_atlas import provenance as pv


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    code = tmp_path / "code" / "bench"
    code.mkdir(parents=True)
    (code / "scale.py").write_text(
        "import sys, json, pathlib\n"
        "src, out, k = sys.argv[1], pathlib.Path(sys.argv[2]), float(sys.argv[3])\n"
        "out.parent.mkdir(parents=True, exist_ok=True)\n"
        "x = json.loads(pathlib.Path(src).read_text())['x']\n"
        "out.write_text(json.dumps({'x': x * k, 'parts': [1.5, 2.25]}))\n")
    git(code, "init", "-q")
    git(code, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(code, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c")
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.setenv("METROLOGY_ATLAS_ROOTS", f"W={w};code={tmp_path / 'code'}")
    monkeypatch.setenv("METROLOGY_ATLAS_ROOTS_FILE", str(tmp_path / "none"))
    (w / "in.json").write_text('{"x": 2}')

    def run(src, out, k):
        o = w / out
        pv.main(["record", "--out", str(o.parent), "--", sys.executable, str(code / "scale.py"), str(w / src), str(o),
                 str(k)])
    run("in.json", "a/mid.json", 3)          # x = 6
    run("a/mid.json", "b/out.json", 10)      # x = 60
    return SimpleNamespace(w=w, code=code, run=run)


def ds(**params):
    items = {pid: {"status": "measured", **p} for pid, p in params.items()}
    return SimpleNamespace(items={"parameter": items})


def levels(d):
    f, _ = graph.check(d)
    return {(x.parameter, x.output): (x.level, x.reasons) for x in f}


def test_ok_and_value(setup):
    r = levels(ds(p={"value": 60, "sources": [{"output": "W:b/out.json", "key": "x"}]}))
    assert r[("p", "W:b/out.json")][0] == "ok"


def test_differs(setup):
    r = levels(ds(p={"value": 61, "sources": [{"output": "W:b/out.json", "key": "x"}]}))
    level, why = r[("p", "W:b/out.json")]
    assert level == "differs" and "parameter 61" in why[0]


def test_rounding_and_scale(setup):
    r = levels(ds(p={"value": 0.06, "sources": [{"output": "W:b/out.json", "key": "x", "scale": 0.001}]}))
    assert r[("p", "W:b/out.json")][0] == "ok"


def test_upstream_input_change_makes_it_stale(setup):
    (setup.w / "in.json").write_text('{"x": 5}')
    r = levels(ds(p={"value": 60, "sources": [{"output": "W:b/out.json", "key": "x"}]}))
    level, why = r[("p", "W:b/out.json")]
    assert level == "stale" and why[0].startswith("upstream W:a/mid.json: input W:in.json")


def test_code_change_makes_it_stale(setup):
    (setup.code / "scale.py").write_text((setup.code / "scale.py").read_text() + "# edit\n")
    level, why = levels(ds(p={"value": 60, "sources": [{"output": "W:b/out.json", "key": "x"}]}))[("p", "W:b/out.json")]
    assert level == "stale" and any(w.startswith("code changed") for w in why)


def test_output_overwritten_by_hand(setup):
    (setup.w / "b" / "out.json").write_text('{"x": 60}')
    level, why = levels(ds(p={"value": 60, "sources": [{"output": "W:b/out.json", "key": "x"}]}))[("p", "W:b/out.json")]
    assert level == "stale" and "output changed after run" in why[0]


def test_rerun_brings_it_back(setup):
    (setup.w / "in.json").write_text('{"x": 5}')
    setup.run("in.json", "a/mid.json", 3)
    setup.run("a/mid.json", "b/out.json", 10)
    r = levels(ds(p={"value": 150, "sources": [{"output": "W:b/out.json", "key": "x"}]}))
    assert r[("p", "W:b/out.json")][0] == "ok"


def test_untraced_missing_and_unsourced(setup):
    (setup.w / "hand.json").write_text('{"y": 1}')
    f, uns = graph.check(ds(p={"value": 1, "sources": [{"output": "W:hand.json", "key": "y"}]},
                            q={"value": 1, "sources": [{"output": "W:nowhere.json"}]},
                            r={"value": 1}, s={"value": 1, "status": "documented"}))
    got = {x.parameter: x.level for x in f}
    assert got == {"p": "untraced", "q": "missing"}
    assert uns == {"measured": ["r"], "documented": ["s"]}
    assert "no sources: 1 documented, 1 measured (1 measured or derived)" in graph.report(f, uns)


def test_sum_of_parts(setup):
    src = [{"output": "W:b/out.json", "key": "parts.0", "field": "sum"},
           {"output": "W:b/out.json", "key": "parts.1", "field": "sum"}]
    assert levels(ds(p={"value": 3.75, "sources": src}))[("p", "W:b/out.json")][0] == "ok"
    assert levels(ds(p={"value": 3.9, "sources": src}))[("p", "W:b/out.json")][0] == "differs"


def test_lookup_keys_with_dots_and_spaces():
    doc = {"loops": {"a + b.c": {"v": [1, {"p2.5": 7}]}}}
    assert graph.lookup(doc, "loops.a + b.c.v.1.p2.5") == 7
    with pytest.raises(KeyError):
        graph.lookup(doc, "loops.x")


def test_string_candidate_holds_the_number(setup):
    (setup.w / "b" / "best.json").write_text(json.dumps({"best": "rmean|8|15"}))
    f, _ = graph.check(ds(p={"value": 8, "sources": [{"output": "W:b/best.json", "key": "best"}]}))
    assert f[0].level == "untraced"           # agrees, but no record lists the hand-written file


def test_a_whole_root_as_input_is_not_compared(setup):
    import glob
    for f in glob.glob(str(setup.w / "b" / "_runs" / "*.json")):
        r = json.loads(open(f).read())
        r["inputs"].append({"path": "W:.", "kind": "folder", "files": 1, "bytes": 1})
        open(f, "w").write(json.dumps(r))
    (setup.w / "more.txt").write_text("new file in the work folder")
    assert levels(ds(p={"value": 60, "sources": [{"output": "W:b/out.json", "key": "x"}]}))[("p", "W:b/out.json")][0] == "ok"


def test_files_added_to_an_input_folder_after_the_run(setup):
    import os
    import time
    f = setup.w / "parts"
    f.mkdir()
    (f / "part_0.jsonl").write_text("1\n")
    old = time.time() - 100
    os.utime(f / "part_0.jsonl", (old, old))
    item = pv.describe(f)
    g = graph.Graph(pv.Roots.load())
    t0 = old + 10
    (f / "summary.json").write_text("{}")              # written after the run
    assert g.changed(item, t0) is None
    g = graph.Graph(pv.Roots.load())
    assert g.changed(item) == "content changed"         # without the run's start time it cannot tell
    (f / "part_0.jsonl").write_text("2\n")
    g = graph.Graph(pv.Roots.load())
    assert g.changed(item, t0) == "content changed"


def test_stale_findings_name_the_forms_that_use_the_parameter(setup):
    (setup.w / "in.json").write_text('{"x": 5}')
    d = ds(p={"value": 60, "sources": [{"output": "W:b/out.json", "key": "x"}]})
    d.links = {"v": [{"field": "timing[raw].bias_s.median", "parameter": "p"},
                     {"field": "timing[raw].u_s", "parameter": "q", "plus": {"parameter": "p", "scale": 0.5}}]}
    f, _ = graph.check(d)
    assert f[0].used_by == ["variable:v timing[raw].bias_s.median", "variable:v timing[raw].u_s"]
    assert "used by variable:v timing[raw].bias_s.median" in f[0].text()


def test_an_input_folder_holding_the_output_folder(setup, tmp_path):
    import os
    import time
    w = setup.w
    (w / "survey").mkdir()
    (w / "survey" / "a.txt").write_text("x")
    old = time.time() - 100
    os.utime(w / "survey" / "a.txt", (old, old))
    tool = setup.code / "summ.py"
    tool.write_text("import sys, pathlib\no = pathlib.Path(sys.argv[1]) / 'cont'\no.mkdir(exist_ok=True)\n"
                    "(o / 's.json').write_text('{\"v\": 1}')\n(o / 'extra.csv').write_text('1')\n")
    pv.main(["record", "--out", str(w / "survey" / "cont"), "--", sys.executable, str(tool), str(w / "survey")])
    tool.write_text(tool.read_text())                   # unchanged content
    f, _ = graph.check(ds(p={"value": 1, "sources": [{"output": "W:survey/cont/s.json", "key": "v"}]}))
    assert f[0].level == "ok", f[0].reasons


def test_a_broad_folder_with_narrower_declared_inputs(setup):
    w = setup.w
    (w / "survey" / "steps").mkdir(parents=True)
    (w / "survey" / "steps" / "s.txt").write_text("1")
    tool = setup.code / "count.py"
    tool.write_text("import sys, pathlib, json\no = pathlib.Path(sys.argv[2])\no.parent.mkdir(exist_ok=True)\n"
                    "o.write_text(json.dumps({'v': 1}))\n")
    pv.main(["record", "--out", str(w / "res"), "--input", str(w / "survey" / "steps"), "--", sys.executable, str(tool),
             str(w / "survey"), str(w / "res" / "c.json")])
    (w / "survey" / "unrelated.csv").write_text("a backup copied in later")
    f, _ = graph.check(ds(p={"value": 1, "sources": [{"output": "W:res/c.json", "key": "v"}]}))
    assert f[0].level == "ok", f[0].reasons
    (w / "survey" / "steps" / "s.txt").write_text("2")
    f, _ = graph.check(ds(p={"value": 1, "sources": [{"output": "W:res/c.json", "key": "v"}]}))
    assert f[0].level == "stale"
