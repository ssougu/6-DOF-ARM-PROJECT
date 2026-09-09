# Power distribution network

Design basis for the arm's power system. Started 2026-09-08.

**Every number is tagged with where it came from.** ✔ = read off a datasheet or
spec sheet we hold. ⚠ = must be verified before it is designed against. The
distinction matters more than the values: a PDN built on unverified numbers is
a guess with a table around it.

Loads are sized from **bounded worst case**, not from measurement, because the
arm does not exist yet. Measurements fill the right-hand column as each joint
comes online. See "Verification" at the end.

---

## 1. Rail decision — 36 V

| Device | V min | V max | Source |
|---|---|---|---|
| moteus r4.11 | 10 V | **44 V** (≤10S) | ✔ mjbots spec sheet |
| CL57T (V4.1) | 24 V | ~50 V | ⚠ **verify in your CL57T manual** — variants differ |
| FEETECH STS3215 | 6 V | 12.6 V | ⚠ verify; runs on its own 12 V rail |

**36 V single rail**, derived as follows:

- 48 V is **ruled out** — exceeds the moteus 44 V ceiling. Not marginal, out.
- 24 V works but sits at the bottom of the CL57T's range. Stepper torque falls
  off with speed because current rise is `di/dt = V/L`; at 2.6 mH, 24 V gives
  half the current slew of 48 V.
- 36 V is inside both ranges with ~8 V of headroom to the moteus ceiling
  (mjbots design for a 10S pack, ~42 V charged, so 36 V is squarely in band).
- 12 V for the servos is **derived from 36 V by a buck downstream of the
  e-stop contactor**, not from a separate mains brick. A separate brick is a
  second power path the e-stop cannot cut — press the button and the wrist
  stays live.

⚠ **Cost of this decision:** J1's gains were tuned at 24 V. Raising the bus
changes its velocity ceiling and effective response. Re-characterise with
`joint_console_v2.py` and `--sync` the profile *before* J3 exists, so the
tuning is done once and copied.

---

## 2. What the spec sheets say

### moteus r4.11 — J1, J3

| Parameter | Value | Source |
|---|---|---|
| Input voltage | 10–44 V | ✔ |
| Peak phase current | 100 A | ✔ |
| Continuous phase current | 12 A / 32 A (w/o, w/ thermal mgmt) | ✔ |
| Peak **electrical power** | 900 W @ 30 V | ✔ |
| Operating temperature | −40 … 85 °C | ✔ |
| Max electrical frequency | 2 kHz | ✔ |
| Power connector | 2 × XT30PW-M | ✔ |
| Data connector | 2 × JST PH-3 | ✔ |
| CAN termination | **not fitted** — sold as an accessory | ✔ |

⚠ **Do not size the supply from 900 W.** That is what the controller can pass,
not what the joint will draw. The limit is the motor, below.

### mj5208 motor — J1, J3

| Parameter | Value | Source |
|---|---|---|
| Continuous power | ⚠ **LOOK UP** | mjbots motor page |
| Continuous current | ⚠ **LOOK UP** | |
| Kv | ⚠ **LOOK UP** | |
| Phase resistance | ⚠ **LOOK UP** | |
| Pole pairs | ⚠ **LOOK UP** | |

**This is the most important gap in the document.** Whether a 600 W supply is
adequate hinges on the mj5208's continuous rating, and nothing else in the
table can substitute for it.

### 24HS40-5004D-E1000 stepper — J2 (J4 TBD)

| Parameter | Value | Source |
|---|---|---|
| Frame | NEMA 24 | ✔ |
| Rated phase current | 5.0 A | ✔ box spec |
| Holding torque | 4 N·m | ✔ |
| Phase resistance | 0.60 Ω ±10% | ✔ box spec (web sheet says 0.75 Ω — trust the box) |
| Phase inductance | 2.60 mH | ✔ box (web says 2.4 mH) |
| Step angle | 1.8° | ✔ |
| Encoder | 1000 PPR | ✔ |

### CL57T (V4.1) driver — J2 (J4 TBD)

| Parameter | Value | Source |
|---|---|---|
| Current setting (S1 = A) | 7 A peak / 5 A RMS | ✔ our DIP config |
| Microstepping (SW1–4 off/on/on/off) | 2000 pulses/rev | ✔ our DIP config |
| Loop mode (SW6 off) | closed loop | ✔ our DIP config |
| Signal voltage (S3) | 5 V | ✔ our DIP config |
| ALM output | open collector, 20 mA, 5–24 V | ✔ |
| Input voltage range | ⚠ **verify in manual** | assumed 24–50 V |
| Efficiency | ⚠ assume 85–90 % | typical chopper |

⚠ **DIP switches are read only at power-up.** Change one, power cycle.

### FEETECH STS3215 — J5, J6, gripper

| Parameter | Value | Source |
|---|---|---|
| Voltage | 12 V | ✔ |
| Stall torque | 30 kg·cm (~2.9 N·m) | ✔ |
| Rated torque | 10 kg·cm | ✔ |
| Gearbox | 1:345 metal | ✔ |
| Encoder | 12-bit magnetic | ✔ |
| **Stall current** | ⚠ **LOOK UP** | needed to size the 12 V buck |
| Idle / no-load current | ⚠ **LOOK UP** | |

---

## 3. Why "sum of the maxima" is the wrong sizing basis

Adding every absolute maximum gives a number no sensible supply meets — two
moteus at 900 W each is 1800 W before anything else. Sizing that way produces
an oversized, expensive, and *still not guaranteed* system, because absolute
maxima are transient thermal ratings that were never meant to be summed.

The correct basis is the **worst credible simultaneous case**: what actually
draws power at the same instant during the demo, plus margin. Everything
beyond that is handled by fusing and by the drivers' own current limits, not
by supply capacity.

Stated assumption for this design:

> Worst credible case = all four major joints accelerating simultaneously
> during a coordinated move, with the three servos at rated (not stall) load.
> Simultaneous stall of every actuator is treated as a fault, handled by
> protection, not by supply sizing.

Write that assumption down and design to it. An assumption stated is
engineering; an assumption hidden is a guess.

---

## 4. Load table

Supply current is **not** phase current. For a chopper drive, input power ≈
output power, so a 5 A phase current at standstill draws far less than 5 A
from a 36 V rail.

Worked example, J2 at standstill:
```
copper loss  = I² × R  ≈ 5² × 0.6 × 2 phases ≈ 30 W
supply current at 36 V ≈ 30 W / 36 V / 0.9 ≈ 0.9 A
```
…against a 5 A phase current. The distinction is the single most common way
PDNs get oversized or undersized.

| Load | Rail | Idle | Worst credible | Bound used | Measured |
|---|---|---|---|---|---|
| J1 moteus + mj5208 | 36 V | ⚠ | ⚠ | ⚠ TBD from mj5208 | — |
| J3 moteus + mj5208 | 36 V | ⚠ | ⚠ | ⚠ TBD from mj5208 | — |
| J2 CL57T + 24HS40 | 36 V | ~0.9 A (calc) | ~4 A (calc) | **150 W** | — |
| J4 CL57T + stepper | 36 V | ~0.9 A | ~4 A | **150 W** | — |
| J5/J6/gripper STS3215 | 12 V | ⚠ | ⚠ | ~100 W | — |
| Logic (Teensy, CAN, encoders) | 5 V / 3.3 V | — | <0.5 A | 10 W | — |

J2 bound of 150 W = 30 W copper + ~94 W mechanical at rated torque and
225 RPM + ~20 W iron and driver losses. Conservative: it will not hit rated
torque at that speed.

**Total pending the mj5208 figure.** With the two steppers, servos and logic
at ~410 W, the moteus pair decides whether LRS-600 suffices.

---

## 5. Derating

| Item | Derate to | Why |
|---|---|---|
| PSU continuous | ≤ 80 % of rating | Meanwell LRS derates above 50 °C ambient |
| Wire, bundled/sleeved | ~70 % of free-air ampacity | bundle runs hotter |
| Connectors | ≤ 80 % of rating | contact resistance rises with cycles |
| Fuse | 125–150 % of continuous branch load, **below** wire ampacity | must protect the wire |

**Protection coordination:** each branch fuse must open before the main fuse,
so a single joint fault doesn't drop the arm. Branch 5–6 A, main 20 A gives
adequate selectivity.

| Conductor | AWG | Free-air | Bundled (×0.7) |
|---|---|---|---|
| PSU → distribution trunk | 14 | ~17 A | ~12 A |
| Branch to each driver | 18 | ~10 A | ~7 A |
| 12 V servo bus | 20 | ~7 A | ~5 A |
| Signals (step/dir, ALM, limits) | 24 | — | — |
| CAN H/L | 24 twisted pair | — | — |

Connector ratings: XT30 ~30 A ✔, JST-XH ~3 A (signal only) ⚠ verify,
JST PH-3 signal only ✔.

---

## 6. Topology

```
AC mains ──[IEC inlet + switch + fuse]──► LRS-600-36 ──► 36 V star point (PSU −)
                                                              │
        ┌─────────────────────────────────────────────────────┤
        │                                                     │
   LOGIC DOMAIN (always alive)                        [MAIN FUSE 20 A]
        │                                                     │
   36→5 V buck                                    [E-STOP CONTACTOR, NO]
        ├─► Teensy                                            │
        ├─► CAN transceiver                          MOTOR DISTRIBUTION
        ├─► logic buffers                                     │
        └─► moteus cooling fan            ┌────────┬──────────┼──────────┬─────────┐
            (must outlive an e-stop)   [F 5A]   [F 5A]     [F 6A]     [F 6A]   [F 8A]
                                          │        │          │          │        │
                                         J1       J3         J2         J4   36→12 V buck
                                       moteus   moteus     CL57T      CL57T       │
                                                                            J5  J6  grip

E-stop button (NC) ──► contactor coil (+ flyback diode), fed from LOGIC domain
Contactor aux NC ──► Teensy input (weld detection)
```

J1 and J3 may share one fused branch by daisy-chaining `XT30PW-M` — the boards
carry two connectors for exactly this. Simpler harness; one connector failure
drops both.

---

## 7. Grounding

Single **star point at the PSU negative terminal**. Every return is its own
conductor back to it.

- Each driver return runs separately to the star. Do **not** daisy-chain
  driver grounds.
- Logic ground gets its own conductor to the star.
- **Motor return current must never share copper with logic ground.** The
  CL57T chopper puts high di/dt in its return; share that with the ALM input
  or limit switches and ground bounce reads as phantom faults.
- Encoder cable shields ground at the **controller end only**. Both ends makes
  a shield current loop.

⚠ **USB ground loop:** a USB-powered Teensy bonded to the PSU star ties laptop
ground to supply ground through a cable never intended as a ground conductor.
The ESP32 already works this way, so accept it — but this is suspect #1 for
any unexplained comms noise. A USB isolator (~$25) is the fix.

---

## 8. Fault analysis

| Fault | Consequence | Detection | Mitigation |
|---|---|---|---|
| Shorted motor lead | branch fault current | branch fuse opens | per-branch fusing; other joints keep running |
| Open ground return | signal reference floats; erratic I/O | erratic behaviour, hard to spot | star topology, separate returns |
| Welded contactor | e-stop does nothing, silently | **aux NC contact read by Teensy** | verify at power-up, refuse to arm if mismatched |
| PSU brownout | drivers reset mid-move | moteus faults; CL57T ALM | size supply with margin; per-branch fuses |
| E-stop pressed mid-move | motor power cut; **arm falls under gravity** | — | ⚠ see below |
| Inrush at contactor close | contact pitting over time | — | ~2 mF total; 40 A contact tolerates it |
| USB disconnect | host stops streaming | moteus 0.25 s watchdog de-energizes | already handled |

⚠ **Cutting motor power drops a gravity-loaded shoulder.** J2 has no holding
torque unpowered. An e-stop that lets the arm fall may be worse than one that
holds. Options: keep the arm light and the fall short, counterbalance, or a
fail-safe spring-applied brake (the CL57T's configurable output can drive one
— presumably why that mode exists). **This is a mechanical decision with an
electrical dependency and belongs in the gearbox CAD conversation now.**

---

## 9. Verification

Every claim above gets a measurement. Left column is predicted; fill the right
as hardware allows.

| Test | Measurable now? | Result |
|---|---|---|
| Quiescent draw, moteus + CL57T idle | **yes** | — |
| Inrush at power-on | **yes** | — |
| Harness voltage drop per amp (dummy load) | **yes** | — |
| Stepper thermal soak, 30 min | **yes** — see note | — |
| **E-stop latency**: button → current zero | when contactor arrives | — |
| Per-joint dynamic current | when arm exists | — |

**Stepper thermal is measurable today on the detached NEMA 24.** Winding
dissipation is set by *commanded current*, not mechanical load, so the bench
motor is representative. In closed loop the CL57T reduces current when
unloaded, which reads optimistically — flip **SW6 on (open loop)** and power
cycle to force full current and bound the worst case. Thermocouple on the
motor case and the driver heatsink, 30 minutes.

**E-stop latency is the number worth chasing.** Button press → contactor open
→ motor current at zero, measured with the logic analyzer on the button and
aux contact plus a scope on a current shunt. "Our e-stop de-energizes in N ms,
measured" is a materially different claim from "we have an e-stop".

---

## Open items

1. ⚠ **mj5208 continuous rating** — decides whether LRS-600 is enough.
2. ⚠ **CL57T input voltage range** — confirm 36 V is in band.
3. ⚠ **STS3215 stall current** — sizes the 12 V buck.
4. ⚠ **J4 frame size** — blocked on the ME; changes its bound.
5. ⚠ **Gravity-drop behaviour on e-stop** — mechanical decision, needed now.
6. Buy **2 CAN-FD termination resistors** (JST PH-3) — the boards ship
   unterminated. Check whether `mjcanfd-usb-1x` terminates internally.
