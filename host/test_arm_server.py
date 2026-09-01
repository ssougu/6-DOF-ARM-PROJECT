#!/usr/bin/env python3
"""
test_arm_server.py -- exercise every arm_server command against --sim.

    python arm_server.py --sim &        # in another terminal
    python test_arm_server.py

Asserts the state stream flows, that each command lands, and that a disabled
joint really does drop out of moves. Exits non-zero on failure.
"""

import asyncio
import json
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8787"


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.state = None
        self.routes = None
        self.acks = asyncio.Queue()
        self.frames = 0
        self._task = asyncio.create_task(self._reader())

    async def _reader(self):
        async for raw in self.ws:
            m = json.loads(raw)
            t = m.get("type")
            if t == "state":
                self.state = m
                self.frames += 1
            elif t == "routes":
                self.routes = m["items"]
            elif t == "ack":
                await self.acks.put(m)
            elif t == "log":
                print(f"      log: {m['msg'][:90]}")

    async def call(self, cmd, timeout=30.0, **kw):
        await self.ws.send(json.dumps({"cmd": cmd, **kw}))
        ack = await asyncio.wait_for(self.acks.get(), timeout)
        assert ack["cmd"] == cmd, f"ack mismatch {ack}"
        return ack

    async def ok(self, cmd, **kw):
        ack = await self.call(cmd, **kw)
        assert ack["ok"], f"{cmd} failed: {ack.get('msg')}"
        return ack

    async def fails(self, cmd, **kw):
        ack = await self.call(cmd, **kw)
        assert not ack["ok"], f"{cmd} unexpectedly succeeded"
        return ack

    async def fresh(self):
        n = self.frames
        while self.frames == n:
            await asyncio.sleep(0.02)
        return self.state

    def joint(self, jid):
        return next(j for j in self.state["joints"] if j["id"] == jid)


async def main():
    print(f"connecting to {URL}")
    async with websockets.connect(URL) as ws:
        c = Client(ws)

        # --- telemetry flows -------------------------------------
        await c.fresh()
        n0 = c.frames
        await asyncio.sleep(1.0)
        rate = c.frames - n0
        print(f"  telemetry {rate} frames/s")
        assert rate >= 8, f"telemetry too slow ({rate}/s)"
        assert c.routes is not None and "warmup" in c.routes, c.routes
        print(f"  routes: {c.routes}")

        # --- arm --------------------------------------------------
        await c.ok("arm")
        await c.fresh()
        assert c.state["armed"] and not c.state["estopped"]
        print("  armed")

        # --- disable J2, move, confirm it was skipped -------------
        await c.ok("disable_joint", id=2)
        await c.fresh()
        assert c.joint(2)["enabled"] is False
        assert c.joint(2)["deg"] is None
        print("  J2 disabled (deg=None, enabled=False)")

        await c.ok("move", targets={"1": 20, "2": -15})
        await c.fresh()
        assert abs(c.joint(1)["deg"] - 20) < 0.2, c.joint(1)
        assert c.joint(2)["deg"] is None, "disabled joint must not have moved"
        print("  move with J2 off -> J1 moved, J2 untouched")

        # --- re-enable and move both ------------------------------
        await c.ok("enable_joint", id=2)
        await c.fresh()
        assert c.joint(2)["enabled"] and c.joint(2)["connected"]
        await c.ok("move", targets={"1": 10, "2": -10})
        await c.fresh()
        assert abs(c.joint(1)["deg"] - 10) < 0.2
        assert abs(c.joint(2)["deg"] + 10) < 0.2
        print("  both joints move together after re-enable")

        # --- jog / move_to / speed / home -------------------------
        before = c.joint(1)["deg"]
        await c.ok("jog", id=1, delta_deg=-5)
        await c.fresh()
        assert abs(c.joint(1)["deg"] - (before - 5)) < 0.2
        print("  jog ok")

        await c.ok("move_to", id=2, deg=12)
        await c.fresh()
        assert abs(c.joint(2)["deg"] - 12) < 0.2
        print("  move_to ok")

        await c.ok("set_speed", value=0.4)
        await c.fresh()
        assert abs(c.state["speed"] - 0.4) < 1e-6
        print("  set_speed ok")

        await c.ok("home")
        await c.fresh()
        assert abs(c.joint(1)["deg"]) < 0.2 and abs(c.joint(2)["deg"]) < 0.2
        print("  home ok")

        # --- guards ------------------------------------------------
        await c.fails("zero")                      # no confirm
        await c.fails("run_route", name="does_not_exist")
        await c.fails("stop_route")                # nothing running
        print("  guards reject bad calls")

        # --- route: run, watch progress, stop ---------------------
        await c.ok("set_speed", value=1.0)
        await c.ok("run_route", name="workout")
        seen = 0
        for _ in range(200):
            await c.fresh()
            if c.state.get("route"):
                seen = max(seen, c.state["route"]["step"])
                if seen >= 3:
                    break
        assert seen >= 3, f"route progress never advanced (step={seen})"
        print(f"  route running, reached step {seen}")

        await c.ok("stop_route")
        for _ in range(300):
            await c.fresh()
            if not c.state.get("route"):
                break
        assert not c.state.get("route"), "route did not stop"
        print("  stop_route halted it")

        # --- estop -------------------------------------------------
        await c.ok("run_route", name="workout")
        await asyncio.sleep(0.5)
        await c.ok("estop")
        await c.fresh()
        assert c.state["estopped"] and not c.state["armed"]
        assert not c.state.get("route")
        print("  estop halted the route and de-energized")

        await c.fails("move", targets={"1": 5})    # blocked while e-stopped
        await c.ok("arm")                          # clears the latch
        await c.fresh()
        assert c.state["armed"] and not c.state["estopped"]
        print("  arm clears the e-stop latch")

        await c.ok("disarm")
        print("\nARM SERVER OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(f"\nFAILED: {e}")
        raise SystemExit(1)
