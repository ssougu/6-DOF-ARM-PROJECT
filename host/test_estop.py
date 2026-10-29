#!/usr/bin/env python3
"""
test_estop.py -- the e-stop must win every race. No hardware, no server to
start: it drives Arm and an in-process ArmServer over a real WebSocket.

    python test_estop.py

Each case is one way an e-stop has failed, or could fail, silently:
  mid-move       the move stops part-way and the joints stay put
  during arm     arming finishing after the stop must not clear the latch
  mid-route      the route ends; no later step runs
  re-arm         after a stop, moves refuse until 'arm'; then work again
  queued cmds    commands sent before E-STOP are discarded, not run after it
  latency        E-STOP is acked promptly even while a long move is running
  link lost      the last UI disconnecting while armed is itself a stop
Exits non-zero on failure.
"""

import asyncio
import json
import sys
import tempfile
import time

import websockets

from arm import Arm
from arm_server import ArmServer
from joints import SimJoint

PORT = 8799
FAILS = []


def check(cond, what):
    print(f"  [{'ok' if cond else 'FAIL'}] {what}")
    if not cond:
        FAILS.append(what)


class SlowArmJoint(SimJoint):
    """Arms like the real J2: ~1 s while the ESP32 boots."""
    async def arm(self):
        await asyncio.sleep(1.0)
        await super().arm()


def new_arm(j2=SimJoint):
    return Arm([SimJoint(1, "J1", quiet=True), j2(2, "J2", quiet=True)],
               log_dir=tempfile.mkdtemp(prefix="test_estop_"))


async def pos_deg(arm):
    return {i: round(s.degrees, 2) for i, s in (await arm.read()).items()}


# ------------------------------------------------------------- Arm level ---
async def case_mid_move():
    print("mid-move")
    arm = new_arm()
    await arm.arm()
    move = asyncio.create_task(arm.move_deg({1: 90, 2: 90}, speed=1.0))
    await asyncio.sleep(0.4)
    t0 = time.monotonic()
    await arm.stop("test")
    try:
        await asyncio.wait_for(move, 1.0)
        check(False, "move raised after e-stop")
    except RuntimeError:
        check(True, "move raised after e-stop")
    check(time.monotonic() - t0 < 0.2,
          f"move ended {1000 * (time.monotonic() - t0):.0f} ms after stop")
    p1 = await pos_deg(arm)
    check(all(5 < v < 85 for v in p1.values()), f"stopped part-way {p1}")
    await asyncio.sleep(0.5)
    check(await pos_deg(arm) == p1, "joints stay put after the stop")
    check(arm.estopped and not arm.armed, "latched")


async def case_during_arm():
    print("during arm")
    arm = new_arm(j2=SlowArmJoint)
    arming = asyncio.create_task(arm.arm())
    await asyncio.sleep(0.2)
    await arm.stop("test")
    try:
        await arming
        check(False, "arm() refused to complete after e-stop")
    except RuntimeError:
        check(True, "arm() refused to complete after e-stop")
    check(arm.estopped and not arm.armed, "latch still set after arming ended")
    await arm.hold()                       # the server calls this after arm()
    try:
        await arm.move_deg({1: 10})
        check(False, "move refused")
    except RuntimeError:
        check(True, "move refused")


async def case_mid_route():
    print("mid-route")
    arm = new_arm()
    await arm.arm()
    lines = []
    route = asyncio.create_task(arm.run_route(
        "speed 1\nmovej 1 90\nmovej 2 90\nmovej 1 -90", echo=lines.append))
    await asyncio.sleep(0.4)
    await arm.stop("test")
    await asyncio.wait_for(route, 2.0)
    p = await pos_deg(arm)
    check(abs(p[2]) < 0.01, f"later steps never ran (J2 {p[2]})")
    check(any("FAILED" in x or "aborted" in x for x in lines),
          "route reports it was cut short")


async def case_rearm():
    print("re-arm")
    arm = new_arm()
    await arm.arm()
    await arm.stop("test")
    try:
        await arm.move_deg({1: 5})
        check(False, "move refused while latched")
    except RuntimeError:
        check(True, "move refused while latched")
    await arm.arm()
    await arm.move_deg({1: 5}, speed=1.0)
    check(abs((await pos_deg(arm))[1] - 5) < 0.01, "moves again after 'arm'")


# ---------------------------------------------------------- server level ---
class Client:
    def __init__(self, ws):
        self.ws, self.state, self.acks = ws, None, []
        self._t = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if m.get("type") == "state":
                    self.state = m
                elif m.get("type") == "ack":
                    self.acks.append(m)
        except websockets.ConnectionClosed:
            pass

    async def send(self, cmd, **kw):
        await self.ws.send(json.dumps({"cmd": cmd, **kw}))

    async def ack(self, cmd, timeout=5.0):
        """Oldest unclaimed ack for `cmd`, in any arrival order."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for i, m in enumerate(self.acks):
                if m["cmd"] == cmd:
                    return self.acks.pop(i)
            await asyncio.sleep(0.005)
        raise TimeoutError(f"no ack for {cmd!r}")


async def with_server(fn):
    arm = new_arm()
    srv = ArmServer(arm, port=PORT, sim=True, hz=30)
    run = asyncio.create_task(srv.run())
    await asyncio.sleep(0.3)
    try:
        await fn(arm, srv)
    finally:
        srv._stop.set()
        await asyncio.wait_for(run, 5)


async def case_server(arm, srv):
    print("queued cmds + latency")
    async with websockets.connect(f"ws://127.0.0.1:{PORT}") as ws:
        c = Client(ws)
        await c.send("arm")
        check((await c.ack("arm"))["ok"], "armed over the socket")
        await c.send("move_to", id=1, deg=170)     # long: ~1.9 s at speed 1
        await c.send("arm")                        # queued behind it
        await c.send("jog", id=2, delta_deg=30)    # queued behind it
        await asyncio.sleep(0.3)
        t0 = time.monotonic()
        await c.send("estop")
        await c.ack("estop")
        ms = 1000 * (time.monotonic() - t0)
        check(ms < 250, f"E-STOP acked in {ms:.0f} ms during a move")
        a2 = await c.ack("arm")
        check(not a2["ok"] and "discarded" in a2.get("msg", ""),
              f"queued 'arm' discarded ({a2.get('msg')})")
        j = await c.ack("jog")
        check(not j["ok"], f"queued 'jog' did not run ({j.get('msg')})")
        await asyncio.sleep(0.5)
        check(arm.estopped and not arm.armed, "still latched afterwards")
        p = await pos_deg(arm)
        check(p[1] < 170 and abs(p[2]) < 0.01, f"nothing moved after stop {p}")

    print("link lost")
    async with websockets.connect(f"ws://127.0.0.1:{PORT}") as ws:
        c = Client(ws)
        await c.send("arm")
        check((await c.ack("arm"))["ok"], "re-armed")
    await asyncio.sleep(0.3)                     # socket closed, while armed
    check(arm.estopped and not arm.armed, "disconnect while armed -> e-stop")


async def main():
    for case in (case_mid_move, case_during_arm, case_mid_route, case_rearm):
        await case()
    await with_server(case_server)
    print("\nE-STOP OK" if not FAILS else f"\nE-STOP FAILED: {len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
