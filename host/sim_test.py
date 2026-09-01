#!/usr/bin/env python3
"""
sim_test.py -- run J1 and J2 together, in simulation, with nothing plugged in.

    python sim_test.py                 # coordinated sequence + self-check
    python sim_test.py routines/demo.txt   # run a route file instead

Builds a simulated two-joint arm (arm.py + joints.py, SimJoint backend), arms
it, and drives both joints through a sequence where every move changes both
joints at once. It then checks two things:

  * landing accuracy -- each joint stops where it was told to
  * synchronisation  -- the two joints finish their shared move together,
                        which is the whole point of Arm.move()

Prints PASS / FAIL and exits non-zero on failure, so it works as a smoke test
after changing arm.py or joints.py. No hardware, no ports, no flags needed.
"""

import asyncio
import sys
import time
from pathlib import Path

from joints import SimJoint
from arm import Arm


# (J1 deg, J2 deg) absolute targets. Consecutive rows differ on BOTH joints,
# so every move is a genuine coordinated move, not a one-joint twitch.
SEQUENCE = [
    ( 25, -15),
    ( 40, -35),
    (-20, -20),
    (-35,  10),
    ( 45,  -5),
    ( 10, -30),
    (  0,   0),
]

LAND_TOL_DEG = 0.05      # SimJoint is exact; this is just slop
SYNC_TOL_S = 0.05       # joints must finish within 50 ms of each other


class TimedSimJoint(SimJoint):
    """SimJoint that remembers how long its last move actually took."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.last_move_dt = None

    async def move_to(self, position, velocity=None, accel=None):
        self.last_move_dt = None
        t0 = time.monotonic()
        result = await super().move_to(position, velocity, accel)
        self.last_move_dt = time.monotonic() - t0
        return result


async def run_sequence(arm, j1, j2):
    worst_land = 0.0
    worst_sync = 0.0
    print(f"{'move':>6}  {'command':>12}  {'landed':>16}  "
          f"{'err (deg)':>14}  {'J1 s':>6} {'J2 s':>6} {'sync gap':>9}")
    for n, (c1, c2) in enumerate(SEQUENCE, 1):
        st = await arm.move_deg({1: c1, 2: c2})
        e1, e2 = st[1].degrees - c1, st[2].degrees - c2
        worst_land = max(worst_land, abs(e1), abs(e2))

        dt1, dt2 = j1.last_move_dt, j2.last_move_dt
        gap = ""
        if dt1 is not None and dt2 is not None:
            worst_sync = max(worst_sync, abs(dt1 - dt2))
            gap = f"{abs(dt1 - dt2):.3f}"
        print(f"{n:>6}  {f'{c1:+.0f},{c2:+.0f}':>12}  "
              f"{f'{st[1].degrees:+.2f},{st[2].degrees:+.2f}':>16}  "
              f"{f'{e1:+.2f},{e2:+.2f}':>14}  "
              f"{(f'{dt1:.2f}' if dt1 else '  -- '):>6} "
              f"{(f'{dt2:.2f}' if dt2 else '  -- '):>6} {gap:>9}")
    return worst_land, worst_sync


async def main(route=None):
    j1 = TimedSimJoint(1, "J1 base yaw", quiet=True)
    j2 = TimedSimJoint(2, "J2 shoulder pitch", quiet=True)
    arm = Arm([j1, j2], note="sim_test")

    await arm.arm()
    await arm.hold()
    print("simulated arm armed at", await arm.pose_deg(), "(deg)\n")

    t0 = time.monotonic()
    if route:
        await arm.run_route(Path(route).read_text())
        await arm.stop("sim test done")
        print(f"\nroute finished in {time.monotonic() - t0:.1f}s")
        return 0

    worst_land, worst_sync = await run_sequence(arm, j1, j2)
    total = time.monotonic() - t0
    await arm.stop("sim test done")

    land_ok = worst_land <= LAND_TOL_DEG
    sync_ok = worst_sync <= SYNC_TOL_S
    print(f"\n  {len(SEQUENCE)} coordinated moves in {total:.1f}s")
    print(f"  landing accuracy : worst {worst_land:.3f} deg   "
          f"[{'ok' if land_ok else 'FAIL'}]  (tol {LAND_TOL_DEG})")
    print(f"  synchronisation  : worst {worst_sync:.3f} s between joints   "
          f"[{'ok' if sync_ok else 'FAIL'}]  (tol {SYNC_TOL_S})")

    ok = land_ok and sync_ok
    print(f"\n  {'PASS -- J1 and J2 move together and land on target'
             if ok else 'FAIL -- see above'}")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        raise SystemExit(asyncio.run(main(arg)))
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
