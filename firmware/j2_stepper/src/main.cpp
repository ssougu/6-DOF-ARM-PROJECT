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
const float GEAR_RATIO               = 15.0;   // set to J2's actual ratio

const float STEPS_PER_OUTPUT_REV = MICROSTEPS_PER_MOTOR_REV * GEAR_RATIO;

// ---------------- soft limits (output rev) ----------------
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
    digitalWrite(DIR_PIN, dirSign > 0 ? HIGH : LOW);
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
                (stepPos != stepTarget) ? 1 : 0,
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
void motionUpdate() {
  long remaining = stepTarget - stepPos;

  if (remaining == 0) {
    curVel = 0;
    return;
  }

  int dirSign = (remaining > 0) ? 1 : -1;
  float vMax = velLimit   * STEPS_PER_OUTPUT_REV;   // steps/s
  float aMax = accelLimit * STEPS_PER_OUTPUT_REV;   // steps/s^2

  // distance needed to stop from current speed
  float vAbs = fabs(curVel);
  float decelDist = (vAbs * vAbs) / (2.0f * aMax);

  // integrate velocity over one step period
  float dt = (curVel != 0) ? (1.0f / vAbs) : (1.0f / sqrtf(2.0f * aMax));

  if (labs(remaining) <= (long)decelDist) {
    vAbs -= aMax * dt;                  // decelerate into the target
  } else {
    vAbs += aMax * dt;                  // accelerate / cruise
  }
  vAbs = constrain(vAbs, aMax * 0.001f, vMax);
  curVel = vAbs * dirSign;

  unsigned long now = micros();
  if ((long)(now - nextStepUs) >= 0) {
    emitStep(dirSign);
    unsigned long interval = (unsigned long)(1e6f / vAbs);
    nextStepUs = now + interval;
  }
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
