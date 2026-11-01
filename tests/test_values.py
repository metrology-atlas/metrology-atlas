"""Numbers written once: [[value:parameter-id]] in prose shows the parameter's value."""

import datetime as dt

import pytest

from metrology_atlas import AtlasError, load, to_json
from metrology_atlas.site import write_site
from metrology_atlas.values import typed_copies, value_text
from test_engine import _dataset

STUDY = {"id": "st", "name": "St", "summary": "S.", "status": "current", "methods": [], "date": dt.date(2026, 10, 1)}
PARAM = {"id": "na-diff", "name": "Na difference", "quantity": "Sodium, blood gas minus central", "value": -3.0, "unit": "mmol/L",
         "status": "measured", "study": "st", "about": []}


def _files(results):
    return {"studies/st.yaml": {**STUDY, "results": results}, "parameters/na-diff.yaml": PARAM}


def test_value_renders_and_derives(tmp_path):
    d = _dataset(tmp_path, **_files("Sodium reads [[value:na-diff]] lower."))
    ds = load(d)
    doc = to_json(ds)
    assert doc["studies"]["st"]["derived"]["values"] == {"na-diff": "−3.0 mmol/L"}
    assert doc["parameters"]["na-diff"]["derived"]["quoted_in"] == ["study:st"]
    assert doc["studies"]["st"]["results"] == "Sodium reads [[value:na-diff]] lower."
    assert not [w for w in ds.warnings if "types the value" in w]
    page = (write_site(ds, tmp_path / "site") / "docs" / "studies" / "st.md").read_text(encoding="utf-8")
    assert "[−3.0 mmol/L](" in page


def test_unknown_parameter_is_refused(tmp_path):
    with pytest.raises(AtlasError, match=r"\[\[value:nope\]\]: no parameter 'nope'"):
        load(_dataset(tmp_path, **_files("See [[value:nope]].")))


def test_typed_copy_warns(tmp_path):
    ds = load(_dataset(tmp_path, **_files("Sodium reads −3.0 mmol/L lower.")))
    assert any("study 'st': types the value of na-diff (1x)" in w for w in ds.warnings)


def test_typed_copies_precision_and_small_integers():
    params = {"a": {"value": 2.26}, "b": {"value": 4}, "c": {"value": 2446}}
    assert typed_copies(["lag 2.26 s, about 2.3 s, N = 4, 2,446 recordings, `2.26` in code"], params) == {"a": 2, "c": 1}
    assert value_text({"value": 70.4, "unit": "%"}) == "70.4%"
    assert value_text({"value": 4.5, "unit": "s"}) == "4.5 s"


def test_format_spec(tmp_path):
    doc = to_json(load(_dataset(tmp_path, **_files("About [[value:na-diff|.0]]; cell [[value:na-diff|number]]."))))
    assert doc["studies"]["st"]["derived"]["values"] == {"na-diff|.0": "−3 mmol/L", "na-diff|number": "−3.0"}
    assert value_text({"value": 8192, "unit": "s"}) == "8,192 s"
    assert value_text({"value": 1.92, "unit": "s"}, ".1") == "1.9 s"


def test_retyped_label_is_refused(tmp_path):
    with pytest.raises(AtlasError, match="is not a value format"):
        load(_dataset(tmp_path, **_files("See [[value:na-diff|minus three]].")))
