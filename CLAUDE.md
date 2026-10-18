# CLAUDE.md

Context for AI assistants working in this repo. Keep this file current — it is
the fastest way to avoid repeating mistakes that already cost us time.

Session-by-session progress and outcomes go in `PROGRESS.md` (newest on top).
Add an entry there at the end of each working session.

Design decisions live in `docs/`: **`CONTROLLER_ARCHITECTURE.md`** (where
control runs, the Teensy 4.1 decision, phasing) and **`VISION_APPROACH.md`**
(camera mount, calibration, error budget). **`POWER_ARCHITECTURE.md`** holds the
36 V bus decision, regen handling, the PDB+Teensy board and the pin map. Read those before proposing
changes to the control, power or perception layers.

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
│   ├── POWER_ARCHITECTURE.md   36 V bus, regen, rail tree, PDB+Teensy board
│   ├── J2_DESIGN_BRIEF.md      hand-off to the ME: encoder provision, stiffness
│   ├── J1_CHARACTERIZATION_PLAN.md  the full J1 test plan, with derivations
│   └── J1_SESSION_REPORT_2026-10-18.md  first bench results + corrections
├── analysis/                   offline plotting; never touches hardware
│   ├── j1_figures.m            MATLAB: all 8 figures (UNTESTED — no MATLAB here)
│   ├── j1_figures.py           Python mirror, same logic/palette — this made the PNGs
│   ├── j1_style.m  j1_manifest.m  j1_load_run.m  j1_settle.m  j1_travel_time.m
│   └── figs/                   rendered PNGs, committed
├── hardware/                   Altium (LFS) + later mechanical CAD
│   ├── arm-pdb/                the PDB + Teensy board
│   └── releases/               fab packages actually sent out
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
│   ├── detect.py               YOLO11m on CUDA → boxes + ground point;
│   │                           --stability = repeatability in px, no board
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

**Superseded 2026-10-18 by an n=50 run.** See
`docs/J1_SESSION_REPORT_2026-10-18.md`; figures in `analysis/figs/`.

| Metric | Value | Basis |
|---|---|---|
| **Design figure, \|μ\|+2σ** | **0.685° → 4.78 mm at 400 mm** | n=50, random approach |
| Landing-error σ | 0.2950° (95% CI ±20%) | n=50 |
| Mean \|error\| | 0.2656° | n=50 |
| Worst single move | 0.5712° | n=50 |
| Direction split | 0.0231° ± 0.0835 (SE) | indistinguishable from zero |
| Backlash, two-point | 0.23° (0.75° at 0.5 rev/s, n=2) | rotor-side inference only |
| Static error floor | 0.03–0.31° | 5 step sizes |
| Damping | **overdamped, ζ ≥ 1** | no overshoot at any step size |

**The old 0.36° was never a σ — it was the *range* of 20 samples.** Ranges grow
with n, so it was not comparable to anything. Quote **0.685°**; it is 1.9× worse
than the figure previously designed around.

Likewise the 2026-08-31 `workout` figure of 0.84° was a range of **6**.
Normalised with `σ̂ = R/d₂` the bench-to-coordinated degradation is **3.4×**, not
the ~2× once recorded — but at n=6 the CI is ±62%, so it never supported a
comparison at all. **No figure from n < 22 belongs in this file.**

The previously recorded step response, *"1.6% overshoot, 0.17 s settle"*, **does
not reproduce and should not be quoted.** It had no logged provenance, and
measurement shows negative overshoot on four of five steps with settling of
0.72–1.22 s. See the trajectory-generator gotcha below for why.

At 400 mm, 0.685° is ±4.78 mm from J1 alone — open-loop forward kinematics will
not be enough for a grasp. Note this is **repeatability, not accuracy**: the
joint returns to a pose reliably, it just cannot tell you where that pose is in
millimetres, because the only encoder sits upstream of the gear train.

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
- Settling is measured in a 2% band *of the commanded step*. The band equals the
  backlash at **δ = 0.0319 rev = 11.5°** (not "~0.05 rev"), below which "did not
  settle" is an artifact. **Confirmed by measurement 2026-10-18** — the flip
  happens exactly there. The replacement absolute band (±0.36°) fixes the lower
  end but is degenerate below δ ≈ 1.8°, where it exceeds a fifth of the step.
  Neither criterion means anything there; report the static error floor instead.
- **`goto`/`step` are NOT step inputs — they go through moteus's trajectory
  generator.** Rate-limited by `vel_limit`/`accel_limit`, so measured "settling
  time" is mostly the traverse time: 4 of 5 step sizes match `travel_time()` to
  within 20%. **Any ζ or ω_n fitted to such a trace describes the rate limiter,
  not the servo.** Raise both limits out of the way before claiming any dynamic
  figure.
- **`servo.max_velocity = 0.5` rev/s is a hard firmware cap, and it is absent
  from `PROFILE`.** Commanding `vel_limit` above it silently does nothing.
  Because `travel_time()` computes dwell from the *commanded* limit, `do_cycle`
  sampled mid-flight and logged `backlash_deg` of 30°, 77° and 108° for a joint
  whose backlash is 0.23°. It printed a warning and logged the metric anyway —
  a test that cannot fail. Records quarantined in `host/logs/voided/`.
- **`moteus.Register.TORQUE` is OUTPUT-side, already ×15.** Proven from the
  board: `Kv = 330` → `Kt_rotor = 0.02894 N·m/A`, and at the 10 A limit the
  rotor can make only 0.289 N·m, so the 0.802 N·m logged cannot be rotor-side
  (it would need 27.7 A) but is 1.85 A output-side. **It assumes a lossless
  gearbox**, so it is an upper bound: true output torque is `η ×` the reading.
  Call it *lossless-referred*. Available at 10 A is 4.34 N·m — the 1.0 N·m
  ceiling used all session was 23% of it, and only 1.9× breakaway.
- **`CONTROL_HZ = 50` does not produce 50 Hz.** Measured 15.73 ms mean
  (n = 1452) = **63.6 Hz**, quantised to the 15.6 ms Windows scheduler tick,
  0.7% double ticks, worst case 31 ms. Jitter is bounded and quantised, not
  Gaussian. Raising the rate above ~64 Hz needs a different timer, not a bigger
  constant.
- **The board's config is not under version control, and it has drifted.**
  `profile_1.json` has never been committed despite this file saying "COMMIT
  THIS" (`git log --all` finds no trace), `servopos` is ±0.55 rev on the board
  vs ±0.25 in `PROFILE`, and `servo.max_velocity` is in no file at all. The
  tooling to prevent this already exists and has never been used: `--sync`,
  `--check`, `--apply`, `--dump --backup`.
- **`do_random` and `do_cycle` save no raw samples** — they call `log_run`
  without a `samples` argument, so only aggregates survive. 50 landing errors
  were lost this way on 2026-10-18; percentiles, normality tests and
  re-stratification are all impossible after the fact. Only `do_step` logs raw
  data.

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
python detect.py --list-classes                   # the 80 COCO classes, free
python detect.py --stability --label bottle       # detection repeatability, px
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
