"""Form numbers written once: a timing form or chain step takes a parameter's value (formlinks)."""

import copy
import datetime as dt

import pytest
from test_engine import _dataset
from test_timing import AS_STORED, _signal, _with_domains

from metrology_atlas import AtlasError, load, to_json
from metrology_atlas.timing import resolve

STUDY = {"id": "st", "name": "St", "summary": "S.", "status": "current", "methods": [], "date": dt.date(2026, 10, 1)}


def _param(id_, value, unit="s", **spread):
    return {f"parameters/{id_}.yaml": {"id": id_, "name": id_, "quantity": "Q.", "value": value, "unit": unit,
                                      "status": "measured", "study": "st", "about": [], "date": dt.date(2026, 11, 1),
                                      **({"spread": spread} if spread else {})}}


def _load(tmp_path, form, *params):
    files = {**_signal([form]), "studies/st.yaml": STUDY}
    for p in params:
        files.update(p)
    return load(_with_domains(_dataset(tmp_path, **files)))


def _form(**changes):
    f = copy.deepcopy(AS_STORED)
    f.update(changes)
    return f


def test_links_resolve_before_the_arithmetic(tmp_path):
    form = _form(bias_s={"median": {"parameter": "late"}, "p5": 3.4, "p95": 5.3, "n": 3652, "scope": "recording"},
                 support_s={"parameter": "span", "use": "p10-p90"},
                 uncertainty={"components": [{"name": "spread", "type": "A", "u_s": {"parameter": "spread-ms"},
                                              "scope": "recording", "distribution": "empirical"},
                                             {"name": "access", "type": "B", "u_s": {"parameter": "width",
                                              "rectangular": True}, "scope": "recording"}]})
    ds = _load(tmp_path, form, _param("late", 4.17), _param("span", 6.6, p10=4.9, p90=8.3),
               _param("spread-ms", 650, unit="ms"), _param("width", 53))
    f = ds.items["variable"]["s"]["timing"][0]
    assert f["bias_s"]["median"] == 4.17 and f["support_s"] == [4.9, 8.3]
    assert f["uncertainty"]["components"][0]["u_s"] == pytest.approx(0.65)
    assert f["uncertainty"]["components"][1]["u_s"] == pytest.approx(53 / 12 ** 0.5)
    assert resolve(f)["u_c"] == pytest.approx((0.65 ** 2 + 53 ** 2 / 12) ** 0.5)
    doc = to_json(ds)
    assert {l["field"] for l in doc["variables"]["s"]["derived"]["links"]} == {
        "timing[raw].bias_s.median", "timing[raw].support_s", "timing[raw].uncertainty.components[0].u_s",
        "timing[raw].uncertainty.components[1].u_s"}
    assert doc["parameters"]["late"]["derived"]["used_in_forms"] == ["variable:s"]


@pytest.mark.parametrize(("link", "params", "expect"), [
    ({"parameter": "nope"}, [], "does not exist"),
    ({"parameter": "rate"}, [_param("rate", 63, unit="ppm")], "is not a time"),
    ({"parameter": "late", "use": "p90"}, [_param("late", 4.17)], "has no p90"),
    ({"parameter": "late", "use": "mean"}, [_param("late", 4.17)], "'use' must be"),
])
def test_bad_links_are_refused(tmp_path, link, params, expect):
    form = _form(bias_s={"median": link, "p5": 3.4, "p95": 5.3, "n": 3652, "scope": "recording"})
    with pytest.raises(AtlasError, match=expect):
        _load(tmp_path, form, *params)


def test_scale_for_a_non_time_unit(tmp_path):
    form = _form(bias_s={"median": {"parameter": "frac", "scale": 10}, "p5": 3.4, "p95": 5.3, "scope": "recording"})
    assert _load(tmp_path, form, _param("frac", 0.42, unit="")).items["variable"]["s"]["timing"][0]["bias_s"]["median"] \
        == pytest.approx(4.2)


def test_typed_copy_in_a_form_warns(tmp_path):
    ds = _load(tmp_path, _form(studies=["st"]), _param("late", 4.2))
    assert any("bias_s.median = 4.2 is typed; parameter late" in w for w in ds.warnings)


def test_form_checked_before_its_parameters_warns(tmp_path):
    ds = _load(tmp_path, _form(studies=["st"], checked=dt.date(2026, 10, 15)), _param("other", 9.9))
    assert any("checked on 2026-10-15, before its studies' parameters other changed" in w for w in ds.warnings)
