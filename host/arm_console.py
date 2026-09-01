#!/usr/bin/env python3
"""
arm_console.py -- interactive console for J1 + J2 as one arm.

    python arm_console.py --sim                     # no hardware
    python arm_console.py --j2-port COM8            # real J1 + J2
    python arm_console.py --sim -c "arm" -c "move 20 -15" --exit

=============================  HOW TO STOP  =============================
  ENTER on an empty line  ->  e-stop, latches       ('arm' to re-enable)
  Ctrl-C                  ->  e-stop + exit
  A blank line typed while a move or route is running cancels it and
  e-stops. The moteus (0.25 s) and stepper (0.25 s) watchdogs also
  de-energize on their own if this program dies. The XT30 is the only
  stop that needs no software -- keep it in reach.
=======================================================================

Moves are synchronised across joints (see arm.py). Angles here are degrees;
internally everything is output revolutions.
"""

import argparse
import asyncio
import shlex
import sys
import threading
from pathlib import Path

from arm import Arm, add_args, parse_route


HELP = """
 STOPPING
  <ENTER>            *** E-STOP (latches) ***      arm       energize + hold
  stop / disarm      e-stop                        quit      stop and exit

 MOVING  (degrees; synchronised so joints start and finish together)
  home                       synchronised move to the home pose
  move <j1> <j2>             J1 and J2 to absolute angles
  j / movej <id> <deg>       one joint, absolute
  jog <id> <ddeg>            one joint, relative
  speed <0.02..1>            global fraction of each joint's velocity limit

 SETUP
  enable <id> / disable <id> switch a joint on/off (disable de-energizes it
                             and drops it out of every move)
  zero [id...] yes           define the current pose as home (place by hand)
  status                     one telemetry line per joint
  watch [hz]                 live telemetry; ENTER stops it (and e-stops)

 ROUTES / SCRIPTING
  route <file>               play a route file (move/movej/jog/home/wait/
                             speed/echo; see routines/demo.txt)
  wait <s>                   pause
  echo <text>                print a marker
  Non-interactive (these run CONSOLE commands, so include 'arm'):
    python arm_console.py --sim -c "arm" -c "move 20 -15" --exit
    python arm_console.py --sim --script my_console_script.txt
  Or play a route straight through, no console:
    python arm.py --sim --route routines/demo.txt
"""


def _start_stdin_reader(loop, queue):
    def reader():
        for line in sys.stdin:
            loop.call_soon_threadsafe(queue.put_nowait, line.rstrip("\n"))
        loop.call_soon_threadsafe(queue.put_nowait, None)
    threading.Thread(target=reader, daemon=True).start()


class Console:
    def __init__(self, arm, preload=None, batch=False):
        self.arm = arm
        self.preload = list(preload or [])
        self.batch = batch
        self.quit = False
        self.queue: asyncio.Queue = asyncio.Queue()
        self.echo_left = len(self.preload)
        # only a real terminal can send a mid-move "blank line = panic"; a
        # piped stdin is buffered, so treat it like a script and just run
        # each command to completion (Ctrl-C still works).
        try:
            self.interactive = sys.stdin.isatty()
        except Exception:                               # noqa: BLE001
            self.interactive = False

    # ---- helpers -------------------------------------------------
    def _joint(self, tok):
        jid = int(tok)
        if jid not in self.arm.specs:
            raise ValueError(f"no joint {jid} on this arm "
                             f"(have {sorted(self.arm.specs)})")
        if jid not in self.arm.active_ids:
            raise ValueError(f"J{jid} is disabled -- 'enable {jid}' first")
        return jid

    async def _status(self):
        for j in (await self.arm.snapshot())["joints"]:
            if not j["enabled"]:
                print(f"  {j['name']:<18} {'OFF':>8}   (disabled)")
                continue
            if j["deg"] is None:
                print(f"  {j['name']:<18} {'--':>8}   (no telemetry)")
                continue
            extra = ""
            if j["voltage"] is not None:
                extra = f"  {j['voltage']:.1f}V {j['temp']:.0f}C"
            print(f"  {j['name']:<18} {j['deg']:+8.2f} deg  "
                  f"vel {j['vel_dps']:+7.2f} deg/s  "
                  f"moving={int(j['moving'])}  fault={j['fault']}{extra}")

    def _report_move(self, want_deg, states):
        for jid, want in want_deg.items():
            if jid not in states:
                print(f"  {self.arm.axes[jid].name:<18} skipped (disabled)")
                continue
            got = states[jid].degrees
            print(f"  {self.arm.axes[jid].name:<18} "
                  f"-> {want:+.2f} deg   landed {got:+.2f}   "
                  f"err {got - want:+.3f}")

    async def _watch(self, hz):
        if not self.interactive:
            await self._status()
            return
        print("streaming -- ENTER stops and e-stops")
        while self.queue.empty():
            line = "  " + " | ".join(
                f"{self.arm.axes[j].name.split()[0]} {s.degrees:+7.2f}"
                for j, s in (await self.arm.read()).items())
            print("\r" + line + "   ", end="", flush=True)
            await asyncio.sleep(1.0 / hz)
        await self.queue.get()
        print()
        await self.arm.stop("panic")

    # ---- dispatch ----------------------------------------------
    async def _exec(self, line):
        try:
            parts = shlex.split(line)
        except ValueError as e:
            print(f"parse error: {e}")
            return
        if not parts:
            return
        cmd, rest = parts[0].lower(), parts[1:]
        try:
            if cmd in ("quit", "exit"):
                await self.arm.stop("exiting")
                self.quit = True

            elif cmd in ("help", "?"):
                print(HELP)

            elif cmd == "arm":
                await self.arm.arm()
                await self.arm.hold()
                print("armed + holding")
                await self._status()

            elif cmd in ("stop", "disarm"):
                await self.arm.stop("commanded")

            elif cmd == "status":
                await self._status()

            elif cmd in ("enable", "disable"):
                jid = int(rest[0])
                if jid not in self.arm.specs:
                    print(f"  no joint {jid} (have {sorted(self.arm.specs)})")
                    return
                if cmd == "enable":
                    await self.arm.enable(jid)
                    print(f"  J{jid} enabled"
                          + ("  (armed + holding)" if self.arm.armed else ""))
                else:
                    await self.arm.disable(jid)
                    print(f"  J{jid} disabled -- de-energized and dropped "
                          f"from moves")
                await self._status()

            elif cmd == "speed":
                self.arm.speed = max(0.02, min(1.0, float(rest[0])))
                print(f"speed {self.arm.speed:g}  "
                      f"(x each joint's velocity limit)")

            elif cmd == "zero":
                confirm = bool(rest) and rest[-1].lower() == "yes"
                ids = [int(x) for x in rest if x.lstrip("-").isdigit()] or None
                if not confirm:
                    who = "all joints" if ids is None else \
                        ", ".join(f"J{i}" for i in ids)
                    hint = " ".join(str(i) for i in ids) if ids else "all"
                    print(f"  'zero' redefines the CURRENT pose of {who} as "
                          f"home (0).")
                    print(f"  Place the arm where home should be, then:  "
                          f"zero {hint} yes")
                    return
                await self.arm.zero(ids)

            elif cmd == "home":
                await self.arm.home()
                await self._status()

            elif cmd == "move":
                a, b = float(rest[0]), float(rest[1])
                st = await self.arm.move_deg({1: a, 2: b})
                self._report_move({1: a, 2: b}, st)

            elif cmd in ("j", "movej"):
                jid, d = self._joint(rest[0]), float(rest[1])
                st = await self.arm.move_deg({jid: d})
                self._report_move({jid: d}, st)

            elif cmd == "jog":
                jid, dd = self._joint(rest[0]), float(rest[1])
                cur = (await self.arm.read())[jid].degrees
                st = await self.arm.move_deg({jid: cur + dd})
                self._report_move({jid: cur + dd}, st)

            elif cmd == "route":
                if not rest:
                    print("route <file>")
                    return
                text = Path(rest[0]).read_text()
                parse_route(text)                    # validate before arming
                await self.arm.run_route(text)

            elif cmd == "wait":
                await asyncio.sleep(float(rest[0]) if rest else 1.0)

            elif cmd == "echo":
                print(" ".join(rest))

            elif cmd == "watch":
                await self._watch(float(rest[0]) if rest else 4.0)

            else:
                print(f"unknown: {cmd}   (try 'help')")

        except IndexError:
            print(f"  '{cmd}': missing argument (try 'help')")
        except ValueError as e:
            print(f"  {e}")
        except Exception as e:                           # noqa: BLE001
            print(f"  error: {e}")

    # ---- main loop --------------------------------------------
    async def run(self):
        loop = asyncio.get_running_loop()
        for ln in self.preload:
            self.queue.put_nowait(ln)
        if self.batch:
            self.queue.put_nowait(None)
            print(f"batch: {len(self.preload)} command(s)\n")
        else:
            _start_stdin_reader(loop, self.queue)
            if self.preload:
                print(f"running {len(self.preload)} command(s), then the "
                      f"prompt ('help' for commands)\n")
            else:
                print(HELP)

        race = self.interactive and not self.batch
        while not self.quit:
            print("arm> ", end="", flush=True)
            line = await self.queue.get()
            if line is not None and self.echo_left > 0:
                print(line)
                self.echo_left -= 1
            if line is None:
                await self.arm.stop("stdin closed")
                self.quit = True
                break
            if line.strip() == "":
                await self.arm.stop("panic")
                continue

            # paste guard: if several lines landed at once, run only the first
            # and drop the rest. Chaining pasted motion commands unattended is
            # how you drive the arm into something.
            if race and not self.queue.empty():
                dropped, hit_eof = [], False
                while not self.queue.empty():
                    try:
                        x = self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if x is None:
                        hit_eof = True
                    elif x.strip():
                        dropped.append(x)
                if dropped:
                    print(f"  {len(dropped) + 1} lines pasted at once -- "
                          f"running only '{line}'.\n  Re-enter the rest one at "
                          f"a time: {', '.join(repr(d) for d in dropped)}")
                if hit_eof:
                    self.quit = True

            task = asyncio.create_task(self._exec(line))
            if race:
                await self._race_panic(task)
            else:
                try:
                    await task
                except Exception as e:                    # noqa: BLE001
                    print(f"error: {e}")

    # commands that are safe to run after the current one finishes; anything
    # else typed while the arm is busy is DISCARDED, not queued -- pasting a
    # block of moves must never chain into an unattended motion sequence.
    REPLAY_OK = {"status", "stop", "disarm", "help", "?", "echo"}

    async def _race_panic(self, task):
        """Run `task` while still watching a live terminal.

        A blank line cancels the task and e-stops. EOF (Ctrl-D) exits after
        the task finishes. A safe follow-up command is replayed when the task
        ends; a motion/arm/zero command typed while busy is refused -- type
        those one at a time.
        """
        stash = []
        eof = False
        getter = None
        while not task.done():
            if getter is None and not eof:
                getter = asyncio.create_task(self.queue.get())
            waits = {task} | ({getter} if getter is not None else set())
            done, _ = await asyncio.wait(
                waits, return_when=asyncio.FIRST_COMPLETED)
            if getter is not None and getter in done:
                nxt = getter.result()
                getter = None
                if nxt is None:
                    eof = True
                    self.quit = True
                elif nxt.strip() == "":
                    await self.arm.stop("panic")
                    task.cancel()
                    stash.clear()          # don't replay commands after a panic
                elif nxt.split() and nxt.split()[0].lower() in self.REPLAY_OK:
                    print(f"  (busy -- '{nxt}' queued)")
                    stash.append(nxt)
                else:
                    print(f"  IGNORED '{nxt}' -- arm is busy; run motion "
                          f"commands one at a time (blank line = e-stop)")
        if getter is not None:
            getter.cancel()
            try:
                await getter
            except asyncio.CancelledError:
                pass
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:                            # noqa: BLE001
            print(f"error: {e}")
        for s in stash:
            self.queue.put_nowait(s)


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_args(p)
    p.add_argument("-c", "--cmd", action="append", default=[], metavar="CMD",
                   help="run a console command (repeatable)")
    p.add_argument("--script", metavar="FILE",
                   help="run console commands from a file")
    p.add_argument("--exit", dest="exit_after", action="store_true",
                   help="with -c/--script, exit when the commands finish")
    args = p.parse_args()

    preload = list(args.cmd)
    if args.script:
        for raw in Path(args.script).read_text().splitlines():
            raw = raw.split("#", 1)[0].strip()
            if raw:
                preload.append(raw)
    batch = bool(preload) and args.exit_after

    async def _go():
        # build the arm INSIDE the event loop -- the moteus fdcanusb transport
        # spawns a reader task on construction and is dead if no loop is running
        arm = Arm.from_args(args)
        try:
            await Console(arm, preload=preload, batch=batch).run()
        finally:
            try:
                await arm.stop("bye")
            except Exception:                            # noqa: BLE001
                pass

    try:
        asyncio.run(_go())
    except KeyboardInterrupt:
        print("\n^C -- watchdogs de-energize within 0.25 s")


if __name__ == "__main__":
    main()
