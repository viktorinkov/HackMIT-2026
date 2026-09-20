// Phone-controlled BOX-3 display via Seeed ESP-NOW relay.
// No sensor or motor control. USB remains available for bench display testing.
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Arduino_GFX_Library.h>
#include "../display_protocol.h"
#include "peel_sprites.h"

Arduino_DataBus *bus = new Arduino_ESP32SPI(4, 5, 7, 6, GFX_NOT_DEFINED);
Arduino_GFX *panel = new Arduino_ILI9342(bus, GFX_NOT_DEFINED, 0);
Arduino_Canvas *canvas;
uint16_t *pixels;
const int WIDTH = 320, HEIGHT = 240;
const uint16_t ORANGE = 0xFC23;
char command[32];
size_t commandLength = 0;
bool overflow = false;
bool greeting = true;
int lastFrame = -1;
const uint8_t SEEED_MAC[6] = {0x68, 0xEE, 0x8F, 0x50, 0x27, 0xE8};
QueueHandle_t displayCommands;
bool radioReady = false;

void onDisplayRequest(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != sizeof(DisplayPacket) || data[0] != 'D' || data[1] != 1 ||
      data[2] > 1 || memcmp(info->src_addr, SEEED_MAC, 6)) return;
  DisplayPacket request;
  memcpy(&request, data, sizeof(request));
  xQueueSend(displayCommands, &request, 0);
}

void beginRadio() {
  displayCommands = xQueueCreate(8, sizeof(DisplayPacket));
  if (!displayCommands) return;
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, true);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) return;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, SEEED_MAC, 6);
  peer.channel = 1;
  peer.ifidx = WIFI_IF_STA;
  if (esp_now_add_peer(&peer) != ESP_OK) return;
  esp_now_register_recv_cb(onDisplayRequest);
  radioReady = true;
}

void serviceRadio() {
  if (!radioReady) return;
  DisplayPacket request;
  while (xQueueReceive(displayCommands, &request, 0) == pdTRUE) {
    greeting = request.scene == 0;
    render((millis() / PEEL_FRAME_MS) & 1);
    // Only acknowledge after the panel has received the frame.
    request.magic = 'A';
    esp_now_send(SEEED_MAC, (const uint8_t *)&request, sizeof(request));
    report();
  }
  static unsigned long channelChecked = 0;
  if (millis() - channelChecked >= 1000) {
    uint8_t channel; wifi_second_chan_t second;
    esp_wifi_get_channel(&channel, &second);
    if (channel != 1) esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);
    channelChecked = millis();
  }
}

void spans(const uint16_t *p) {
  while (*p != 0xFFFF) {
    int y = *p++, x = *p++, n = *p++;
    if (y < HEIGHT && x + n <= WIDTH) memcpy(pixels + y * WIDTH + x, p, n * 2);
    p += n;
  }
}

void render(int frame) {
  memset(pixels, 0, WIDTH * HEIGHT * 2);
  spans(PEEL_ready_chr_right);
  spans(frame ? PEEL_ready_fx_right_1 : PEEL_ready_fx_right_0);
  const char *label = greeting ? "Hello!" : "Peel";
  canvas->setTextColor(ORANGE);
  canvas->setTextSize(3);
  canvas->setCursor((WIDTH - strlen(label) * 18) / 2, 10);
  canvas->print(label);
  canvas->flush();
}

void report() {
  Serial.printf("{\"display\":\"peel\",\"text\":\"%s\",\"version\":1}\n", greeting ? "Hello!" : "Peel");
}

void receiveCommands() {
  // Bounded input work so an overactive host cannot starve the display.
  for (int count = 0; count < 128 && Serial.available(); count++) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      command[commandLength] = 0;
      if (!overflow && (!strcmp(command, "HELLO") || !strcmp(command, "PEEL"))) {
        greeting = !strcmp(command, "HELLO");
        render((millis() / PEEL_FRAME_MS) & 1);
        report();
      } else if (commandLength || overflow) {
        Serial.println("{\"error\":\"Use HELLO or PEEL followed by newline\"}");
      }
      commandLength = 0;
      overflow = false;
    } else if (commandLength < sizeof(command) - 1) {
      command[commandLength++] = c;
    } else {
      overflow = true;
    }
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  pinMode(47, OUTPUT);
  digitalWrite(47, LOW);
  // BOX-3 LCD reset is active HIGH; leave it LOW after reset.
  pinMode(48, OUTPUT);
  digitalWrite(48, HIGH); delay(20);
  digitalWrite(48, LOW); delay(150);
  panel->begin();
  canvas = new Arduino_Canvas(WIDTH, HEIGHT, panel, 0, 0);
  if (!canvas->begin(GFX_SKIP_OUTPUT_BEGIN) || !(pixels = canvas->getFramebuffer())) {
    Serial.println("{\"error\":\"No framebuffer\"}");
    for (;;) delay(1000);
  }
  render(0);
  beginRadio();
  digitalWrite(47, HIGH);
  Serial.println("{\"displayReady\":1}");
  report();
}

void loop() {
  serviceRadio();
  receiveCommands();
  int frame = (millis() / PEEL_FRAME_MS) & 1;
  if (frame != lastFrame) { render(frame); lastFrame = frame; }
  static unsigned long lastReport = 0;
  if (millis() - lastReport >= 3000) { report(); lastReport = millis(); }
  delay(5);
}
