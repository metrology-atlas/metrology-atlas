# metrology-atlas

A machine-readable metrology of a recorded dataset. Every recorded value is a pair, a recorded time and a recorded
value, and neither is the truth. The atlas describes, for every **variable**, where the true time and the true value
can lie given the recorded pair, on two axes (time, value), each with a systematic error (bias) and a standard
uncertainty (VIM/GUM), together with the evidence: the **clocks** and **links** that carry time, the **devices**, every
**parameter** we rely on, and the **studies** that measured them, grouped by **method** and built from shared
**techniques**. Observations, software and references complete it.

The first atlas, for VitalDB, is at **https://vitaldb.metrology-atlas.org**. Comments and corrections are welcome
as issues or in Discussions here.

[![Atlas DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23494768.svg)](https://doi.org/10.5281/zenodo.23494768)
Archived VitalDB atlas (all versions; v0.1.0 is [10.5281/zenodo.23494769](https://doi.org/10.5281/zenodo.23494769)).
This software, v0.2.0: [10.5281/zenodo.23488888](https://doi.org/10.5281/zenodo.23488888).

Paper: Goodwin, A. J. (2026). *The Metrology Atlas: describing recorded physiological data as a measurement system, with VitalDB as a first application*. [arXiv:2610.29001](https://arxiv.org/abs/2610.29001).

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

## How an atlas is organised

An atlas holds items of these kinds: variables, the measurands they measure, clocks, links between clocks, devices,
parameters, studies, observations, the methods and techniques the studies use, worked examples, software and
references. Each fact lives in one place, and every relation is written once and linked both ways.

For each variable an atlas records:

| Part | Fields |
|---|---|
| Measurand | what is measured; the device; the clock that stamps it |
| Support | the length of the interval each value describes, and where the stamp sits in it |
| Timing forms | as stored, shifted by a value known in advance, or corrected per recording; usable in real time or not |
| Bias | stamp minus the close of the support, against the working reference: one value or a distribution between recordings (median, 5th–95th percentile, number), its scope and status |
| Uncertainty | components, each with a name, Type A or B, distribution, standard uncertainty, scope, correlation shape and length, and shared key; an upper-bound flag, a 95% interval and a likely value |
| Value | resolution, rounding rule, bias and uncertainty of the value |
| Relations | what it measures or estimates; the variables it was derived from, with algorithm, code and version; how its uncertainty propagates |
| Clock domain | the domain whose drift remains, with its rate and its spread between recordings |
| Evidence | status, the studies behind each number, the correction and the code |

The combined standard uncertainty is computed by the engine from the components, never typed.

**Studies** are short reports: data in aggregate, method, results, limitations and the code that produced them.
Their general findings are collected as **observations** (established, likely, open or withdrawn), and their
unsettled points as **open questions** of five kinds: phenomena not yet explained, weakly supported hypotheses,
untestable assumptions, conflicts between studies, and next steps. Evidence can come from the records themselves,
from device documentation, or from reverse-engineering the recording chain (converter and filter models, bench
tests). Studies are grouped by **methods** that another dataset can reuse, such as reading a device's own stamps,
finding one event on two clocks, using a rhythm carried in a signal (a pacemaker, an oximeter's frames, the mains
hum) as a third clock, and method comparison; each method's page lists its techniques and the studies that use it.

The **clocks** form a network: each clock is measured against another, with the rate and resynchronisation schedule
of the link. Device rates are relative, so the network is tested by its loops: around any loop the rates should sum
to zero, and, with the network adjusted as a geodetic network is, the misclosures flag a bad link and test whether
the stated uncertainties are right. A clock outside the recording, such as the mains grid, ties the network to an
outside reference.

## Checks

Before it builds, the engine checks every field and cross-reference. It refuses unknown and retired fields, a timing
form whose bias and uncertainty do not follow the atlas's conventions, the word *accuracy* next to a number (VIM 2.13:
accuracy is not given a number), and any text that matches a pattern the dataset forbids, such as a record
identifier outside a deliberate link, so that no per-recording table leaves by accident. `check --provenance` also
traces each parameter to the saved output and run record behind it (see `metrology_atlas/provenance.py`).

A worked example is marked *current* only when it can be repeated. Its code is committed. Every output it uses was
made by that committed code and has a run record. Every number on its page can be traced to a key in a saved summary,
and every figure is byte-identical to a run output. Until then it stays *draft*, however complete its text.

## Versions, and papers that quote an atlas

An atlas is revised as evidence comes in; adding a study is the system working, not a new edition. When a number
changes, the old value is kept, marked superseded with the date and the reason, so a number quoted from an earlier
version can still be traced. Each release is archived with its own identifier.

Numbers flow one way: from the atlas into papers, the website and any other output, never back. A paper quotes one
release, and draws every number about the dataset from a registry of **facts** generated from that release's
machine-readable file: each fact has its value, its printed form, unit, status and source item, and the registry
records the release it was built from. A paper that refers to a fact the registry does not define fails to build. A
change that leaves a paper's argument intact needs nothing further; one that alters an argument calls for a revised
version of the paper. Generation guarantees agreement, not correctness: correctness rests on the studies, on the
closed loops of the clock network, on corrections tested on data held out from their fit, and on anyone being able
to read the machine-readable file and compare it with the website.

## Contributing, and other datasets

Contributions are pull requests against a dataset's folder, checked by the same engine. What carries over to a new
dataset is the schema, the engine and its checks, the website and the machine-readable output, the planner, and the
dataset-independent timing tools; what is written afresh is the dataset's folder and the studies behind it. Each
atlas has its own site; the project's home page, https://metrology-atlas.org, lists them with the software, papers
and news.

## Writing items

- **Each fact lives in one place.** A model fitted by another library stays in that library's files: the dataset pins
  a snapshot (`sources:` in `dataset.yaml`, with its commit) and pages read the numbers from it. An import script may
  generate items from a snapshot into `_generated/`; a hand-written file with the same id adds to it, and its fields
  win.
- Relations are written once. A variable names its device and clocks; the device page lists its variables. A
  parameter names its study and what it is about; the study page lists its parameters.
- Prose is Markdown. `[[clock:recorder-pc]]` (or `[[clock:recorder-pc|the PC]]`) links to another item, and
  `[[code:software-id/path/file.py]]` links into a repository; both are checked.
- Every number is a parameter with a status: `measured`, `derived`, `documented` (a rule of the device or software,
  from its code, manual or developer), `estimated`, `assumed`, `withdrawn` or `superseded`.
- Figures live in the dataset's `figures/` folder; `[[figure:id]]` places one inline.
- A variable's `timing:` lists the forms its times come in, each with the interval a value describes, its bias and
  its uncertainty budget against the working reference, and its clock domain; the **synchronisation planner** combines them. Its `value:` gives the value
  side: resolution, bias and uncertainty, and an optional model in a pinned snapshot.
- `dataset.yaml` lists forbidden patterns. Any text that matches one, anywhere, fails the check. A dataset can also
  declare `records:` (for VitalDB, `case`): then `[[case:1234]]` names one record deliberately, the forbidden
  patterns do not apply inside such a reference, and every named record is listed on a "Cases discussed" page with
  the pages that name it. Figures of specific records list them under `records:`.

The schema is in `metrology_atlas/model.py`.

## Datasets

- `datasets/vitaldb`: VitalDB (PhysioNet 1.0.0): its timing graph, and the value models of vitaldb-resolution.

MIT licence.
