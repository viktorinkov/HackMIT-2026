# Bench data

Real captures from the assembled electronics, 2026-09-19. Nothing here is simulated. Use these to
build the simulator and the fault thresholds against, and to check a parser against real lines.

Bench conditions for every file: XIAO and BOX-3 on USB from a Mac, room lighting (LED fixtures,
120 Hz ripple), LEDs and both TEMT6000s **loose on the table, not yet in the enclosure**, so there
is no controlled optical path. Absolute light levels are therefore ambient and arbitrary. What is
meaningful is structure: floors, noise, timing, line format, and what each fault looks like.

| file | firmware | what it shows |
|---|---|---|
| `session_full_cycle.jsonl` | `17_stream` | **The canonical protocol capture.** 74 s, every line from the XIAO and the BOX-3 with a host timestamp, plus the commands sent. Idle → `b` blank at 12 s → `z` start at 38 s → `m` stirrer on at 52 s → `m` off at 58 s → `s` stop at 68 s. Seven sweeps. |
| `session_full_cycle_xiao.log` | `17_stream` | The same session, XIAO side only, as plain text. |
| `session_full_cycle.csv` | `17_stream` | The same session, data lines parsed into columns. |
| `box3_face_heartbeat.log` | `21_box3_face` | The face's 3 s heartbeat during that session: frame rate, link state, packet age. |
| `espnow_link_test.log` | `17_stream` + `19_box3_link` | Radio packets against USB lines, and a command going BOX-3 → XIAO. |
| `selftest_short_window.log` | `18_selftest` | A ~12 ms averaging window aliasing 120 Hz room light: ±100 mV of slow wander with nothing changing. |
| `selftest_lockin_100ms.log` | `18_selftest` | 100 ms window plus lock-in: residual ±4 mV; an LED facing a sensor reads +30 mV or more. |
| `diode_check.csv` | `18_selftest` | Forward-drop node voltage of all six LEDs through the MCU's own ADC. |
| `light_response.csv` | `18_selftest` | Both sensors responding to light, independently of each other. |
| `motor_coupling_dc.csv` | `18_selftest` | A DC motor on the USB 5 V rail driving both ADC channels up by about 2000 mV. |

## Numbers worth knowing, from `session_full_cycle`

| condition | trans (mV) | scat (mV) | tC |
|---|---|---|---|
| stirrer off, line not swept (n = 62) | 175–458, mean 332 | 21–99, mean 54 | 20.94–23.69, sd 0.52 |
| **swept lines** (n = 7) | **0–218, mean 66** | **197–386, mean 258** | unchanged |
| **stirrer on** at 100 % PWM, 20 kHz (n = 4) | 385–599, mean 489 | **166–312, mean 212** | unchanged |

- Line period: mean 1.016 s, min 0.91 s, max 2.18 s. The long one is the stirrer's start ramp,
  which blocks the loop for about 1.5 s.
- Every sweep value is **negative** (−66 to −345 mV): there is no optical path on the bench.
- `tC` moves by up to ±1.5 °C between consecutive seconds with the radio on. With the radio off
  (`18_selftest` files) the same probe is steady to 0.06 °C.
