"""Timing forms in bias-and-uncertainty terms (framework spec of 28 Oct 2026): resolution, checks, planner, pages."""

import json
import math

import pytest
import yaml
from test_engine import _dataset

from metrology_atlas import AtlasError, load, write_site
from metrology_atlas.timing import resolve

DOMAINS = [{"id": "ref", "name": "Reference"}, {"id": "dev", "name": "Device clock"}]


def _with_domains(d):
    meta = yaml.safe_load((d / "dataset.yaml").read_text())
    meta["domains"] = DOMAINS
    (d / "dataset.yaml").write_text(yaml.safe_dump(meta))
    return d


def _signal(timing):
    return {"devices/dev.yaml": {"id": "dev", "name": "Dev", "summary": "S.", "type": "other"},
            "variables/s.yaml": {"id": "s", "name": "Sig", "summary": "S.", "type": "numeric", "device": "dev",
                                 "stamp_clock": "a", "timing": timing}}


AS_STORED = {"id": "raw", "name": "as stored", "kind": "as_stored", "support_s": [6, 8], "stamp_position": "close",
             "bias_s": {"median": 4.2, "p5": 3.4, "p95": 5.3, "n": 3652, "scope": "recording"},
             "uncertainty": {"components": [{"name": "spread of the delay", "type": "A", "u_s": 0.65,
                                             "scope": "recording", "distribution": "empirical"}]},
             "domain": "dev", "status": "measured", "evidence": "E."}
FIXED = {"id": "fix", "name": "release median", "kind": "fixed_shift", "support_s": [6, 8], "stamp_position": "close",
         "removes_bias_s": {"median": 4.2, "p5": 3.4, "p95": 5.3}, "corrects": ["raw"], "correction": "release median",
         "uncertainty": {"upper_bound": False, "components": [
             {"name": "spread of the delay", "type": "A", "u_s": 0.65, "scope": "recording"}]},
         "domain": "dev", "status": "measured", "evidence": "E."}
LABEL = {"id": "lab", "name": "per-case label", "kind": "per_recording", "default": True, "uses_future": True,
         "support_s": [6, 8], "stamp_position": "close", "removes_bias_s": {"median": 4.2, "p5": 1.05, "p95": 5.25},
         "corrects": ["raw"], "correction": "per-case label",
         "uncertainty": {"upper_bound": True, "interval95_s": [-0.9, 0.9], "likely_u_s": 0.2, "components": [
             {"name": "label", "type": "A", "u_s": 0.3, "scope": "recording"},
             {"name": "drift left", "type": "A", "u_s": 0.4, "scope": "structured", "length_s": 8192},
             {"name": "poll grid", "type": "B", "u_s": 0.58, "scope": "independent", "included_in": "label"}]},
         "domain": "ref", "status": "measured", "evidence": "E."}


def test_current_forms_resolve():
    raw, fix, lab = resolve(AS_STORED), resolve(FIXED), resolve(LABEL)
    assert raw["kind"] == "as_stored" and raw["shift_s"] == 0 and raw["bias"]["mid"] == 4.2
    assert fix["shift_s"] == 4.2 and fix["bias"]["mid"] == 0 and not fix["uses_future"]
    assert lab["shift_s"] is None and lab["bias"]["mid"] == 0 and lab["uses_future"]          # D5: no shift
    assert lab["u_c"] == pytest.approx(0.5)                     # 0.3 and 0.4; the grid is already in the label
    assert lab["upper_bound"] and lab["likely_u"] == 0.2 and lab["interval95"] == [-0.9, 0.9]   # D3
    assert lab["latency_s"] == pytest.approx(5.25)              # the data still arrived that late


def test_retired_fields_are_refused(tmp_path):
    form = {**AS_STORED, "delay_s": [0, 1]}
    with pytest.raises(AtlasError) as err:
        load(_with_domains(_dataset(tmp_path, **_signal([form]))))
    assert any("retired in schema 0.3" in p for p in err.value.problems), err.value.problems


def test_early_stamps_add_no_latency():
    f = resolve({**LABEL, "removes_bias_s": {"median": -0.8, "p5": -0.97, "p95": -0.6}})
    assert f["latency_s"] == 0


@pytest.mark.parametrize(("form", "expect"), [
    ({**LABEL, "bias_s": {"value": 0.1}}, "a bias left after the correction needs a name"),
    ({k: v for k, v in LABEL.items() if k != "uses_future"}, "uses data after the stamp"),
    ({**LABEL, "uncertainty": {"upper_bound": True, "components": [
        {"name": "d", "type": "A", "u_s": 0.4, "scope": "structured"}]}}, "correlation length"),
    ({**LABEL, "uncertainty": {"components": [{"name": "d", "type": "A", "u_s": 0.4, "scope": "recording"}]}},
     "upper bound (D3)"),
    ({**AS_STORED, "bias_s": {"median": 0.1, "p5": -0.2, "p95": 0.3}}, "mark 'look_ahead'"),
    ({**AS_STORED, "stamp_position": "open", "bias_s": None}, "needs a bias giving its displacement"),
    ({k: v for k, v in AS_STORED.items() if k != "support_s"}, "'support_s' is required"),
    ({**FIXED, "uses_future": True}, "cannot use future data"),
    ({**LABEL, "uncertainty": {"upper_bound": True, "components": [
        {"name": "g", "type": "B", "u_s": 0.1, "scope": "independent", "included_in": "nope"}]}}, "included_in 'nope'"),
])
def test_rejects_forms(tmp_path, form, expect):
    form = {k: v for k, v in form.items() if v is not None}
    with pytest.raises(AtlasError) as err:
        load(_with_domains(_dataset(tmp_path, **_signal([form]))))
    assert any(expect in p for p in err.value.problems), err.value.problems


def test_planner_and_pages(tmp_path):
    raw = {**AS_STORED}
    d = _with_domains(_dataset(tmp_path, **_signal([raw, FIXED, LABEL])))
    ds = load(d)
    out = write_site(ds, tmp_path / "site")
    page = (out / "docs" / "variables" / "s.md").read_text()
    assert "Uncertainty budget, per-case label" in page and "≤ " in page and "drift left" in page
    planner = (out / "docs" / "planner.md").read_text()
    data = json.loads(planner.split("const ATLAS_PLANNER = ", 1)[1].split(";\n", 1)[0])
    fs = {f["id"]: f for f in data["signals"][0]["forms"]}
    assert fs["lab"]["shift"] is None and fs["lab"]["uses_future"] and fs["lab"]["u_c"] == pytest.approx(0.5)
    assert fs["fix"]["shift"] == 4.2 and not fs["fix"]["uses_future"]
    assert fs["raw"]["bias"]["mid"] == 4.2 and fs["raw"]["shift"] == 0
    assert "Real-time use" in planner


def test_shared_errors_cancel_in_the_planner(tmp_path):
    a = {**LABEL, "corrects": [], "uncertainty": {"upper_bound": True, "components": [
        {"name": "clock", "type": "A", "u_s": 0.3, "scope": "recording", "shared_with": "one clock"},
        {"name": "own", "type": "A", "u_s": 0.4, "scope": "independent"}]}}
    files = _signal([a])
    files["variables/t.yaml"] = {**files["variables/s.yaml"], "id": "t", "name": "Other"}
    ds = load(_with_domains(_dataset(tmp_path, **files)))
    out = write_site(ds, tmp_path / "site")
    planner = (out / "docs" / "planner.md").read_text()
    data = json.loads(planner.split("const ATLAS_PLANNER = ", 1)[1].split(";\n", 1)[0])
    assert all(s["forms"][0]["shared"] == {"one clock": 0.3} for s in data["signals"])
    assert "Shared errors" in (out / "docs" / "time.md").read_text()


def test_correlation_shapes():
    from metrology_atlas.timing import correlation
    base = {"scope": "structured", "length_s": 100.0}
    assert correlation({**base, "correlation": "rectangular"}, 50) == 1 and correlation({**base, "correlation": "rectangular"}, 150) == 0
    assert correlation({**base, "correlation": "triangular"}, 25) == pytest.approx(0.75)
    assert correlation(base, 100) == pytest.approx(math.exp(-1))            # exponential by default
    assert correlation({"scope": "recording"}, 1e6) == 1 and correlation({"scope": "independent"}, 1) == 0


def test_accuracy_with_a_number_is_refused(tmp_path):
    files = {"clocks/c.yaml": {"id": "c", "name": "C", "summary": "Its accuracy is 5 ms.", "type": "oscillator"}}
    with pytest.raises(AtlasError) as err:
        load(_dataset(tmp_path, **files))
    assert any("'accuracy' with a number" in p for p in err.value.problems), err.value.problems
