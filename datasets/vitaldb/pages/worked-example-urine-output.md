# Worked example: a rounded urine volume

This page talks through Figure 3 of the paper on the Metrology Atlas: what a hand-charted urine volume in VitalDB
means. [Worked example: one heart-rate record](worked-example-heart-rate.md) is mostly about time; this one is about
value. Every number here is read from this atlas, from the release's own records and the fitted value model.

![Two panels sharing a volume axis from 0 to 400 mL. A: a histogram of recorded urine volumes per 5 mL, with tall spikes at every multiple of 50 mL and a smooth red curve of the true volumes beneath them; the bars at 100 and 260 mL are dark. B: the PDF of the true volume for a recorded 100 mL, a wide stepped shape from 50 to 150 mL built from four rounding modes, and for a recorded 260 mL, a narrow block from 255 to 265 mL from the 5 and 10 mL modes only.](figures/worked-example-urine-output.png)

*Figure 3 of the paper.*

## The record

Intraoperative urine output ([[variable:intraop-uo]]) is one total per case, charted by hand on the anaesthesia
record and stored in the clinical table. Its time is the whole anaesthesia, so the interest is in its value. A
recorded volume could have been read from the collection device to the nearest 5 or 10 mL, or rounded to 50 or 100 mL
when it was charted. Which of these happened is not recorded.

## A. What was recorded

The bars are the positive urine totals in the release, per 5 mL. They pile up on round numbers:
[[value:uo-share-on-100]] of records sit on a multiple of 100 mL, and [[value:uo-share-on-50]] on a multiple of 50 mL
that is not a multiple of 100 ([[parameter:uo-share-on-100]], [[parameter:uo-share-on-50]]). The volumes themselves
have no reason to favour round numbers; the people charting them do. This is digit preference, or heaping
([[study:heaping-screen-all-variables]]).

The red curve is the distribution of true volumes that the value model infers ([[study:value-model-intraop-uo]],
[[software:vitaldb-resolution]]). The model is a smooth density of true volumes (a log-spline, shifted by the length
of the anaesthesia) together with four rounding modes, each with its own probability: read to 5 mL, read to 10 mL,
rounded to 50 mL (only for true volumes within 20 mL of the multiple), and rounded to 100 mL. Fitted to the records,
it deconvolves the heaps: the spikes are explained by rounding, and what is left is the curve. The curve is averaged
over the recordings' anaesthesia durations and scaled to the same number of records.

## B. What two recorded values mean

For one record, the model gives the PDF of its true volume, given the recorded value: one part for each rounding mode
that could have produced it, weighted by how likely that mode is at that volume.

- **A recorded 100 mL** could have come from any of the four modes. Its true volume lies between
  [[value:uo-recorded-100-low|.0]] and [[value:uo-recorded-100-high|.0]] (95% interval), and only
  [[value:uo-recorded-100-fine|.0]] of the probability is on it having been read to 10 mL or finer.
- **A recorded 260 mL** is not a multiple of 50, so it can only have been read to 5 or 10 mL. Its true volume lies
  between [[value:uo-recorded-260-low|.0]] and [[value:uo-recorded-260-high|.0]].

The same variable, charted on the same record, carries an uncertainty seven or eight times larger for one recorded
value than for another. A model that treats every recorded volume as exact, or as exact to 5 mL, misses that.

Both PDFs are for a record whose department is not known: the model's rounding probabilities differ by department
(thoracic surgery charts more finely, gynaecology more coarsely), and with the department known the PDF narrows or
widens accordingly ([[study:value-model-intraop-uo]]).

## Where it is used

The same posterior is what the worked analyses that use urine output draw from:
[[example:urine-output-per-kg-per-hour]], [[example:oliguria-labels]], [[example:fluid-balance]] and
[[example:regression-with-rounding]].

## How the figure is made

The figure is drawn by `tools/fig_urine_heaping.py` in the [[software:metrology-atlas]] repository, from the release's
clinical table and the fitted model in [[software:vitaldb-resolution]]:

    python tools/fig_urine_heaping.py ../vitaldb/vitaldb-resolution $VITALDB --summary $W/worked_examples/urine_output.json datasets/vitaldb/figures/worked-example-urine-output.png

It writes, with the figure, a summary of every number on this page (aggregates only), from which the parameters above
are taken. The curve in A is drawn from 5 mL, the smallest positive record. The paper's PDF is drawn by the same
script.
