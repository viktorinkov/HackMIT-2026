# ESP32-S3-BOX-3

Main unit only, no dock or bracket: the enclosure pocket is cut to the bare unit. Powered through
its own USB-C on the left side. Module ESP32-S3-WROOM-1-N16R16V.

## The display reset line is active HIGH
Espressif's BSP sets `reset_active_high = 1`: GPIO48 reaches the panel through an inverter and is
shared with the touch controller's reset. Display libraries end their reset pulse with the pin
**high**, which on this board holds the panel in reset: backlight on, screen white, no response to
SPI at any clock, with any driver.

**Give the display library no reset pin. Drive GPIO48 yourself: high for 20 ms, then low, and
leave it low for good.** `Arduino_GFX`'s own `ESP32_S3_BOX_3` device entry does the same
(`GFX_NOT_DEFINED` for RST).

## Bring-up that works
```cpp
Arduino_DataBus *bus = new Arduino_ESP32SPI(4 /*DC*/, 5 /*CS*/, 7 /*SCK*/, 6 /*MOSI*/, GFX_NOT_DEFINED);
Arduino_GFX *panel   = new Arduino_ILI9342(bus, GFX_NOT_DEFINED /*RST*/, 0 /*rotation*/);

pinMode(48, OUTPUT); digitalWrite(48, HIGH); delay(20); digitalWrite(48, LOW); delay(150);
pinMode(47, OUTPUT); digitalWrite(47, HIGH);           // backlight
panel->begin();                                        // default host, default clock
Arduino_Canvas *fb = new Arduino_Canvas(320, 240, panel, 0, 0);
fb->begin(GFX_SKIP_OUTPUT_BEGIN);                      // PSRAM framebuffer; flush() once a frame
```
320 × 240, landscape, RGB565, colours correct without inversion. Drawing straight to the panel
flickers when regions are cleared and redrawn; the framebuffer does not. Every `begin()` on a bus
object that was given the reset pin re-asserts reset, so never create a second one.

Espressif's BSP selects the panel driver by touch chip: TT21100 at I2C `0x24` → ST7789 driver,
otherwise ILI9341 with vendor init, and mirrors the panel on both axes. This unit runs correctly
on `Arduino_ILI9342` at rotation 0.

## Peripherals
| | |
|---|---|
| Touch | I2C SDA 8, SCL 18, INT 3. TT21100 (`0x24`) or GT911 (`0x5D` / `0x14`), depending on the unit. Not used yet |
| Speaker | ES8311 codec over I2S (MCLK 2, BCLK 17, LRCK 45, DOUT 15), amplifier enable GPIO46 high. Not used yet |
| Microphones | ES7210, I2S DIN 16. Not used |
| IMU | ICM-42607-P on I2C. Not used |
| Buttons | mute GPIO1 (active low), boot GPIO0, reset |
| LEDs | power, mute |

## What the face does (`firmware/21_box3_face`)
Two pill-shaped eyes, orange on black, with blinks, saccades and a breathing scale; eight moods
eased over ~300 ms; a one-line status in dim orange at the bottom.

| instrument state | how it knows | mood | status line |
|---|---|---|---|
| no packets for 5 s | link timeout | sleep (or, with a tap, steps through every mood as a demo) | `DEMO - <MOOD>` |
| no blank stored | `flags` bit 1 clear, `t < 0` | curious | `CLEAR WATER IN? HOLD FOR BLANK` |
| blank just stored | bit 1 rising edge, 1.8 s | happy | `BLANK STORED` |
| ready | blank stored, `t < 0` | ready | `READY - HOLD TO START` |
| run just started | `t` crossed 0, first 2 s | surprise | `TABLET IN` |
| running | `t ≥ 0` | running, dim eyes, **backlight 40/255** | `RUNNING 12s  CLOUD 0.31 - HOLD TO STOP` |
| run just ended | `t` fell below 0, 4 s | happy | `DONE` |
| `tC > 40` | packet | worried | `TOO HOT 41.2C` |

Mute button: tap sends `m`; a 1.2 s hold sends whichever of `b`, `z`, `s` is the next step.

## Restoring the factory firmware
`factory_demo-ESP-BOX-3-1_2_4.bin` from `https://espressif.github.io/esp-box/`, a 15 MB merged
image: `esptool --chip esp32s3 -p <port> -b 921600 write_flash 0x0 <file>`. About 100 s.
