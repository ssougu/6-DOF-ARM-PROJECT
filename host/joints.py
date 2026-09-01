"""
Joint abstraction: one interface over a moteus controller and a
serial-attached stepper, so motion code never knows which is which.

    pip install moteus pyserial

    import asyncio
    from joints import MoteusJoint, StepperJoint, SimJoint

    async def main():
        j1 = MoteusJoint(joint_id=1, moteus_id=1)
        j2 = StepperJoint(joint_id=2, port="COM8")
        try:
            for j in (j1, j2):
                await j.arm()
            await asyncio.gather(j1.move_to(0.1), j2.move_to(-0.05))
            print(await j1.read(), await j2.read())
        finally:
            for j in (j1, j2):
                await j.stop()          # cancels the background keepalive tasks

    asyncio.run(main())

Positions are OUTPUT REVOLUTIONS on both, matching the moteus convention
once rotor_to_output_ratio is configured. The stepper firmware applies
its own GEAR_RATIO so the units line up without the host caring.
"""

import asyncio
import math
from dataclasses import dataclass


@dataclass
class JointState:
    position: float          # output revolutions
    velocity: float          # output rev/s
    moving: bool
    fault: int = 0
    torque: float = 0.0
    voltage: float = math.nan     # bus volts, where the driver reports them
    temperature: float = math.nan  # deg C, ditto

    @property
    def degrees(self) -> float:
        return self.position * 360.0


class Joint:
    """Common interface. Subclasses implement the four underscore methods."""

    def __init__(self, joint_id: int, name: str = ""):
        self.id = joint_id
        self.name = name or f"J{joint_id}"

    async def arm(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError

    async def move_to(self, position: float, velocity=None, accel=None):
        raise NotImplementedError

    async def read(self) -> JointState:
        raise NotImplementedError

    async def hold(self):
        """Servo to the current position and keep holding it (stiff)."""
        raise NotImplementedError

    async def zero(self):
        """Define the current position as 0.0 (output revolutions)."""
        raise NotImplementedError

    async def close(self):
        """Release the underlying link (serial port, etc). Default: nothing."""
        return

    # ---- shared conveniences -------------------------------------
    async def move_to_deg(self, degrees, **kw):
        return await self.move_to(degrees / 360.0, **kw)

    async def wait_until_stopped(self, timeout=30.0, poll=0.02):
        """Poll until the joint reports it is no longer moving."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            st = await self.read()
            if not st.moving:
                return st
            await asyncio.sleep(poll)
        raise TimeoutError(f"{self.name} did not stop within {timeout}s")

    async def move_and_settle(self, position, settle=0.3, **kw):
        await self.move_to(position, **kw)
        st = await self.wait_until_stopped()
        await asyncio.sleep(settle)
        return await self.read()


# ------------------------------------------------------------------
class MoteusJoint(Joint):
    """Wraps a moteus controller. Requires `pip install moteus`.

    Once armed, a background task re-sends the current position target at
    ``control_hz``. The moteus watchdog (``servo.default_timeout_s``, 0.25 s
    on this arm) de-energizes the motor the moment the host stops talking, so
    a move has to be commanded continuously rather than once. ``read()``
    returns the latest telemetry that task captured -- issuing a competing
    query on the same transport would interleave CAN transactions with it.
    """

    def __init__(self, joint_id, moteus_id=1, transport=None, name="",
                 control_hz=50):
        super().__init__(joint_id, name)
        import moteus
        self._moteus = moteus
        self.moteus_id = moteus_id
        self.controller = moteus.Controller(id=moteus_id, transport=transport)
        self._armed = False
        self._last_cmd = None
        self._period = 1.0 / control_hz
        self._target = None          # (pos, vel, accel, max_torque) or None
        self._last = None            # cached moteus result
        self._faulted = 0            # non-zero -> a real fault stopped driving
        self._stream = None          # background asyncio.Task

    def _streaming(self):
        return self._stream is not None and not self._stream.done()

    async def arm(self):
        try:
            await asyncio.wait_for(self.controller.set_stop(), timeout=3.0)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"{self.name}: no response from moteus id {self.moteus_id}. "
                f"Check 24V power, the CAN link, and that nothing else holds "
                f"the adapter.")
        self._armed = True
        self._faulted = 0
        self._target = None
        if not self._streaming():
            self._stream = asyncio.create_task(self._run())

    async def stop(self):
        self._armed = False
        self._target = None
        if self._stream is not None:
            self._stream.cancel()
            try:
                await self._stream
            except asyncio.CancelledError:
                pass
            self._stream = None
        for _ in range(3):
            try:
                await self.controller.set_stop()
                return
            except Exception:                        # noqa: BLE001
                await asyncio.sleep(0.02)

    async def _run(self):
        """Re-assert the active target every period; hold it until it changes."""
        R = self._moteus.Register
        try:
            while True:
                try:
                    if self._target is None:
                        self._last = await self.controller.query()
                    else:
                        pos, vel, acc, mt = self._target
                        kw = dict(position=pos, velocity=0.0, query=True)
                        if vel is not None:
                            kw["velocity_limit"] = vel
                        if acc is not None:
                            kw["accel_limit"] = acc
                        if mt is not None:
                            kw["maximum_torque"] = mt
                        self._last = await self.controller.set_position(**kw)
                    if self._last is not None:
                        f = int(self._last.values.get(R.FAULT, 0))
                        if f and not 100 <= f <= 104:   # 100-104 = torque limit
                            self._faulted = f
                            self._target = None         # stop commanding, keep
                except asyncio.CancelledError:          # querying so read() works
                    raise
                except Exception:                       # noqa: BLE001
                    pass                                # transient; keep last
                                                        # telemetry, retry

                await asyncio.sleep(self._period)
        except asyncio.CancelledError:
            pass

    async def move_to(self, position, velocity=None, accel=None,
                      max_torque=None):
        if not self._armed:
            raise RuntimeError(f"{self.name} not armed")
        if self._faulted:
            raise RuntimeError(f"{self.name} faulted ({self._faulted}) -- "
                               f"re-arm to clear")
        if not self._streaming():                    # self-heal a dead loop
            self._stream = asyncio.create_task(self._run())
        self._last_cmd = position
        self._target = (position, velocity, accel, max_torque)
        for _ in range(4):                           # let the loop report back
            await asyncio.sleep(self._period)
            if self._last is not None:
                break
        return self._to_state(self._last)

    async def hold(self):
        st = await self.read()
        if math.isnan(st.position):
            for _ in range(int(1.0 / self._period) + 5):
                await asyncio.sleep(self._period)
                if self._last is not None:
                    break
            st = self._to_state(self._last)
        if not math.isnan(st.position):
            await self.move_to(st.position)

    async def zero(self):
        resume = self._streaming()
        if resume:
            self._stream.cancel()
            try:
                await self._stream
            except asyncio.CancelledError:
                pass
            self._stream = None
        await self.controller.set_output_exact(position=0.0)
        self._last_cmd = 0.0
        self._target = None
        try:
            self._last = await self.controller.query()   # refresh cache
        except Exception:                                # noqa: BLE001
            self._last = None
        if resume:
            self._stream = asyncio.create_task(self._run())

    async def read(self) -> JointState:
        if self._streaming():
            return self._to_state(self._last)
        try:
            result = await asyncio.wait_for(self.controller.query(),
                                            timeout=2.0)
        except asyncio.TimeoutError:
            return JointState(math.nan, math.nan, False, fault=-1)
        return self._to_state(result)

    def _to_state(self, result) -> JointState:
        if result is None:
            return JointState(math.nan, math.nan, False, fault=-1)
        R = self._moteus.Register
        v = result.values
        pos = v.get(R.POSITION, math.nan)
        vel = v.get(R.VELOCITY, 0.0)
        moving = (abs(vel) > 1e-3) or (
            self._last_cmd is not None
            and not math.isnan(pos)
            and abs(pos - self._last_cmd) > 2e-3
        )
        return JointState(pos, vel, moving,
                          fault=int(v.get(R.FAULT, 0)),
                          torque=v.get(R.TORQUE, 0.0),
                          voltage=v.get(R.VOLTAGE, math.nan),
                          temperature=v.get(R.TEMPERATURE, math.nan))


# ------------------------------------------------------------------
class StepperJoint(Joint):
    """Serial-attached ESP32 running stepper_joint.ino."""

    def __init__(self, joint_id, port, baud=115200, name="", boot_wait=2.0):
        super().__init__(joint_id, name)
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.5)
        self._lock = asyncio.Lock()
        self._keepalive_task = None
        self._boot_wait = boot_wait
        self._ready = False

    async def _cmd(self, line: str) -> dict:
        """Send one line, parse the key=value reply."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            if not self._ready:
                # opening the port resets the ESP32 (DTR). Wait out the boot
                # and drop the "ready joint=2 ..." banner so it isn't parsed
                # as a reply to the first command.
                self._ready = True
                await asyncio.sleep(self._boot_wait)
                await loop.run_in_executor(None, self.ser.reset_input_buffer)
            await loop.run_in_executor(
                None, self.ser.write, (line + "\n").encode())
            raw = await loop.run_in_executor(None, self.ser.readline)
        reply = raw.decode(errors="replace").strip()
        out = {"_raw": reply}
        parts = reply.split()
        if parts:
            out["_status"] = parts[0]
            for p in parts[1:]:
                if "=" in p:
                    k, _, val = p.partition("=")
                    try:
                        out[k] = float(val)
                    except ValueError:
                        out[k] = val
        return out

    async def arm(self):
        r = await self._cmd("A")
        if r.get("_status") not in ("ok", None):
            print(f"  {self.name}: unexpected reply to arm -- {r.get('_raw')!r}"
                  f"\n  (firmware flashed? correct port? DIP switches read only "
                  f"at power-up)")
        # firmware watchdog bites after 250 ms of host silence during a move
        if self._keepalive_task is None:
            self._keepalive_task = asyncio.create_task(self._keepalive())

    async def _keepalive(self):
        try:
            while True:
                await asyncio.sleep(0.1)
                await self._cmd("Q")
        except asyncio.CancelledError:
            pass

    async def stop(self):
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        await self._cmd("S")

    async def zero(self):
        await self._cmd("Z")

    async def hold(self):
        await self._cmd("H")

    async def close(self):
        """Stop, then release COM so the board can be unplugged / re-opened."""
        try:
            await self.stop()
        except Exception:                            # noqa: BLE001
            pass
        try:
            self.ser.close()
        except Exception:                            # noqa: BLE001
            pass

    async def move_to(self, position, velocity=None, accel=None):
        parts = [f"P {position:.5f}"]
        if velocity is not None:
            parts.append(f"{velocity:.4f}")
            parts.append(f"{accel:.4f}" if accel is not None else "0")
        r = await self._cmd(" ".join(parts))
        if r.get("_status") == "err":
            raise RuntimeError(f"{self.name}: {r['_raw']}")
        return self._to_state(r)

    async def read(self) -> JointState:
        return self._to_state(await self._cmd("Q"))

    @staticmethod
    def _to_state(r) -> JointState:
        return JointState(
            position=r.get("pos", math.nan),
            velocity=r.get("vel", 0.0),
            moving=bool(r.get("moving", 0)),
            fault=int(r.get("fault", 0)),
        )


# ------------------------------------------------------------------
class SimJoint(Joint):
    """No hardware. Lets motion and IK code be written before a joint exists."""

    def __init__(self, joint_id, name="", velocity=0.25, quiet=False):
        super().__init__(joint_id, name)
        self.position = 0.0
        self.velocity_limit = velocity
        self.quiet = quiet               # suppress the per-move [sim] line
        self._target = 0.0
        self._t0 = 0.0
        self._armed = False

    async def arm(self):
        self._armed = True

    async def stop(self):
        self._armed = False
        self._target = self.position

    async def hold(self):
        self._target = self.position

    async def zero(self):
        self.position = 0.0
        self._target = 0.0

    async def move_to(self, position, velocity=None, accel=None):
        if not self._armed:
            raise RuntimeError(f"{self.name} not armed")
        v = velocity or self.velocity_limit
        a = accel or 1.0
        d = abs(position - self.position)
        # trapezoidal profile, matching arm.trapezoid_time: triangular when
        # the move is too short to reach cruise speed, else ramp/cruise/ramp.
        dt = 2.0 * math.sqrt(d / a) if d <= v * v / a else v / a + d / v
        if not self.quiet:
            print(f"  [sim] {self.name}: {self.position:+.4f} -> "
                  f"{position:+.4f} rev ({dt:.2f}s)")
        await asyncio.sleep(dt)
        self.position = position
        self._target = position
        return await self.read()

    async def read(self) -> JointState:
        return JointState(self.position, 0.0,
                          abs(self.position - self._target) > 1e-6)


# ------------------------------------------------------------------
async def move_all(joints, targets, **kw):
    """Start every joint together and wait for all of them to land."""
    await asyncio.gather(*(j.move_to(t, **kw)
                           for j, t in zip(joints, targets)))
    return await asyncio.gather(*(j.wait_until_stopped() for j in joints))


if __name__ == "__main__":
    async def demo():
        j1 = SimJoint(1, "J1 base yaw")
        j2 = SimJoint(2, "J2 shoulder")
        for j in (j1, j2):
            await j.arm()
        print("coordinated move:")
        states = await move_all([j1, j2], [0.25, -0.10])
        for j, s in zip((j1, j2), states):
            print(f"  {j.name}: {s.degrees:+.2f} deg")

    asyncio.run(demo())