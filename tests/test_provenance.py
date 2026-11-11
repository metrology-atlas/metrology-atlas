"""Run records (metrology_atlas.provenance)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from metrology_atlas import provenance as pv


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "code" / "bench"
    (r / "tools").mkdir(parents=True)
    tool = r / "tools" / "double.py"
    tool.write_text(
        "import sys, json, pathlib\n"
        "src, out = sys.argv[1], pathlib.Path(sys.argv[2])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "x = json.loads(pathlib.Path(src).read_text())\n"
        "(out / 'summary.json').write_text(json.dumps({'y': 2 * x['x']}))\n"
        "sys.exit(int(x.get('fail', 0)))\n")
    git(r, "init", "-q")
    git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "tool")
    return r


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.setenv("METROLOGY_ATLAS_ROOTS", f"W={w};code={tmp_path / 'code'}")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    return w


def records(out):
    return [json.loads(p.read_text()) for p in sorted((out / "_runs").glob("run_*.json"))]


def test_record_wraps_a_command(repo, work):
    inp = work / "in.json"
    inp.write_text('{"x": 21}')
    out = work / "res"
    code = pv.main(["record", "--out", str(out), "--", sys.executable, str(repo / "tools" / "double.py"),
                    str(inp), str(out)])
    assert code == 0
    assert json.loads((out / "summary.json").read_text()) == {"y": 42}
    [r] = records(out)
    assert r["kind"] == "recorded" and r["exit_code"] == 0 and r["finished"]
    assert r["script"]["path"] == "code:bench/tools/double.py"
    assert r["script"]["git"]["dirty"] is False and len(r["script"]["git"]["commit"]) == 40
    [i] = r["inputs"]                       # the output folder is not an input
    assert i["path"] == "W:in.json" and i["sha256"] == pv.sha256(inp)
    [o] = r["outputs"]
    assert o["path"] == "W:res/summary.json" and o["sha256"] == pv.sha256(out / "summary.json")


def test_exit_code_passed_on_and_recorded(repo, work):
    inp = work / "in.json"
    inp.write_text('{"x": 1, "fail": 3}')
    out = work / "res"
    assert pv.main(["record", "--out", str(out), "--", sys.executable, str(repo / "tools" / "double.py"),
                    str(inp), str(out)]) == 3
    assert records(out)[0]["exit_code"] == 3


def test_changed_script_is_flagged(repo, work):
    (repo / "tools" / "double.py").write_text((repo / "tools" / "double.py").read_text() + "\n# edit\n")
    inp = work / "in.json"
    inp.write_text('{"x": 1}')
    out = work / "res"
    pv.main(["record", "--out", str(out), "--", sys.executable, str(repo / "tools" / "double.py"), str(inp), str(out)])
    g = records(out)[0]["script"]["git"]
    assert g["dirty"] and g["file_changed"]


def test_resume_adds_a_record(repo, work):
    inp = work / "in.json"
    inp.write_text('{"x": 1}')
    out = work / "res"
    for _ in range(2):
        pv.main(["record", "--out", str(out), "--", sys.executable, str(repo / "tools" / "double.py"),
                 str(inp), str(out)])
    assert len(records(out)) == 2


def test_folder_tree_hash_and_fingerprint(work):
    f = work / "parts"
    f.mkdir()
    for i in range(3):
        (f / f"part_{i}.jsonl").write_text(f"{i}\n")
    d = pv.describe(f)
    assert d["kind"] == "folder" and d["files"] == 3 and "tree_sha256" in d
    (f / "part_0.jsonl").write_text("changed\n")
    assert pv.describe(f)["tree_sha256"] != d["tree_sha256"]
    big = pv.describe(f, tree_limit=2)
    assert "tree_sha256" not in big and big["files"] == 3 and "mtime_newest" in big
    large = pv.describe(f / "part_1.jsonl", hash_limit=1)
    assert "sha256" not in large and "mtime" in large


def test_option_value_and_declared_inputs(work):
    a, b = work / "rates.json", work / "fixed.json"
    a.write_text("{}")
    b.write_text("[]")
    out = work / "res"
    out.mkdir()
    rec = pv.new_record(out, ["python", "x.py", f"--step-rates={a}", "--cases", "1,2"], None, "recorded",
                        extra=[str(b)], program=True)
    paths = {i["path"]: i for i in rec["inputs"]}
    assert set(paths) == {"W:rates.json", "W:fixed.json"} and paths["W:fixed.json"]["declared"]


def test_flag_is_kept(work):
    a = work / "units.csv"
    a.write_text("case\n")
    out = work / "res"
    out.mkdir()
    [i] = pv.inputs_of(["x.py", "--units", str(a)], out, None)
    assert i["flag"] == "--units"


def test_begin_end_for_a_driver(repo, work):
    out = work / "scan"
    rates = work / "rates.json"
    rates.write_text("{}")
    path = None
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pv.main(["begin", "--out", str(out), "--script", str(repo / "tools" / "double.py"), "--",
                 "--step-rates", str(rates)])
    path = Path(buf.getvalue().strip())
    (out / "part_0.jsonl").write_text("{}\n")
    (out / "_runs_warnings.txt").write_text("")
    pv.main(["end", str(path), "--exit-code", "0"])
    [r] = records(out)
    assert r["exit_code"] == 0 and [o["path"] for o in r["outputs"]] == ["W:scan/part_0.jsonl"]
    assert r["inputs"][0]["flag"] == "--step-rates"


def test_reconstructed_needs_a_note(work):
    out = work / "old"
    out.mkdir()
    (out / "summary.json").write_text("{}")
    with pytest.raises(SystemExit):
        pv.main(["reconstructed", "--out", str(out), "--", "python", "x.py"])
    pv.main(["reconstructed", "--out", str(out), "--note", "runbook 9 Nov, 3a", "--", "python", "x.py"])
    [r] = records(out)
    assert r["kind"] == "reconstructed" and r["started"] is None and r["note"]
    assert [o["path"] for o in r["outputs"]] == ["W:old/summary.json"]


def test_runs_as_a_file_without_the_package(repo, work, tmp_path):
    inp = work / "in.json"
    inp.write_text('{"x": 2}')
    out = work / "res"
    mod = Path(pv.__file__)
    r = subprocess.run([sys.executable, "-I", str(mod), "record", "--out", str(out), "--", sys.executable,
                        str(repo / "tools" / "double.py"), str(inp), str(out)], capture_output=True, text=True,
                       cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert records(out)[0]["outputs"][0]["path"] == "W:res/summary.json"


def test_unreadable_files_do_not_stop_the_run(repo, work, monkeypatch):
    f = work / "parts"
    f.mkdir()
    (f / "a.jsonl").write_text("1\n")
    (f / "b.jsonl").write_text("2\n")
    real = Path.stat

    def stat(self, *a, **k):
        if self.name == "b.jsonl":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "stat", stat)
    d = pv.describe(f)
    assert d["files"] == 1 and d["unreadable"] == 1 and "tree_sha256" not in d


def test_recorder_failure_still_runs_the_command(repo, work, monkeypatch):
    inp = work / "in.json"
    inp.write_text('{"x": 5}')
    out = work / "res"

    def boom(*a, **k):
        raise RuntimeError("broken")
    monkeypatch.setattr(pv, "new_record", boom)
    code = pv.main(["record", "--out", str(out), "--", sys.executable, str(repo / "tools" / "double.py"),
                    str(inp), str(out)])
    assert code == 0 and json.loads((out / "summary.json").read_text()) == {"y": 10}
    [r] = records(out)
    assert "broken" in r["record_error"] and r["exit_code"] == 0


def test_roots_file_and_aliases(tmp_path, monkeypatch):
    w = tmp_path / "work"
    (w / "res").mkdir(parents=True)
    f = tmp_path / "cfg" / "roots"
    f.parent.mkdir()
    f.write_text("# local first, then where other machines mount it\nW = ../work\nW=/mnt/c/vitalDB/work\n")
    monkeypatch.delenv("METROLOGY_ATLAS_ROOTS", raising=False)
    monkeypatch.setenv("METROLOGY_ATLAS_ROOTS_FILE", str(f))
    R = pv.Roots.load()
    assert R.local("W") == w
    assert pv.portable(w / "res" / "x.json") == "W:res/x.json"
    assert R.portable(Path("/mnt/c/vitalDB/work/res/x.json"), resolve=False) == "W:res/x.json"
    assert R.resolve("W:res/x.json") == w / "res" / "x.json"
    assert R.resolve("Q:x") is None


def test_env_roots_come_first(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    f = tmp_path / "roots"
    f.write_text(f"W={b}\n")
    monkeypatch.setenv("METROLOGY_ATLAS_ROOTS_FILE", str(f))
    monkeypatch.setenv("METROLOGY_ATLAS_ROOTS", f"W={a}")
    assert pv.Roots.load().local("W") == a


def test_a_root_given_as_input_is_not_read(repo, work):
    inp = work / "in.json"
    inp.write_text('{"x": 4}')
    out = work / "res"
    pv.main(["record", "--out", str(out), "--input", str(inp), "--", sys.executable, str(repo / "tools" / "double.py"),
             str(inp), str(out), "--work", str(work)])
    rec = records(out)[0]
    root = [i for i in rec["inputs"] if i.get("kind") == "root"]
    assert root == [{"path": "W:", "kind": "root", "arg_index": 5, "flag": "--work"}]


def test_a_declared_input_inside_the_output_folder_is_read(repo, work):
    out = work / "res"
    (out / "parts").mkdir(parents=True)
    (out / "parts" / "p0.csv").write_text("1\n")
    pv.main(["record", "--out", str(out), "--input", str(out / "parts"), "--", sys.executable, "-c", "pass"])
    [i] = records(out)[0]["inputs"]
    assert i["path"] == "W:res/parts" and i["files"] == 1 and "tree_sha256" in i
