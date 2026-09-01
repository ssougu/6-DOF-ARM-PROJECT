# Parts list

As of 2026-09-01. Prices are rough USD and will vary — treat them as budgeting
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
