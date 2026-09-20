# Power

| consumer | source | path |
|---|---|---|
| XIAO, both TEMT6000s, DS18B20, six LEDs | the **phone**, over the USB-C data cable | VBUS → XIAO regulator → 3V3 |
| stirrer motor | the **power bank** | plus into B b16, minus into B b10 |
| ESP32-S3-BOX-3 | the **power bank** | its own USB-C, on the unit's left side |

**The rule that protects the phone: the power bank's 5 V and the phone's VBUS must never be
tied together.** The XIAO's 5V pin *is* VBUS. So when the power bank feeds the motor rail, the
jumper **A j1 → B b16 comes out**. Grounds are common (B b10 is on the GND net); only the plus
rails stay separate.

Bench state on 2026-09-19: the power bank is not fitted yet. Everything, motor included, runs from
USB through the A j1 → B b16 jumper. All captures in `data/` were taken that way.

## Budget
| load | current |
|---|---|
| XIAO, radio on | ~100 mA, bursts to ~300 mA on transmit |
| LEDs | 1–20 mA each; green is on continuously; one extra during a sweep |
| TEMT6000 ×2, DS18B20 | < 5 mA |
| TT motor | 150–250 mA running, up to ~1 A at start or stall |
| BOX-3, backlight on | ~150–250 mA |

A phone's USB host port supplies roughly 500 mA. The instrument without the motor fits easily.
With the motor on the same rail it does not, reliably: see `FAULTS.md`, *brownout* and *motor
coupling*. That is the reason the motor has its own supply.

## Grounding
The motor's return current and the sensors' ground reference share Board B's GND rows. With the
motor's supply minus landed at **b10**, on the emitter's own row, motor current returns to the bank
without crossing the jumper that carries the sensors' ground back to the XIAO (B f1 → A j2).
