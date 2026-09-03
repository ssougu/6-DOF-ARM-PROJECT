# Host tools — user guide

Everything in `host/`. Positions are **output revolutions** internally,
**degrees** in anything you see. `python` = your 3.12 venv with
`pip install moteus pyserial`.

Ports on this rig: **COM7** = moteus (J1, mjcanfd-usb), **COM3** = J2 ESP32.
Windows serial ports are exclusive — one program per port at a time.

Design decisions live in `CONTROLLER_ARCHITECTURE.md` (where control runs) and
`VISION_APPROACH.md` (camera + calibration). This file is *how to drive the
tools*; those are *why the system is shaped this way*.

⚠️ `pkill` does nothing on Windows. To free a stuck port:
`Get-NetTCPConnection -LocalPort 8787 -State Listen | Stop-Process` for the
server, or `Get-Process python | Stop-Process -Force`.

---

## Quick reference

| I want to… | command |
|---|---|
| Check J1 is alive and calibrated | `python joint_setup_v2.py --id 1 --probe` |
| Tune / characterise one moteus joint | `python joint_console_v2.py --id 1` |
| Write J1's tuned config to the board | `python joint_setup_v2.py --id 1 --apply` |
| Drive J1 + J2 together, interactively | `python arm_console.py --j2-port COM3` |
| Play a motion routine, no console | `python arm.py --j2-port COM3 --route routines/warmup.txt` |
| Try any of the above with no hardware | add `--sim` |
| Confirm the arm code still works | `python sim_test.py` |
| Open the desktop GUI | `npm run tauri dev` in `ui/` |
| Run the control server alone | `python arm_server.py --sim` |
| Flash J2 firmware | `pio run -t upload` in `firmware/j2_stepper` |

---

## joint_setup_v2.py — one moteus joint: calibration & config

Config I/O goes through `moteus_tool` subprocesses (the in-process
`moteus.Stream` path doesn't work on this rig).

```
python joint_setup_v2.py --id 1 --probe        # liveness + calibration, no motion
python joint_setup_v2.py --id 1 --check        # calibrated? config drift vs profile
python joint_setup_v2.py --id 1 --dump servo   # print config (optionally filtered)
python joint_setup_v2.py --id 1 --backup j1.cfg --dump    # save full config to a file
python joint_setup_v2.py --id 1 --apply        # write profile_1.json to the board + verify
python joint_setup_v2.py --id 1 --sync         # capture the board's values AS profile_1.json
python joint_setup_v2.py --id 1 --set servo.pid_position.kp 250   # one param, then verify
python joint_setup_v2.py --id 1 --calibrate    # MOTOR SPINS FREELY — output must be disconnected
```

`profile_1.json` next to the script overrides the built-in defaults and is
what `--apply` writes. After tuning in the console, `--sync` to capture it.

**Do not `--calibrate` a joint that `--check` says is CALIBRATED.**

---

## joint_console_v2.py — one moteus joint: live control & tests

```
python joint_console_v2.py --id 1
python joint_console_v2.py --id 1 --script tune.txt        # run a script, stay at prompt
python joint_console_v2.py --id 1 -c "step 0.05" -c "csv a.csv" --exit
```

Stopping: **blank line = e-stop**, Ctrl-C = e-stop + exit, watchdog stops the
joint ~0.25 s after the host goes quiet.

Key commands (`help` for the full list):

| | |
|---|---|
| `goto <rev>` / `hold` / `vel <v>` / `zero` | move / hold / velocity / define 0 |
| `kp <x>` `kd <x>` `ilim <x>` | live gain scaling (nothing written to the board) |
| `save [--flash]` | bake current scales into config on exit |
| `step <delta> [dwell]` | step response: overshoot, settle, ringing |
| `cycle <a> <b> <n>` | repeatability between two points |
| `random <n> [--seed s] [--ref p]` | random point-to-point — the honest repeatability number |
| `backlash` | push-by-hand compliance / backlash |
| `wdtest` | prove the watchdog actually stops the joint |

Every test writes `logs/<stamp>_j<id>_<kind>.json` + appends `j<id>_history.csv`.

---

## joints.py — the Joint abstraction (library, not a CLI)

`MoteusJoint`, `StepperJoint`, `SimJoint` behind one interface so motion code
never knows which is which. `python joints.py` runs a SimJoint demo.

- `MoteusJoint` — once `arm()`ed, a background task re-sends the position
  target at 50 Hz to survive the 0.25 s watchdog. `read()` returns the last
  telemetry that task saw; don't run your own `query()` alongside it.
- `StepperJoint` — talks to the ESP32 over serial. Opening the port resets
  the board; the first command waits ~2 s for boot. The firmware only ever
  reports its *commanded* position — there is no real position feedback.
- `SimJoint` — trapezoidal model, no hardware.

---

## arm.py — J1 + J2 as one mechanism

```
python arm.py --sim                              # built-in demo, no hardware
python arm.py --sim --route routines/warmup.txt
python arm.py --j2-port COM3 --route routines/workout.txt
python arm.py --j2-port COM3 --no-j1              # J2 only (e.g. bench motor)
python arm.py --no-j2                             # J1 only
```

`--route` arms both joints, holds, plays the route, stops. Ctrl-C aborts
(watchdogs de-energize in 0.25 s). Moves are **time-synchronised** — every
joint's cruise velocity is scaled to the longest move so they start and
finish together.

Soft limits (per `Axis` in `arm.py`): ±0.53 output-rev both joints, 0.25
rev/s, 1.0 rev/s². `speed` in a route scales the velocity ceiling.

Route logs: `logs/<stamp>_arm_route.json` + `arm_history.csv`.

---

## arm_console.py — interactive console for the whole arm

```
python arm_console.py --j2-port COM3              # real J1 + J2
python arm_console.py --sim                       # no hardware
python arm_console.py --sim -c "arm" -c "move 20 -15" --exit
```

**Stopping:** blank line = e-stop (latches; `arm` to clear). Ctrl-C = stop +
exit. A blank line *during* a move or route cancels it. Pasting several lines
at once runs only the first — type motion commands one at a time.

| command | |
|---|---|
| `status` | one telemetry line per joint |
| `arm` | energize + hold (≈2 s while J2 boots) |
| `stop` / `disarm` | e-stop |
| `zero [id…] yes` | define the current pose as home — **position the arm by hand first** |
| `move <j1> <j2>` | both joints to absolute degrees, synchronised |
| `j` / `movej <id> <deg>` | one joint, absolute |
| `jog <id> <ddeg>` | one joint, relative |
| `speed <0.02–1>` | global fraction of each joint's velocity limit |
| `home` | synchronised move to the zeroed home pose |
| `route <file>` | play a route file |
| `watch [hz]` | live telemetry stream (Enter stops it) |
| `wait <s>` / `echo <text>` | for scripts |

Typical session: `status` → `arm` → position arm by hand → `zero all yes` →
`status` → `move …`.

---

## Route files (`routines/*.txt`)

One step per line (or `;`-separated). `#` starts a comment.

```
speed 0.4
move  25 -12        ; J1 -> 25°, J2 -> -12°, synchronised
movej 2 -20         ; just J2
jog 1 5             ; J1 by +5°, relative
wait 0.5            ; dwell (seconds)
home
echo picking
```

Ops: `move` `movej` `jog` `home` `wait` `speed` `echo`. `move` needs both
joints present. Routes run relative to the current zero.

| file | what it is |
|---|---|
| `warmup.txt` | ~20 s, gentle, slow — run first each session |
| `demo.txt` | short coordinated sequence |
| `pick_place.txt` | ~60 s, 3× simulated pick-and-place with grab/release dwells and speed changes |
| `workout.txt` | ~76 s — big sweeps, hard reversals, speed ramp, 6× repeatability return |

Angles are *output* degrees. J2 is currently a bare motor (`GEAR_RATIO=15`
placeholder), so its shaft turns 15× the commanded angle — keep J2 numbers
small until the gearbox and real ratio are in.

---

## sim_test.py — no-hardware smoke test

```
python sim_test.py                       # coordinated sequence + PASS/FAIL
python sim_test.py routines/demo.txt      # run a route through the sim
```

Checks landing accuracy and that the two joints finish their shared move
together. Exits non-zero on failure — use it after changing `arm.py` or
`joints.py`.


---

## arm_server.py — WebSocket control server (backend for the GUI)

```
python arm_server.py --sim                 # no hardware
python arm_server.py --j2-port COM3        # live (autodetects a CP210x/CH340 if omitted)
python arm_server.py --port 8787 --hz 15
```

Wraps one `Arm` and serves it to WebSocket clients on `ws://127.0.0.1:8787`.
Unlike the CLI entry points it builds joints **lazily** — a joint that is off,
or whose hardware is unplugged, never opens its port, so the server always
starts and you switch joints on from the UI.

- Broadcasts a full state frame ~15 Hz: per joint `{enabled, connected, deg,
  vel_dps, moving, fault, voltage, temp, min/max/home_deg}` plus `{armed,
  estopped, speed, busy, route, sim}`.
- Commands are serialised through one worker, so two clients can't interleave
  motion. **`estop` bypasses the queue** and lands mid-move.
- A client disconnecting does *not* stop the arm — a dropped browser tab
  shouldn't abort a running routine, and the hardware watchdogs cover a crash.

Commands: `arm` `disarm` `estop` `home` `enable_joint {id}` `disable_joint {id}`
`jog {id, delta_deg}` `move_to {id, deg}` `move {targets}` `zero {ids, confirm}`
`set_speed {value}` `run_route {name}` `stop_route` `list_routes`.

Test it: `python test_arm_server.py` (server must be running) — fires every
command and asserts the state stream reflects each one.

---

## ui/ — the desktop control panel (Tauri + Svelte)

```
cd ui
npm run tauri dev                    # SIM by default
$env:ARM_UI_SIM=0; npm run tauri dev # LIVE hardware
npm run tauri build                  # packaged .exe + installer
```

The Rust shell only spawns and kills `host/arm_server.py` — all arm logic
stays in Python. Closing the window kills the server, so it can never be left
holding COM ports. **Defaults to SIM**; `ARM_UI_SIM=0` starts in LIVE, or use
the SIM/LIVE button in the header to switch at runtime.

Switching modes restarts the server. The UI sends a `shutdown` command first,
which de-energizes every joint and releases the COM ports; only if that does
not land within 2 s does the Rust side force-kill. Same on window close, which
is why the app takes a beat to exit. Going LIVE needs a second, explicit
confirmation — the SIM default exists so no single stray click can energize a
motor, and a one-click toggle would give that back.

In LIVE, each joint card shows where it is addressed (`COM3` for the stepper,
`id 1` for the moteus) so a joint that will not come up is easy to diagnose.

### Live bring-up, in order

Switching to LIVE restarts the server, which rebuilds every spec from
defaults — so **a joint you switched off comes back on after a mode switch**.
Do it in this order:

1. **SIM → LIVE** (confirm the prompt)
2. **Switch off any joint that is not physically present.** Do not switch a
   missing moteus *on*: `_build_joint` calls `get_singleton_transport`
   synchronously, and with no fdcanusb attached that can block the event loop
   and freeze the UI. Pressing Arm with it enabled is safe — the failure is
   caught, the joint is auto-disabled, and the reason is logged.
3. **Arm.** This is what actually opens the ports. Until you arm, an enabled
   joint shows an amber knob and *"switched on — press Arm to connect"*, its
   controls are dead, and `Zero here` refuses — it is enabled but not
   connected. See the gotcha in CLAUDE.md.
4. Place the arm at home **by hand**, then **Zero here**. J2 has no absolute
   reference; its zero is wherever it powered up, and it moves again after
   every ESP32 reset (including a reflash).
5. Jog. Start at ±1°.

If a joint switches itself OFF during Arm, the log pane says why — that is a
connection failure, not a bug.

What's on screen:

| | |
|---|---|
| **E-STOP** | top-right, always visible. Also bound to **Esc**. Latches; press *Re-arm* to clear. Red border round the whole window while latched. |
| **SIM / LIVE badge** | it is a **button**. Click it to switch modes without relaunching — SIM→LIVE asks for confirmation first, LIVE→SIM goes straight through. Greyed out mid-route, and in a browser (no Rust side to restart). |
| **Arm / Disarm / Home** | plus a speed slider (0.05–1.0) and *Zero here* behind a confirm |
| **Joint card** (one per joint) | ON/OFF toggle, dial with soft-limit sweep, live angle, moving/velocity/fault/volts/temp chips, jog buttons (±1/5/10°), go-to-angle box |
| **Routines** | pick any `routines/*.txt`, Run / Stop, live step counter and progress bar |
| **Log** | the server's own log stream |

Motion controls grey out unless the arm is armed, that joint is enabled, and
no routine is running. Switching a joint **off de-energizes it** and drops it
out of every move — the other joint keeps working.

Without Tauri you can run the same UI in a browser: `npm run dev` in `ui/`
plus `python arm_server.py --sim`, then open `http://localhost:1420`.
