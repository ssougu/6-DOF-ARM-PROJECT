# J1 gearbox characterization — test plan

**Scope: J1 only.** Base yaw, mj5208 + moteus r4.11, 15:1 printed herringbone
planetary, unloaded. No other joint; no arm-level or perception content.

**Goal:** a defensible, chart-backed description of what this gearbox does from
low power to maximum power — torque, responsiveness, backlash, repeatability,
thermal and wear — with the maths behind each test stated, and every number
carrying its sample size, uncertainty and conditions.

**Status:** plan. Nothing here has been run. `[FILL]` marks a value the bench
must supply. Figures are numbered in §11.

---

## 1. Why this plan looks the way it does

Three principles drive every choice below.

**1. State what the instrument can see before stating any number.** The only
encoder on this joint is on the *rotor*, upstream of the gear train. It cannot
see backlash, tooth compliance, carrier wind-up or creep — exactly the things a
gearbox report is about. Every test is therefore classified by whether it
measures something the instrument can actually reach (§2).

**2. Separate friction from load by direction-averaging.** Coulomb friction
flips sign with direction of travel; load does not. Measuring any quantity in
both directions and taking the half-sum and half-difference splits the two
analytically — no friction model, no curve fitting. This one trick carries the
torque constant (§5.1), drag (§5.2), efficiency (§5.3), inertia (§5.5) and
backlash (§6.1). It is the backbone of the plan.

**3. Fit parameters to whole curves, not features of curves.** Reading
"overshoot" and "settle time" off a step discards ~95% of the samples and, as
§7.2 shows, for this joint those two numbers are not even independent. Fitting a
model to every sample yields confidence intervals and a residual that reveals
when the model itself is wrong. Feature extraction cannot do either.

---

## 2. The instrument, and its blind spot

### 2.1 Resolution

`motor_position.rotor_to_output_ratio = 0.0666667` = 1/15 exactly, confirmed
from the logged config of the 2026-08-26 runs. The moteus `POSITION` register is
therefore already in **output revolutions**, so the project convention holds with
no conversion. The underlying quantum is still one rotor count:

```
rotor encoder (AS5047P, r4.11 onboard)  2^14 = 16384 counts / rotor rev
reflected through 15:1                  16384 x 15 = 245,760 counts / output rev
angular quantum                         360 / 245,760 = 0.001465 deg
```

Against the 0.36 deg figure the project designs around, that is **246x finer**.
Encoder resolution is not a limiting error source here, and saying so up front
removes it from the discussion permanently.

**Confirmed on the board, 2026-10-18.** The logged config reports
`motor_position.sources.0.cpr = 16384`, so the 14-bit assumption and the
0.001465 deg quantum above are measured, not assumed.

Also from that dump: `motor_position.sources.0.pll_filter_hz = 200`. The
position estimate is PLL-filtered at 200 Hz, which is an upper bound on the
measurement bandwidth of §7.5 independent of the host sample rate.

### 2.2 The blind spot, as a classification

| Class | Terms | Visible to the rotor encoder? |
|---|---|---|
| **A** — electrical / control | tracking error, rise and settling, ringing, cogging, current limit, bus droop | Yes, directly |
| **B** — mechanical, downstream of the sun gear | backlash, tooth compliance, carrier wind-up, bearing play, transmission error, creep, wear | **No** — only as a direction- or position-dependent residual |

Class B *is* the gearbox. The rotor encoder is at best a proxy for it. Any claim
about backlash or stiffness built on rotor data alone is an inference, not a
measurement, and must be labelled as one. This is why §4 recommends an external
witness before §6 is attempted.

### 2.3 Sampling

`CONTROL_HZ = 50` (`host/joint_console_v2.py:33`) — nominally 20 ms apart.

**Measured 2026-10-18 (see §15.4): the real interval is 15.6 ms, not 20 ms**,
i.e. ~64 Hz rather than the nominal 50 Hz, quantised to the Windows scheduler
tick with occasional 31 ms doubles. Consequences are quantified in §7.1 and
§7.5.

The logged tuple in `control_loop` is `(t, position, velocity, torque)`.
`time.monotonic()` is already captured per sample, so the inter-sample deltas of
any run are a **host timing-jitter dataset for free** — no new code, only
analysis.

---

## 3. What the existing data already says, and where it breaks

Re-analysis of the three logged runs in `host/logs/j1_history.csv`, done before
spending bench time. All three: seed 42, n=20, kp/kd scale 1.0, vel_limit 0.25,
accel_limit 1.0, `max_torque` **1.0 N·m**, travel ±0.53 rev.

| run | mean abs err | worst | std | dir split | ref spread (n=20) |
|---|---|---|---|---|---|
| 23:03:58 | 0.1886 | −0.4223 | 0.2333 | 0.2292 | 0.3625 |
| 23:07:44 | 0.1932 | −0.4223 | 0.2282 | 0.2363 | 0.3735 |
| 23:46:26 | 0.1807 | −0.4173 | 0.2168 | 0.2193 | 0.3516 |

Run-to-run agreement is excellent (std 0.217–0.233 deg). That is itself a
reportable result: the *measurement* is stable, so differences found later are
real rather than noise.

### 3.1 The headline numbers are ranges, not standard deviations

`ref_spread_deg` is `max − min` of the landings. The 0.36 deg design figure is
the **range of 20 samples**; the 0.84 deg workout figure is the **range of 6**.
Range grows with sample size, so the two are not comparable as written.

Converting each with the control-chart constant `σ̂ = R / d₂`, where
`d₂(6) = 2.534` and `d₂(20) = 3.735`:

```
bench   (n=20, R=0.3625)   σ̂ = 0.3625 / 3.735 = 0.097 deg
workout (n=6,  R=0.84)     σ̂ = 0.84   / 2.534 = 0.332 deg
ratio                      3.42x
```

CLAUDE.md records this as "roughly 2× the cold bench number". Normalised for
sample size it is **3.4×**. The qualitative conclusion — coordinated moves are
materially worse — strengthens; the number changes.

### 3.2 …and n=6 cannot support the comparison anyway

The relative 95% CI on an estimated standard deviation is approximately

```
± 1.96 / sqrt(2(n−1))

n = 20  ->  ± 32%      σ in [0.066, 0.128]
n = 6   ->  ± 62%      σ in [0.126, 0.537]
```

The intervals **abut at 0.127**. The difference is marginal at best, and n=6
cannot settle it. This is the direct motivation for the sample size derived in
§8.1 — not a vague "collect more", but the specific n that makes the interval
tight enough to support the claim.

### 3.3 An attempted variance decomposition, and why its failure is useful

If landing error at random targets were a sum of independent terms:

```
var(total)        = 0.2168^2 = 0.04700
var(direction)    = (0.2193/2)^2 = 0.01202      (balanced ± approach)
var(point repeat) = 0.097^2    = 0.00942
residual          = 0.02556  ->  σ = 0.160 deg
```

That would imply ~0.16 deg of position-dependent error. But the same model
applied to the reference-return data contradicts itself. Those returns also
arrive from random directions, so they must contain the direction term too:

```
var(ref) − var(direction) = 0.00942 − 0.01202 = −0.0026     NEGATIVE
```

A negative variance proves the model or the sample size is inadequate — most
likely both. The terms are confounded; the distribution is probably bimodal (in
which case `d₂`, derived for a normal distribution, understates σ); and n=20 is
too small.

**This failure is the most useful thing in the existing data**, because it
dictates the design of §8: the error terms must be made orthogonal *by the
experiment*, stratified deliberately rather than untangled afterwards. That is
the entire logic behind the three-test structure in §8.2.

### 3.4 The step-response numbers have no logged provenance

`host/logs/` holds three `random` records and four `arm_route` records. There is
no `step` record. The 1.6% overshoot / 0.17 s settle figures exist only as prose
in CLAUDE.md. **Re-run and log them** (§7) before they appear in any report.

> **CORRECTION (inserted after review).** This section's premise is wrong, and
> §15.2, §15.8 and the §7.2 correction table inherit the error. The figures
> **do have provenance**, in version control, with their conditions stated in
> full — `host/joint_setup_v2.py:61-63`:
>
> ```
> # Measured: 1.6% overshoot, 0.17s settle, 1 zero crossing on a 0.05 rev
> # step with accel_limit 5, vel_limit 1, torque ceiling 1.5 Nm.
> ```
>
> Those are **not** the 2026-10-18 conditions (`accel_limit` 1.0, `vel_limit`
> 0.25, `max_torque` 1.0, δ 0.0319–0.25 rev). Accel differs by 5×, the velocity
> limit by 4×, the torque ceiling by 1.5×, and the step size does not overlap.
> So "neither reproduces" compares two different experiments and is not
> evidence that the originals are wrong. **Do not delete them from CLAUDE.md** —
> annotate them with their conditions instead.
>
> What *does* survive untouched: the §7.1 finding that 0.17 s is a rise time
> rather than a settling time, because overshoot (1.6%) falls inside the 2%
> band. That is a metric-definition defect and holds independently of
> provenance. Also note §7.2's "±20 ms quantisation" should be ±15.6 ms per the
> §15.9 measurement.
>
> Second-order consequence worth acting on: **the tune was validated at
> `accel_limit` 5**, while the board's `default_accel_limit` is 1.0 and every
> run this session used 1.0. Part of the slow settling is simply running at a
> fifth of the acceleration the gains were tuned at. §16.3's proposed 8 exceeds
> the validated point; **5 has documented precedent and needs no new risk.**

### 3.5 Everything so far is at a 1.0 N·m ceiling

`max_torque` was 1.0 N·m in all three runs, with `vel_limit` 0.25 and
`accel_limit` 1.0 throughout. The torque axis of this joint has **never been
explored at all**. Since the brief is explicitly "low power to maximum power",
that axis (§7.4) is the largest genuinely unmeasured region in the joint.

---

## 4. Fixtures: converting class-B inference into class-B measurement

Everything in §6 and §8.3 needs an external witness. Three tiers, with what each
unlocks and what it costs.

### Tier 0 — rotor encoder only (free, current state)

Class A only. Backlash and stiffness stay inferences from direction-dependent
residuals. Sufficient for §7 (responsiveness) and §8.2 (repeatability); not for
§6 (backlash and stiffness as absolute numbers).

### Tier 1 — lever arm + dial indicator (~$25) — the minimum for a credible report

A rigid lever clamped to the output at radius `r`, with a 0.01 mm dial indicator
reading tangentially against a flat face at its tip.

```
exact:        d = r * sin(theta)      ->  theta = arcsin(d / r)
small angle:  theta ~= d / r
```

At `r = 200 mm` with a 0.01 mm indicator:

```
theta_min = 0.01 / 200 = 5.00e-5 rad = 0.00286 deg
```

**126× finer than the 0.36 deg figure being designed around**, from a $25 part.
That ratio is the entire argument for building this fixture first.

Error terms, all bounded and all small:

| Term | Magnitude | Note |
|---|---|---|
| small-angle (chord vs arc) | 0.127% at 5 deg | use `arcsin` and it vanishes |
| cosine error, 5 deg plunger misalignment | 0.38% | align by eye; even 10 deg is only 1.52% |
| lever compliance | `[FILL]` | steel or thick aluminium; verify by loading the tip with the output clamped and watching the indicator |
| radius uncertainty | ±0.5 mm on `r` → ±0.25% | dominant systematic; measure with calipers and record it |

The same fixture carries the hanging masses for §5. **Build one fixture, get §5
and §6 both** — which is why those sessions are adjacent in §10.

### Tier 2 — AS5048A on the output (~$10 + a printed boss) — recommended

A 14-bit magnetic encoder on the output shaft:

```
360 / 2^14 = 0.0220 deg/count     ->  16x finer than 0.36 deg
```

Coarser than the dial indicator, but **continuous and logged**, which the
indicator can never be. §6.3 (the transmission-error map) needs a few thousand
points per revolution and is therefore impossible at Tier 1 in any useful form.
Tier 2 is what makes that test exist at all.

**Recommendation:** Tier 1 before anything in §6. Tier 2 if §6.3 is wanted —
and it should be, because §3.3 hints that position-dependent error is the
largest single term and §6.3 is the only test that can confirm or refute it.

---

## 5. Making torque real, before measuring anything with it

### 5.0 Why this section comes first

`moteus.Register.TORQUE` is **not measured**. It is derived:

```
tau_rotor ~= Kt * I_q        with Kt inferred by moteus from motor.v_per_hz
```

For an ideal machine the torque constant equals the back-EMF constant, and with
`Kv` in RPM/V:

```
Ke [V.s/rad] = 60 / (2*pi*Kv) = 9.549 / Kv  =  Kt [N.m/A]
```

But this rests on conventions that are easy to get wrong — line-to-line vs
phase, peak vs RMS, sinusoidal vs trapezoidal commutation — each a factor of
sqrt(3) or 2 from the truth. Which is exactly why `Kt` gets measured, not
trusted.

### 5.0.1 Which side of the reduction is `TORQUE` reported on? (settled 2026-10-18)

The register could plausibly be rotor-side or output-side, a factor of 15 apart —
the same class of error as the J2 `GEAR_RATIO` bug. Settled from the board's own
constants rather than by assumption.

```
motor.Kv = 330 RPM/V   ->  Kt_rotor = 9.5493 / 330 = 0.02894 N.m/A
servo.max_current_A = 10 A

max ROTOR  torque at the current limit  = 0.02894 * 10      = 0.2894 N.m
max OUTPUT torque, lossless 15:1        = 0.2894 * 15       = 4.341 N.m
```

Peak reported torque observed this session was **0.802 N·m** (§15.7). Testing
both interpretations against the 10 A limit:

| interpretation | implied `I_q` | verdict |
|---|---|---|
| rotor-side | 27.7 A | **impossible** — 2.8× over the 10 A limit |
| output-side | 1.85 A | plausible, 18% of the limit |

Even granting a 1.5× peak/phase convention on `Kt`, the rotor-side reading would
need `Kv = 119` rather than the configured 330.

**Conclusion: `moteus.Register.TORQUE` is already OUTPUT-side — scaled by
1/`rotor_to_output_ratio` = 15.** This is consistent with power invariance
(velocity ÷15, torque ×15), and it means the project convention of
"everything above the driver layer is output units" already holds for torque as
well as position. No 15× correction is needed anywhere.

**But it is an upper bound, not a measurement.** What moteus computes is

```
tau_reported = N * Kt * I_q        with Kt from the NAMEPLATE Kv, and eta = 1
```

so three caveats, all of which §5.1 and §5.3 exist to remove:

1. **It assumes a lossless gearbox.** moteus knows nothing about `eta`. True
   output torque is `eta * tau_reported`, i.e. **10–30% lower** at a typical
   70–90% efficiency.
2. **`Kt` is a nameplate figure**, not calibrated — ±10–15% systematic.
3. **It is rotor-side in origin.** It is "motor torque expressed in output
   units", not "torque arriving at the output". It cannot see anything the
   gearbox does, so it is a class-A quantity (§2.2) wearing class-B clothing.

Honest phrasing for the report: *lossless-referred output torque estimate*.

### 5.0.2 How to read genuinely absolute output torque

In cost order. Only options 2–4 are measurements; option 1 is a calibrated
inference, which for this project is probably enough.

| Option | Method | Cost | Measures under motion? |
|---|---|---|---|
| **1. Calibrate what you have** (§5.1) | hanging mass on the Tier 1 lever; the fit returns the combined `N*Kt*eta` product directly — exactly the wanted number | ~$25 | static only, but then applies to motion |
| **2. Reaction-torque mount** | mount the whole joint on a bearing, restrain the housing with a load cell at radius `r`; `tau_out = F*r` | ~$40 | **yes**, and no slip ring needed |
| **3. Series-elastic** | known-stiffness element between output and load + the §4 Tier 2 AS5048A; `tau = k_spring * theta` | ~$15 on top of Tier 2 | yes, but **adds compliance to the joint** — bad for positioning |
| **4. Inline rotary transducer** | commercial torque cell in the driveline | $300+ | yes, needs slip ring or telemetry |

**Recommendation: option 1 now, option 2 if a continuous trace is wanted.** The
reaction mount is the classic approach and the cheapest true measurement,
because it measures the *housing* reaction and so needs no rotating
instrumentation at all.

Consequence: `do_backlash` currently reports "approx stiffness in N·m per output
rev" built on an unvalidated constant (`host/joint_console_v2.py:702`). Until
§5.1 is done, label every torque figure as a lossless-referred estimate. §5.3, §6.1 and §7.4 all inherit `Kt`'s accuracy, so
this test gates the rest of the campaign.

### 5.1 Torque constant by known mass

J1 is base yaw and carries no gravity load, so load must be imposed: hang mass
`m` at radius `r` on the Tier 1 lever, lever horizontal so the moment arm is
exactly `r`. Hold position, let it settle, record steady-state `I_q`. Approach
the hold point from **both** directions.

```
raising approach:   Kt * I_q+  =  m*g*r + tau_f
lowering approach:  Kt * I_q-  =  m*g*r - tau_f
```

Half-sum and half-difference separate them exactly:

```
m*g*r  =  Kt * (I_q+ + I_q-) / 2        load, friction cancelled
tau_f  =  Kt * (I_q+ - I_q-) / 2        friction, load cancelled
```

Repeat for 4–5 masses spanning the usable range, then least-squares fit
`(I_q+ + I_q-)/2` against `m*g*r`. The slope gives the torque constant; the
intercept is the current offset, which should sit near zero and is a check on
the rig itself.

**Honest caveat:** this measures `Kt` *through the gearbox*, so it is entangled
with `N*eta`. The defensible reported quantity is the product `Kt*N*eta` unless
the motor is characterised off the gearbox. §5.3 must therefore use this same
fit rather than treating `Kt` as independently known.

**Protocol detail that matters:** settle ≥5 s and average ≥100 samples per
point. Holding current wanders with rotor angle from cogging, so one reading is
not the mean.

**Figure 1:** half-sum current vs applied moment, fit line, residual inset,
slope ± CI and R² annotated.

### 5.2 Drag torque vs speed — Coulomb and viscous separated

Unloaded constant-velocity runs at 8–10 speeds spanning the usable range, both
directions, steady-state mean `I_q` per speed. The standard friction model:

```
tau_drag(omega) = tau_C + b * omega
```

Linear regression gives intercept `tau_C` (Coulomb, N·m) and slope `b`
(viscous, N·m·s/rev), each with a CI. Report both directions separately:
asymmetry is itself a finding (misaligned carrier, uneven preload).

This is the most legible chart in the set — a straight line through real data
yielding two coefficients with physical meaning. It feeds §5.3 (efficiency) and
§9.1 (thermal load), and it explains the "too weak to break stiction" branch
already in `do_step` (`host/joint_console_v2.py:434`): `tau_C` *is* the breakaway
threshold that branch detects.

Uses the console's existing `vel` mode. New command: `drag`.

**Figure 2:** drag torque vs speed, both directions, fit lines, `tau_C` and `b`
annotated with CIs.

### 5.3 Efficiency vs load

With a known output torque from the hanging mass, and `omega_in = N * omega_out`
by kinematics:

```
eta_gb = (tau_out * omega_out) / (tau_in * omega_in) = tau_out / (N * tau_in)
```

`N = 15`, `tau_in = Kt * I_q` from §5.1. **The speed terms cancel exactly**, so
no tachometer and no speed measurement are needed — only the two torques. That
cancellation is why §5.1 gates this test and why the rig stays simple.

Sweep load from light to the ceiling established in §7.4. Printed herringbone
planetaries typically land 70–90% and vary strongly with print quality and
preload, so this is genuinely informative rather than a formality.

**Also measure back-drive torque:** with the motor de-energised, the output
torque needed to turn the input. A non-back-drivable gearbox holds position on
power loss (a safety property); a back-drivable one needs holding current (a
thermal cost). Either answer is a real result about this joint.

**Figure 3:** `eta` vs output torque, with the §5.2 no-load drag marked as the
`eta -> 0` asymptote.

### 5.4 Independent confirmation of 15:1 from the data

A false 11.14:1 from hand rotation has already cost this project time. The data
can settle the ratio without touching the gearbox.

FFT the `I_q` and velocity ripple from a slow constant-velocity run. For a
ring-fixed planetary:

```
N = 1 + Z_ring / Z_sun

harmonic orders, per output (carrier) revolution:
  1              carrier / output bearing eccentricity
  n_planets      planet-passing
  Z_ring         ring tooth-meshing
  N_pp * 15      rotor electrical, from pole pairs
```

Fill in `Z_sun`, `Z_planet`, `Z_ring`, `n_planets` = `[FILL]` from tooth counts,
predict the orders, then confirm them in the spectrum. Agreement verifies the
ratio *from measurement*. A missing or damaged tooth appears as a sideband
around the mesh order, making this a free mechanical inspection as well.

**Figure 4:** order spectrum of velocity ripple, predicted orders marked.

### 5.5 Rotor + output inertia

Needed for the regen energy budget (§7.4) and the stopping-distance figure
(§9.3), and it cross-checks `omega_n` from §7.2.

Use the console's existing `torque` mode (`kp_scale = kd_scale = 0`, pure
feedforward). Command a constant torque and measure angular acceleration from
the velocity slope, in both directions. While moving:

```
tau = J * alpha + tau_C * sign(omega)
```

Runs at `+tau` and `-tau` give two equations in two unknowns:

```
J     = 2*tau / (alpha+ - alpha-)
tau_C = tau * (alpha+ + alpha-) / (alpha- - alpha+)
```

The recovered `tau_C` must agree with §5.2's intercept. **Two independent routes
to the same constant is a strong internal consistency check** — and if they
disagree, the friction model is richer than Coulomb + viscous, which is itself
worth reporting.

Fit `alpha` by linear regression on the velocity trace over the linear segment
only: exclude the first 100 ms (current-loop rise) and anything approaching the
velocity limit.

---

## 6. Backlash and stiffness

Three deliberately independent methods. Where they disagree, the disagreement is
the finding.

### 6.1 The torque–angle hysteresis loop — the headline chart

Ramp commanded torque slowly from `-tau_max` to `+tau_max` and back, logging
output angle from the external witness (§4).

**How slow?** Slow enough that inertia is negligible. Require the inertial term
to stay below 1% of the Coulomb term:

```
J * alpha  <  0.01 * tau_C
```

With `J` from §5.5 and `tau_C` from §5.2, solve for the maximum ramp rate. In
practice this lands at a 20–60 s full loop — but compute it rather than guessing,
and record the figure used.

One dataset yields both headline mechanical numbers:

```
backlash   = loop width at tau = 0                              [deg]
stiffness  = k_theta = d(tau) / d(theta) on the loaded branch   [N.m/deg]
```

And then the term that matters under load:

```
theta_windup = tau_applied / k_theta
```

This adds **linearly** to positioning error whenever the joint is loaded. It is
systematic, not random: it does not average out and it does not belong in an RSS
sum (§10).

Fit `k_theta` over the clearly linear portion of the loaded branch only, and
**report the fit range**. Printed gears stiffen non-linearly as teeth seat, so a
secant stiffness quoted without its range is meaningless.

A torque–angle hysteresis loop is the canonical gearbox figure. It belongs on
page one.

**Figure 5:** hysteresis loop, backlash width and fitted stiffness slope
annotated, fit range shaded.

### 6.2 Lost motion on reversal

Independent of §6.1 and needing no torque calibration at all — worth running
even before §5.1 exists.

Command `+delta` then `-delta`, sweeping `delta` from below the expected backlash
to well above it (0.1 to 5 deg, log-spaced). Plot achieved vs commanded reversal
amplitude. Below the backlash width the output barely moves — teeth are
traversing clearance — so the curve hugs zero. Above it the curve runs parallel
to the unity line, offset by the backlash. The knee is the backlash; the
asymptotic offset is a second, independent estimate of the same quantity.

**Figure 6:** achieved vs commanded reversal amplitude, unity line, knee and
asymptotic offset marked.

### 6.3 Transmission error vs output angle (Tier 2)

§3.3 suggested position-dependent error may be the largest single term but could
not confirm it. This is the test that can.

Sweep the output slowly through full travel at constant velocity, logging
commanded and witnessed angle continuously, both directions:

```
TE(theta) = theta_witnessed - theta_commanded
```

FFT `TE` against output *angle* (not time) and interpret by harmonic order using
the §5.4 table. The interpretation is the actionable part:

| Order | Cause | Correctable without an output encoder? |
|---|---|---|
| 1 | carrier / output bearing eccentricity | **Yes** — a lookup table on output angle |
| `n_planets` | planet spacing or sizing error | Partly |
| `Z_ring` | tooth-to-tooth error | **No** |

So this test does not merely quantify the position-dependent term, it
**partitions it into a calibratable and a non-calibratable part**. If order 1
dominates, a software calibration table recovers most of it for free.

**Sampling requirement:** resolving order `Z_ring` needs ≥2 samples per cycle by
Nyquist, realistically 4–8× that, so roughly `8 * Z_ring` points per output
revolution. With `Z_ring = [FILL]` likely of order 100+, that is ~1000 points per
revolution — hence Tier 2 only. At 0.05 rev/s output and 400 Hz logging you get
8000 points per revolution, comfortably enough.

**Figure 7:** `TE` vs output angle (both directions overlaid), with its order
spectrum as a second panel.

### 6.4 Direction split from random moves — already running

`do_random` already produces `dir_split_deg` (0.219–0.236 deg across the three
logged runs). Keep it. It measures backlash **as the closed loop experiences
it**, which is smaller than the mechanical width because the integrator
(`ki = 200`, `ilimit = 0.5`) partially walks the error out.

The ratio

```
backlash_mechanical (6.1) / dir_split (6.4)
```

quantifies how much of the backlash the controller is hiding. That is a result in
its own right, and the honest bridge between a mechanical number and a servo
number.

---

## 7. Responsiveness, from low power to maximum power

### 7.1 Fix the settling criterion first

`do_step` measures settling inside a band of 2% **of the commanded step**
(`host/joint_console_v2.py:400`). In degrees:

```
band_deg = 0.02 * delta_rev * 360 = 7.2 * delta_rev
```

Setting that equal to the measured backlash of 0.23 deg:

```
delta = 0.23 / 7.2 = 0.0319 rev = 11.5 deg
```

So **below ~0.032 rev the settling band is finer than the backlash itself**, and
"did not settle" is an artifact of the metric, not a property of the joint.
CLAUDE.md records this as "below ~0.05 rev"; the exact crossover is 0.032 rev.

Fix: **dual-criterion settling, both always reported.**

```
t_s_rel   first entry into +/- 2% of delta, never leaving      (existing)
t_s_abs   first entry into +/- 0.36 deg, never leaving          (new)
```

`0.36 deg = 0.001 rev`, which is exactly 2% of a 0.05 rev step — so the two
criteria coincide at `delta = 0.05 rev` and diverge either side. For large steps
they agree; for small steps `t_s_abs` is the meaningful one and `t_s_rel` is
noise.

Reporting "our own metric was unphysical below 0.032 rev, here is the
replacement and here is the crossover" is a credibility *gain*, not a weakness.

### 7.2 What the existing step numbers do and do not support

From 1.6% overshoot, the standard second-order relation:

```
OS = exp(-pi*zeta / sqrt(1 - zeta^2))

=>  zeta = -ln(OS) / sqrt(pi^2 + ln^2(OS))

ln(0.016) = -4.1352
zeta = 4.1352 / sqrt(9.8696 + 17.0999) = 4.1352 / 5.1932 = 0.796
```

**zeta ~= 0.80** — well damped, near the 0.707 textbook optimum.

Then from 2% settling, using the exact envelope `exp(-zeta*w_n*t)/sqrt(1-zeta^2)`
rather than the usual `4/(zeta*w_n)` shortcut:

```
t_s = -ln(0.02 * sqrt(1-zeta^2)) / (zeta * w_n)

exact envelope:   w_n = 32.6 rad/s = 5.19 Hz
4/(zeta*w_n):     w_n = 29.5 rad/s = 4.70 Hz
```

Quote the **range 4.7–5.2 Hz**, not a single figure — the spread is purely which
approximation is used, and hiding that is dishonest. Derived quantities, using
the exact value:

```
w_d = w_n*sqrt(1-zeta^2) = 19.7 rad/s = 3.14 Hz   ->  ring period T_d = 0.318 s
t_peak = pi / w_d = 0.159 s
closed-loop -3 dB bandwidth:
  w_bw = w_n * sqrt(1 - 2*zeta^2 + sqrt(4*zeta^4 - 4*zeta^2 + 2))
       = 32.6 * 0.876 = 28.6 rad/s = 4.55 Hz      (4.1 Hz on the other w_n)
```

**Now the important caveat, which changes how the test must be run.** The
overshoot is 1.6% and the settling band is 2%. The overshoot peak is therefore
*inside the band*. The response never leaves the band at the peak, so the
reported 0.17 s is **not a settling time at all — it is a rise time**, and it
carries no information about damping. Consistent with that, `t_peak` computes to
0.159 s, essentially the same instant.

The consequences are concrete:

- `zeta` and `w_n` above are **not two independent measurements**. One scalar
  (overshoot) fixes `zeta`; the other (a rise time misread as settling) then
  fixes `w_n`. The apparent agreement is partly circular.
- The 2% band is too coarse to see this joint's ringing at all. `t_s_abs` from
  §7.1 is the criterion that can.
- Sampling is *not* the problem for the overshoot figure. At `T_d = 0.318 s`, a
  worst-case 10 ms offset from the true peak underestimates the peak by
  `1 - cos(2*pi*0.010/0.318) = 1.94%` *of the overshoot* — i.e. 1.6% becomes
  1.63%. Negligible. But `t_s` is quantised to ±20 ms, i.e. **±12%** on a 0.17 s
  figure, and resolving the decay envelope across several ring cycles needs far
  more than the ~9 samples currently available.

**Therefore: do not extract zeta and w_n from features. Fit them.** (§7.3)

### 7.3 Second-order fit to the whole step response

Fit every sample by nonlinear least squares (Levenberg–Marquardt):

```
x(t) = x_f + A * exp(-zeta*w_n*t) * cos(w_d*t + phi),    w_d = w_n*sqrt(1-zeta^2)
```

Free parameters `x_f, A, zeta, w_n, phi`. This gives `zeta` and `w_n` with
genuine confidence intervals from the covariance matrix, uses all samples instead
of two, and — most valuable — produces an **RMS residual that tests whether a
second-order model is even right.**

It will not be, and that is the point. Expected departures, each diagnostic:

| Residual signature | Cause |
|---|---|
| flat spot near `t = 0` | backlash deadzone — teeth traversing clearance before load transfers |
| clipped initial slope | torque or current saturation (§7.4) |
| slow tail after apparent settling | integrator walking out static friction |
| residual growing with step size | non-linear stiffness, or hitting the velocity limit |

Then fit a second model with a backlash deadzone added and compare residuals.
Whichever fits better is the better description of the joint, and stating which
one won — with the residual numbers — is a far stronger result than any single
clean figure.

Raise the sample rate (§12 item 2) so the fit is well-conditioned: target ≥50
samples across the first two ring cycles, i.e. ≥150 Hz given `T_d = 0.318 s`.
400 Hz gives ample margin.

**Figure 8:** step response with fitted model overlaid, residuals in a second
panel, both models compared.

### 7.4 The step matrix — the actual "low power to maximum power" axis

Three-factor sweep, every cell logged:

| Axis | Values | Why these |
|---|---|---|
| step size `delta` | 0.5, 2, 11.5, 45, 90 deg | 0.5 and 2 are below the §7.1 crossover (backlash-dominated); 11.5 deg *is* the crossover; 45 and 90 are slew/torque-limited |
| `kp_scale` | 0.25, 0.5, 1.0, 2.0, 4.0 | effective `kp` = 225 × scale, from sloppy to buzzing |
| `max_torque` | 0.2, 0.5, 1.0, 2.0, ceiling | **the power axis — never yet explored; all existing data sits at 1.0** |

`do_sweep` already handles the `kp` axis and returns to a fixed base position
between runs (`host/joint_console_v2.py:797`), which is what stops a long sweep
marching the joint out of travel. Extend it to nest `delta` and `max_torque`.

Per cell record: overshoot%, `t_s_rel`, `t_s_abs`, peak |err|, zero crossings,
peak `I_q`, bus voltage minimum, fitted `zeta` and `w_n` with CIs, and residual
RMS.

#### The confounder that will otherwise ruin this chart: the supply

**Corrected 2026-10-18 — the firmware clips first, not the brick.** The config
dump reports `servo.max_power_W = 100` and `servo.max_regen_power_W = 10`
(against `servo.max_voltage = 30` and `flux_brake_margin_voltage = 4`, so flux
braking engages at 26 V). So the ceiling is a *configured firmware limit at
100 W*, below the 120 W supply, and regen is clipped at only 10 W — aggressive
deceleration will hit that long before the brick complains. Any "maximum power"
claim must name the 100 W firmware limit, not the supply. This is exactly the
confusion §7.4 was written to prevent, caught in the config before any run.

A 24 V / 5 A brick is **120 W**. The brick current-limits before the motor does,
and a sagging bus reads as a torque ceiling that is not the joint's. Rough scale,
assuming `eta = 0.8`, `tau_in = 1 N·m` so `tau_out = 12 N·m`:

```
P_mech = tau_out * omega_out * 2*pi

at 0.25 rev/s out  ->  19 W     comfortable
at 0.50 rev/s out  ->  38 W     comfortable
at 1.00 rev/s out  ->  75 W     plus copper and iron losses: approaching 120 W
```

So the supply bites at **high speed combined with high torque** — precisely the
top-right corner of the matrix. Required mitigations:

- **Log `VOLTAGE` on every sample.** It is not in the telemetry tuple today
  (§12 item 1). Without it, a supply-limited cell is indistinguishable from a
  mechanical limit.
- Flag any run whose bus droops more than ~1 V, and plot the droop alongside.
- Title the chart **"torque available at 24 V / 5 A"**, never "joint maximum
  torque".
- Expect `fault 34 OVER VOLTAGE (regen)` on aggressive deceleration into a brick
  with no dump resistor — already in `FAULT_NAMES`
  (`host/joint_console_v2.py:38`). Log it rather than be surprised; with `J` from
  §5.5 the recoverable energy is `E = 0.5*J*omega^2`, which bounds how bad it can
  get and tells you whether `servo.max_regen_power_W` and
  `servo.flux_brake_margin_voltage` need adjusting first.
- `LIMIT_REASONS` (`host/joint_console_v2.py:43`) already distinguishes
  `100 system voltage`, `101 motor temperature`, `102 max_torque ceiling`,
  `104 flux braking`. **Record which limit was active per cell** — this turns an
  ambiguous ceiling into a labelled one, and it is the single most useful column
  in the matrix.

#### A logging gap that must be closed before this runs

`log_run` filters the config dump to keys starting `servo.pid`, `servopos` and
`motor_position` (`host/joint_console_v2.py:756`), which the logged JSON
confirms. So `servo.max_current_A`, `servo.max_power_W`, `servo.max_voltage`,
`servo.max_regen_power_W` and `servo.flux_brake_margin_voltage` — every one of
them a knob that clips before anything physical does, and all five already known
to `CONFIG_LIMITS` — are **not recorded**. Widen the filter to the full dump
(§12 item 7), or a chart will eventually show a firmware limit and be read as a
mechanical one.

**Figure 9:** step-response family overlay across `delta` at nominal gains.
**Figure 10:** overshoot% and `t_s_abs` vs `kp_scale`, paired panels, one series
per `max_torque`.
**Figure 11:** peak `I_q` and bus-voltage minimum vs commanded step, with the
active limit reason encoded as the marker.

### 7.5 Closed-loop frequency response by sine sweep

The number a reviewer actually wants for "responsiveness" is bandwidth, measured
rather than inferred.

Command `A*sin(2*pi*f*t)` at log-spaced `f` from 0.1 Hz upward, several cycles
each. Per frequency, fit amplitude and phase by **linear** least squares — not
peak-picking, which is noise-sensitive and biased:

```
model:  y = a*cos(2*pi*f*t) + b*sin(2*pi*f*t) + c      (f known, so linear in a,b,c)

amplitude = sqrt(a^2 + b^2)
phase     = atan2(-b, a)
|G(f)|    = A_out / A_in        ->  -3 dB (ratio 0.707) is the bandwidth
angle G(f)                      ->  phase margin from the -180 deg crossing
```

Closed form, no iteration, and it yields a residual for free.

**Accept criterion:** if residual RMS exceeds 10% of the fitted amplitude, reject
that frequency point as untrustworthy (non-linearity, drift or a dropped sample).
Publishing a Bode point that failed its own fit is how a frequency response
becomes fiction.

**Amplitude choice — the thing most easily got wrong.** `A` must be large enough
that the loop is not sitting inside the backlash deadzone, but small enough to
stay linear:

```
A >> backlash (0.23 deg)   ->  A = 5 deg is ~22x the backlash
A << travel (+/-190 deg)   ->  comfortably satisfied
```

Then **run the whole sweep at two amplitudes (2 deg and 10 deg).** If `|G(f)|`
differs between them the system is non-linear, a single Bode plot is a lie, and
the honest object is a describing function at stated amplitude. Testing this
costs one extra sweep and protects the headline number.

**Sampling constraint, stated plainly.** At 50 Hz, Nyquist is 25 Hz but usable
fidelity needs ~10 samples/cycle, so `f <= 5 Hz`. The predicted bandwidth of
4.1–4.6 Hz (§7.2) sits **right at that ceiling** — the measurement would end
exactly where the interesting part begins. At 400 Hz, 25 Hz is clean at 16
samples/cycle. This is the second independent reason to raise the rate.

**Time cost:** 5 cycles per point over 0.1–25 Hz at quarter-decade spacing is
`sum(5/f) ~= 135 s`, dominated by the lowest frequencies. Use 3 cycles below
0.5 Hz to cut it further. Under 4 minutes per sweep — cheap for the most
informative chart in §7.

**What loop this measures, and why that is the right one.** moteus closes current
at ~30 kHz and position in the kHz range internally. A host-side chirp measures
**host + fdcanusb transport + controller + gearbox** — the loop the joint
actually presents to anything driving it. Naming the distinction explicitly
matters: it is the difference between characterising the servo and
characterising the system.

**Cross-validation, the strongest result available.** The chirp's −3 dB point
should land near the 4.1–4.6 Hz predicted from step data in §7.2. Two independent
methods agreeing is more persuasive than either alone; disagreement localises the
problem (§7.2's circularity, or a model-order error). Plot both on the same axes.

**Figure 12:** Bode magnitude and phase, two panels, both amplitudes, with the
§7.3 fitted second-order model overlaid as a dashed line and the step-derived
bandwidth marked.

---

## 8. Repeatability, with defensible statistics

### 8.1 Sample size, derived rather than guessed

§3.1 showed the current figures are ranges, and §3.2 that the max of 6 points
cannot support a comparison. Replace both with `sigma` and a stated percentile.
The relative 95% CI on an estimated standard deviation is

```
+/- 1.96 / sqrt(2(n-1))
```

Inverting for a target precision:

```
+/- 30%  ->  n = 22
+/- 25%  ->  n = 32
+/- 20%  ->  n = 49
+/- 15%  ->  n = 86
```

**Use n = 50 per condition** (±20%), with 32 as the practical floor. Below ~22
you are quoting noise, which is exactly what the existing n=6 figure does.

**This is affordable, which is why it is the right choice.** The logged runs did
20 moves + 20 reference returns in 87.2 s, i.e. 2.18 s per move. So n=50 with
returns is 100 moves ≈ **3.6 minutes per condition**. The six conditions in §8.2
total about 22 minutes of bench time. There is no reason to accept n=6.

**Report:** `mu`, `sigma`, the 95th percentile, `n`, and **`mu + 2*sigma` as the
design figure** — never the max. The maximum of a small sample is a famously bad
estimator: it has no bounded variance and drifts upward with `n`, so quoting it
makes a joint look worse the longer you test it.

### 8.2 Make the error terms orthogonal by design

This is the direct answer to the failed decomposition in §3.3. Rather than
untangling confounded terms afterwards, separate them in the experiment:

| Test | Protocol | Isolates |
|---|---|---|
| **8.2a** | fixed target, **fixed** approach direction, n=50 | pure repeatability `sigma_r` — no direction term, no position term |
| **8.2b** | fixed target, approach direction **alternated** +/-, n=50 each | the direction split cleanly, as a two-sample difference with its own CI |
| **8.2c** | 12-point position grid over +/-180 deg, both directions, n=10 each | position-dependent error vs absolute angle |

By construction `8.2a` contains no direction term, so `sigma_r` is clean. Then
`8.2b − 8.2a` is the direction term and `8.2c` residual-after-removing-both is
the position term. No negative variances, every term with a CI.

`do_random` already supports `ref`, `seed`, `min_deg` and `max_deg`
(`host/joint_console_v2.py:546`), so **8.2c needs only a fixed target list added**
— the smallest code change of any test here.

Use **random approach directions** for the headline number, never a fixed
two-point cycle: the project already learned the two-point figure flatters by
12×. Put that comparison in the report deliberately — "here is the number a
naive protocol gives, and here is why we do not quote it" is a strong page.

### 8.3 Conditions to cross

- **3 speeds** (`vel_limit` 0.1 / 0.3 / 1.0) — does repeatability degrade with
  speed? The 3.4× bench-to-workout gap in §3.1 predicts yes; this measures it.
- **2 move-distance bands** — `do_random` already splits near/far
  (`host/joint_console_v2.py:650`).
- **integrator on vs off** (`ilimit_scale` 1 vs 0) — isolates how much of the
  backlash the integrator hides, pairing with §6.4.
- **cold vs warm** — ties into §9.1.

**Figure 13:** error histogram with `mu ± 2*sigma` overlay, per speed.
**Figure 14:** error vs move distance scatter with a fitted trend.
**Figure 15:** paired box plots by approach direction, integrator on vs off.
**Figure 16:** position-dependent error vs absolute output angle (8.2c), with
the §6.3 transmission-error curve overlaid if Tier 2 exists — two independent
measurements of the same physical quantity.

---

## 9. Thermal and wear

### 9.1 Thermal soak

Hold against load for 20–30 min, logging `TEMPERATURE`, `I_q`, position. Measure
drag (§5.2, single speed) immediately before, immediately after, and again after
full cooldown.

Fit a first-order thermal model:

```
T(t) = T_inf + (T_0 - T_inf) * exp(-t / tau_th)
R_th = (T_inf - T_ambient) / P_loss
```

A 20–30 min soak covers 3–6 time constants if `tau_th` is 5–10 min, which is
enough to estimate `T_inf` rather than extrapolate wildly. Record ambient
temperature — without it `R_th` is meaningless.

**Two failure signatures that must be separated, because they have opposite
implications:**

- **`I_q` rising at constant load.** Either friction increasing (thermal
  expansion closing clearances) or `Kt` falling with magnet temperature.
  Distinguish by the cooldown drag measurement: if drag returns to baseline cold,
  it was `Kt`. Quantitatively, NdFeB remanence drifts about **−0.11 %/K**
  (reversible), so a 40 K rise predicts `Kt` down ~4.4% and `I_q` up ~4.6% at
  constant torque. **Predict it, then check it** — a prediction confirmed is
  worth far more than a measurement alone.
- **Position drifting at constant commanded torque.** That is polymer **creep**,
  the distinctive printed-gearbox risk, and it does not recover on cooldown.

**Caveat to state in the report:** moteus `TEMPERATURE` is the **board** sensor,
not the winding. It is a lower bound on motor temperature with unknown lag.
Do not dress it up as a motor temperature.

**Figure 17:** temperature, `I_q` and position drift on a shared time axis, with
the fitted thermal model; drag before/after/cooled as an inset bar triple.

### 9.2 Burn-in and wear — the highest-value measurement outstanding

CLAUDE.md open question 1: all J1 data is from a cold, fresh, unloaded gearbox,
and the burn-in has never been run.

```
protocol:  hysteresis loop (6.1) + drag (5.2) + repeatability (8.2a)
           at cumulative cycles N = 0, 100, 300, 1000, 3000
           driven between measurement points by:  cycle -0.5 0.5 <n>
```

**Why log spacing?** Wear-in is typically fast then asymptotic. Linear spacing
spends most of the bench time on the flat part where nothing changes. Half-decade
steps put the measurements where the curvature is.

**Why stop at 3000?** From `travel_time` (`host/joint_console_v2.py:454`) at
`vel_limit` 1.0 and `accel_limit` 1.0, a 1.0 rev leg takes 2.75 s, so a round
trip is 5.5 s:

```
  100 cycles  = 0.2 h
  300 cycles  = 0.5 h
 1000 cycles  = 1.5 h
 3000 cycles  = 4.6 h      <- one unattended session
10000 cycles  = 15.3 h
```

3000 cycles is a single long unattended run and is many times the duty of a
fair demo, so it is defensible coverage. 10000 costs 15 hours for extrapolation
nobody needs. **Extrapolating beyond 3000 is explicitly out of scope** — say so
rather than implying endurance data you do not have.

Three possible shapes, all publishable:

1. **Backlash grows then plateaus** — normal run-in. Quantify the plateau and
   state it as the design figure instead of the cold number.
2. **Backlash grows without bound** — wear-out. Printed gears will not survive
   extended use, and knowing that early is worth far more than knowing it late.
3. **Drag falls while backlash holds** — polishing-in, the happy case.

Fit an asymptotic form `y = y_inf - (y_inf - y_0)*exp(-N/N_tau)` and report
`y_inf` with its CI, so the plateau is a number rather than an eyeball judgement.

**Run the cold measurements of §6 before this.** Burn-in destroys the cold state
irreversibly — there is exactly one opportunity to measure it, which is why §10
orders the sessions the way it does.

**Figure 18:** backlash, `tau_C` and `sigma_repeatability` vs cumulative cycles
on a log x-axis, with fitted asymptotes.

### 9.3 Stopping distance (derived, no extra run)

From `J` (§5.5) and the maximum decel torque established in §7.4:

```
theta_stop = 0.5 * J * omega^2 / tau_max
```

A real safety figure for a joint that will move near people at a public fair,
obtained from data already collected. Tabulate it at each `vel_limit` used in
§8.3.

---

## 10. J1's own error budget

The synthesis that ties the bench numbers together. **J1 only** — no whole-arm
projection.

### 10.1 Systematic and random terms do not combine the same way

```
theta_total = SUM(systematic) + sqrt(SUM(random^2))
```

- **Systematic / direction- or position-dependent:** backlash (§6.1), compliance
  wind-up (§6.1), transmission error (§6.3). These add **linearly** within a
  given direction of approach. They do not average out over repeated moves.
- **Random / independent:** landing scatter (§8.2a), encoder quantisation
  (§2.1, negligible at 0.0015 deg), host timing jitter (§2.3). These combine in
  **RSS**.

Getting this wrong in either direction misleads: RSS-ing everything flatters the
joint, summing everything panics about a number that will never occur.

### 10.2 To Cartesian error at a given radius

```
e = R * theta_rad = R * theta_deg * pi/180

at R = 400 mm, theta = 0.36 deg:   e = 400 * 0.006283 = 2.513 mm
```

which reproduces the figure in CLAUDE.md exactly and confirms the conversion.

Report the budget as a table of contributions, each with its measured value, its
classification (systematic or random), and the section it came from. The loaded
case must be reported separately from the unloaded one, because `theta_windup`
is zero in one and not the other — and the loaded case is the one that matters.

**Figure 19:** stacked bar of J1 error contributions, systematic and random
shaded differently, unloaded vs loaded side by side.
**Figure 20:** J1 Cartesian error vs radius, both load cases.

---

## 11. Figure list

| # | Figure | From |
|---|---|---|
| 1 | Torque-constant fit: half-sum current vs applied moment | §5.1 |
| 2 | Drag torque vs speed, both directions, `tau_C` and `b` | §5.2 |
| 3 | Gearbox efficiency vs output torque | §5.3 |
| 4 | Order spectrum of velocity ripple, ratio confirmation | §5.4 |
| 5 | **Torque-angle hysteresis loop** (backlash + stiffness) | §6.1 |
| 6 | Lost motion vs commanded reversal amplitude | §6.2 |
| 7 | Transmission error vs output angle + order spectrum | §6.3 |
| 8 | Step response with fitted model and residuals | §7.3 |
| 9 | Step-response family across step size | §7.4 |
| 10 | Overshoot and settling vs `kp_scale`, per `max_torque` | §7.4 |
| 11 | Peak current and bus droop vs step, limit reason encoded | §7.4 |
| 12 | **Bode magnitude and phase**, two amplitudes, model overlaid | §7.5 |
| 13 | Repeatability histograms with `mu ± 2 sigma`, per speed | §8.3 |
| 14 | Error vs move distance | §8.3 |
| 15 | Error by approach direction, integrator on vs off | §8.3 |
| 16 | Position-dependent error vs absolute angle | §8.3 |
| 17 | Thermal soak: temperature, current, drift | §9.1 |
| 18 | **Wear: backlash, drag, sigma vs cumulative cycles** | §9.2 |
| 19 | J1 error budget, stacked, unloaded vs loaded | §10 |
| 20 | J1 Cartesian error vs radius | §10 |

The four bolded figures are the ones a senior reviewer will look at first.

---

## 12. Software changes required

Strict value order. Nothing here is a new framework —
`host/joint_console_v2.py` already has `step`, `cycle`, `random`, `backlash`,
`sweep`, `log_run` (JSON + CSV + rolling history), `--script` and `--cmd`.

1. **Richer telemetry — do this first; most charts are blocked on it.** The
   sample tuple in `control_loop` (`host/joint_console_v2.py:143`) is
   `(t, position, velocity, torque)`. Add `Q_CURRENT`, `D_CURRENT`, `VOLTAGE`,
   `TEMPERATURE` and the **commanded** position (so per-sample tracking error is
   computed, not inferred). Update `write_csv`'s header to match
   (`host/joint_console_v2.py:793`). Without this: no §5.1, no §5.3, no §7.4
   droop detection, no §9.1, and no honest torque anywhere.

2. **A `--rate` flag** raising `CONTROL_HZ` for characterisation runs, and log
   achieved inter-sample jitter alongside. Required by §7.3 (fit conditioning)
   and §7.5 (Nyquist); delivers the §2.3 jitter dataset as a side effect.

3. **Four new commands:**
   - `drag` — velocity sweep both directions, regression to `tau_C`, `b`, R² (§5.2)
   - `hysteresis` — slow bidirectional torque ramp with external-witness capture (§6.1)
   - `chirp` — log-spaced sine sweep, per-frequency linear LSQ amplitude/phase (§7.5)
   - `soak` — timed hold under load with thermal logging and model fit (§9.1)

4. **An external-witness channel.** A side CSV of
   `(timestamp, external_deg, source)` merged offline on timestamp, so
   dial-indicator and AS5048A readings join the logs as first-class columns.
   Without it, class B stays unmeasured permanently (§2.2).

5. **`analyze_j1.py` — plotting strictly offline and separate.** Reads the logs,
   emits every figure in §11. Keeping it out of the measurement path means a
   plotting bug can never cost a bench session. Load the `dataviz` skill before
   writing it so all 20 figures read as one visual system.

6. **Self-verification on every automated run**, per the project's own
   dominant-failure-mode gotcha. Abort loudly on: did it actually move (>5% of
   commanded, logic already in `do_step` at `host/joint_console_v2.py:421`); did
   the bus hold; did temperature stay bounded; is `n_achieved == n_requested`;
   were samples dropped (check the jitter histogram for gaps). A characterisation
   campaign is the worst possible place for a run that produces a plausible file
   from a broken setup, because five gearboxes would be designed on it.

7. **Widen `log_run`'s config capture** (`host/joint_console_v2.py:756`) from the
   `servo.pid`/`servopos`/`motor_position` prefixes to the full board dump, and
   record ambient temperature, fixture geometry (`r`, masses) and warm-up state
   per run. Required by §7.4. A number without its conditions is unusable in two
   months.

---

## 13. Session sequencing

| # | Session | Needs | Output |
|---|---|---|---|
| S0 | Telemetry + `--rate` + witness channel; build Tier 1 fixture; verify in sim | no motor | richer CSVs, fixture, jitter baseline |
| S1 | `Kt` calibration, drag vs speed, efficiency, back-drive, inertia, ratio FFT | fixture | torque becomes traceable; Figs 1–4 |
| S2 | Hysteresis loops, lost motion, transmission error — **cold** | fixture (+Tier 2) | backlash, stiffness; Figs 5–7 |
| S3 | Step matrix, chirp Bode, model fits and cross-check | high rate | Figs 8–12 |
| S4 | Repeatability 8.2a/b/c × 3 speeds × integrator on/off | — | Figs 13–16 |
| S5 | Thermal soak; burn-in to 3000 cycles with measurements at each point | long unattended run | Figs 17–18 — the de-risking data |
| S6 | Error budget, write the report | — | Figs 19–20, the deliverable |

**Ordering logic, explicitly:**

- **S1 before everything** — `Kt` gates every torque number (§5.0). Running it
  late means redoing §5.3, §6.1 and §7.4.
- **S2 before S5** — burn-in destroys the cold state irreversibly. There is
  exactly one cold baseline available, ever (§9.2).
- **S3 before S4** — the gains chosen in S3 are the conditions S4 runs under.
  Reversing them means S4 characterises a tune you then abandon.
- **S5 last** — mostly unattended wall-clock time, so start its cycling in the
  background during S3/S4 if the bench allows.
- **S1 and S2 share the Tier 1 fixture** — build it once, in S0.

---

## 14. Limitations — to be written last and kept honest

The section that earns the credibility. A senior engineer reads a limitations
section to decide whether to trust the rest, so it is written plainly and
without hedging:

- **Rotor-side measurement only** unless Tier 2 was fitted. Everything
  downstream of the sun gear is inferred (§2.2). Name which figures this affects.
- **Board temperature, not winding temperature** (§9.1).
- **Torque is derived from `Kt`, not measured**, and `Kt` as measured here is
  entangled with `N*eta` (§5.1).
- **Maximum power figures are bounded by a 120 W supply**, not by the motor
  (§7.4). If the 36 V bus is the demo supply, these curves need re-running —
  decide before S3, not after.
- **`n` per condition**, with CIs stated, and the §3.2 lesson applied: no figure
  from n < 22 appears in the report.
- **Unloaded only.** Base yaw has no gravity load; these numbers are a floor,
  not a prediction for a loaded joint.
- **Wear characterised to 3000 cycles**; no claim beyond that (§9.2).
- **What was not measured at all**, listed explicitly.

Numbers with stated uncertainty and named blind spots read as competence. Clean
numbers with no error bars read as inexperience. The two places to be loudest
are the supply-limited torque ceiling and the class-B blind spot.

---

## 15. First bench results — 2026-10-18 (Tier 0, rotor encoder only)

**What ran:** liveness probe, full config dump, five logged step responses across
the §7.4 `delta` axis, a `kp_scale` sweep at the crossover step, and an n=50
repeatability run. All on the real joint, 11 records in `host/logs/`.

**Conditions:** `kp_scale`/`kd_scale`/`ilimit_scale` 1.0, `max_torque` 1.0 N·m,
`vel_limit` 0.25, `accel_limit` 1.0, bus 23.5 V, board temperature 26 °C at
start and 30 °C at the end. Identical to the 2026-08-26 runs apart from `n`.

**What did not run, and why:** all of §5 (no lever or hanging masses), §6.1 and
§6.3 (no external witness), §6.2 (meaningless at Tier 0 — the rotor encoder
cannot see lost motion), `backlash` and `ratio` (both need a hand on the
output), `drag`/`chirp`/`soak` (specified in §12 but unwritten), and §9.2
burn-in (4.6 h unattended). **The campaign is approximately 25% run.**

### 15.1 The §7.1 crossover prediction is confirmed exactly

Predicted: the relative settling band equals the backlash at
`delta = 0.23/7.2 = 0.0319 rev = 11.5 deg`, below which "did not settle" is an
artifact. Measured:

| delta (deg) | band_rel (deg) | `t_s_rel` | `t_s_abs` | overshoot % | final err (deg) | peak torque (N·m) |
|---|---|---|---|---|---|---|
| 0.50 | 0.010 | **none** | 0.06 | −5.8 | −0.032 | 0.526 |
| 2.00 | 0.040 | **none** | 0.14 | −14.8 | −0.302 | 0.628 |
| 11.48 | 0.230 | 1.03 | 1.00 | −1.5 | −0.174 | 0.764 |
| 45.00 | 0.900 | 0.72 | 0.77 | −0.4 | −0.179 | 0.777 |
| 90.00 | 1.800 | 1.16 | 1.22 | +0.1 | +0.060 | 0.766 |

The relative criterion fails at 0.50 and 2.00 deg and succeeds from 11.48 deg
up. **The flip happens precisely at the predicted crossover.** The absolute
criterion settles all five.

**But the absolute criterion is degenerate at the other end.** At
`delta = 0.5 deg` the ±0.36 deg band is 72% of the entire step, so the joint is
"settled" after moving 0.14 deg. `t_s_abs = 0.06 s` is not a settling time
either. The honest conclusion is that **neither criterion is meaningful for
`delta` below roughly 2 deg**, because the joint's static error floor
(0.03–0.30 deg) is comparable to the step itself. For that regime, report the
static error floor and stop using the word "settling".

Revised recommendation, superseding §7.1: report `t_s` against a band of
`max(2% of delta, 0.36 deg)`, **and** state `delta_min = 1.8 deg` (5× the
absolute band) as the smallest step for which any settling figure is reportable.

### 15.2 The joint does not overshoot, and the documented step figures do not reproduce

CLAUDE.md records "1.6% overshoot, 0.17 s settle". Neither reproduces:

- **Overshoot is negative for four of five steps** (−14.8% to +0.1%). The joint
  approaches monotonically from below. Zero crossings were 0 everywhere except
  one at the 90 deg step. The joint is **overdamped**, so the §7.2 derivation of
  `zeta ~= 0.80` from a 1.6% overshoot has no measured basis — `zeta >= 1`.
- **Settling times are 0.72–1.22 s, 4–7× the documented 0.17 s.**

Since §3.4 established those figures have no logged provenance, the resolution
is simply that they are not reproducible on the current configuration and should
be removed from CLAUDE.md rather than explained.

### 15.3 §7.3's premise is wrong: these are not step responses

The five-parameter second-order fit failed to converge on every trace, staying
pinned at its initial guess, with RMS residuals growing from 0.08 deg at
`delta = 0.5 deg` to 28.0 deg at 90 deg. The model is wrong, and the reason is
structural.

`goto` and `step` pass through moteus's **trajectory generator**, which is
rate-limited by `vel_limit` and `accel_limit`. Comparing measured settling to
`travel_time()` (`host/joint_console_v2.py:454`):

| delta (deg) | `t_s_abs` (s) | trapezoidal prediction (s) | ratio | regime |
|---|---|---|---|---|
| 0.50 | 0.06 | 0.075 | 0.80 | accel-limited |
| 2.00 | 0.14 | 0.149 | 0.94 | accel-limited |
| 11.48 | 1.00 | 0.357 | **2.80** | accel-limited |
| 45.00 | 0.77 | 0.750 | 1.03 | cruise-limited |
| 90.00 | 1.22 | 1.250 | 0.98 | cruise-limited |

**Four of five match the trajectory duration to within 20%.** The measured
"settling time" is overwhelmingly the trajectory generator, not joint dynamics.

Consequences:

- **A true step response cannot be measured with `vel_limit` and `accel_limit`
  active.** §7.3 and §7.5 must raise both until the trajectory generator is no
  longer the binding constraint, then confirm that settling time stops tracking
  `travel_time()`. Until that is done, no `zeta` or `omega_n` figure for this
  joint is defensible — including the ones in §7.2.
- **The 11.48 deg point is the one real outlier at 2.80×**, and it sits exactly
  at the backlash/band crossover. That extra 0.64 s is a genuine dynamic effect —
  plausibly the final approach through backlash, or the integrator walking out
  the last fraction of a degree. It is the most interesting single data point
  collected and deserves a dedicated high-rate run.

### 15.4 Host timing jitter — open question 6, answered for free

From the inter-sample deltas of all five traces, exactly as §2.3 predicted
would come free:

| delta (deg) | mean (ms) | sd (ms) | min | max | n |
|---|---|---|---|---|---|
| 0.50 | 15.62 | 0.48 | 15 | 16 | 127 |
| 2.00 | 15.75 | 1.45 | 15 | 31 | 126 |
| 11.48 | 15.82 | 1.79 | 15 | 31 | 157 |
| 45.00 | 15.62 | 0.48 | 15 | 16 | 191 |
| 90.00 | 15.84 | 1.85 | 15 | 31 | 220 |

Two findings:

1. **`CONTROL_HZ = 50` does not produce 50 Hz.** The real interval is 15.6 ms,
   i.e. **~64 Hz**. `asyncio.sleep(0.02)` is being rounded to the Windows
   scheduler tick of 15.6 ms.
2. **Jitter is quantised, not Gaussian** — every interval is 15.6 ms or 31.2 ms
   (one tick or two), which is why `sd` is bimodal across runs (0.48 ms when no
   doubles occurred, ~1.8 ms when they did). Worst observed gap is 2 ticks.

This is a bounded, well-understood jitter source rather than the open-ended risk
CLAUDE.md describes. It also means **any `--rate` above ~64 Hz needs a different
timing mechanism**, not just a larger constant — the Windows tick is the
limit until the timer resolution is raised explicitly.

### 15.5 Repeatability at n=50, and what changed since August

Same seed, same bounds, same gains. All differences tested rather than eyeballed.

| metric | 2026-08-26 (n=20, mean of 3) | 2026-10-18 (n=50) | ratio | significant? |
|---|---|---|---|---|
| landing-error `sigma` | 0.2261 deg | 0.2950 deg | 1.30× | **No** — F=1.70, p=0.21 |
| direction split | 0.2283 deg | 0.0231 deg | 0.10× | **No** — z=1.56, p=0.12 |
| reference `sigma` (range-normalised) | 0.0970 deg | 0.2259 deg | **2.33×** | range-based, wide CI |
| systematic offset at reference | 0.0573 deg | 0.1609 deg | 2.8× | — |

Notes:

- **The scatter increase is not statistically significant** (p=0.21), despite
  the 1.30× ratio. The 95% CIs overlap: [0.154, 0.298] vs [0.237, 0.353]. This
  is §3.2's lesson applied to new data — and at n=50 the Oct interval is ±20%
  as designed, versus ±32% in August.
- **The direction split has collapsed from marginally-significant to
  indistinguishable from zero** (0.0231 ± 0.0835 SE). Suggestive of the
  September greasing removing stiction-driven approach dependence, but at
  p=0.12 the *change* is not significant either. Worth one repeat run to settle.
- **The reference-point figure is 2.33× worse** after normalising for `n`. Note
  the raw ranges (0.3625 vs 1.0162) would read as 2.80× — §3.1's correction
  mattering again on fresh data.
- **Short moves are now worse than long** (0.307 vs 0.228 deg mean |err|),
  reversing the usual expectation. Consistent with backlash and stiction
  dominating small displacements, which is the §6.2 regime.

### 15.6 The design figure, restated

With `mu = -0.0951 deg` and `sigma = 0.2950 deg` at n=50:

```
design figure = |mu| + 2*sigma = 0.685 deg
at 400 mm reach:  400 * 0.685 * pi/180 = 4.78 mm
```

The project currently designs around 0.36 deg → 2.51 mm. **That 0.36 deg was
never a sigma — it was the range of 20 samples** (§3.1). The properly defined,
n=50 figure is **0.685 deg → 4.78 mm from J1 alone, unloaded — 1.9× the
assumed error.**

This is the single most consequential number from the session, and it is worse
than the assumption rather than better.

### 15.7 Gain sweep: the current tune is conservative

`sweep kp` at the crossover step (`delta = 0.0319 rev`), one run per cell:

| `kp_scale` | effective `kp` | overshoot % | `t_s_rel` | final err (deg) | ringing |
|---|---|---|---|---|---|
| 0.25 | 56 | 6.5 | none | 0.737 | 1 |
| 0.50 | 113 | 5.9 | none | 0.672 | 1 |
| **1.00** | **225** | −0.0 | 1.30 | −0.003 | 0 |
| 2.00 | 450 | −1.4 | **0.34** | −0.165 | 0 |
| 4.00 | 900 | −0.5 | **0.36** | −0.057 | 0 |

- **`kp_scale` 2.0–4.0 settles ~3.8× faster than the current tune** (0.34–0.36 s
  vs 1.30 s) with no overshoot and no ringing. The current `kp = 225` looks
  conservative for this step size.
- At `kp_scale` ≤ 0.5 the joint is too soft to close the last degree: final error
  0.67–0.74 deg exceeds the 0.23 deg band, so it cannot settle by the relative
  criterion — a third independent confirmation of §7.1.
- Peak torque reached 0.80 N·m at `kp_scale` 4.0 against the 1.0 N·m ceiling, so
  authority was not saturated.

**Do not change the tune on this evidence.** It is n=1 per cell, one step size,
one torque ceiling, unloaded, and higher stiffness is exactly what will ring
once J1 carries the rest of the arm. It is a strong hypothesis for §13 S3, not a
result.

### 15.8 Corrections this session forced on the plan

| § | Was | Now |
|---|---|---|
| 2.1 | 14-bit encoder assumed | **confirmed**, `cpr = 16384`; `pll_filter_hz = 200` also bounds §7.5 |
| 2.3 | 50 Hz, 20 ms | **64 Hz, 15.6 ms**, quantised to the Windows tick (§15.4) |
| 7.1 | absolute band fixes small steps | fixes the lower end, **degenerate below ~1.8 deg** (§15.1) |
| 7.2 | `zeta ~= 0.80` from 1.6% overshoot | **no overshoot exists**; `zeta >= 1`; the source figures do not reproduce (§15.2) |
| 7.3 | fit a second-order model | **wrong model** — these are rate-limited trajectories, not steps (§15.3) |
| 7.4 | 120 W supply is the ceiling | **`servo.max_power_W = 100`** clips first; regen clipped at 10 W |
| 8.1 | n=50 for ±20% CI | confirmed: achieved ±20%, and 211 s per run as predicted |
| 10.2 | 0.36 deg → 2.51 mm | **0.685 deg → 4.78 mm** (§15.6) |
| 5.0 | torque side-of-reduction unstated | **output-side, already ×15** — proven from `Kv=330` vs the 10 A limit (§5.0.1) |

### 15.10 The torque axis was never actually stretched

Now that §5.0.1 fixes the units, the whole session sits in the bottom quarter of
the joint's envelope:

| quantity | value | as a fraction of available |
|---|---|---|
| `max_torque` ceiling used all session | 1.0 N·m output | **23%** of the 4.34 N·m at the 10 A limit |
| peak actually drawn (45 deg step) | 0.777 N·m output = 1.79 A | 18% |
| breakaway (0.5 deg step) | 0.526 N·m output = 1.21 A | 12% |

So the "breakaway torque" figure of ~0.53 N·m output is a real and useful
number (it is the §5.2 `tau_C` seen from the output side, lossless-referred),
but **every responsiveness result in §15 was obtained at under a quarter of
available torque.** The `max_torque` axis of §7.4 remains entirely unexplored,
and that is now the cheapest remaining experiment — it needs no fixture, only
`limit torque <v>` and a re-run.

Also, the 100 W firmware clip does **not** bind at the speeds used:

```
100 W / 4.341 N.m = 23.0 rad/s = 3.67 rev/s output
vel_limit in use  = 0.25 rev/s   ->  15x below the power clip
```

So in this operating region the joint is **current-limited, not power-limited**,
which refines the §7.4 warning: the 100 W ceiling matters only above ~3.7 rev/s
output, far faster than anything run so far. Regen at 10 W remains the limit
worth watching on deceleration.

### 15.9 Next actions, in priority order

1. **Raise `vel_limit`/`accel_limit` and re-run the `delta` sweep.** Everything
   in §7 is currently measuring the trajectory generator (§15.3). This is one
   console command and it unblocks the whole responsiveness section.
2. **Save per-move samples in `do_random`.** `log_run` is called without the
   `samples` argument (`host/joint_console_v2.py:669`), so the 50 landing errors
   were lost — only summary statistics survived, and the console's own stdout is
   a rolling buffer. Percentiles, normality and re-stratification are all
   impossible after the fact. **This is now the top item in §12**, ahead of
   richer telemetry.
3. **One repeat n=50** to test whether the direction-split collapse is real
   (§15.5).
4. Build the Tier 1 fixture (§4) — nothing in §5 or §6 can run without it.
5. Add `VOLTAGE`/`Q_CURRENT` to telemetry before any `max_torque` sweep, so the
   100 W firmware clip is visible when it binds.

### 15.11 "Full speed" attempt — a firmware velocity cap nobody knew about

Attempted a progressive speed ladder (bare output, nothing attached), stepping
`vel_limit`/`accel_limit` together at `max_torque` 3.0 N·m: 0.5/2, 1.0/5,
1.5/10, 2.0/15. **It stopped at the first rung, and the reason was a config
value, not the joint.**

```
servo.max_velocity          = 0.5      <- hard cap, output rev/s
servo.max_velocity_derate   = 2
servo.default_velocity_limit = 0.25    <- where the console default comes from
```

`status` read `vel = +0.5003` then `+0.4991` — pinned exactly at the cap.
Commanding `vel_limit` above 0.5 has no effect.

**Why this corrupted three of the four runs.** `travel_time()`
(`host/joint_console_v2.py:454`) computes the dwell from the *commanded*
`vel_limit`, which the firmware then ignores. So `cycle` sampled the joint
mid-flight:

| `vel_limit` | actual | true motion time | dwell used | short by | neg-target error | verdict |
|---|---|---|---|---|---|---|
| 0.5 | 0.5 | 2.05 s | 2.80 s | — | −0.0006 rev | **ok** |
| 1.0 | 0.5 | 1.90 s | 1.85 s | 0.05 s | +0.037 rev | invalid |
| 1.5 | 0.5 | 1.85 s | 1.50 s | 0.35 s | +0.180 rev | invalid |
| 2.0 | 0.5 | 1.83 s | 1.33 s | 0.50 s | +0.267 rev | invalid |

The shortfall predicts the error exactly: 0.50 s × 0.5 rev/s = 0.25 rev against
0.267 rev observed.

**The dangerous part is what got logged.** Those truncated moves were recorded
as `backlash_deg` of **30.11, 77.51 and 108.42 degrees** — physically absurd for
a joint whose backlash is ~0.23 deg, sitting in `j1_history.csv` next to real
numbers. `do_cycle` *did* print a "mean landing is far off" warning, but it
logged the metric anyway. **This is exactly the silent-partial-success failure
mode CLAUDE.md names: a test that cannot fail.** `do_cycle` must refuse to emit
`backlash_deg` when the mean landing error exceeds a few percent of the
commanded travel.

**Treat these three records as void:** `20261018-145931`, `20261018-145937`,
`20261018-145943`. Only `20261018-145924` (vel 0.5) is valid, and it gives a
legitimate two-point figure at 2× the usual speed: backlash 0.75 deg, spreads
0.30 / 0.01 deg — though at only 2 round trips it carries little weight.

**Also: `do_cycle` saves no samples either** (0 cycle CSVs on disk), same gap as
`do_random` (§15.9 item 2). Of the three test commands, only `do_step` logs raw
samples. That makes the §12 sample-logging item apply to all three.

### 15.12 What the joint's real speed ceiling is

The motor is capable of far more than the config allows:

```
Kv = 330 RPM/V, 24 V bus, 15:1

no-load theoretical     330 * 24      = 7920 RPM rotor = 8.8 rev/s output
FOC voltage-limited     330 * 24/sqrt(3) = 4574 RPM    = 5.1 rev/s output
                                                          (no field weakening)
configured cap                                         = 0.5 rev/s output
```

So **`servo.max_velocity` is holding the joint 10–18× below its capability**,
and the project has been operating at 0.25 rev/s — half of even that cap.

Two further constraints bound any attempt to actually use that headroom:

1. **Travel.** With 1.06 rev of usable travel, peak speed in position mode is
   `sqrt(accel * distance)`. Reaching 5 rev/s needs ~24 rev/s² and reaching
   8.8 rev/s needs ~70 rev/s² — and the joint is at peak for only an instant
   mid-travel. Sustained high speed requires continuous rotation, which means
   relaxing `servopos`, not just `servo.max_velocity`.
2. **Regen.** `servo.max_regen_power_W = 10`. Braking from 5 rev/s with ~1 N·m
   is `1 * 31.4 = 31 W`, 3× over the cap, so deceleration will trip
   over-voltage (fault 34) or dump into flux braking at 26 V. A high-speed test
   is really a regen test.

**Recommended next step, if the speed envelope is wanted:** raise
`servo.max_velocity` *without* persisting to flash, so a power cycle restores
the safe value, and re-run the ladder with dwells computed from the real cap.
Do it in small increments with temperature watched — 7920 RPM on the rotor side
of a printed herringbone planetary is the one irreversible risk in this whole
plan.

---

## 16. Fixing the under-capability problem

### 16.1 Most of the caps are correct, and deliberately so

`PROFILE` in `host/joint_setup_v2.py:42` is version-controlled and well-reasoned.
Its own comments document the intent:

| Value | In `PROFILE`? | Verdict |
|---|---|---|
| `servo.max_regen_power_W = 10` | yes — *"mains supply cannot sink regen, dissipate it in the windings instead"* | **correct**, and the arithmetic confirms it (§16.3) |
| `servo.flux_brake_margin_voltage = 4` | yes | correct — the companion to the above |
| `servo.max_power_W = 100` | yes | deliberate |
| `servo.max_current_A = 10` | yes | deliberate, but set by nothing in particular (§16.4) |
| `servo.default_timeout_s = 0.25` | yes — *"THE SAFETY ONE"* | correct |
| `servo.default_velocity_limit = 0.25` | yes | deliberate |
| **`servo.max_velocity = 0.5`** | **no — absent entirely** | **unmanaged; this is the one that bit us** |

So this is not a case of timid configuration. It is one unmanaged value in an
otherwise deliberate set.

### 16.2 The actual defect: the board's config is not under version control

Three symptoms, one root cause:

1. **`servo.max_velocity = 0.5` is on the board but in no file.** It was never
   written by the project's tooling, nobody knew it existed, and it silently
   truncated three of four runs in §15.11 while logging a 108 deg "backlash".
2. **`servopos` has drifted.** The board reports ±0.55 rev; `PROFILE` specifies
   ±0.25 rev (`JOINT_MAX_REV`). A **2.2× discrepancy** on the travel limits, with
   no record of which is intended or when it changed.
3. **`profile_1.json` was never committed** — `git log --all` finds no trace,
   despite CLAUDE.md listing it as "tuned J1 config — COMMIT THIS". There is no
   reference snapshot, so drift is undetectable by construction.

**The tooling to fix this already exists and has never been used:**
`joint_setup_v2.py` has `--sync` (snapshot board → profile), `--check`
(calibration status + profile drift), `--apply`, and `--dump --backup`.

**Fix 1 — close the config loop. Do it regardless of any speed decision:**

> **⚠ NOT zero risk — the ORDER is load-bearing (inserted after review).**
> `PROFILE` and the board disagree on the integrator, and `PROFILE` is the one
> that is wrong:
>
> | | board (live) | `PROFILE` | CLAUDE.md |
> |---|---|---|---|
> | `servo.pid_position.ki` | **200** | **0.0** | 200 |
> | `servo.pid_position.ilimit` | **0.5** | **0.0** | 0.5 |
>
> **`--apply` before `--sync` zeroes the integrator**, destroying the tune
> CLAUDE.md documents and invalidating the 0.23° backlash figure, which is
> explicitly "direction split, *with integrator*". This document depends on
> those live values itself — §6.1 reads the hysteresis width against
> `ki = 200, ilimit = 0.5`.
>
> **`--sync` first**, which snapshots the board into `profile_1.json`; per
> `joint_setup_v2.py:73` that file then overrides the `PROFILE` dict, which
> defuses the trap permanently. The sequence below is already in the right
> order — but "zero risk" invites someone to reach for `--apply` to fix the
> servopos discrepancy, and that is the one move that must not happen first.

- `--sync`, then **commit `profile_1.json`**. That is the reference snapshot.
- Add `servo.max_velocity` to `PROFILE` with an explicit commented value.
- Resolve the ±0.25 vs ±0.55 servopos discrepancy deliberately, and record why.
- Run `--check` at the start of every bench session.
- **Have the host read `servo.max_velocity` at startup and clamp `vel_limit` to
  it with a warning.** This single change would have prevented every corrupted
  record in §15.11.
- Make `travel_time()` (`host/joint_console_v2.py:454`) use the *effective*
  limit, not the commanded one.
- Make `do_cycle` and `do_random` refuse to emit metrics when the mean landing
  error exceeds a few percent of commanded travel.
- Widen `log_run`'s config capture (§12 item 7) so every record carries the
  limits that were actually in force.

### 16.3 Fix 2 — set the speed cap from a requirement, and the requirement is regen

A 90 deg base-yaw move (0.25 rev), by trapezoidal time:

| `vel_limit` | `accel_limit` | time | note |
|---|---|---|---|
| 0.5 | 1.0 | **1.00 s** | today |
| 0.5 | 4.0 | 0.62 s | accel alone buys a lot |
| 1.0 | 4.0 | 0.50 s | |
| **1.5** | **8.0** | **0.35 s** | recommended ceiling |
| 5.0 | 24.0 | 0.20 s | voltage-limited max |

There is no demo requirement beyond ~0.35 s for a 90 deg move, and the regen cap
independently picks out the same ceiling:

```
braking at 1 N.m from 0.5 rev/s  ->  3.1 W    within the 10 W cap
braking at 1 N.m from 1.5 rev/s  ->  9.4 W    right AT the cap
braking at 1 N.m from 5.0 rev/s  -> 31.4 W    3.1x over
```

**So ~1.5 rev/s is not an arbitrary choice — it is where the regen limit binds**,
and the regen limit is set by a hardware fact the project already documented:
a mains brick cannot sink current. The correct speed ceiling is therefore
derived, not guessed.

**Recommendation: `servo.max_velocity = 1.5`, `default_accel_limit = 8`.** That
is 3× faster moves, still 3.4× below the voltage-limited maximum, and regen
stays inside its cap. Raising regen headroom is a *hardware* change — a dump
resistor or a battery on the 36 V bus — not a config one.

Two further reasons not to chase the full 5–8.8 rev/s: repeatability already
degrades 3.4× from bench to coordinated moves (§3.1), and 7920 RPM on the rotor
side of a printed herringbone planetary is the one irreversible risk in this plan.

### 16.4 Fix 3 — torque is the axis genuinely worth opening, but the limit is mechanical

Unlike speed, torque has real unused headroom and no regen implication
(acceleration consumes energy; only deceleration returns it):

- the session ran at `max_torque` 1.0 N·m of **4.34 N·m available — 23%**
- measured breakaway is 0.53 N·m, so a 1.0 N·m ceiling is only **1.9×
  breakaway** — a thin margin, and plausibly why small steps settle poorly
- torque never saturated in any run (peak 0.80 N·m against the 1.0 ceiling)

**To be clear: `servo.max_current_A = 10` is not causing a problem today.**
Unlike `servo.max_velocity` (§15.11), which actively corrupted data, the current
limit has never been reached in any run. The issue is latent, and it is about
which limit can be bypassed. There are three layers:

| Layer | Where it lives | Value | Survives a host failure? |
|---|---|---|---|
| 1. `max_torque` | **host RAM** — `state.max_torque` (`host/joint_console_v2.py:78`), sent as `maximum_torque=` with every command at ~64 Hz | 1.0 N·m | **No.** Dies with the process; resets to 1.0 on restart |
| 2. `servo.max_current_A` | **board flash** | 10 A → **4.34 N·m** at the output | **Yes** — always enforced |
| 3. mechanical rating | nowhere | **unknown** | — |

A config dump finds no board-side operational torque limit at all, so layer 2 is
the only ceiling the host cannot move. Layer 1 is safe-by-default (it resets to
1.0 every launch) but `limit torque 4` changes it instantly, and `arm_server.py`
and the GUI carry their own defaults.

It is a fuse sized by what the wire can carry rather than by what the appliance
can take — harmless until something upstream asks for more. **This session asked
for more:** §15.11 set `limit torque 3.0` to get acceleration headroom, with no
mechanical number to check it against. The same thing happens the moment §7.4's
torque axis is opened.

The fix is therefore to **derive `servo.max_current_A` from the gearbox's
allowable output torque**, so the firmware physically cannot damage the gears
regardless of what the host asks for:

```
I = tau_out / (N * Kt) = tau_out / 0.4341

allow 1.0 N.m  ->  2.3 A
allow 2.0 N.m  ->  4.6 A
allow 3.0 N.m  ->  6.9 A
allow 4.34 N.m -> 10.0 A    <- today's value, set by nothing in particular
```

**Action: ask the ME for the printed planetary's allowable continuous and peak
output torque, then set `servo.max_current_A` from it.** That converts an
accidental electrical limit into an engineered mechanical one, and it protects
the gearbox far better than any host-side ceiling — the host can be bypassed,
the current limit cannot.

Until that number exists, raise `max_torque` to 2.0 N·m (46% of available) for
testing, which restores a healthy ~3.8× margin over breakaway.

### 16.5 Priority

1. **Fix 1** — config under version control. `--sync` **before** any `--apply`
   (see the warning in §16.2); fixes the actual defect,
   and prevents the next silent data corruption.
2. **Fix 3's question to the ME** — the gearbox torque spec gates the only
   limit worth raising, and it is a dependency on someone else, so ask early.
3. **Fix 2** — raise `max_velocity` to 1.5 and `accel` to 8, non-persisted
   first, then re-run §15.11's ladder with correct dwells.

---

## 17. Stress-to-failure: finding the gearbox limit empirically

Decided 2026-10-18: with no vendor rating for a printed part, the limit will be
measured by loading it until it fails. That is the right call — but the sequencing
and the method both matter more than the ramp itself.

### 17.1 This must be the LAST test on a given unit, not the next one

Nothing in §5 or §6 has been run. Every one of those needs an **intact** gearbox:

| Blocked test | Why a yielded gearbox invalidates it |
|---|---|
| §5.1 torque constant | calibration shifts if tooth geometry changes |
| §5.2 drag vs speed | damaged teeth change `tau_C` and `b` permanently |
| §5.3 efficiency | the headline `eta` number becomes unmeasurable |
| §6.1 backlash + stiffness | the cold, undamaged baseline exists exactly once |
| §6.3 transmission error | order spectrum is meaningless after tooth damage |
| §9.2 burn-in | wear-in from a fresh state cannot be re-run |

Run stress-to-failure next session and the result is the worst of both worlds:
**characterization data for a gearbox you can no longer measure, and a failure
number for a gearbox you never characterized.** The two datasets would not
describe the same object.

**Order: §5 → §6 → §9.2 burn-in → §17 failure.** Failure last, always.

### 17.2 Test a sacrificial print, keep the characterized unit

It is a printed part — reprint it. Destroy the copy, keep the unit all existing
J1 data describes.

Caveat to state in the report: print-to-print variation in a printed planetary is
real (layer adhesion, spool batch, dimensional drift), so the sacrificial unit's
failure torque is not exactly the keeper's. That is acceptable because the result
gets derated by 40–50% anyway (§17.5) — but it means the failure number is a
**population estimate from n=1**, which should be said plainly. Two sacrificial
units would be far better than one if print time allows.

### 17.3 You cannot stress the gearbox by moving it fast

This is the practical trap. Free acceleration produces only `tau = J * alpha`,
and the reflected inertia is tiny:

```
J_eff ~ 5.6e-3 kg.m^2 at the output

accel  1 rev/s^2  ->  0.035 N.m
accel 15 rev/s^2  ->  0.528 N.m
accel 70 rev/s^2  ->  2.463 N.m     (and 70 rev/s^2 is the full-speed figure)
```

Today's ladder peaked at **0.80 N·m — 18% of the 4.34 N·m available** — because
nothing was resisting it. **Torque requires reacting the output against ground.**

So §17 is a **stall test**, and it needs the fixture from §4 Tier 1 that does not
exist yet. Build the clamp first; "next time" is gated on it.

Best form: the **reaction-torque mount** of §5.0.2 option 2 — output clamped to
ground through a load cell at known radius. That measures *true* output torque
including `eta`, rather than the lossless-referred estimate, so it calibrates
§5.0.1 at the same time.

### 17.4 Without an output encoder you learn almost nothing

The rotor encoder reports the commanded position happily while teeth strip past
each other. At Tier 0 the outcome of a failure test is "it broke somewhere
between 4 and 6 N·m" with no insight into how.

**And the number you actually want is not where it shatters — it is where it
permanently deforms.** A printed gear that survives 6 N·m once but gains 2 deg of
backlash doing so has already failed for this application. Detecting that
requires measuring backlash *between* load steps, which makes this a **stepped
test with a measurement at every step**, not a ramp to destruction.

That makes §4 Tier 2 (AS5048A on the output) effectively a prerequisite: it is
what detects first tooth skip, and what makes the backlash-growth measurement
possible at all.

### 17.5 Protocol

Preconditions: §5 and §6 complete on the keeper; sacrificial unit fitted;
reaction mount with load cell; AS5048A on the output; high-rate logging with
`Q_CURRENT` and `VOLTAGE`; video and audio running.

1. Baseline backlash and stiffness (§6.1) on the sacrificial unit, so its
   starting condition is known rather than assumed.
2. **Use `torque` mode, not position mode.** `kp_scale = kd_scale = 0` commands
   torque directly. In position mode against a stall the integrator winds up and
   dumps torque the instant the gears slip — violent and uncontrolled.
3. Ramp in steps of ~0.5 N·m output. At each step: hold 5 s, release, re-measure
   backlash, cool down, record.
4. Failure criteria, **defined in advance**:
   - **(a) backlash grows >10% from baseline → onset of permanent set. This is
     the number the project needs. Stop here on the keeper.**
   - (b) output slips while the rotor advances → tooth skip (needs Tier 2)
   - (c) audible crack or visible deformation
   - (d) catastrophic failure — sacrificial unit only
5. Thermal limit. A stall has no back-EMF, so all electrical power is `I^2*R`
   heating, concentrated in one phase pair because the rotor does not move:

   | I (A) | `tau_out` lossless | stall `P_cu` |
   |---|---|---|
   | 5 | 2.17 N·m | 1.8 W |
   | 10 | 4.34 N·m | 7.4 W |
   | 15 | 6.51 N·m | 16.6 W |
   | 20 | 8.68 N·m | 29.6 W |
   | 30 | 13.02 N·m | 66.5 W |

   Short bursts with cooldown between, watching `TEMPERATURE`. Going above
   `max_current_A = 10` requires **verifying the r4.11's own peak current
   rating** first — the console's `CONFIG_LIMITS` permits 30 A, which is a
   software bound, not a board rating.

### 17.6 Converting the result into a limit

Derate hard — it is a printed prototype, n=1, and the §15.5 data already shows
the joint is less repeatable than assumed:

| measured failure | design limit (50–60%) | resulting `servo.max_current_A` |
|---|---|---|
| 4.0 N·m | 2.0–2.4 N·m | 4.6–5.5 A |
| 6.0 N·m | 3.0–3.6 N·m | 6.9–8.3 A |
| 8.0 N·m | 4.0–4.8 N·m | 9.2–11.1 A |

Then set `servo.max_current_A` from that number and commit it to `PROFILE`
(§16.2), so the firmware physically cannot exceed the gearbox's rating
regardless of what the host asks for. **That closes the loop opened in §16.4.**

---

## 18. Audit fixes applied — 2026-10-20

A correctness audit of the host code, prompted by the 2026-10-18 session.
Verified with `host/test_joints.py` (new, no hardware), `sim_test.py`,
`test_arm_server.py` and a sim route. **Not yet exercised against a motor.**

| # | Defect | Fix | Verified by |
|---|---|---|---|
| 1 | `MoteusJoint._run()` swallows every exception and `_last` had no age, so a dead CAN link left `read()` serving a frozen position with `moving=False, fault=0` — which `Arm.move()` reads as "arrived" | `_last_t` stamp; `read()` returns `fault=-1` after `STALE_PERIODS` (3) periods, and recovers when the link returns | `test_joints.py` [1] |
| 2 | Settle tolerance was `2e-3` rev = 0.72°, **below** the joint's own measured \|μ\|+2σ of 0.685°, so ~2% of real moves never reported `moving=False` | `SETTLE_TOL_REV = 4e-3` (1.44°), 1.47× the \|μ\|+3σ bound, derived from the n=50 data | `test_joints.py` [2] |
| 3 | `Arm.move()` only `print()`ed on settle-timeout then returned as success — and `print()` is invisible under Tauri | raises `RuntimeError` naming the joints still moving | sim route |
| 4 | `Arm.stop()` documented "never raises" but `_safe_stop` catches only `Exception` | `gather(..., return_exceptions=True)` | inspection |
| 5 | `do_random`/`do_cycle` saved no per-move rows — 50 landing errors were lost | `log_run(table=...)` writes `<stamp>_rows.csv`; both now pass one | console smoke test |
| 6 | `do_cycle` warned about truncated moves then logged `backlash_deg` anyway | refuses to emit `backlash_deg`, records `invalid` + `truncated_targets` instead | console smoke test |
| 7 | `travel_time()` used the *commanded* velocity while firmware enforced a lower cap | `effective_vel()` clamps to `servo.max_velocity`; `limit vel` warns when the command exceeds it | console smoke test — the 2 rev/s dwell now predicts **3.05 s, not 1.33 s**, which is exactly the shortfall that corrupted three runs |
| 8 | `log_run` captured only `servo.pid*`/`servopos`/`motor_position*`, so the limits that actually bind were never recorded | full config minus the multi-thousand-entry cogging/compensation tables | console smoke test |
| 9 | `servo.max_velocity` was on the board and in no file | added to `PROFILE` **at the board's actual value (0.5)** and to `CONFIG_LIMITS` so `set` can write it | inspection |
| 10 | Telemetry logged only `(t, pos, vel, torque)` | appended `q_current`, `voltage`, `temperature`, `commanded_rev`; `write_csv` handles narrow and wide rows | console smoke test |

**Deliberately not changed:**

- **`servo.max_velocity` was recorded, not raised.** Making the limit visible
  was the defect; changing it is a hardware decision (§16.3 derives 1.5 rev/s
  from the regen cap). `PROFILE` now carries 0.5 with that reasoning in a
  comment, so `--check` reports drift instead of silence.
- **The `servopos` ±0.25 vs ±0.55 drift is flagged, not reconciled.** Widening
  or narrowing soft travel stops is a safety decision. The comment in `PROFILE`
  says so; `--check` will keep flagging it until someone decides.
- **`profile_1.json` still does not exist** — `--sync` needs the board, so it
  must be run at the bench.

**One correction the test forced on me:** the comment justifying
`SETTLE_TOL_REV` originally claimed "~1.5× the 3-sigma bound". It is 1.47×.
The assertion failed, and the right fix was to make the comment precise rather
than inflate the constant to fit a round number.
