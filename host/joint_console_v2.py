#!/usr/bin/env python3
"""
joint_console.py -- test & tuning console for one moteus joint.

    python joint_console.py --id 1

=============================  HOW TO STOP  =============================
  ENTER on an empty line -> instant e-stop      Ctrl-C -> e-stop + exit
  Watchdog stops the joint ~0.25s after the host goes quiet (verify: wdtest)
  The XT30 is the only stop that needs no software. Keep it in reach.
=========================================================================

Live gain tuning uses kp_scale/kd_scale/ilimit_scale, which are sent with
every position command. Nothing is written to the board until you 'save',
so you can always recover by restarting.
"""

import argparse
import asyncio
import math
import shlex
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import moteus

CONTROL_HZ = 50

FAULT_NAMES = {
    32: "calibration fault", 33: "motor driver fault",
    34: "OVER VOLTAGE (regen)", 35: "encoder fault",
    36: "motor not configured", 37: "pwm cycle overrun",
    38: "over temperature", 39: "outside limit", 40: "under voltage",
    41: "config changed", 42: "theta invalid", 43: "position invalid",
}
# Not faults -- reasons torque is being limited right now.
LIMIT_REASONS = {
    100: "system voltage", 101: "motor temperature",
    102: "max_torque ceiling", 103: "position bounds (servopos)",
    104: "flux braking (bus voltage high)",
}
MODE_NAMES = {
    0: "stopped", 1: "FAULT", 5: "pwm", 6: "voltage", 7: "voltage_foc",
    8: "voltage_dq", 9: "current", 10: "position", 11: "TIMEOUT",
    12: "zero_velocity", 13: "stay_within", 14: "measure_ind", 15: "brake",
}

# Config keys the 'set'/'limits' commands know about, with sane bounds so a
# fat-fingered value cannot quietly become a hardware problem.
CONFIG_LIMITS = {
    "servo.max_current_A": (0.0, 30.0),
    "servo.max_power_W": (0.0, 500.0),
    "servo.max_voltage": (10.0, 44.0),
    "servo.max_regen_power_W": (0.0, 200.0),
    "servo.flux_brake_margin_voltage": (0.0, 20.0),
    "servo.default_timeout_s": (0.0, 10.0),
    "servo.pid_position.kp": (0.0, 5000.0),
    "servo.pid_position.kd": (0.0, 500.0),
    "servo.pid_position.ki": (0.0, 5000.0),
    "servo.pid_position.ilimit": (0.0, 100.0),
    "servopos.position_min": None,        # nan allowed
    "servopos.position_max": None,
}


class JointState:
    def __init__(self):
        self.mode = "idle"
        self.position = math.nan
        self.velocity = 0.0
        self.torque = 0.0
        self.max_torque = 1.0
        self.vel_limit = 0.25
        self.accel_limit = 1.0
        # live gain multipliers -- 1.0 means "use the configured value"
        self.kp_scale = 1.0
        self.kd_scale = 1.0
        self.ilimit_scale = 1.0
        self.last = None
        self.log = None              # list to append samples to, or None
        self.last_samples = []       # samples from the most recent test
        self.limit_seen = set()      # torque-limit reasons during a test
        self.log_dir = "logs"        # where test records are written
        self.joint_id = 1
        self.cfg = {}                # configured values, for the record
        self.note = ""               # session label for the log
        self.fault_seen = 0          # real fault seen during a test
        self.quit = False
        self.estop = False


# ---------------------------------------------------------------- e-stop --
async def do_estop(controller, state, reason="e-stop"):
    state.mode = "idle"
    state.estop = True
    for _ in range(3):
        try:
            await controller.set_stop()
            break
        except Exception:                                    # noqa: BLE001
            await asyncio.sleep(0.02)
    print(f"\n*** {reason.upper()} -- de-energized. 'arm' to re-enable ***")


# ---------------------------------------------------------- control loop --
async def control_loop(controller, state):
    period = 1.0 / CONTROL_HZ
    while not state.quit:
        try:
            if state.mode == "idle" or state.estop:
                state.last = await controller.query()
            elif state.mode in ("hold", "goto"):
                state.last = await controller.set_position(
                    position=state.position, velocity=0.0,
                    velocity_limit=state.vel_limit,
                    accel_limit=state.accel_limit,
                    maximum_torque=state.max_torque,
                    kp_scale=state.kp_scale, kd_scale=state.kd_scale,
                    ilimit_scale=state.ilimit_scale, query=True)
            elif state.mode == "vel":
                state.last = await controller.set_position(
                    position=math.nan, velocity=state.velocity,
                    accel_limit=state.accel_limit,
                    maximum_torque=state.max_torque,
                    kp_scale=state.kp_scale, kd_scale=state.kd_scale,
                    ilimit_scale=state.ilimit_scale, query=True)
            elif state.mode == "torque":
                state.last = await controller.set_position(
                    position=math.nan, velocity=0.0,
                    kp_scale=0.0, kd_scale=0.0, ilimit_scale=0.0,
                    feedforward_torque=state.torque,
                    maximum_torque=state.max_torque, query=True)
            # mode 'silent_test' deliberately sends nothing

            if state.last is not None:
                v = state.last.values
                if state.log is not None:
                    state.log.append((
                        time.monotonic(),
                        v.get(moteus.Register.POSITION, math.nan),
                        v.get(moteus.Register.VELOCITY, math.nan),
                        v.get(moteus.Register.TORQUE, math.nan)))
                f = int(v.get(moteus.Register.FAULT, 0))
                if f in LIMIT_REASONS:
                    state.limit_seen.add(f)
                elif f:
                    state.fault_seen = f
                if f and f not in LIMIT_REASONS and not state.estop:
                    await do_estop(controller, state,
                                   f"fault {f} ({FAULT_NAMES.get(f, '?')})")
        except Exception as e:                               # noqa: BLE001
            print(f"\n[control loop] {e}")
            await asyncio.sleep(0.5)
        await asyncio.sleep(period)
    try:
        await controller.set_stop()
    except Exception:                                        # noqa: BLE001
        pass


async def await_telemetry(state, timeout=3.0, quiet=False):
    """Commands that read position need the control loop to have run once."""
    if state.last is not None:
        return True
    if not quiet:
        print("  waiting for first telemetry...", end="", flush=True)
    deadline = time.monotonic() + timeout
    while state.last is None and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    if not quiet:
        print(" ok" if state.last is not None else " TIMED OUT")
    return state.last is not None


def val(result, reg, default=math.nan):
    return result.values.get(reg, default) if result else default


def fmt_status(r):
    if r is None:
        return "no telemetry yet"
    m = int(val(r, moteus.Register.MODE, -1))
    f = int(val(r, moteus.Register.FAULT, 0))
    out = (f"mode={MODE_NAMES.get(m, m):<12} "
           f"pos={val(r, moteus.Register.POSITION):+8.4f} "
           f"vel={val(r, moteus.Register.VELOCITY):+8.4f} "
           f"tq={val(r, moteus.Register.TORQUE):+6.3f}Nm "
           f"vbus={val(r, moteus.Register.VOLTAGE):5.1f}V "
           f"T={val(r, moteus.Register.TEMPERATURE):4.1f}C")
    if f in LIMIT_REASONS:
        out += f"  [limited: {LIMIT_REASONS[f]}]"
    elif f:
        out += f"  FAULT={f} ({FAULT_NAMES.get(f, 'unknown')})"
    return out


# ------------------------------------------------- config via moteus_tool --
def fast_config(target):
    """Prefer profile_<id>.json (instant) over a full dump (~30s).

    Written by `setup.py --id N --sync`. It holds exactly the parameters
    this console cares about: soft limits and PID gains.
    """
    import json
    path = Path(__file__).parent / f"profile_{target}.json"
    if path.exists():
        try:
            data = {k: str(v) for k, v in json.loads(path.read_text()).items()}
            age = (time.time() - path.stat().st_mtime) / 3600.0
            print(f"config from {path.name} ({len(data)} params, "
                  f"{age:.0f}h old) -- 'refresh' to re-read the board")
            return data
        except Exception as e:                               # noqa: BLE001
            print(f"could not read {path.name}: {e}")
    return None


def tool_dump(target):
    """Read config. Needs the USB port, so the console must be idle."""
    cmd = [sys.executable, "-m", "moteus.moteus_tool",
           "--target", str(target), "--dump-config"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "").strip() or "moteus_tool failed")
    out = {}
    for line in p.stdout.splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) >= 4 and parts[:2] == ["conf", "set"]:
            out[parts[2]] = parts[3]
        elif len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def tool_set(target, pairs, persist):
    lines = [f"conf set {k} {v}" for k, v in pairs.items()]
    if persist:
        lines.append("conf write")
    tmp = Path(tempfile.gettempdir()) / "moteus_console_set.cfg"
    tmp.write_text("\n".join(lines) + "\n")
    cmd = [sys.executable, "-m", "moteus.moteus_tool",
           "--target", str(target), "--write-config", str(tmp)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "").strip() or "moteus_tool failed")


def release_transport(transport, verbose=False):
    """Close the serial port so moteus_tool can have it.

    The library's internals are not a stable API, so this closes anything
    closeable it can find rather than assuming a particular attribute.
    """
    import gc
    closed = []

    def try_close(obj, label):
        for name in ("close", "_close", "shutdown"):
            fn = getattr(obj, name, None)
            if callable(fn):
                try:
                    fn()
                    closed.append(f"{label}.{name}()")
                    return True
                except Exception:                            # noqa: BLE001
                    pass
        return False

    if transport is not None:
        try_close(transport, "transport")
        for name in ("_serial", "serial", "_port", "port", "_stream",
                     "_write_stream", "_read_stream"):
            sub_obj = getattr(transport, name, None)
            if sub_obj is not None and not isinstance(sub_obj, (str, int)):
                if try_close(sub_obj, f"transport.{name}"):
                    pass

    # drop the library's cached singleton if there is one
    try:
        import moteus.transport_factory as tf
        for attr in dir(tf):
            if "singleton" in attr.lower() or "GLOBAL" in attr:
                try:
                    setattr(tf, attr, None)
                    closed.append(f"transport_factory.{attr}=None")
                except Exception:                            # noqa: BLE001
                    pass
    except Exception:                                        # noqa: BLE001
        pass

    gc.collect()
    if verbose:
        print("  released: " + (", ".join(closed) if closed else "nothing"))
    return closed


def tool_set_with_retry(target, pairs, flash, transport=None, attempts=5):
    """Windows can take a moment to actually free an exclusive COM port."""
    last = None
    for i in range(attempts):
        try:
            tool_set(target, pairs, flash)
            return True
        except RuntimeError as e:
            last = e
            if "Access is denied" not in str(e) and "PermissionError" \
                    not in str(e):
                raise
            if i == 0:
                print("  port still busy; releasing and retrying...")
                release_transport(transport, verbose=True)
            time.sleep(0.5 * (i + 1))
    raise RuntimeError(f"port never became available: {last}")


PORT_HELP = ("""moteus_tool could not open the adapter -- this console is
  holding it. Windows serial ports are exclusive. Either:
    - 'quit' this console, run the setup script, then come back, or
    - keep tuning live with kp/kd/ki (no config write needed).""")


async def with_port_released(controller, state, fn):
    """Stop the motor and pause commanding while a subprocess uses the port."""
    state.mode = "silent_test"
    await do_estop(controller, state, "releasing port")
    await asyncio.sleep(0.4)              # let in-flight frames drain
    try:
        return fn()
    except RuntimeError as e:
        print(f"\n{e}\n\n{PORT_HELP}")
        return None
    finally:
        state.mode = "idle"


# ------------------------------------------------------------ test moves --
def check_bounds(state, cfg, target):
    """Return an error string if target is outside servopos, else None."""
    lo = cfg.get("servopos.position_min")
    hi = cfg.get("servopos.position_max")
    for name, v, bad in (("min", lo, lambda t, b: t < b),
                         ("max", hi, lambda t, b: t > b)):
        try:
            b = float(v)
        except (TypeError, ValueError):
            continue
        if b != b:                       # nan means "no limit"
            continue
        if bad(target, b):
            return (f"target {target:+.4f} is outside "
                    f"servopos.position_{name} ({b:+.4f}).\n"
                    f"  The controller will fault 39 rather than move.\n"
                    f"  Fix: 'zero' here, or 'goto' back inside the range, "
                    f"or widen the limit.")
    return None


async def do_step(controller, state, delta, dwell=2.0):
    """Step response: jump by delta, record overshoot and settling."""
    if not await await_telemetry(state):
        print("no telemetry -- is the controller responding?")
        return None
    start = val(state.last, moteus.Register.POSITION)
    target = start + delta
    print(f"step {start:+.4f} -> {target:+.4f} rev "
          f"(kp_scale={state.kp_scale}, kd_scale={state.kd_scale})")

    state.estop = False
    state.position = start
    state.mode = "hold"
    await asyncio.sleep(0.5)

    state.log = []
    state.limit_seen = set()
    state.fault_seen = 0
    state.position = target
    state.mode = "goto"
    await asyncio.sleep(dwell)
    samples = state.log
    state.log = None
    seen = set(state.limit_seen)

    state.last_samples = samples
    if not samples:
        print("no samples captured")
        return None
    positions = [s[1] for s in samples]
    err = [p - target for p in positions]
    overshoot = (max(positions) - target if delta > 0
                 else target - min(positions))
    final = statistics.fmean(positions[-10:])
    band = abs(delta) * 0.02
    settle_t = None
    t0 = samples[0][0]
    for i, s in enumerate(samples):
        if all(abs(x - target) <= band for x in positions[i:]):
            settle_t = s[0] - t0
            break
    print(f"  overshoot   {overshoot:+.5f} rev "
          f"({100 * overshoot / abs(delta):+.1f}% of step)")
    print(f"  settle 2%   "
          f"{f'{settle_t:.2f}s' if settle_t is not None else 'did not settle'}")
    print(f"  final err   {final - target:+.5f} rev "
          f"({(final - target) * 360:+.2f} deg at output)")
    print(f"  peak |err|  {max(abs(e) for e in err):.5f} rev")
    torques = [s[3] for s in samples]
    peak_tq = max(abs(t) for t in torques)
    moved = max(positions) - min(positions)
    print(f"  peak torque {peak_tq:.4f} Nm (ceiling {state.max_torque} Nm)")
    if seen:
        print("  torque limited by: "
              + ", ".join(LIMIT_REASONS.get(x, str(x)) for x in sorted(seen)))
    if moved < abs(delta) * 0.05:
        print("\n  !! THE JOINT DID NOT MOVE.")
        if state.fault_seen:
            print(f"     FAULT {state.fault_seen} "
                  f"({FAULT_NAMES.get(state.fault_seen, '?')}) during the "
                  f"move -- the controller refused to drive.")
            if state.fault_seen == 39:
                print("     Position is outside servopos limits. "
                      "Use 'zero' or move back in range.")
        elif peak_tq >= state.max_torque * 0.95:
            print("     Torque hit your per-command ceiling. "
                  "Try: limit torque 3")
        else:
            print(f"     Commanded torque peaked at only {peak_tq:.4f} Nm --\n"
                  f"     too weak to break stiction through the gearbox.\n"
                  f"     Raise stiffness: kp 10   (then re-run the step)")
    ringing = sum(1 for a, b in zip(err, err[1:]) if a * b < 0)
    print(f"  zero xings  {ringing}"
          + ("   <- oscillating, raise kd" if ringing > 4 else ""))
    metrics = {"overshoot_pct": round(100 * overshoot / abs(delta), 2),
               "settle_s": round(settle_t, 3) if settle_t is not None else "",
               "final_err_deg": round((final - target) * 360, 4),
               "peak_torque_Nm": round(peak_tq, 4),
               "ringing": ringing,
               "moved_rev": round(moved, 5)}
    log_run(state, "step",
            {"delta_rev": delta, "dwell_s": dwell, "start_rev": round(start, 5)},
            metrics, samples)
    return {"overshoot_pct": metrics["overshoot_pct"],
            "settle": (f"{settle_t:.2f}" if settle_t is not None else "none"),
            "final_err_deg": metrics["final_err_deg"],
            "ringing": ringing}


def travel_time(state, distance):
    """Trapezoidal estimate: ramp up, cruise, ramp down, plus settle."""
    v, acc = max(state.vel_limit, 1e-6), max(state.accel_limit, 1e-6)
    d = abs(distance)
    if d <= v * v / acc:                 # never reaches cruise speed
        t = 2.0 * math.sqrt(d / acc)
    else:
        t = 2.0 * (v / acc) + (d - v * v / acc) / v
    return t + 0.75                      # settling margin


async def do_cycle(controller, state, a, b, n, dwell=None):
    """Repeatability: bounce between two targets, report landing spread."""
    if dwell is None:
        dwell = travel_time(state, b - a)
    print(f"cycling {a:+.4f} <-> {b:+.4f} rev "
          f"({abs(b - a) * 360:.0f} deg), {n} round trips")
    print(f"  dwell {dwell:.2f}s per leg "
          f"(vel<={state.vel_limit}, accel<={state.accel_limit})")
    est = 2 * n * dwell
    print(f"  estimated {est:.0f}s total\n")
    lands = {a: [], b: []}
    state.estop = False
    state.fault_seen = 0
    aborted = False
    for i in range(n):
        for tgt in (a, b):
            state.position = tgt
            state.mode = "goto"
            await asyncio.sleep(dwell)
            if state.fault_seen or state.estop:
                print(f"\n  ABORTED after {i} complete trip(s) -- "
                      f"{'fault ' + str(state.fault_seen) if state.fault_seen
                         else 'e-stopped'}.\n"
                      f"  Results below cover only the completed trips.")
                aborted = True
                break
            lands[tgt].append(val(state.last, moteus.Register.POSITION))
        if aborted:
            break
        print(f"  trip {i + 1}/{n}: "
              f"{lands[a][-1]:+.5f} / {lands[b][-1]:+.5f}")
    print()
    if not all(lands.values()):
        print("  no complete trips recorded -- nothing to report")
        return
    for tgt, vals in lands.items():
        if vals and abs(statistics.fmean(vals) - tgt) > abs(b - a) * 0.05:
            print(f"  !! target {tgt:+.4f}: mean landing is far off. Either "
                  f"the dwell is too short\n     for this distance, or the "
                  f"joint is hitting something. Try a longer dwell:\n"
                  f"     cycle {a} {b} {len(vals)} "
                  f"{travel_time(state, b - a) * 2:.1f}")
    for tgt, vals in lands.items():
        if len(vals) > 1:
            spread = max(vals) - min(vals)
            print(f"  target {tgt:+.4f}: mean err "
                  f"{statistics.fmean(v - tgt for v in vals):+.5f} rev, "
                  f"spread {spread:.5f} rev ({spread * 360:.2f} deg)")
    metrics = {}
    for tgt, vals in lands.items():
        if len(vals) > 1:
            tag = "neg" if tgt < 0 else "pos"
            metrics[f"{tag}_mean_err_rev"] = round(
                statistics.fmean(v - tgt for v in vals), 6)
            metrics[f"{tag}_spread_deg"] = round(
                (max(vals) - min(vals)) * 360, 4)
    if "neg_mean_err_rev" in metrics and "pos_mean_err_rev" in metrics:
        metrics["backlash_deg"] = round(
            abs(metrics["neg_mean_err_rev"] - metrics["pos_mean_err_rev"])
            * 360, 4)
        print(f"  implied backlash: {metrics['backlash_deg']:.3f} deg "
              f"(separation of the two biases)")
    log_run(state, "cycle",
            {"a_rev": a, "b_rev": b, "trips": n, "dwell_s": round(dwell, 2),
             "travel_deg": round(abs(b - a) * 360, 1)}, metrics)
    print("\n  Spread is repeatability. Mean error is bias (backlash/droop).")


def bounds_from_cfg(cfg, margin=0.02):
    """Usable travel from servopos, shrunk by a margin for overshoot."""
    def num(key, default):
        try:
            v = float(cfg.get(key))
            return default if v != v else v      # nan -> default
        except (TypeError, ValueError):
            return default
    lo = num("servopos.position_min", -0.25) + margin
    hi = num("servopos.position_max", 0.25) - margin
    return (lo, hi) if hi > lo else (None, None)


async def do_random(controller, state, n, cfg, seed=None, ref=None,
                    min_deg=5.0, max_deg=None):
    """Random point-to-point moves -- closer to how the arm really moves.

    Reports error against distance and against direction of approach, which
    is what a fixed A-B cycle cannot show you.
    """
    import random as _rnd
    if not await await_telemetry(state):
        print("no telemetry")
        return
    lo, hi = bounds_from_cfg(cfg)
    if lo is None:
        print("  soft limits leave no usable travel -- check servopos")
        return

    rng = _rnd.Random(seed)
    span_deg = (hi - lo) * 360
    max_deg = max_deg if max_deg is not None else span_deg
    print(f"random moves within {lo:+.3f}..{hi:+.3f} rev "
          f"({span_deg:.0f} deg of travel)")
    print(f"  {n} moves, {min_deg:.0f}-{min(max_deg, span_deg):.0f} deg each"
          + (f", seed {seed}" if seed is not None else "")
          + (f", returning to {ref:+.3f} between moves" if ref is not None
             else ""))

    state.estop = False
    state.fault_seen = 0
    cur = val(state.last, moteus.Register.POSITION)
    results = []
    ref_lands = []

    async def move_to(tgt):
        d = abs(tgt - state_pos())
        state.position = tgt
        state.mode = "goto"
        await asyncio.sleep(travel_time(state, d))
        return val(state.last, moteus.Register.POSITION)

    def state_pos():
        return val(state.last, moteus.Register.POSITION)

    t_start = time.monotonic()
    for i in range(n):
        for _ in range(40):                      # pick a valid target
            tgt = rng.uniform(lo, hi)
            dist_deg = abs(tgt - cur) * 360
            if min_deg <= dist_deg <= max_deg:
                break
        else:
            tgt = rng.uniform(lo, hi)
            dist_deg = abs(tgt - cur) * 360

        direction = "+" if tgt > cur else "-"
        landed = await move_to(tgt)
        if state.fault_seen or state.estop:
            print(f"\n  ABORTED at move {i + 1} -- fault "
                  f"{state.fault_seen or 'e-stop'}")
            break
        err_deg = (landed - tgt) * 360
        results.append({"i": i + 1, "target": tgt, "dist_deg": dist_deg,
                        "dir": direction, "err_deg": err_deg})
        print(f"  {i + 1:>3}. {direction} {dist_deg:>6.1f} deg -> "
              f"{tgt:+.4f}   err {err_deg:+.3f} deg")
        cur = landed

        if ref is not None:
            landed_ref = await move_to(ref)
            if state.fault_seen or state.estop:
                break
            ref_lands.append(landed_ref)
            cur = landed_ref

    if not results:
        print("  no moves completed")
        return

    errs = [r["err_deg"] for r in results]
    pos = [r["err_deg"] for r in results if r["dir"] == "+"]
    neg = [r["err_deg"] for r in results if r["dir"] == "-"]
    elapsed = time.monotonic() - t_start

    print(f"\n  moves            {len(results)} in {elapsed:.0f}s")
    print(f"  mean |error|     {statistics.fmean(abs(e) for e in errs):.4f} deg")
    print(f"  worst error      {max(errs, key=abs):+.4f} deg")
    if len(errs) > 1:
        print(f"  std deviation    {statistics.pstdev(errs):.4f} deg")
    if pos and neg:
        mp, mn = statistics.fmean(pos), statistics.fmean(neg)
        print(f"  approaching +    {mp:+.4f} deg mean  ({len(pos)} moves)")
        print(f"  approaching -    {mn:+.4f} deg mean  ({len(neg)} moves)")
        print(f"  direction split  {abs(mp - mn):.4f} deg "
              f"<- backlash seen as approach-dependent error")
    far = [r for r in results if r["dist_deg"] > statistics.fmean(
        x["dist_deg"] for x in results)]
    near = [r for r in results if r not in far]
    if far and near:
        print(f"  short moves      "
              f"{statistics.fmean(abs(r['err_deg']) for r in near):.4f} deg "
              f"mean |err|")
        print(f"  long moves       "
              f"{statistics.fmean(abs(r['err_deg']) for r in far):.4f} deg "
              f"mean |err|   <- if much worse, distance-dependent")
    metrics = {"moves": len(results),
               "mean_abs_err_deg": round(
                   statistics.fmean(abs(e) for e in errs), 4),
               "worst_err_deg": round(max(errs, key=abs), 4),
               "std_err_deg": round(statistics.pstdev(errs), 4)
               if len(errs) > 1 else 0.0,
               "elapsed_s": round(elapsed, 1)}
    if pos and neg:
        metrics["dir_split_deg"] = round(
            abs(statistics.fmean(pos) - statistics.fmean(neg)), 4)
    if len(ref_lands) > 1:
        spread = (max(ref_lands) - min(ref_lands)) * 360
        metrics["ref_spread_deg"] = round(spread, 4)
        metrics["ref_mean_err_deg"] = round(
            statistics.fmean(v - ref for v in ref_lands) * 360, 4)
        print(f"\n  reference point  {len(ref_lands)} returns, "
              f"spread {spread:.4f} deg")
        print("  (spread here is repeatability from RANDOM approach "
              "directions --\n   the number that matters for a vision-guided "
              "grasp)")
    log_run(state, "random",
            {"n": n, "seed": seed, "ref_rev": ref, "min_deg": min_deg,
             "max_deg": max_deg, "lo_rev": round(lo, 4),
             "hi_rev": round(hi, 4)}, metrics)


async def do_backlash(controller, state):
    """Hold, then report how far the output moves before position responds."""
    if not await await_telemetry(state):
        print("no telemetry")
        return
    state.estop = False
    state.position = val(state.last, moteus.Register.POSITION)
    state.mode = "hold"
    await asyncio.sleep(0.5)
    base = val(state.last, moteus.Register.POSITION)
    print("Holding. Push the OUTPUT gently one way, hold it, then release.\n"
          "Sampling for 8s -- watch how far it deflects per Nm.\n")
    state.log = []
    await asyncio.sleep(8.0)
    s = state.log
    state.log = None
    if not s:
        print("no samples")
        return
    dev = [(p - base, tq) for _, p, _, tq in s]
    loaded = [(d, t) for d, t in dev if abs(t) > 0.02]
    print(f"  max deflection  {max(abs(d) for d, _ in dev):.5f} rev "
          f"({max(abs(d) for d, _ in dev) * 360:.2f} deg)")
    print(f"  max torque      {max(abs(t) for _, t in dev):.3f} Nm")
    if loaded:
        stiff = statistics.fmean(abs(t) / max(abs(d), 1e-9)
                                 for d, t in loaded)
        print(f"  approx stiffness {stiff:.2f} Nm per output rev "
              f"({stiff / 360:.4f} Nm/deg)")
    print(f"  returned to     {dev[-1][0]:+.5f} rev from start "
          f"({dev[-1][0] * 360:+.2f} deg)")
    log_run(state, "backlash", {"sample_s": 8.0},
            {"max_deflection_deg": round(max(abs(d) for d, _ in dev) * 360, 4),
             "max_torque_Nm": round(max(abs(t) for _, t in dev), 4),
             "residual_deg": round(dev[-1][0] * 360, 4)}, s)
    print("\n  Residual offset after release ~= backlash + stiction.")


# --------------------------------------------------------------- logging --
def log_run(state, kind, params, metrics, samples=None, note=None):
    """Record a test with enough context to be meaningful months later.

    Writes three things into the log directory:
      <stamp>_j<id>_<kind>.json   metrics + the exact conditions
      <stamp>_j<id>_<kind>.csv    raw samples, if any
      j<id>_history.csv           one row per run, for plotting trends
    """
    import csv as _csv
    import json
    import datetime

    note = state.note if note is None else note
    d = Path(state.log_dir)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    base = d / f"{stamp}_j{state.joint_id}_{kind}"

    record = {
        "timestamp": now.isoformat(timespec="seconds"),
        "joint_id": state.joint_id,
        "test": kind,
        "note": note,
        "conditions": {
            "kp_scale": state.kp_scale,
            "kd_scale": state.kd_scale,
            "ilimit_scale": state.ilimit_scale,
            "max_torque": state.max_torque,
            "vel_limit": state.vel_limit,
            "accel_limit": state.accel_limit,
            "configured": {k: v for k, v in (state.cfg or {}).items()
                           if k.startswith(("servo.pid", "servopos",
                                            "motor_position"))},
        },
        "params": params,
        "metrics": metrics,
    }
    base.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")

    if samples:
        write_csv(str(base.with_suffix(".csv")), samples, note=stamp,
                  quiet=True)

    hist = d / f"j{state.joint_id}_history.csv"
    row = {"timestamp": record["timestamp"], "test": kind, "note": note,
           "kp_scale": state.kp_scale, "kd_scale": state.kd_scale,
           "vel_limit": state.vel_limit, "accel_limit": state.accel_limit}
    row.update({k: v for k, v in params.items()})
    row.update({k: v for k, v in metrics.items()
                if isinstance(v, (int, float, str))})
    exists = hist.exists()
    prior = []
    if exists:
        with open(hist, newline="") as f:
            prior = list(_csv.DictReader(f))
    cols = list(dict.fromkeys(
        [c for r in prior for c in r] + list(row)))
    with open(hist, "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in prior:
            w.writerow(r)
        w.writerow(row)
    print(f"  logged -> {base.name}.json  (history: {hist.name})")
    return base


def write_csv(path, samples, note="", quiet=False):
    if not samples:
        print("nothing to write")
        return
    t0 = samples[0][0]
    with open(path, "w", newline="") as f:
        if note:
            f.write(f"# {note}\n")
        f.write("t_s,position_rev,velocity_rev_s,torque_Nm\n")
        for t, pos, vel, tq in samples:
            f.write(f"{t - t0:.4f},{pos:.6f},{vel:.6f},{tq:.6f}\n")
    if not quiet:
        print(f"wrote {len(samples)} samples -> {path}")


async def do_sweep(controller, state, which, values, delta, dwell=2.0,
                   cfg=None):
    """Run the same step at several gain scales from a FIXED base position.

    Every run starts from the same place and returns there afterwards, so a
    long sweep cannot march the joint out of its travel.
    """
    if not await await_telemetry(state):
        print("no telemetry")
        return
    base = val(state.last, moteus.Register.POSITION)
    err = (check_bounds(state, cfg or {}, base + delta) or
           check_bounds(state, cfg or {}, base))
    if err:
        print("  " + err)
        return
    print(f"sweeping {which}_scale over {values} with step {delta} rev")
    print(f"base position {base:+.4f} rev; returning here between runs\n")
    rows = []
    saved = (state.kp_scale, state.kd_scale)
    for v in values:
        if which == "kp":
            state.kp_scale = v
        else:
            state.kd_scale = v
        print(f"--- {which}_scale = {v} ---")
        stats = await do_step(controller, state, delta, dwell)
        if stats:
            rows.append((v, stats))
        # return to base so the next run starts from the same place
        if not (state.fault_seen or state.estop):
            state.position = base
            state.mode = "goto"
            await asyncio.sleep(max(1.0, dwell * 0.6))
        if state.fault_seen or state.estop:
            print(f"\n  ABORTING SWEEP -- "
                  f"{'fault ' + str(state.fault_seen) if state.fault_seen else 'e-stopped'}. "
                  f"Fix the cause and re-run; repeating would just "
                  f"produce the same failure {len(values)} times.")
            break
        await asyncio.sleep(0.3)
    state.kp_scale, state.kd_scale = saved
    if rows:
        print(f"\n  {which}_scale   overshoot%   settle_s   final_err_deg   "
              f"ringing")
        for v, st in rows:
            print(f"  {v:>9}   {st['overshoot_pct']:>9.1f}   "
                  f"{st['settle']:>8}   {st['final_err_deg']:>13.3f}   "
                  f"{st['ringing']:>7}")
        print("\n  Want: low overshoot, short settle, few crossings.")
    print(f"  scales restored to kp={state.kp_scale} kd={state.kd_scale}")


# --------------------------------------------------- non-blocking stdin ---
def start_stdin_reader(loop, queue):
    def reader():
        for line in sys.stdin:
            loop.call_soon_threadsafe(queue.put_nowait, line.rstrip("\n"))
        loop.call_soon_threadsafe(queue.put_nowait, None)
    threading.Thread(target=reader, daemon=True).start()


HELP = """
 STOPPING
  <ENTER>        *** E-STOP ***          arm            re-enable motion
  stop           e-stop                  quit           stop and exit

 MOVING
  hold                        servo to current position
  goto <pos>                  absolute move (output revolutions)
  vel <v>                     constant velocity
  torque <nm>                 feedforward only, gains zeroed -- goes limp
  zero                        call current position 0.0

 LIVE GAINS (registers -- instant, nothing written to the board)
  kp <scale>    kd <scale>    ilim <scale>   multiply configured gain
                              (no ki_scale exists; use 'set' for ki)
  gains                       show scales and resulting effective gains
  save [--flash]              bake current scales into config, reset to 1.0

 LIMITS
  limit torque|vel|accel <v>  per-command ceilings (this session only)
  limits                      show cached config limits
  refresh                     re-read the full config from the board
  history [test]              past runs from the log (cycle/step/backlash)
  set <key> <value> [--flash] write a config parameter (needs the port)

 TEST RUNS
  step <delta> [dwell]        step response: overshoot, settling, ringing
  cycle <a> <b> <n> [dwell]   repeatability between two targets
                              (dwell auto-scales with distance)
  random <n> [--seed s] [--ref p] [--min deg] [--max deg]
                              random point-to-point moves; reports error
                              vs distance and vs approach direction
  backlash                    push-by-hand compliance/backlash measurement
  watch [hz]                  live telemetry (ENTER stops and e-stops)
  status                      one telemetry line
  sweep kp|kd <v>... [--step d]   run a step at each scale, tabulate
  csv [file]                  extra copy of last samples (tests auto-log)
  ratio [turns]               measure the TRUE gear reduction by hand
  wdtest                      prove the watchdog stops the joint

 SCRIPTING
  wait <s>                    pause (useful in scripts)
  echo <text>                 print a marker
  Run non-interactively:
    python joint_console.py --id 1 --script tune.txt
    python joint_console.py --id 1 -c "limits" -c "step 0.02" -c "csv a.csv"
"""


async def console_loop(controller, state, target_id,
                       preload=None, batch=False, startup_cfg=None,
                       pending_out=None):
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    scripted = len(preload or [])
    for line in (preload or []):
        queue.put_nowait(line)
    if batch:
        queue.put_nowait(None)          # exit once the script is consumed
        print(f"batch mode: {scripted} command(s)\n")
    else:
        start_stdin_reader(loop, queue)
        if scripted:
            print(f"running {scripted} command(s), then staying at the "
                  f"prompt ('help' for commands, 'quit' to exit)\n")
        else:
            print(HELP)
    cfg_cache = dict(startup_cfg or {})
    pending = {}
    echo_left = [scripted]
    await await_telemetry(state, timeout=3.0, quiet=True)

    while not state.quit:
        print("joint> ", end="", flush=True)
        line = await queue.get()
        if line is not None and echo_left[0] > 0:
            print(line)
            echo_left[0] -= 1
        if line is None:
            await do_estop(controller, state, "stdin closed")
            state.quit = True
            break
        if line.strip() == "":
            await do_estop(controller, state)
            continue

        args = shlex.split(line.strip())
        cmd, rest = args[0].lower(), args[1:]
        flash = "--flash" in rest
        rest = [r for r in rest if r != "--flash"]

        try:
            if cmd in ("quit", "exit"):
                await do_estop(controller, state, "exiting")
                if pending_out is not None:
                    pending_out.update(pending)
                state.quit = True

            elif cmd == "help":
                print(HELP)

            elif cmd == "arm":
                state.estop = False
                print("armed")

            elif cmd == "status":
                print(fmt_status(state.last))

            elif cmd == "gains":
                print(f"  kp_scale     {state.kp_scale}")
                print(f"  kd_scale     {state.kd_scale}")
                print(f"  ilimit_scale {state.ilimit_scale}")
                if cfg_cache:
                    for k, s in (("kp", state.kp_scale), ("kd", state.kd_scale)):
                        base = cfg_cache.get(f"servo.pid_position.{k}")
                        if base:
                            print(f"  effective {k} = {float(base)} x {s} "
                                  f"= {float(base) * s:.4f}")
                else:
                    print("  (run 'limits' to read configured gains)")

            elif cmd in ("kp", "kd", "ilim", "ki"):
                if cmd == "ki":
                    print("  NOTE: there is no ki_scale in the moteus "
                          "position command.\n"
                          "  This scales servo.pid_position.ILIMIT. To change "
                          "ki itself use:\n"
                          "    set servo.pid_position.ki <value> --flash")
                s = float(rest[0])
                if s < 0:
                    print("scale must be >= 0")
                    continue
                if cmd == "kp":
                    state.kp_scale = s
                elif cmd == "kd":
                    state.kd_scale = s
                else:
                    state.ilimit_scale = s
                base = cfg_cache.get(f"servo.pid_position."
                                     f"{'ilimit' if cmd in ('ilim', 'ki') else cmd}")
                if base is not None and float(base) == 0.0:
                    print(f"  !! the configured value is 0, so scaling it "
                          f"does nothing.\n"
                          f"     Set a real value first with 'set'.")
                print(f"  kp x{state.kp_scale}  kd x{state.kd_scale}  "
                      f"ilimit x{state.ilimit_scale}   (live)")

            elif cmd == "save":
                if not cfg_cache:
                    print("run 'limits' first so I know the configured gains")
                    continue
                new = {}
                for k, s in (("kp", state.kp_scale), ("kd", state.kd_scale),
                             ("ilimit", state.ilimit_scale)):
                    key = f"servo.pid_position.{k}"
                    if key in cfg_cache:
                        # Write ALL gains, not just changed ones. Writing an
                        # unchanged value is harmless; omitting one produced
                        # a half-saved tune that looked successful.
                        new[key] = round(float(cfg_cache[key]) * s, 6)
                if not new:
                    print("no gains in the cached config -- run 'refresh'")
                    continue
                if (state.kp_scale == state.kd_scale ==
                        state.ilimit_scale == 1.0):
                    print("  (all scales are 1.0 -- writing current values "
                          "back unchanged)")
                pending.update(new)
                pending["__flash__"] = flash
                cfg_cache.update({k: str(v) for k, v in new.items()})
                state.kp_scale = state.kd_scale = state.ilimit_scale = 1.0
                print("queued: " + ", ".join(f"{k}={v}"
                                             for k, v in new.items()))
                print("  scales reset to 1.0; written when you 'quit'"
                      + ("  (to flash)" if flash else "  (volatile)"))

            elif cmd == "history":
                import csv as _csv
                h = Path(state.log_dir) / f"j{state.joint_id}_history.csv"
                if not h.exists():
                    print(f"  no runs logged yet in {h}")
                    continue
                want = rest[0] if rest else None
                with open(h, newline="") as f:
                    rows = [r for r in _csv.DictReader(f)
                            if not want or r.get("test") == want]
                if not rows:
                    print("  no matching runs")
                    continue
                keys = ["timestamp", "test", "travel_deg", "neg_spread_deg",
                        "pos_spread_deg", "backlash_deg", "overshoot_pct",
                        "settle_s", "note"]
                keys = [k for k in keys if any(r.get(k) for r in rows)]
                print("  " + "  ".join(f"{k:>16}" for k in keys))
                for r in rows[-15:]:
                    print("  " + "  ".join(
                        f"{str(r.get(k, ''))[:16]:>16}" for k in keys))
                print(f"\n  {len(rows)} run(s) in {h.name}")

            elif cmd == "refresh":
                cfg = await with_port_released(
                    controller, state, lambda: tool_dump(target_id))
                if cfg:
                    cfg_cache.update(cfg)
                    print(f"re-read {len(cfg)} parameters from the board")

            elif cmd == "limits":
                if not cfg_cache:
                    print("  config was not read at startup (moteus_tool "
                          "could not run). Use the setup script.")
                for k in CONFIG_LIMITS:
                    if k in cfg_cache:
                        print(f"  {k:<38} {cfg_cache[k]}")
                if pending:
                    print("\n  queued for write on exit:")
                    for k, v in pending.items():
                        print(f"    {k:<36} {v}")

            elif cmd == "set" and len(rest) == 2:
                key, value = rest[0], rest[1]
                if key not in CONFIG_LIMITS:
                    print(f"'{key}' is not in the known-safe list. Use the "
                          "setup script for arbitrary parameters.")
                    continue
                bounds = CONFIG_LIMITS[key]
                if bounds is not None:
                    try:
                        f = float(value)
                    except ValueError:
                        print("value must be a number")
                        continue
                    lo, hi = bounds
                    if not (lo <= f <= hi):
                        print(f"refusing: {key} outside safe range "
                              f"[{lo}, {hi}]")
                        continue
                pending[key] = value
                pending["__flash__"] = pending.get("__flash__", False) or flash
                cfg_cache[key] = value
                print(f"queued {key} = {value} -- written when you 'quit'"
                      + ("  (to flash)" if flash else "  (volatile)"))
                if key.startswith("servopos."):
                    print("  NOTE: this limit is NOT enforced by the "
                          "controller until it is written.\n"
                          "  Until you quit, only this console's own checks "
                          "protect you.")

            elif cmd in ("hold", "goto", "vel", "torque", "step", "cycle",
                         "backlash") and state.estop:
                print("e-stopped -- type 'arm' first")

            elif cmd == "hold":
                if not await await_telemetry(state):
                    print("no telemetry")
                    continue
                state.position = val(state.last, moteus.Register.POSITION)
                state.mode = "hold"
                print(f"holding {state.position:+.4f} rev")

            elif cmd == "goto":
                _err = check_bounds(state, cfg_cache, float(rest[0]))
                if _err:
                    print("  " + _err)
                    continue
                state.position = float(rest[0])
                state.mode = "goto"
                print(f"-> {state.position:+.4f} rev")

            elif cmd == "vel":
                state.velocity = float(rest[0])
                state.mode = "vel"
                print(f"velocity {state.velocity:+.4f} rev/s")

            elif cmd == "torque":
                state.torque = float(rest[0])
                state.mode = "torque"
                print(f"feedforward {state.torque:+.3f} Nm -- joint is limp")

            elif cmd == "step":
                _t = val(state.last, moteus.Register.POSITION) + \
                    float(rest[0])
                _err = check_bounds(state, cfg_cache, _t)
                if _err:
                    print("  " + _err)
                    continue
                await do_step(controller, state, float(rest[0]),
                              float(rest[1]) if len(rest) > 1 else 2.0)

            elif cmd == "cycle":
                if not await await_telemetry(state):
                    print("no telemetry")
                    continue
                _err = (check_bounds(state, cfg_cache, float(rest[0])) or
                        check_bounds(state, cfg_cache, float(rest[1])))
                if _err:
                    print("  " + _err)
                    continue
                await do_cycle(controller, state, float(rest[0]),
                               float(rest[1]),
                               int(rest[2]) if len(rest) > 2 else 5,
                               float(rest[3]) if len(rest) > 3 else None)

            elif cmd == "random":
                _n = int(rest[0]) if rest else 10
                _kw = {}
                _it = iter(rest[1:])
                for tok in _it:
                    if tok in ("--seed", "--ref", "--min", "--max"):
                        _kw[tok[2:]] = float(next(_it))
                await do_random(
                    controller, state, _n, cfg_cache,
                    seed=int(_kw["seed"]) if "seed" in _kw else None,
                    ref=_kw.get("ref"),
                    min_deg=_kw.get("min", 5.0),
                    max_deg=_kw.get("max"))

            elif cmd == "backlash":
                await do_backlash(controller, state)

            elif cmd == "ratio":
                # Measure the TRUE reduction by back-driving the output.
                # No motion is commanded; we just read the encoder.
                cfgr = cfg_cache.get(
                    "motor_position.rotor_to_output_ratio", "1")
                try:
                    configured = 1.0 / float(cfgr)
                except (ValueError, ZeroDivisionError):
                    configured = float("nan")
                turns = float(rest[0]) if rest else 1.0
                await do_estop(controller, state, "motor off for measurement")
                await asyncio.sleep(0.3)
                if not await await_telemetry(state):
                    print("no telemetry")
                    continue
                p0 = val(state.last, moteus.Register.POSITION)
                print(f"\n  configured reduction: {configured:.4g}:1")
                print("  NOTE: hand-rotating changes the reported position "
                      "and can push it\n  outside servopos limits. Run "
                      "'zero' afterwards.")
                print(f"  motor is OFF. Rotate the OUTPUT shaft exactly "
                      f"{turns:g} full turn(s) by hand,")
                print("  as accurately as you can, then press ENTER.")
                await queue.get()
                p1 = val(state.last, moteus.Register.POSITION)
                moved = abs(p1 - p0)
                if moved < 1e-6:
                    print("  position did not change -- did the output move?")
                    continue
                # position is reported in configured-output units, so the
                # true reduction = configured * (units seen / turns asked)
                measured = configured * moved / turns
                print(f"\n  encoder moved   {moved:.4f} configured-output rev")
                print(f"  TRUE reduction  {measured:.3f} : 1")
                print(f"  configured      {configured:.3f} : 1")
                err = measured / configured if configured else float("nan")
                if abs(err - 1.0) < 0.05:
                    print("  => configuration matches the hardware.")
                else:
                    correct = round(1.0 / measured, 7)
                    print(f"  => MISMATCH by {err:.3f}x. Real travel is "
                          f"{err:.2f}x what you command.")
                    print(f"     Fix with:")
                    print(f"       set motor_position.rotor_to_output_ratio "
                          f"{correct} --flash")
                    print(f"     Then re-check servopos limits and re-tune "
                          f"(gains scale with ratio squared).")

            elif cmd == "sweep":
                which = rest[0].lower()
                if which not in ("kp", "kd"):
                    print("sweep kp|kd <v1> <v2> ... [--step <delta>]")
                    continue
                delta, vals = 0.02, []
                it = iter(rest[1:])
                for tok in it:
                    if tok == "--step":
                        delta = float(next(it))
                    else:
                        vals.append(float(tok))
                if not vals:
                    print("give at least one scale value")
                    continue
                await do_sweep(controller, state, which, vals, delta,
                               cfg=cfg_cache)

            elif cmd == "csv":
                write_csv(rest[0] if rest else "run.csv",
                          state.last_samples,
                          f"kp_scale={state.kp_scale} "
                          f"kd_scale={state.kd_scale}")

            elif cmd == "wait":
                await asyncio.sleep(float(rest[0]) if rest else 1.0)

            elif cmd == "echo":
                print(" ".join(rest))

            elif cmd == "stop":
                await do_estop(controller, state)

            elif cmd == "zero":
                await do_estop(controller, state, "zeroing")
                await controller.set_output_exact(position=0.0)
                print("position is now 0.0")

            elif cmd == "limit" and len(rest) == 2:
                v = float(rest[1])
                setattr(state, {"torque": "max_torque", "vel": "vel_limit",
                                "accel": "accel_limit"}[rest[0]], v)
                print(f"tq={state.max_torque} vel={state.vel_limit} "
                      f"accel={state.accel_limit}")

            elif cmd == "watch":
                hz = float(rest[0]) if rest else 5.0
                print("streaming -- ENTER stops and e-stops")
                while queue.empty():
                    print("\r" + fmt_status(state.last) + "  ",
                          end="", flush=True)
                    await asyncio.sleep(1.0 / hz)
                await queue.get()
                print()
                await do_estop(controller, state)

            elif cmd == "wdtest":
                if not await await_telemetry(state):
                    print("no telemetry yet")
                    continue
                print("hold, then TRUE silence, then look.\n")
                fired = None
                for quiet in (0.25, 0.5, 1.0, 2.0, 5.0):
                    state.position = val(state.last, moteus.Register.POSITION)
                    state.estop = False
                    state.mode = "hold"
                    await asyncio.sleep(0.6)
                    state.mode = "silent_test"
                    await asyncio.sleep(quiet)
                    r = await controller.query()
                    m = int(val(r, moteus.Register.MODE, -1))
                    left = m != 10
                    print(f"  silent {quiet:>4.2f}s -> "
                          f"mode={MODE_NAMES.get(m, m)}"
                          f"{'   <-- fired' if left else ''}")
                    if left:
                        fired = quiet
                        break
                state.mode = "idle"
                await do_estop(controller, state, "watchdog test done")
                print(f"\nPASS: stops after ~{fired}s of silence." if fired
                      else "\nFAIL: still driving after 5s. Check "
                           "servo.default_timeout_s.")

            else:
                print(f"unknown: {cmd}   (try 'help')")

        except (ValueError, IndexError, KeyError):
            print("bad arguments -- try 'help'")
        except Exception as e:                               # noqa: BLE001
            print(f"error: {e}")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, default=1)
    p.add_argument("-c", "--cmd", action="append", default=[],
                   help="run a console command then exit (repeatable)")
    p.add_argument("--script", metavar="FILE",
                   help="run console commands from a file, then exit")
    p.add_argument("--exit", dest="exit_after", action="store_true",
                   help="with --script/--cmd, exit when the commands finish "
                        "(default is to stay at the prompt)")
    p.add_argument("--interactive", action="store_true",
                   help="(default; kept for compatibility)")
    p.add_argument("--logs", default="logs", metavar="DIR",
                   help="where test records go (default: ./logs)")
    p.add_argument("--note", default="",
                   help="label attached to every run this session, "
                        "e.g. --note \"after 2h burn-in\"")
    p.add_argument("--refresh", action="store_true",
                   help="re-read the full config from the board at startup")
    moteus.make_transport_args(p)
    args = p.parse_args()

    preload = list(args.cmd)
    if args.script:
        for raw in Path(args.script).read_text().splitlines():
            raw = raw.split("#", 1)[0].strip()
            if raw:
                preload.append(raw)
    batch = bool(preload) and args.exit_after

    startup_cfg = None if args.refresh else fast_config(args.id)
    if startup_cfg is None:
        try:
            print("reading full config from the board (slow; run "
                  "'setup.py --id N --sync' once to speed this up)...")
            startup_cfg = tool_dump(args.id)
            print(f"read {len(startup_cfg)} parameters")
        except Exception as e:                               # noqa: BLE001
            print(f"could not read config ({e}); "
                  "'limits'/'save' will be unavailable")
            startup_cfg = {}

    transport = moteus.get_singleton_transport(args)
    controller = moteus.Controller(id=args.id, transport=transport)
    state = JointState()
    state.joint_id = args.id
    state.log_dir = args.logs
    state.cfg = dict(startup_cfg or {})
    state.note = args.note
    print(f"logging test records to {Path(args.logs).resolve()}")
    await controller.set_stop()

    def on_signal():
        state.quit = True
        asyncio.ensure_future(do_estop(controller, state, "signal"))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal)
        except (NotImplementedError, AttributeError):
            pass

    pending_out = main.pending
    main.transport = transport
    ctrl = asyncio.ensure_future(control_loop(controller, state))
    try:
        await console_loop(controller, state, args.id,
                           preload=preload, batch=batch,
                           startup_cfg=startup_cfg, pending_out=pending_out)
    except KeyboardInterrupt:
        pass
    finally:
        state.quit = True
        try:
            await asyncio.wait_for(ctrl, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        try:
            await controller.set_stop()
        except Exception:                                    # noqa: BLE001
            pass
        print("motor stopped, bye")


if __name__ == "__main__":
    main.pending = {}
    main.transport = None
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
    # The transport is closed now, so moteus_tool can have the port.
    pend = {k: v for k, v in main.pending.items() if k != "__flash__"}
    if pend:
        flash = main.pending.get("__flash__", False)
        print(f"\nwriting {len(pend)} queued setting(s)"
              + (" to flash..." if flash else " (volatile)..."))
        try:
            import argparse as _a
            _p = _a.ArgumentParser(); _p.add_argument("--id", type=int,
                                                      default=1)
            tid = _p.parse_known_args()[0].id
            release_transport(getattr(main, "transport", None), verbose=True)
            time.sleep(0.5)
            tool_set_with_retry(tid, pend, flash,
                                getattr(main, "transport", None))
            after = tool_dump(tid)
            for k, v in pend.items():
                ok = k in after and abs(float(after[k]) - float(v)) < 1e-6
                print(f"  {'ok  ' if ok else 'FAIL'} {k:<40} "
                      f"{after.get(k)}")
        except Exception as e:                               # noqa: BLE001
            print(f"  write failed: {e}")
            print("  values to set by hand:")
            for k, v in pend.items():
                print(f"    python setup.py --id 1 --set {k} {v}")
