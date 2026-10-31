"""Propagation along links between variables (schema 0.4): the time floor and the GUM law of propagation."""

import math

import pytest
import yaml

from metrology_atlas import AtlasError, load, to_json
from metrology_atlas.propagate import FormulaError, compile_formula, law, time_conflicts, time_floor
from test_engine import _dataset


def _v(id_, **extra):
    return {f"variables/{id_}.yaml": {"id": id_, "name": id_.upper(), "summary": "S.", "type": "numeric", **extra}}


def _derived(id_, inputs, formula=None, **extra):
    value = {"formula": formula} if formula else {}
    return _v(id_, origin="derived", value=value, **extra,
              derived_from=[{"variable": i, "relation": "computed-from"} for i in inputs])


def _form(id_, support, bias=0.0, uses_future=False, kind="as_stored"):
    f = {"id": id_, "name": id_, "kind": kind, "support_s": support, "stamp_position": "close",
         "uncertainty": {"components": [{"name": "g", "type": "B", "u_s": 0.01, "scope": "independent"}]},
         "domain": "d", "status": "measured", "evidence": "E."}
    if kind == "as_stored":
        f["bias_s"] = {"value": bias}
    else:
        f |= {"removes_bias_s": {"value": bias}, "uses_future": uses_future,
              "uncertainty": {**f["uncertainty"], "upper_bound": True}}
    return f


def _with_domain(d):
    meta = yaml.safe_load((d / "dataset.yaml").read_text())
    meta["domains"] = [{"id": "d", "name": "D"}]
    (d / "dataset.yaml").write_text(yaml.safe_dump(meta))
    return d


@pytest.mark.parametrize("bad", ["__import__('os')", "a.real", "open(a)", "a + zz", "a +"])
def test_formula_is_checked(bad):
    with pytest.raises(FormulaError):
        compile_formula(bad, {"a"})


def test_difference_of_two_day_dates_is_triangular(tmp_path):
    ds = load(_dataset(tmp_path, **_v("adm", value={"step": 86400}), **_v("dis", value={"step": 86400}),
                       **_derived("los", ["adm", "dis"], "(dis - adm) / 86400", propagation={"method": "law"})))
    r = law(ds, "los")
    assert r["linear"] and math.isclose(r["u"], 1 / math.sqrt(6), rel_tol=1e-6)   # triangular over n ± 1 day
    assert [round(t["share"], 6) for t in r["terms"]] == [0.5, 0.5]


def test_shared_component_cancels_in_a_difference(tmp_path):
    comp = lambda u, shared: {"name": "cal", "type": "B", "u_s": u, "scope": "shared", "shared_with": shared}
    ds = load(_dataset(tmp_path,
                       **_v("a", value={"uncertainty": {"components": [comp(0.3, "one-transducer")]}}),
                       **_v("b", value={"uncertainty": {"components": [comp(0.4, "one-transducer")]}}),
                       **_v("c", value={"uncertainty": {"components": [comp(0.4, "another")]}}),
                       **_derived("ab", ["a", "b"], "a - b", propagation={"method": "law"}),
                       **_derived("ac", ["a", "c"], "a - c", propagation={"method": "law"})))
    assert math.isclose(law(ds, "ab")["u"], 0.1, rel_tol=1e-6)       # sqrt(0.09 + 0.16 - 2 * 0.12)
    assert math.isclose(law(ds, "ac")["u"], 0.5, rel_tol=1e-6)       # independent
    assert law(ds, "ab")["shared"][0]["shared_with"] == "one-transducer"


def test_nonlinear_needs_a_point(tmp_path):
    files = {**_v("w", value={"step": 1, "bias": {"value": 0.5}}), **_v("h", value={"step": 0.01})}
    with pytest.raises(AtlasError, match="not linear"):
        load(_dataset(tmp_path, **files, **_derived("bmi", ["w", "h"], "w / h ** 2", propagation={"method": "law"})))
    ds = load(_dataset(tmp_path / "2", **files, **_derived("bmi", ["w", "h"], "w / h ** 2", propagation={
        "method": "law", "at": [{"symbol": "w", "value": 70}, {"symbol": "h", "value": 1.75}]})))
    r = law(ds, "bmi")
    rel = math.sqrt((1 / math.sqrt(12) / 70) ** 2 + (2 * 0.01 / math.sqrt(12) / 1.75) ** 2)
    assert math.isclose(r["u"], rel * 70 / 1.75 ** 2, rel_tol=1e-5)
    assert math.isclose(r["bias"], 0.5 / 1.75 ** 2, rel_tol=1e-5)    # biases propagate by the same coefficients


def test_law_needs_input_uncertainty(tmp_path):
    with pytest.raises(AtlasError, match="no value uncertainty to propagate"):
        load(_dataset(tmp_path, **_v("a"), **_v("b", value={"step": 1}),
                      **_derived("ab", ["a", "b"], "a + b", propagation={"method": "law"})))


def test_time_floor_and_conflicts(tmp_path):
    d = _with_domain(_dataset(tmp_path,
        **_v("x", timing=[_form("raw", [2, 2], bias=1.5)]),
        **_v("y", timing=[_form("fit", [0, 0], bias=0.2, kind="per_recording", uses_future=True)]),
        **_derived("mid", ["x"]),                                     # no forms of its own: passes the floor on
        **_derived("z", ["mid", "y"], timing=[_form("own", [1, 1], bias=0.0)])))
    ds = load(d)
    f = time_floor(ds, "z")
    assert f["support_min_s"] == 2 and f["input_latency_s"] == 1.5 and f["uses_future"]
    msgs = time_conflicts(ds, "z")
    assert any("shorter than an input's" in m for m in msgs)
    assert any("availability rule" in m for m in msgs)               # needs at least 1.5 - 1 = 0.5 s
    assert any("uses_future" in m for m in msgs)
    assert any("availability rule" in w for w in ds.warnings)        # warnings in 0.4, not errors
    assert to_json(ds)["variables"]["z"]["derived"]["propagated"]["time"]["support_min_s"] == 2


def test_unstated_inputs_are_listed(tmp_path):
    ds = load(_dataset(tmp_path, **_v("a"), **_derived("b", ["a"])))
    assert time_floor(ds, "b")["unstated"] == ["a"]
