# J2 shoulder pitch — design brief

**To:** mechanical
**From:** electronics / controls
**Date:** 2026-09-01
**Status:** requirements + open questions. Nothing here is a mechanical
instruction — it's what the control side needs from the joint, and what our
J1 measurements imply about where the error will come from.

> Assumes a **cycloidal** reducer. Sections marked ⚙ are cycloidal-specific; if
> the design goes another way, tell me and I'll revise those.

---

## 1. Why J2 is the hard joint

J1 is characterised and it's the *easy* one — base yaw, no gravity load. Its
numbers:

| Metric | J1 measured |
|---|---|
| Repeatability, random approach | 0.36° |
| Spread under large/fast moves | 0.84° |
| Backlash (direction split) | 0.23° |
| Worst single move | 0.48° |

J2 is worse in every way that matters:

- It **holds the entire arm against gravity**, continuously, at a ~350 mm lever.
- That load is **pose-dependent** — deflection changes with arm position.
- Under sustained torque, printed plastic **creeps**. The error drifts with
  *time*, not just position.

The consequence for controls: **J2's error cannot be calibrated out.** A fixed
offset we can correct in software. A deflection that varies with pose and
creeps over a demo session, we cannot — unless we can measure it.

---

## 2. HARD REQUIREMENT: output-side encoder provision

**This is the only item in this document with a deadline, and the deadline is
"before the part prints."** Retrofitting means reprinting.

We need to measure the **output** angle, after the reduction. The motor's
encoder sits before the gearbox and is blind to backlash, windup and creep —
which is exactly the error we're trying to see.

### What to reserve

- A **Ø10 mm × 5 mm clear volume centred on the output rotation axis**,
  accessible from the static side.
- Mounting bosses for a small PCB (~15 × 15 mm) bridging that space at a
  **1–2 mm standoff** from the magnet face.
- A **Ø6 mm × 2.5 mm counterbore** in the rotating output member for a
  diametrically-magnetised magnet.
- Cable exit route for a 6-conductor ribbon.

### Two tolerances that decide whether it works

1. **Concentricity ±0.25 mm** between the magnet and the true rotation axis.
   Easiest way to hit this: print the magnet counterbore **concentric with the
   output bearing bore, in the same part, in the same orientation**, so
   alignment comes from the print rather than assembly stack-up.
2. **Keep steel bearing races ≥3 mm from the magnet.** Steel distorts the
   field. A non-magnetic bearing at that end also solves it.

Make the sensor standoff **shimmable or slotted** — the 1–2 mm gap is
forgiving, but print tolerances stack.

### The trade this forces

**Cables cannot route through the joint axis.** They have to cross the joint
around the outside with a service loop, or through an off-axis hole in the
rotating structure.

Our soft limits are ±190°, so a service loop is entirely adequate — it's what
most printed arms do. **If routing through the axis is a hard requirement for
your design, say so and we'll drop the encoder on this joint** and absorb the
error in the gripper instead. That's a legitimate outcome; I'd just rather
decide it deliberately than discover it after printing.

```
        ┌─ sensor PCB on a bridge bolted to the static housing
        │
    ╔═══╪═══╗
    ║  [▪]  ║  ← 1–2 mm gap
    ║ ╭───╮ ║
════╣ │mag│ ╠════  ← Ø6 magnet, counterbored, concentric with the axis
    ║ ╰───╯ ║
    ╚═══════╝
   output member (rotating) — arm link bolts to the bolt circle, clearing centre
```

---

## 3. Design driver: **stiffness, not torque**

Please don't optimise this joint for torque. Run the numbers:

- Motor holding torque: **4 N·m** (24HS40-5004D-E1000)
- At any reduction ≥10:1 with ~85% efficiency: **≥34 N·m at the output**

That is far more than the arm needs. **Torque is not the constraint.**

What *is* the constraint is angular deflection under load, because it lands
directly in our error budget:

> **0.1° of deflection at J2 = 0.6 mm of gripper error.**

So where there's a trade between more reduction and more stiffness, **take
stiffness**. Practical levers that matter to us: minimising cantilever on the
output bearing, larger/wider-spaced output bearings, and keeping the load path
through metal (pins, bearings) rather than through plastic in bending.

**Creep is the one to watch.** If the material choice is open, something with
better creep resistance under sustained load than standard nylon is worth
considering — this joint holds torque continuously, not intermittently.

---

## 4. ⚙ Cycloidal-specific notes

Good choice for this joint if it's the direction you're going — the low
backlash is exactly what J1's printed planetary lacks (0.23°).

Three things that affect us:

**a. Two discs, 180° out of phase.** A single cycloidal disc is dynamically
unbalanced and the eccentric produces vibration at input speed. That matters
here beyond noise: we're mounting a **camera on the forearm**, and vibration
degrades both the images and the magnetic encoder reading. If a two-disc
arrangement is feasible, it's worth the complexity.

**b. Backdriveability — please tell us which way this lands.** At high
reduction, cycloidal often isn't backdriveable. That's a genuine trade:

| Non-backdriveable | Backdriveable |
|---|---|
| ✅ Holds pose with no holding current, no heat | ✅ Can hand-position the arm |
| ❌ **Cannot hand-position** — breaks our current homing workflow | ❌ Needs continuous holding current |
| ❌ Can't push the arm away by hand in a fault | ✅ Safer to be near |

Our zeroing procedure today is *"place the arm at home by hand, then zero."*
Non-backdriveable would break that — though an absolute output encoder
(section 2) removes the need for it entirely, so these two decisions interact.

**c. Ratio comes from lobe and pin counts**, so it's exact and computable —
`reduction = N_lobes` when `N_pins = N_lobes + 1`. **Please report the actual
counts.** We have a hard-learned rule about this:

> *CLAUDE.md:* **Trust tooth counts over hand rotation.** A 0.74-turn hand
> rotation gave us a false 11.14:1 against a true 15:1 on J1.

---

## 5. Electrical / integration interface

- **Motor:** NEMA 24, 24HS40-5004D-E1000 (5.0 A, 4 N·m, 1.8°, integrated
  1000-line encoder). Needs its DB15 encoder cable to exit alongside the motor
  leads — please leave room for both connectors, they're bulky.
- **Limit switch:** we'd like one hard limit at a known end of travel, for a
  power-on homing reference and as a mechanical backstop for the safety chain.
  A simple lever microswitch and a mounting boss is enough.
- **Hard stops:** please include physical end stops inside the ±190° range.
  Software limits are our first line, but they are not the last one.
- **Cable service loops:** enough slack for ±190° of travel without tension on
  any connector. Connector fatigue from repeated flexing is a failure mode we'd
  like to design out rather than debug at the fair.

---

## 6. What we need back from you

To finish the firmware and the kinematics, these are blocking:

| Item | Why we need it | Blocking |
|---|---|---|
| **Exact reduction ratio** (lobe + pin counts) | `GEAR_RATIO` in `firmware/j2_stepper/src/main.cpp` is still a placeholder **15**. Every J2 angle we command is wrong until this is real | Any accurate J2 motion |
| **Link length, J2 axis → J3 axis** | Forward kinematics and the whole error budget | IK, vision calibration |
| **Mass + CG of everything distal to J2** | Sizing check and sag prediction | Nothing yet, but wanted |
| **Is the output axis end free?** (section 2) | Decides encoder yes/no on this joint | The gearbox print |
| **Backdriveable?** (section 4b) | Decides the homing workflow | Firmware homing routine |
| **Travel limits** | Soft limits are currently ±190° placeholders | Safety config |

---

## 7. Open questions from our side

1. Is a two-disc (balanced) arrangement feasible, or does packaging rule it out?
2. Is there room for the encoder bridge on the output face without fouling the
   link's bolt circle?
3. Do you want the limit switch to trip at one end of travel, or both?
4. Has anything been printed yet? **If J2's gearbox hasn't printed, section 2
   is free to add. If it has, tell me and we'll plan a bolt-on retrofit
   instead** — that's what we're doing for J1, which is already built and which
   we've decided *not* to reprint.

---

## Summary — the one thing that matters most

If you take nothing else from this: **reserve the space on the output axis for
the encoder before this part prints.** It costs a counterbore and two bosses
now. It costs a reprint later.

Everything else here is a preference or a question. That one has a deadline.
