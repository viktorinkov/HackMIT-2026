# Hardware overview

Peel measures a tablet dissolving in a stirred vial by shining LEDs through it. Two boards:

| board | job | firmware |
|---|---|---|
| **Seeed XIAO ESP32-S3** | the instrument: drives six LEDs and the stirrer, reads two light sensors and a temperature probe, streams to the phone over USB | `firmware/17_stream` |
| **Espressif ESP32-S3-BOX-3** (main unit, no dock) | the face in the wall of the enclosure: shows state, takes a blank, starts and stops a run | `firmware/21_box3_face` |

```
 Android phone ──USB-C (data + XIAO power)──► XIAO ESP32-S3 ──ESP-NOW ch 1──► ESP32-S3-BOX-3
                                                │                                   ▲
              LEDs ×6, TEMT6000 ×2, DS18B20, stirrer driver                 power bank (USB-C)
```

## Where everything is written down

| file | contents |
|---|---|
| `BOM.md` | every part, with values and markings |
| `PINMAP.md` | XIAO and BOX-3 pin assignments |
| `WIRING.md` | the breadboard, hole by hole |
| `POWER.md` | who powers what, current budget, the rule that protects the phone |
| `SIGNALS.md` | every signal the device produces: source, unit, range, rate |
| `BASELINES.md` | measured electrical behaviour: floors, noise, diode drops, timing |
| `FAULTS.md` | what each fault looks like in the data, with thresholds |
| `PROTOCOL.md` | the USB line protocol and the ESP-NOW packet |
| `SYSTEM_SETTINGS.md` | toolchain versions, build targets, firmware constants, radio and display settings |
| `BOX3.md` | the BOX-3: display bring-up, reset polarity, touch, audio, buttons |
| `ENCLOSURE.md` | the printed enclosure: datums and where each part sits |
| `../data/` | real captures from this hardware; see `data/README.md` |

## State of the build

Electronics are complete and running on two snapped mini breadboards. Verified on the real parts:
USB streaming, all six LEDs in circuit and correctly oriented, both light sensors responding and
independent, the temperature probe, the stirrer driver, the radio link in both directions, and
the BOX-3 face driving a run from its button.

Not yet done: the parts are **not in the enclosure**, so there is no optical path and no light
reading means anything in absolute terms. The IR LED's emission is unverified. The power bank is
not fitted. The phone app has not yet talked to the board.
