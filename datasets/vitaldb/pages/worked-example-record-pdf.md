# Worked example: a record as a PDF

A record is a point in time–value space: one recorded time and one recorded value. What it tells us is a joint
probability density function (PDF) over the true times and values that could have produced it. This page is the
worked example behind Figure 1 of the paper on the Metrology Atlas: two records, each shown before correction (what
the stored record alone allows, across the release) and after correction (what the atlas gives for one typical
record, from that record's own labels). It gives the atlas items behind every element of the figure.

The typical record is built from medians of the per-record labels. It is not a named case.

![Four panels. Left column, monitor heart rate; right column, laboratory haematocrit. Top row, before correction: a bimodal delay for the heart rate and a two-analyser mixture for the haematocrit. Bottom row, after correction: one narrow peak for the heart rate and one narrow block for the haematocrit.](figures/worked-example-record-pdf.png)

*Figure 1 of the paper. Top row: before correction. Bottom row: after correction, for one typical record.*

## Monitor heart rate of 72 bpm (panels A and C)

**The value.** [[variable:solar8000-hr]] is computed by the monitor from the intervals between R peaks in the last
few seconds of ECG, and rounded down: a recorded 72 means anything from 72 up to, but not including, 73, equally
likely. The rounding was tested against rounding to the nearest in the whole release
([[study:numerics-derivation-release]]). This holds before and after correction.

**The time, before correction.** The value describes a stretch of ECG, its support, of 6–10 s, which closed a delay
before the stamp. Across the release that delay is bimodal: the recording computers fall into an early group
([[parameter:hr-delay-early]]) and a late group ([[parameter:hr-delay-late]]) ([[study:hr-delay-groups]]). Timing
forms: [as stamped, early group](variables/solar8000-hr.md#form-hr-early) and [as stamped, late group](variables/solar8000-hr.md#form-hr-late).

**The time, after correction.** Each recording has a delay label (timing form [after the per-case delay label](variables/solar8000-hr.md#form-hr-lab)): its group, its window and
its delay, with a standard uncertainty of 0.26 s (median of the labels' standard errors). The typical record is in
the late group, with a delay of 4.3 s (the late group's median) and a 6 s window.

## Laboratory haematocrit of 35% (panels B and D)

**The value, before correction.** [[variable:hct]] comes from two analysers with different resolutions
([[study:lab-haematocrit-two-analysers]]): the theatre blood-gas analyser reports whole percent, so 35% means 34.5%
to 35.5%; the central laboratory reports to 0.1%, so it means 34.95% to 35.05%. The value alone does not say which.
The value model in [[software:vitaldb-resolution]] gives the weights for a recorded 35%: about three in four from the
blood-gas analyser (77%), the rest from the central laboratory (23%).

**The time, before correction.** The lab stamp marks the specimen, not the draw and not the result: the blood was
drawn minutes earlier, by a delay that depends on the analyser (about 3–12 min for blood gases, 8–24 min for the
central laboratory; [[variable:lab-blood-gas]], [[variable:lab-central]], [[study:lab-timestamp-meaning]]).

**After correction.** The panel stamped with the value names the analyser (a panel with pH is a blood gas), and the
draw's label places the draw within one arterial-line access ([[study:arterial-line-accesses]]; timing form
[draw time from arterial access](variables/lab-blood-gas.md#form-lab-draw)). Where in that access the draw happened is uniform over about 89 s. The typical record is a blood gas
drawn 410 s (6.8 min, the blood-gas median) before its stamp, so its value stays the whole-percent band.

## Numbers in the caption

| In the caption | Value | From |
|---|---|---|
| Support before correction | 6–10 s | [[variable:solar8000-hr]], [timing form after the per-case delay label](variables/solar8000-hr.md#form-hr-lab): interval described |
| Standard uncertainty of a recording's delay label | 0.26 s | [[variable:solar8000-hr]], [timing form after the per-case delay label](variables/solar8000-hr.md#form-hr-lab): its uncertainty component |
| Share of recorded 35% from the blood-gas analyser | about three in four (77%) | [[software:vitaldb-resolution]] value model |
| Length of the arterial-line access | about 89 s | [[variable:lab-blood-gas]], [timing form draw time from arterial access](variables/lab-blood-gas.md#form-lab-draw): its component (√12 × u) |

The figure is drawn by `figures/src/fig_record_distributions.py` in the paper's source, from the atlas file, the
per-record label tables of [[software:vitaldb-bench]] (numeric delay and lab draw labels), and
[[software:vitaldb-resolution]].
