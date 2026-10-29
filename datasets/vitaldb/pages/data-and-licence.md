# Data and licence

This atlas describes a public dataset, and is published under open licences. This page says what the data are and
under what terms they are shared, what the atlas does and does not contain, and how the atlas itself may be reused.

## The data: VitalDB

The atlas describes **VitalDB version 1.0.0** on PhysioNet: high-resolution waveforms, numerics and clinical
information from 6,388 surgical patients at Seoul National University Hospital
([[reference:lee2022vitaldb-physionet]]; described in [[reference:lee2022vitaldb]]).

- **Licence:** VitalDB is shared under the
  [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/)
  (CC BY 4.0). Its files are open access on [PhysioNet](https://physionet.org/content/vitaldb/1.0.0/): there is no
  data use agreement and no credentialing.
- **Copyright** in the data stays with VitalDB's authors. Everything in this atlas that is derived from the data
  (numbers, figures, models, corrections) is shared under the same licence, CC BY 4.0.
- **What the atlas changes.** The atlas does not alter the data. It measures them, and proposes corrections: time
  stamps re-modelled against the recorder's clock, and some scale factors corrected (each listed with its "Corrected
  to" value on the device's page). Where a result here differs from VitalDB's documentation, the atlas says so on
  the page concerned; VitalDB's own release and documentation remain the reference.
- **What the atlas does not contain.** No recording, waveform file or per-case table is redistributed here.
  Results are aggregates and figures; a case is named only when it is the point of an example (see
  [Contributing](contributing.md)). To work with the data, download them from PhysioNet under their terms.

### Citing the data

If you use VitalDB, or results from this atlas that are derived from it, cite:

- [[reference:lee2022vitaldb-physionet]]
- [[reference:lee2022vitaldb]]
- [[reference:pollard2026physionet]]

## This atlas

| Part | Licence |
|---|---|
| Text, figures and the machine-readable atlas file | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| The atlas engine and analysis code ([[software:metrology-atlas]], [[software:vitaldb-bench]] and the others listed on [Contributing](contributing.md)) | MIT, unless the repository says otherwise |
| Results derived from VitalDB | CC BY 4.0, as above, with VitalDB's citations |

CC BY 4.0 lets you copy, adapt and build on the atlas for any purpose, including commercially, provided you give
credit, link to the licence, and say what you changed. Please cite the atlas and the data together.

### Citing the atlas

The atlas is described in:

Goodwin, A. J. (2026). The Metrology Atlas: describing recorded physiological data as a measurement system, with VitalDB as a first application. arXiv:2610.29001.
[doi:10.48550/arXiv.2610.29001](https://doi.org/10.48550/arXiv.2610.29001)

The archived atlas itself:

Goodwin, A. J. (2026). *VitalDB metrology atlas* [Data set]. Zenodo.
[doi:10.5281/zenodo.23494768](https://doi.org/10.5281/zenodo.23494768)

This DOI always resolves to the latest archived version. To cite the exact version you used, take its own DOI from
that page; version 0.1.0 is [doi:10.5281/zenodo.23494769](https://doi.org/10.5281/zenodo.23494769). Each archived
version holds the website, the machine-readable file and the YAML source. The software releases have DOIs of their
own, listed on their Zenodo records and in each repository.

## No warranty, and not for clinical use

The atlas is a research resource. It is provided as is, without warranty of any kind, under the terms of its
licences. Nothing in it is advice for the care of any patient, and it has not been reviewed by the makers of the
devices it describes. Each number states how it is known (measured, derived, estimated or assumed) and from which
study; check those before relying on one.

## Names of devices and software

Device and product names (such as the BIS monitor, the Primus anaesthesia workstation and the CardioQ monitor) are
used only to say which equipment made a recording; they belong to their owners. The atlas is an independent work,
not affiliated with or endorsed by the VitalDB team, PhysioNet or any manufacturer.
