# metrology-atlas

A machine-readable metrology of a recorded dataset. Every recorded value is a pair, a recorded time and a recorded
value, and neither is the truth. The atlas describes, for every **variable**, where the true time and the true value
can lie given the recorded pair, on two axes (time, value) and with two kinds of error on each (accuracy,
resolution), together with the evidence: the **clocks** and **links** that carry time, the **devices**, every
**parameter** we rely on, and the **studies** that measured them, grouped by **method** and built from shared
**techniques**. Observations, software and references complete it.

The first atlas, for VitalDB, is at **https://vitaldb.metrology-atlas.org**. Comments and corrections are welcome
as issues or in Discussions here.

[![Atlas DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23494768.svg)](https://doi.org/10.5281/zenodo.23494768)
Archived VitalDB atlas (all versions; v0.1.0 is [10.5281/zenodo.23494769](https://doi.org/10.5281/zenodo.23494769)).
This software, v0.2.0: [10.5281/zenodo.23488888](https://doi.org/10.5281/zenodo.23488888).

The engine knows nothing about any one dataset. A dataset is a folder of YAML files, one per item:

```text
datasets/<id>/
  dataset.yaml        name, summary, site settings, sources, forbidden patterns (e.g. record ids)
  references.yaml
  variables/  clocks/  links/  devices/  parameters/  studies/  observations/  methods/  techniques/  software/
  _sources/<software>/     pinned snapshots of other libraries' data files (never edited by hand)
  _generated/<kind>/       items written by an import script from a snapshot (never edited by hand)
  _import/                 the import scripts
```

From that folder the engine checks every field and cross-reference, then writes

- `<id>.metrology.json`: the whole atlas in one file, for code and models to read;
- a website: one page per item, every relation linked both ways, a measurement-space figure for every variable, a
  chain from UTC to each stored time stamp, and a synchronisation planner.

```bash
python -m metrology_atlas check datasets/vitaldb
python -m metrology_atlas json  datasets/vitaldb --out build/vitaldb.metrology.json
python -m metrology_atlas site  datasets/vitaldb --out build/vitaldb
cd build/vitaldb && zensical build          # the site lands in build/vitaldb/site/
```

## Writing items

- **Each fact lives in one place.** A model fitted by another library stays in that library's files: the dataset pins
  a snapshot (`sources:` in `dataset.yaml`, with its commit) and pages read the numbers from it. An import script may
  generate items from a snapshot into `_generated/`; a hand-written file with the same id adds to it, and its fields
  win.
- Relations are written once. A variable names its device and clocks; the device page lists its variables. A
  parameter names its study and what it is about; the study page lists its parameters.
- Prose is Markdown. `[[clock:recorder-pc]]` (or `[[clock:recorder-pc|the PC]]`) links to another item, and
  `[[code:software-id/path/file.py]]` links into a repository; both are checked.
- Every number is a parameter with a status: `measured`, `derived`, `estimated`, `assumed`, `withdrawn` or
  `superseded`.
- Figures live in the dataset's `figures/` folder; `[[figure:id]]` places one inline.
- A variable's `timing:` lists the forms its times come in, each with its delay and interval ranges against the
  working reference and its clock domain; the **synchronisation planner** combines them. Its `value:` gives the value
  side: resolution, accuracy and an optional model in a pinned snapshot.
- `dataset.yaml` lists forbidden patterns. Any text that matches one, anywhere, fails the check. A dataset can also
  declare `records:` (for VitalDB, `case`): then `[[case:1234]]` names one record deliberately, the forbidden
  patterns do not apply inside such a reference, and every named record is listed on a "Cases discussed" page with
  the pages that name it. Figures of specific records list them under `records:`.

The schema is in `metrology_atlas/model.py`.

## Datasets

- `datasets/vitaldb`: VitalDB (PhysioNet 1.0.0): its timing graph, and the value models of vitaldb-resolution.

MIT licence.
