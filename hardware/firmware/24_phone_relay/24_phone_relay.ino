// Seeed USB-to-BOX-3 display relay, based on the local working bench firmware.
// Sensor, probe, LED and stirrer behavior below is preserved.
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
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>
#include "../display_protocol.h"

const int SENS_T = 8;                   // [XIAO D9]
const int SENS_S = 9;                   // [XIAO D10]
const int LED_PINS[4]   = { 3, 4, 5, 6 };   // [XIAO D2 D3 D4 D5]
const char* LED_NAMES[4] = { "red", "yellow", "green", "blue" };
// All six LEDs on the build: the four swept colours, then IR 940 (D0) and violet (D1).
// Only the lamp test drives the last two; the sweep still covers four.
const int ALL_LEDS[6] = { 3, 4, 5, 6, 1, 2 };
bool lampTest = false;
// Automatic t = 0 is ARMED by a blank and DISARMED by a run starting or stopping, so a finished
// run cannot restart itself: the stirrer stopping shifts the transmission reading by more than
// the trigger, and that used to read as a tablet landing. It also waits out a hold-off after the
// blank, and compares against a running average of calm lines rather than the single last line.
bool  tzArmed = false;
unsigned long tzHoldOff = 0;
float tzBase[5]; int tzN = 0, tzLow = 0;
void tzReset(unsigned long holdMs) { tzN = 0; tzLow = 0; tzHoldOff = millis() + holdMs; }
// Which of the four swept LEDs are actually working. The blue one did not survive assembly,
// so the sweep skips it and reports null for it: an honest gap, not a junk number.
const bool LED_FITTED[4] = { true, true, true, false };   // red, yellow, green, blue
const int FAST_LED = 2;                 // green: brightest on this rig, so best signal to noise
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
DisplayCommandParser displayParser;
const uint8_t DISPLAY_MAC[6] = {0x80, 0x45, 0x6B, 0x64, 0x89, 0x18};
QueueHandle_t displayReplies;
DisplayPacket displayRequest = {'D', 1, 0, 0};
bool displayWaiting = false;
unsigned long displaySentAt = 0;
int displayAttempts = 0;

void sendDisplay(uint8_t scene) {
  displayRequest.scene = scene;
  displayRequest.sequence++;
  displayWaiting = true;
  displayAttempts = 0;
  displaySentAt = 0;
}

void serviceDisplay() {
  DisplayPacket reply;
  while (xQueueReceive(displayReplies, &reply, 0) == pdTRUE) {
    if (!displayWaiting || reply.sequence != displayRequest.sequence ||
        reply.scene != displayRequest.scene) continue;
    displayWaiting = false;
    Serial.printf("{\"display\":\"peel\",\"text\":\"%s\",\"version\":1,\"via\":\"seeed-radio\"}\n",
                  reply.scene ? "Peel" : "Hello!");
  }
  if (!displayWaiting) return;
  if (displayAttempts && millis() - displaySentAt < 400) return;
  if (!nowReady || displayAttempts >= 8) {
    displayWaiting = false;
    Serial.println("{\"displayError\":\"BOX-3 did not acknowledge. Check its power and radio firmware.\"}");
    return;
  }
  holdChannel();
  esp_now_send(DISPLAY_MAC, (const uint8_t *)&displayRequest, sizeof(displayRequest));
  displaySentAt = millis();
  displayAttempts++;
}
const unsigned long SWEEP_EVERY_MS = 10000;
const float DROP_FRACTION  = 0.15;      // auto t=0: transmission 15 % under its recent calm average,
                                        // on two lines running. 6 % on one line was inside the noise.
const int   STIR_PCT       = 30;        // stirring speed, found on the bench with the 6x3 mm magnets:
                                        // slow enough that the bar stays locked, and the motor's
                                        // electrical noise in the sensor readings is far lower
const int   STIR_START_PCT = 50;        // a TT gearbox will not start at 30 %, so it creeps up to
                                        // this first, holds, and creeps back down
                                        // speed instead and keep it identical across every run.

OneWire oneWire(TEMP_PIN);
DallasTemperature probe(&oneWire);
bool haveProbe = false;

float blankT = 0, blankS = 0;
bool  haveBlank = false;
bool  autoZero = false;          // OFF by default: a run starts when someone presses the screen.
                                 // The light reaching the sensor on this build is weak and comes and
                                 // goes (570 mV one minute, 170 the next), so a drop detector cannot
                                 // be trusted not to start the motor by itself. 'a' turns it on.
unsigned long tZero = 0;                // 0 means the run has not started
float sweep[4] = { NAN, NAN, NAN, NAN };
bool  sweptThisLine = false;
bool  stirring = false;           // off until a run begins
int   stirPct  = STIR_PCT;        // live stirrer speed: digit keys and + / - change it

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
  // No kick at all. Any jump in hub speed leaves the stir bar behind: it snaps to the magnets and
  // sits there instead of turning. Creep up past the speed the gearbox needs to break loose, hold,
  // then creep down to the stirring speed. 2 % every 40 ms up, 1 % every 25 ms down.
  int peak = max(stirPct, STIR_START_PCT);
  for (int p = 8; p < peak; p += 2) { analogWrite(MOTOR, (p * 255) / 100); delay(40); }
  analogWrite(MOTOR, (peak * 255) / 100);
  if (peak > stirPct) {
    delay(800);
    for (int p = peak; p > stirPct; p--) { analogWrite(MOTOR, (p * 255) / 100); delay(25); }
  }
  analogWrite(MOTOR, (stirPct * 255) / 100);
  stirring = true;
}
void stirSpeed(int pct) {                       // change speed on the fly; 0 stops
  stirPct = constrain(pct, 0, 100);
  if (stirPct == 0) { analogWrite(MOTOR, 0); stirring = false; stirPct = STIR_PCT; Serial.println("# stirrer off"); return; }
  static int lastPct = 0;
  if (stirring) { int from = lastPct ? lastPct : stirPct;
    for (int q = from; q != stirPct; q += (stirPct > from ? 1 : -1)) { analogWrite(MOTOR, (q * 255) / 100); delay(25); }
    analogWrite(MOTOR, (stirPct * 255) / 100); }
  else stirOn();
  lastPct = stirPct;
  Serial.printf("# stirrer %d%%\n", stirPct);
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
  allLedsOff(); delay(SETTLE_MS);
  long dark = avgMv(SENS_T);
  for (int i = 0; i < 4; i++) {
    if (!LED_FITTED[i]) { sweep[i] = NAN; continue; }
    digitalWrite(LED_PINS[i], HIGH); delay(SETTLE_MS);
    sweep[i] = avgMv(SENS_T) - dark;
    digitalWrite(LED_PINS[i], LOW);
  }
  fastLedOn(); delay(SETTLE_MS);
  sweptThisLine = true;
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
    Serial.printf("# radio had drifted to channel %d, pulled back to %d\n", ch, NOW_CHANNEL);
  }
}

void nowSendReading(float elapsed, float t, float s, float aT, float aS, float tC) {
  if (!nowReady) return;
  holdChannel();
  PeelPacket p;
  p.magic = 'P'; p.version = 1;
  p.t = elapsed; p.trans = t; p.scat = s; p.absT = aT; p.absS = aS; p.tC = tC;
  for (int i = 0; i < 4; i++) p.sweep[i] = isnan(sweep[i]) ? 0xFFFF : (uint16_t)sweep[i];
  p.stir = stirring ? stirPct : 0;
  p.flags = (sweptThisLine ? 1 : 0) | (haveBlank ? 2 : 0) | (autoZero ? 4 : 0) | (stirring ? 8 : 0);
  // Broadcasts are sent once, unacknowledged, and in a hall full of Wi-Fi about 40 % of them
  // are lost. The packet is a complete statement of state, so sending it three times is
  // harmless to a receiver that gets more than one and takes loss from 40 % to about 6 %.
  for (int k = 0; k < 3; k++) {
    esp_now_send(BCAST, (const uint8_t *)&p, sizeof(p));
    if (k < 2) delay(4);
  }
}

// A command is one ASCII letter, the same alphabet as USB, optionally followed by a sequence
// byte. Senders repeat each command three times with the same sequence byte; we act once.
// This runs in the Wi-Fi task, so it only leaves a note: the stirrer ramp blocks for 1.5 s
// and must happen in loop(), not here.
volatile char pendingCmd = 0;
void onNowRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len == sizeof(DisplayPacket) && data[0] == 'A' && data[1] == 1 &&
      data[2] <= 1 && !memcmp(info->src_addr, DISPLAY_MAC, 6)) {
    DisplayPacket reply;
    memcpy(&reply, data, sizeof(reply));
    xQueueSend(displayReplies, &reply, 0);
    return;
  }
  if (len < 1 || data[0] < 'a' || data[0] > 'z') return;
  static int lastSeq = -1; static unsigned long lastSeqAt = 0;
  if (len >= 2) {
    if (data[1] == lastSeq && millis() - lastSeqAt < 2000) return;   // a repeat of one we have
    lastSeq = data[1]; lastSeqAt = millis();
  }
  pendingCmd = (char)data[0];
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
  memcpy(peer.peer_addr, DISPLAY_MAC, 6);
  if (esp_now_add_peer(&peer) != ESP_OK) { Serial.println("# display peer FAILED"); return; }
  esp_now_register_recv_cb(onNowRecv);
  nowReady = true;
  Serial.printf("# esp-now up on channel %d, this board is %s\n", NOW_CHANNEL,
                WiFi.macAddress().c_str());
}

void setup() {
  Serial.begin(115200);
  // Never wait for a USB host. With the default timeout every print blocks while nobody is
  // reading the port, the loop stalls, and the radio goes silent: measured, zero packets a
  // second with the port closed. The instrument has to run whether or not a phone is listening.
#if ARDUINO_USB_CDC_ON_BOOT && ARDUINO_USB_MODE
  Serial.setTxTimeoutMs(0);
#endif
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  for (int i = 0; i < 6; i++) { pinMode(ALL_LEDS[i], OUTPUT); digitalWrite(ALL_LEDS[i], LOW); }
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
  // The stirrer stays off until a run begins: see beginRun() and the 's' command.
  Serial.println();
  Serial.printf("# 17_stream ready. Fast channel = %s LED. Stirrer off until a run, then %d%%. Temperature probe: %s\n",
                LED_NAMES[FAST_LED], STIR_PCT, haveProbe ? "found" : "absent, reporting null");
  Serial.println("# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer, l lamp test, d diode check");
  displayReplies = xQueueCreate(8, sizeof(DisplayPacket));
  if (!displayReplies) { Serial.println("# display queue FAILED"); return; }
  nowBegin();
}

void handleCommand(char c) {
  if (c == 'b') { takeBlank(); tzArmed = true; tzReset(4000); }
  else if (c == 'z') { tzArmed = false; tZero = millis(); Serial.println("# t = 0 marked"); if (!stirring) { stirOn(); Serial.println("# stirrer on"); } }
  else if (c == 'a') { autoZero = !autoZero; Serial.printf("# auto t=0 %s\n", autoZero ? "on" : "off"); }
  else if (c == 's') { tzArmed = false; tZero = 0; Serial.println("# run stopped"); if (stirring) { stirOff(); Serial.println("# stirrer off"); } }
  else if (c >= '0' && c <= '9') stirSpeed((c - '0') * 10);      // 0 off, 1-9 = 10-90 %
  else if (c == '+') stirSpeed((stirring ? stirPct : 30) + 5);
  else if (c == '-') stirSpeed((stirring ? stirPct : 40) - 5);
  else if (c == 'd') {                       // diode check: is each LED in circuit, and which way round
    // Release the pin to the weak internal pull-up and read it with its own ADC channel: the node
    // settles at that LED's forward drop. ~3300 mV = open (lead off, or LED backwards),
    // under ~60 mV = shorted to ground, anything between = a diode that conducts.
    static const char *NM[6] = {"red", "yellow", "green", "blue", "ir", "violet"};
    int was[6];
    for (int i = 0; i < 6; i++) { was[i] = digitalRead(ALL_LEDS[i]); digitalWrite(ALL_LEDS[i], LOW); }
    delay(150);                              // all dark: no LED lights its neighbour's die
    Serial.print("# diode check mV:");
    for (int i = 0; i < 6; i++) {
      int wasHigh = was[i];
      pinMode(ALL_LEDS[i], INPUT_PULLUP); delay(60);
      long v = 0; for (int k = 0; k < 20; k++) { v += analogReadMilliVolts(ALL_LEDS[i]); delay(2); }
      v /= 20;
      pinMode(ALL_LEDS[i], OUTPUT); digitalWrite(ALL_LEDS[i], LOW);
      Serial.printf(" %s %ld%s", NM[i], v, v > 3000 ? "(OPEN)" : v < 60 ? "(SHORT)" : "");
    }
    Serial.println();
    for (int i = 0; i < 6; i++) digitalWrite(ALL_LEDS[i], was[i]);
  }
  else if (c == 'l') {                       // lamp test: every LED on, for aiming and checking
    lampTest = !lampTest;
    if (lampTest) { for (int i = 0; i < 6; i++) digitalWrite(ALL_LEDS[i], HIGH);
                    Serial.println("# lamp test on: all six LEDs lit, sweep paused"); }
    else          { for (int i = 0; i < 6; i++) digitalWrite(ALL_LEDS[i], LOW); fastLedOn();
                    Serial.println("# lamp test off"); }
  }
  else if (c == 'm') { if (stirring) { stirOff(); Serial.println("# stirrer off"); } else { stirOn(); Serial.println("# stirrer on"); } }
}

void loop() {
  static unsigned long lastReport = 0, lastSweep = 0;
  static float lastT = 0;

  for (int count = 0; count < 32 && Serial.available(); count++) {
    uint8_t scene = 0;
    char legacy = 0;
    if (displayParser.feed(Serial.read(), scene, legacy)) sendDisplay(scene);
    if (legacy) handleCommand(legacy);
  }
  if (displayReplies) serviceDisplay();
  if (pendingCmd) { char c = pendingCmd; pendingCmd = 0; handleCommand(c); }

  // The probe may be plugged in after boot. Keep looking for it, and notice if it goes away.
  static unsigned long lastProbeLook = 0;
  if (!haveProbe && millis() - lastProbeLook > 3000) {
    lastProbeLook = millis();
    probe.begin();
    if (probe.getDeviceCount() > 0) {
      haveProbe = true;
      probe.setResolution(12); probe.setWaitForConversion(false); probe.requestTemperatures();
      Serial.println("# temperature probe found");
    }
  }

  if (!lampTest && millis() - lastSweep >= SWEEP_EVERY_MS) { lastSweep = millis(); doSweep(); }

  if (millis() - lastReport < REPORT_MS) return;
  lastReport = millis();
  digitalWrite(LED_BUILTIN, LOW);

  float t = avgMv(SENS_T);
  float s = avgMv(SENS_S);

  // Auto t = 0: the tablet hitting the water makes transmission fall sharply.
  // Automatic t = 0. Swept lines are ignored: a sweep disturbs the fast channel for one line.
  if (!sweptThisLine && autoZero && tzArmed && tZero == 0 && millis() > tzHoldOff) {
    float mean = 0; for (int i = 0; i < tzN; i++) mean += tzBase[i]; if (tzN) mean /= tzN;
    if (tzN >= 3 && t < mean * (1.0f - DROP_FRACTION)) {
      if (++tzLow >= 2) {
        tZero = millis(); tzArmed = false;
        Serial.println("# t = 0 detected from the transmission drop");
        if (!stirring) { stirOn(); Serial.println("# stirrer on"); }
      }
    } else {                                   // a calm line: it joins the average, a low one never does
      tzLow = 0;
      if (tzN < 5) tzBase[tzN++] = t; else { for (int i = 1; i < 5; i++) tzBase[i - 1] = tzBase[i]; tzBase[4] = t; }
    }
  }
  lastT = t;

  float tC = NAN;
  if (haveProbe) {
    tC = probe.getTempCByIndex(0); probe.requestTemperatures();
    static int misses = 0;                       // -127 five times running: it has been unplugged
    if (tC < -100) { if (++misses >= 5) { haveProbe = false; misses = 0; Serial.println("# temperature probe lost"); } }
    else misses = 0;
  }

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
  Serial.printf("},\"stir\":%d,\"swept\":%s}\n", stirring ? stirPct : 0, sweptThisLine ? "true" : "false");
  nowSendReading(elapsed, t, s, absorbance(blankT, t), absorbance(blankS, s), tC);
  sweptThisLine = false;
  digitalWrite(LED_BUILTIN, HIGH);
}
