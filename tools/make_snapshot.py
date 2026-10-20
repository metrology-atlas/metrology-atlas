"""Build the archived snapshot of a dataset's atlas for Zenodo (one zip per atlas version).

    python tools/make_snapshot.py datasets/vitaldb --version 0.1.0 [--zensical PATH] [--draft]

Writes build/snapshot/<id>-metrology-atlas-v<version>.zip containing
  dataset/            the dataset folder as committed (YAML, figures, pinned sources, import scripts)
  <id>.metrology.json the whole atlas in one machine-readable file
  site/               the website, built in release mode (open site/index.html)
  README.md, LICENSE.txt
and, beside the zip, zenodo_fields.txt with the values for Zenodo's upload form.
Refuses when the dataset folder has uncommitted changes (--draft builds anyway, marked as a draft).
"""
import argparse
import datetime as dt
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORG = "https://github.com/metrology-atlas"


def git(*args):
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--zensical", default=shutil.which("zensical") or "zensical")
    ap.add_argument("--draft", action="store_true")
    a = ap.parse_args(argv)
    ds = (ROOT / a.dataset).resolve() if not a.dataset.is_absolute() else a.dataset
    rel = ds.relative_to(ROOT)
    dirty = git("status", "--porcelain", "--", str(rel))
    commit = git("rev-parse", "HEAD")
    if dirty and not a.draft:
        raise SystemExit(f"{rel} has uncommitted changes; commit first (or --draft):\n{dirty}")
    import yaml
    meta = yaml.safe_load((ds / "dataset.yaml").read_text(encoding="utf-8"))
    did = meta.get("id") or ds.name
    name = meta.get("name", did)
    site_url = (meta.get("site") or {}).get("url", "")
    today = dt.date.today().isoformat()
    tag = f"{did}-metrology-atlas-v{a.version}" + ("-DRAFT" if a.draft and dirty else "")
    out = ROOT / "build" / "snapshot"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / tag
        stage.mkdir()
        # dataset folder exactly as committed (or as on disk for a draft)
        if dirty:
            shutil.copytree(ds, stage / "dataset", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            arch = Path(tmp) / "ds.tar"
            subprocess.run(["git", "archive", "-o", str(arch), "HEAD", str(rel)], cwd=ROOT, check=True)
            subprocess.run(["tar", "xf", str(arch), "-C", tmp], check=True)
            shutil.move(str(Path(tmp) / rel), stage / "dataset")
        py = sys.executable
        subprocess.run([py, "-m", "metrology_atlas", "json", str(ds), "--out", str(stage / f"{did}.metrology.json")],
                       cwd=ROOT, check=True)
        src = Path(tmp) / "site_src"
        subprocess.run([py, "-m", "metrology_atlas", "site", str(ds), "--out", str(src), "--release"], cwd=ROOT,
                       check=True)
        subprocess.run([a.zensical, "build"], cwd=src, check=True, capture_output=True)
        shutil.copytree(src / "site", stage / "site")
        (stage / "README.md").write_text(f"""# {name}, version {a.version}

Archived snapshot of the {name}, built {today} from {ORG}/metrology-atlas at commit {commit[:12]}.
The live, current version is at {site_url or ORG}.

Contents
- `site/`: the website as published. Open `site/index.html` in a browser; it works offline.
- `{did}.metrology.json`: the whole atlas in one machine-readable file.
- `dataset/`: the source the site and the file are built from: one YAML file per item, the figures, the pinned
  snapshots of the libraries it reads (`_sources/`) and the import scripts (`_import/`, MIT licence). Rebuild with
  the metrology-atlas engine at the commit above: `python -m metrology_atlas site dataset --out site_src`.

The atlas contains no recordings or per-case tables, only aggregates, figures and models. The data it describes
are VitalDB 1.0.0 (PhysioNet, CC BY 4.0, https://doi.org/10.13026/czw8-9p62). Cite the atlas together with the
data; see `site/data-and-licence.html` for the full list.

Licence: CC BY 4.0 (see LICENSE.txt). Author: Andrew J. Goodwin, School of Biomedical Engineering, The University of
Sydney (ORCID 0000-0002-2776-7039).
""", encoding="utf-8")
        (stage / "LICENSE.txt").write_text(f"""Copyright (c) 2026 Andrew J. Goodwin

The text, figures, models and machine-readable file of this atlas are licensed under the Creative Commons
Attribution 4.0 International licence (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/legalcode

The scripts in dataset/_import/ are licensed under the MIT licence, as in {ORG}/metrology-atlas.

Results derived from VitalDB are shared under CC BY 4.0, as VitalDB is; copyright in the underlying data stays
with VitalDB's authors. Device and product names belong to their owners. Provided as is, without warranty; not for
clinical use.
""", encoding="utf-8")
        zpath = out / f"{tag}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(stage.parent))
    (out / "zenodo_fields.txt").write_text(f"""Zenodo upload form: values for {zpath.name}

Resource type:   Dataset
Title:           {name} (version {a.version})
Creator:         Goodwin, Andrew J. | ORCID 0000-0002-2776-7039 | School of Biomedical Engineering, The University of Sydney
Publication date:{today}
Version:         {a.version}
Licence:         Creative Commons Attribution 4.0 International
Keywords:        metrology; measurement uncertainty; physiological signals; clock synchronisation; data quality; VitalDB
Description:     A machine-readable description of VitalDB 1.0.0 as a measurement system: for every variable, what was
                 measured, the measurement model linking it to the recorded time and value, and what is known about
                 the true time and value, with the clocks, devices, studies and parameters behind it. This snapshot
                 holds the website (open site/index.html), the single-file JSON and the YAML source, built from
                 {ORG}/metrology-atlas at commit {commit[:12]}. Live version: {site_url}
Related works:   is derived from       10.13026/czw8-9p62 (DOI, VitalDB 1.0.0 on PhysioNet)
                 is supplemented by    {ORG}/metrology-atlas (URL; after 4.4, its version DOI instead)
                 is documented by      {site_url} (URL)
                 is described by       the arXiv paper (add when announced, 7.7)
""", encoding="utf-8")
    print(f"wrote {zpath.relative_to(ROOT)} ({zpath.stat().st_size / 1e6:.1f} MB) and zenodo_fields.txt"
          + (" (DRAFT: uncommitted changes)" if dirty else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
