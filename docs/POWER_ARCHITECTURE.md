# Power Architecture

Power distribution and signal conditioning for the 6-DOF arm. Covers the 36 V bus
decision, rail tree, regeneration handling, and the combined PDB + MCU board.

**Status:** decided, not built. No board has been fabricated. Numbers marked
*estimate* have not been measured.

---

## Decisions at a glance

| Decision | Value | Driver |
| --- | --- | --- |
| Bus voltage | **36 V** | Only voltage inside both driver windows |
| Board | Combined PDB + Teensy, single PCB | Deadline is soft; fewer cables |
| Stackup | 4 layer, 2 oz outer / 1 oz inner | Current, not routing density |
| Regen sink | Firmware (`max_regen_power_W`) | moteus does it internally; no chopper |
| Host link | One cable, laptop → Teensy | Laptop keeps vision only |
| Assembly | Hand populated | No package finer than SOIC / SOT-23 |

---

## 1. Bus voltage

### Why not 48 V

The moteus r4.11 is rated **10–44 V (≤10S)**. A 48 V nominal bus sits above the
board's absolute rating, not merely above its comfortable range. Going to 48 V
would mean replacing both BLDC controllers (n1 is 10–54 V, c1 is 10–51 V), not
changing a power supply.

### Why 36 V specifically

| Device | Operating range | Notes |
| --- | --- | --- |
| moteus r4.11 | 10–44 V | Hard ceiling |
| CL57T (V4.1) | 18–50 V, recommended 24–48 V | Manual names 36 V as the ideal |
| STS3215 (C047) | 4–14 V | Bucked down, not on the bus |

The CL57T manual recommends a 36 VDC supply explicitly, to leave room for line
fluctuation and back-EMF. 36 V is the midpoint of the 24–44 V window where both
motor drivers are inside spec. This is not a compromise — it is the intersection.

**Consequence:** regen headroom is 44 − 36 = **8 V**. That is tight, and it is
why section 3 exists.

---

## 2. Rail tree

```
36 V supply
  └── input protection (fuse, reverse-polarity FET, TVS, NTC inrush)
        ├── ALWAYS LIVE ─────────────────────────────┐
        │     ├── 36→5 V buck (3 A)                  │  logic, buffers,
        │     │     └── 5→3.3 V LDO (1 A)            │  transceiver, fans,
        │     │                                      │  display, Teensy
        │     └── e-stop loop + contactor coil       │
        │                                            │
        └── E-STOP CONTACTOR ────────────────────────┘
              ├── 36 V → moteus chain (J1, J3)   XT30PW-M, daisy chained
              ├── 36 V → CL57T J2                separate home-run
              ├── 36 V → CL57T J4                separate home-run
              └── 36→12 V buck (6 A) → STS3215 J5/J6
```

**Logic sits upstream of the contactor.** An e-stop must kill motor power while
the Teensy stays alive to report the fault and hold state. If the whole bus drops,
the MCU resets and re-enable becomes a lurch.

**The CL57T home-runs are not optional.** The manual states directly that power
input pins must not be daisy-chained between drives; each connects to the supply
separately to avoid cross interference. The moteus is the opposite — it is
*designed* to chain, with doubled power and data connectors.

---

## 3. Regeneration — the primary hazard

A gravity-loaded arm back-drives. Any joint descending under load pumps energy
into the bus, and a mains supply cannot sink it. With 8 V of headroom this is the
failure mode most likely to damage hardware.

### moteus handles this in firmware

`servo.max_regen_power_W` caps how much regenerated power reaches the bus; the
excess is dissipated in the motor windings via injected d-axis current. Setting
it to `0` keeps essentially all regen out of the bus. mjbots' guidance for a
mains supply with no bus capacitance is a small value — `10` or `0`.

**This replaces a brake chopper entirely.** No hardware required.

Two conditions:

1. **Acceleration limits are required for it to work.** `servo.default_accel_limit`
   controls how fast braking torque ramps; `max_regen_power_W` mops up the rest.
   Without an accel limit, regen can outrun the mechanism.
2. **The energy becomes heat in the motor**, up to `1.5 · I² · R` sustained.
   This lands on the thermal budget, it does not disappear.

### The cross-coupling nobody plans for

J1 and J3 regen onto a bus shared with J2 and J4. The CL57T has its own
overvoltage protection, so a hard reversal on a moteus joint **can fault a
stepper driver that did nothing wrong**. The symptom is J2 dropping out during a
coordinated move, which is extremely hard to diagnose from the outside.

Setting `max_regen_power_W` near zero protects both. Do not "optimise" it back up
without understanding this.

### Bulk capacitance has a ceiling

Total system capacitance must stay **≤ 4000 µF** if using a mjbots power_dist or
mjpower-ss, and whatever inrush solution is used must tolerate whatever is added.
Size the cap bank and the inrush circuit together.

### The TVS cannot help

A TVS with a 36 V standoff does not break down until ~40 V and clamps near 58 V —
above the moteus limit. **No TVS fits inside a 36–44 V window**; the
standoff-to-clamp ratio of the technology is wider than the available headroom.

The input TVS is for hot-plug spikes and external transients only. Regen
protection is entirely `max_regen_power_W` plus accel limits.

---

## 4. Per-branch notes

### moteus (J1, J3) — CAN-FD

| Item | Value |
| --- | --- |
| Power connector | 2× XT30PW-M (chains through) |
| Data connector | 2× JST PH-3 (chains through) |
| Bus rate | 5 Mbps CAN-FD |
| Board connectors needed | **One** XT30 + **one** PH-3 for both controllers |

- One controller per motor. There is no multi-axis variant.
- Teensy **CAN3 (pins 30/31) is the only FD-capable bus.** CAN1 and CAN2 are
  classic CAN only. This fixes connector placement.
- Requires an external transceiver — the Teensy peripheral is logic level.
  TJA1051T/3 is what mjbots names. **It needs both 5 V (VCC) and 3.3 V (VIO).**
- Termination: 120 Ω at each physical end, never zero. Near end on our board
  with a jumper; far end via a mjbots PH-3 terminator on J3.
- Official Arduino support exists: `MoteusTeensy.h` in `mjbots/moteus-arduino`,
  backed by ACAN_T4.
- **Calibration cannot be done from the Teensy.** It needs `moteus_tool` on a
  desktop with a CAN-FD adapter. Only dev-kit controllers ship pre-calibrated,
  so a separately purchased controller for J3 must be calibrated before use.

**Therefore the board carries a second PH-3 as a debug CAN tap**, plus a GPIO on
the transceiver standby pin so the Teensy can go silent while `moteus_tool` runs.
Without this, calibration means disassembling the harness.

### CL57T (J2, J4) — step/dir

| Parameter | Value |
| --- | --- |
| Operating voltage | 18–50 V (rec. 24–48 V) |
| Logic input current | **7 mA min, 10 typ, 16 max** |
| Max pulse frequency | 500 kHz |
| Min pulse width | 1.0 µs |
| DIR setup before PUL | 2 µs |
| Brake output | 24 V / 100 mA, needs relay + diode |
| Alarm output | sink or source 100 mA at 5–24 V, 30 V max |
| Operating temperature | **0–40 °C**, vertical mount, 30 mm between drives |

**S3 selector — destroys hardware if wrong.** Factory setting is 24 V. The manual
states that with signals at 24 V, selecting 5 V on S3 will damage the input
photocoupling. Set S3 to **5 V** on both drives, label them physically, and put
it in the bring-up checklist before anything is wired.

**Drive current is why a buffer is mandatory.** Teensy pins cannot supply 7–16 mA
into an optocoupler. The troubleshooting table lists "control signal too weak"
against that exact window as a cause of erratic motion.

- Use **one 74ACT244** (SOIC-20W). It is an octal buffer in two independent
  4-bit banks with separate OE — J2 in one bank, J4 in the other, one spare
  channel each, and per-axis output enable for the watchdog.
- 74HCT244 is *not* sufficient: ~±6 mA guaranteed drive is below the 7 mA minimum.
  ACT gives ±24 mA with TTL input thresholds, so 3.3 V reads reliably as high.

**Motor:** 24HS40-5004D-E1000 is a 5 A motor — S1 rotating switch in the top band
(7.0 A peak / 5 A RMS, codes A–F). Lower bands will undertorque it. Encoder is
1000 PPR / 4000 CPR differential into P2, and **P2's VCC is a 5 V output from the
drive** — the encoder is not powered by our board.

### STS3215 (J5, J6) — half-duplex TTL

Part is **ST-3215-C047**, the 12 V variant. Not the 7.4 V part.

| Parameter | Value |
| --- | --- |
| Operating voltage | 12 V (range 4–14 V) |
| Rated current | 900 mA |
| Stall current | 2.7 A |
| Idle current | 30 mA |
| Signal high / low | 2–5 V / 0–0.45 V |
| Protections | OV > 14 V, UV < 4 V, OC > 2 A for 2 s, OT > 70 °C |
| Connector | 5264-3P (GND / VCC / Signal) |
| Default baud | 1 Mbps, configurable to 38400 |
| Max position update rate | 1 ms |

**Buffer circuit:** use Feetech's reference schematic (datasheet p.8) —
SN74LVC1G126 (active-high OE) driving the bus from TX, SN74LVC1G125 (active-low
OE) feeding RX from the bus. **Run both at 3.3 V.** The datasheet notes VCC
follows the MCU serial level, and signal high is specified at 2–5 V, so 3.3 V is
in spec at both ends. No level shifting anywhere. Add a 10 kΩ pull-up to 3.3 V on
DATA so the line idles high.

**Deviate from the reference in one place:** it derives TXEN from TXD with a PNP
and two resistors. Use a **dedicated GPIO** instead. Auto-direction circuits are
timing-sensitive and we have ~40 spare pins.

**Firmware hazard — bus turnaround.** TXEN must deassert after the stop bit has
physically left the pin but before the servo replies. `flush()` returns when the
FIFO drains, which can be earlier. **Use the LPUART transmission-complete flag.**
This is the most common failure mode on these buses and presents as intermittent
checksum errors that look like noise.

**Run at 500 kbps, not 1 Mbps.** Two servos need nowhere near 1 Mbps, and halving
the rate doubles noise margin on a cable running down a moving arm.

#### The ground-offset problem

Signal low is 0–0.45 V, referenced to a ground that also carries servo return
current. One metre of 24 AWG is ~0.084 Ω:

| Condition | Ground offset |
| --- | --- |
| One servo stalled, 24 AWG | 0.23 V |
| Both servos stalled, daisy-chained, 24 AWG | **0.45 V** — entire budget |
| Both stalled, star wired, 20 AWG | ~0.18 V |

**J6 is the gripper. It stalls every time it closes on something.** The condition
that breaks the signal reference is a normal part of the demo, not a corner case.

Mitigations (do both):
- **20 AWG** for power and ground, not the stock cable gauge.
- **Star the servos** — two separate 5264 runs from the board, so J5's connector
  never carries J6's current. Costs one extra board connector.

**Before first connection:** both servos ship with the same default ID. Connect
one at a time, assign IDs, then bring up the bus. Two servos with identical IDs
reads as a dead bus.

---

## 5. Safety architecture

The existing safety layers (host watchdogs, firmware watchdogs, GUI E-STOP, soft
limits, sim-by-default) all depend on firmware or software running correctly.
**There is no layer that works when firmware does not.**

### Hardware e-stop

- DC-rated contactor on the motor bus. AC contactors do not reliably break DC arcs.
- **Break-only.** The physical e-stop loop energises the contactor; the Teensy
  GPIO can only break that loop. A firmware bug or hung MCU must never be able to
  *close* motor power.
- Aux contact into a Teensy GPIO for state sense.
- Logic rail fed upstream of the contactor.

### Holding brakes

If motor power drops, J2 loses holding torque and gravity takes the shoulder. The
hardware e-stop and the J2 brake are **one design problem, not two.**

The CL57T BRK output (24 V / 100 mA, relay + diode) is the natural driver: if the
drive loses 36 V, BRK dies, the relay releases, and a power-off-engage brake
clamps. Fail-safe with no firmware in the path.

*Open:* whether the mechanical design includes brakes at all, and whether 12 V
coils would suffice (which would delete the 24 V rail entirely).

### Step/dir runaway watchdog

If STEP comes from FlexPWM hardware and firmware hangs, the peripheral keeps
emitting pulses unsupervised and the joint runs away. moteus is immune — its
0.25 s timeout de-energises when commands stop. The CL57T has no such notion and
will follow pulses forever.

**Fix:** gate the 74ACT244 OE pins with a retriggerable monostable (74HC123 or
74LVC1G123) that firmware must kick every ~100 ms. Firmware hangs → OE deasserts
→ pulses stop → closed-loop drive holds position. One part, and it gives the
steppers the same guarantee moteus has natively.

---

## 6. Board architecture

Single combined board: power distribution, conversion, signal conditioning and
the Teensy.

### Stackup

| Layer | Contents |
| --- | --- |
| L1 | Fast signals (CAN pair, servo bus) + power pours |
| L2 | **Solid ground, unbroken** |
| L3 | Power distribution — 36 V / 12 V / 5 V regions |
| L4 | Slow signals (I²C, buttons, display, enables) + pours |

Four layers, not six. The constraint is copper weight, not routing density —
roughly 40 signal nets and one 5 Mbps differential pair do not need six layers.
2 oz outer / 1 oz inner; 2 oz inner costs more and buys little since inner copper
cannot shed heat by convection.

**L3 is a split plane.** Anything on L4 references those splits, not ground. A
signal crossing a 36 V / 12 V boundary has a discontinuous return path. **CAN and
the servo bus stay on L1 against the solid L2 ground and do not move.**

Heavy copper widens minimum trace/space (typically 6–8 mil rather than 4–5) due
to etch undercut. Fine for this board — nothing is fine-pitch — but confirm with
the fab before setting design rules.

### Current paths

14 A flows only through the input section (connector → fuse → FET → NTC →
distribution point). Keep that path short and compact. After the split, each
stepper home-run carries up to 7 A — roughly 100 mil on 2 oz outer for a 10 °C
rise. Run IPC-2152 against measured peaks once available.

### Placement order

1. **Connectors and the two stepper home-runs first.** Those runs are ~2.5 mm
   pours crossing the whole board; nothing can route around them afterwards.
2. CAN connector against whichever edge pins 30/31 land on. Teensy oriented to
   serve it.
3. Servo connectors as far from power paths as the board allows.
4. Everything else inward from its own connector.

Board perimeter is the scarce resource, not area — ~13 connectors, several wide.

### Hand-assembly rules

- Nothing finer than SOIC / SOT-23. Passives at 0805, not 0603.
- IPC footprint density **Level A (Most)** — larger pads and longer toe fillets.
- **Thermal relief spokes on every through-hole pad landing on a 2 oz pour.**
  Set this in footprints now. Without it, joints will not flow.
- Socket the buck modules and the Teensy. Never solder the Teensy down.
- Reverse-polarity FET in TO-220, not DPAK — easier to solder and better thermals
  at 14 A.
- NTC inrush limiter instead of a FET soft-start circuit. Runs hot in steady
  state and won't re-limit on a fast power cycle; acceptable for a bench arm.

### Teensy 4.1 notes

- **Cut the VUSB–VIN pads.** Otherwise the board's 5 V backfeeds the host USB
  port. This matters more now that the Teensy is the single point of host contact.
- **Not 5 V tolerant on any pin.**
- The onboard 3.3 V regulator is a **250 mA budget, not a rail.** Sensors, the
  transceiver and buffers run from the board's own 3.3 V LDO. Share ground only;
  do not tie the LDO output to the Teensy 3.3 V pin.
- USB device port exists only on the Teensy's own micro-USB connector — it cannot
  be relocated to the PCB. Use a panel-mount USB-B with a short internal cable;
  micro-USB is an SMT part and a mechanical weak point.
- Leave the program button accessible.

---

## 7. Proposed pin map

| Function | Pins | Notes |
| --- | --- | --- |
| CAN-FD → moteus J1/J3 | 30 (RX), 31 (TX) | **Fixed.** Only FD-capable bus |
| STS3215 bus | 0, 1 (Serial1) | Plus 1 GPIO for TXEN |
| J2 step / dir / ena | 2, 3, 4 | STEP on FlexPWM4 |
| J4 step / dir / ena | 5, 6, 9 | STEP on FlexPWM2 — separate module |
| CL57T ALM returns | 20, 21 | Via optocoupler, pulled to 3.3 V |
| E-stop contactor sense | 22 | Aux contact |
| Contactor break | 23 | **Break-only** |
| Transceiver standby | TBD | Silences Teensy for `moteus_tool` |
| Buffer OE (watchdog kick) | TBD | Retriggerable monostable |
| Display / HMI | 18, 19 (Wire) | I²C |

~18 pins of 40+ available. Budget is not a constraint — **assign for layout
proximity, not availability.** J2 and J4 STEP are on different FlexPWM modules
deliberately, so they get independent pulse frequencies without sharing a
prescaler.

**Verify all of this against the i.MX RT1062 mux table before committing.**

---

## 8. Power budget

| Branch | Continuous | Peak | Basis |
| --- | --- | --- | --- |
| J5/J6 servos (12 V) | ~24 W | ~72 W | Spec, 90 % buck |
| Logic, fans, buffers, display | ~12 W | ~15 W | |
| Brakes (if fitted) | ~25 W | ~25 W | |
| J2/J4 steppers | ~100 W | ~250 W | *estimate* |
| J1/J3 moteus | ~120 W | ~350 W | *estimate* |
| **Total** | **~280 W (7.8 A)** | ~700 W | |

The 700 W column never occurs — it sums peaks that cannot coincide. Realistic
simultaneous worst case is **500–600 W (14–17 A)**.

**Supply: 36 V, ~500 W, ~14 A.** Do not exceed ~600 W — the supply still cannot
sink regen, so extra capacity buys nothing, and larger units have more output
capacitance and worse inrush behaviour.

Every branch has a configurable ceiling (`servo.max_power_W`, the CL57T S1 band,
the servo OC threshold), so pick the supply and configure branches to fit inside
it rather than guessing.

---

## 9. Harness

Board trace widths are in §6. These are the cable runs.

| Run | AWG | Note |
| --- | --- | --- |
| Supply → board input | 14 | carries the full 14 A |
| CL57T home-runs (×2) | 18 | up to 7 A each, separate runs per §2 |
| moteus chain | 18 | XT30 pigtails, chained |
| 12 V servo runs (×2) | **20** | §4 ground offset — not the stock gauge |
| Step/dir, ALM, limits | 24 | |
| CAN H / L | 24 twisted pair | |

**Stranded silicone only on anything crossing a joint.** Solid core work-hardens
and snaps; connector and wire fatigue at moving joints is the most likely thing
to fail at the fair. Derate ampacity ~30 % inside sleeving.

**Star ground at the supply negative.** Each driver return is its own conductor
back to that point — do not daisy-chain driver grounds. Motor return current must
never share copper with logic ground: the CL57T chopper puts high di/dt in its
return, and sharing that path with ALM or limit inputs reads as phantom faults.
Encoder cable shields ground at the board end only; both ends makes a shield
current loop.

---

## 10. Autonomy provisions

Laptop retains vision (heavier model than any SBC would run) and high-level
sequencing. Teensy owns all real-time motion. **No companion SBC** — the 5 V rail
is sized for logic only.

Stored-routine mode is the **degraded mode**, not the primary one: route files on
the Teensy SD card, button + rotary selector to choose, so the arm can home and
run a canned sequence with no laptop. An I²C display shows current joint, routine
step, and last fault code — without it, a moteus fault 34 or CL57T alarm is a
motor that silently stopped.

**Trajectory generation belongs on the Teensy, not the host.** `Arm.move()`
velocity scaling should port across. If the laptop sends complete moves (targets
+ speed) rather than continuous targets, a dropped link always leaves the arm at
a defined pose.

---

## 11. Open items

| Item | Blocks | Owner |
| --- | --- | --- |
| CL57T mounting location — base or at the motors | Connector count and placement | ME + EE |
| Brakes: exist? 12 V or 24 V coils? | Whether the 24 V rail exists at all | ME |
| **Gearbox continuous output torque (PAHT-CF)** | Current limits on every branch | ME |
| 12 V servo buck MPN | BOM, footprint | EE |
| Reverse-polarity P-FET MPN | BOM, footprint | EE |
| DC contactor MPN | BOM | EE |
| Measured regen headroom | Validates the whole 36 V margin | EE |
| Harness bundling / which edge each connector leaves from | Placement | ME + EE |
| mj5208 phase resistance, J1/J3 gear ratios | Tightens the power budget | EE |
| CL57T 0–40 °C vs enclosure ambient | Enclosure airflow, drive placement | ME + EE |
| **Per-branch fusing?** §2 shows one input fuse only. Branch fuses localise a fault and keep one joint from dropping the arm — but need coordination (branch opens before main) | Harness, BOM | EE |
| Ethernet vs USB for host link | Rev B | EE |
| Current sensing (INA228) | Deferred from rev A | EE |

### Cheapest next measurement

`workout.txt` is already the regen worst case — big sweeps, hard reversals, speed
ramp. Run it on J1 with tview watching bus voltage and fault codes, at 24 V on the
dev-kit supply already on hand. Whatever margin appears at 24 V predicts 36 V, and
it produces a measured number for the figure the entire rail design hangs on.

---

## 12. Bring-up checklist

- [ ] **Set S3 to 5 V on both CL57Ts and label them.** Wrong setting destroys the
      input photocoupler.
- [ ] Set S1 to the 7 A / 5 A band (codes A–F) on both drives.
- [ ] Cut the VUSB–VIN pads on the Teensy.
- [ ] Configure `servo.max_regen_power_W` and `servo.default_accel_limit` on both
      moteus **before** any motor is energised from the new supply.
- [ ] Verify 120 Ω termination at exactly two points on the CAN bus.
- [ ] Assign STS3215 IDs one servo at a time before connecting both.
- [ ] Confirm the contactor cannot be closed by any Teensy GPIO state.
- [ ] Verify the OE watchdog: halt firmware deliberately, confirm pulses stop.
- [ ] Log servo input voltage during a gripper stall to separate rail sag from
      genuine overcurrent.

---

## Sources

- moteus r4.11 specifications and connectors — mjbots product page
- Overvoltage fault 34, `max_regen_power_W`, 4000 µF ceiling — moteus docs,
  Troubleshooting → Overvoltage Fault 34
- Arduino/Teensy support, transceiver, termination — moteus docs, Platforms →
  Arduino; `mjbots/moteus-arduino`
- CL57T(V4.1) User Manual, Revision 4.1 — STEPPERONLINE
- ST-3215-C047 Product Specification, Edition A/0, 2023-07-20 — FEETECH
- 24HS40-5004D-E1000 datasheet — STEPPERONLINE
