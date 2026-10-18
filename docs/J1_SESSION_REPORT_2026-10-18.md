# J1 bench session — 2026-10-18

**Subject:** J1 base yaw. mj5208 + moteus r4.11, 15:1 printed herringbone
planetary, bare output, nothing attached.

**Instrumentation:** rotor-side magnetic encoder only (`cpr = 16384`, confirmed
from the board). No external witness, so **everything downstream of the sun gear
is inferred rather than measured.** Every claim below is labelled accordingly.

**Conditions**, constant unless stated: `kp` 225, `kd` 4.5, `ki` 200,
`ilimit` 0.5, all scales 1.0; `vel_limit` 0.25 rev/s; `accel_limit` 1.0 rev/s²;
`max_torque` 1.0 N·m; bus 23.5 V; board 26 °C at start, 30 °C at end.

**Runs:** 5 step responses across step size, 5 across gain, one n=50
repeatability run, 4 two-point cycles. 15 records in `host/logs/`.

Figures are produced by `analysis/j1_figures.m`.

---

## 1. Headline results

| Quantity | Value | Basis |
|---|---|---|
| **Repeatability, design figure** | **0.685° → 4.78 mm at 400 mm** | \|μ\|+2σ, n=50, random approach |
| Landing-error σ | 0.2950° (95% CI ±20%) | n=50 |
| Mean \|error\| | 0.2656° | n=50 |
| Direction split | 0.0231° ± 0.0835 (SE) | indistinguishable from zero |
| Static error floor | 0.03–0.31° | 5 step sizes |
| Breakaway torque | ~0.53 N·m at the output | lossless-referred |
| Peak torque drawn | 0.802 N·m = **18%** of available | — |
| Host loop rate | **63.6 Hz**, not the nominal 50 Hz | n=1452 intervals |
| Damping | **overdamped, ζ ≥ 1** | no overshoot at any step size |

The repeatability figure is **1.9× worse than the 0.36° the project had been
designing around** — because 0.36° was never a σ. It was the *range* of 20
samples (§2.1).

---

## 2. What we learned about our own measurements

Four of today's findings are about method rather than about the joint. They
matter more than the numbers, because they determine whether any number is
trustworthy.

### 2.1 We had been comparing ranges at different sample sizes

The 0.36° bench figure was `max − min` of 20 landings; the 0.84° figure from
coordinated moves was `max − min` of **6**. Range grows with sample size, so the
two were never comparable. Converting both with the control-chart constant
`σ̂ = R/d₂`:

```
bench   (n=20, R=0.3625)  ->  sigma = 0.097 deg
workout (n=6,  R=0.84)    ->  sigma = 0.332 deg      ratio 3.4x, not the ~2x recorded
```

Worse, at n=6 the 95% confidence interval on σ is **±62%**, so that comparison
was never supportable in either direction. Inverting the CI expression
`±1.96/√(2(n−1))` for a target precision gives the sample size we should have
used: **n = 50 for ±20%**, n = 32 as a floor. At 2.18 s per move that is only
3.6 minutes per condition — there was never a good reason to accept n=6.
**Figure 7.**

### 2.2 A variance decomposition of the old data returns a negative variance

Treating landing error as independent contributions:

```
var(total) 0.04700 - var(direction) 0.01202 - var(point repeat) 0.00942 = 0.02556
```

which would suggest ~0.16° of position-dependent error. But applying the same
model to the reference-return data gives `0.00942 − 0.01202 = −0.0026` — a
**negative variance**, which is proof the model or the sample size is wrong. The
terms are confounded.

The useful consequence: error terms must be made orthogonal **by experiment
design**, not untangled afterwards. That is why the plan now specifies three
separate runs (fixed approach / alternating approach / position grid) rather than
one random run plus arithmetic.

### 2.3 Our step responses were not step responses

This is the most important finding of the session. `goto` and `step` pass through
moteus's **trajectory generator**, which is rate-limited by `vel_limit` and
`accel_limit`. Comparing measured settling against the trapezoidal traverse time:

| step (deg) | measured (s) | trapezoidal prediction (s) | ratio |
|---|---|---|---|
| 0.50 | 0.06 | 0.075 | 0.83 |
| 2.00 | 0.14 | 0.149 | 0.94 |
| 11.48 | 1.00 | 0.357 | **2.80** |
| 45.00 | 0.77 | 0.750 | 1.02 |
| 90.00 | 1.22 | 1.250 | 0.97 |

**Four of five sit on the unity line.** The "settling time" was the rate limiter,
not the joint. Any ζ or ω_n fitted to such a trace describes the trajectory
generator — so the previously recorded "1.6% overshoot, 0.17 s settle" and the
ζ≈0.80 derived from it are not defensible, and in fact do not reproduce at all:
**overshoot is negative on four of five steps** and settling is 0.72–1.22 s.
The joint is overdamped. **Figures 1 and 3.**

The 11.48° point is the single genuine outlier at 2.80×, and it sits exactly at
the backlash/settling-band crossover — the most interesting data point collected,
and worth a dedicated high-rate run.

### 2.4 Our settling criterion was unphysical below 11.5°, exactly as predicted

The relative band is 2% of the commanded step. In degrees that is `7.2·δ_rev`.
Setting it equal to the measured backlash of 0.23°:

```
delta = 0.23 / 7.2 = 0.0319 rev = 11.5 deg
```

Below that the band is finer than the backlash and "did not settle" is an
artifact. **Measured, the flip from "did not settle" to "settled" happens
precisely at 11.48°** — a quantitative prediction confirmed on the first run, and
confirmed twice more in the gain sweep where low stiffness pushes static error
above the band. **Figure 2.**

The replacement absolute band (±0.36°) fixes the lower end but is degenerate at
the extreme: at δ = 0.5° it is 72% of the whole step. **Neither criterion is
meaningful below about δ = 1.8°**; report the static error floor there instead.

---

## 3. Timing: the host loop does not run at its nominal rate

`control_loop` already stamps every sample with `time.monotonic()`, so the
inter-sample deltas are a timing dataset at no cost. Pooled across all 10 step
runs, n = 1452 intervals:

```
mean 15.73 ms  ->  63.6 Hz, i.e. 1.27x the nominal CONTROL_HZ = 50

15 ms  37.3%     quantised to the 15.6 ms Windows scheduler tick
16 ms  62.0%
31 ms   0.7%     double ticks
```

`asyncio.sleep(0.02)` is being rounded to the Windows timer granularity. The
jitter is **quantised, not Gaussian**, and bounded at two ticks. This is a far
better-behaved timing environment than "uncharacterised" implied — but it also
means any sample-rate increase above ~64 Hz needs a different timing mechanism,
not a larger constant. **Figure 4.**

---

## 4. Envelope: we have been using a small corner of it

### 4.1 Torque is output-side already, and only 23% was requested

`moteus.Register.TORQUE` is scaled by `1/rotor_to_output_ratio`, so it is
**post-reduction**. Settled from the board rather than assumed:

```
motor.Kv = 330  ->  Kt_rotor = 0.02894 N.m/A
servo.max_current_A = 10 A  ->  max rotor torque 0.289 N.m
                            ->  max output torque 4.341 N.m (lossless)
```

The peak logged value of 0.802 N·m would require **27.7 A** rotor-side — 2.8×
over the current limit, so impossible — but only **1.85 A** output-side. Even
granting a 1.5× peak/phase convention the rotor interpretation fails.

Caveat that must travel with every torque number here: moteus assumes a
**lossless** gearbox and a nameplate `Kt`. True output torque is `η ×` these
values, and η is not yet measured. The honest term is *lossless-referred*.

Against that 4.34 N·m, the session used a 1.0 N·m ceiling (23%) and drew at most
0.802 N·m (18%). Breakaway alone is ~0.53 N·m, so the ceiling was only **1.9×
breakaway** — a thin margin, and plausibly why small steps settle poorly.
**Figures 6 and 8.**

### 4.2 Velocity is capped 18× below capability — by configuration

An attempted speed ladder stopped at the first rung on a config value nobody
knew about:

```
servo.max_velocity = 0.5 rev/s     <- hard cap, absent from PROFILE
no-load theoretical  8.80 rev/s
voltage-limited      5.08 rev/s
used this session    0.25 rev/s    <- half of even the cap
```

`status` read `vel = +0.5003` then `+0.4991`, pinned exactly at the cap.
**Figure 8.**

**This silently corrupted three of four cycle records.** `travel_time()`
computes the dwell from the *commanded* limit, which the firmware ignored, so
`cycle` sampled mid-flight and logged `backlash_deg` of 30.1°, 77.5° and 108.4°
— physically absurd for a joint whose backlash is ~0.23°, sitting in
`j1_history.csv` beside real numbers. The shortfall predicts the error exactly
(0.50 s × 0.5 rev/s = 0.25 rev vs 0.267 observed). Records `20261018-145931`,
`145937` and `145943` are **void**.

A warning was printed, but the metric was logged anyway. That is a test that
cannot fail — the dominant failure mode this project has already named.

---

## 5. Root cause behind §4.2: the board's config is not under version control

1. `servo.max_velocity = 0.5` exists on the board and in **no file**.
2. `servopos` is **±0.55 rev on the board vs ±0.25 rev in `PROFILE`** — a 2.2×
   discrepancy with no record of which is intended.
3. **`profile_1.json` has never been committed** — `git log --all` finds no
   trace, despite being listed as "COMMIT THIS".

The tooling to prevent all three already exists and has never been used:
`--sync`, `--check`, `--apply`, `--dump --backup`.

---

## 6. Corrections to existing documentation

| Claim | Status |
|---|---|
| repeatability 0.36° | **a range of n=20, not σ.** Design figure is 0.685° |
| coordinated moves "~2× worse" | **3.4×** after normalising for n |
| "1.6% overshoot, 0.17 s settle" | **does not reproduce**; no overshoot, 0.72–1.22 s |
| ζ ≈ 0.80 | **unsupported** — joint is overdamped, ζ ≥ 1 |
| settling band artifact "below ~0.05 rev" | crossover is **0.0319 rev** exactly |
| `CONTROL_HZ = 50` → 20 ms | **15.73 ms, 63.6 Hz** |
| 14-bit encoder assumed | **confirmed**, `cpr = 16384` |
| 120 W supply is the ceiling | `servo.max_power_W = 100` clips first; regen capped at 10 W |
| torque side-of-reduction unstated | **output-side, ×15 already applied** |

---

## 7. Next

**Software, before more data is taken:**

1. **Save per-move samples.** `do_random` and `do_cycle` call `log_run` without
   a `samples` argument, so 50 landing errors were lost — only aggregates
   survived, which is why §1 has no error histogram. Only `do_step` logs raw
   data.
2. **Clamp `vel_limit` to `servo.max_velocity` with a warning**, and make
   `travel_time()` use the effective limit. Prevents §4.2 recurring.
3. **Refuse to emit metrics when a move did not complete** (mean landing error
   beyond a few percent of commanded travel).
4. **Commit `profile_1.json`** and run `--check` each session.
5. Log `Q_CURRENT`, `D_CURRENT`, `VOLTAGE`, `TEMPERATURE` and commanded
   position; widen `log_run`'s config capture to the full board dump.

**Measurement, to move past rotor-side inference:**

6. Raise `vel_limit`/`accel_limit` above the trajectory-generator constraint and
   re-run the step sweep — until then no dynamic figure for this joint is
   defensible (§2.3).
7. Build the lever + dial-indicator fixture. At r = 200 mm a 0.01 mm indicator
   resolves **0.00286°, 126× finer** than the design figure, and unlocks
   backlash, stiffness, torque-constant calibration and efficiency — none of
   which the rotor encoder can reach.
8. Fit an output-side encoder (AS5048A, 0.022°/count). It is the only route to
   transmission error, true backlash under load, and detecting tooth skip.

Full test plan, with derivations: `docs/J1_CHARACTERIZATION_PLAN.md`.
