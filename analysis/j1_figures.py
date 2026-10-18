#!/usr/bin/env python3
"""
j1_figures.py -- Python mirror of j1_figures.m.

Same data, same logic, same validated palette. Exists because MATLAB was not
installed on the bench laptop when the 2026-10-18 figures were first needed;
`j1_figures.m` is the MATLAB deliverable and this is the reference rendering.
If the two ever disagree, the logs are the source of truth and both are wrong.

    python analysis/j1_figures.py              -> analysis/figs/*.png
    python analysis/j1_figures.py --show       -> interactive

Palette: dataviz reference instance, validated against a white surface.
  5-step ordinal blue ramp     ALL CHECKS PASS (monotone L, dL>=0.06,
                               light end 2.11:1, single hue, spread 3 deg)
  2-slot categorical blue/orange  ALL CHECKS PASS (all-pairs CVD dE 24.7,
                               normal-vision dE 33.6, both >=3:1 on white)
Rules honoured: one y-axis per plot, ordinal ramps for ordered quantities,
fixed categorical order, recessive chrome, legend whenever >=2 series.
"""
import argparse
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "..", "host", "logs")
FIGS = os.path.join(HERE, "figs")

RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
CAT = ["#2a78d6", "#eb6834", "#1baf7a"]
GOOD, CRIT = "#0ca30c", "#d03b3b"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
LW, LWT, MS = 2.0, 1.2, 7

DELTA = [("20261018-143719", 0.00139), ("20261018-143724", 0.00556),
         ("20261018-143729", 0.03190), ("20261018-143735", 0.12500),
         ("20261018-143742", 0.25000)]
KP = [("20261018-144553", 0.25), ("20261018-144557", 0.50),
      ("20261018-144601", 1.00), ("20261018-144605", 2.00),
      ("20261018-144609", 4.00)]
KP_DELTA = 0.03190
ABS_BAND_DEG = 0.36
BACKLASH_DEG = 0.23
CONTROL_HZ = 50
KV, N, IMAX = 330.0, 15.0, 10.0
KT = 9.5493 / KV
TQ_AVAIL = N * KT * IMAX          # 4.341 N.m at the output, lossless
TQ_CEIL = 1.0

REP = dict(
    label=["2026-08-26\nn=20", "2026-10-18\nn=50"],
    n=[20, 50],
    sigma=[float(np.mean([0.2168, 0.2282, 0.2333])), 0.2950],
    ref_range=[float(np.mean([0.3625, 0.3735, 0.3516])), 1.0162],
    d2=[3.736, 4.499],
)


def load(stamp):
    rows = []
    with open(os.path.join(LOGS, f"{stamp}_j1_step.csv")) as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("t_s"):
                continue
            a = line.strip().split(",")
            if len(a) >= 4:
                try:
                    rows.append([float(x) for x in a[:4]])
                except ValueError:
                    pass
    a = np.array(rows)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def settle(t, p, tgt, band):
    ins = np.abs(p - tgt) <= band
    for i in range(len(t)):
        if ins[i:].all():
            return float(t[i])
    return None


def travel(d, v=0.25, a=1.0):
    d = abs(d)
    return 2 * math.sqrt(d / a) if d <= v * v / a else 2 * (v / a) + (d - v * v / a) / v


def dress(ax):
    ax.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("bottom", "left"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=MUTED, direction="out", labelsize=9)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)
    ax.title.set_color(INK)


def save(fig, name, show):
    os.makedirs(FIGS, exist_ok=True)
    p = os.path.join(FIGS, name + ".png")
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    print(f"  wrote {os.path.relpath(p, os.path.join(HERE, '..'))}")
    if not show:
        plt.close(fig)


# ---------------------------------------------------------------- fig 1
def fig1(show):
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for i, (s, d) in enumerate(DELTA):
        t, p, _, _ = load(s)
        tgt = p[0] + d
        ax.plot(t, 100 * (p - tgt) / d, "-", color=RAMP[i], lw=LW,
                label=f"{d*360:.2f}°")
    ax.axhline(0, color=AXIS, lw=LWT)
    ax.set_xlim(0, 2.2); ax.set_ylim(-110, 20)
    ax.set_xlabel("time since command (s)")
    ax.set_ylabel("position error (% of commanded step)")
    ax.set_title("J1 step response, cold, kp = 225\n"
                 "monotone approach from below — no overshoot at any step size",
                 fontsize=11)
    ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=INK2,
              title="step size", title_fontsize=9)
    dress(ax); save(fig, "fig1_step_family", show)


# ---------------------------------------------------------------- fig 2
def fig2(show):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    d = np.array([x[1] for x in DELTA]) * 360
    br = np.array([x[1] for x in DELTA]) * 0.02 * 360
    fin, ok = [], []
    for s, dd in DELTA:
        t, p, _, _ = load(s)
        tgt = p[0] + dd
        fin.append(abs(p[-10:].mean() - tgt) * 360)
        ok.append(settle(t, p, tgt, abs(dd) * 0.02) is not None)
    fin, ok = np.array(fin), np.array(ok)
    ax.plot(d, br, "-o", color=CAT[0], lw=LW, ms=MS,
            label="relative band (2% of step)")
    ax.axhline(ABS_BAND_DEG, ls="--", color=CAT[1], lw=LW,
               label=f"absolute band ({ABS_BAND_DEG}°)")
    ax.plot(d, fin, "-s", color=INK2, lw=LWT, ms=MS, mfc="white",
            label="measured static error")
    xc = BACKLASH_DEG / 7.2 * 360
    ax.axvline(xc, ls=":", color=CRIT, lw=LW)
    ax.annotate(f"predicted crossover\n{xc:.1f}°", (xc * 1.15, 0.0125),
                color=CRIT, fontsize=9)
    ax.plot(d[ok], br[ok], "o", ms=MS + 7, mfc="none", mec=GOOD, mew=LW)
    ax.plot(d[~ok], br[~ok], "x", ms=MS + 6, mec=CRIT, mew=LW)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("commanded step (deg)")
    ax.set_ylabel("band or error (deg)")
    ax.set_title("Why the relative settling criterion fails on small steps\n"
                 "circle = settled, cross = “did not settle” (an artifact)",
                 fontsize=11)
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK2)
    dress(ax); save(fig, "fig2_crossover", show)


# ---------------------------------------------------------------- fig 3
def fig3(show):
    fig, ax = plt.subplots(figsize=(6.8, 5.4))
    ts, tj = [], []
    for s, d in DELTA:
        t, p, _, _ = load(s)
        tgt = p[0] + d
        ts.append(settle(t, p, tgt, ABS_BAND_DEG / 360))
        tj.append(travel(d))
    ts, tj = np.array(ts, float), np.array(tj, float)
    lim = (0.04, 2.0)
    ax.plot(lim, lim, "--", color=AXIS, lw=LWT)
    ax.annotate("y = x", (0.235, 0.33), color=MUTED, fontsize=9, rotation=40)
    for i, (s, d) in enumerate(DELTA):
        ax.plot(tj[i], ts[i], "o", ms=MS + 4, mfc=RAMP[i], mec="white", mew=1.8)
        ax.annotate(f"{d*360:.1f}°", (tj[i] * 1.14, ts[i] * 0.97),
                    fontsize=9, color=INK2)
    k = int(np.argmax(ts / tj))
    ax.annotate(f"{ts[k]/tj[k]:.1f}× — the only\nreal outlier",
                xy=(tj[k] * 1.04, ts[k] * 0.99),
                xytext=(tj[k] * 0.33, ts[k] * 1.55),
                color=CRIT, fontsize=9,
                arrowprops=dict(arrowstyle="->", color=CRIT, lw=1.2))
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    ax.set_xlabel("trapezoidal traverse time, predicted (s)")
    ax.set_ylabel("measured settling time (s)")
    ax.set_title("“Settling time” is the trajectory generator,\n"
                 "not joint dynamics — four of five land on y = x", fontsize=11)
    dress(ax); save(fig, "fig3_trajectory", show)


# ---------------------------------------------------------------- fig 4
def fig4(show):
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    dt = np.concatenate([np.diff(load(s)[0]) * 1000 for s, _ in DELTA + KP])
    ax.hist(dt, bins=np.arange(13, 33.5, 0.5), color=CAT[0], edgecolor="white")
    nom = 1000 / CONTROL_HZ
    ax.axvline(nom, ls="--", color=CRIT, lw=LW)
    top = ax.get_ylim()[1]
    ax.annotate(f"nominal {nom:.0f} ms\n(CONTROL_HZ = {CONTROL_HZ})",
                (nom * 1.02, top * 0.80), color=CRIT, fontsize=9)
    mu = dt.mean()
    ax.annotate(f"measured mean {mu:.2f} ms\n= {1000/mu:.1f} Hz "
                f"({(1000/mu)/CONTROL_HZ:.2f}× nominal)",
                (13.6, top * 0.62), color=INK, fontsize=9)
    ax.set_xlabel("interval between samples (ms)")
    ax.set_ylabel("count")
    ax.set_title(f"Host loop runs at {1000/mu:.1f} Hz, not 50 Hz  "
                 f"(n = {len(dt)} intervals)\n"
                 "quantised to the 15.6 ms Windows scheduler tick, "
                 "0.7% double ticks", fontsize=11)
    ax.set_xlim(13, 33)
    dress(ax); save(fig, "fig4_jitter", show)


# ---------------------------------------------------------------- fig 5
def fig5(show):
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.3))
    x = np.array([k for _, k in KP])
    ts, fin = [], []
    for s, k in KP:
        t, p, _, _ = load(s)
        tgt = p[0] + KP_DELTA
        ts.append(settle(t, p, tgt, ABS_BAND_DEG / 360))
        fin.append((p[-10:].mean() - tgt) * 360)
    good = np.array([v if v is not None else np.nan for v in ts], float)
    fin = np.array(fin)

    ax = axes[0]
    ax.plot(x, good, "-o", color=CAT[0], lw=LW, ms=MS)
    bad = np.isnan(good)
    if bad.any():
        ax.plot(x[bad], np.zeros(bad.sum()), "x", ms=MS + 6, mec=CRIT, mew=LW)
        ax.annotate("never settled", (x[bad][0], 0.06), color=CRIT, fontsize=9)
    ax.set_xscale("log"); ax.set_xticks(x)
    ax.set_xticklabels([f"{v:g}" for v in x])
    ax.set_xlabel("kp_scale  (effective kp = 225 × scale)")
    ax.set_ylabel(f"settling time, {ABS_BAND_DEG}° band (s)")
    ax.set_title("Settling", fontsize=11); dress(ax)

    ax = axes[1]
    ax.bar(np.arange(len(x)), np.abs(fin), 0.6, color=CAT[0], edgecolor="white")
    ax.axhline(ABS_BAND_DEG, ls="--", color=CAT[1], lw=LW)
    ax.annotate(f"repeatability floor, {ABS_BAND_DEG}°", (0.1, ABS_BAND_DEG * 1.1),
                color=CAT[1], fontsize=9)
    ax.set_xticks(np.arange(len(x)))
    ax.set_xticklabels([f"{v:g}" for v in x])
    ax.set_xlabel("kp_scale"); ax.set_ylabel("|static error| (deg)")
    ax.set_title("Static error", fontsize=11); dress(ax)

    fig.suptitle(f"Raising stiffness settles {good[2]/np.nanmin(good):.1f}× faster "
                 "with no ringing — but n = 1 per cell, one step size, unloaded",
                 fontsize=10.5, color=INK, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, "fig5_gain_sweep", show)


# ---------------------------------------------------------------- fig 6
def fig6(show):
    fig, ax = plt.subplots(figsize=(7.8, 4.6))
    for i, (s, d) in enumerate(DELTA):
        t, _, _, q = load(s)
        ax.plot(t, np.abs(q), "-", color=RAMP[i], lw=LW, label=f"{d*360:.2f}°")
    ax.axhline(TQ_CEIL, ls="--", color=CAT[1], lw=LW, label="ceiling used")
    ax.axhline(TQ_AVAIL, ls=":", color=CRIT, lw=LW, label="available at 10 A")
    ax.annotate(f"{TQ_AVAIL:.2f} N·m available at {IMAX:.0f} A",
                (1.25, TQ_AVAIL * 0.92), color=CRIT, fontsize=9)
    ax.annotate("max_torque ceiling used, 1.0 N·m", (1.25, TQ_CEIL * 1.08),
                color=CAT[1], fontsize=9)
    ax.set_xlim(0, 2.2); ax.set_ylim(0, TQ_AVAIL * 1.1)
    ax.set_xlabel("time since command (s)")
    ax.set_ylabel("|torque| at the output, lossless-referred (N·m)")
    ax.set_title("Torque never approached the envelope\n"
                 "peak 0.80 N·m = 18% of available; the ceiling itself was only 23%",
                 fontsize=11)
    ax.legend(frameon=False, loc="center right", fontsize=9, labelcolor=INK2, ncol=2)
    dress(ax); save(fig, "fig6_torque", show)


# ---------------------------------------------------------------- fig 7
def fig7(show):
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.5))
    sd = np.array(REP["sigma"]); n = np.array(REP["n"])
    rel = 1.96 / np.sqrt(2 * (n - 1))

    ax = axes[0]
    for i in range(2):
        ax.bar(i, sd[i], 0.5, color=CAT[i], edgecolor="white")
        ax.errorbar(i, sd[i], yerr=sd[i] * rel[i], color=INK, lw=LW,
                    capsize=9, fmt="none")
        ax.annotate(f"±{100*rel[i]:.0f}%", (i, sd[i] * (1 + rel[i]) + 0.02),
                    ha="center", fontsize=9, color=INK2)
    ax.set_xticks([0, 1]); ax.set_xticklabels(REP["label"])
    ax.set_ylabel("σ of landing error (deg)"); ax.set_ylim(0, 0.46)
    ax.set_title("Landing-error σ\nF = 1.70, p = 0.21 — NOT significant",
                 fontsize=11)
    dress(ax)

    ax = axes[1]
    raw = np.array(REP["ref_range"]); nrm = raw / np.array(REP["d2"])
    w = 0.36; idx = np.arange(2)
    ax.bar(idx - w / 2, raw, w, color=CAT[0], edgecolor="white",
           label="raw range (max − min)")
    ax.bar(idx + w / 2, nrm, w, color=CAT[1], edgecolor="white",
           label="σ = range / d₂")
    ax.set_xticks(idx); ax.set_xticklabels(REP["label"])
    ax.set_ylabel("reference-point scatter (deg)")
    ax.set_title(f"Range vs σ at the reference point\n"
                 f"raw reads {raw[1]/raw[0]:.2f}×; normalised for n it is "
                 f"{nrm[1]/nrm[0]:.2f}×", fontsize=11)
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK2)
    dress(ax)

    fig.suptitle("Comparing ranges at different n is invalid — the headline "
                 "0.36° was a range of 20\nno error histogram is possible: "
                 "do_random never saved per-move samples",
                 fontsize=10.5, color=INK, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    save(fig, "fig7_repeatability", show)


# ---------------------------------------------------------------- fig 8
def fig8(show):
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.0))
    ax = axes[0]
    v = [0.25, 0.5, KV * 24 / math.sqrt(3) / 60 / N, KV * 24 / 60 / N]
    nm = ["used this session", "servo.max_velocity", "voltage-limited",
          "no-load theoretical"]
    for i, val in enumerate(v):
        ax.barh(i, val, 0.55, color=RAMP[i], edgecolor="white")
        ax.annotate(f"{val:.2f}", (val * 1.07, i), va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(4)); ax.set_yticklabels(nm, fontsize=9)
    ax.set_xscale("log"); ax.set_xlim(0.15, 20)
    ax.set_xlabel("output velocity (rev/s)")
    ax.set_title(f"Velocity: capped {v[3]/v[1]:.0f}× below capability", fontsize=11)
    dress(ax)

    ax = axes[1]
    t = [0.802, TQ_CEIL, TQ_AVAIL]
    nm2 = ["peak actually drawn", "max_torque ceiling", "available at 10 A"]
    for i, val in enumerate(t):
        ax.barh(i, val, 0.55, color=RAMP[i + 1], edgecolor="white")
        ax.annotate(f"{val:.2f} N·m  ({100*val/TQ_AVAIL:.0f}%)",
                    (val + 0.08, i), va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(3)); ax.set_yticklabels(nm2, fontsize=9)
    ax.set_xlim(0, TQ_AVAIL * 1.55)
    ax.set_xlabel("output torque, lossless-referred (N·m)")
    ax.set_title("Torque: 23% of the envelope was ever requested", fontsize=11)
    dress(ax)

    fig.suptitle("Both axes of the envelope were barely explored — "
                 "by configuration, not by physics", fontsize=10.5, color=INK, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, "fig8_capability", show)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.show:
        matplotlib.use("TkAgg")
    print("J1 figures, 2026-10-18 session:")
    for f in (fig1, fig2, fig3, fig4, fig5, fig6, fig7, fig8):
        f(a.show)
    if a.show:
        plt.show()
    print("\n8 figures generated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
