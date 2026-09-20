// 17_stream: free-running dissolution logger for the Peel bench rig.
//
// Pins are raw GPIO numbers, so this one sketch runs on both ESP32-S3 boards (same chip):
//   Espressif ESP32-S3-DevKitC-1-N8R8  -> the HackMIT build. Labels on its silkscreen are GPIO numbers.
//   Seeed XIAO ESP32-S3                -> the home bench rig. Its D-labels are given in brackets.
//
//   GPIO8  [D9]   sensor #1, transmission, looks straight at the LEDs through the liquid
//   GPIO9  [D10]  sensor #2, scatter, 90 degrees off the beam
//   GPIO3/4/5/6 [D2/D3/D4/D5]  red, yellow, green, blue LEDs, each through 220R to ground
//   GPIO7  [D8]   DS18B20 data with a 4.7k-5.1k pull-up. Optional: no probe -> temperature null.
//   GPIO14 (DevKitC, J1 header) / GPIO44 [D7] (XIAO)  stirrer PWM, into the TB6612's PWMA.
//
// Both sensors sit on ADC1 (GPIO1-10), which keeps working with Wi-Fi on. ADC2 does not.
//
// How it samples, and why:
//   The fast channel keeps ONE LED on continuously and never switches it, so the sensor never has
//   to settle and 1 Hz costs nothing. That is the channel the kinetics fit uses.
//   The four-colour sweep runs every SWEEP_EVERY_MS in the background for identity, not kinetics.
//   Lines taken during a sweep are flagged so the fit can drop them.
//
// Serial commands:
//   b  take a blank now (clear water in the cup) and store it
//   z  mark t = 0 by hand (until the break beam is wired)
//   a  toggle auto t = 0, which triggers on a sudden drop in transmission
//   s  stop the run and reset the clock
//   m  toggle the stirrer (it starts running automatically)
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>

const int SENS_T = 8;                   // [XIAO D9]
const int SENS_S = 9;                   // [XIAO D10]
const int LED_PINS[4]   = { 3, 4, 5, 6 };   // [XIAO D2 D3 D4 D5]
const char* LED_NAMES[4] = { "red", "yellow", "green", "blue" };
// Which LED lights the fast channel. Green is brightest on this rig, so it is the default for
// turbidity kinetics. For a coloured active use the colour it absorbs: riboflavin needs blue,
// so build with -DFAST_LED=3.
#ifndef FAST_LED
#define FAST_LED 2
#endif
const int TEMP_PIN = 7;                 // [XIAO D8]
#ifdef ARDUINO_XIAO_ESP32S3
const int MOTOR    = 44;                // [XIAO D7] stirrer. 5V bus, see PEEL_BUILD_PLAN.txt
#else
const int MOTOR    = 14;                // DevKitC: on the J1 header with every other pin this sketch
#endif                                  // uses. Plugged into a breadboard, the DevKitC's J3 header is buried.

const int   SAMPLES        = 24;        // averaged per reported value
const int   SETTLE_MS      = 12;        // TEMT6000 is microseconds fast; 12 ms is generous
// The HackMIT build uses CdS photoresistors (docs/HARDWARE.md), which take ~600 ms to settle.
// Only the sweep switches LEDs, so only the sweep pays for it, and it runs less often so the
// fast channel loses fewer seconds.
#ifndef SENSOR_LDR
#define SENSOR_LDR 1
#endif
#if SENSOR_LDR
const int   SWEEP_SETTLE_MS = 700;
const unsigned long SWEEP_EVERY_MS = 30000;
#else
const int   SWEEP_SETTLE_MS = SETTLE_MS;
const unsigned long SWEEP_EVERY_MS = 10000;
#endif
const unsigned long REPORT_MS      = 1000;
const float DROP_FRACTION  = 0.06;      // auto t=0: a 6 percent fall in transmission
const int   STIR_PCT       = 100;       // demo speed: flat out. For DATA runs use a fixed, modest
                                        // speed instead and keep it identical across every run.

OneWire oneWire(TEMP_PIN);
DallasTemperature probe(&oneWire);
bool haveProbe = false;

float blankT = 0, blankS = 0;
bool  haveBlank = false;
bool  autoZero = true;
unsigned long tZero = 0;                // 0 means the run has not started
float sweep[4] = { NAN, NAN, NAN, NAN };
bool  sweptThisLine = false;
bool  stirring = true;

long avgMv(int pin) {
  long s = 0;
  for (int i = 0; i < SAMPLES; i++) { s += analogReadMilliVolts(pin); delayMicroseconds(150); }
  return s / SAMPLES;
}

void allLedsOff() { for (int i = 0; i < 4; i++) digitalWrite(LED_PINS[i], LOW); }

// Spin-up is a soft ramp, not a step, and that is what lets it reach full speed without losing
// the bar. A stir bar follows a rotating field only while magnetic torque beats the drag on it;
// slam the field to full and the bar cannot accelerate fast enough, breaks lock and just rattles.
// Ramping lets the bar come up WITH the field, so it stays locked at speeds a step change loses.
void stirOn() {
  analogWrite(MOTOR, 255);            // brief kick to break stiction
  delay(250);
  for (int p = 40; p <= STIR_PCT; p += 5) {   // then ramp, ~1.3 s to full
    analogWrite(MOTOR, (p * 255) / 100);
    delay(100);
  }
  analogWrite(MOTOR, (STIR_PCT * 255) / 100);
  stirring = true;
}
void stirOff() { analogWrite(MOTOR, 0); stirring = false; }
void fastLedOn()  { allLedsOff(); digitalWrite(LED_PINS[FAST_LED], HIGH); }

// Absorbance against the stored blank. Positive means the sample blocks more light than water.
// JSON has no NaN. A dark or unplugged sensor makes absorbance NaN, printf would emit "nan",
// and every parser (the monitor, the phone app) would reject that whole line and lose the second.
void printNum(float v, int places) {
  if (isnan(v) || isinf(v)) Serial.print("null"); else Serial.print(v, places);
}

float absorbance(float blank, float now) {
  if (blank <= 1 || now <= 1) return NAN;
  return log10f(blank / now);
}

// One pass through all four colours. Slow channel, for identity rather than kinetics.
void doSweep() {
  allLedsOff(); delay(SWEEP_SETTLE_MS);
  long dark = avgMv(SENS_T);
  for (int i = 0; i < 4; i++) {
    digitalWrite(LED_PINS[i], HIGH); delay(SWEEP_SETTLE_MS);
    sweep[i] = avgMv(SENS_T) - dark;
    digitalWrite(LED_PINS[i], LOW);
  }
  fastLedOn(); delay(SWEEP_SETTLE_MS);
  sweptThisLine = true;
}

void takeBlank() {
  fastLedOn(); delay(SETTLE_MS * 4);
  blankT = avgMv(SENS_T);
  blankS = avgMv(SENS_S);
  haveBlank = true;
  Serial.printf("# blank stored: transmission %.0f mV, scatter %.0f mV\n", blankT, blankS);
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  for (int i = 0; i < 4; i++) { pinMode(LED_PINS[i], OUTPUT); digitalWrite(LED_PINS[i], LOW); }
  pinMode(SENS_T, INPUT);
  pinMode(SENS_S, INPUT);
  pinMode(LED_BUILTIN, OUTPUT); digitalWrite(LED_BUILTIN, HIGH);
  pinMode(MOTOR, OUTPUT);
  analogWriteFrequency(MOTOR, 20000);
  delay(300);
  probe.begin();
  haveProbe = probe.getDeviceCount() > 0;
  if (haveProbe) { probe.setResolution(12); probe.setWaitForConversion(false); probe.requestTemperatures(); }
  fastLedOn();
  stirOn();
  Serial.println();
  Serial.printf("# 17_stream ready. Fast channel = %s LED. Stirrer %d%%. Temperature probe: %s\n",
                LED_NAMES[FAST_LED], STIR_PCT, haveProbe ? "found" : "absent, reporting null");
  Serial.println("# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer");
}

void loop() {
  static unsigned long lastReport = 0, lastSweep = 0;
  static float lastT = 0;

  if (Serial.available()) {
    char c = Serial.read(); while (Serial.available()) Serial.read();
    if (c == 'b') takeBlank();
    else if (c == 'z') { tZero = millis(); Serial.println("# t = 0 marked"); }
    else if (c == 'a') { autoZero = !autoZero; Serial.printf("# auto t=0 %s\n", autoZero ? "on" : "off"); }
    else if (c == 's') { tZero = 0; Serial.println("# run stopped"); }
    else if (c == 'm') { if (stirring) { stirOff(); Serial.println("# stirrer off"); } else { stirOn(); Serial.println("# stirrer on"); } }
  }

  if (millis() - lastSweep >= SWEEP_EVERY_MS) { lastSweep = millis(); doSweep(); }

  if (millis() - lastReport < REPORT_MS) return;
  lastReport = millis();
  digitalWrite(LED_BUILTIN, LOW);

  float t = avgMv(SENS_T);
  float s = avgMv(SENS_S);

  // Auto t = 0: the tablet hitting the water makes transmission fall sharply.
  if (autoZero && tZero == 0 && haveBlank && lastT > 1 && t < lastT * (1.0f - DROP_FRACTION)) {
    tZero = millis();
    Serial.println("# t = 0 detected from the transmission drop");
  }
  lastT = t;

  float tC = NAN;
  if (haveProbe) { tC = probe.getTempCByIndex(0); probe.requestTemperatures(); }

  float elapsed = tZero ? (millis() - tZero) / 1000.0f : -1.0f;

  Serial.print("{");
  Serial.printf("\"t\":%.1f,\"trans\":%.0f,\"scat\":%.0f", elapsed, t, s);
  if (haveBlank) {
    Serial.print(",\"absT\":"); printNum(absorbance(blankT, t), 4);
    Serial.print(",\"absS\":"); printNum(absorbance(blankS, s), 4);
  } else {
    Serial.print(",\"absT\":null,\"absS\":null");
  }
  if (isnan(tC) || tC < -100) Serial.print(",\"tC\":null");
  else Serial.printf(",\"tC\":%.2f", tC);
  Serial.print(",\"sweep\":{");
  for (int i = 0; i < 4; i++) {
    if (isnan(sweep[i])) Serial.printf("%s\"%s\":null", i ? "," : "", LED_NAMES[i]);
    else Serial.printf("%s\"%s\":%.0f", i ? "," : "", LED_NAMES[i], sweep[i]);
  }
  Serial.printf("},\"stir\":%d,\"swept\":%s}\n", stirring ? STIR_PCT : 0, sweptThisLine ? "true" : "false");
  sweptThisLine = false;
  digitalWrite(LED_BUILTIN, HIGH);
}
