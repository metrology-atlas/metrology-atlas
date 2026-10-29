"""Timing forms in bias-and-uncertainty terms (framework spec of 28 Oct 2026): resolution, checks, planner, pages."""

import json
import math

import pytest
import yaml
from test_engine import _dataset

from metrology_atlas import AtlasError, load, write_site
from metrology_atlas.timing import SQ12, forms, resolve

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


def test_legacy_forms_keep_their_numbers_without_the_wrong_shift():
    raw = {"id": "r", "name": "raw", "delay_s": [0.53, 1.05], "interval_s": [0.0078, 0.0078], "domain": "x",
           "status": "measured", "evidence": "E.", "default": True}
    sync = {"id": "y", "name": "sync", "delay_s": [0.017, 0.042], "interval_s": [0.0078, 0.0078],
            "corrected_delay_s": [0.53, 1.05], "domain": "x", "status": "measured", "evidence": "E.", "corrects": ["r"]}
    r, y = resolve(raw), resolve(sync)
    assert r["legacy"] and r["kind"] == "as_stored" and r["bias"]["mid"] == pytest.approx(0.79)
    assert r["u_c"] == pytest.approx(math.hypot(0.52 / SQ12, 0.0078 / SQ12))
    assert y["kind"] == "per_recording" and y["shift_s"] is None and y["bias"]["mid"] == 0
    # a signal with only a raw default gains a named fixed shift, which becomes the default
    fs = forms({"timing": [raw]})
    assert [f["id"] for f in fs] == ["r", "r-shift"] and fs[1]["default"] and not fs[0]["default"]
    assert fs[1]["shift_s"] == pytest.approx(0.79) and fs[1]["kind"] == "fixed_shift"
    # with a correction present, the default stays where it was
    assert next(f for f in forms({"timing": [dict(raw, default=False), dict(sync, default=True)]}) if f["default"])["id"] == "y"


@pytest.mark.parametrize(("form", "expect"), [
    ({**LABEL, "bias_s": {"value": 0.1}}, "a bias left after the correction needs a name"),
    ({k: v for k, v in LABEL.items() if k != "uses_future"}, "uses data after the stamp"),
    ({**LABEL, "uncertainty": {"upper_bound": True, "components": [
        {"name": "d", "type": "A", "u_s": 0.4, "scope": "structured"}]}}, "correlation length"),
    ({**LABEL, "uncertainty": {"components": [{"name": "d", "type": "A", "u_s": 0.4, "scope": "recording"}]}},
     "upper bound (D3)"),
    ({**AS_STORED, "bias_s": {"median": 0.1, "p5": -0.2, "p95": 0.3}}, "mark 'look_ahead'"),
    ({**AS_STORED, "stamp_position": "open", "bias_s": None}, "needs a bias giving its displacement"),
    ({**AS_STORED, "delay_s": [0, 1]}, "mixes legacy fields"),
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
