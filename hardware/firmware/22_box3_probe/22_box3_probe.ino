// 22_box3_probe - find what actually drives the BOX-3 panel.
//
// Colour is useless as a signal here: a white backlight photographs blue under warm light.
// So every config paints BLACK and holds it. If the screen goes DARK, that config works.
// If it stays lit and white, the controller never got our init.
//
// Serial says which config is on screen, counting down, so you can call out which one darkened.
//
//   arduino-cli compile --upload -p <port> --fqbn esp32:esp32:esp32s3box sketches/22_box3_probe

#include <Arduino_GFX_Library.h>

#define LCD_DC 4
#define LCD_CS 5
#define LCD_SCK 7
#define LCD_MOSI 6
#define LCD_RST 48
#define LCD_BL 47

SPIClass spiH(HSPI);
SPIClass spiF(FSPI);

void hold(const char *label) {
  for (int i = 3; i > 0; i--) {
    Serial.printf("#   %s : black, %d\n", label, i);
    delay(1000);
  }
}

// bus 0 = Arduino_ESP32SPI on SPI3, 1 = on SPI2, 2 = HWSPI on SPI3, 3 = HWSPI on SPI2
void tryOne(const char *label, int busKind, bool is9341, uint32_t hz) {
  Serial.printf("# %s : bus %d, %s, %lu Hz\n", label, busKind, is9341 ? "ILI9341" : "ILI9342",
                (unsigned long)hz);
  Arduino_DataBus *bus;
  switch (busKind) {
    case 0: bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED, HSPI); break;
    case 1: bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED, FSPI); break;
    case 2: spiH.begin(LCD_SCK, -1, LCD_MOSI, LCD_CS);
            bus = new Arduino_HWSPI(LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED, &spiH); break;
    default: spiF.begin(LCD_SCK, -1, LCD_MOSI, LCD_CS);
            bus = new Arduino_HWSPI(LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED, &spiF); break;
  }
  Arduino_GFX *panel = is9341 ? (Arduino_GFX *)new Arduino_ILI9341(bus, LCD_RST, 1, false)
                              : (Arduino_GFX *)new Arduino_ILI9342(bus, LCD_RST, 0, false);
  if (!panel->begin(hz)) {
    Serial.println("#   begin() returned false");
    return;
  }
  panel->fillScreen(0x0000);
  hold(label);
  panel->fillScreen(0xFFFF);      // back to white, so the next config starts from lit
  delay(400);
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) {}
  delay(300);
  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, HIGH);
  Serial.println("\n# watch for the screen going DARK. Call out which config did it.");

  tryOne("ONE",   0, false, 20000000);   // ESP32SPI SPI3, ILI9342
  tryOne("TWO",   2, false, 20000000);   // HWSPI    SPI3, ILI9342
  tryOne("THREE", 2, true,  10000000);   // HWSPI    SPI3, ILI9341, slow
  tryOne("FOUR",  3, false, 10000000);   // HWSPI    SPI2, ILI9342, slow
  Serial.println("# all four done");
}

void loop() {}
