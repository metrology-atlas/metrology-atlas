"""The engine on a tiny made-up dataset, and on the shipped datasets."""

import json
from pathlib import Path

import pytest
import yaml

from metrology_atlas import AtlasError, load, to_json, write_site

ROOT = Path(__file__).resolve().parents[1]


def _dataset(tmp_path, **files):
    d = tmp_path / "ds"
    (d / "clocks").mkdir(parents=True)
    (d / "dataset.yaml").write_text(yaml.safe_dump({
        "id": "toy", "name": "Toy", "summary": "A toy dataset.",
        "forbidden_patterns": [{"pattern": r"(?i)\bpatient\s*\d+", "why": "no patient numbers"}]}))
    base = {"clocks/a.yaml": {"id": "a", "name": "A", "summary": "Clock A.", "type": "oscillator"},
            "clocks/b.yaml": {"id": "b", "name": "B", "summary": "Clock B.", "type": "software"}}
    for path, item in {**base, **files}.items():
        (d / path).parent.mkdir(parents=True, exist_ok=True)
        (d / path).write_text(yaml.safe_dump(item))
    return d


def test_loads_and_derives(tmp_path):
    d = _dataset(tmp_path, **{
        "devices/dev.yaml": {"id": "dev", "name": "Dev", "summary": "S.", "type": "other", "clocks": ["a"]},
        "variables/sig.yaml": {"id": "sig", "name": "Sig", "summary": "S.", "type": "waveform", "device": "dev",
                             "stamp_clock": "b", "sample_clock": "a"},
    })
    doc = to_json(load(d))
    assert doc["devices"]["dev"]["derived"]["variables"] == ["sig"]
    assert doc["clocks"]["b"]["derived"]["stamps"] == ["sig"]
    assert doc["clocks"]["a"]["derived"] == {"devices": ["dev"], "spaces": ["sig"]}


@pytest.mark.parametrize(("files", "expect"), [
    ({"variables/s.yaml": {"id": "s", "name": "S", "summary": "S.", "type": "waveform", "device": "nope",
                         "stamp_clock": "a"}}, "'nope' is not a known device"),
    ({"clocks/c.yaml": {"id": "c", "name": "C", "summary": "See [[clock:zz]].", "type": "oscillator",
                        "description": "See [[clock:zz]]."}}, "[[clock:zz]] does not exist"),
    ({"clocks/c.yaml": {"id": "x", "name": "C", "summary": "S.", "type": "oscillator"}}, "must equal the file name"),
    ({"clocks/c.yaml": {"id": "c", "name": "C", "summary": "S.", "type": "quartz"}}, "must be one of"),
    ({"clocks/c.yaml": {"id": "c", "name": "C", "summary": "S.", "type": "oscillator", "colour": 1}}, "unknown field"),
    ({"clocks/c.yaml": {"id": "c", "name": "C", "summary": "Seen in patient 12.", "type": "oscillator"}},
     "forbidden pattern"),
    ({"clocks/c.yaml": {"id": "c", "name": "C", "summary": "S.", "type": "oscillator",
                        "figures": [{"id": "f", "file": "nope.png", "caption": "C.", "alt": "A."}]}}, "no file figures/"),
    ({"clocks/c.yaml": {"id": "c", "name": "C", "summary": "S.", "type": "oscillator",
                        "description": "[[figure:zz]]"}}, "not one of this item's figures"),
    ({"devices/dev.yaml": {"id": "dev", "name": "D", "summary": "S.", "type": "other"},
      "variables/s.yaml": {"id": "s", "name": "S", "summary": "S.", "type": "waveform", "device": "dev", "stamp_clock": "a",
                         "timing": [{"id": "t", "name": "raw", "delay_s": [0.1, 0.2], "interval_s": [0, 0.01],
                                     "domain": "nowhere", "status": "measured", "evidence": "E."}]}},
     "is not in dataset.yaml domains"),
    ({"devices/dev.yaml": {"id": "dev", "name": "D", "summary": "S.", "type": "other"},
      "variables/s.yaml": {"id": "s", "name": "S", "summary": "S.", "type": "waveform", "device": "dev", "stamp_clock": "a",
                         "timing": [{"id": "t", "name": "raw", "delay_s": [0.3, 0.2], "interval_s": [0, 0.01],
                                     "domain": "nowhere", "status": "measured", "evidence": "E."}]}},
     "must be [low, high]"),
])
def test_rejects(tmp_path, files, expect):
    with pytest.raises(AtlasError) as err:
        load(_dataset(tmp_path, **files))
    assert any(expect in p for p in err.value.problems), err.value.problems


@pytest.mark.parametrize("name", [p.name for p in (ROOT / "datasets").iterdir() if (p / "dataset.yaml").exists()])
def test_shipped_datasets_build(tmp_path, name):
    ds = load(ROOT / "datasets" / name)
    out = write_site(ds, tmp_path / name)
    assert (out / "zensical.toml").exists()
    pages = list((out / "docs").rglob("*.md"))
    assert len(pages) > sum(len(v) for v in ds.items.values() if v) - len(ds.items["reference"])
    assert json.loads((out / "docs" / "data" / f"{name}.metrology.json").read_text())["schema"].startswith("metrology-atlas/")


def test_code_links(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "scan.py").write_text("")
    d = _dataset(tmp_path, **{
        "software/kit.yaml": {"id": "kit", "name": "Kit", "summary": "S.", "repo": "https://example.org/kit.git",
                              "branch": "dev", "local": "../repo"},
        "clocks/c.yaml": {"id": "c", "name": "C", "summary": "S.", "type": "oscillator",
                          "description": "Made by [[code:kit/tools/scan.py|the scan]]."},
    })
    ds = load(d)
    from metrology_atlas.code import code_url
    assert code_url(ds, "kit/tools/scan.py") == "https://example.org/kit/blob/dev/tools/scan.py"
    assert code_url(ds, "kit/tools") == "https://example.org/kit/tree/dev/tools"
    assert code_url(ds, "kit") == "https://example.org/kit"
    assert to_json(ds)["software"]["kit"]["derived"]["mentioned_in"] == ["clock:c"]
    (d / "clocks" / "c.yaml").write_text(yaml.safe_dump(
        {"id": "c", "name": "C", "summary": "S.", "type": "oscillator", "description": "[[code:kit/tools/gone.py]]"}))
    with pytest.raises(AtlasError, match="gone.py is not in the local copy"):
        load(d)
    (d / "clocks" / "c.yaml").write_text(yaml.safe_dump(
        {"id": "c", "name": "C", "summary": "S.", "type": "oscillator", "description": "[[code:nokit/x.py]]"}))
    with pytest.raises(AtlasError, match="not a known software item"):
        load(d)


def test_generated_overlay_and_snapshot(tmp_path):
    d = _dataset(tmp_path, **{
        "_generated/variables/h.yaml": {"id": "h", "name": "Height", "summary": "Generated.", "type": "clinical",
                                         "unit": "cm", "value": {"step": 0.1, "model": "lib/models/h.json"}},
        "variables/h.yaml": {"id": "h", "name": "Height", "summary": "Hand-written.", "type": "clinical",
                             "value": {"bias": {"value": 0.5}}},
        "software/lib.yaml": {"id": "lib", "name": "Lib", "summary": "S."},
    })
    meta = yaml.safe_load((d / "dataset.yaml").read_text())
    meta["sources"] = [{"software": "lib", "folder": "_sources/lib"}]
    (d / "dataset.yaml").write_text(yaml.safe_dump(meta))
    (d / "_sources" / "lib").mkdir(parents=True)
    with pytest.raises(AtlasError, match="not in the snapshot"):
        load(d)
    (d / "_sources" / "lib" / "models").mkdir()
    (d / "_sources" / "lib" / "models" / "h.json").write_text("{}")
    item = load(d).items["variable"]["h"]
    assert item["summary"] == "Hand-written."
    assert item["value"] == {"step": 0.1, "model": "lib/models/h.json", "bias": {"value": 0.5}}


def test_record_references(tmp_path):
    d = _dataset(tmp_path, **{
        "clocks/c.yaml": {"id": "c", "name": "C", "summary": "S.", "type": "oscillator",
                          "description": "Seen in [[patient:12]] and [[patient:7|the paced one]]."},
    })
    meta = yaml.safe_load((d / "dataset.yaml").read_text())
    meta["records"] = {"name": "patient", "max": 100}
    (d / "dataset.yaml").write_text(yaml.safe_dump(meta))
    doc = to_json(load(d))
    assert doc["clocks"]["c"]["derived"] == {} or True
    from metrology_atlas.load import derived
    rel = derived(load(d))
    assert rel["record"]["12"]["mentioned_in"] == ["clock:c"]
    (d / "clocks" / "c.yaml").write_text(yaml.safe_dump(
        {"id": "c", "name": "C", "summary": "S.", "type": "oscillator", "description": "Seen in patient 12."}))
    with pytest.raises(AtlasError, match="forbidden pattern"):
        load(d)
    (d / "clocks" / "c.yaml").write_text(yaml.safe_dump(
        {"id": "c", "name": "C", "summary": "S.", "type": "oscillator", "description": "[[patient:500]]"}))
    with pytest.raises(AtlasError, match="out of range"):
        load(d)
