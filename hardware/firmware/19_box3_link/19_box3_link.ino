// 19_box3_link - ESP32-S3-BOX-3 end of the Peel radio link.
//
// Stage one, deliberately no graphics: prove the BOX-3 hears the XIAO's readings and that a
// command sent from here reaches it. The eyes and the Start button get built on top of this.
//
// The phone stays the readout. This screen is for feedback and for launching a run.
//
//   arduino-cli compile --upload -p <port> --fqbn esp32:esp32:esp32s3box firmware/19_box3_link
//
// Commands it can send, the same alphabet the USB serial uses:
//   b take a blank    z mark t=0 (this is what Start will send)    s stop
//   a toggle auto t=0 m toggle the stirrer

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

// ---- the radio packet, identical in firmware/17_stream ----------------------------------
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

// The mute button on the left side is the only physical control until the touch UI lands:
// a tap toggles the stirrer, holding it starts a run.
#define BTN_MUTE 1
volatile bool havePacket = false;
PeelPacket latest;
unsigned long lastHeard = 0;
uint32_t packets = 0;

void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(PeelPacket)) return;
  PeelPacket p;
  memcpy(&p, data, sizeof(p));
  if (p.magic != 'P' || p.version != 1) return;
  latest = p;
  havePacket = true;
  lastHeard = millis();
  packets++;
}

void sendCommand(char c) {
  uint8_t b = (uint8_t)c;
  esp_err_t r = esp_now_send(BCAST, &b, 1);
  Serial.printf("# sent '%c' %s\n", c, r == ESP_OK ? "ok" : "FAILED");
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 4000) {}
  delay(300);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) { Serial.println("# esp-now init FAILED"); return; }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = NOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  esp_now_register_recv_cb(onRecv);

  Serial.println();
  Serial.printf("# 19_box3_link ready. channel %d, this board is %s\n", NOW_CHANNEL,
                WiFi.macAddress().c_str());
  pinMode(BTN_MUTE, INPUT_PULLUP);
  Serial.println("# keys: b blank, z start (t=0), s stop, a auto t=0, m stirrer");
  Serial.println("# mute button: tap = stirrer on/off, hold 1.2 s = start a run");
  Serial.println("# waiting for the orange...");
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    while (Serial.available()) Serial.read();
    if (c == 'b' || c == 'z' || c == 's' || c == 'a' || c == 'm') sendCommand(c);
  }

  // --- the mute button, debounced, tap versus hold ---------------------------------------
  static bool wasDown = false;
  static unsigned long downAt = 0;
  static bool heldFired = false;
  bool down = digitalRead(BTN_MUTE) == LOW;
  if (down && !wasDown) { downAt = millis(); heldFired = false; }
  if (down && !heldFired && millis() - downAt > 1200) {
    sendCommand('z'); Serial.println("# hold: START"); heldFired = true;
  }
  if (!down && wasDown && !heldFired && millis() - downAt > 40) {
    sendCommand('m'); Serial.println("# tap: stirrer toggled");
  }
  wasDown = down;

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint < 1000) return;
  lastPrint = millis();

  if (!havePacket) {
    Serial.printf("# nothing heard yet (%lu s)\n", millis() / 1000);
    return;
  }
  PeelPacket p = latest;
  unsigned long age = millis() - lastHeard;
  Serial.printf("rx %lu  age %lums  t %6.1f  trans %6.0f  scat %6.0f  cloud ",
                (unsigned long)packets, age, p.t, p.trans, p.scat);
  if (isnan(p.absS)) Serial.print("  --  "); else Serial.printf("%6.3f", -p.absS);
  if (isnan(p.tC)) Serial.print("  tC --"); else Serial.printf("  tC %.2f", p.tC);
  Serial.printf("  stir %d%%  %s%s%s\n", p.stir,
                (p.flags & 2) ? "blank " : "", (p.flags & 4) ? "auto " : "",
                (p.flags & 1) ? "swept" : "");
}
