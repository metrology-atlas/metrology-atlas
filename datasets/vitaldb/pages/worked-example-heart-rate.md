# Worked example: one heart-rate record

This page talks through Figure 1 of the paper on the Metrology Atlas: how one heart-rate record in VitalDB was made,
and how it can be read. It follows the figure panel by panel, and links each step to the study and the numbers
behind it. The record is an illustration: the ECG is synthetic, and the recording's delay is the late group's median,
not a named case. Every number that describes VitalDB is read from this atlas.

![Six panels. Top row: A, an ECG with its R peaks; B, the last 8 R–R intervals shaded as the support, averaged and truncated to 72; C, the delay from the window's close to the value being ready at the recorder; D, the wait for the recorder's 2 s poll, then the stamp. Between the rows, the measurement model in two lines. Bottom row: E, the joint PDF over the true time the window closed and the true heart rate from the stored record alone, wide in time as the sum of two groups of recordings; F, the same with the atlas, narrow in time, the width of one poll. In both, the value is uniform over 72 to 73 bpm.](figures/worked-example-heart-rate.png)

*Figure 1 of the paper.*

## The measurement model

How the record was made, run forward from the heart to the stored pair:

- **Value:** recorded = floor(60 / mean of the last [[value:hr-window|number]] R–R intervals within about
  [[value:hr-outlier-band]] of their median). The true value therefore lies anywhere in [recorded, recorded + 1).
- **Time:** stamp = window close + d + φ, where d is the recording's delay and φ is the wait for the recorder's poll,
  uniform on [0, [[value:solar8000-poll-gap]]).

## How the record was made (panels A–D)

**A. The heart beats.** Each R peak of the ECG is an event in true time. The heart rate describes the intervals
between them.

**B. The monitor averages and truncates.** The Solar8000 computes its heart rate ([[variable:solar8000-hr]]) as 60 over
the mean of the last [[value:hr-window|number]] R–R intervals, leaving out any interval more than about
[[value:hr-outlier-band]] from their median, and rounds the result down ([[study:hr-derivation]]). This rule reproduces
a median of [[value:hr-derivation-exact]] of a recording's values exactly. The outlier band is weakly determined:
bands of 10–25% fit equally well. The stretch of ECG the value describes, its support, is a count of beats, not a
span of seconds: [[value:hr-window-span]] at the release's median rate. Truncation means a recorded 72 is anything
from 72 up to, but not including, 73.

**C. The value is processed and sent.** The value is ready at the recorder a delay d after the window closes. Across
the release, the recordings fall into two groups by this delay ([[study:hr-delay-groups]]): an early group, a median
[[parameter:hr-delay-early]] after the window, and a late group, [[parameter:hr-delay-late]] after it. Each recording
has its own delay, fitted from its ECG and HR ([[variable:numeric-delay-label]], [[variable:hr-delay-group-label]]).
The example recording is in the late group, with that group's median delay of [[value:hr-late-label-delay]].

**D. The recorder stamps it.** Vital Recorder polls the Solar8000 every [[value:solar8000-poll-gap]] and stamps each
value on arrival ([[study:numerics-derivation-release]]). A value therefore waits between none and all of one poll
before it is stamped. The delay fits model this wait as uniform, so d is the shortest time from the window's close to
the stamp, and the stamp comes d plus half a poll after the window closes, on average.

## How the record can be read (panels E and F)

Both panels show the joint probability density function (PDF) over the true time the window closed, relative to the
stamp, and the true heart rate, given the recorded pair (the white dot). The shading is the joint PDF, on the same
scale in both panels; the purple curves along the top and on the right are its marginal PDFs of time and of value.

**E. The stored record alone.** Without the atlas, a reader knows only that the record came from one of the two
groups of recordings. The PDF of the time is the sum of the two groups, weighted by their shares of the classified
recordings, each group spread by its delay's variation between recordings and by the wait for the poll. These are the
timing forms [as stamped, early group](variables/solar8000-hr.md#form-hr-early) and
[as stamped, late group](variables/solar8000-hr.md#form-hr-late).

**F. With the atlas.** The recording's own label gives its delay, with a standard uncertainty of
[[value:hr-label-se]] (the median of the labels' standard errors). What remains is mostly the wait for the poll,
which no label can remove: a flat-topped PDF one poll wide. This is the timing form
[after the per-case delay label](variables/solar8000-hr.md#form-hr-lab).

The value's PDF is the same in both panels: truncation is many-to-one, so no correction narrows it.

## How the figure is made

The figure is drawn by `tools/fig_concept_hr.py` in the [[software:metrology-atlas]] repository:

    python tools/fig_concept_hr.py . datasets/vitaldb/figures/worked-example-heart-rate.png

It reads the parameters [[parameter:hr-window]], [[parameter:hr-outlier-band]], [[parameter:hr-delay-early]],
[[parameter:hr-delay-late]] (median, standard deviation between recordings, and number of recordings, which give the
groups' shares), [[parameter:hr-late-label-delay]], [[parameter:hr-label-se]] and [[parameter:solar8000-poll-gap]].
The paper's PDF is drawn by the same script.
