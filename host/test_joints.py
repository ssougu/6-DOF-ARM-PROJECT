#!/usr/bin/env python3
"""test_joints.py -- MoteusJoint safety behaviour, no hardware required.

    python test_joints.py

Covers the two defects found in the 2026-10-20 audit:

  1. A dead CAN link used to leave read() serving a frozen position with
     moving=False and fault=0 -- which Arm.move() reads as "arrived". The
     stream task swallows transient errors by design, so staleness has to be
     caught by age, not by exception.
  2. The settle tolerance sat at 2e-3 rev = 0.72 deg, BELOW the joint's own
     measured |mu|+2sigma landing error of 0.685 deg (n=50, 2026-10-18), so
     roughly 2% of real moves never reported moving=False.

The joint is built field-by-field and handed a fake controller, so this needs
no transport, no motor and no event-loop construction order.
"""
import asyncio
import math
import sys

sys.path.insert(0, r"C:\dev\6-DOF-ARM-PROJECT\host")
import moteus
from joints import MoteusJoint, SETTLE_TOL_REV, STALE_PERIODS

R = moteus.Register
FAILS = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


class FakeResult:
    def __init__(self, pos, vel=0.0, fault=0):
        self.values = {R.POSITION: pos, R.VELOCITY: vel, R.FAULT: fault,
                       R.TORQUE: 0.1, R.VOLTAGE: 24.0, R.TEMPERATURE: 26.0}


class FakeController:
    """Serves telemetry until `dead` is set, then raises like a dead link."""
    def __init__(self):
        self.dead = False
        self.pos = 0.25
        self.stops = 0

    async def query(self):
        if self.dead:
            raise OSError("fdcanusb went away")
        return FakeResult(self.pos)

    async def set_position(self, **kw):
        if self.dead:
            raise OSError("fdcanusb went away")
        return FakeResult(self.pos)

    async def set_stop(self):
        self.stops += 1


def make_joint(control_hz=50):
    j = object.__new__(MoteusJoint)
    j.id, j.name = 1, "J1"
    j._moteus = moteus
    j.moteus_id = 1
    j.controller = FakeController()
    j._armed = True
    j._last_cmd = None
    j._period = 1.0 / control_hz
    j._target = None
    j._last = None
    j._last_t = 0.0
    j._faulted = 0
    j._stream = None
    return j


async def test_staleness():
    print("\n[1] stale telemetry must become a fault, not a frozen position")
    j = make_joint()
    j._target = (0.25, None, None, None)
    j._stream = asyncio.create_task(j._run())
    await asyncio.sleep(0.15)

    st = await j.read()
    check("live link reads a real position", not math.isnan(st.position)
          and st.fault == 0, f"pos={st.position}")

    # kill the link; _run() will swallow the errors exactly as before
    j.controller.dead = True
    frozen = st.position
    await asyncio.sleep(STALE_PERIODS * j._period + 0.08)

    st2 = await j.read()
    check("dead link no longer serves the frozen position",
          st2.position != frozen or math.isnan(st2.position),
          f"was {frozen}, now {st2.position}")
    check("dead link reports fault=-1", st2.fault == -1, f"fault={st2.fault}")
    check("dead link does not claim 'arrived' (moving False + no fault)",
          not (st2.fault == 0 and not st2.moving))
    check("stream task is still alive (retrying, not crashed)",
          not j._stream.done())

    # link comes back -> recovers
    j.controller.dead = False
    await asyncio.sleep(STALE_PERIODS * j._period + 0.08)
    st3 = await j.read()
    check("recovers when the link returns", st3.fault == 0
          and not math.isnan(st3.position), f"pos={st3.position}")

    j._stream.cancel()
    try:
        await j._stream
    except asyncio.CancelledError:
        pass


async def test_settle_tolerance():
    print("\n[2] settle tolerance must sit above the measured landing error")
    j = make_joint()
    j._last_cmd = 0.0

    meas = 0.685 / 360.0          # |mu|+2sigma, n=50, 2026-10-18
    worst = 0.5712 / 360.0        # worst single move that session
    check("tolerance exceeds measured |mu|+2sigma",
          SETTLE_TOL_REV > meas,
          f"tol={SETTLE_TOL_REV*360:.2f} deg vs {meas*360:.3f} deg")
    check("tolerance exceeds the worst observed single move",
          SETTLE_TOL_REV > worst, f"{worst*360:.3f} deg")
    check("tolerance clears |mu|+3sigma with margin",
          SETTLE_TOL_REV >= 1.4 * (0.095 + 3 * 0.295) / 360.0,
          f"3sigma bound={(0.095+3*0.295):.2f} deg")

    # a joint parked with a realistic landing error must read as STOPPED
    for err_deg, want_moving in ((0.31, False),   # static error floor
                                 (0.685, False),  # the design figure
                                 (0.98, False),   # |mu|+3sigma
                                 (2.00, True)):   # genuinely not there yet
        st = j._to_state(FakeResult(err_deg / 360.0, vel=0.0))
        check(f"landed {err_deg:.2f} deg off -> moving={want_moving}",
              st.moving == want_moving)

    # velocity still dominates: actually turning == moving, however close
    st = j._to_state(FakeResult(0.0, vel=0.05))
    check("non-zero velocity reads as moving even when on target", st.moving)


async def main():
    await test_staleness()
    await test_settle_tolerance()
    print()
    if FAILS:
        print(f"*** {len(FAILS)} FAILED: {FAILS}")
        return 1
    print("ALL PASS -- both audit fixes behave as intended")
    return 0


sys.exit(asyncio.run(main()))
