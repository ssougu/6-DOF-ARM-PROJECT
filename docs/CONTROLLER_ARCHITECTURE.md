# Controller architecture

Decision record, 2026-09-01. Where control runs, why, and what to build when.

---

## Current architecture

The laptop is the motion controller. `host/arm.py` generates trajectories in
Python and streams position targets over USB — CAN-FD to J1's moteus via the
`fdcanusb`, and an ASCII line protocol to the ESP32 that pulses J2's stepper.

**This works better than it sounds, for one reason: every actuator closes its
own control loop.**

| Actuator | Onboard loop |
|---|---|
| moteus r4.11 | FOC + position PID @ 40 kHz |
| CL57T + `-E1000` motor | closed loop on the motor's 1000-line encoder |
| FEETECH STS3215 | internal position loop, 12-bit encoder |

So the host is a **trajectory sequencer, not a servo loop**. The only hard
deadlines in the entire system are two 0.25 s watchdogs. A late host command
means a joint holds its last target for a few more milliseconds — it does not
mean lost position. This is why a non-real-time Windows box is viable, and it
is the single most important property of the design.

---

## The gating constraint: CAN-FD

moteus requires **CAN-FD with bit rate switching** (5 Mbps data phase). Not
negotiable, and it decides the hardware:

| Candidate | CAN-FD | Step generation | Verdict |
|---|---|---|---|
| **Teensy 4.1** (600 MHz M7) | **CAN3 is FD-capable** | FlexPWM ×4 + QuadTimer ×4 | **chosen** |
| STM32H7 (H723/H743) | FDCAN ×2–3 | timers + DMA | better *product* part, slower to first light |
| RP2350 / Pico 2 | none — needs external MCP2518FD | PIO is best-in-class | CAN gap disqualifies |
| ESP32 / ESP32-S3 | **none** — TWAI is classic CAN 2.0 | mediocre | **cannot talk to moteus** |
| Pi + mjbots pi3hat | 5× FD, built for moteus | Linux can't pulse steppers | complement, not replacement |

Either board still needs an external **CAN-FD** transceiver — TCAN334G or
MCP2562FD. *Not* SN65HVD230 or TJA1051: classic-only parts appear to work at
low rate and then fail at 5 Mbps BRS.

---

## Decision: Teensy 4.1

**Clock speed is not the reason** — the workload (2 step generators at ~10 kHz
plus a 200 Hz CAN loop) would run on a 100 MHz M4. 600 MHz vs 550 MHz is
irrelevant. The reasons are:

1. **Deadline.** `FlexCAN_T4`'s CAN-FD support is mature and Arduino-simple.
   The STM32 Arduino core's FDCAN support is weaker, so STM32 realistically
   means CubeIDE + HAL — a real time cost for a team where one person is doing
   firmware *and* host *and* control *and* vision.
2. **It doesn't foreclose STM32.** See below.

### Why the PCB question doesn't decide it

The i.MX RT1062 is **BGA-only** (196-ball) — not hand-solderable, needs 6+
layers and multi-rail power sequencing, and you lose PJRC's bootloader chip.
So the realistic Teensy custom-PCB path is a **carrier board with the Teensy
socketed on it**.

That turns out not to matter, because **the MCU is not the expensive part of
the board.** The project-specific work is the CAN-FD transceiver and
termination, opto-isolated stepper drive, the e-stop relay chain, connectors
and power distribution — all of which is **MCU-agnostic**. Design that carrier
with a Teensy socket; if STM32 is needed later, respin the MCU section and keep
everything else.

**Switch to STM32H7 when** the fair is no longer the near-term goal or a
product is being committed to. Then LQFP packages, SWD debugging, industrial
temperature grades, 10-year availability and CubeMX pin planning all win — and
moteus itself is STM32-based (G4), so mjbots' open firmware becomes readable
reference.

---

## What the MCU should and should not do

❌ **Not PID.** Every actuator already runs one, and J1's is *tuned* (kp 225,
kd 4.5, ki 200). A Teensy PID recomputing what moteus does at 40 kHz adds
latency and fights the inner loop. Strictly worse.

✅ **An outer loop on output-side position** — cascade, not duplicate. Read an
output-shaft encoder the actuator cannot see, and command moteus's inner loop.
This is the only thing that attacks the 0.84° spread, because that error lives
downstream of the rotor encoder. **Requires the gearbox mounting provisions
(see CLAUDE.md open question #2) — that window closes when the gearboxes
print.**

✅ **Kalman filtering, but placed carefully:**
- *On the MCU* — fuse rotor-side + output-side encoders to estimate true joint
  angle and backlash state. A 6-state filter per joint at 1 kHz is microseconds
  on an M7 with a double-precision FPU.
- *On the laptop* — fuse the vision pose estimate with forward kinematics.
  Belongs where the CV model is.
- ⚠️ A filter **cannot** observe lost steps without a sensor. No filter
  recovers unobservable state.

✅ **Consolidation** — one USB cable instead of three.

✅ **A hardware safety chain** independent of Windows. Today the only interlocks
are per-driver watchdogs and the XT30.

---

## Target architecture

```
Windows + RTX 4090          Teensy 4.1 (1 kHz)              Actuators
─────────────────────       ──────────────────              ─────────
CV inference (CUDA)         outer position loop  ──CAN-FD──► moteus (inner PID @40k)
task planning, IK    ──USB──► Kalman: rotor+output ─step/dir─► CL57T steppers
pose targets @10-50Hz       servo bus, safety chain ──TTL───► STS3215
vision+FK fusion            AS5048A ×N over SPI ◄────────────  output-side encoders
```

### Peripheral budget

| Need | Peripheral | Notes |
|---|---|---|
| moteus J1 + J3 | **CAN3** (only FD-capable one) | one bus, two nodes, different ids |
| Steppers J2 + J4 | FlexPWM / QuadTimer ISR | 2 pins each; ~300 kHz available, ~10 kHz needed |
| STS3215 J5 + J6 | one UART, half-duplex @ 1 Mbaud | both servos on **one wire pair**, by id |
| Host link | native USB high-speed | same line protocol + a joint index |
| Safety | e-stop in, limits in, 1 enable out | enable gates every driver's ENA |

Two steppers and two CAN nodes fit a **Teensy 4.0** as well; 4.1 is chosen for
the extra I/O, the SD slot (onboard logging) and Ethernet headroom.

⚠️ **Teensy 4.x is 3.3 V and not 5 V tolerant.** Fine for driving the CL57T —
its inputs are optocouplers, current-driven, so the existing common-anode
pattern carries over — but any 5 V input needs a divider.

---

## Phasing

**Phase 0 — 6 DOF on the existing Python stack. No MCU at all.**
This is the fair demo, and the Teensy is *not on its critical path*.

- **0a** joint table → `host/arm_config.json` (currently hardcoded in
  `DEFAULT_AXES`, `Arm.specs_from_args` and `add_args`)
- **0b** J3 — spare moteus to CAN id 3, calibrate, add a config entry. Appears
  in the console, GUI and routes automatically
- **0c** J5/J6 — a `ServoJoint` in `host/joints.py` over a USB→TTL adapter
- **0d** J4 — second axis on the **existing ESP32**; it has spare pins

**Phase 1 — safety chain only (pre-fair, ~1 week).** Teensy does nothing but
safety: e-stop button, limit switches, one watchdog, an enable line to every
driver's ENA. Python keeps driving the arm. Worth shipping on its own merits.

**Phase 2 — steppers move to the Teensy (pre-fair if Phase 1 lands).** Port
`firmware/j2_stepper` to a 2-axis Teensy step generator, add a joint index to
the protocol, add `TeensyJoint` to `host/joints.py`.

**Phase 3 — servos + CAN-FD takeover (post-fair).** One cable to the laptop.

**Phase 4 — product hardening (post-fair).** Carrier PCB; revisit STM32H7.

---

## Why the host keeps trajectory generation

Moving it into C++ before the fair re-implements tested, working Python
(`Arm.move`'s velocity scaling, the route runner, logging) under deadline for
zero demo benefit. It also does not remove the host from the loop for a
vision-guided pick — the host still says "go to this pose" after inference, and
that path is dominated by inference time, not by who computes the trapezoid.

**Measure before designing around jitter.** Instrument the control loop, log
inter-cycle timing, run `routines/workout.txt` idle vs under a real CUDA load.
That turns CLAUDE.md open question #6 into a number.

---

## Migration is cheap because of `joints.py`

`Joint` isolates actuator type behind one interface. A `TeensyJoint` reusing
`StepperJoint`'s parsing and keepalive pattern means `arm.py`, the route files,
`sim_test.py`, `arm_server.py` and the Tauri GUI are **all untouched**. The
`A/S/Z/H/P/Q` protocol generalises to multi-axis by adding a joint index, and
`sim_test.py` / `test_arm_server.py` stay valid as regression gates.

## Parts to order

Second stepper + CL57T for J4 (they ship together) · USB→TTL bus-servo adapter
(Waveshare or FE-URT-1) · CAN-FD transceiver breakout · Teensy 4.1.

⚠️ The spare moteus gets consumed by J3 — after that there is **no spare
controller for debugging**.
