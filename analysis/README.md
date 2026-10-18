# analysis/

Offline plotting for the J1 characterization data. **Nothing here touches
hardware** — that separation is deliberate, so a plotting bug can never cost a
bench session.

Everything reads from `../host/logs/`. The logs are the single source of truth;
if MATLAB and Python ever disagree, both are wrong.

## Running it

```matlab
% MATLAB, from the repo root
addpath('analysis'); j1_figures('analysis/figs')
```

```bash
# Python, from the repo root
python analysis/j1_figures.py            # writes analysis/figs/*.png
python analysis/j1_figures.py --show     # interactive
```

> **The MATLAB path is untested.** MATLAB was not installed on the bench laptop
> when these were written, so `j1_figures.m` has been written carefully and
> reviewed but never executed. The committed PNGs were produced by the Python
> mirror. If you run the MATLAB and it errors, that is expected to be a
> syntax-level fix, not a logic one — the numerics are identical and were
> verified against the logs independently.

## Files

| File | Role |
|---|---|
| `j1_figures.m` | MATLAB: all eight figures |
| `j1_figures.py` | Python mirror, same logic and palette |
| `j1_style.m` | colours and chrome (validated palette, see below) |
| `j1_manifest.m` | which run is which; machine constants read from the board |
| `j1_load_run.m` | robust CSV reader for `*_j1_step.csv` |
| `j1_settle.m` | settling time under a given band |
| `j1_travel_time.m` | trapezoidal traverse time — mirrors `travel_time()` in the console |
| `figs/` | rendered PNGs |

## The figures

| # | Figure | What it shows |
|---|---|---|
| 1 | `fig1_step_family` | Step response across step size — monotone, no overshoot |
| 2 | `fig2_crossover` | **Why the relative settling criterion fails below 11.5°** — a prediction confirmed |
| 3 | `fig3_trajectory` | **Settling time is the trajectory generator, not joint dynamics** |
| 4 | `fig4_jitter` | Host loop runs at 63.6 Hz, quantised to the Windows tick |
| 5 | `fig5_gain_sweep` | Settling and static error vs `kp_scale` |
| 6 | `fig6_torque` | Torque against the real ceilings — 18% of available |
| 7 | `fig7_repeatability` | August vs October with CIs; range vs σ |
| 8 | `fig8_capability` | How little of the velocity and torque envelope was used |

Figures 2 and 3 are the ones worth showing first.

## Units

- Position is **output revolutions**; plots convert to degrees.
- Torque is **output-side already** — moteus scales it by
  `1/rotor_to_output_ratio`. It assumes a **lossless** gearbox, so it is an
  upper bound: true output torque is `η ×` the plotted value, and `η` is not yet
  measured. Labelled *lossless-referred* throughout.

## Colour

Palette is the dataviz reference instance, validated against a white figure
surface rather than eyeballed:

- 5-step ordinal blue ramp (ordered quantities: step size, gain) — ALL CHECKS
  PASS: monotone lightness, ΔL ≥ 0.06, light end 2.11:1 vs surface, single hue.
- 2-slot categorical blue/orange (unordered identity) — ALL CHECKS PASS:
  all-pairs CVD ΔE 24.7, normal-vision ΔE 33.6, both ≥ 3:1.

Rules kept: one y-axis per plot (never dual-axis), ordinal ramps for ordered
variables, fixed categorical order, recessive grid and axes, legend whenever
there are two or more series.

## What is deliberately missing

**There is no histogram of landing errors.** `do_random` calls `log_run`
without a `samples` argument, so the 50 individual errors from the n=50 run were
never written to disk — only summary statistics survived. Figure 7 shows σ with
confidence intervals instead. Fixing that logging gap is the top software item
in the plan.
