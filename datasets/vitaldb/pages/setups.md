# Recording setups

Many timing results in the atlas hold per **recording setup**: a delay, a drift rate or a correction mode that is
the same for every recording made on one setup and differs between setups. This page says what a setup is, how the
atlas recognises one, what depends on it, and where the uncertainty models should use it.

## What a setup is

A setup is the equipment that made a recording: the recorder PC in one operating theatre, its serial cables, and
the particular units plugged into it (one SNUADC converter, one BIS monitor, one patient monitor and its oximeter
module, one ventilator). The release never names a theatre, a PC or a serial number. It does record, in every
`.vital` file, each device's Windows serial port (COM port), and those ports recognise setups well.

## How the atlas recognises a setup

1. **The PC key** (the working definition): the serial ports of the four core devices, SNUADC · Solar8000 · Primus
   · BIS, for example `COM4 · COM9 · COM10 · COM20`. It is complete for 90% of recordings. Port numbers are
   assigned by Windows on each PC, so one port number alone is a poor key (the SNUADC was on COM4 in 2,824
   recordings, on several PCs), but the combination of four rarely repeats across PCs: [[study:hr-delay-groups]]
   found 44 PCs this way. Knowing the PC key puts the SNUADC's drift within 3 ppm of its setup's median in 97% of
   cases, against 34% for the release's median.
2. **Coarser keys**, where the PC key is incomplete: one device's port (75% within 3 ppm for the SNUADC), or the
   SNUADC and BIS ports together (96%).
3. **Clock fingerprints**, which need no port: a device's crystal runs at its own rate to about 1 ppm, so drift
   identifies physical units ([[study:drift-units]]), and the oximeter's frame clock identifies its module
   ([[observation:oximeter-frame-clock-fingerprint]]). They can also split one PC key into the different units it
   carried over the years.

Some results were grouped differently before this page existed: the PPG delays by the SNUADC port plus its
correction mode ([[code:vitaldb-bench/tools/setup_offsets.py]]), the drift units by port pairs. They are coarser
versions of the PC key. A setup is not the same as a correction mode: one setup can record in either mode, and the
mode changes some constants ([[observation:eeg-ecg-offset-by-mode]]). None of these keys identifies a theatre, a
date or a patient.

## What varies by setup

| Quantity | Range across setups | Within a setup | Evidence |
|---|---|---|---|
| PLETH device delay | 368–399 ms | tight | [[observation:ppg-hardware-delay]], [[parameter:pleth-chain-delay]], [[study:ppg-offset-reference]] |
| PLETH sawtooth creep rate | 18–52 ppm | fixed | [[observation:ppg-sawtooth]], [[parameter:pleth-sawtooth-rate]], [[study:ppg-sawtooth]] |
| Oximeter frame clock against the SNUADC | +24 to +84 ppm | about 2 ppm | [[observation:oximeter-frame-clock-fingerprint]], [[parameter:pleth-frame-clock-rate]] |
| SNUADC correction mode (step or frequent) | 0–68% frequent by port | mostly one mode | [[observation:snuadc-mode-setups]] |
| SNUADC step-mode drift | medians −44 to −81 ppm by setup | within 3 ppm in 97% of cases | [[parameter:snuadc-step-rate]], [[observation:device-drift-by-setup]] |
| BIS drift | medians 18–55 ppm by setup | within 3 ppm in 83% of cases | [[parameter:bis-rate]], [[observation:device-drift-by-setup]] |
| EEG minus ECG constant offset | −803 ms step, −690 ms frequent mode | tight within a port or unit | [[observation:eeg-ecg-offset-by-mode]], [[parameter:eeg-ecg-offset]] |
| Solar8000 heart-rate delay group (1.9 or 4.2 s) | set by the PC | 94% of cases follow their PC's majority | [[observation:hr-two-delay-groups]], [[study:hr-delay-groups]] |

## The setup register

<!-- setups:register -->

Ports are recorded for almost every device: the four core devices' ports, and so the PC key, are complete for 5,755 of 6,388 recordings (90%); the rest lack a BIS or have no port for one device. They form 65 distinct PC keys, 37 of them with at least 20 recordings (5,631 recordings).

**How much a grouping tells you about a device's drift.** Share of cases whose drift is within 3 ppm of their group's median, against within 3 ppm of the median of all cases (groups with at least 5 cases):

| Device | By its own port | By SNUADC + BIS ports | By PC key | Release median |
|---|---|---|---|---|
| SNUADC, step mode | 75% (14 ports) | 96% (20 pairs) | 97% (23 keys) | 34% |
| BIS | 74% (19 ports) | — | 83% (37 keys) | 17% |

**Setups with at least 20 recordings**, by PC key (SNUADC · Solar8000 · Primus · BIS port). Drifts are medians over the cases where they were measured.

| PC key | Recordings | SNUADC frequent mode | SNUADC step drift (ppm) | BIS drift (ppm) |
|---|---|---|---|---|
| COM4 · COM6 · COM5 · COM8 | 755 | 92% of 37 | -30.3 (n=3) | 44.1 (n=186) |
| COM4 · COM12 · COM11 · COM14 | 428 | 20% of 5 | -44.3 (n=4) | 50.5 (n=178) |
| COM19 · COM26 · COM27 · COM29 | 359 | 14% of 7 | -50.6 (n=6) | 32.3 (n=93) |
| COM4 · COM9 · COM10 · COM20 | 275 | 0% of 61 | -80.3 (n=61) | 18.6 (n=64) |
| COM4 · COM5 · COM6 · COM8 | 267 | 100% of 8 | — | 54.7 (n=44) |
| COM3 · COM4 · COM5 · COM7 | 245 | 0% of 23 | -61.1 (n=23) | 25.1 (n=60) |
| COM45 · COM42 · COM43 · COM39 | 219 | 36% of 25 | -60.1 (n=16) | 18.8 (n=37) |
| COM18 · COM13 · COM14 · COM6 | 216 | 0% of 38 | -72.3 (n=38) | 18.2 (n=48) |
| COM12 · COM4 · COM5 · COM7 | 207 | 30% of 30 | -60.8 (n=21) | 21.5 (n=75) |
| COM4 · COM5 · COM6 · COM3 | 196 | 0% of 2 | — | 49.4 (n=53) |
| COM7 · COM4 · COM5 · COM9 | 183 | 0% of 27 | -67.2 (n=27) | 18.9 (n=51) |
| COM25 · COM26 · COM27 · COM29 | 168 | 0% of 13 | -59.7 (n=13) | 30.9 (n=56) |
| COM8 · COM42 · COM43 · COM39 | 153 | 33% of 18 | -60.2 (n=12) | 18.7 (n=26) |
| COM13 · COM26 · COM27 · COM19 | 141 | 4% of 26 | -68.4 (n=25) | 17.4 (n=56) |
| COM14 · COM4 · COM5 · COM7 | 137 | 100% of 1 | — | 26.3 (n=36) |
| COM4 · COM26 · COM27 · COM29 | 132 | 14% of 14 | -64.9 (n=12) | 30.8 (n=25) |
| COM4 · COM9 · COM10 · COM12 | 131 | 4% of 26 | -65.1 (n=25) | 30.5 (n=44) |
| COM15 · COM26 · COM27 · COM29 | 123 | 100% of 9 | — | 29.9 (n=23) |
| COM14 · COM10 · COM11 · COM18 | 114 | 0% of 3 | -46.6 (n=3) | 25.6 (n=38) |
| COM4 · COM11 · COM12 · COM8 | 114 | 0% of 11 | -60.1 (n=11) | 23.6 (n=30) |
| COM8 · COM14 · COM15 · COM4 | 110 | 33% of 12 | -60.5 (n=8) | 21.0 (n=20) |
| COM4 · COM5 · COM6 · COM20 | 104 | 0% of 20 | -81.5 (n=20) | 17.2 (n=27) |
| COM13 · COM14 · COM15 · COM19 | 97 | 4% of 24 | -67.1 (n=23) | 18.4 (n=39) |
| COM4 · COM5 · COM6 · COM12 | 80 | 0% of 18 | -67.1 (n=18) | 28.2 (n=39) |
| COM13 · COM4 · COM5 · COM23 | 77 | 0% of 9 | -66.2 (n=9) | 19.3 (n=20) |
| COM14 · COM21 · COM22 · COM18 | 75 | 0% of 5 | -47.4 (n=5) | 24.7 (n=18) |
| COM13 · COM4 · COM5 · COM9 | 62 | 8% of 12 | -66.9 (n=11) | 19.5 (n=18) |
| COM9 · COM10 · COM11 · COM16 | 59 | 0% of 13 | -80.5 (n=13) | 17.8 (n=18) |
| COM31 · COM28 · COM29 · COM34 | 54 | 0% of 4 | -66.8 (n=4) | 18.2 (n=18) |
| COM9 · COM15 · COM16 · COM20 | 54 | 0% of 5 | -68.1 (n=5) | 26.4 (n=20) |
| COM3 · COM15 · COM16 · COM20 | 51 | 0% of 1 | — | 22.9 (n=16) |
| COM15 · COM25 · COM26 · COM30 | 46 | 0% of 2 | — | 24.4 (n=23) |
| COM15 · COM13 · COM14 · COM22 | 46 | 0% of 3 | -62.2 (n=3) | 19.9 (n=31) |
| COM4 · COM11 · COM12 · COM3 | 44 | — | — | 49.1 (n=14) |
| COM32 · COM28 · COM27 · COM30 | 44 | — | — | 42.6 (n=9) |
| COM4 · COM13 · COM14 · COM6 | 33 | 7% of 14 | -79.2 (n=13) | 18.8 (n=9) |
| COM15 · COM27 · COM26 · COM29 | 32 | 100% of 4 | — | 28.6 (n=9) |

<!-- /setups:register -->

## Where the uncertainty models should use the setup

Several parameters are quoted over all recordings although they are known per setup. For a recording whose setup is
known, the per-setup value has a much smaller uncertainty; the all-recordings range applies only when the setup is
unknown. The SNUADC step drift ([[parameter:snuadc-step-rate]]) and the BIS drift ([[parameter:bis-rate]]) now list
their values per setup; the rest are on the work plan.

- **PLETH delay and sawtooth rate.** The PAT correction works far better with the setup's creep rate as a prior:
  without it, few teeth reach a confident tier ([[example:pulse-arrival-time]]).
- **SNUADC and BIS drift.** A track without a whole tooth already takes its port's or unit's typical rate in the
  stamp model ([[study:snuadc-stamp-sawtooth]]); the uncertainty of that rate should be the port's spread, not the
  release's.
- **Numeric delays.** The heart-rate delay is two-valued and set by the PC; its uncertainty for a known PC is far
  smaller than the 1.9–4.2 s range.
- **Planner and clock domains.** The synchronisation planner uses one drift per clock domain; per-setup drift would
  tighten its windows for recordings whose setup is known.

## Open questions

They are kept, with what would settle each, on [[study:setup-identification]], and appear with every other study's
on the [Open questions](open-questions.md) page.
