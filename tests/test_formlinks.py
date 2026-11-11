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


def test_typed_ok_in_a_form(tmp_path):
    def run(path, entry):
        files = {**_signal([_form(studies=["st"])]), "studies/st.yaml": STUDY, **_param("late", 4.2)}
        files["variables/s.yaml"]["typed_ok"] = [entry]
        return load(_with_domains(_dataset(path, **files))).warnings
    w = run(tmp_path / "a", {"field": "timing[raw].bias_s.median", "parameter": "late", "why": "a different delay"})
    assert not any("is typed; parameter late" in x or "typed_ok" in x for x in w)
    w = run(tmp_path / "b", {"field": "timing[raw].bias_s.p5", "parameter": "late", "why": "stale"})
    assert any("bias_s.median = 4.2 is typed; parameter late" in x for x in w)
    assert any("typed_ok entry (timing[raw].bias_s.p5, late) matches no typed form number now" in x for x in w)


def test_form_checked_before_its_parameters_warns(tmp_path):
    ds = _load(tmp_path, _form(studies=["st"], checked=dt.date(2026, 10, 15)), _param("other", 9.9))
    assert any("checked on 2026-10-15, before its studies' parameters other changed" in w for w in ds.warnings)


def test_plus_adds_a_number_or_a_linked_share(tmp_path):
    form = _form(bias_s={"median": {"parameter": "late", "plus": {"parameter": "gap", "scale": 0.5}},
                         "p5": {"parameter": "late", "use": "p5", "plus": 1.0}, "p95": 5.3, "scope": "recording"},
                 support_s={"parameter": "span", "use": "p10-p90", "plus": 0.5})
    ds = _load(tmp_path, form, _param("late", 4.17, p5=3.55), _param("gap", 2.0), _param("span", 6.6, p10=4.9, p90=8.3))
    f = ds.items["variable"]["s"]["timing"][0]
    assert f["bias_s"]["median"] == pytest.approx(5.17) and f["bias_s"]["p5"] == pytest.approx(4.55)
    assert f["support_s"] == pytest.approx([5.4, 8.8])


def test_plus_must_be_one_number(tmp_path):
    form = _form(bias_s={"median": {"parameter": "late", "plus": {"parameter": "span", "use": "p10-p90"}},
                         "p5": 3.4, "p95": 5.3, "scope": "recording"})
    with pytest.raises(AtlasError, match="'plus' must be"):
        _load(tmp_path, form, _param("late", 4.17), _param("span", 6.6, p10=4.9, p90=8.3))


def test_a_count_links_and_a_typed_count_warns(tmp_path):
    form = _form(bias_s={"median": {"parameter": "late"}, "p5": 3.4, "p95": 5.3, "n": {"parameter": "late", "use": "n"},
                         "scope": "recording"}, studies=["st"])
    ds = _load(tmp_path, form, _param("late", 4.17, n=3758))
    assert ds.items["variable"]["s"]["timing"][0]["bias_s"]["n"] == 3758
    assert not [w for w in ds.warnings if "(n) holds it" in w]
    typed = _form(bias_s={"median": 4.0, "p5": 3.4, "p95": 5.3, "n": 3758, "scope": "recording"}, studies=["st"])
    ds = _load(tmp_path / "b", typed, _param("late", 4.17, n=3758))
    assert any("bias_s.n = 3758 is typed; parameter late (n) holds it" in w for w in ds.warnings)


def test_a_link_inside_a_yaml_anchor_resolves_in_every_form(tmp_path):
    shared = {"median": {"parameter": "late"}, "p5": 3.4, "p95": 5.3, "scope": "recording"}
    a = _form(bias_s=shared)
    b = _form(id="raw2", name="Raw 2", default=False, bias_s=shared)
    files = {**_signal([a, b]), "studies/st.yaml": STUDY, **_param("late", 4.17)}
    ds = load(_with_domains(_dataset(tmp_path, **files)))
    assert [f["bias_s"]["median"] for f in ds.items["variable"]["s"]["timing"]] == [4.17, 4.17]
    assert {l["field"] for l in ds.links["s"]} == {"timing[raw].bias_s.median", "timing[raw2].bias_s.median"}
