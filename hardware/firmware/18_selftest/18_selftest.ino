// 18_selftest - bench check for the PEEL build before anything goes in the orange.
// Checks, in order: both TEMT6000 channels, the DS18B20, and all four LEDs.
// Nothing here writes to the motor unless you ask for it with 'm'.
//
//   XIAO ESP32-S3        raw GPIO   board hole (step 6 wiring)
//   D2 red LED           3          A a3 -> B a4
//   D3 yellow LED        4          A a4 -> B a5
//   D4 green LED         5          A a5 -> B a6
//   D5 blue LED          6          A a6 -> B a7
//   D8 DS18B20 data      7          A j6, 5.1k pull-up i3-i6
//   D9 transmission      8          A i5
//   D10 scatter          9          A i4
//   D7 motor PWM         44         A j7 -> B a14
//
//   arduino-cli compile --upload -p <port> --fqbn esp32:esp32:XIAO_ESP32S3 sketches/18_selftest

#include <OneWire.h>
#include <DallasTemperature.h>

#define NLED 6
const int LED_PIN[NLED] = {3, 4, 5, 6, 1, 2};   // D2 D3 D4 D5, then D0 = IR 940, D1 = violet
const char *LED_NAME[NLED] = {"red   ", "yellow", "green ", "blue  ", "IR 940", "violet"};
const int PIN_TRANS = 8, PIN_SCAT = 9, PIN_OW = 7, PIN_MOTOR = 44;

OneWire ow(PIN_OW);
DallasTemperature ds(&ow);
bool haveProbe = false;

// Room lighting ripples at 120 Hz and the ripple is bigger than the LEDs we are trying to
// measure, so every reading averages over ~100 ms, which is 12 whole cycles of it.
int mv(int pin, int n = 250) {
  long sum = 0;
  for (int i = 0; i < n; i++) { sum += analogReadMilliVolts(pin); delayMicroseconds(400); }
  return (int)(sum / n);
}

// Lock-in: switch the LED on and off `pairs` times and average the differences. Anything
// that does not follow the switching, which is all of the ambient light, cancels out.
void lockin(int led, int *dTrans, int *dScat, int pairs = 6) {
  long st = 0, ss = 0;
  for (int i = 0; i < pairs; i++) {
    digitalWrite(led, LOW);  delay(40);
    int t0 = mv(PIN_TRANS), s0 = mv(PIN_SCAT);
    digitalWrite(led, HIGH); delay(40);
    int t1 = mv(PIN_TRANS), s1 = mv(PIN_SCAT);
    st += t1 - t0; ss += s1 - s0;
  }
  digitalWrite(led, LOW);
  *dTrans = (int)(st / pairs);
  *dScat = (int)(ss / pairs);
}

void spread(int pin, int *lo, int *hi, int *mean, int n = 12) {
  long sum = 0; *lo = 4096; *hi = 0;
  for (int i = 0; i < n; i++) {
    int v = mv(pin);                       // each one is already a 100 ms average
    sum += v; if (v < *lo) *lo = v; if (v > *hi) *hi = v;
  }
  *mean = (int)(sum / n);
}

void allLedsOff() { for (int i = 0; i < NLED; i++) digitalWrite(LED_PIN[i], LOW); }

void selftest() {
  Serial.println();
  Serial.println("=== PEEL self-test =========================================");

  // ---- 1. the two light channels, in the dark -------------------------------------------
  allLedsOff(); delay(200);
  int tLo, tHi, tMean, sLo, sHi, sMean;
  spread(PIN_TRANS, &tLo, &tHi, &tMean);
  spread(PIN_SCAT, &sLo, &sHi, &sMean);
  Serial.printf("1. transmission (D9) : %4d mV   noise %d mV   %s\n", tMean, tHi - tLo,
                tMean >= 4000 ? "PINNED HIGH, check wiring" : (tHi - tLo) > 60 ? "noisy" : "reads ok");
  Serial.printf("   scatter      (D10): %4d mV   noise %d mV   %s\n", sMean, sHi - sLo,
                sMean >= 4000 ? "PINNED HIGH, check wiring" : (sHi - sLo) > 60 ? "noisy" : "reads ok");
  Serial.println("   (a TEMT6000 in room light usually sits somewhere between 100 and 2500 mV)");

  // ---- 2. temperature --------------------------------------------------------------------
  ds.begin();
  int n = ds.getDeviceCount();
  DeviceAddress addr;
  if (n > 0 && ds.getAddress(addr, 0)) {
    haveProbe = true;
    Serial.printf("2. DS18B20           : found %d, address ", n);
    for (uint8_t i = 0; i < 8; i++) Serial.printf("%02X", addr[i]);
    ds.requestTemperatures();
    float c = ds.getTempCByIndex(0);
    Serial.printf("\n   temperature       : %.2f C   %s\n", c,
                  (c > 5 && c < 45) ? "PASS" : "out of range, suspect wiring");
  } else {
    haveProbe = false;
    Serial.println("2. DS18B20           : NOT FOUND. Check the 5.1k from i3 to i6, the yellow");
    Serial.println("                       wire in A j6, red in B d1 (3V3) and black in B i1 (GND).");
  }

  // ---- 3. the LEDs, one at a time, watched by both sensors --------------------------------
  Serial.println("3. LEDs: each one on for a moment. WATCH THEM: every one should light.");
  for (int i = 0; i < NLED; i++) {
    allLedsOff(); delay(150);
    int dt, dsc;
    lockin(LED_PIN[i], &dt, &dsc);
    Serial.printf("   %s (GPIO %2d): transmission %+5d mV, scatter %+5d mV   %s\n",
                  LED_NAME[i], LED_PIN[i], dt, dsc,
                  (dt > 15 || dsc > 15) ? "SEEN" : "no light reached a sensor");
    for (int k = 0; k < 2; k++) {            // a slow double blink, for your eyes
      digitalWrite(LED_PIN[i], HIGH); delay(180);
      digitalWrite(LED_PIN[i], LOW);  delay(180);
    }
  }
  allLedsOff();

  Serial.println("------------------------------------------------------------");
  Serial.println("Now the live stream, one line a second.");
  Serial.println("  cover the TRANSMISSION sensor  -> trans should fall");
  Serial.println("  cover the SCATTER sensor       -> scat should fall");
  Serial.println("  hold a finger on the probe     -> tC should climb");
  Serial.println("  keys:  r re-run   g green   i IR 940   v violet   m motor 1.5 s");
  Serial.println("============================================================");
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 4000) {}
  delay(400);
  for (int i = 0; i < NLED; i++) { pinMode(LED_PIN[i], OUTPUT); digitalWrite(LED_PIN[i], LOW); }
  pinMode(PIN_MOTOR, OUTPUT); digitalWrite(PIN_MOTOR, LOW);
  analogReadResolution(12);
  selftest();
}

void loop() {
  static bool green = false;
  if (Serial.available()) {
    int c = Serial.read();
    while (Serial.available()) Serial.read();
    if (c == 'r') selftest();
    if (c == 'i' || c == 'v') {          // the two new ones, on solid so you can look at them
      int k = (c == 'i') ? 4 : 5;
      static bool onI = false, onV = false;
      bool &st = (c == 'i') ? onI : onV;
      st = !st;
      digitalWrite(LED_PIN[k], st);
      Serial.printf("# %s %s\n", LED_NAME[k], st ? "ON" : "off");
    }
    if (c == 'd') {   // is each LED really in circuit, and the right way round?
      Serial.println("# diode check: each pin is released to a weak internal pull-up, so the");
      Serial.println("#   node settles at that LED's own forward drop. ~3300 mV means nothing");
      Serial.println("#   is connected; a few hundred mV means it is in backwards or shorted.");
      for (int i = 0; i < NLED; i++) {
        pinMode(LED_PIN[i], INPUT_PULLUP);
        delay(60);
        long v = 0;
        for (int k = 0; k < 20; k++) { v += analogReadMilliVolts(LED_PIN[i]); delay(2); }
        v /= 20;
        pinMode(LED_PIN[i], OUTPUT); digitalWrite(LED_PIN[i], LOW);
        Serial.printf("   %s (GPIO %2d): %4ld mV  %s\n", LED_NAME[i], LED_PIN[i], v,
                      v > 3000 ? "OPEN, nothing in the holes" : v < 250 ? "near zero, backwards or shorted"
                                                              : "diode present");
      }
    }
    if (c == 'x') {   // hold the transmission sensor against the IR dome, then press x
      Serial.println("# IR lock-in, 20 pairs, hold the sensor on the dome");
      int dt, dsc;
      lockin(LED_PIN[4], &dt, &dsc, 20);
      Serial.printf("   IR 940: transmission %+5d mV, scatter %+5d mV   %s\n", dt, dsc,
                    (dt > 8 || dsc > 8) ? "EMITTING" : "no IR seen");
      digitalWrite(LED_PIN[4], HIGH);
      Serial.println("# IR left ON");
    }
    if (c == 'g') { green = !green; digitalWrite(LED_PIN[2], green); Serial.printf("# green %s\n", green ? "on" : "off"); }
    if (c == 'c') {                       // one colour at a time, with time to aim
      for (int i = 0; i < 4; i++) {
        allLedsOff();
        Serial.printf("# %s is ON now: point the transmission sensor straight at it\n", LED_NAME[i]);
        digitalWrite(LED_PIN[i], HIGH);
        delay(4000);
        int dt, dsc;
        lockin(LED_PIN[i], &dt, &dsc, 8);
        Serial.printf("   %s: transmission %+5d mV, scatter %+5d mV   %s\n", LED_NAME[i], dt, dsc,
                      (dt > 15 || dsc > 15) ? "SEEN" : "nothing");
      }
      allLedsOff();
      Serial.println("# colour walk done");
    }
    if (c == 'M') { digitalWrite(PIN_MOTOR, HIGH); Serial.println("# motor ON, full DC"); }
    if (c == 'o') { digitalWrite(PIN_MOTOR, LOW);  Serial.println("# motor off"); }
    if (c == 'm') {
      Serial.println("# motor 1.5 s");
      digitalWrite(PIN_MOTOR, HIGH); delay(1500); digitalWrite(PIN_MOTOR, LOW);
      Serial.println("# motor off");
    }
  }
  float c = NAN;
  if (haveProbe) { ds.requestTemperatures(); c = ds.getTempCByIndex(0); }
  Serial.printf("trans %4d mV   scat %4d mV   tC ", mv(PIN_TRANS), mv(PIN_SCAT));
  if (isnan(c) || c < -50) Serial.println("--"); else Serial.printf("%.2f\n", c);
  delay(1000);
}
