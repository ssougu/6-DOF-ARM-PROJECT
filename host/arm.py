#!/usr/bin/env python3
"""
arm.py -- drive J1 and J2 together as one mechanism.

    python arm.py --sim                       # no hardware, trapezoid model
    python arm.py --j2-port COM8              # J1 on the moteus link, J2 ESP32
    python arm.py --sim --route routines/demo.txt

`Arm` composes the Joint abstraction from joints.py. Moves are time-
synchronised: every joint starts together and, because each joint's cruise
velocity is scaled to the joint with the longest move, they finish together
too. A joint-by-joint sequence looks like twitching; a synchronised move
looks like arm motion.

Positions are OUTPUT REVOLUTIONS; angles in the console and logs are degrees.
Nothing here knows J1 is a moteus and J2 a stepper -- that stays in joints.py.
"""

import argparse
import asyncio
import math
import time
from dataclasses import dataclass
from pathlib import Path

from joints import MoteusJoint, StepperJoint, SimJoint


# --------------------------------------------------------------- axes ------
@dataclass
class Axis:
    """Per-joint soft limits and motion ceilings, in OUTPUT units."""
    name: str
    pos_min: float          # output rev
    pos_max: float
    vel_max: float          # output rev/s
    accel_max: float        # output rev/s^2
    home: float = 0.0       # output rev

    def outside(self, pos):
        if pos < self.pos_min:
            return f"target {pos:+.4f} < min {self.pos_min:+.4f} rev"
        if pos > self.pos_max:
            return f"target {pos:+.4f} > max {self.pos_max:+.4f} rev"
        return None


# J1: profile_1.json servopos is +/-0.55; keep a 0.02 rev margin for overshoot.
#     vel/accel from servo.default_velocity_limit / default_accel_limit.
# J2: the firmware's posMin/posMax and velLimit/accelLimit.
DEFAULT_AXES = {
    1: Axis("J1 base yaw",       -0.53, 0.53, 0.25, 1.0),
    2: Axis("J2 shoulder pitch", -0.53, 0.53, 0.25, 1.0),
}


@dataclass
class JointSpec:
    """How to build one joint, and whether it is switched on right now.

    An `Arm` built from specs creates a `Joint` only when that joint is
    enabled — so a disabled or physically absent J2 never opens its COM port.
    `kind='prebuilt'` wraps an already-constructed Joint (the path
    `Arm([SimJoint(1), ...])` uses); those are never rebuilt, only re-armed.
    """
    id: int
    kind: str                 # 'moteus' | 'stepper' | 'sim' | 'prebuilt'
    axis: Axis
    enabled: bool = True
    moteus_id: int = 1
    port: str = ""            # stepper serial port
    instance: object = None   # kind='prebuilt' only

    @property
    def name(self):
        return self.axis.name


def _num(x, places):
    """Round for JSON; NaN/inf become None so the wire format stays valid."""
    try:
        if x is None or not math.isfinite(x):
            return None
        return round(float(x), places)
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------- motion timing ---
def trapezoid_time(dist, vmax, amax):
    """Time for a trapezoidal move of `dist` at the given ceilings."""
    d, v, a = abs(dist), max(vmax, 1e-9), max(amax, 1e-9)
    if d <= v * v / a:                     # triangular -- never reaches vmax
        return 2.0 * math.sqrt(d / a)
    return v / a + d / v                   # ramp up + cruise + ramp down


def cruise_vel_for_time(dist, amax, T):
    """Peak velocity that makes a trapezoidal move of `dist` last exactly T.

    From  T = v/a + d/v  ->  v^2 - aT*v + a*d = 0. The smaller root is the
    real trapezoid; the larger one implies negative cruise time.
    """
    d, a = abs(dist), max(amax, 1e-9)
    disc = a * a * T * T - 4.0 * a * d
    if disc <= 0.0:                        # T too short even for a triangle
        return math.sqrt(d * a)           # triangular peak, best effort
    return (a * T - math.sqrt(disc)) / 2.0


# --------------------------------------------------------- route parser ---
_ROUTE_ARITY = {"move": 2, "movej": 2, "jog": 2, "home": 0,
                "wait": 1, "speed": 1, "echo": -1}


def parse_route(text):
    """Parse a route into a list of (op, args) steps.

    One step per line or per `;`-separated clause. `#` starts a comment.
        speed 0.4
        move 25 -12       ; J1 -> 25 deg, J2 -> -12 deg, synchronised
        movej 2 -20       ; just J2
        jog 1 5           ; J1 by +5 deg, relative
        wait 0.5
        home
    """
    if isinstance(text, (list, tuple)):
        text = "\n".join(text)
    steps = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]            # strip the comment first, so a
        for clause in line.split(";"):         # ';' or '#' inside one is safe
            clause = clause.strip()
            if not clause:
                continue
            tok = clause.split()
            op = tok[0].lower()
            if op not in _ROUTE_ARITY:
                raise ValueError(f"route: unknown op {op!r}")
            if op == "echo":
                steps.append((op, clause[len(tok[0]):].strip()))
                continue
            try:
                args = [float(x) for x in tok[1:]]
            except ValueError:
                raise ValueError(
                    f"route: non-numeric argument in {clause!r}")
            want = _ROUTE_ARITY[op]
            if len(args) != want:
                raise ValueError(f"route: {op!r} takes {want} arg(s), "
                                 f"got {len(args)} in {clause!r}")
            steps.append((op, args))
    return steps


# -------------------------------------------------------------- the arm ---
class Arm:
    def __init__(self, joints_or_specs, axes=None, log_dir="logs", note="",
                 transport_factory=None):
        items = list(joints_or_specs or [])
        if not items:
            raise ValueError("Arm needs at least one joint")
        src = axes or DEFAULT_AXES
        specs = []
        for it in items:
            if isinstance(it, JointSpec):
                specs.append(it)
            else:                              # an already-built Joint
                specs.append(JointSpec(id=it.id, kind="prebuilt",
                                       axis=src[it.id], instance=it))
        self.specs = {s.id: s for s in specs}
        self.order = sorted(self.specs)
        self.axes = {i: self.specs[i].axis for i in self.order}
        self._joints = {i: self.specs[i].instance for i in self.order}
        self._transport = None
        self._transport_factory = transport_factory
        self.log_dir = Path(log_dir)
        self.note = note
        self.armed = False
        self.estopped = False
        self.speed = 1.0                   # global 0..1 multiplier on vel_max

    # ---- joint registry --------------------------------------------
    @property
    def joints(self):
        """Connected joint instances, by id (built and not released)."""
        return {i: j for i, j in self._joints.items() if j is not None}

    @property
    def active_ids(self):
        """Ids that are enabled AND connected — everything motion acts on."""
        return [i for i in self.order
                if self.specs[i].enabled and self._joints[i] is not None]

    def _build_joint(self, spec):
        if spec.kind == "prebuilt":
            return spec.instance
        if spec.kind == "sim":
            return SimJoint(spec.id, spec.axis.name)
        if spec.kind == "stepper":
            if not spec.port:
                raise RuntimeError(f"{spec.name}: no serial port configured")
            return StepperJoint(spec.id, port=spec.port, name=spec.axis.name)
        if spec.kind == "moteus":
            if self._transport is None and self._transport_factory is not None:
                self._transport = self._transport_factory()
            return MoteusJoint(spec.id, moteus_id=spec.moteus_id,
                               transport=self._transport, name=spec.axis.name)
        raise RuntimeError(f"unknown joint kind {spec.kind!r}")

    def _ensure_built(self):
        """Instantiate any enabled-but-unbuilt joint. Returns error strings."""
        errs = []
        for i in self.order:
            spec = self.specs[i]
            if spec.enabled and self._joints[i] is None:
                try:
                    self._joints[i] = self._build_joint(spec)
                except Exception as e:             # noqa: BLE001
                    spec.enabled = False           # can't connect -> stays off
                    errs.append(f"{spec.name}: {e}")
        return errs

    async def enable(self, jid):
        """Switch a joint on: build/connect it, and arm it if the arm is armed."""
        if jid not in self.specs:
            raise ValueError(f"no joint {jid} on this arm")
        spec = self.specs[jid]
        if self._joints[jid] is None:
            self._joints[jid] = self._build_joint(spec)     # may raise
        spec.enabled = True
        if self.armed and not self.estopped:
            j = self._joints[jid]
            await j.arm()
            await j.hold()
        return True

    async def disable(self, jid):
        """Switch a joint off: de-energize it and drop it out of every move."""
        if jid not in self.specs:
            raise ValueError(f"no joint {jid} on this arm")
        spec = self.specs[jid]
        spec.enabled = False
        j = self._joints[jid]
        if j is not None:
            await self._safe_stop(j)
            if spec.kind != "prebuilt":
                try:
                    await j.close()                # frees the COM port
                except Exception:                  # noqa: BLE001
                    pass
                self._joints[jid] = None           # rebuilt on re-enable
        return True

    # ---- lifecycle ---------------------------------------------------
    async def arm(self):
        errs = self._ensure_built()
        ids = self.active_ids
        if not ids:
            raise RuntimeError("no joints enabled"
                               + (" -- " + "; ".join(errs) if errs else ""))
        res = await asyncio.gather(
            *(self._joints[i].arm() for i in ids),
            return_exceptions=True)
        for jid, r in zip(ids, res):
            if isinstance(r, Exception):
                raise RuntimeError(f"{self.axes[jid].name}: arm failed: {r}")
        self.armed = True
        self.estopped = False
        for e in errs:
            print(f"  ! {e} (left disabled)")
        # Returned so a caller with a UI can say *why* a joint switched itself
        # off -- under the desktop app stdout goes to a hidden console, and a
        # joint that silently turns OFF is indistinguishable from a bug.
        return errs

    async def hold(self):
        await asyncio.gather(*(self._joints[i].hold() for i in self.active_ids),
                             return_exceptions=True)

    async def stop(self, reason="stop"):
        """Panic path: de-energize every joint. Never raises."""
        already_down = self.estopped and not self.armed
        self.armed = False
        self.estopped = True
        await asyncio.gather(*(self._safe_stop(j)
                               for j in self.joints.values()))
        if not already_down:                   # stay quiet on redundant calls
            print(f"\n*** {reason.upper()} -- all joints stopped. "
                  f"'arm' to re-enable ***")

    @staticmethod
    async def _safe_stop(j):
        for _ in range(3):
            try:
                await j.stop()
                return
            except Exception as e:                    # noqa: BLE001
                print(f"  {j.name}: stop retry ({e})")
                await asyncio.sleep(0.05)

    async def zero(self, ids=None):
        """Define the current pose as home. Place the arm by hand first."""
        ids = [i for i in (list(ids) if ids else list(self.active_ids))
               if self._joints.get(i) is not None]
        if not ids:
            # Distinguish "switched off" from "on but never connected" -- the
            # lazy build means an enabled joint is not open until arm/enable.
            waiting = [self.specs[i].name for i in self.order
                       if self.specs[i].enabled and self._joints[i] is None]
            raise RuntimeError(
                f"not connected yet ({', '.join(waiting)}) -- arm first"
                if waiting else "no enabled joints to zero")
        await asyncio.gather(*(self._joints[i].zero() for i in ids),
                             return_exceptions=True)
        for i in ids:
            self.axes[i].home = 0.0
        print("zeroed: " + ", ".join(self.axes[i].name for i in ids))

    # ---- state -----------------------------------------------------
    async def read(self):
        ids = self.active_ids
        st = await asyncio.gather(*(self._joints[i].read() for i in ids))
        return dict(zip(ids, st))

    async def snapshot(self):
        """Full structured state for a UI: every joint, enabled or not."""
        states = {}
        ids = self.active_ids
        if ids:
            got = await asyncio.gather(
                *(self._joints[i].read() for i in ids),
                return_exceptions=True)
            states = {i: s for i, s in zip(ids, got)
                      if not isinstance(s, Exception)}
        joints = []
        for i in self.order:
            spec, ax, s = self.specs[i], self.axes[i], states.get(i)
            joints.append({
                "id": i,
                "name": ax.name,
                "kind": spec.kind,
                # where this joint actually talks, for live bring-up: the
                # serial port for a stepper, the CAN id for a moteus.
                "link": (spec.port if spec.kind == "stepper"
                         else f"id {spec.moteus_id}" if spec.kind == "moteus"
                         else ""),
                "enabled": spec.enabled,
                "connected": self._joints[i] is not None,
                "deg": None if s is None else _num(s.degrees, 3),
                "vel_dps": None if s is None else _num(s.velocity * 360.0, 2),
                "moving": bool(s.moving) if s else False,
                "fault": int(s.fault) if s else 0,
                "voltage": None if s is None else _num(s.voltage, 1),
                "temp": None if s is None else _num(s.temperature, 1),
                "min_deg": round(ax.pos_min * 360.0, 1),
                "max_deg": round(ax.pos_max * 360.0, 1),
                "home_deg": round(ax.home * 360.0, 1),
            })
        return {"armed": self.armed, "estopped": self.estopped,
                "speed": round(self.speed, 3), "joints": joints}

    async def pose_deg(self):
        return {i: round(s.degrees, 3) for i, s in (await self.read()).items()}

    # ---- motion --------------------------------------------------
    async def move(self, targets_rev, speed=None, settle=0.25, min_T=0.25):
        """Synchronised move. `targets_rev` is {joint_id: output_rev}."""
        if not self.armed:
            raise RuntimeError("not armed -- 'arm' first")
        if self.estopped:
            raise RuntimeError("e-stopped -- 'arm' to clear")
        speed = self.speed if speed is None else speed
        speed = max(0.02, min(1.0, speed))

        active = set(self.active_ids)
        skipped = []
        wanted = {}
        for jid, tgt in targets_rev.items():
            if jid not in self.specs:
                raise ValueError(f"no joint {jid} on this arm")
            if jid not in active:
                skipped.append(self.axes[jid].name)   # disabled -> not an error
                continue
            bad = self.axes[jid].outside(tgt)
            if bad:
                raise ValueError(f"{self.axes[jid].name}: {bad}")
            wanted[jid] = tgt
        if skipped:
            print(f"  (skipping {', '.join(skipped)} -- disabled)")
        if not wanted:
            return await self.read()
        targets_rev = wanted

        cur = await self.read()

        # the joint with the longest move sets the tempo
        T = min_T
        plan = {}
        for jid, tgt in targets_rev.items():
            ax = self.axes[jid]
            d = abs(tgt - cur[jid].position)
            plan[jid] = (tgt, d, ax)
            if d > 1e-6:
                T = max(T, trapezoid_time(d, ax.vel_max * speed, ax.accel_max))

        movers = []
        for jid, (tgt, d, ax) in plan.items():
            if d <= 1e-6:
                continue
            v = cruise_vel_for_time(d, ax.accel_max, T)
            v = max(1e-3, min(v, ax.vel_max * speed))
            movers.append((jid, tgt, v, ax.accel_max))

        if not movers:
            await asyncio.sleep(settle)
            return await self.read()

        # fire them all at once (gather so a blocking SimJoint move still
        # runs concurrently with the others)
        await asyncio.gather(*(self._joints[j].move_to(t, velocity=v, accel=a)
                               for j, t, v, a in movers))

        moving_ids = [j for j, *_ in movers]
        deadline = time.monotonic() + T * 4.0 + 5.0
        while time.monotonic() < deadline:
            if self.estopped:
                raise RuntimeError("e-stopped during move")
            sts = await self.read()
            bad = {j: sts[j].fault for j in sts
                   if sts[j].fault > 0 and not 100 <= sts[j].fault <= 104}
            if bad:
                await self.stop(f"fault {bad}")
                raise RuntimeError(f"joint fault during move: {bad}")
            if all(not sts[j].moving for j in moving_ids):
                break
            await asyncio.sleep(0.03)
        else:
            print(f"  ! move did not settle within {T * 4.0 + 5.0:.1f}s")

        await asyncio.sleep(settle)
        return await self.read()

    async def move_deg(self, targets_deg, **kw):
        return await self.move({j: d / 360.0 for j, d in targets_deg.items()},
                               **kw)

    async def home(self, **kw):
        return await self.move({j: self.axes[j].home for j in self.active_ids},
                               **kw)

    # ---- routes --------------------------------------------------
    async def run_route(self, lines, echo=print, should_abort=None,
                        on_step=None):
        """Execute a route (see parse_route). Logs a per-move error report.

        `should_abort()` is polled between steps so a UI can stop a route
        without e-stopping. `on_step(i, total, op, args)` fires before each.
        """
        if not self.armed:
            raise RuntimeError("not armed -- 'arm' first")
        steps = parse_route(lines)
        report, t0 = [], time.monotonic()
        echo(f"route: {len(steps)} step(s)")
        for i, (op, a) in enumerate(steps):
            if self.estopped:
                echo(f"  aborted at step {i + 1} (e-stopped)")
                break
            if should_abort is not None and should_abort():
                echo(f"  stopped at step {i + 1}")
                break
            if on_step is not None:
                on_step(i + 1, len(steps), op, a)
            tag = f"  {i + 1:>2}."
            try:
                if op in ("move", "movej", "jog"):
                    want = await self._route_targets(op, a)
                    got = await self.move(want)
                    errs = {f"J{j}": round((got[j].position - want[j]) * 360, 3)
                            for j in want if j in got}
                    report.append({"step": i + 1, "op": op, "args": a,
                                   "err_deg": errs})
                    echo(f"{tag} {op} {' '.join(f'{x:g}' for x in a)}   "
                         + "  ".join(
                             f"J{j} -> {want[j] * 360:+.1f} "
                             f"(err {errs[f'J{j}']:+.2f})"
                             for j in want if f"J{j}" in errs))
                elif op == "home":
                    await self.home()
                    echo(f"{tag} home")
                elif op == "speed":
                    self.speed = max(0.02, min(1.0, a[0]))
                    echo(f"{tag} speed {self.speed:g}")
                elif op == "wait":
                    await asyncio.sleep(a[0])
                elif op == "echo":
                    echo(f"  # {a}")
            except Exception as e:                        # noqa: BLE001
                echo(f"{tag} {op} FAILED: {e}")
                break
        elapsed = time.monotonic() - t0
        self._log_route(steps, report, elapsed)
        return report

    async def _route_targets(self, op, a):
        if op == "move":
            # J1/J2 pair. A disabled joint is dropped by move(), not an error;
            # only a joint this arm has never heard of is.
            missing = [j for j in (1, 2) if j not in self.specs]
            if missing:
                raise ValueError(f"'move' needs J1 and J2 (missing {missing}); "
                                 f"use 'movej <id> <deg>'")
            return {1: a[0] / 360.0, 2: a[1] / 360.0}
        if op == "movej":
            jid = int(a[0])
            if jid not in self.specs:
                raise ValueError(f"no joint {jid} on this arm")
            return {jid: a[1] / 360.0}
        # jog: relative to the joint's current position
        jid = int(a[0])
        if jid not in self.specs:
            raise ValueError(f"no joint {jid} on this arm")
        cur = (await self.read()).get(jid)
        if cur is None:
            raise ValueError(f"{self.axes[jid].name} is disabled")
        return {jid: cur.position + a[1] / 360.0}

    def _log_route(self, steps, report, elapsed):
        import json
        import datetime
        self.log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        stamp = now.strftime("%Y%m%d-%H%M%S")
        base = self.log_dir / f"{stamp}_arm_route"
        worst = max((abs(e) for r in report for e in r["err_deg"].values()),
                    default=0.0)
        ids = self.active_ids
        record = {
            "timestamp": now.isoformat(timespec="seconds"),
            "joints": {f"J{j}": type(self._joints[j]).__name__ for j in ids},
            "note": self.note,
            "speed": self.speed,
            "axes": {f"J{j}": vars(self.axes[j]) for j in ids},
            "steps": [{"op": op, "args": a} for op, a in steps],
            "moves": report,
            "metrics": {"moves": len(report),
                        "worst_err_deg": round(worst, 4),
                        "elapsed_s": round(elapsed, 1)},
        }
        base.with_suffix(".json").write_text(
            json.dumps(record, indent=2) + "\n")
        hist = self.log_dir / "arm_history.csv"
        _append_csv(hist, {
            "timestamp": record["timestamp"],
            "joints": "+".join(f"J{j}" for j in ids) or "none",
            "note": self.note, "speed": self.speed,
            "moves": len(report), "worst_err_deg": round(worst, 4),
            "elapsed_s": round(elapsed, 1),
        })
        print(f"  logged -> {base.name}.json   (history: {hist.name})")

    # ---- construction ------------------------------------------
    @classmethod
    def specs_from_args(cls, args, axes=None):
        """Build JointSpecs from CLI args. Nothing is connected yet."""
        src = axes or DEFAULT_AXES
        kind = "sim" if args.sim else None
        specs = [
            JointSpec(1, kind or "moteus", src[1],
                      enabled=not args.no_j1, moteus_id=args.j1_id),
            JointSpec(2, kind or "stepper", src[2],
                      enabled=not args.no_j2, port=args.j2_port or ""),
        ]
        return specs

    @classmethod
    def from_args(cls, args):
        """Eagerly connect whatever is enabled — the CLI entry points want a
        hard failure at startup, not a joint that silently stays off."""
        if args.sim:
            print("SIM -- trapezoid model, no hardware")
        factory = None
        if not args.sim:
            def factory():                            # noqa: E306
                import moteus
                return moteus.get_singleton_transport(args)
        arm = cls(cls.specs_from_args(args), log_dir=args.logs,
                  note=args.note, transport_factory=factory)
        if not any(s.enabled for s in arm.specs.values()):
            raise SystemExit("nothing to drive -- --no-j1 and --no-j2 "
                             "are both set")
        if not args.sim and arm.specs[2].enabled and not args.j2_port:
            raise SystemExit("J2 needs --j2-port COMx   "
                             "(or pass --no-j2, or --sim for no hardware)")
        # J2 first: opening a missing COM port is the likeliest failure, and
        # doing it before the moteus transport avoids leaking that link.
        for jid in (2, 1):
            spec = arm.specs[jid]
            if not spec.enabled:
                continue
            try:
                arm._joints[jid] = arm._build_joint(spec)
            except Exception as e:                       # noqa: BLE001
                if spec.kind == "stepper":
                    raise SystemExit(
                        f"could not open J2 on {spec.port}: {e}\n"
                        f"  serial ports present: "
                        f"{_serial_ports() or '(none)'}\n"
                        f"  plug in the ESP32 and pass its port, use --no-j2, "
                        f"or run with --sim")
                raise SystemExit(f"{spec.name}: {e}")
        return arm

    @classmethod
    def lazy_from_args(cls, args):
        """Like from_args but connects nothing — the server enables joints on
        demand, so a missing ESP32 must not stop the app from starting."""
        if args.sim:
            print("SIM -- trapezoid model, no hardware")
        factory = None
        if not args.sim:
            def factory():                            # noqa: E306
                import moteus
                return moteus.get_singleton_transport(args)
        return cls(cls.specs_from_args(args), log_dir=args.logs,
                   note=args.note, transport_factory=factory)


def _serial_ports():
    try:
        from serial.tools import list_ports
        return ", ".join(p.device for p in list_ports.comports())
    except Exception:                                    # noqa: BLE001
        return ""


def _append_csv(path, row):
    """Append a row, preserving any columns earlier rows already had."""
    import csv
    prior = []
    if path.exists():
        with open(path, newline="") as f:
            prior = list(csv.DictReader(f))
    cols = list(dict.fromkeys([c for r in prior for c in r] + list(row)))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in prior:
            w.writerow(r)
        w.writerow(row)


# ------------------------------------------------------------------ cli ---
def add_args(p):
    p.add_argument("--sim", action="store_true",
                   help="simulate both joints; no hardware")
    p.add_argument("--j1-id", type=int, default=1,
                   help="J1 moteus CAN id (default 1)")
    p.add_argument("--j2-port", metavar="COMx",
                   help="serial port of the J2 ESP32")
    p.add_argument("--no-j1", action="store_true", help="leave J1 out")
    p.add_argument("--no-j2", action="store_true", help="leave J2 out")
    p.add_argument("--logs", default="logs", metavar="DIR",
                   help="where route logs go (default: ./logs)")
    p.add_argument("--note", default="", help="label attached to route logs")
    try:
        import moteus
        moteus.make_transport_args(p)
    except Exception:                                    # noqa: BLE001
        pass


DEMO_ROUTE = """
# built-in demo -- gentle, symmetric, small angles
speed 0.5
move 15 -10
wait 0.4
move -15 -10
wait 0.4
move 0 0
"""


async def _run(args):
    arm = Arm.from_args(args)
    try:
        await arm.arm()
        await arm.hold()
        print(f"armed. pose = {await arm.pose_deg()} (deg)")
        if any(isinstance(j, StepperJoint) for j in arm.joints.values()):
            print("note: J2 has no absolute encoder -- 'home' is wherever it "
                  "was zeroed / powered on.\n      Use arm_console.py to zero "
                  "it against a known pose first.")
        text = Path(args.route).read_text() if args.route else DEMO_ROUTE
        await arm.run_route(text)
    finally:
        try:
            await arm.stop("exit")
        except Exception:                               # noqa: BLE001
            pass


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_args(p)
    p.add_argument("--route", metavar="FILE",
                   help="run this route file, then exit (default: a demo)")
    args = p.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\n^C -- tasks stopped; the moteus and stepper watchdogs "
              "de-energize within 0.25 s")


if __name__ == "__main__":
    main()
