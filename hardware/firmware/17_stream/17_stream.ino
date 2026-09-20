// 17_stream: free-running dissolution logger for the Peel bench rig.
//
// Pins are raw GPIO numbers, so this one sketch runs on both ESP32-S3 boards (same chip):
//   Espressif ESP32-S3-DevKitC-1-N8R8  -> the HackMIT build. Labels on its silkscreen are GPIO numbers.
//   Seeed XIAO ESP32-S3                -> the home bench rig. Its D-labels are given in brackets.
//
//   GPIO8  [D9]   sensor #1, transmission, looks straight at the LEDs through the liquid
//   GPIO9  [D10]  sensor #2, scatter, 90 degrees off the beam
//   GPIO3/4/5/6 [D2/D3/D4/D5]  red, yellow, green, blue LEDs, each through 220R to ground
//   GPIO1/2 [D0/D1]  IR 940 and violet, through 100R. Same sweep as the other four.
//   GPIO7  [D8]   DS18B20 data with a 4.7k-5.1k pull-up. Optional: no probe -> temperature null.
//   GPIO14 (DevKitC, J1 header) / GPIO44 [D7] (XIAO)  stirrer PWM, into the TB6612's PWMA.
//
// Both sensors sit on ADC1 (GPIO1-10), which keeps working with Wi-Fi on. ADC2 does not.
//
// How it samples, and why:
//   The fast channel keeps ONE LED on continuously and never switches it, so the sensor never has
//   to settle and 1 Hz costs nothing. That is the channel the kinetics fit uses.
//   The six-colour sweep runs every SWEEP_EVERY_MS in the background for identity, not kinetics.
//   It reports both sensors per colour, and the dark reading it subtracted, so the host can tell
//   an LED that never lit from a lid left open. Lines taken during a sweep are flagged so the fit
//   can drop them.
//
// Serial commands:
//   b  take a blank now (clear water in the cup) and store it
//   z  mark t = 0 by hand (until the break beam is wired)
//   a  toggle auto t = 0, which triggers on a sudden drop in transmission
//   s  stop the run and reset the clock
//   m  toggle the stirrer (it starts running automatically)
//   d  print one diagnostics line: 18_selftest's diode check, noise, probe, radio and motor
//      numbers as JSON, so the phone can name a fault instead of showing a bad curve
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>

const char* FIRMWARE = "17_stream+diag";
const char* FW_VERSION = "1.1.0";

const int SENS_T = 8;                   // [XIAO D9]
const int SENS_S = 9;                   // [XIAO D10]
#define NLED 6
// Sweep order, and the order the JSON prints: shortest wavelength last, IR first.
const int LED_PINS[NLED]   = { 1, 3, 4, 5, 6, 2 };   // [XIAO D0 D2 D3 D4 D5 D1]
const char* LED_NAMES[NLED] = { "ir", "red", "yellow", "green", "blue", "violet" };
const int FAST_LED = 3;                 // green: brightest on this rig, so best signal to noise
// The four colours the ESP-NOW packet has room for, as indices into the arrays above. The
// packet is version 1 and the BOX-3 face drops anything else, so it keeps carrying these.
const int PACKET_LEDS[4] = { 1, 2, 3, 4 };   // red, yellow, green, blue
const int TEMP_PIN = 7;                 // [XIAO D8]
#ifdef ARDUINO_XIAO_ESP32S3
const int MOTOR    = 44;                // [XIAO D7] stirrer. 5V bus, see PEEL_BUILD_PLAN.txt
#else
const int MOTOR    = 14;                // DevKitC: on the J1 header with every other pin this sketch
#endif                                  // uses. Plugged into a breadboard, the DevKitC's J3 header is buried.

const int   SAMPLES        = 24;        // averaged per reported value
const int   SETTLE_MS      = 12;        // TEMT6000 is microseconds fast; 12 ms is generous
const unsigned long REPORT_MS      = 1000;

// ---- the radio packet, identical in sketches/19_box3_link -------------------------------
#define NOW_CHANNEL 1
static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
struct __attribute__((packed)) PeelPacket {
  uint8_t  magic;        // 'P'
  uint8_t  version;      // 1
  float    t, trans, scat, absT, absS, tC;   // NAN where the JSON says null
  uint16_t sweep[4];     // mV per colour, 0xFFFF = not swept yet
  uint8_t  stir;         // percent
  uint8_t  flags;        // 1 swept, 2 blank stored, 4 auto t=0, 8 stirring
};
bool nowReady = false;
const unsigned long SWEEP_EVERY_MS = 10000;
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
float sweep[NLED], sweepS[NLED];        // transmission and scatter mV per colour, NAN until swept
float darkT = NAN, darkS = NAN;         // what the sweep subtracted: both sensors, all LEDs off
bool  sweptThisLine = false;
bool  stirring = true;

// ---- diagnostics, printed only when asked for with 'd' ---------------------------------
bool  diagPending = false;
unsigned long loopMaxUs = 0;
uint32_t radioFail = 0, radioDrift = 0;
// When the face last said anything to us. Broadcast ESP-NOW is not acknowledged, so a send
// that returns ESP_OK proves only that the packet left this board; this is the one piece of
// evidence we have that something is listening.
unsigned long lastHeardFromFace = 0;
unsigned long stirChangedMs = 0;
float motorTransBefore = NAN, motorTransAfter = NAN;
float motorScatBefore = NAN, motorScatAfter = NAN;
char  probeAddr[17] = "";
int   probeCount = 0;

long avgMv(int pin) {
  long s = 0;
  for (int i = 0; i < SAMPLES; i++) { s += analogReadMilliVolts(pin); delayMicroseconds(150); }
  return s / SAMPLES;
}

void allLedsOff() { for (int i = 0; i < NLED; i++) digitalWrite(LED_PINS[i], LOW); }

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

// One pass through all six colours, both sensors. Slow channel, for identity rather than
// kinetics. The dark reading is kept as it was measured: with the lid shut it is the ADC
// floor, and with the lid open it is room light, which is how the host tells them apart.
void doSweep() {
  allLedsOff(); delay(SETTLE_MS);
  darkT = avgMv(SENS_T);
  darkS = avgMv(SENS_S);
  for (int i = 0; i < NLED; i++) {
    digitalWrite(LED_PINS[i], HIGH); delay(SETTLE_MS);
    sweep[i]  = avgMv(SENS_T) - darkT;
    sweepS[i] = avgMv(SENS_S) - darkS;
    digitalWrite(LED_PINS[i], LOW);
  }
  fastLedOn(); delay(SETTLE_MS);
  sweptThisLine = true;
}

// ---------------------------------------------------------------- diagnostics ('d')
// Everything 18_selftest measures at the bench, as one JSON line, so a phone can say which
// wire is wrong instead of drawing a bad curve. Printed once per request, never on a timer.

// Each LED pin is an ADC1 channel. Released to the weak internal pull-up, the node settles
// at that LED's own forward drop: ~3300 mV means nothing is in the holes, and a few tens of
// mV means it is in backwards or shorted. Measured drops are in docs/BASELINES.md.
long diodeMv(int pin) {
  pinMode(pin, INPUT_PULLUP);
  delay(60);
  long v = 0;
  for (int k = 0; k < 20; k++) { v += analogReadMilliVolts(pin); delay(2); }
  pinMode(pin, OUTPUT); digitalWrite(pin, LOW);
  return v / 20;
}

// Peak to peak across 12 windows, each a 100 ms average. avgMv is 24 samples, about 4 ms,
// which is a fraction of a mains cycle: room light's 120 Hz ripple would come out as the
// sensor's own noise and the 60 mV threshold in BASELINES.md is measured against 100 ms
// means. Both sensors share the windows, so this costs 1.2 s rather than 2.4 s.
void noiseMv(int pinA, int pinB, long& outA, long& outB) {
  long loA = 4096, hiA = 0, loB = 4096, hiB = 0;
  for (int i = 0; i < 12; i++) {
    long sumA = 0, sumB = 0, n = 0;
    unsigned long until = millis() + 100;
    while ((long)(millis() - until) < 0) {
      sumA += analogReadMilliVolts(pinA);
      sumB += analogReadMilliVolts(pinB);
      n++;
      delayMicroseconds(150);
    }
    if (n == 0) n = 1;
    long a = sumA / n, b = sumB / n;
    if (a < loA) loA = a;
    if (a > hiA) hiA = a;
    if (b < loB) loB = b;
    if (b > hiB) hiB = b;
  }
  outA = hiA - loA;
  outB = hiB - loB;
}

void printMvOrNull(float v) {
  if (isnan(v)) Serial.print("null"); else Serial.printf("%.0f", v);
}

const char* resetReason();

// Costs about two seconds of the fast channel: 1.2 s of noise windows, then the LEDs have
// to be off and released to measure their drops. Hence on request, never on a timer.
void emitDiag() {
  allLedsOff(); delay(SETTLE_MS);
  long nT = 0, nS = 0;
  noiseMv(SENS_T, SENS_S, nT, nS);
  long drops[NLED];
  for (int i = 0; i < NLED; i++) drops[i] = diodeMv(LED_PINS[i]);
  fastLedOn();

  Serial.printf("{\"diag\":{\"fw\":\"%s\",\"ver\":\"%s\",\"build\":\"%s\"", FIRMWARE, FW_VERSION, __DATE__);
  Serial.printf(",\"reset\":\"%s\",\"up\":%lu", resetReason(), millis());
  Serial.printf(",\"heap\":%u,\"heapMin\":%u,\"loopMax\":%lu",
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMinFreeHeap(), loopMaxUs);
  // Reserved: sampling with the motor gated off is not implemented, so it is always false.
  Serial.print(",\"gated\":false");
  Serial.print(",\"dark\":{\"trans\":"); printMvOrNull(darkT);
  Serial.print(",\"scat\":"); printMvOrNull(darkS); Serial.print("}");
  Serial.print(",\"diode\":{");
  for (int i = 0; i < NLED; i++) Serial.printf("%s\"%s\":%ld", i ? "," : "", LED_NAMES[i], drops[i]);
  Serial.printf("},\"noise\":{\"trans\":%ld,\"scat\":%ld}", nT, nS);
  Serial.printf(",\"probe\":{\"present\":%s,\"count\":%d,\"addr\":",
                haveProbe ? "true" : "false", probeCount);
  if (probeAddr[0]) Serial.printf("\"%s\"}", probeAddr); else Serial.print("null}");
  Serial.printf(",\"radio\":{\"ch\":%d,\"fail\":%u,\"drift\":%u,\"heard\":",
                NOW_CHANNEL, (unsigned)radioFail, (unsigned)radioDrift);
  if (lastHeardFromFace) Serial.printf("%lu}", millis() - lastHeardFromFace);
  else Serial.print("null}");
  // Both channels moving together across a stirrer toggle means the motor is talking to the
  // sensors, through the supply or through the light path. The host compares these four.
  Serial.printf(",\"motor\":{\"stir\":%d,\"transBefore\":", stirring ? STIR_PCT : 0);
  printMvOrNull(motorTransBefore); Serial.print(",\"transAfter\":"); printMvOrNull(motorTransAfter);
  Serial.print(",\"scatBefore\":"); printMvOrNull(motorScatBefore);
  Serial.print(",\"scatAfter\":"); printMvOrNull(motorScatAfter);
  Serial.println("}}}");
}

const char* resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "POWERON";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_SW:       return "SW";
    case ESP_RST_PANIC:    return "PANIC";
    case ESP_RST_INT_WDT:  return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT:      return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_EXT:      return "EXT";
    default:               return "UNKNOWN";
  }
}

void takeBlank() {
  fastLedOn(); delay(SETTLE_MS * 4);
  blankT = avgMv(SENS_T);
  blankS = avgMv(SENS_S);
  haveBlank = true;
  Serial.printf("# blank stored: transmission %.0f mV, scatter %.0f mV\n", blankT, blankS);
}

// ---------------------------------------------------------------- ESP-NOW link to the BOX-3
// The JSON over USB is unchanged and stays the source of truth for the phone. This is a
// second, one-way-plus-commands radio path so the screen in the orange can show a run and
// start one. Broadcast, so there is nothing to pair and no MAC to configure.
void handleCommand(char c);

void holdChannel() {
  uint8_t ch = 0; wifi_second_chan_t sc;
  esp_wifi_get_channel(&ch, &sc);
  if (ch != NOW_CHANNEL) {
    esp_wifi_set_channel(NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    radioDrift++;
    Serial.printf("# radio had drifted to channel %d, pulled back to %d\n", ch, NOW_CHANNEL);
  }
}

void nowSendReading(float elapsed, float t, float s, float aT, float aS, float tC) {
  if (!nowReady) return;
  holdChannel();
  PeelPacket p;
  p.magic = 'P'; p.version = 1;
  p.t = elapsed; p.trans = t; p.scat = s; p.absT = aT; p.absS = aS; p.tC = tC;
  for (int i = 0; i < 4; i++) {
    float mv = sweep[PACKET_LEDS[i]];
    p.sweep[i] = (isnan(mv) || mv < 0) ? 0xFFFF : (uint16_t)mv;
  }
  p.stir = stirring ? STIR_PCT : 0;
  p.flags = (sweptThisLine ? 1 : 0) | (haveBlank ? 2 : 0) | (autoZero ? 4 : 0) | (stirring ? 8 : 0);
  // ESP_OK here means queued for transmission, nothing more: broadcasts get no ack.
  if (esp_now_send(BCAST, (const uint8_t *)&p, sizeof(p)) != ESP_OK) radioFail++;
}

void onNowRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len >= 1) lastHeardFromFace = millis();
  // one ASCII letter, the same alphabet the USB commands use
  if (len >= 1 && data[0] >= 'a' && data[0] <= 'z') handleCommand((char)data[0]);
}

void nowBegin() {
  // A station with no access point goes looking for one, and scanning drags the radio off our
  // channel: the link then works for a few seconds after boot and dies. So: nothing stored,
  // no reconnecting, no power-save naps, and holdChannel() checks every second.
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, true);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) { Serial.println("# esp-now init FAILED"); return; }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = NOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) { Serial.println("# esp-now peer FAILED"); return; }
  esp_now_register_recv_cb(onNowRecv);
  nowReady = true;
  Serial.printf("# esp-now up on channel %d, this board is %s\n", NOW_CHANNEL,
                WiFi.macAddress().c_str());
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  for (int i = 0; i < NLED; i++) {
    pinMode(LED_PINS[i], OUTPUT); digitalWrite(LED_PINS[i], LOW);
    sweep[i] = NAN; sweepS[i] = NAN;
  }
  pinMode(SENS_T, INPUT);
  pinMode(SENS_S, INPUT);
  pinMode(LED_BUILTIN, OUTPUT); digitalWrite(LED_BUILTIN, HIGH);
  pinMode(MOTOR, OUTPUT);
  analogWriteFrequency(MOTOR, 20000);
  delay(300);
  probe.begin();
  probeCount = probe.getDeviceCount();
  haveProbe = probeCount > 0;
  if (haveProbe) {
    DeviceAddress addr;
    if (probe.getAddress(addr, 0)) {
      for (uint8_t i = 0; i < 8; i++) sprintf(probeAddr + i * 2, "%02X", addr[i]);
    }
    probe.setResolution(12); probe.setWaitForConversion(false); probe.requestTemperatures();
  }
  fastLedOn();
  stirOn();
  Serial.println();
  Serial.printf("# 17_stream ready. Fast channel = %s LED. Stirrer %d%%. Temperature probe: %s\n",
                LED_NAMES[FAST_LED], STIR_PCT, haveProbe ? "found" : "absent, reporting null");
  Serial.println("# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer, d diagnostics");
  nowBegin();
}

void handleCommand(char c) {
  if (c == 'b') takeBlank();
  else if (c == 'z') { tZero = millis(); Serial.println("# t = 0 marked"); }
  else if (c == 'a') { autoZero = !autoZero; Serial.printf("# auto t=0 %s\n", autoZero ? "on" : "off"); }
  else if (c == 's') { tZero = 0; Serial.println("# run stopped"); }
  else if (c == 'm') {
    // Take both channels just before the stirrer changes state; the report a second later
    // takes the "after" pair. Together they are the evidence for MOTOR_COUPLING.
    motorTransBefore = avgMv(SENS_T);
    motorScatBefore = avgMv(SENS_S);
    motorTransAfter = NAN; motorScatAfter = NAN;
    if (stirring) { stirOff(); Serial.println("# stirrer off"); } else { stirOn(); Serial.println("# stirrer on"); }
    stirChangedMs = millis();
  }
  else if (c == 'd') diagPending = true;
}

void loop() {
  static unsigned long lastReport = 0, lastSweep = 0, lastLoopUs = 0;
  static float lastT = 0;

  // How long the worst pass through here took. The stirrer ramp and a sweep both block,
  // and a blocked loop is what a line gap on the host side actually is.
  unsigned long nowUs = micros();
  if (lastLoopUs && nowUs - lastLoopUs > loopMaxUs) loopMaxUs = nowUs - lastLoopUs;
  lastLoopUs = nowUs;

  if (Serial.available()) {
    char c = Serial.read(); while (Serial.available()) Serial.read();
    handleCommand(c);
  }

  if (millis() - lastSweep >= SWEEP_EVERY_MS) { lastSweep = millis(); doSweep(); }

  if (millis() - lastReport < REPORT_MS) return;
  lastReport = millis();
  digitalWrite(LED_BUILTIN, LOW);

  float t = avgMv(SENS_T);
  float s = avgMv(SENS_S);

  if (stirChangedMs && isnan(motorTransAfter) && millis() - stirChangedMs >= 1000) {
    motorTransAfter = t;
    motorScatAfter = s;
  }

  // Auto t = 0: the tablet hitting the water makes transmission fall sharply.
  // A sweep disturbs the fast channel for one line (transmission reads a few mV), which looks
  // exactly like a tablet landing. Swept lines neither trigger the detector nor seed it.
  if (!sweptThisLine) {
    if (autoZero && tZero == 0 && haveBlank && lastT > 1 && t < lastT * (1.0f - DROP_FRACTION)) {
      tZero = millis();
      Serial.println("# t = 0 detected from the transmission drop");
    }
    lastT = t;
  }

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
  for (int i = 0; i < NLED; i++) {
    Serial.printf("%s\"%s\":", i ? "," : "", LED_NAMES[i]);
    printMvOrNull(sweep[i]);
  }
  Serial.print("},\"sweepS\":{");
  for (int i = 0; i < NLED; i++) {
    Serial.printf("%s\"%s\":", i ? "," : "", LED_NAMES[i]);
    printMvOrNull(sweepS[i]);
  }
  Serial.print("},\"dark\":{\"trans\":"); printMvOrNull(darkT);
  Serial.print(",\"scat\":"); printMvOrNull(darkS); Serial.print("}");
  Serial.printf(",\"stir\":%d,\"swept\":%s}\n", stirring ? STIR_PCT : 0, sweptThisLine ? "true" : "false");
  nowSendReading(elapsed, t, s, absorbance(blankT, t), absorbance(blankS, s), tC);
  sweptThisLine = false;
  // After the data line, so a host that asked for it while a run is going does not get the
  // diagnostics wedged in the middle of the second.
  if (diagPending) { diagPending = false; emitDiag(); }
  digitalWrite(LED_BUILTIN, HIGH);
}
