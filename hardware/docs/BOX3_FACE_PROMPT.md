# Build the face for Peel's screen (ESP32-S3-BOX-3)

You are building the on-device UI for **Peel**, a pill-dissolution tester built into a 3D-printed
orange. An ESP32-S3-BOX-3 is mounted in the wall of the orange with its screen looking out
through a window. The phone app is the readout: graphs, numbers, history. **Your screen is the
face and the control surface**, nothing else. It shows how the instrument feels and it starts a
run.

Think Anki Vector's eyes, but the character is a pill in an orange. Expressive, alive, a bit
cheeky. It should be the thing people crowd around at the demo table.

## The hardware, exactly

ESP32-S3-BOX-3 main unit, 66.1 x 61.2 x 17.6 mm, ESP32-S3 with 16 MB flash and 16 MB octal PSRAM.

| part | detail |
|---|---|
| Display | 320 x 240, SPI, ILI9341-family controller (the spec sheet says ILI9342C; Espressif's BSP drives it with their `esp_lcd_ili9341` component) |
| LCD pins | MOSI/DATA0 **GPIO6**, PCLK **GPIO7**, CS **GPIO5**, DC **GPIO4**, RST **GPIO48**, backlight **GPIO47**, SPI3_HOST, 40 MHz |
| Touch | capacitive, on the shared I2C bus: SDA **GPIO8**, SCL **GPIO18**, INT **GPIO3**. Units ship with either a **TT21100** (addr 0x24) or a **GT911** (addr 0x5D or 0x14). Probe both. |
| Audio out | ES8311 codec, I2S: MCLK **GPIO2**, SCLK/BCLK **GPIO17**, LRCK **GPIO45**, DOUT **GPIO15**. Amplifier enable **GPIO46**, must be driven high for sound. Speaker is on the right side of the unit. |
| Audio in | ES7210 ADC, DSIN **GPIO16**. Not needed. |
| Buttons | Mute **GPIO1**, Boot/config **GPIO0** |
| Dock I2C | SCL GPIO40, SDA GPIO41. Not used. |

Source: Espressif's own BSP header, `bsp/esp-box-3/include/bsp/esp-box-3.h` in `espressif/esp-bsp`.
Trust these over any blog post.

## Read this before you touch the display

**The BOX-3's LCD reset line is active HIGH.** Espressif's BSP sets `reset_active_high = 1`; the
line is shared with the touch controller through an inverter. Every display library finishes
its reset pulse with the pin high, which on this board holds the panel in reset forever:
backlight on, screen white, deaf to everything you send. **Give the
library no reset pin, and drive GPIO48 yourself: high for 20 ms, then low, and leave it low.**

There is already a working face in `firmware/21_box3_face`: `Arduino_GFX`, `Arduino_ILI9342`
on `Arduino_ESP32SPI` with default host and clock, a PSRAM `Arduino_Canvas` framebuffer for
flicker-free frames, 20 fps with ESP-NOW running. Start from it. Do not start from a blank file.

## Toolchain, non-negotiable

The build machine has **arduino-cli with esp32 core 3.3.11** and nothing else. No ESP-IDF, no
PlatformIO. Your work must compile and upload with exactly this:

```
arduino-cli compile --upload -p <port> --fqbn esp32:esp32:esp32s3box firmware/21_box3_face
```

Put everything in `firmware/21_box3_face/`. Any library you need must be installable with
`arduino-cli lib install "<name>"`. For the panel, LovyanGFX or Arduino_GFX both drive this
display. The working configuration is in `docs/BOX3.md`: `Arduino_ILI9342`, rotation 0, no
inversion, colours correct as they are.

## The link you must not break

The instrument's microcontroller (a Seeed XIAO ESP32-S3) broadcasts one reading a second over
**ESP-NOW on channel 1** and listens for single-letter commands back. This already works. There
is a working face with this radio code in `firmware/21_box3_face`; keep its radio code exactly
as it is, including the channel hold.

```c
#define NOW_CHANNEL 1
static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
struct __attribute__((packed)) PeelPacket {
  uint8_t  magic;        // 'P'
  uint8_t  version;      // 1
  float    t, trans, scat, absT, absS, tC;   // NAN means "not available"
  uint16_t sweep[4];     // red, yellow, green, blue, in mV. 0xFFFF = not swept yet
  uint8_t  stir;         // stirrer percent, 0 when off
  uint8_t  flags;        // bit0 swept this second, bit1 blank stored, bit2 auto t=0, bit3 stirring
};
```

What the fields mean:

- `t` is seconds since the tablet went in. **`-1.0` means no run is in progress.**
- `trans` is the light straight through the vial, `scat` is light at 90 degrees.
- `absS` is the scatter absorbance. **Cloudiness is `-absS`**: it climbs as the tablet breaks up.
  It is NAN until a blank has been taken.
- `tC` is the liquid temperature, NAN if no probe.

Commands you can send, as a single ASCII byte to the broadcast address:

| byte | effect |
|---|---|
| `z` | mark t = 0, which is **Start** |
| `b` | take a blank (clear water in the vial, lid on) |
| `s` | stop the run |
| `m` | toggle the stirrer |
| `a` | toggle automatic t = 0 detection |

Rules: do not change the channel, the packet or the command letters. Never call `WiFi.begin()`
or join an access point, since that moves the channel and kills the link. Keep the ESP-NOW
receive callback to a memcpy and a flag; all drawing happens in `loop()`.

## Three constraints that outrank prettiness

1. **This screen lives inside an optical instrument.** The thing being measured is light through
   a liquid a few centimetres away. A bright screen leaks light into the measurement. So:
   **black background always**, orange on black, no white fills, no full-screen flashes, no
   bright transitions. When a run is active (`t >= 0`), **dim the backlight** and keep the
   animation minimal. The face can be lively while idle and must go calm and dark while
   measuring. If you break this, the instrument reads its own screen.
2. **Never block.** No `delay()` longer than about 10 ms in the main path. The radio callback
   must stay tiny. Target a steady 30 fps; use a PSRAM sprite or dirty-rectangle redraws rather
   than clearing the screen every frame.
3. **Silence is the default for sound.** Audio is a bonus, it starts muted, and the mute button
   (GPIO1) toggles it. Never let audio setup failure stop the face from running.

## What to build

### The face

Vector-style eyes: two shapes that live on a black field and act like eyes rather than
illustrations of eyes. The character is a **pill in an orange**, so:

- Eyes are **capsules** (stadium shapes, a pill lying down or standing up), not circles or
  squares. Rounded ends, crisp edges.
- Palette: orange on black. Something like `#FF7A18` primary, `#FFB24D` for the highlight,
  `#8A3B00` for dim states. No white above about 60% brightness. Never pure white.
- Give them the Vector vocabulary: idle drift, spontaneous **blinks** (squash to a line and
  back), **saccades** to look around, squash and stretch on emotion changes, a subtle breathing
  scale. Eyelids as angled shapes that cut the capsule are how you get most expressions.
- Nice touch if you can: a faint segmented arc behind the eyes, like the inside of an orange.
  Keep it dim.

### Emotions, driven by the instrument's real state

| state | how you know | feeling |
|---|---|---|
| no link | no packet for 5 s | asleep, eyes closed, slow breathing, occasional one-eye peek |
| idle, ready | packets arriving, `t < 0`, blank stored (flags bit1) | calm, alert, looking around |
| needs a blank | `t < 0`, no blank stored | curious, questioning, a small prompt |
| blank taken | after `b` | a quick happy squint |
| waiting for the tablet | just after Start | focused, watching, eyes forward |
| tablet detected | `t` crosses 0 | surprise, a big pop, then delight |
| running | `t >= 0` | concentrating, calm, dim. This is the state that must stay dark. |
| cloudiness climbing fast | `-absS` rising quickly | excited, wide eyes |
| stirring | flags bit3 | a slow rhythmic sway, in time with the stirrer |
| done or stopped | after `s` | satisfied, sleepy, slow blink |
| too hot | `tC > 40` | worried |

Emotions should **blend**, not snap. A state machine with eased transitions of 200 to 400 ms.

### Controls

- **Tap anywhere: Start.** Sends `z`. The biggest, most obvious interaction, because a person at
  a demo table will poke the screen. Give it a clear reaction: eyes snap to attention plus a
  chirp.
- **Long press, about 1.5 s: take a blank.** Sends `b`. Show a ring or a fill so the press is
  visible.
- **Two-finger tap or a tap in the top corner: toggle the stirrer.** Sends `m`.
- While a run is going, a tap should **stop** it (`s`), with a confirmation gesture rather than a
  dialog.
- If the touch controller cannot be identified, fall back to the **mute button** (GPIO1) as
  Start so the device is never dead.

Keep any text tiny and rare. A number or two at most, in the corner, dim. The phone has the data.

### Sound, optional and last

ES8311 over I2S with the amp enable on GPIO46. Short, soft, synthesized: a rising chirp on
Start, a pop on tablet-detected, a two-note sigh when a run ends, a quiet tick per stir cycle.
Under 300 ms each, never during the quiet part of a run, and off by default. If you cannot get
the codec up in reasonable time, ship without it and say so.

## Deliverables

1. `firmware/21_box3_face/21_box3_face.ino` (plus any helper files in the same folder), compiling
   with the arduino-cli line above with no manual steps.
2. A `DEMO_MODE` compile-time flag that cycles every emotion on a timer with no radio at all, so
   the face can be shown and tuned with nothing else plugged in.
3. A short `README.md` in the sketch folder: which library you used, which touch controller you
   found, what the panel needed for rotation/colour, what works, what does not.

## How it will be judged

- The link still works: with the XIAO powered, packets arrive and `z` starts a run.
- It holds 30 fps and never stalls the radio.
- The background is black and the screen goes dim during a run.
- An outsider looking at the face can tell whether the instrument is idle, working, or finished,
  without reading a word.
- It makes people smile.

If something in this brief conflicts with reality on the hardware, reality wins: say what you
found and what you did instead.
