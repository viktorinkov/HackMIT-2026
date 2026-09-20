// Phone-controlled BOX-3 display. No sensor, motor, radio, or touch commands.
// USB 115200: HELLO\n or PEEL\n. Each valid command emits its rendered state.
#include <Arduino_GFX_Library.h>
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
  digitalWrite(47, HIGH);
  Serial.println("{\"displayReady\":1}");
  report();
}

void loop() {
  receiveCommands();
  int frame = (millis() / PEEL_FRAME_MS) & 1;
  if (frame != lastFrame) { render(frame); lastFrame = frame; }
  static unsigned long lastReport = 0;
  if (millis() - lastReport >= 3000) { report(); lastReport = millis(); }
  delay(5);
}
