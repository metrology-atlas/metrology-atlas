# SPDX-License-Identifier: MIT
"""Figure 1 of the paper and the atlas page "Worked example: one heart-rate record": how one heart-rate record was made
(A-D), its measurement model, and how it can be read (E, F). Conceptual: the ECG is synthetic, and the recording's
delay is the late group's median; every number that describes VitalDB is read from the atlas's parameters.

    python tools/fig_concept_hr.py ATLAS_REPO OUT [OUT ...]      # e.g. datasets/vitaldb/figures/worked-example-heart-rate.png

Drawn at print size (160 mm wide). Each OUT is written in the format its extension names (PNG at 200 dpi). Parameters read (datasets/vitaldb/parameters):
hr-window and hr-outlier-band (the monitor's rule); hr-delay-early and hr-delay-late (each group's median delay, its
SD between recordings, and its number of recordings, which give the shares); hr-late-label-delay and hr-label-se (one
recording's delay and its standard uncertainty); solar8000-poll-gap (the recorder's poll).
Measurement model: value = floor(60 / mean of the last N R-R intervals within b of their median); stamp = window close
+ d + phi, phi uniform on [0, g). E and F share one density scale.
"""
import sys
from pathlib import Path

import matplotlib
import numpy as np
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

P = Path(sys.argv[1]) / "datasets" / "vitaldb" / "parameters"


def par(pid):
    return yaml.safe_load((P / f"{pid}.yaml").read_text(encoding="utf-8"))


early, late, one, se, gap = (par(p) for p in ("hr-delay-early", "hr-delay-late", "hr-late-label-delay", "hr-label-se",
                                              "solar8000-poll-gap"))
G = float(gap["value"])
n_e, n_l = early["spread"]["n"], late["spread"]["n"]
W_E, W_L = n_e / (n_e + n_l), n_l / (n_e + n_l)
D_E, S_E = float(early["value"]), float(early["spread"]["sd"])
D_L, S_L = float(late["value"]), float(late["spread"]["sd"])
D_1, S_1 = float(one["value"]), float(se["value"])
N_IV = int(par("hr-window")["value"])                     # the HR rule (hr-derivation): the last N R-R intervals,
BAND = float(par("hr-outlier-band")["value"])              # those within b% of their median (10-25% fit equally)


# Drawn at print size: the paper's text width (160 mm), so the type is the size it prints at. Positions in inches.
W, H = 6.3, 7.5
FS, FT, FH = 6.5, 7.2, 8.5                                # body, panel titles, section headings (pt)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": FS, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#5a6170", "xtick.color": "#5a6170",
                     "ytick.color": "#5a6170", "axes.labelcolor": "#1b2333", "axes.linewidth": 0.6,
                     "xtick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.width": 0.6,
                     "ytick.major.size": 2.5, "xtick.labelsize": FS, "ytick.labelsize": FS, "axes.labelsize": FS,
                     "axes.labelpad": 2})
INK, MUTED, ORANGE, DARKOR = "#1b2333", "#5a6170", "#e8a33d", "#a86a10"
BLUE = "#2a78d6"
MARG = "#8a4fbf"                                          # the 1D marginal PDFs, apart from the 2D joint PDF
rng = np.random.default_rng(3)

# --- one synthetic heartbeat sequence near 72.5 bpm, with breathing variation (illustration)
rr = 60 / 72.5 + 0.03 * np.sin(2 * np.pi * np.arange(40) / 4.5) + rng.normal(0, 0.008, 40)
beats = np.cumsum(rr)
k_end = 17
t_end = beats[k_end]
iv = np.diff(beats[k_end - N_IV:k_end + 1])
hr_exact = 60 / iv[np.abs(iv - np.median(iv)) <= BAND / 100 * np.median(iv)].mean()
hr_rec = np.floor(hr_exact)
t_out = t_end + D_1
t_stamp = np.ceil(t_out / G) * G
fs = 250
t = np.arange(0, beats[25], 1 / fs)
ecg = sum(np.exp(-((t - b) / 0.012) ** 2) - 0.25 * np.exp(-((t - b - 0.25) / 0.05) ** 2) for b in beats[:26])
ecg += 0.03 * rng.normal(size=t.size)

fig = plt.figure(figsize=(W, H))


def axes(x, y, w, h):
    return fig.add_axes([x / W, y / H, w / W, h / H])


def text(x, y, s, **kw):
    fig.text(x / W, y / H, s, **kw)


def title(ax, s):
    ax.set_title(s, loc="left", fontsize=FT, pad=3, color=INK)


text(0.05, 7.36, "How the record was made", fontsize=FH, fontweight="bold", color=INK)

# A. the heart
ax = axes(0.15, 5.7, 2.85, 1.25)
ax.plot(t, ecg, color="0.3", lw=0.5)
for b in beats[k_end - N_IV:k_end + 1]:
    ax.axvline(b, color=BLUE, lw=0.4, alpha=0.5)
ax.set_xlim(beats[6], beats[20]); ax.set_yticks([]); ax.set_xlabel("true time (s)")
title(ax, "A  The heart beats: each R peak is an event")

# B. the monitor
ax = axes(3.35, 5.7, 2.85, 1.25)
ax.plot(t, ecg, color="0.72", lw=0.45)
ax.axvspan(beats[k_end - N_IV], t_end, color=ORANGE, alpha=0.25, lw=0)
ax.annotate("", (t_end, 1.25), (beats[k_end - N_IV], 1.25), arrowprops=dict(arrowstyle="<->", color=ORANGE, lw=0.8))
ax.text((beats[k_end - N_IV] + t_end) / 2, 1.33, f"the support: last {N_IV} R–R intervals", ha="center", color=DARKOR)
ax.axvline(t_end, color=ORANGE, lw=1)
ax.text(t_end + 0.15, 0.95, f"{hr_exact:.1f} bpm\n→ {hr_rec:.0f}", va="top", color=INK)
ax.set_xlim(beats[6], t_end + 2.6); ax.set_ylim(-0.5, 1.55); ax.set_yticks([]); ax.set_xlabel("true time (s)")
title(ax, "B  The monitor averages and truncates")

# C. the value is processed and sent; D. the recorder stamps it at its next poll
x0, x1 = t_end - 1.0, t_stamp + 0.8
for i, (ttl, last) in enumerate((("C  The value is processed and sent", False), ("D  The recorder stamps it", True))):
    ax = axes(0.15 + 3.2 * i, 4.2, 2.85, 0.95)
    ax.set_xlim(x0, x1); ax.set_ylim(0, 1); ax.set_yticks([]); ax.set_xlabel("true time (s)")
    title(ax, ttl)
    ax.axvline(t_end, color=ORANGE, lw=1, alpha=0.4 if last else 1)
    ax.plot([t_out], [0.5], "o", color="0.3", ms=3)
    if not last:
        ax.text(t_end + 0.12, 0.93, "window\ncloses", va="top", color=DARKOR)
        ax.annotate("", (t_out, 0.5), (t_end, 0.5), arrowprops=dict(arrowstyle="->", color="0.3", lw=0.9))
        ax.text((t_end + t_out) / 2, 0.58, f"this recording's delay d: {D_1:.1f} s", ha="center")
        ax.text(t_out, 0.4, "value ready\nat the recorder", ha="center", va="top")
    else:
        for k in np.arange(np.ceil(x0 / G) * G, x1, G):
            ax.plot([k, k], [0.04, 0.16], color="0.55", lw=0.8)
        ax.text(x0 + 0.1, 0.2, f"the recorder polls every {G:g} s", color=MUTED)
        ax.annotate("", (t_stamp, 0.5), (t_out, 0.5), arrowprops=dict(arrowstyle="->", color="0.3", lw=0.9))
        ax.text(t_out - 0.15, 0.62, f"waits for the poll:\nφ, 0 to {G:g} s", ha="right", va="center")
        ax.plot([t_stamp], [0.5], "o", color="white", mec="k", ms=6, mew=0.8, zorder=5)
        ax.text(t_stamp + 0.15, 0.95, f"stamped: {hr_rec:.0f} bpm", ha="right", va="top", fontweight="bold")

text(0.05, 3.64, "Measurement model of this record", fontsize=FT, fontweight="bold", color=INK)
text(0.05, 3.47, f"Value:  recorded = floor(60 / mean of the last {N_IV} R–R intervals within about {BAND:g}% of their "
     "median),", color=INK)
text(0.52, 3.33, "so the true value lies in [recorded, recorded + 1).", color=INK)
text(0.05, 3.17, f"Time:    stamp = window close + d + φ;  d = the recording's delay;  φ uniform on [0, {G:g}) s, the wait "
     "for the poll.", color=INK)
text(0.05, 2.92, "How the record can be read", fontsize=FH, fontweight="bold", color=INK)

TT = np.linspace(-8.5, 1, 600)


def time_pdf(groups):
    """Each group's share of the PDF of the true time the window closed, relative to the stamp, per second:
    close = stamp - d - phi, d ~ N(d, s) between recordings, phi ~ U[0, G)."""
    phs = np.linspace(0, G, 201)
    return [w * np.mean([np.exp(-0.5 * ((TT + d + ph) / s) ** 2) / (s * np.sqrt(2 * np.pi)) for ph in phs], axis=0)
            for w, d, s in groups]


GROUPS_E = [(W_E, D_E, S_E), (W_L, D_L, S_L)]
GROUPS_F = [(1.0, D_1, S_1)]
PMAX = max(sum(time_pdf(GROUPS_E)).max(), sum(time_pdf(GROUPS_F)).max())   # one density scale for E and F
CMAP = matplotlib.colors.LinearSegmentedColormap.from_list("joint", ["white", BLUE])


def pdf_panel(x, ttl, groups, names=None):
    """Joint PDF over the true time the window closed (relative to the stamp) and the true value, shaded on the same
    density scale in both panels, with its marginals: time above (with each group's share where there are several),
    value on the right. The value is uniform over one bpm, so the joint density is the time PDF times 1/bpm."""
    y, w, h = 0.98, 2.3, 1.2
    ax = axes(x, y, w, h)
    vv = np.linspace(hr_rec - 0.7, hr_rec + 1.7, 300)
    pv = ((vv >= hr_rec) & (vv < hr_rec + 1)).astype(float)
    comps = time_pdf(groups)
    pt = sum(comps)
    ax.imshow(np.outer(pv, pt), extent=[TT[0], TT[-1], vv[0], vv[-1]], origin="lower", aspect="auto", cmap=CMAP,
              vmin=0, vmax=PMAX)
    ax.plot([0], [hr_rec], "o", color="white", mec="k", ms=5, mew=0.8, zorder=5)
    ax.text(0.2, hr_rec - 0.12, "recorded\npair", va="top", fontsize=6)
    ax.set_xlim(TT[0], TT[-1]); ax.set_ylim(vv[0], vv[-1])
    ax.set_xticks([-8, -6, -4, -2, 0]); ax.set_yticks([72, 73])
    ax.set_xlabel("true time the window closed,\nrelative to the stamp (s)")
    ax.set_ylabel("true heart rate (bpm)")
    tp = axes(x, y + h + 0.03, w, 0.42)
    tp.axis("off"); tp.set_xlim(TT[0], TT[-1]); tp.set_ylim(0, 1.45)
    if len(comps) > 1:
        for c, nm, ls, ha in zip(comps, names, ("--", ":"), ("left", "right")):
            mc = c / PMAX > 0.004
            tp.plot(TT[mc], (c / PMAX)[mc], color="0.35", lw=0.7, ls=ls)
            i = int(np.argmax(c))
            tp.text(TT[i] + (0.6 if ha == "left" else -0.6), c[i] / PMAX + 0.1, nm, ha=ha, fontsize=5.8, color="0.35")
    m = pt / PMAX > 0.004
    tp.fill_between(TT, pt / PMAX, where=m, color=MARG, alpha=0.18, lw=0)
    tp.plot(TT[m], (pt / PMAX)[m], color=MARG, lw=1)
    tp.text(TT[0], 0.08, "time PDF", fontsize=6, color=MARG)
    title(tp, ttl)
    sd = axes(x + w + 0.05, y, 0.22, h)
    sd.axis("off"); sd.set_ylim(vv[0], vv[-1]); sd.set_xlim(0, 1.6)
    mv = (vv >= hr_rec) & (vv <= hr_rec + 1)
    sd.fill_betweenx(vv[mv], pv[mv], color=MARG, alpha=0.18, lw=0)
    sd.plot(np.r_[0, pv[mv], 0], np.r_[hr_rec, vv[mv], hr_rec + 1], color=MARG, lw=1)
    sd.plot([0, 0], [vv[0], vv[-1]], color=MARG, lw=0.5, alpha=0.5)
    sd.text(0.05, hr_rec + 1.15, "value\nPDF", fontsize=6, color=MARG)


pdf_panel(0.45, "E  The stored record alone", GROUPS_E, names=[f"early group, {W_E:.0%}", f"late group, {W_L:.0%}"])
pdf_panel(3.55, "F  With the atlas: this recording's delay", GROUPS_F)

from matplotlib.lines import Line2D  # noqa: E402
cb = axes(0.45, 0.13, 1.3, 0.07)
cb.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto", cmap=CMAP, extent=[0, 1, 0, 1])
cb.set_yticks([]); cb.set_xticks([0, 1]); cb.set_xticklabels(["0", "highest density"], fontsize=6)
cb.tick_params(length=1.5, pad=1)
for s_ in cb.spines.values():
    s_.set_visible(False)
text(0.45, 0.25, "joint PDF over true time and true value (2D), one scale for E and F", fontsize=6, color=INK)
fig.legend(handles=[Line2D([], [], color=MARG, lw=1, label="marginal PDF of time, or of value (1D)"),
                    Line2D([], [], color="0.35", lw=0.7, ls="--", label="one group's share of the time PDF")],
           loc="lower left", frameon=False, fontsize=6, bbox_to_anchor=(3.55 / W, 0.02), handlelength=2.2,
           borderaxespad=0)
for out in sys.argv[2:]:
    fig.savefig(out, dpi=200 if out.endswith(".png") else None)
print(f"groups {D_E:g}/{D_L:g} s (SD {S_E:g}/{S_L:g}; {W_E:.1%}/{W_L:.1%}), this recording {D_1:g} s (u {S_1:g}), "
      f"poll {G:g} s; example value {hr_exact:.2f} -> {hr_rec:.0f}")
