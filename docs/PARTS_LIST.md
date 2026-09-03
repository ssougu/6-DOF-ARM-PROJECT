# Parts list

As of 2026-09-03 (bench electronics added). Prices are rough USD and will vary — treat them as budgeting
figures, not quotes.

## Already owned — do not re-buy

| Item | Qty | Use |
|---|---|---|
| moteus r4.11 + mj5208 | 2 | J1 (built), **J3** |
| 24HS40-5004D-E1000 + CL57T | 1 | J2 |
| FEETECH STS3215 | 2 | J5, J6 |
| ESP32 dev board | 1 | J2 step generation (can take J4 too) |
| RealSense depth camera | 1 | perception |
| mjcanfd-usb-1x | 1 | moteus link |

⚠️ **The spare moteus is consumed by J3.** After that there is no spare
controller for debugging — worth knowing before something dies.

---

## Tier 1 — buy now (unblocks the fair demo)

### 1. Bus servo adapter — **highest priority, cheapest unblock**

| | |
|---|---|
| **Waveshare Serial Bus Servo Driver Board** *or* FEETECH FE-URT-1 | 1 × ~$12 |

Gets J5/J6 running on the existing Python stack with **no microcontroller
work at all**. Half-duplex TTL, plugs into USB. Buy this first.

⚠️ Both STS3215 ship as **id 1**. Set ids individually before daisy-chaining.

### 2. J4 stepper + driver

| | |
|---|---|
| Closed-loop stepper + matching driver (ships together) | 1 × ~$90–130 |

**Frame size is a mechanical decision I can't make for you.** Matching J2's
NEMA 24 keeps spares and firmware identical — but a NEMA 24 is ~1.1 kg, and at
J4 that mass sits ~250 mm out from the shoulder, adding roughly **2.7 kg·m of
moment on J2**, which then needs a stiffer gearbox. A NEMA 17 or 23 closed-loop
kit may serve better. **Ask the ME before ordering.**

Whatever you pick, get the closed-loop version with an integrated encoder —
same reasoning as J2.

### 3. Output encoders — J2 and J3

| | |
|---|---|
| AS5048A magnetic encoder breakout | 2 × ~$12 |
| Diametric magnet, 6 mm ⌀ × 2.5 mm | 4 × ~$1 (2 spares) |

⚠️ **The magnet must be *diametrically* magnetised**, not axial. They look
identical; axial simply does not work. Search the word "diametric" explicitly.
Many breakouts include a correct magnet — check before buying separately.

Budget alternative: **MT6701** breakout, also 14-bit, ~$5. Fine if buying
several; less documentation than the ams part.

❌ **Do not buy the AS5600.** 12-bit only, and its fixed I²C address (0x36)
makes multiple units impossible without a mux.

### 4. Power — **check this before it bites you**

Current supply is a **24 V 5 A** dev brick. That is not enough for the full arm:

| Load | Rough supply draw |
|---|---|
| 2 × moteus/mj5208 @ 24 V | ~4–6 A peak |
| 2 × NEMA-class steppers (chopper drives, ~60% of phase current) | ~6 A |
| 2 × STS3215 @ 12 V | ~2–4 A stall |

| | |
|---|---|
| Meanwell **LRS-350-24** (24 V, 14.6 A) — or LRS-600-24 for headroom | 1 × ~$35–60 |
| 12 V rail for the servos: LRS-100-12 **or** a 24→12 V buck (≥5 A) | 1 × ~$12–25 |

Verify against your real duty cycle — these are estimates, and steppers draw
most when holding, not moving.

### 5. Wire and cable

| | |
|---|---|
| Shielded 6-conductor cable, ~3 m (encoder SPI runs) | ~$10 |
| Silicone **stranded** hook-up wire, 22–24 AWG assortment | ~$15 |
| JST-XH / Dupont connector kit + crimper | ~$25 |
| Braided sleeving + spiral wrap | ~$10 |

⚠️ **Stranded, flex-rated wire only** for anything crossing a joint. Solid core
work-hardens and snaps. Connector fatigue at moving joints is the most likely
thing to fail at the fair.

**Tier 1 subtotal: roughly $250–350**, dominated by the stepper and PSU.

---

## Tier 2 — buy when Phase 1 (safety chain) starts

| Item | Qty | ~Cost |
|---|---|---|
| **Teensy 4.1** (PJRC) | 1 | $32 |
| **CAN-FD** transceiver breakout — TCAN334G or MCP2562FD | 1 | $8 |
| E-stop button, latching mushroom, NC contacts | 1 | $10 |
| Mechanical lever limit switches | 4–6 | $6 |
| 120 Ω resistors (CAN bus termination) | 2 | — |

⚠️ **The transceiver must be a CAN-FD part.** SN65HVD230 and TJA1051 are
classic-CAN only — they appear to work at low rate and then fail at moteus's
5 Mbps data phase. This is the easiest thing on the list to get wrong.

Teensy 4.0 would also work (2 steppers, 2 CAN nodes fit easily); 4.1 is chosen
for the extra I/O, SD slot and Ethernet headroom for ~$10 more.

---

## Bench electronics — the prototyping layer

Everything needed to actually build the Teensy stage on a bench before any
PCB exists. Roughly **$90–120** all in, most of it reusable across projects.

### The controller and its accessories

| Item | Qty | ~Cost | Note |
|---|---|---|---|
| **Teensy 4.1** | 1 | $32 | **Ships with no headers soldered** |
| Male header strip, 24-pin 0.1" | 2 | $2 | Or buy the pre-soldered "with pins" version |
| Female header strip, 24-pin | 2 | $2 | **Socket it** — see below |
| USB **micro-B** cable | 1 | $4 | Not USB-C. Teensy 4.1 is micro-B |

**Socket the Teensy rather than soldering it into anything.** It is the most
expensive single part on the bench and the one most likely to be killed by a
wiring mistake — 3.3 V pins, not 5 V tolerant. Female headers on the board,
male pins on the Teensy, and a blown MCU costs $32 and five minutes instead of
a rebuild. This is also the architecture's stated PCB plan (a carrier board
with the Teensy socketed), so prototyping the same way keeps the transition
honest.

### Breadboard and wiring

| Item | Qty | ~Cost |
|---|---|---|
| Large breadboard, 1660-point or bigger (2220/3220 "giant" is fine) | 1 | $12 |
| Pre-formed solid-core jumper kit (350 pc, assorted lengths) | 1 | $8 |
| Dupont jumpers M–M / M–F / F–F, 20 cm | 1 set | $7 |
| Twisted pair wire for CANH/CANL (or pull a pair from Cat5) | — | ~$0 |

Teensy 4.1 is 0.7" wide with 24 pins a side, so it straddles the centre
channel leaving one free row each side. Comfortable.

⚠️ **A breadboard is the wrong home for CAN-FD at 5 Mbps.** No controlled
impedance, a few pF per contact, and every stub is a reflector. It will
probably survive a bench bring-up if you keep the transceiver within a few cm
of the Teensy and twist CANH/CANL, but do not conclude anything about signal
integrity from it, and do not build the demo on it. Steppers, servos, limit
switches and the ALM inputs are all perfectly happy on breadboard.

Also: **no motor current through the breadboard, ever.** Those rails are good
for a couple of amps at best, and the contacts are a resistance you cannot see.

### Resistors — what each one is actually for

An **E12 assortment kit** (~$10, 10 Ω–1 MΩ, 1/4 W) covers nearly all of it.
Buy 120 Ω separately if the kit lacks it — it usually does, and it is the one
value that must be right.

| Value | Qty | Where it goes |
|---|---|---|
| **120 Ω** ¼ W | 2 | CAN-FD termination, one at each **physical end** of the bus |
| **10 kΩ** | 4 | CL57T **ALM pull-ups** to 3.3 V — one per stepper driver, plus spares |
| 10 kΩ | 6 | Limit-switch pull-ups (optional — the Teensy has internal ones) |
| 100 Ω | 6 | Series damping on long SPI runs to the AS5048A encoders |
| 330 Ω – 1 kΩ | 6 | Status LEDs, if you add any |

⚠️ **Check whether the far-end moteus already terminates the CAN bus** before
adding a second 120 Ω. Two terminators is correct; three is not, and an
over-terminated bus fails in ways that look like software.

The **ALM pull-ups are the ones to fit first.** One 10 kΩ resistor and one
wire per driver turns J2's fabricated `fault=0` into real fault reporting,
and the entire software path already exists.

### Passives and interface parts

| Item | Qty | ~Cost | Why |
|---|---|---|---|
| 100 nF ceramic capacitors | 20 | $3 | One at every IC's supply pin. Not optional |
| 10 µF / 100 µF electrolytic | 5 | $3 | Bulk on each rail |
| **74HCT244** or **74HCT245** | 2 | $2 | 3.3 V → 5 V buffer for step/dir, if needed |
| 74HC125 / 74HC126 | 2 | $2 | Half-duplex direction control, if the servo bus ever moves off the USB adapter |

On the buffer: the architecture doc is right that the CL57T's opto inputs are
current-driven and the existing common-anode pattern carries over from the
ESP32 — it is already proven on J2. Worth knowing the marginal case, though:
with PUL+ at 5 V and the MCU pin idling at 3.3 V, the opto still sees ~1.7 V,
which is above its LED forward voltage. It evidently stays below the turn-on
threshold in practice, but if you ever chase phantom steps, that is the first
thing to suspect, and a 74HCT244 driving PUL+ with PUL− grounded gives a clean
full-swing 0–5 V drive instead.

### Safety chain

| Item | Qty | ~Cost |
|---|---|---|
| Latching mushroom E-stop, **NC** contacts | 1 | $10 |
| Mechanical lever limit switches | 4–6 | $6 |
| **Relay or contactor rated for the motor supply** | 1 | $12–25 |

⚠️ **An e-stop that only tells software to stop is not an e-stop.** The button
must break motor power, or at minimum the drivers' enable lines, through
hardware that works with the firmware hung. The existing software e-stop is a
convenience feature, not a safety one, and should not be described as one at
the fair.

### Test gear

| Item | ~Cost | Why |
|---|---|---|
| **8-channel USB logic analyzer** (24 MHz clone) | $12 | The best $12 on this list |
| Multimeter | — | Presumably owned |
| Oscilloscope | — | **Use the CSUF lab** — needed for CAN-FD eye quality, not worth buying |

The logic analyzer directly answers an open question: **step timing jitter has
never been measured.** Clip it on PUL/DIR and you can see the pulse train the
ESP32 actually produces, idle versus under CUDA load, and whether the step
interval holds. That is open question 6 and part of the latency work, settled
for the price of lunch. It also decodes the STS3215 serial bus and the CL57T
handshake when something refuses to talk.

Its 24 MHz sampling is **not** enough for CAN-FD's 5 Mbps data phase — that
needs the lab scope.

---

## Not specified — decisions still open

| Item | Blocked on |
|---|---|
| **Gripper** | Not designed. Needs to be **self-centring, 15–20 mm compliance** — see `VISION_APPROACH.md`. This is the single highest-leverage mechanical decision left |
| Camera mount hardware | Depends on the forearm CAD |
| J3–J6 gearbox materials / bearings | Mechanical |
| Encoders for J4 | Marginal value (short lever arm) — design the pocket, decide later |

---

## Costs nothing — do these anyway

- **Wire the CL57T ALM output.** One wire + a pull-up resistor you already own.
  The whole software path (`fault=` telemetry → `Arm.move()` abort → GUI fault
  chip) already exists. Highest value-per-effort item open.
- **Encoder mounting provisions in the gearbox CAD.** Free before printing,
  a reprint after. See `J2_DESIGN_BRIEF.md`.
- **`python joint_setup_v2.py --id 1 --sync`** — J1's tuning currently exists
  only in that board's flash.

---

## Suggested order

1. **Bus servo adapter** — cheapest, unblocks 2 of 6 joints immediately
2. **Power supply** — everything else is limited by it
3. **Encoders + magnets** — cheap, and the mechanical provision decision
   depends on committing to them
4. **J4 stepper** — after the ME confirms frame size
5. Tier 2 when the safety chain work begins

### If you are ordering the Teensy bench kit now

Reasonable to pull forward — it is cheap, has long shipping lead times from
PJRC, and none of it is blocked on a mechanical decision. One basket:

| | |
|---|---|
| Teensy 4.1 + male and female headers + micro-B cable | ~$40 |
| CAN-FD transceiver breakout (TCAN334G / MCP2562FD) | $8 |
| Large breadboard + jumper kit + Dupont set | ~$27 |
| E12 resistor assortment + 120 Ω separately | ~$12 |
| 100 nF / electrolytic capacitor assortment | ~$6 |
| 74HCT244 ×2, 74HC125 ×2 | ~$4 |
| 8-channel USB logic analyzer | ~$12 |
| E-stop button + limit switches + relay | ~$30 |
| **Total** | **~$140** |

⚠️ **The transceiver is the one item on this list you can get wrong without
noticing.** It must be a CAN-**FD** part. SN65HVD230 and TJA1051 are
classic-CAN only: they work at low bit rates and fail at moteus's 5 Mbps data
phase, which presents as intermittent bus errors rather than an obvious fault.

**Two 10 kΩ resistors from this kit are worth using the day it arrives** — the
CL57T ALM pull-ups. That is the highest value-per-effort item still open.
