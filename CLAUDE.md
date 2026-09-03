# CLAUDE.md

Context for AI assistants working in this repo. Keep this file current — it is
the fastest way to avoid repeating mistakes that already cost us time.

Session-by-session progress and outcomes go in `PROGRESS.md` (newest on top).
Add an entry there at the end of each working session.

Design decisions live in `docs/`: **`CONTROLLER_ARCHITECTURE.md`** (where
control runs, the Teensy 4.1 decision, phasing) and **`VISION_APPROACH.md`**
(camera mount, calibration, error budget). Read those before proposing changes
to the control or perception layers.

## What this is

A 6-DOF vision-guided robotic arm for the CSUF ECE fair. Two-person team: one
ME doing gearboxes and mechanical design, one EE/software lead doing firmware,
host software, control and vision.

Target demo: detect an object on a flat surface, select it from a terminal, and
pick it up. Reliably, repeatedly, on request.

## Repo layout

```
6-DOF-ARM-PROJECT/
├── PROGRESS.md                 daily progress + outcomes log (newest on top)
├── docs/
│   ├── TOOLS_USER_GUIDE.md     every host script, commands, workflows
│   ├── CONTROLLER_ARCHITECTURE.md  where control runs; the Teensy 4.1 decision
│   ├── VISION_APPROACH.md      camera mount, calibration, error budget
│   ├── J2_DESIGN_BRIEF.md      hand-off to the ME: encoder provision, stiffness
│   └── J1_BRINGUP_REPORT.md    (to be written — J1 method + raw data, 2026-08-26)
├── firmware/
│   ├── j2_stepper/             PlatformIO, ESP32, Arduino framework C++
│   │   ├── platformio.ini      upload_port/monitor_port pinned to COM3
│   │   └── src/main.cpp        moteus-like serial protocol, trapezoidal motion
│   └── j2_bench/               scratch sketch for bench-testing the CL57T
└── host/                       Python, runs on the laptop
    ├── joint_console_v2.py     one moteus joint: live control, tuning, tests
    ├── joint_setup_v2.py       calibration and config via moteus_tool
    ├── joints.py               Joint abstraction over moteus + stepper + sim
    ├── arm.py                  Arm: J1+J2 as one mechanism, synchronised moves
    ├── arm_console.py          interactive console for the whole arm
    ├── arm_server.py           WebSocket control server — backend for the GUI
    ├── test_arm_server.py      exercises every server command against --sim
    ├── sim_test.py             no-hardware smoke test: both joints, PASS/FAIL
    ├── routines/               route files: warmup, demo, pick_place, workout
    ├── profile_1.json          tuned J1 config — COMMIT THIS
    └── logs/                   every test writes itself here
├── vision/                     perception — runs without the arm
│   ├── check_vision.py         self-check, no camera needed: CUDA, weights,
│   │                           and ray-plane recovering known mm
│   ├── board.py                the ChArUco board, defined once + printable
│   ├── camera.py               capture; pins focus/exposure and verifies it
│   ├── calibrate.py            intrinsics + coverage score → intrinsics_*.json
│   ├── detect.py               YOLO11m on CUDA → boxes + ground point
│   ├── locate.py               pixel → table mm by ray-plane; --ruler tests it
│   └── models/                 yolo11m.pt (GITIGNORED, re-downloadable)
ui/                             Tauri v2 + SvelteKit desktop control panel
├── src/                        Svelte 5 frontend (joint cards, jog, routines)
│   ├── lib/arm.svelte.ts       WebSocket link + command helpers
│   └── lib/components/         EStop, JointCard, Dial, ArmBar, RoutinePanel
└── src-tauri/                  thin Rust shell: spawns/kills arm_server.py
```

## Hardware

| Joint | Actuator | Driver | Link | Status |
|---|---|---|---|---|
| J1 base yaw | mj5208 BLDC | moteus r4.11 | CAN-FD | characterised; runs coordinated with J2 |
| J2 shoulder pitch | 24HS40-5004D-E1000 NEMA 24 | CL57T(V4.1) | step/dir | firmware flashed; gearbox in progress |
| J3 | **moteus + mj5208** (the spare) | moteus r4.11 | CAN-FD | decided 2026-09-01, not built |
| J4 | **stepper** (ships with its CL57T) | CL57T | step/dir | decided 2026-09-01, not ordered |
| J5, J6 | **FEETECH STS3215** bus servos | — | half-duplex TTL | decided 2026-09-01, unwired |

Also on hand: RealSense (eye-in-hand planned) and the **RTX 4060 Laptop (8 GB)
Windows** laptop for vision — measured 2026-09-02; earlier notes here said
4090, which was wrong. **Every joint has feedback at the actuator level** — moteus (rotor
encoder), CL57T (motor's 1000-line encoder, closed loop), STS3215 (12-bit
output encoder). Nothing in this arm is truly open-loop, which is why a
non-real-time host is survivable.

**Reductions:** J1 is 15:1 printed herringbone planetary. J2's is in progress
(firmware `GEAR_RATIO` is **1.0** — bare motor, matching what is actually
bolted on; set it to the real ratio when the gearbox goes on). J3–J6 not
designed.

### J1 — moteus r4.11 + mj5208
- 24V 5A dev-kit brick on XT30. Host link is mjcanfd-usb-1x, **COM7**.
- Rotor-side encoder only. Output-side position is NOT measured.
- Gains: kp 225, kd 4.5, ki 200, ilimit 0.5.

### J2 — CL57T(V4.1) + 24HS40
- Motor: 5.0A, 4 N·m holding, 0.60 Ω ±10%, 2.60 mH, 1.8°, 1000PPR encoder.
  (The box spec sheet says 0.60 Ω / 2.60 mH; the web datasheet says 0.75 Ω /
  2.4 mH. Trust the box.)
- Driver switches: **S3 → 5V**, S1 → **A** (7A peak / 5A RMS), SW1–4 →
  off/on/on/off (2000 pulses/rev), SW5 off, SW6 **off** (closed loop),
  SW7 off, SW8 off.
- **DIP switches are only read at power-up.** Change one, power cycle.
- ESP32 common-anode wiring, inverted logic: VIN → PUL+, bridge PUL+ → DIR+,
  GPIO32 → PUL−, GPIO33 → DIR−. Driving a pin LOW is an active pulse.
- Cable colours (documented, verified): motor GX16 black/green/red/blue =
  A+/A−/B+/B−. Encoder DB15 red=VCC(2), white=EGND(3), thin black=EA+(1),
  blue=EA−(13), yellow=EB+(11), green=EB−(12). Thick black = shield, optional.
- **The CL57T is genuinely closed-loop** (SW6 off + the motor's `-E1000` 1000-line
  encoder). It reads that encoder and corrects missed steps *internally*. It
  does **not** silently drift — if following error exceeds its threshold it
  faults. What it never does is report position back to the host.
- **The ALM output is currently unwired — fix this.** P1 carries ALM+/ALM−, an
  open-collector output (20 mA, 5–24 V, sinking or sourcing) that asserts on
  over-voltage, over-current, or **position following error**. Configurable as
  ALARM (default), IN POSITION, or BRAKE via their PC tool.
  Wiring: ALM− → ESP32 GND, ALM+ → GPIO with a 3.3 V pull-up, ALM set to
  sinking (ESP32 GPIOs are **not** 5 V tolerant). Then a `digitalRead` sets the
  firmware's existing `faulted` flag, `Q` telemetry already emits `fault=`,
  `Arm.move()` already aborts on `fault > 0`, and the GUI already renders it.
  **One wire, ~3 lines of firmware, zero host changes.**
- **ESP32 firmware flashed 2026-08-31, on COM3.** The firmware reports its
  *commanded* position, so host-side J2 tracking error always reads 0.00. That
  number is fabricated — see the honesty gotcha below.

### J5 / J6 — FEETECH STS3215 bus servos
- 12 V, 30 kg·cm stall (~2.9 N·m), 10 kg·cm rated, metal 1:345 gearbox.
- **12-bit magnetic encoder** — real position/load/voltage/temperature readback,
  so `JointState` populates properly. ~0.088°/count, well below J1's
  repeatability, so the wrist is not the limiting error source.
- **Half-duplex TTL, 1 Mbaud, daisy-chained on one wire pair**, addressed by id
  (id lives in register 5). Dynamixel-style binary packets with checksum.
- ⚠️ **Both ship as id 1.** Set ids individually *before* chaining them, or two
  servos answer the same address and it is baffling to debug.
- These are **serial bus servos, not "digital servos"** in the RC sense — an RC
  "digital servo" still takes a PWM pulse. Wiring is completely different.
- Drivable from the laptop today via a USB→TTL adapter (Waveshare bus-servo
  board or FEETECH FE-URT-1). **No microcontroller needed.**

## Conventions — do not violate these

- **Positions are OUTPUT REVOLUTIONS.** 1.0 = one full joint turn. This matches
  moteus once `rotor_to_output_ratio` is set. The stepper firmware applies its
  own `GEAR_RATIO` so both actuator types speak the same units. Never mix in
  motor revolutions or steps above the driver layer.
- Angles in reports and user-facing output are degrees; internal is revolutions.
- Mixed actuators are hidden behind `Joint` in `host/joints.py`. Motion and IK
  code must never know whether a joint is a moteus or a stepper.
- **Multi-joint moves are time-synchronised.** `Arm.move()` in `host/arm.py`
  scales every joint's cruise velocity so they all start and finish together.
  A joint-by-joint sequence looks like twitching; drive the arm through `Arm`.
- **Joints switch on and off at runtime.** `Arm` holds a `JointSpec` per joint
  and builds the `Joint` only when it is enabled, so a disabled or unplugged
  joint never opens its port. `enable(id)` / `disable(id)` — disable
  de-energizes and drops that joint from every move (a target for it is
  skipped, not an error). Everything iterates `arm.active_ids`.
- **`MoteusJoint` streams its target.** Once armed it re-sends the position
  command at 50 Hz from a background task, because the 0.25 s watchdog
  de-energizes the motor the moment the host goes quiet. `read()` returns the
  last telemetry that task saw — do not issue your own `controller.query()`
  alongside it. `arm()` starts the task, `stop()` cancels it.

## Numbers that matter

From the 2026-08-26 J1 session (see the report for method):

| Metric | Value |
|---|---|
| Repeatability, fixed two-point | 0.02–0.04° |
| **Repeatability, random approach** | **0.36°** ← design around this one |
| Worst single move | 0.42° |
| Backlash (direction split, with integrator) | 0.23° |
| Step response | 1.6% overshoot, 0.17 s settle |

The two-point number flatters the joint by 12×. Quote 0.36°. At 400 mm reach
that is ±2.5 mm from J1 alone, before the other five joints contribute — open-
loop forward kinematics will not be enough for a grasp.

2026-08-31, J1 in the `workout` routine (±75° moves, speed 0.3–1.0, J2 now
hanging off it): mean |error| 0.14°, worst 0.48°, and a 6-point
return-to-pose spread of **0.84°** — roughly 2× the cold bench number under
bigger/faster moves. Not yet characterised properly; see PROGRESS.md.

## Gotchas that already cost us time

- **Gains scale with ratio².** A 15:1 reducer divides effective stiffness by
  225. Configuring the ratio without rescaling gains produced *no motion* and
  looked like a mechanical fault. It was arithmetic.
- **`moteus.Stream` does not work on this setup.** Register commands are fine;
  the in-process diagnostic text channel times out. All config goes through
  `moteus_tool` as a subprocess. Root cause unknown.
- **Build the moteus transport inside the event loop.** `get_singleton_transport`
  / `Controller` spawn an fdcanusb reader task on construction; if no loop is
  running yet it is dead on arrival and every query hangs. `Arm.from_args`
  must be called from inside `asyncio.run`, not before it.
- **Windows serial ports are exclusive.** `console.py` and `moteus_tool` cannot
  both hold COM7. Config writes are queued and applied on exit. The ESP32 is a
  different port, so it can run concurrently.
- **The watchdog ships disabled** (`servo.default_timeout_s` = 100 s). It is now
  0.25 s. Verify safety interlocks empirically; do not assume.
- **Trust tooth counts over hand rotation** for gear ratio. A 0.74-turn hand
  rotation produced a false 11.14:1 reading against the true 15:1.
- **`enabled` is not `connected`.** Joints are built lazily: a spec can be
  enabled from startup while nothing is open on its port. `active_ids` needs
  both, so an enabled-but-unbuilt joint silently drops out of every move,
  `zero`, and `read`. **`arm()` is what connects them** (`_ensure_built`), or
  `enable(id)` explicitly. Cost a bench session in 2026-09-02: J2 showed a
  green ON toggle, dead controls, and "no enabled joints to zero" about a
  joint that was enabled. The UI now distinguishes the two states.
- **A firmware constant describing planned hardware will read as a broken
  sensor.** `GEAR_RATIO` sat at the intended 15 while a bare motor was on the
  bench, so every commanded angle came out 15× too big. Constants must track
  what is *bolted on right now*. See open question 5.
- **Silent partial success is the dominant failure mode.** Half-saved tunes,
  config writes that report success and revert, tests that cannot fail. Add a
  verification step to anything automated.
- **We are currently guilty of exactly that in our own telemetry.**
  `StepperJoint._to_state` returns the *commanded* position as if measured, so
  J2's `err` is 0.00 by construction — and it flows into `worst_err_deg` in
  `arm_history.csv` next to J1's real numbers. It should report `null` /
  "unmeasured", and the metric should name which joints it actually covers.
- **CAN-FD is a hard architectural constraint.** moteus needs CAN-FD with bit
  rate switching (5 Mbps data phase). This rules out the ESP32 entirely (TWAI
  is classic CAN 2.0 only) and means any future controller must have a real
  FD peripheral plus a **CAN-FD** transceiver — TCAN334G or MCP2562FD, *not*
  SN65HVD230/TJA1051, which are classic-only and will appear to work at low
  rate then fail at 5 Mbps.
- Settling is measured in a 2% band *of the commanded step*. On steps below
  ~0.05 rev that band is finer than the backlash and "did not settle" is an
  artifact.

## Commands

```bash
# host — one joint
cd host
python joint_setup_v2.py --id 1 --probe          # liveness + calibration
python joint_console_v2.py --id 1                 # single-joint console
python joints.py                                  # SimJoint demo, no hardware

# host — the arm (J1 + J2 together)
python sim_test.py                                # self-checking sim smoke test
python arm.py --sim --route routines/warmup.txt   # play a route, no hardware
python arm.py --j2-port COM3 --route routines/warmup.txt
python arm_console.py --sim                       # interactive, no hardware
python arm_console.py --j2-port COM3              # real J1 (moteus) + J2 (ESP32)

# GUI (Tauri desktop app)
cd ui
npm run tauri dev                                 # starts arm_server.py itself, SIM by default
$env:ARM_UI_SIM=0; npm run tauri dev              # LIVE hardware
# or backend alone + browser at localhost:1420:
python host/arm_server.py --sim                   # ws://127.0.0.1:8787
python host/test_arm_server.py                    # protocol test suite

# vision (needs no arm, no camera for the self-check)
cd vision
python check_vision.py                            # 8 checks, PASS/FAIL
python board.py                                   # printable ChArUco board
python camera.py --list                           # what cameras exist
python camera.py --index 0 --lock                 # can this camera hold still?
python calibrate.py --index 0 --lock --tag webcam # intrinsics
python locate.py --ruler                          # pixel -> mm, vs a real ruler
python locate.py --detect                         # YOLO objects located in mm
python detect.py --bench                          # inference latency

# firmware  (pio is not on PATH; it's at ~/.platformio/penv/Scripts/pio.exe)
cd firmware/j2_stepper
pio run -t upload                                 # port pinned to COM3 in platformio.ini
pio device monitor
```

The GUI defaults to **SIM** so a stray launch cannot energize a motor; set
`ARM_UI_SIM=0` for hardware. Joints can be switched on/off from the UI or with
`enable`/`disable` in `arm_console.py`.

Empty line at either console prompt is the panic key. E-stop latches; type
`arm` to clear. In `arm_console.py` a blank line typed *during* a move or
route cancels it and e-stops.

J2 has no absolute reference: `arm_console.py` → place the arm at home by
hand → `zero all yes` before running routes. J2 is on **COM3**, J1 is the
moteus link on COM7 (autodetected). They are separate ports and run
concurrently. Pasting a block of commands into `arm_console.py` runs only the
first line — type motion commands one at a time.

## Open questions

1. **Gearbox wear is unmeasured.** All J1 data is from a cold, fresh, unloaded
   gearbox. The burn-in (`backlash` → `cycle -0.5 0.5 100` → `backlash`) has not
   been run, and five more gearboxes are being designed on the strength of a
   cold-start number. Highest-value outstanding measurement.
2. ⚠️ **Output-side encoder mounting provisions — DEADLINE IS THE GEARBOX CAD.**
   The rotor-side encoder cannot see backlash, windup or compliance; the 0.84°
   spread lives entirely downstream of it. A magnet pocket on the output shaft
   and a sensor boss must go into **every** gearbox before it prints —
   retrofitting means reprinting. Cheap now, expensive later. Do it even if the
   encoders are never wired.
   Topology note: if the goal is an *outer control loop* (not just power-on
   disambiguation), prefer **AS5048A over SPI to a central MCU** rather than
   AS5048B on moteus's ABS port — moteus treats ABS as a disambiguator and
   won't close a loop on it, and separate SPI CS lines scale to 6 joints where
   multiple I²C AS5048Bs need address juggling.
3. **J1 is the easy joint.** Base yaw has no gravity load. Shoulder pitch will
   have holding current, thermal load, pose-dependent sag and nylon creep. The
   0.36° figure is a floor for the arm, not a prediction — and J1 itself
   already shows ~0.84° spread under the larger/faster coordinated moves.
4. **The host cannot see stepper position.** The CL57T corrects lost steps
   itself, so this is not silent drift — but the host has no independent
   measurement, and the reported error is fabricated (see gotchas). Wiring ALM
   closes most of this gap for one wire.
5. **J2 `GEAR_RATIO` must track what is physically fitted.** It is now `1.0`
   (bare motor — the shaft *is* the output, so the convention holds). It sat
   at a planned-but-unfitted 15 through the 2026-09-02 bench session, which
   made every commanded angle come out 15× too big and read as a broken
   degree scale. **Set it to the real ratio and reflash the moment the
   gearbox goes on** — from tooth counts, not hand rotation.
6. **Windows is permanent; timing jitter is still uncharacterised.** Decided
   2026-09-01 — no Linux migration. This is survivable because every actuator
   closes its own loop and the host is only a trajectory sequencer, but the
   jitter has never actually been measured. Instrument the control loop and run
   `workout.txt` idle vs under CUDA load before designing around it.
7. **Perception is started; grasping is not.** As of 2026-09-02 `vision/` has
   the detector (YOLO11m/CUDA, 8.8 ms), the board, camera focus-locking,
   intrinsic calibration and ray-plane localisation, all self-checked. **None
   of it has yet seen a real camera** — the maths is verified synthetically
   and the capture path is untested. The next step is a printed board and a
   ruler: measured mm error at working distance is the number the arm design
   needs, and nothing upstream substitutes for it.
   Still missing entirely: **camera mount, hand-eye transform, IK, and a
   gripper**. IK is blocked on measured link lengths, which are blocked on the
   arm being built — a serial dependency that will bite late if mechanical
   slips.
8. ⚠️ **The gripper has no owner and is not in the actuator map.** The demo is
   "pick it up", and J1–J6 accounts for no gripper actuator at all. It is on
   the critical path with a mechanical design dependency of its own. An STS3215
   is the obvious pick given J5/J6 already use that bus. Raised 2026-09-02;
   unassigned.

## Scope discipline

~9 weeks to the fair as of 2026-09-01. Cut before adding. Already cut: LiDAR
(optical ToF, not RF, and no clear job on a fixed-frame arm), moving-object
tracking, visual servoing. Deferred: mmWave radar safety zone (real RF/DSP,
genuinely good addition, but only if ahead by week 9).

A scoped-down demo that works beats an ambitious one that half-works.

**Standing risk (named 2026-09-01):** the software is running ahead of
integration — abstraction, tests, safety layering and a desktop GUI exist for
an arm that is 2 joints of 6 with no perception. The classic failure shape is
the tractable half racing ahead while mechanical + integration + perception
collide in the last fortnight. **A 4-DOF pick that works reliably beats a
6-DOF arm that half-works** — if the DOF count is not load-bearing for the
pitch, cutting to 4 + gripper makes IK closed-form and frees weeks.
