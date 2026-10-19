"""The --release build leaves out links into repositories that are not public."""
from pathlib import Path

from metrology_atlas.__main__ import main

DS = Path(__file__).resolve().parents[1] / "datasets" / "vitaldb"


def test_release_build_has_no_private_links(tmp_path):
    assert main(["site", str(DS), "--out", str(tmp_path / "rel"), "--release"]) == 0
    docs = tmp_path / "rel" / "docs"
    text = "".join(p.read_text(encoding="utf-8") for p in docs.rglob("*.md"))
    for repo in ("meshlab/physiosync", "meshlab/vitaldb-bench", "meshlab/lineaccess", "meshlab/vitaldb-resolution"):
        assert f"github.com/{repo}" not in text
    assert "not yet released" in text
