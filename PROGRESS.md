# Progress log

Daily record of what was done, what came out of it, and what's next. Newest
entry on top. Keep entries short and concrete — this is for "what did we
learn / what's blocked", not a changelog (git has that).

**Entry template**

```
## YYYY-MM-DD — one-line headline

**Focus:** what the session was aimed at
**Done:**
- ...
**Outcomes / data:**
- numbers, measurements, pass/fail
**Problems hit:**
- what broke and the fix (or "still open")
**Next:**
- the next concrete step
**Time:** ~Nh   **Who:** initials
```

---

## 2026-09-02 — first live motion from the GUI (J2); J2 degree scale was 15× off

**Focus:** the GUI could only reach real hardware by relaunching with an env
var. Make the mode switchable at runtime, make switching safe, then actually
drive a motor with it. **J2 moved under GUI control — the first time the
desktop app has driven real hardware.** J1 was off the bench being greased, so
its live path is still unexercised.

**Done:**
- **Found the actual gap:** `restart_server` / `server_status` existed in
  `ui/src-tauri/src/lib.rs` but the frontend never called `invoke` at all —
  both were dead code. `ARM_UI_SIM=0` at launch was the only way into LIVE.
- **`ModeSwitch.svelte`** (new) — the SIM/LIVE badge is now a button.
  SIM→LIVE requires a second confirmation (the SIM default is the thing that
  stops a stray click energizing a motor; a one-click toggle would undo it);
  LIVE→SIM goes straight through. Disabled mid-route and in a browser.
- **`shutdown` command in `arm_server.py`** — stops any route, de-energizes,
  then ends `run()` a beat later so the ack still reaches the client.
  Mode-switch and window-close both use it.
- **`kill()` in Rust now takes a grace period** and prefers the server's own
  exit: 2 s on a mode switch, 800 ms on window close. Previously always
  `TerminateProcess`, which skips `run()`'s `finally` entirely — only the
  moteus 0.25 s watchdog was saving J1, and a holding stepper just stayed
  energized. Waiting also means port 8787 is free before the replacement binds
  it (the stale-server failure from 2026-09-01).
- **`restart_server` is now `async`** so the grace wait is off the UI thread.
- **`snapshot()` gained `link`** — COM port for a stepper, CAN id for a
  moteus. Shown on the joint card in LIVE only, for bring-up diagnosis.
- **`test_arm_server.py` covers `shutdown`** — asserts it de-energizes *and*
  that the process actually closes the connection, not just acks.

**Then the bench session, and two things it caught:**
- **`GEAR_RATIO` was 15 with no gearbox fitted, so every J2 angle came out 15×
  too big** — a commanded 10° moved the shaft ~150°. It reads as a broken
  degree scale; it is arithmetic. The constant described the gearbox we
  *plan* to fit, not the bare motor actually bolted on. Set to **1.0** (the
  shaft is the output, so the OUTPUT-REVOLUTIONS convention holds exactly),
  firmware rebuilt clean. Consequence: `velLimit` 0.25 output rev/s is now
  90°/s at the shaft instead of ~1350°/s, so motion is correctly much slower.
- **`enabled` and `connected` are different things, and the UI conflated
  them.** Joints are built lazily, so J2's spec was enabled from startup while
  nothing was open on COM3. The card showed a green ON toggle, "no telemetry",
  dead jog buttons, and `zero: no enabled joints to zero` — about a joint that
  *was* enabled. Pressing Arm is what builds and connects it. Fixed: an
  enabled-but-unconnected joint now shows an amber knob and "switched on —
  press Arm to connect", the readout says `not connected` rather than "no
  telemetry", and the zero error names the joint and says to arm first.
- **`Arm.arm()` now returns the build errors it swallows.** `_ensure_built`
  auto-disables a joint that cannot connect, but the reason only went to
  `print()` — which under Tauri is a hidden console. J1 would just flip to OFF
  for no visible reason. The server now logs each as a warning.

**Outcomes / data:**
- **J2 driven live from the GUI**: connect on COM3 (autodetected), arm, zero,
  jog. Motion correct and repeatable once the ratio was fixed.
- `test_arm_server.py` green including the new shutdown case; verified the
  server process exits on its own (`HasExited: True`), no force-kill needed.
- `sim_test.py` PASS (worst landing 0.000°, sync 0.000 s); `warmup.txt` clean.
- `svelte-check` 0 errors / 0 warnings; `cargo build` clean; `pio run` SUCCESS
  (flash 22.9%).
- LIVE server startup autodetects the ESP32 correctly: `J2: autodetected COM3`.

**Problems hit:**
- Repo had moved from `OneDrive\Desktop` to `C:\dev`; `ui/src-tauri/target/`
  carried absolute paths from the old location and `tauri-build` failed
  looking for permission files under the dead path. All 76 build-script dirs
  referenced it, so `cargo clean` (4.5 GB) was the only fix. `.svelte-kit`
  had the same staleness. Rebuild was 2m10s.
- Node was on the machine PATH but not in the running shell — VS Code had
  inherited a pre-install environment snapshot. Restarting VS Code fixes it.
- A leftover test server holding 8787 made the app show NO SERVER: the child
  it spawned could not bind and died silently. Same failure as 2026-09-01, so
  it is now twice. The Rust side does not surface the child's exit at all —
  worth fixing, since the symptom is indistinguishable from "python missing".

**Still not done — the honest part:**
- **J1's live path is still unexercised.** J1 was being greased, so the moteus
  transport built inside the server's event loop has never run under the GUI.
  It is the piece most likely to bite, because `_build_joint` calls
  `get_singleton_transport` synchronously — if that hangs rather than raises
  with no fdcanusb attached, it blocks the event loop and freezes the UI.
- **J2's `err` is still fabricated** (commanded reported as measured). It read
  0.00 throughout today's live session, which is exactly when it is most
  misleading. Unchanged — see the gotcha in CLAUDE.md.
- Nothing has run *both* joints live, so the coordinated-move path under the
  GUI is untested.
- The gearbox burn-in (open question 1) is still not run.

**Next:**
- Repeat today's bring-up with J1 once it is back: J1 alone first, then both.
  Confirm the mode switch de-energizes real motors.
- **Set `GEAR_RATIO` to the true ratio the moment J2's gearbox is fitted**, and
  re-zero. From tooth counts, not hand rotation.
- Wire the CL57T ALM output (one wire, ~3 lines of firmware) — the cheapest
  way to make J2's fault reporting real, and the fabricated-`err` problem is
  now demonstrably live rather than theoretical.
**Time:** ~4h   **Who:** —

---

## 2026-09-02 (evening) — perception stack stood up; runs without the arm

**Focus:** J2 is blocked on mechanical, so start the half of the demo that
needs no arm at all. Perception was 100% unstarted with ~9 weeks to the fair,
and it is the workstream least coupled to anything else.

**Done:**
- **`vision/` created.** `board.py` (ChArUco, defined once, printable at exact
  scale), `camera.py` (capture + focus/exposure pinning), `calibrate.py`
  (intrinsics + coverage score), `detect.py` (YOLO11m on CUDA),
  `locate.py` (**pixel → table mm by ray-plane**), `check_vision.py`
  (8 checks, PASS/FAIL, no camera needed).
- **Nothing needed installing.** torch 2.6.0+cu124, ultralytics 8.4.61,
  opencv 4.13 were all already present and CUDA works. Only the 38.8 MB
  YOLO11m weights were downloaded (gitignored).
- **Ray-plane is verified synthetically** — a virtual camera projects points
  with known board coordinates, and `pixel_to_table` recovers them to 4.8e-14
  mm. That test caught a real sign error in `--plane-offset`: the offset moved
  the plane toward the camera when the documented meaning is *behind* the
  board face. A visual overlay would have looked completely fine.

**Outcomes / data:**
- YOLO11m, RTX 4060 Laptop, imgsz 640: **median 8.8 ms (114 fps)**, p95
  10.4 ms, worst 44.2 ms. Far faster than look-then-move needs — detection
  will not be the bottleneck, localisation accuracy will.
- **FP16 is not worth it**: median 8.4 ms but p95 17.1 ms and worst 64 ms.
  Bound by preprocessing and NMS, not conv math. Stay FP32.
- `check_vision.py`: 8/8.

**Corrections to earlier assumptions:**
- **The laptop GPU is an RTX 4060 Laptop with 8 GB, not a 4090.** CLAUDE.md
  had said 4090 since the start. Fine for YOLO11m, but it changes the headroom
  story if anything heavier is ever considered.

**Problems hit:**
- `cv2.setLogLevel` does not exist in this OpenCV build, and my first attempt
  to quiet the camera-probe warnings wrapped it in try/except — so it silently
  did nothing while looking like it worked. Exactly the failure mode this repo
  keeps warning about, committed in new code. Now an fd-level stderr redirect,
  scoped to the scan, with the restore verified.

**Then the camera came on, and `--lock` produced a near-black image:**
- **My bug.** `lock()` switched auto-exposure off without supplying a value,
  so the driver fell back to its manual default — a very short exposure. Now
  it lets auto converge, reads the value it chose, pins that, then *checks the
  resulting picture* and backs out to auto if the driver ignored it (this
  webcam does). Final image 138/255.
- **`Locked.ok` was wrong in principle**, requiring both focus and exposure.
  Focus changes the intrinsics; exposure does not move a pixel geometrically.
  A well-exposed auto frame beats a pinned dark one, so `ok` is focus-only.
- **`AUTOFOCUS` returning −1 is ambiguous** — no control exposed covers both
  "fixed-focus lens, nothing to pin" and "autofocus we cannot stop". The
  property cannot distinguish them, so it now watches Laplacian sharpness over
  ~2 s. **This laptop's webcam reads as fixed-focus (cv ~1–3%) and is safe to
  calibrate.**
- Webcams also stream dark for a few hundred ms after opening, so the first
  measurements described the ramp rather than the camera. Settles added.

**Not done — and it matters:**
- Calibration quality against a real board is still unmeasured.
- No board printed yet, so no intrinsics, so no real mm number.

**Next:**
- Print `charuco_7x5_25mm.png` at **exactly 100%**, verify a square with
  calipers, glue it to something rigid.
- `python camera.py --index 0 --lock` — if the laptop webcam will not pin
  focus, it cannot be calibrated and the RealSense is the answer.
- Calibrate, then `locate.py --ruler` against a real ruler. **That mm number
  is the deliverable** — it feeds the error budget and tells us early whether
  the grasp closes, while there is still time to widen the jaws instead of
  chasing joint precision.
**Time:** ~1h   **Who:** —

---

## 2026-09-01 — Tauri desktop control panel; joints switchable at runtime

**Focus:** a GUI that makes the arm usable without the text console, with
per-joint on/off switching from the computer.

**Done:**
- **Toolchain:** installed Node 24.19, Rust 1.98 (rustup 1.29), MSVC Build
  Tools. `pio` is still off PATH at `~/.platformio/penv/Scripts/pio.exe`.
- **`host/arm.py` — runtime joint management.** New `JointSpec`; `Arm` now
  builds a `Joint` only when it is enabled, so a joint that is off or
  unplugged never opens its port. `enable(id)` / `disable(id)` /
  `active_ids` / `snapshot()`. Disabling de-energizes and drops that joint
  from every move (its target is skipped, not an error). The old
  `Arm([joint, ...])` constructor path is unchanged, so `sim_test.py` and the
  route runner kept working throughout.
- **`host/arm_server.py`** (new) — WebSocket control server on
  `ws://127.0.0.1:8787`. ~15 Hz state broadcast, commands serialised through
  one worker, `estop` bypasses the queue so it lands mid-move, routes run as a
  cancellable task with a step counter. `--sim` for no hardware; autodetects a
  CP210x/CH340 for J2 if `--j2-port` is omitted.
- **`host/test_arm_server.py`** (new) — fires every command and asserts the
  state stream reflects it.
- **`ui/`** (new) — Tauri v2 + SvelteKit + Svelte 5 desktop app. Joint cards
  with ON/OFF toggle, dial with soft-limit sweep, jog ±1/5/10°, go-to-angle,
  live telemetry chips; arm/disarm/home/zero/speed bar; routine runner with
  progress; log pane; big E-STOP bound to Esc. Rust side is thin — it only
  spawns and supervises `arm_server.py`.
- **`arm_console.py`** gained `enable <id>` / `disable <id>`.

**Outcomes / data:**
- `test_arm_server.py` green: 13 telemetry frames/s, every command lands,
  disabling J2 really does drop it from a `move` while J1 still runs,
  re-enabling re-arms it, `stop_route` and `estop` both halt a running route.
- Regression green throughout: `sim_test.py` PASS, workout/warmup routes
  clean, `arm_console.py --sim` unchanged.
- Rust builds clean (3m32s cold). `svelte-check`: 0 errors, 0 warnings.
- GUI **defaults to SIM** (`ARM_UI_SIM=0` for hardware) so a stray launch
  cannot energize a motor.

**Problems hit:**
- First sidecar test: hard-killing the app left `arm_server.py` running and
  holding COM ports **with motors energized**. Fixed — Rust passes
  `--parent-pid` and the server polls it every 2 s, shutting down (and
  de-energizing) when the UI dies for any reason. Verified with a forced kill.
- A stale orphaned server on 8787 made one test look like a failure; the new
  server couldn't bind and died silently. Worth remembering: `pkill` does
  nothing on Windows — use `Get-NetTCPConnection -LocalPort ... | Stop-Process`.
- npm 11 gates postinstall scripts; esbuild needed `npm rebuild esbuild`.

**Architecture decisions (second half of the session, no code):**
- **Actuator map settled.** J3 = moteus (the spare), J4 = stepper (ships with
  its CL57T), J5/J6 = FEETECH **STS3215** bus servos. → 2 CAN-FD nodes, 2 step
  generators, 2 servos.
- **Controller: Teensy 4.1** — see `docs/CONTROLLER_ARCHITECTURE.md`. Chosen
  for CAN-FD (CAN3 is the only FD-capable peripheral) and Arduino-speed under
  deadline, *not* clock speed — the workload would run on a 100 MHz M4. The
  custom-PCB path is a carrier board with the Teensy socketed, which keeps the
  STM32H7 option open because the expensive part of that board (transceiver,
  opto drive, e-stop chain, power) is MCU-agnostic.
- **Windows is permanent.** No Linux migration. Survivable because every
  actuator closes its own loop and the host is only a sequencer.
- **The MCU should not run PID** — every actuator already does, and J1's is
  tuned. Its real jobs are consolidation, a hardware safety chain, and later an
  *outer* loop on output-side encoders.
- **Vision plan written** — `docs/VISION_APPROACH.md`. Eye-in-hand on the
  forearm (not the tool flange), look-then-move to dodge min-Z, ray–plane
  intersection as the primary localiser with depth as a cross-check, ChArUco
  hand-eye calibration.

**Corrections to earlier assumptions:**
- **The steppers are not open-loop.** The CL57T with the `-E1000` motor is
  genuinely closed-loop and corrects missed steps internally — it faults rather
  than drifting silently. Previous notes overstated this.
- **The CL57T's ALM output is unwired**, and that is the actual gap. One wire +
  ~3 lines of firmware; the whole host path (`fault=` telemetry → `Arm.move()`
  abort → GUI fault chip) already exists. **Highest value-per-effort item open.**
- **The STS3215 has a 12-bit encoder** with position/load/voltage/temp
  readback, so `JointState` populates for real. Not PWM servos.
- **`err +0.00` for J2 in the route logs is fabricated** —
  `StepperJoint._to_state` returns commanded position as if measured, and it
  feeds `worst_err_deg` alongside J1's real numbers. This is the "tests that
  cannot fail" gotcha, in our own telemetry. Should report `null`.
- **Error budget is better than feared:** ~5–8 mm at the gripper, not 10–15 —
  independent errors combine as RSS, not linearly. Most of a naive budget is
  systematic and therefore calibratable.

**Next:**
- ⚠️ **Encoder mounting provisions into the gearbox CAD** — magnet pocket +
  sensor boss, before anything prints. Retrofit means reprinting. Cheap now.
- ⚠️ **Self-centring gripper** (V-groove/funnel, 15–20 mm compliance) — absorbs
  the whole error budget mechanically. Tell the ME before it's designed.
- **Wire the CL57T ALM output.** One wire.
- Phase 0 (no MCU needed): joint table → `arm_config.json`, then J3, then
  `ServoJoint` for J5/J6, then J4 as a second ESP32 axis.
- Make the fake `err +0.00` honest.
- Measure the control-loop jitter idle vs under CUDA load — turns open question
  #6 into a number instead of an assumption.
- Click-through the GUI on hardware (`ARM_UI_SIM=0`).
- Still open: J2 real gear ratio, gearbox burn-in, the J1 0.84° spread.

**Standing risk named this session:** the software is running ahead of
integration. Abstraction, tests, safety layering and a GUI exist for an arm
that is 2 joints of 6 with no gripper and no perception, ~9 weeks out. A 4-DOF
pick that works reliably beats a 6-DOF arm that half-works.

**Time:** ~1 session   **Who:** —

---

## 2026-08-31 — first coordinated J1 + J2 motion on hardware

**Focus:** get both joints moving together as one arm.

**Done:**
- New multi-joint control layer:
  - `host/arm.py` — `Arm` class: time-synchronised moves (velocity of each
    joint scaled so they start and finish together), `home` / `zero` /
    panic-`stop`, route player, per-move error logging to
    `logs/arm_history.csv`.
  - `host/arm_console.py` — interactive + scriptable console for the whole
    arm. Blank line = e-stop; refuses pasted command blocks.
  - `host/sim_test.py` — no-hardware self-checking smoke test (landing
    accuracy + joint synchronisation), PASS/FAIL.
- `host/joints.py`: `MoteusJoint` now *streams* its target at 50 Hz (it was
  fire-and-forget and would have been cut off by the 0.25 s watchdog on real
  hardware); added `hold()` / `zero()` to every joint type; `SimJoint` got a
  trapezoidal profile so sim timing matches hardware.
- Flashed the J2 stepper firmware to the ESP32 (COM3) and verified the serial
  protocol (`ready joint=2 type=stepper`, `Q` -> telemetry).
- Route files: `routines/warmup.txt`, `routines/pick_place.txt`,
  `routines/workout.txt` (direction reversals, speed changes, dwells).
- First hardware runs: `warmup` and `workout` routines, J1 (moteus, COM7) +
  J2 (stepper, COM3) together.

**Outcomes / data:**
- **J1 (moteus):** tracked every command. Over 30 moves in `workout`
  (±75°, speeds 0.3–1.0): mean |error| **0.14°**, worst **0.48°**.
  Repeatability block (6× return to the same pose from varied detours):
  errors −0.36° … +0.48°, **spread 0.84°**. Wider than the 2026-08-26 cold
  bring-up figure (0.36° random-approach) — expected, since moves here are
  larger, faster, and J2 is now hanging off it. Still sub-degree.
- **J2 (stepper):** every move completed, no stalls, watchdog held through
  multi-second moves. **Host-side error is always 0.00 and is NOT a real
  measurement** — the firmware reports commanded position, so missed steps
  would show only as an accumulating physical offset the host can't see.
- No faults, no e-stops, no missed watchdog kicks. `arm_console.py` transport
  fix confirmed (`status` returns real telemetry, no hang).
- Logs: `host/logs/20260831-23*.json` + `arm_history.csv`.

**Problems hit (all fixed today):**
- `firmware/j2_stepper/platformio.ini` (and `j2_bench/`, `.gitignore`) had a
  UTF-8 BOM → PlatformIO couldn't parse it → J2 firmware had never actually
  been flashed. Rewrote the files without the BOM; pinned `upload_port` /
  `monitor_port = COM3`.
- `arm_console.py` built the moteus fdcanusb transport *before* the asyncio
  loop started → dead transport → `status` hung forever on J1's query. Now
  built inside `asyncio.run`. Added to CLAUDE.md gotchas.
- Route parser split on `;` before stripping `#` comments, so a `;` inside a
  comment became a bogus command. Fixed.
- `MoteusJoint.arm()` / `read()` could hang on a dead link — now time out
  (3 s / 2 s) with a clear "no response from moteus" message.
- A pasted block of console commands chained into an unattended motion
  sequence (and `zero all yes` fired at the wrong pose). Console now runs
  only the first pasted line and refuses the rest.

**Next:**
- Set J2's real gear reduction in `firmware/j2_stepper/src/main.cpp`
  (`GEAR_RATIO`, still the placeholder 15.0) once the gearbox exists.
- Decide how to validate J2 open-loop (visual index mark, or the AS5048B on
  the moteus ABS port idea from CLAUDE.md open question #2).
- `zero all yes` against a defined mechanical home before any real
  repeatability testing — today's routes ran from an arbitrary power-on zero.
- Characterise J1 repeatability under the larger/faster coordinated moves
  (the 0.84° spread) rather than assuming the 0.36° bench number.
- Run the gearbox burn-in (CLAUDE.md open question #1) — still not done.

**Time:** ~1 session   **Who:** —

---

## Before this log

J1 base-yaw bring-up and characterisation happened 2026-08-26 (see
`CLAUDE.md` "Numbers that matter" and `host/logs/20260826-*`). That work
predates this file.
