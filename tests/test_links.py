"""Links between variables (schema 0.4): measurands, derivations, versions and propagation."""

import pytest

from metrology_atlas import AtlasError, load, to_json
from test_engine import _dataset


def _v(id_, **extra):
    return {f"variables/{id_}.yaml": {"id": id_, "name": extra.pop("name", id_.upper()), "summary": "S.",
                                      "type": "numeric", **extra}}


MAP = {"measurands/map.yaml": {"id": "map", "name": "Mean arterial pressure", "summary": "S.", "unit": "mmHg"},
       "measurands/sbp.yaml": {"id": "sbp", "name": "Systolic pressure", "summary": "S.", "unit": "mmHg",
                               "related": [{"measurand": "map", "relation": "related"}]}}


def test_links_load_and_derive(tmp_path):
    d = _dataset(tmp_path, **MAP,
                 **_v("art", unit="mmHg", value={"step": 0.1}, measures=[{"measurand": "map", "method": "invasive"}]),
                 **_v("cuff", unit="mmHg", measures=[{"measurand": "map", "method": "oscillometric"}]),
                 **_v("num", unit="mmHg", derived_from=[{"variable": "art", "relation": "same-source"}]),
                 **_v("est", unit="mmHg", origin="derived", version="1",
                      derived_from=[{"variable": "art", "relation": "computed-from", "symbol": "p"}],
                      estimates=[{"measurand": "sbp",
                                  "validation": {"reference": "arterial line", "trained_on_dataset": True}}],
                      value={"formula": "1.02 * p"}, propagation={"method": "law"}))
    doc = to_json(load(d))
    assert doc["measurands"]["map"]["derived"]["measured_by"] == ["art", "cuff"]
    assert doc["measurands"]["map"]["derived"]["related"] == ["sbp"]
    assert doc["measurands"]["sbp"]["derived"]["related"] == ["map"]
    assert doc["measurands"]["sbp"]["derived"]["estimated_by"] == ["est"]
    assert doc["variables"]["art"]["derived"]["derived_into"] == ["est"]
    assert doc["variables"]["art"]["derived"]["same_source"] == ["num"]


@pytest.mark.parametrize(("files", "expect"), [
    ({**_v("a"), **_v("b", origin="derived", derived_from=[{"variable": "a", "relation": "copied"}])}, "must be one of"),
    ({**_v("b", origin="derived", derived_from=[{"variable": "zz", "relation": "computed-from"}])},
     "'zz' is not a known variable"),
    ({**_v("a"), **_v("b", derived_from=[{"variable": "a", "relation": "computed-from"}])}, "must be 'derived'"),
    ({**_v("b", origin="derived")}, "needs at least one 'derived_from'"),
    ({**_v("a", origin="derived", derived_from=[{"variable": "b", "relation": "computed-from"}]),
      **_v("b", origin="derived", derived_from=[{"variable": "c", "relation": "computed-from"}]),
      **_v("c", origin="derived", derived_from=[{"variable": "a", "relation": "computed-from"}])},
     "derived from itself through"),
    ({**_v("a", origin="derived", derived_from=[{"variable": "a", "relation": "computed-from"}])},
     "cannot be derived from itself"),
    ({**_v("a"), **_v("b", origin="derived", derived_from=[{"variable": "a", "relation": "computed-from",
                                                           "form": "nope"}])}, "is not a timing form of 'a'"),
    ({**_v("a"), **_v("b", origin="derived", value={"formula": "x + 1"},
                      derived_from=[{"variable": "a", "relation": "computed-from", "symbol": "y"}])},
     "does not appear in the formula"),
    ({**_v("a"), **_v("b", origin="derived", derived_from=[{"variable": "a", "relation": "computed-from"}],
                      propagation={"method": "law"})}, "needs the value's 'formula'"),
    ({**_v("a"), **_v("b", origin="derived", derived_from=[{"variable": "a", "relation": "computed-from"}],
                      propagation={"method": "study"})}, "needs the studies"),
    ({**_v("a"), **_v("b", value={"inputs": ["a"]})}, "retired in schema 0.4"),
    ({**MAP, **_v("a", unit="kPa", measures=[{"measurand": "map"}])}, "differs from the measurand's"),
    ({**MAP, **_v("a", estimates=[{"measurand": "map", "validation": {"reference": "line",
                                                                       "trained_on_dataset": False}}])},
     "set 'origin: derived'"),
    ({"measurands/x.yaml": {"id": "x", "name": "X", "summary": "S.", "related": [{"measurand": "y", "relation": "related"}]},
      "measurands/y.yaml": {"id": "y", "name": "Y", "summary": "S.", "related": [{"measurand": "x", "relation": "related"}]}},
     "write the relation once"),
    ({**_v("a"),
      **_v("f1", name="F", origin="derived", version="2", superseded_by="f2",
           derived_from=[{"variable": "a", "relation": "computed-from"}]),
      **_v("f2", name="F", origin="derived", version="1.9", derived_from=[{"variable": "a", "relation": "computed-from"}])},
     "is not later than"),
])
def test_rejects_bad_links(tmp_path, files, expect):
    with pytest.raises(AtlasError) as err:
        load(_dataset(tmp_path, **files))
    assert any(expect in p for p in err.value.problems), err.value.problems


def test_unit_conversion_allowed(tmp_path):
    load(_dataset(tmp_path, **MAP, **_v("a", unit="kPa", measures=[{"measurand": "map", "conversion": "x 7.50062"}])))


def test_supersession(tmp_path):
    doc = to_json(load(_dataset(tmp_path, **_v("a"),
        **_v("f1", name="F", origin="derived", version="2.9", superseded_by="f2",
             derived_from=[{"variable": "a", "relation": "computed-from"}]),
        **_v("f2", name="F", origin="derived", version="2.10", derived_from=[{"variable": "a", "relation": "computed-from"}]))))
    assert doc["variables"]["f2"]["derived"]["supersedes"] == ["f1"]
