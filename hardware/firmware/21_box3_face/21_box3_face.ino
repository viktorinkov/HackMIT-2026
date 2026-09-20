// 21_box3_face - Peel's face on the ESP32-S3-BOX-3.
//
// Vector-style eyes, pill shaped, orange on black, driven by what the instrument is actually
// doing. The phone stays the readout; this screen is the character and the control.
//
//   arduino-cli compile --upload -p <port> --fqbn esp32:esp32:esp32s3box sketches/21_box3_face
//
// Mute button (left side, above the USB-C):
//   linked   : tap = stirrer on/off, hold 1.2 s = start a run
//   no link  : tap = step through the moods, so the face can be demoed on its own
//
// The screen lives in the wall of an optical instrument, so the background is always black,
// the palette is orange only, and the backlight drops while a run is measuring.

// Bisecting a panel problem: with WITH_RADIO 0 the sketch never starts Wi-Fi, so the face runs
// on its own and cycles moods by itself.
#define WITH_RADIO 1
#if WITH_RADIO
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#endif
#include <Arduino_GFX_Library.h>
#include "face_types.h"

// ---- BOX-3 hardware, from Espressif's BSP header ----------------------------------------
#define LCD_DC 4
#define LCD_CS 5
#define LCD_SCK 7
#define LCD_MOSI 6
#define LCD_RST 48
#define LCD_BL 47
#define BTN_MUTE 1

// Panel bring-up. THE TRAP ON THIS BOARD: the BOX-3's LCD reset line is ACTIVE HIGH (Espressif's
// BSP sets reset_active_high = 1; it is shared with the touch reset through an inverter). Every
// display library ends its reset sequence with the pin HIGH, which here holds the panel in reset
// forever: backlight on, screen white, nothing you send is heard. So the library gets NO reset
// pin (exactly as its own ESP32_S3_BOX_3 device entry does) and we drive GPIO48 ourselves.
Arduino_DataBus *bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED);
Arduino_GFX *panel = new Arduino_ILI9342(bus, GFX_NOT_DEFINED /* RST: see above */, 0);
Arduino_GFX *gfx = nullptr;          // canvas if PSRAM allows it, else the panel itself
bool buffered = false;

// ---- the radio packet, identical in sketches/17_stream ----------------------------------
#define NOW_CHANNEL 1
static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
volatile bool havePacket = false;
PeelPacket latest;
unsigned long lastHeard = 0;

#if WITH_RADIO
void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(PeelPacket)) return;
  PeelPacket p;
  memcpy(&p, data, sizeof(p));
  if (p.magic != 'P' || p.version != 1) return;
  latest = p; havePacket = true; lastHeard = millis();
}

void sendCommand(char c) {
  uint8_t b = (uint8_t)c;
  esp_now_send(BCAST, &b, 1);
}
#else
void sendCommand(char c) {}
#endif

// ---- palette: orange on black, nothing bright ---------------------------------------------
static inline uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}
const uint16_t C_EYE   = rgb(255, 122, 24);
const uint16_t C_HI    = rgb(255, 178, 77);
const uint16_t C_DIM   = rgb(138, 59, 0);
const uint16_t C_TEXT  = rgb(120, 52, 0);
const uint16_t C_BG    = 0x0000;

// ---- moods ---------------------------------------------------------------------------------
const char *MOOD_NAME[] = {"SLEEP", "CURIOUS", "READY", "WATCH", "SURPRISE", "RUNNING", "HAPPY", "WORRIED"};
Mood mood = M_SLEEP, prevMood = M_SLEEP;
unsigned long moodSince = 0;

Look moodLook(Mood m) {
  switch (m) {
    case M_SLEEP:    return {1.00f, 0.08f, 0.00f, 0.00f,  0.0f, 0.0f,  0.0f, 1.00f};
    case M_CURIOUS:  return {1.00f, 1.05f, 0.10f, 0.00f, -0.3f, 0.0f, -0.1f, 1.05f};
    case M_READY:    return {1.00f, 1.00f, 0.05f, 0.00f,  0.0f, 0.0f,  0.0f, 1.00f};
    case M_WATCH:    return {0.95f, 0.90f, 0.22f, 0.00f,  0.2f, 0.0f,  0.1f, 0.95f};
    case M_SURPRISE: return {1.25f, 1.30f, 0.00f, 0.00f,  0.0f, 0.0f, -0.1f, 1.10f};
    case M_RUNNING:  return {0.92f, 0.78f, 0.28f, 0.05f,  0.15f, 0.0f, 0.05f, 0.95f};
    case M_HAPPY:    return {1.05f, 0.55f, 0.00f, 0.45f,  0.0f, 0.0f,  0.0f, 1.00f};
    case M_WORRIED:  return {0.95f, 0.95f, 0.18f, 0.00f, -0.45f, 0.0f, 0.0f, 1.00f};
  }
  return {1, 1, 0, 0, 0, 0, 0, 1};
}

Look cur = {1, 1, 0, 0, 0, 0, 0, 1};
float blinkT = 0;              // 0 open, 1 shut
unsigned long nextBlink = 0, nextSaccade = 0;
float gazeTX = 0, gazeTY = 0, gazeX = 0, gazeY = 0;

const int BASE_W = 74, BASE_H = 108, EYE_GAP = 104, CY = 112;

void drawEye(int cx, int cy, int w, int h, float lidTop, float lidBot, float tilt, uint16_t col) {
  int x = cx - w / 2, y = cy - h / 2;
  int r = w / 2;
  gfx->fillRoundRect(x, y, w, h, min(r, h / 2), col);
  if (h > 24) {   // highlight, upper outer corner
    gfx->fillRoundRect(x + w / 6, y + h / 8, w / 4, h / 5, w / 8, C_HI);
  }
  if (lidTop > 0.01f) gfx->fillRect(x - 2, y - 2, w + 4, (int)(h * lidTop) + 2, C_BG);
  if (lidBot > 0.01f) gfx->fillRect(x - 2, y + h - (int)(h * lidBot), w + 4, (int)(h * lidBot) + 4, C_BG);
  if (fabsf(tilt) > 0.02f) {    // angled inner lid: the whole expression lives here
    int drop = (int)(h * 0.45f * fabsf(tilt));
    if (tilt > 0) gfx->fillTriangle(x - 2, y - 2, x + w + 2, y - 2, x + w + 2, y + drop, C_BG);
    else          gfx->fillTriangle(x - 2, y - 2, x + w + 2, y - 2, x - 2, y + drop, C_BG);
  }
}

void drawFace(float dim) {
  if (buffered) gfx->fillScreen(C_BG);          // free in RAM, and the flush is one clean frame
  else { gfx->fillRect(30, 20, 120, 180, C_BG); gfx->fillRect(170, 20, 120, 180, C_BG); }
  uint16_t col = (dim < 0.5f) ? C_DIM : C_EYE;
  float breathe = 1.0f + 0.03f * sinf(millis() / 900.0f);
  float openness = 1.0f - blinkT;
  int w = (int)(BASE_W * cur.w);
  int h = (int)(BASE_H * cur.h * breathe * openness);
  if (h < 6) h = 6;
  int gap = (int)(EYE_GAP * cur.gap);
  int gx = (int)(gazeX * 26), gy = (int)(gazeY * 18);
  int cy = CY + gy + (int)(6 * (1.0f - cur.h));
  // left eye mirrors the tilt so the expression is symmetric
  drawEye(160 - gap / 2 + gx, cy, w, h, cur.lidTop, cur.lidBot, -cur.tilt, col);
  drawEye(160 + gap / 2 + gx, cy, w, h, cur.lidTop, cur.lidBot, cur.tilt, col);
}

void drawStatus(const char *line) {
  gfx->fillRect(0, 210, 320, 22, C_BG);
  gfx->setTextSize(1);
  gfx->setTextColor(C_TEXT);
  int len = strlen(line);
  gfx->setCursor(160 - len * 3, 218);
  gfx->print(line);
}

// ---- state from the instrument --------------------------------------------------------------
bool linked() { return havePacket && (millis() - lastHeard) < 5000; }

Mood moodFromState(char *status, size_t n) {
  if (!linked()) { snprintf(status, n, "NO LINK - TAP TO DEMO"); return M_SLEEP; }
  PeelPacket p = latest;
  static bool wasRunning = false;
  static unsigned long startedAt = 0, endedAt = 0;
  static bool hadBlank = false; static unsigned long blankAt = 0;
  bool blank = p.flags & 2;
  if (blank && !hadBlank) blankAt = millis();
  hadBlank = blank;
  bool running = p.t >= 0;
  if (running && !wasRunning) startedAt = millis();
  if (!running && wasRunning) endedAt = millis();
  wasRunning = running;

  if (!isnan(p.tC) && p.tC > 40) { snprintf(status, n, "TOO HOT %.1fC", p.tC); return M_WORRIED; }
  if (running) {
    if (millis() - startedAt < 2000) { snprintf(status, n, "TABLET IN"); return M_SURPRISE; }
    if (isnan(p.absS)) snprintf(status, n, "RUNNING %.0fs - HOLD TO STOP", p.t);
    else               snprintf(status, n, "RUNNING %.0fs  CLOUD %.2f - HOLD TO STOP", p.t, -p.absS);
    return M_RUNNING;
  }
  if (endedAt && millis() - endedAt < 4000) { snprintf(status, n, "DONE"); return M_HAPPY; }
  if (blankAt && millis() - blankAt < 1800) { snprintf(status, n, "BLANK STORED"); return M_HAPPY; }
  if (!blank) { snprintf(status, n, "CLEAR WATER IN? HOLD FOR BLANK"); return M_CURIOUS; }
  snprintf(status, n, "READY - HOLD TO START");
  return M_READY;
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_MUTE, INPUT_PULLUP);
  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, HIGH);

  // No canvas: the framebuffer would land in PSRAM and this SPI path cannot DMA out of PSRAM,
  // which leaves the screen lit and blank. Draw straight at the panel and clear only the
  // regions that change.
  pinMode(LCD_RST, OUTPUT);
  digitalWrite(LCD_RST, HIGH); delay(20);     // assert reset (active high on this board)
  digitalWrite(LCD_RST, LOW);  delay(150);    // release it, and leave it released for good
  if (!panel->begin()) Serial.println("# panel begin failed");
  Arduino_Canvas *canvas = new Arduino_Canvas(320, 240, panel, 0, 0);
  if (canvas->begin(GFX_SKIP_OUTPUT_BEGIN)) { gfx = canvas; buffered = true; }
  else { gfx = panel; buffered = false; Serial.println("# no framebuffer, drawing direct"); }
  // first-light check: name each colour on serial as it goes up, so a wrong colour order or
  // inversion is obvious from the outside
  const uint16_t seq[] = {0x0000, rgb(255,122,24), 0x0000};
  const char *seqName[] = {"BLACK", "ORANGE", "BLACK"};
  for (int i = 0; i < 3; i++) {
    Serial.printf("# screen should now be %s\n", seqName[i]);
    gfx->fillScreen(seq[i]);
    if (buffered) gfx->flush();
    delay(900);
  }

#if WITH_RADIO
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, true);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_err_t e1 = esp_now_init();
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = NOW_CHANNEL; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
  esp_err_t e2 = esp_now_add_peer(&peer);
  esp_err_t e3 = esp_now_register_recv_cb(onRecv);
  uint8_t ch = 0; wifi_second_chan_t sc;
  esp_wifi_get_channel(&ch, &sc);
  Serial.printf("# esp-now init %d, peer %d, cb %d, on channel %d\n", e1, e2, e3, ch);
  Serial.printf("\n# 21_box3_face ready, %s\n", WiFi.macAddress().c_str());
#else
  Serial.println("\n# 21_box3_face ready, radio OFF, moods cycle on their own");
#endif
  moodSince = millis();
  nextBlink = millis() + 2000;
}

void loop() {
  // ---- button ---------------------------------------------------------------------------
  static bool wasDown = false; static unsigned long downAt = 0; static bool held = false;
  static int demoMood = 0;
  bool down = digitalRead(BTN_MUTE) == LOW;
  if (down && !wasDown) { downAt = millis(); held = false; }
  if (down && !held && millis() - downAt > 1200) {
    held = true;
    if (linked()) {
      PeelPacket p = latest;
      if (p.t >= 0)            sendCommand('s');   // running      -> stop
      else if (!(p.flags & 2)) sendCommand('b');   // no blank yet -> take one
      else                     sendCommand('z');   // ready        -> start
    }
  }
  if (!down && wasDown && !held && millis() - downAt > 40) {
    if (linked()) sendCommand('m');
    else { demoMood = (demoMood + 1) % 8; }
  }
  wasDown = down;

  static unsigned long lastBeat = 0; static uint32_t frames = 0; frames++;
  if (millis() - lastBeat > 3000) {
#if WITH_RADIO
    uint8_t ch = 0; wifi_second_chan_t sc;
    esp_wifi_get_channel(&ch, &sc);
    if (ch != NOW_CHANNEL) {
      esp_wifi_set_channel(NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
      Serial.printf("# radio had drifted to channel %d, pulled back\n", ch);
    }
#endif
    Serial.printf("# %lu fps, link %s, last packet %lu ms ago\n", (unsigned long)(frames / 3),
                  linked() ? "UP" : "down", havePacket ? millis() - lastHeard : 0UL);
    frames = 0; lastBeat = millis();
  }

  // ---- mood -----------------------------------------------------------------------------
  char status[48];
  Mood want = moodFromState(status, sizeof(status));
  if (!linked()) {
#if !WITH_RADIO
    demoMood = (millis() / 3500) % 8;          // no radio: parade the moods
#endif
    want = (Mood)demoMood;
    snprintf(status, sizeof(status), "DEMO - %s", MOOD_NAME[demoMood]);
  }
  if (want != mood) { prevMood = mood; mood = want; moodSince = millis(); }

  // ease toward the target look
  Look tgt = moodLook(mood);
  float k = 0.18f;
  cur.w += (tgt.w - cur.w) * k;      cur.h += (tgt.h - cur.h) * k;
  cur.lidTop += (tgt.lidTop - cur.lidTop) * k;
  cur.lidBot += (tgt.lidBot - cur.lidBot) * k;
  cur.tilt += (tgt.tilt - cur.tilt) * k;
  cur.gap += (tgt.gap - cur.gap) * k;

  // blinks and saccades, the two things that make it look alive
  unsigned long now = millis();
  if (now > nextBlink && mood != M_SLEEP) {
    blinkT += 0.34f;
    if (blinkT >= 1.0f) blinkT = 1.0f;
    if (blinkT >= 1.0f) { nextBlink = now + random(2200, 6000); }
  } else if (blinkT > 0) {
    blinkT -= 0.28f;
    if (blinkT < 0) blinkT = 0;
  }
  if (now > nextSaccade) {
    nextSaccade = now + random(900, 2600);
    if (mood == M_RUNNING || mood == M_WATCH) { gazeTX = 0; gazeTY = 0.15f; }
    else { gazeTX = (random(-100, 100)) / 260.0f; gazeTY = (random(-60, 60)) / 260.0f; }
  }
  gazeX += (gazeTX - gazeX) * 0.12f;
  gazeY += (gazeTY - gazeY) * 0.12f;

  // ---- draw -----------------------------------------------------------------------------
  drawFace(mood == M_RUNNING ? 0.4f : 1.0f);
  drawStatus(status);
  if (buffered) gfx->flush();

  // dim the backlight while measuring: this screen sits inside the optics
  analogWrite(LCD_BL, mood == M_RUNNING ? 40 : 255);
}
