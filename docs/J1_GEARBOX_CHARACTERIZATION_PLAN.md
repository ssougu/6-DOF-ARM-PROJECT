# J1 gearbox characterization — campaign plan

**Subject:** J1 base yaw, mj5208 + moteus r4.11 + 15:1 printed herringbone
planetary. Unloaded (no arm structure on the output).

**Audience:** a senior mechatronics engineer who has not seen this project.
They will ask, in this order: *what was your reference, what is your
uncertainty, and what did you not measure.* This plan is built around
answering those three before showing a single chart.

**Status:** plan only. Nothing here has been run. Written 2026-10-18.

> **⚠ SUPERSEDED — and it contained a 15× error.** `docs/J1_CHARACTERIZATION_PLAN.md`
> is the canonical plan; it is more rigorous and it holds measured results.
> This document originally asserted that `moteus.Register.TORQUE` is
> rotor-side and that output torque is `15 × τ_reported`. **That is wrong.**
> moteus divides position and multiplies torque by `1/rotor_to_output_ratio`
> (= 15, confirmed as `0.0666667` in the log records), so **reported torque is
> already output-referred** and true output torque is `η × τ_reported` —
> 10–30% *lower*, not 15× higher. Independent confirmation: `CLAUDE.md`'s
> "gains scale with ratio² (225×)" gotcha is only possible under this
> convention. The corrections are applied below; keep this file only for the
> clamped-output method, the ArUco witness option and the thermal Tg limit,
> which are not in the canonical plan.

Related: `CONTROLLER_ARCHITECTURE.md` (where control runs),
`J2_DESIGN_BRIEF.md` (the encoder provision this campaign justifies), and
open questions 1 and 2 in `CLAUDE.md` (gearbox wear, output-side encoder).

---

## 1. Scope boundary — read this first

Every number available today comes from **one sensor: the moteus rotor
encoder, upstream of the gearbox.** That single fact decides what is
measurable and what is not. Stating it first is what makes the rest
credible.

### Measurable with rotor sensing alone

| Because | Metric |
|---|---|
| The output is **clamped**, so the clamp is the reference and rotor motion *is* the deflection | backlash, torsional stiffness, hysteresis loop, breakaway torque |
| The quantity is **referred to the input** anyway | drag torque vs speed, torque–speed envelope, thermal rise, cogging/mesh ripple |
| The loop is **closed on the rotor**, so this is the controller's own performance | step response, bandwidth, gain tradeoff |

The clamped-output case is the one where rotor sensing is not a compromise
but the *correct* instrument: the clamp is the reference, so reported motion
**is** the deflection — and because moteus already reports in output
revolutions, the 16384-cpr rotor encoder resolves 0.0015° at the output. No
hand conversion is needed (an earlier revision of this file wrongly divided
by 15 a second time).

### NOT measurable without an output-side reference

- **True positioning repeatability.** The 0.36° figure is rotor-side. The
  error it cannot see — backlash take-up, windup, compliance — lives
  entirely downstream of it. The real number is worse and we do not know by
  how much. Quoting 0.36° as the joint's repeatability is the claim in this
  project most likely to be challenged, correctly.
- **Transmission error** (output angle vs commanded through a full
  revolution). The headline quality metric for a printed planetary. Not
  available.
- **Whether the output moved at all**, independently of the motor's belief.

### NOT measurable without a load

- **Efficiency.** η = P_out / P_in and P_out = τ_out·ω_out. With no load,
  ω_out carries no torque, so η is undefined. An unloaded campaign yields
  the **loss torque curve** instead, which is not the same thing and must
  not be relabelled as efficiency.
- Load-dependent stiffness, tooth deflection under working load, nylon creep.

### NOT measurable at all with this instrumentation

- **Absolute torque.** moteus reports `τ = N · Kt · I_q` — **already
  output-referred** (N = 15), with `Kt` from the *nameplate* `motor.Kv` and
  **η assumed to be 1**. So it is a **lossless-referred upper bound**: true
  output torque is `η × τ_reported`, i.e. **10–30% lower** at 70–90%
  efficiency, on top of ±10–15% nameplate uncertainty in `Kt`. It is a
  rotor-side quantity wearing output-side units — "motor torque expressed at
  the output", not "torque arriving at the output". One cheap fixture (§3)
  calibrates the whole `N · Kt · η` product in one fit; that is the
  highest-value addition in this plan.

---

## 2. Instrumentation and uncertainty budget

Fill the measured column during bring-up. The report quotes value ± this.

| Quantity | Source | Resolution | Accuracy / uncertainty | How established |
|---|---|---|---|---|
| Rotor angle | moteus onboard magnetic encoder | ~0.02° rotor → 0.0015° output | dominated by encoder eccentricity and nonlinearity, **not** resolution; assume 0.1–0.3° rotor until measured | compare against output reference over a full turn |
| Output angle | *(see §3 decision)* | TBD | TBD | — |
| Torque | `N · Kt · I_q`, **already output-referred**, η assumed 1 | 0.001 N·m reported | **±10–15%** from nameplate `Kt`, **plus a 10–30% high bias** because η is taken as 1 | calibrate the `N · Kt · η` product vs lever arm + known mass |
| Bus power | moteus `POWER` register | — | includes winding I²R and controller loss — this is **drive-train**, not gearbox | stated, not corrected |
| Time / sample interval | host `time.monotonic()`, Windows | — | TBD — **measure it (T0.2)** | burst-sample jitter histogram |
| Motor temp | moteus `MOTOR_TEMPERATURE` | 0.1 °C | thermistor is in the stator, not the gearbox | — |
| Gearbox body temp | IR thermometer, if available | 0.1 °C | ±2 °C typical, emissivity-dependent on plastic | — |
| Ratio | tooth counts | exact | exact — **tooth counts are the authority** | never hand rotation (that produced a false 11.14:1) |

Resolution is not accuracy. Reporting four decimals on a ±15% quantity is
the fastest way to lose a reviewer; every table in the report carries ± or
it does not ship.

---

## 3. Fixtures — three tiers, decide before building anything

**Tier A — output clamp (build this regardless).** A rigid bracket locking
the output shaft to the bench. Unlocks the entire static set: backlash,
stiffness, hysteresis, breakaway. It must be **stiffer than the gearbox** or
it measures itself; verify by re-running at a second clamp point and
comparing slopes. If they differ, the fixture is in the measurement.

**Tier B — lever arm + scale (~$15, strongly recommended).** A 150 mm arm on
the output pulling on a 20 kg digital luggage scale (~0.15 N·m resolution at
that radius). Gives real static output torque, and the one-point calibration
that turns the torque axis from estimate into measurement. Also gives
**static efficiency** = τ_out,measured / τ_reported — the closest honest
thing to η available without a dyno. (`τ_reported` is already output-referred
and lossless, so this ratio *is* η directly; no factor of 15 enters.)

**Tier C — output-side angle reference (the §1 gap).** Options, cheapest
first:

| Option | Resolution | Cost / effort | Notes |
|---|---|---|---|
| Dial indicator on a lever arm | ~0.01 mm → ~0.004° at 150 mm | $20, manual | Traceable, excellent for static points. Cannot do dynamics. |
| Camera + ArUco marker on the output disc | ~0.05–0.1° | **$0 — reuses `vision/`** | `board.py` already fixes the dictionary. Best value: static *and* slow dynamic, and it exercises the untested capture path. |
| Laser pointer + wall scale | ~0.01° at 3 m | $10 | Large angular gain, read by eye or photo. Static only. |
| AS5048A on SPI | 14-bit, ~0.02° | $10 + wiring | The real answer, and **open question 2's deadline is the gearbox CAD** — a magnet pocket must go in before the next five print. |

Recommendation: **A + B now, C via camera + ArUco** (free, already built),
and put the AS5048A magnet pocket into every gearbox CAD whether or not it
is ever wired. Retrofitting means reprinting.

---

## 4. Tier 0 — tooling prerequisites

Nothing below produces publishable data until these three land. Each is
small; all three are in `host/joint_console_v2.py`.

**T0.1 — Widen the sample record.** `control_loop` logs
`(t, position, velocity, torque)`. Add `q_current`, `d_current`, `power`,
`motor_temperature`, `temperature`, `position_error`, `mode`, `fault`,
`command_position`. All are already in the query result and are simply being
thrown away. Bump the CSV header and add `"schema": 2` to the JSON so the
plot script can branch. **Do this first** — every later test then writes a
richer file for free, and `q_current` plus temperature are what make the
torque-constant check and the thermal chart possible at all.

**T0.2 — Burst sampling, and measure the jitter.** The control loop is
50 Hz. A 0.17 s settle is ~8 samples, so overshoot is aliased and any
step-response plot at that rate will be discounted on sight. Add a burst
mode that queries as fast as the transport allows and reports mean / σ / max
sample interval. Then **state the achieved rate as the bandwidth ceiling on
every transient claim in the report.** This also closes part of open
question 6 (host jitter never characterized) — run it idle and under CUDA
load.

**T0.3 — Campaign metadata and a cycle counter.** `log_run` already writes
JSON + CSV + an appending history row; keep that shape. Add to the record:

```
"campaign":  "j1-gbx-2026-10-18"      selects exactly this campaign's runs
"hardware":  { "gearbox_id", "ratio", "lubricant",
                "output_revs_since_new", "fixture", "ambient_C" }
```

`output_revs_since_new` is a monotonic counter persisted in a small JSON
file and incremented by every test. **Without it the wear story (#13) is
unreconstructable after the fact** — it is the one field that cannot be
backfilled.

---

## 5. Test matrix

Hardware column: **—** none, **A** clamp, **B** lever + scale, **C** output
angle reference.

| # | Metric | Method | HW | Figure it produces | Time |
|---|---|---|---|---|---|
| 1 | Ratio verification | Rotor revs over ≥10 full output turns vs tooth counts | C | table only | 15 m |
| 2 | **Backlash + torsional stiffness + hysteresis** | Clamp output; ramp feedforward torque 0→+T→0→−T→0 in ~40 dwelled steps; read rotor | A | **hysteresis loop** — backlash is the zero-torque flat width, stiffness the loaded slope, friction the enclosed area | 45 m |
| 3 | Breakaway / Coulomb friction | Slow torque ramp until velocity crosses a threshold; 10 reps × 2 directions × 3 rotor positions | — | bar chart by direction, with spread | 30 m |
| 4 | Static output torque + torque-axis calibration | Lever arm vs scale at 6 commanded torques, both directions | B | τ_measured vs τ_reported against the unity line → **static efficiency η** | 45 m |
| 5 | **No-load drag torque vs speed** | `vel` mode, 12–15 speeds from 0.02 to max, both directions, 5 s dwell, mean steady-state torque | — | **loss curve**; a linear fit splits Coulomb (intercept) from viscous (slope) | 40 m |
| 6 | **Torque–speed envelope** | Sweep the `maximum_torque` ceiling 0.05→max; at each, command a speed that ceiling cannot sustain; record achieved speed | — | **achieved output speed vs torque ceiling** — the operating envelope, i.e. the low-power-to-max-power chart | 40 m |
| 7 | Thermal rise under duty | Sustained `cycle` at representative amplitude and speed, 25 min; log motor, board and gearbox body temp | — | temperature vs time with current overlay | 30 m |
| 8 | Step response family | Steps of 0.5 / 1 / 2 / 5 / 10 / 30 / 90° output, 5 reps each, burst-sampled | — | small-multiples of position vs time; overshoot and settle vs step size | 45 m |
| 9 | **Closed-loop bandwidth** | Position chirp 0.2→20 Hz at small amplitude; gain and phase from rotor position | — | **Bode magnitude / phase** → bandwidth, plus any printed-gearbox resonance peak | 30 m |
| 10 | Gain tradeoff | The existing `sweep` over kp and kd | — | overshoot vs kp, settle vs kp — shows the design point was chosen, not stumbled into | 30 m |
| 11 | Repeatability, rotor vs output | The existing `random`, ≥50 moves × 3 seeds, logged against both references at once | C | error histogram; error vs approach direction; error vs distance; **the rotor-vs-output gap** | 60 m |
| 12 | Cogging / mesh ripple | Very slow constant velocity; FFT the torque signal | — | spectrum; peaks at mesh frequency indicate printed-tooth quality | 20 m |
| 13 | **Wear / burn-in** | Run #2, #3, #5 → 500–2000 cycles with spot-checks every 250 → repeat #2, #3, #5 | A | **before/after overlaid hysteresis loops** (backlash growth is visually unmistakable), drag shift, trend vs cycles | 3–4 h |

### Method notes on the ones that bite

**#2, the hysteresis loop, is the single most informative chart** and it
needs no output encoder — that is the whole trick. Applied output torque is
`τ_reported` directly (already output-referred, lossless-assumed); losses
show up as the loop's width rather than corrupting the axis, which is
exactly where they belong.

Ramp in **tiers**, with a pass/fail at each: does the loop return to zero
when the torque does? The first tier where it does not is **permanent set in
a printed plastic planetary**, and that torque is itself a headline result.
"Practical output torque limit before permanent set" is a number the ME
needs more than the theoretical stall figure. Stop there. Do not chase the
~25 N·m that 15 × motor peak suggests; the gears will not survive it.

**#6: the 24 V 5 A brick (120 W) is probably the binding constraint on
"maximum power", not the motor.** Chart it and say so — a reviewer who sees
a torque–speed envelope that is supply-limited and *labelled* as
supply-limited learns that the power budget is understood. Watch for regen
over-voltage on fast decelerations; `servo.flux_brake_margin_voltage` and
`servo.max_regen_power_W` are already in the console's bounds table.

**#8: the existing 2% settling band is an artifact below ~0.05 rev** —
that band is finer than the backlash. Define it in absolute degrees (±0.1°)
for small steps, report both, and name which is which in the caption.

**#5 control experiment:** the loss curve is *joint* loss, not *gearbox*
loss, unless there is a bare-motor baseline to subtract. If the gearbox can
be unbolted, a 20-minute bare-motor run makes every loss number
attributable. Without it the chart is still valid, but the title must say
"joint", not "gearbox".

**#9 is gated by T0.2.** Sample rate must be ≥10× the top sweep frequency.
If burst sampling reaches only ~100 Hz, cap the chirp at ~10 Hz and state
the ceiling rather than extrapolating past it.

---

## 6. Data and plotting architecture

Keep the existing `log_run` pattern — JSON record, CSV samples, appending
history row. It is already the right shape. Three additions, all in §4.

**New: `host/analyze_j1.py`.** Reads `host/logs/`, selects by `campaign`,
and emits every figure to `docs/figures/` as PNG **and** SVG, plus a
`metrics.json` holding every summary number the report quotes. One command,
idempotent, re-runnable. The report then cites `metrics.json` rather than
hand-copied numbers, so **the prose cannot drift from the data** — which is
this project's documented dominant failure mode (silent partial success).
matplotlib, numpy and scipy are already installed; pandas is not and is not
needed.

Chart conventions: one consistent palette across all figures, direction
encoded by colour, every axis labelled with units *and* the reference
("output deg, rotor-derived"), and error bars or ± bands wherever §2 gives
an uncertainty. A chart whose axis does not say which sensor produced it is
what a senior engineer will stop on.

**Report: `docs/J1_GEARBOX_CHARACTERIZATION.md`**, in reading order:

1. Scope, and what was **not** measured (§1 — first, not in an appendix)
2. Fixture and instrumentation, with the uncertainty table
3. Results table, every row with ±
4. Figures, each captioned with its *conclusion*, not its contents
5. Error budget rolled up to a single positioning number
6. Design implications for J2–J6 — **the section the ME actually needs**
7. Pointers to raw data and the exact command that produced each figure

This absorbs the never-written `J1_BRINGUP_REPORT.md`; remove that row from
the repo layout in `CLAUDE.md` when it ships.

---

## 7. Running order

The dependencies are real: T0.1 gates every CSV, T0.2 gates #8/#9/#12, the
fixtures gate #2/#3/#4, and #13 must bracket a burn-in so it cannot be
parallelized away.

- **Session 1 — tooling, no motor.** T0.1, T0.2, T0.3, skeleton
  `analyze_j1.py`. Verify by running one existing `step` and plotting it.
- **Session 2 — fixtures.** Build clamp and lever arm. Verify clamp
  stiffness at two points. Calibrate the torque axis (#4).
- **Session 3 — static set.** #1, #2, #3. This is the day that produces the
  hysteresis loop.
- **Session 4 — dynamic set.** #5, #6, #8, #9, #10, #12.
- **Session 5 — repeatability and thermal.** #11, #7.
- **Session 6 — burn-in.** #13, mostly unattended with spot-checks.
- **Session 7 — write-up.** Run `analyze_j1.py`, write the report.

### Minimum credible subset — one bench day

If the fair timeline wins (and with ~2 weeks out, J3–J6 unbuilt and no
gripper owner, it probably should), this subset still stands up to review:

- **T0.1 + T0.3** (2 h) — richer logs and the cycle counter. Skip T0.2 and
  cap the transient claims accordingly.
- **#2** with a clamp (1 h) — backlash, stiffness, hysteresis. The one chart
  that is unambiguously *about the gearbox*.
- **#5** (40 m) — the loss curve.
- **#8** at 50 Hz (45 m) — step response, with the sample-rate caveat stated.
- **#11** rotor-side only (1 h) — repeatability, explicitly labelled
  rotor-side and therefore optimistic.
- **#13 abbreviated** (2 h) — #2 before and after 500 cycles. Even one
  before/after pair answers open question 1, which `CLAUDE.md` calls the
  highest-value outstanding measurement — and five more gearboxes are
  currently being designed on the strength of a cold-start number.

That is roughly 8 hours for four real charts plus the wear answer. The rest
is upside.

---

## 8. Safety and abort criteria

- A blank line at the console prompt is the panic key; e-stop latches.
- Soft limits (`servopos.position_min/max`) set before any test that moves
  far. #1 needs ≥10 output turns, so limits must be widened deliberately
  and restored afterwards.
- The watchdog stays at 0.25 s. Do not raise it for convenience during
  torque tests — a limp joint under a torque command with no watchdog is how
  a clamp fixture gets destroyed.
- **Torque tests are the dangerous ones.** Clamp before commanding torque,
  ramp in tiers, abort on the first sign of permanent set, and keep hands
  clear of a 15:1 output.
- Thermal: stop at 80 °C motor, or at **60 °C on the gearbox body** if it is
  PLA — that is approaching Tg, and the gearbox will deform before anything
  electrical complains.
- Every automated sequence gets a verification step. Half-saved tunes and
  tests that cannot fail are this project's documented failure mode.

---

## 9. Risks

1. **The campaign competes with the demo.** ~2 weeks to the fair, 2 of 6
   joints built, no gripper owner. Sessions 1–7 are about 5 bench days. The
   §7 subset exists for exactly this reason.
2. **Rotor-side repeatability will look better than the joint is.** Publish
   the gap (#11 with reference C) or publish the caveat. Publishing 0.36°
   unqualified is the review risk.
3. **The torque axis is ±15% until #4 runs.** Every chart with a torque axis
   inherits that.
4. **A printed planetary may be damaged by its own characterization.** #2 at
   high tiers and #13's burn-in both consume gearbox life. Either run them on
   the gearbox already fitted to J1 and accept the cost, or print a
   sacrificial twin — but then record its `gearbox_id`, because two
   gearboxes' data in one history file with no distinguishing field is worse
   than no data.
