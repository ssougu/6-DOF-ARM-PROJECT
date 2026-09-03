#!/usr/bin/env python3
"""
arm_server.py -- WebSocket control server for the arm. Backend for the UI.

    python arm_server.py --sim                 # no hardware
    python arm_server.py --j2-port COM3        # live
    python arm_server.py --port 8787 --hz 15

Wraps one `Arm` (arm.py) and exposes it to WebSocket clients on 127.0.0.1.
Joints are built lazily, so a joint that is switched off -- or whose hardware
is unplugged -- never opens its port and never stops the app from starting.
You switch joints on from the UI.

Protocol: JSON both ways.

  client -> server  {"cmd": ...}
    arm | disarm | estop | home | stop_route | list_routes
    enable_joint  {id}            disable_joint {id}
    jog           {id, delta_deg}
    move_to       {id, deg}
    move          {targets: {"1": deg, "2": deg}}
    zero          {ids: [...]|null, confirm: true}
    set_speed     {value}
    run_route     {name}

  server -> client
    {"type":"state", armed, estopped, speed, busy, route, sim, joints:[...]}
    {"type":"routes", items:[...]}
    {"type":"log", level, msg}      {"type":"ack", cmd, ok, msg}
    {"type":"error", msg}

`estop` is handled the instant it arrives rather than through the queue, so it
lands mid-move. Every other command is serialised through one worker so two
clients cannot interleave motion. A client disconnecting does NOT stop the arm
-- the hardware watchdogs cover a server crash, and a dropped browser tab
should not fling a running routine into an abort.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import websockets

from arm import Arm, add_args, parse_route

ROUTES_DIR = Path(__file__).parent / "routines"

# USB-serial chips these ESP32 boards use, for --j2-port autodetect
ESP_HINTS = ("cp210", "ch340", "ch910", "silicon labs", "wch")


def parent_alive(pid):
    """True while `pid` is still running. Used to shut down with the UI."""
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes
        QUERY, STILL_ACTIVE = 0x1000, 259
        k = ctypes.windll.kernel32
        h = k.OpenProcess(QUERY, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def guess_esp_port():
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            blob = f"{p.description} {p.manufacturer or ''}".lower()
            if any(h in blob for h in ESP_HINTS):
                return p.device
    except Exception:                                    # noqa: BLE001
        pass
    return None


class ArmServer:
    def __init__(self, arm, host="127.0.0.1", port=8787, sim=False, hz=15.0):
        self.arm = arm
        self.host, self.port, self.sim = host, port, sim
        self.period = 1.0 / max(hz, 1.0)
        self.clients = set()
        self.queue = asyncio.Queue()
        self.busy = None            # command in flight, or None
        self.route = None           # {"name","step","total"} while running
        self._route_task = None
        self._route_stop = False
        self._outbox = []           # log lines waiting to be broadcast
        self._stop = None           # set to end run()
        self._bye = None            # pending graceful-shutdown task

    # ---- output ----------------------------------------------------
    def log(self, msg, level="info"):
        """Safe to call from sync callbacks (route echo) -- just queues."""
        text = str(msg).rstrip()
        if not text:
            return
        print(f"  [{level}] {text}")
        self._outbox.append({"type": "log", "level": level, "msg": text})

    @staticmethod
    async def _send(ws, obj):
        try:
            await ws.send(json.dumps(obj))
        except Exception:                                # noqa: BLE001
            pass

    async def broadcast(self, obj):
        if not self.clients:
            return
        msg = json.dumps(obj)
        await asyncio.gather(
            *(self._raw(ws, msg) for ws in list(self.clients)),
            return_exceptions=True)

    @staticmethod
    async def _raw(ws, msg):
        try:
            await ws.send(msg)
        except Exception:                                # noqa: BLE001
            pass

    # ---- background tasks -----------------------------------------
    async def _telemetry(self):
        while True:
            try:
                snap = await self.arm.snapshot()
                snap.update({"type": "state", "ts": round(time.time(), 3),
                             "sim": self.sim, "busy": self.busy,
                             "route": self.route})
                await self.broadcast(snap)
                while self._outbox:
                    await self.broadcast(self._outbox.pop(0))
            except asyncio.CancelledError:
                raise
            except Exception as e:                       # noqa: BLE001
                print(f"  [telemetry] {e}")
            await asyncio.sleep(self.period)

    async def _worker(self):
        while True:
            cmd, ws = await self.queue.get()
            name = cmd.get("cmd")
            self.busy = name
            try:
                await self._dispatch(cmd, ws)
                await self._send(ws, {"type": "ack", "cmd": name, "ok": True})
            except asyncio.CancelledError:
                raise
            except Exception as e:                       # noqa: BLE001
                self.log(f"{name}: {e}", "error")
                await self._send(ws, {"type": "ack", "cmd": name,
                                      "ok": False, "msg": str(e)})
            finally:
                self.busy = None
                self.queue.task_done()

    # ---- guards ----------------------------------------------------
    def _require_armed(self):
        if not self.arm.armed:
            raise RuntimeError("not armed")
        if self.arm.estopped:
            raise RuntimeError("e-stopped -- arm to clear")

    def _require_idle(self):
        if self._route_task is not None and not self._route_task.done():
            raise RuntimeError("a route is running -- stop it first")

    # ---- commands --------------------------------------------------
    async def _dispatch(self, c, ws):
        cmd, a = c.get("cmd"), self.arm

        if cmd == "arm":
            errs = await a.arm()
            await a.hold()
            # A joint that could not connect switched itself off; say so, or
            # the UI just shows it flip to OFF for no visible reason.
            for e in (errs or []):
                self.log(f"{e} -- left disabled", "warn")
            self.log("armed + holding")

        elif cmd == "disarm":
            self._route_stop = True
            await a.stop("disarm")

        elif cmd == "home":
            self._require_armed()
            self._require_idle()
            await a.home()
            self.log("home")

        elif cmd == "enable_joint":
            jid = int(c["id"])
            await a.enable(jid)
            self.log(f"J{jid} enabled"
                     + (" (armed + holding)" if a.armed else ""))

        elif cmd == "disable_joint":
            jid = int(c["id"])
            await a.disable(jid)
            self.log(f"J{jid} disabled -- de-energized")

        elif cmd == "jog":
            self._require_armed()
            self._require_idle()
            jid, d = int(c["id"]), float(c["delta_deg"])
            cur = (await a.read()).get(jid)
            if cur is None:
                raise RuntimeError(f"J{jid} is disabled")
            await a.move_deg({jid: cur.degrees + d})

        elif cmd == "move_to":
            self._require_armed()
            self._require_idle()
            await a.move_deg({int(c["id"]): float(c["deg"])})

        elif cmd == "move":
            self._require_armed()
            self._require_idle()
            targets = {int(k): float(v) for k, v in (c.get("targets") or {}).items()}
            if not targets:
                raise RuntimeError("move needs targets")
            await a.move_deg(targets)

        elif cmd == "zero":
            if not c.get("confirm"):
                raise RuntimeError("zero requires confirm:true")
            self._require_idle()
            ids = c.get("ids")
            await a.zero([int(i) for i in ids] if ids else None)
            self.log("zeroed -- this pose is now home")

        elif cmd == "set_speed":
            a.speed = max(0.02, min(1.0, float(c["value"])))
            self.log(f"speed {a.speed:g}")

        elif cmd == "list_routes":
            await self._send(ws, {"type": "routes", "items": self._routes()})

        elif cmd == "run_route":
            await self._start_route(str(c["name"]))

        elif cmd == "stop_route":
            if self._route_task is None or self._route_task.done():
                raise RuntimeError("no route is running")
            self._route_stop = True
            self.log("stopping route after the current step")

        elif cmd == "shutdown":
            # Graceful exit, used by the UI before it restarts us in the other
            # mode. Stops any route and de-energizes here rather than leaving
            # it to a hard kill -- TerminateProcess skips run()'s finally, so
            # on live hardware only moteus's 0.25 s watchdog would save us and
            # a holding stepper would just stay energized.
            self._route_stop = True
            await a.stop("shutdown")
            self.log("shutdown requested -- de-energized")
            # Let the ack reach the client before run() tears the server down.
            self._bye = asyncio.create_task(self._exit_soon())

        else:
            raise RuntimeError(f"unknown command {cmd!r}")

    # ---- routes ----------------------------------------------------
    @staticmethod
    def _routes():
        if not ROUTES_DIR.is_dir():
            return []
        return sorted(p.stem for p in ROUTES_DIR.glob("*.txt"))

    async def _start_route(self, name):
        self._require_armed()
        self._require_idle()
        path = ROUTES_DIR / f"{name}.txt"
        if not path.is_file():
            raise RuntimeError(f"no route {name!r} in {ROUTES_DIR.name}/")
        text = path.read_text()
        steps = parse_route(text)              # validate before anything moves
        self._route_stop = False
        self.route = {"name": name, "step": 0, "total": len(steps)}

        def on_step(i, total, op, args):
            self.route = {"name": name, "step": i, "total": total}

        async def runner():
            try:
                await self.arm.run_route(
                    text, echo=self.log,
                    should_abort=lambda: self._route_stop,
                    on_step=on_step)
            except asyncio.CancelledError:
                self.log(f"route {name} cancelled", "warn")
                raise
            except Exception as e:                       # noqa: BLE001
                self.log(f"route {name} failed: {e}", "error")
            finally:
                self.route = None

        self._route_task = asyncio.create_task(runner())
        self.log(f"route {name}: {len(steps)} steps")

    # ---- e-stop (never queued) -------------------------------------
    async def _estop(self):
        self._route_stop = True
        if self._route_task is not None and not self._route_task.done():
            self._route_task.cancel()
        try:
            await self.arm.stop("e-stop")
        finally:
            self.route = None
        self.log("E-STOP -- all joints de-energized", "warn")

    # ---- client ----------------------------------------------------
    async def _client(self, ws, path=None):
        self.clients.add(ws)
        self.log(f"client connected ({len(self.clients)} total)")
        try:
            await self._send(ws, {"type": "routes", "items": self._routes()})
            async for raw in ws:
                try:
                    c = json.loads(raw)
                except Exception:                        # noqa: BLE001
                    await self._send(ws, {"type": "error", "msg": "bad json"})
                    continue
                if not isinstance(c, dict) or "cmd" not in c:
                    await self._send(ws, {"type": "error",
                                          "msg": "missing 'cmd'"})
                    continue
                if c["cmd"] == "estop":                  # inline, not queued
                    await self._estop()
                    await self._send(ws, {"type": "ack", "cmd": "estop",
                                          "ok": True})
                    continue
                self.queue.put_nowait((c, ws))
        except Exception:                                # noqa: BLE001
            pass
        finally:
            self.clients.discard(ws)
            self.log(f"client disconnected ({len(self.clients)} left)")

    async def _exit_soon(self, delay=0.25):
        """End run() after a beat, so the shutdown ack gets out first."""
        await asyncio.sleep(delay)
        if self._stop is not None:
            self._stop.set()

    async def _parent_watch(self, pid):
        """If the app that launched us dies -- even by a hard kill -- go with
        it. Otherwise a crashed UI leaves motors energized and ports held."""
        while True:
            await asyncio.sleep(2.0)
            if not parent_alive(pid):
                print("  parent process gone -- shutting down")
                self._stop.set()
                return

    async def run(self, parent_pid=0):
        self._stop = asyncio.Event()
        tasks = [asyncio.create_task(self._telemetry()),
                 asyncio.create_task(self._worker())]
        if parent_pid:
            tasks.append(asyncio.create_task(self._parent_watch(parent_pid)))
        try:
            async with websockets.serve(self._client, self.host, self.port):
                print(f"arm_server: ws://{self.host}:{self.port}  "
                      f"[{'SIM' if self.sim else 'LIVE'}]  "
                      f"joints {sorted(self.arm.specs)}"
                      + (f"  parent={parent_pid}" if parent_pid else ""))
                await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            try:
                await self.arm.stop("server exit")
            except Exception:                            # noqa: BLE001
                pass


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_args(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787,
                   help="WebSocket port (default 8787)")
    p.add_argument("--hz", type=float, default=15.0,
                   help="telemetry broadcast rate (default 15)")
    p.add_argument("--parent-pid", type=int, default=0,
                   help="exit when this process exits (the UI passes its pid)")
    args = p.parse_args()

    if not args.sim and not args.j2_port and not args.no_j2:
        found = guess_esp_port()
        if found:
            args.j2_port = found
            print(f"  J2: autodetected {found}")

    async def go():
        arm = Arm.lazy_from_args(args)       # nothing connects until enabled
        await ArmServer(arm, args.host, args.port,
                        sim=args.sim, hz=args.hz).run(args.parent_pid)

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        print("\nserver stopped")


if __name__ == "__main__":
    main()
