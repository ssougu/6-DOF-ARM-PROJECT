#!/usr/bin/env python3
"""
joint_setup.py -- calibrate + configure a moteus joint. No tview required.

    python joint_setup.py --id 1 --dump              # read config off the board
    python joint_setup.py --id 1 --check             # calibrated? what's set?
    python joint_setup.py --id 1 --apply             # write profile + verify
    python joint_setup.py --id 1 --backup mine.cfg   # save current config
    python joint_setup.py --id 1 --calibrate         # MOTOR MUST SPIN FREELY

All config I/O goes through `moteus_tool --dump-config` / `--write-config`,
which run as separate processes with their own transport. This avoids the
in-process moteus.Stream path, which does not work on every setup.

>>> BEFORE --calibrate <<<
Calibration spins the rotor in both directions at high speed. It needs the
output FREE -- bare motor, or gearbox output disconnected. A joint with hard
stops will slam into them. Calibration data lives on the board permanently,
so this is once per controller. If --check says CALIBRATED, skip it.
"""

import argparse
import asyncio
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import moteus

# --------------------------------------------------------------------------
GEAR_RATIO = 15.0          # 5:1 x 3:1 planetary
JOINT_MIN_REV = -0.25      # soft limits, OUTPUT revolutions (0.25 = 90 deg)
JOINT_MAX_REV = 0.25

# PID gains are referenced to the OUTPUT of the reducer, so equivalent
# stiffness needs gains scaled by the SQUARE of the reduction (15^2 = 225).
# These are starting points for the tuning procedure, not final answers.
_K = GEAR_RATIO ** 2

PROFILE = {
    "motor_position.rotor_to_output_ratio": round(1.0 / GEAR_RATIO, 7),

    "servopos.position_min": JOINT_MIN_REV,
    "servopos.position_max": JOINT_MAX_REV,

    "servo.default_velocity_limit": 0.25,      # output rev/s
    "servo.default_accel_limit": 1.0,          # output rev/s^2

    "servo.max_current_A": 10.0,
    "servo.max_power_W": 100.0,

    # mains supply cannot sink regen -- dissipate it in the windings instead
    "servo.max_regen_power_W": 10.0,
    "servo.flux_brake_margin_voltage": 4.0,

    # THE SAFETY ONE: stop driving if the host goes quiet
    "servo.default_timeout_s": 0.25,

    # TUNED on the bench for J1 base yaw (see notes below), not guessed.
    # Measured: 1.6% overshoot, 0.17s settle, 1 zero crossing on a 0.05 rev
    # step with accel_limit 5, vel_limit 1, torque ceiling 1.5 Nm.
    "servo.pid_position.kp": 225.0,      # = 11.25 x kp_scale 20
    "servo.pid_position.kd": 4.5,        # = 0.1125 x kd_scale 40
    "servo.pid_position.ki": 0.0,
    "servo.pid_position.ilimit": 0.0,
}

TOOL = [sys.executable, "-m", "moteus.moteus_tool"]

# If profile_<id>.json exists next to this script it OVERRIDES the dict above.
# Create it with --sync after you tune, and the file can never go stale again.
PROFILE_FILE = "profile_{id}.json"


def load_profile(target):
    import json
    path = Path(__file__).parent / PROFILE_FILE.format(id=target)
    if path.exists():
        data = json.loads(path.read_text())
        print(f"using tuned profile: {path.name} "
              f"({len(data)} parameters)")
        return data, path
    return dict(PROFILE), path


def save_profile(target, values):
    import json
    path = Path(__file__).parent / PROFILE_FILE.format(id=target)
    path.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(values)} parameters -> {path.name}")
    return path


# ------------------------------------------------------------ moteus_tool --
def run_tool(target, *args, capture=True):
    cmd = TOOL + ["--target", str(target)] + list(args)
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() if capture else ""
        raise RuntimeError(
            f"moteus_tool failed (exit {proc.returncode}): {' '.join(cmd)}\n"
            f"{err}")
    return proc.stdout if capture else ""


def parse_config(text):
    """Accept either 'key value' or 'conf set key value' per line."""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("OK", "ERR")):
            continue
        parts = line.split()
        if parts[0] == "conf":
            # 'conf set K V' carries a value; 'conf write' and friends do not.
            if len(parts) >= 4 and parts[1] == "set":
                out[parts[2]] = parts[3]
            continue
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def dump_config(target):
    return parse_config(run_tool(target, "--dump-config"))


def write_config(target, settings, persist=True):
    """Send 'conf set' lines through moteus_tool --write-config."""
    lines = [f"conf set {k} {v}" for k, v in settings.items()]
    if persist:
        lines.append("conf write")
    body = "\n".join(lines) + "\n"

    tmp = Path(tempfile.gettempdir()) / "moteus_joint_profile.cfg"
    tmp.write_text(body)
    print(f"writing {len(settings)} settings via moteus_tool "
          f"({tmp})...")
    run_tool(target, "--write-config", str(tmp), capture=False)
    return tmp


def same(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


# ------------------------------------------------------------- operations --
def cmd_dump(target, prefix, path=None):
    conf = dump_config(target)
    sel = {k: v for k, v in conf.items() if k.startswith(prefix)}
    for k, v in sorted(sel.items()):
        print(f"{k:<48} {v}")
    print(f"\n({len(sel)} of {len(conf)} parameters)")
    if path:
        Path(path).write_text(
            "\n".join(f"conf set {k} {v}" for k, v in sorted(conf.items()))
            + "\nconf write\n")
        print(f"saved full config -> {path}")
    return conf


def cmd_check(target):
    profile, _ = load_profile(target)
    conf = dump_config(target)
    if not conf:
        print("moteus_tool returned no config. Is the id right?")
        return False

    motor = {k: v for k, v in conf.items() if k.startswith("motor.")}

    # Collapse indexed arrays (cogging tables, per-pole offsets) into one
    # summary line each -- otherwise this prints a thousand zeros.
    import re
    scalars, arrays = {}, {}
    for k, v in motor.items():
        m = re.match(r"^(.*)\.\d+$", k)
        if m:
            arrays.setdefault(m.group(1), []).append(v)
        else:
            scalars[k] = v

    print("motor configuration on this controller:")
    for k, v in sorted(scalars.items()):
        print(f"  {k:<40} {v}")
    for k, vals in sorted(arrays.items()):
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except ValueError:
                pass
        nz = sum(1 for n in nums if abs(n) > 1e-12)
        if nums and nz:
            print(f"  {k + '[' + str(len(vals)) + ']':<40} "
                  f"{nz} non-zero, range {min(nums):.4g} .. {max(nums):.4g}")
        else:
            print(f"  {k + '[' + str(len(vals)) + ']':<40} all zero")

    def nz(sub):
        for k, v in motor.items():
            if sub in k:
                try:
                    return abs(float(v)) > 1e-12
                except ValueError:
                    return bool(v)
        return None

    print()
    verdicts = {}
    for label, sub in (("pole count", "poles"),
                       ("winding resistance", "resistance"),
                       ("Kv / v_per_hz", "v_per_hz")):
        verdicts[label] = nz(sub)
        print(f"  {label:<22} "
              f"{ {True: 'set', False: 'ZERO', None: 'not present'}[nz(sub)] }")

    cal = all(v is True for v in verdicts.values() if v is not None)
    print("\n=> " + ("CALIBRATED -- do not run --calibrate, do not take the "
                     "gearbox apart." if cal else
                     "NOT calibrated. Read the notes at the top of this file."))

    print("\nprofile parameters, current vs desired:")
    drift = 0
    gains_differ = []
    for k, want in profile.items():
        have = conf.get(k)
        if have is None:
            print(f"  ABSENT   {k:<44} (not on this firmware)")
            drift += 1
        elif same(have, want):
            print(f"  ok       {k:<44} {have}")
        else:
            print(f"  DIFFERS  {k:<44} {have}  ->  {want}")
            drift += 1
            if k.startswith("servo.pid_position."):
                gains_differ.append(k)
    if gains_differ:
        print("\n  !! PID GAINS DIFFER FROM THE PROFILE.")
        print("     If you tuned on the bench, the BOARD is right and this\n"
              "     file is stale -- copy the board's values into PROFILE\n"
              "     before running --apply, or --apply will overwrite your\n"
              "     tuning with these defaults.")
    print(f"\n{drift} parameter(s) differ."
          + ("" if gains_differ else " Run --apply to fix."))
    return cal


def cmd_apply(target, persist):
    profile, _ = load_profile(target)
    before = dump_config(target)
    unknown = [k for k in profile if k not in before]
    if unknown:
        print("These names are not in this firmware's config tree and will "
              "be skipped:")
        for k in unknown:
            print(f"  {k}")
        print("(run --dump to find the correct names)\n")

    settings = {k: v for k, v in profile.items() if k in before}
    if not settings:
        print("nothing to write")
        return False

    clobber = [k for k in settings
               if k.startswith("servo.pid_position.")
               and k in before and not same(before[k], settings[k])]
    if clobber:
        print("This will OVERWRITE tuned PID gains on the board:")
        for k in clobber:
            print(f"  {k:<40} {before[k]}  ->  {settings[k]}")
        if input("type OVERWRITE to continue: ").strip() != "OVERWRITE":
            print("aborted -- copy the board's values into PROFILE first")
            return False

    write_config(target, settings, persist=persist)

    after = dump_config(target)
    print("\nverifying:")
    bad = 0
    for k, want in settings.items():
        have = after.get(k)
        ok = have is not None and same(have, want)
        print(f"  {'ok  ' if ok else 'FAIL'} {k:<44} {have}")
        bad += not ok
    if bad:
        retry = {k: v for k, v in settings.items()
                 if not (after.get(k) is not None and same(after[k], v))}
        print(f"\n{bad} did not stick -- retrying individually...")
        for k, v in retry.items():
            write_config(target, {k: v}, persist=persist)
        final = dump_config(target)
        still = 0
        for k, v in retry.items():
            have = final.get(k)
            ok = have is not None and same(have, v)
            print(f"  {'ok  ' if ok else 'FAIL'} {k:<44} {have}")
            still += not ok
        if still:
            print(f"\n{still} still failing. Set by hand:")
            for k, v in retry.items():
                if not same(final.get(k), v):
                    print(f"  python {Path(sys.argv[0]).name} --id {target} "
                          f"--set {k} {v}")
            return False
        print("\nall settings verified after retry.")
        bad = 0
    if bad:
        return False
    print(f"\nall {len(settings)} settings verified"
          + (" and written to flash." if persist else
             " (NOT persisted -- rerun with --write)."))

    to = after.get("servo.default_timeout_s")
    if to and float(to) > 0:
        print(f"\nwatchdog is now {to}s -- rerun 'wdtest' in the console to "
              "confirm the controller stops on its own.")
    return True


def cmd_sync(target):
    """Capture the board's current values for every profile key."""
    profile, path = load_profile(target)
    conf = dump_config(target)
    new, missing = {}, []
    for k in profile:
        if k in conf:
            try:
                new[k] = float(conf[k])
            except ValueError:
                new[k] = conf[k]
        else:
            missing.append(k)
    for k, v in sorted(new.items()):
        old = profile.get(k)
        mark = "  " if same(old, v) else "->"
        print(f"  {mark} {k:<44} {v}")
    if missing:
        print(f"  (not on this firmware, dropped: {', '.join(missing)})")
    save_profile(target, new)
    print("\nThis file now matches the board. It overrides the dict in the\n"
          "script, so --check and --apply will agree from here on.")
    return new


async def probe(target):
    """Register-channel liveness + calibration probe. Zero torque, no motion."""
    c = moteus.Controller(id=target)
    print("contacting controller...", end="", flush=True)
    try:
        r = await asyncio.wait_for(c.query(), timeout=3.0)
    except asyncio.TimeoutError:
        print(" NO RESPONSE")
        print("  check: 24V on the XT30, JST PH-3 seated, correct --id,\n"
              "  and that no other program is holding the USB adapter.")
        return
    v = r.values
    vbus = v.get(moteus.Register.VOLTAGE, float("nan"))
    print(f" ok  (vbus={vbus:.1f}V, "
          f"temp={v.get(moteus.Register.TEMPERATURE, float('nan')):.1f}C)")
    if vbus < 10.0:
        print(f"  !! only {vbus:.1f}V -- motor supply not connected")

    await c.set_stop()
    await asyncio.sleep(0.1)
    await c.set_position(position=math.nan, velocity=0.0,
                         maximum_torque=0.0, query=True)
    await asyncio.sleep(0.2)
    r = await c.query()
    await c.set_stop()
    mode = int(r.values.get(moteus.Register.MODE, -1))
    print(f"position-mode probe: mode={mode}"
          + ("  (accepted -> motor is calibrated)" if mode == 10 else
             "  (fault 36 = not calibrated)" if mode == 1 else ""))


def cmd_calibrate(target, extra):
    print("=" * 70)
    print("  THE MOTOR WILL SPIN FREELY, BOTH DIRECTIONS, AT HIGH SPEED.")
    print("  Output disconnected? No hard stops in the way? Bench clear?")
    print("=" * 70)
    if input("type YES to continue: ").strip() != "YES":
        print("aborted")
        return 1
    run_tool(target, "--calibrate", *extra, capture=False)
    print("\ncalibration done -- now run --apply")
    return 0


def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="typical first run:  --probe  then  --check  then  --apply")
    p.add_argument("--id", type=int, default=1, help="CAN id (default 1)")
    p.add_argument("--probe", action="store_true",
                   help="liveness + calibration check via registers")
    p.add_argument("--dump", nargs="?", const="", metavar="PREFIX",
                   help="print config from the board, optionally filtered")
    p.add_argument("--backup", metavar="FILE",
                   help="with --dump, also save full config to FILE")
    p.add_argument("--sync", action="store_true",
                   help="save the board's current values as the profile")
    p.add_argument("--check", action="store_true",
                   help="calibration status + profile drift")
    p.add_argument("--apply", action="store_true", help="write the profile")
    p.add_argument("--no-write", dest="persist", action="store_false",
                   help="with --apply, do not persist to flash")
    p.add_argument("--restore", metavar="FILE",
                   help="write a previously saved config file back")
    p.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), action="append",
                   help="write one parameter (repeatable), then verify")
    p.add_argument("--calibrate", action="store_true")
    args, extra = p.parse_known_args()
    if extra and not args.calibrate:
        p.error(f"unrecognized arguments: {' '.join(extra)}   "
                "(note: '--id 1' with a space)")

    print(f"target controller id: {args.id}\n")
    try:
        if args.probe:
            asyncio.run(probe(args.id))
        if args.calibrate:
            rc = cmd_calibrate(args.id, extra)
            if rc:
                return rc
        if args.dump is not None:
            cmd_dump(args.id, args.dump, args.backup)
        if args.sync:
            cmd_sync(args.id)
        if args.check:
            cmd_check(args.id)
        if args.restore:
            run_tool(args.id, "--restore-config", args.restore, capture=False)
            print(f"restored from {args.restore}")
        if args.set:
            want = {k: v for k, v in args.set}
            write_config(args.id, want, persist=args.persist)
            got = dump_config(args.id)
            for k, v in want.items():
                ok = got.get(k) is not None and same(got[k], v)
                print(f"  {'ok  ' if ok else 'FAIL'} {k:<44} {got.get(k)}")
        if args.apply:
            cmd_apply(args.id, args.persist)
        if not any([args.probe, args.calibrate, args.check, args.apply,
                    args.restore, args.set, args.sync,
                    args.dump is not None]):
            p.print_help()
    except RuntimeError as e:
        print(f"\n{e}")
        print("\nIf moteus_tool itself cannot reach the board, nothing here "
              "will work -- check power, cabling and --id first with --probe.")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
