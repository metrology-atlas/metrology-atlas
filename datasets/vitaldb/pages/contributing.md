# Contributing

Corrections, new studies, better models and code are all welcome. This page says where each kind of contribution
goes, the rules that apply everywhere, and the steps for the common cases.

## Where things live

| You want to change | Repository | Licence |
|---|---|---|
| A page of this atlas: a variable, clock, study, observation, method ... | [[software:metrology-atlas]] (`datasets/vitaldb/`) | MIT |
| A value model: rounding, heaping, a charted time | [[software:vitaldb-resolution]] | MIT |
| An analysis script, the clock model, corrected times, builds, labels | [[software:vitaldb-bench]] | MIT |
| AtriumDB builds and labels | [[software:vitaldb-bench-atriumdb]] | GPL-3.0-or-later |
| Timing corrections that are not specific to VitalDB | [[software:physiosync]] | MIT |
| Pressure-line access detection | [[software:lineaccess]] | MIT |
| How VitalDB files are imported into TimeNet | [[software:timenet]] (its VitalDB connector) | see the repository |

Some of these repositories are private for now. To contribute to one, ask the maintainer (Andrew J. Goodwin,
University of Sydney) for access. If you only want to report a problem, describe it with the page it concerns;
no access is needed for that.

## Rules that apply everywhere

- **Name a case only when it is the point.** VitalDB's case ids are public, and a study may name a case when it
  discusses a specific example: an edge case, a clear illustration of a mechanism, or a comparison of two cases.
  Write it as `[[case:1234]]`; the atlas lists every named case on [Cases discussed](records.md) with the pages that
  name it, and refuses a case number written any other way, so no id appears by accident. Population and group results, and figures
  of a general principle, carry no ids; a figure that shows specific cases lists them under `records:`. The code
  repositories follow the same rule; what they must not publish is bulk per-case output, which their
  `test_no_per_case_files.py` checks.
- **Per-case results stay on the analysis machine.** Only aggregates and figures are published. A script writes its
  per-case output to a local work folder, then a second step aggregates it.
- **Each fact lives in one place.** A model's numbers live in its library; the atlas pins a snapshot and reads them
  from it. A number the atlas holds is a parameter with its study, so other pages refer to it rather than repeat it.
- **Every number says how it is known**: measured (from the data, by a study), derived, estimated or assumed.
  Never state a number without its status and where it came from.
- **History is kept, not overwritten.** When a result changes, the old study or observation is marked superseded,
  and the new one says what it supersedes.
- Contributions are made under the repository's licence.

## Correcting or extending an atlas page

Every page is built from one YAML file in `datasets/vitaldb/`, in a folder named after its kind
(`variables/`, `clocks/`, `studies/` ...). The schema, with a help text for every field, is in
[[code:metrology-atlas/metrology_atlas/model.py]].

1. Edit or add the YAML file. Its `id` must equal the file name. Link other items with `[[kind:id]]`, and code with
   `[[code:software-id/path/to/file.py]]`.
2. Check it: `python -m metrology_atlas check datasets/vitaldb`. This finds every broken reference, unknown field,
   missing figure, code path that does not exist, and forbidden pattern.
3. Build the site and look at the page:
   `python -m metrology_atlas site datasets/vitaldb --out build/vitaldb`, then `zensical build` in that folder.
4. Open a pull request that says what changed and why.

Two folders are never edited by hand. `_sources/` holds pinned snapshots of other libraries, and `_generated/` holds
items written from them by the import scripts in `_import/`. To add to a generated page (a discussion, a better
name, a measurand), write a file with the same id in the normal folder: its fields are merged over the generated
ones and win.

## Updating a study

A study is a short report: background, data (in aggregate), method, results, discussion, limitations, and the code
that ran it. Its numbers are parameters (`parameters/`), each naming the study.

- **A correction that does not change the conclusion** (a typo, a clearer method, a missing limitation): edit the
  study in place.
- **A new result**: write a new study, list the old one under `supersedes:`, and set the old one's `status:` to
  `superseded`. Give changed numbers new parameters and set `superseded_by:` on the old ones. Pages then show both,
  with the old marked.
- **An observation** (a general fact about the data) moves between `established`, `likely`, `open` and
  `withdrawn` as evidence comes in. Withdraw rather than delete.
- List the scripts under `code:`, as `software-id/path`, so the page links to them. The check warns when a script is
  not yet committed, because its link will not work until it is pushed.

## Improving or correcting a value model

The value models (rounding modes, heaping, charted times) live in [[software:vitaldb-resolution]]. The atlas shows
them, one study per model, read from a pinned snapshot. Each model is meant to be examined on its own: its study
page gives the data, the fit, the figures and what is still open, and anyone can propose a better fit or point out
a wrong one.

**How models are versioned.** Each model has its own version (`aneend` v1, v2 …). A published model file is never
edited: a refit or a correction becomes a new version, and the old one stays in the library and can still be
called (`model="aneend@1"`), so results made with it can be reproduced. Each model file records a hash of its
fitted numbers and what it was fitted on (data release, exclusion rules, fitting code and seed). Each package
release ships a `models.lock` listing the version and hash of every model; most users pin a release, and anyone
can pin a single model. Every result the library returns names the model version that made it. (This scheme is
being introduced from the next release; until then the atlas pins the library by commit.)

**If you only have a suggestion,** open an issue on [[software:vitaldb-resolution]] naming the model and what you
think is wrong, or settle one of the open questions on its study page. Evidence helps most: a figure, a count, or
a better-fitting alternative.

**To propose a new version,** in vitaldb-resolution:

1. Change the model, or the decision that sets it. Decisions about each variable's resolution are recorded where
   [[code:vitaldb-resolution/tools/build_registry.py]] says; rebuild the registry with that script after a decision
   changes.
2. Refit as a new version of that model; leave the current file as it is.
3. Validate against the data with [[code:vitaldb-resolution/tools/validate.py]]: every fitted model must reproduce
   its stored log-likelihood, and every value must return a status.
4. Compare the new version with the current one on the same data: log-likelihood and BIC, the propensities, and
   any figure that shows the difference. Say what changed and why in the pull request.
5. Run the tests (`pytest -q tests`, including the per-case files check), regenerate the variables page with
   [[code:vitaldb-resolution/tools/gen_variables_page.py]], and open a pull request. Once it is merged, the new
   version becomes current in the next release.

Then in the atlas:

6. Refresh the snapshot: `python datasets/vitaldb/_import/resolution.py <path to vitaldb-resolution>`. This copies
   the registry and models, records the commit in `_sources/vitaldb-resolution/SOURCE.yaml`, and rewrites the
   generated variables and model studies.
7. Recompute how wide each variable's distributions are in the release:
   `python datasets/vitaldb/_import/resolution_spread.py <path to vitaldb-resolution> <VitalDB release folder>`
   (aggregates only; run it until it reports nothing left), then run the import in step 6 again so the variable
   pages pick it up. For the fitted models, also redraw the worked examples and joint maps on the variable pages:
   `python datasets/vitaldb/_import/value_slices.py <path to vitaldb-resolution> <VitalDB release folder>`
   (aggregates only; it uses the snapshot's commit, never uncommitted changes; run it until nothing is left).
8. Copy the commit and date from `SOURCE.yaml` into `sources:` in `dataset.yaml`, so every page states which
   version of the model it shows.
9. Say what changed in a hand-written file for that model's study (for example
   `studies/value-model-height.yaml`, with a `discussion:`), and credit whoever proposed it. Check and build as
   above.

## Contributing code to vitaldb-bench

[[software:vitaldb-bench]] holds the analysis behind most studies. Set it up with
`pip install -e ".[tools,test]"`, copy `scripts/local.env.example` to `local.env` (which git ignores), and point
`VITALDB_ROOT` at your copy of the VitalDB release and `VITALDB_WORK` at a work folder for per-case output.

Where code goes:

- **The package** (`vitaldb_bench/`): code others import, such as builds, stores, the clock model, corrected times
  and labels. Python 3.11 or later, formatted and linted with ruff (line length 120), with Google-style docstrings
  and tests in `tests/`.
- **Analysis scripts** (`tools/`): one script per analysis. Start it with a module docstring whose first paragraph
  says what it does and what leaves the machine ("Per case, this machine only; aggregates leave."): that
  paragraph becomes its entry in the scripts reference, regenerated by
  [[code:vitaldb-bench/tools/gen_tools_page.py]]. Follow the two-step pattern: a resumable per-case pass that writes
  to the work folder, then an aggregate or plot step that writes to `results/`. Add each published file to the
  table in [[code:vitaldb-bench/docs/how-to/reproduce-results.md]].
- **Short helpers** kept only because a number came from them go in `tools/adhoc/`, with a one-line docstring.
- **Anything that imports the AtriumDB SDK** goes in [[software:vitaldb-bench-atriumdb]], never here, because of
  its licence.

Before a pull request, run `pytest -q` (which includes the per-case files check) and ruff. Then link the script from the
atlas study it supports, under `code:`.

## Checklist

- [ ] Case ids only where a specific case is discussed (in the atlas as `[[case:N]]`); no bulk per-case files committed.
- [ ] Only aggregates and figures published.
- [ ] Every new number has a status and a study.
- [ ] Changed results supersede the old ones rather than overwrite them.
- [ ] Code linked from the study that uses it, and committed.
- [ ] The atlas check and build pass.

## Open questions

The studies so far have left questions of four kinds. Some results are seen clearly but nobody can yet explain
them. Some have a working explanation that the evidence only weakly supports. Some rest on assumptions that the
data in the release cannot test, so they hold only until someone finds outside evidence. And in a few places two
studies give answers that disagree. Each entry below names the question, links to the study where it is
discussed, and says briefly what is known. Settling one, or showing that one of these assumptions is wrong, is
among the most useful contributions you can make; the study page usually says what would settle it. Checks still
to run and decisions still to make are listed on each study page and on the [Open questions](open-questions.md)
page, not here.

<!-- atlas:open-questions -->
