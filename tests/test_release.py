"""The --release build leaves out links into repositories that are not public."""
from pathlib import Path

import yaml

from metrology_atlas.__main__ import main

DS = Path(__file__).resolve().parents[1] / "datasets" / "vitaldb"


def test_release_build_has_no_private_links(tmp_path):
    assert main(["site", str(DS), "--out", str(tmp_path / "rel"), "--release"]) == 0
    docs = tmp_path / "rel" / "docs"
    text = "".join(p.read_text(encoding="utf-8") for p in docs.rglob("*.md"))
    hidden = 0
    for f in (DS / "software").glob("*.yaml"):
        w = yaml.safe_load(f.read_text(encoding="utf-8"))
        if w.get("visibility") in ("private", "unpublished"):
            hidden += 1
            if w.get("repo"):
                assert w["repo"].rstrip("/") not in text, w["id"]
    if hidden:
        assert "not yet released" in text
