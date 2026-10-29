// ============================================================
//  J2 stepper joint - moteus-like command set over USB serial
//  ESP32 + CL57T + 24HS40-5004D-E1000
//
//  Units are OUTPUT REVOLUTIONS, matching the moteus convention
//  once rotor_to_output_ratio is configured. 1.0 = one joint turn.
//
//  Wiring (common anode, inverted logic):
//    VIN  -> PUL+   and bridge PUL+ -> DIR+
//    D32  -> PUL-
//    D33  -> DIR-
//
//  Protocol - one ASCII line in, one line out. 115200 baud.
//    A                 arm (clear estop latch)
//    S                 estop, latches
//    Z                 define current position as 0
//    H                 hold current position
//    P <rev> [v] [a]   position command, output rev; v,a optional limits
//    Q                 query -> telemetry line
//
//  Every reply is key=value pairs so the host can parse without
//  positional assumptions:
//    ok pos=0.1234 vel=0.0500 moving=1 armed=1 fault=0
// ============================================================

#include <Arduino.h>

// ---------------- hardware ----------------
const int PUL_PIN = 32;
const int DIR_PIN = 33;

const long  MICROSTEPS_PER_MOTOR_REV = 2000;   // must match SW1-SW4

// Motor revs per output rev. The host speaks OUTPUT units, so this must match
// the hardware actually bolted on RIGHT NOW, not the hardware we plan to fit.
//
//   25.0 = single-stage cycloidal, 25:1   <-- fitted 2026-10-28, J2 on J1
//   1.0  = bare motor, no gearbox
//
// Take it from LOBE/PIN COUNTS (reduction = N_lobes when N_pins = N_lobes+1),
// never hand rotation -- that gave a false 11.14:1 against J1's true 15:1.
// Leaving a planned-but-unfitted ratio here made every commanded angle come
// out that many times too big at the shaft, which reads as a broken scale.
const float GEAR_RATIO               = 25.0;

// A single-stage cycloid turns its output OPPOSITE to its input, so the
// positive direction flipped when the gearbox went on. Flip this if +deg
// moves the shoulder the wrong way -- it is the only place sign lives.
const bool  INVERT_DIR               = false;

const float STEPS_PER_OUTPUT_REV = MICROSTEPS_PER_MOTOR_REV * GEAR_RATIO;

// ---------------- soft limits (output rev) ----------------
// +/-0.55 rev = +/-198 deg. J2 has no hard stops and can turn continuously,
// so +/-180 covers every pose; this bound is not mechanical. It stops a typo
// from commanding many turns and winding the motor + encoder cables round
// the joint. Same bound as J1.
float posMin = -0.55;
float posMax =  0.55;

// ---------------- motion limits (output rev/s, rev/s^2) ----------------
float velLimit   = 0.25;
float accelLimit = 1.0;

// ---------------- watchdog ----------------
// Matches servo.default_timeout_s = 0.25 on the moteus side.
const unsigned long WATCHDOG_US = 250000;
unsigned long lastCommandUs = 0;

// ---------------- state ----------------
long  stepPos     = 0;      // absolute position in steps
long  stepTarget  = 0;
float curVel      = 0.0;    // steps/s, signed
bool  armed       = false;
bool  faulted     = false;
unsigned long nextStepUs = 0;

// ---------------- helpers ----------------
inline float stepsToRev(long s) { return s / STEPS_PER_OUTPUT_REV; }
inline long  revToSteps(float r) { return lround(r * STEPS_PER_OUTPUT_REV); }

void emitStep(int dirSign) {
  static int lastDir = 0;
  if (dirSign != lastDir) {
    digitalWrite(DIR_PIN, (dirSign > 0) != INVERT_DIR ? HIGH : LOW);
    delayMicroseconds(5);            // manual wants >=2us DIR setup
    lastDir = dirSign;
  }
  digitalWrite(PUL_PIN, LOW);        // active (inverted)
  delayMicroseconds(3);
  digitalWrite(PUL_PIN, HIGH);
  stepPos += dirSign;
}

void estop(const char *why) {
  armed   = false;
  curVel  = 0.0;
  stepTarget = stepPos;
  Serial.printf("estop reason=%s pos=%.5f\n", why, stepsToRev(stepPos));
}

void telemetry(const char *prefix) {
  Serial.printf("%s pos=%.5f vel=%.4f moving=%d armed=%d fault=%d\n",
                prefix,
                stepsToRev(stepPos),
                curVel / STEPS_PER_OUTPUT_REV,
                (stepPos != stepTarget || curVel != 0) ? 1 : 0,
                armed ? 1 : 0,
                faulted ? 1 : 0);
}

// ---------------- command parsing ----------------
void handleLine(String line) {
  line.trim();
  if (line.length() == 0) { estop("empty_line"); return; }

  lastCommandUs = micros();
  char cmd = toupper(line.charAt(0));
  String rest = line.substring(1);
  rest.trim();

  switch (cmd) {
    case 'A':
      armed = true; faulted = false;
      telemetry("ok");
      break;

    case 'S':
      estop("commanded");
      break;

    case 'Z':
      stepTarget -= stepPos;
      stepPos = 0;
      stepTarget = 0;
      telemetry("ok");
      break;

    case 'H':
      stepTarget = stepPos;
      curVel = 0;
      telemetry("ok");
      break;

    case 'Q':
      telemetry("ok");
      break;

    case 'P': {
      if (!armed) { Serial.println("err reason=not_armed"); break; }
      float p = NAN, v = NAN, a = NAN;
      int n = sscanf(rest.c_str(), "%f %f %f", &p, &v, &a);
      if (n < 1 || isnan(p)) { Serial.println("err reason=bad_args"); break; }
      if (p < posMin || p > posMax) {
        Serial.printf("err reason=outside_limit min=%.3f max=%.3f\n",
                      posMin, posMax);
        break;
      }
      if (n >= 2 && v > 0) velLimit   = v;
      if (n >= 3 && a > 0) accelLimit = a;
      stepTarget = revToSteps(p);
      telemetry("ok");
      break;
    }

    default:
      Serial.println("err reason=unknown_cmd");
  }
}

// ---------------- motion, non-blocking ----------------
// Velocity is updated ONCE PER STEP, as v^2 = v0^2 +/- 2a (one step of
// distance). The previous version integrated a += a*dt on every loop()
// pass -- tens of thousands per second -- so it hit vMax almost instantly
// and accelLimit was never honoured. Harmless on a bare motor at 500
// steps/s; at 25:1 that is a velocity step to 12.5 k steps/s with an arm
// on the output, which a closed-loop CL57T answers with a following-error
// fault, or worse, doesn't.
void motionUpdate() {
  long remaining = stepTarget - stepPos;
  if (remaining == 0 && curVel == 0) return;

  unsigned long now = micros();
  if ((long)(now - nextStepUs) < 0) return;

  float aMax  = accelLimit * STEPS_PER_OUTPUT_REV;     // steps/s^2
  float vMax  = velLimit   * STEPS_PER_OUTPUT_REV;     // steps/s
  float vStep = fminf(sqrtf(2.0f * aMax), vMax);       // one step from rest
  float vAbs  = fabsf(curVel);
  int   toTgt = (remaining > 0) - (remaining < 0);
  int   dir   = (curVel > 0) - (curVel < 0);

  if (dir == 0) {                                      // start from rest
    dir  = toTgt;
    vAbs = vStep;
  } else if (dir != toTgt || vAbs > vMax ||
             labs(remaining) <= (long)(vAbs * vAbs / (2.0f * aMax))) {
    // reversing, past the target, over a lowered limit, or inside the
    // stopping distance: brake at aMax rather than stop dead
    vAbs = sqrtf(fmaxf(vAbs * vAbs - 2.0f * aMax, 0.0f));
    if (vAbs < vStep) {
      if (dir != toTgt) { curVel = 0; return; }        // stopped; turn around
      vAbs = vStep;                                    // creep the last steps
    }
  } else {
    vAbs = fminf(sqrtf(vAbs * vAbs + 2.0f * aMax), vMax);
  }

  emitStep(dir);
  curVel = (stepPos == stepTarget && vAbs <= vStep) ? 0 : vAbs * dir;
  nextStepUs = now + (unsigned long)(1e6f / vAbs);
}

// ---------------- main ----------------
void setup() {
  Serial.begin(115200);
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  digitalWrite(PUL_PIN, HIGH);      // idle
  digitalWrite(DIR_PIN, HIGH);
  lastCommandUs = micros();
  Serial.println("ready joint=2 type=stepper");
}

void loop() {
  // --- serial ---
  static String buf;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handleLine(buf); buf = ""; }
    else if (c != '\r') buf += c;
  }

  // --- watchdog: only bites while a move is outstanding ---
  if (armed && stepPos != stepTarget &&
      (micros() - lastCommandUs) > WATCHDOG_US) {
    estop("watchdog");
  }

  // --- motion ---
  if (armed && !faulted) motionUpdate();
}
