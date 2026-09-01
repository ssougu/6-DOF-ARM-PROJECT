# 6-DOF Vision-Guided Robotic Arm

A six-degree-of-freedom robotic arm built for the CSUF ECE fair. Two-person
team: one ME on gearboxes and mechanical design, one EE/software lead on
firmware, host software, control and vision.

**Target demo:** detect an object on a flat surface, select it from a terminal,
and pick it up — reliably, repeatedly, on request.

```
python host/sim_test.py          # try the motion stack right now, no hardware
```

---

## Status

| Joint | Actuator | Driver | Link | State |
|---|---|---|---|---|
| **J1** base yaw | mj5208 BLDC | moteus r4.11 | CAN-FD | ✅ built, tuned, characterised |
| **J2** shoulder pitch | 24HS40 NEMA 24 | CL57T (closed loop) | step/dir | ⚙ motor + firmware working, gearbox in design |
| **J3** | moteus + mj5208 | moteus r4.11 | CAN-FD | 📋 decided, not built |
| **J4** | stepper | CL57T | step/dir | 📋 decided, not ordered |
| **J5 / J6** | FEETECH STS3215 | — | half-duplex TTL | 📋 on hand, unwired |

J1 and J2 run coordinated moves together today. Perception, gripper and IK are
not built yet.

**Every joint has feedback at the actuator level** — moteus closes a 40 kHz FOC
loop on its rotor encoder, the CL57T closes on the motor's 1000-line encoder,
and the STS3215 has a 12-bit encoder on its output shaft. Nothing here is truly
open-loop, which is why a non-real-time Windows host is viable: the PC is a
*trajectory sequencer*, not a servo loop.

---

## Measured performance

J1 base yaw, 2026-08-26 characterisation (`host/logs/`):

| Metric | Value |
|---|---|
| Repeatability, fixed two-point | 0.02–0.04° |
| **Repeatability, random approach** | **0.36°** ← the honest number |
| Backlash (direction split) | 0.23° |
| Step response | 1.6% overshoot, 0.17 s settle |

The two-point figure flatters the joint by 12×. **We quote 0.36°.** At 400 mm
reach that's ±2.5 mm from J1 alone.

Under larger, faster coordinated moves (±75°, `routines/workout.txt`) J1 shows
mean |error| 0.14°, worst 0.48°, and a 6-point return-to-pose spread of 0.84° —
roughly 2× the cold bench number. That degradation is expected and logged
rather than hidden.

---

## Quick start

Everything runs in simulation with no hardware attached.

```bash
cd host
python sim_test.py                            # self-checking smoke test, PASS/FAIL
python arm.py --sim --route routines/warmup.txt   # play a motion routine
python arm_console.py --sim                   # interactive console
```

Desktop control panel (Tauri + Svelte):

```bash
cd ui
npm install
npm run tauri dev                             # SIM by default
```

On hardware — J1 on the moteus link, J2 on the ESP32:

```bash
python arm_console.py --j2-port COM3
$env:ARM_UI_SIM=0; npm run tauri dev          # GUI against real hardware
```

> The GUI **defaults to simulation** so a stray launch can't energise a motor.
> Blank line at any console prompt is the panic key; **Esc** is E-STOP in the GUI.

**Requirements:** Python 3.12 (`pip install moteus pyserial websockets`),
Node 20+ and Rust (GUI only), PlatformIO (firmware only).

---

## Architecture

```
┌──────────── Tauri desktop app (ui/) ─────────────┐
│  Svelte frontend ──ws://127.0.0.1:8787──┐        │
│  joint cards, jog, routines, E-STOP     │        │
│  Rust shell: spawns + supervises ───────┼──► arm_server.py
└─────────────────────────────────────────┘        │
                                                   ▼
   arm_console.py ─────────────────────────►  arm.py  ·  Arm
   (interactive / scriptable)                      │
                                                   ▼
                                    joints.py  ·  Joint abstraction
                                    ┌──────────────┼──────────────┐
                              MoteusJoint    StepperJoint     SimJoint
                                (CAN-FD)      (serial)      (no hardware)
```

Three ideas hold this together:

**One interface over three protocols.** `Joint` hides whether a joint is a
moteus over CAN-FD, a stepper behind an ESP32, or pure simulation. Motion code
never knows the difference — which is why the GUI, route files and test suites
all work unchanged across actuator types.

**Moves are time-synchronised.** `Arm.move()` scales every joint's cruise
velocity to the joint with the longest move, so they start *and finish*
together. A joint-by-joint sequence looks like twitching; this looks like arm
motion.

**Joints switch on and off at runtime.** A `Joint` is only constructed when
enabled, so a joint that's off — or whose hardware is unplugged — never opens
its port. Disabling de-energises it and drops it from every move; a target for
a disabled joint is skipped, not an error.

---

## Safety

Layered, because a printed arm with a 4 N·m motor deserves it:

- **Hardware watchdogs, 0.25 s** on both the moteus and the ESP32 firmware — if
  the host goes quiet, the joints de-energise on their own.
- **E-STOP everywhere** — blank line at a console prompt, **Esc** in the GUI,
  latching until explicitly re-armed.
- **Soft limits** enforced host-side before any command is sent.
- **The GUI defaults to simulation**; hardware is opt-in via `ARM_UI_SIM=0`.
- **The control server dies with its UI** — it polls its parent process and
  shuts down (de-energising) if the app crashes, so a dead GUI can never leave
  motors live.
- **Pasted command blocks are refused** — only the first line runs, so a pasted
  script can't chain unattended motion.

---

## Repository layout

```
host/                    Python control stack (runs on the laptop)
  joints.py              Joint abstraction: moteus / stepper / sim
  arm.py                 Arm: synchronised motion, routes, logging
  arm_console.py         interactive + scriptable console
  arm_server.py          WebSocket control server (GUI backend)
  sim_test.py            no-hardware smoke test
  test_arm_server.py     server protocol test suite
  joint_setup_v2.py      moteus calibration + config
  joint_console_v2.py    single-joint tuning & characterisation
  routines/              motion files: warmup, demo, pick_place, workout
  logs/                  every test writes itself here

firmware/j2_stepper/     ESP32 — moteus-like serial protocol, trapezoidal motion
ui/                      Tauri v2 + SvelteKit desktop control panel
docs/                    design decisions and hand-off briefs
```

## Documentation

| Document | What's in it |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Project context, conventions, and the gotchas that already cost us time |
| [PROGRESS.md](PROGRESS.md) | Daily log — what was done, what came out of it, what's next |
| [docs/TOOLS_USER_GUIDE.md](docs/TOOLS_USER_GUIDE.md) | Every script, every command, common workflows |
| [docs/CONTROLLER_ARCHITECTURE.md](docs/CONTROLLER_ARCHITECTURE.md) | Where control runs, the Teensy 4.1 decision, migration phases |
| [docs/VISION_APPROACH.md](docs/VISION_APPROACH.md) | Camera mount, calibration, and the error budget |
| [docs/J2_DESIGN_BRIEF.md](docs/J2_DESIGN_BRIEF.md) | Hand-off to mechanical: encoder provision, stiffness targets |
| [docs/PARTS_LIST.md](docs/PARTS_LIST.md) | What to buy, what's already owned, what's still undecided |

---

## Route files

Motion sequences are plain text, in `host/routines/`:

```
speed 0.4
move  25 -12        ; J1 -> 25°, J2 -> -12°, synchronised
movej 2 -20         ; just J2
wait 0.5            ; dwell
home
```

Every run logs per-move landing error to `logs/arm_history.csv`.

| File | |
|---|---|
| `warmup.txt` | ~20 s, gentle — run first each session |
| `pick_place.txt` | ~60 s, 3× simulated pick-and-place with grab/release dwells |
| `workout.txt` | ~76 s — big sweeps, hard reversals, speed ramp, repeatability block |

---

## Scope

~9 weeks to the fair as of 2026-09-01. Already cut: LiDAR, moving-object
tracking, visual servoing.

> A scoped-down demo that works beats an ambitious one that half-works.
