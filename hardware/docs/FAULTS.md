# Fault signatures

What each failure looks like in the data. Thresholds are starting points taken from
`BASELINES.md`; each names the measurement behind it. "Seen" means it was produced on this
hardware and there is a capture; "derived" means it follows from the circuit and has not been
provoked.

| id | what is wrong | signature | threshold | status |
|---|---|---|---|---|
| `MOTOR_COUPLING` | motor current shares the sensors' ground or supply | `trans` **and** `scat` move together within 1 s of `stir` changing, with no light change | both shift by > 100 mV on a stirrer toggle; > 500 mV is severe | **seen**: `motor_coupling_dc.csv` (+2000 mV), `session_full_cycle.csv` 52–58 s (+150 mV, erratic) |
| `SWEPT_LINE` | not a fault: a sweep disturbed this line | `swept: true`; `trans` collapses toward 0, `scat` rises | exclude the line from any rate or drop calculation | **seen**: 7 of 7 sweeps |
| `NOT_ASSEMBLED` | no optical path between LEDs and sensors | all four `sweep` values negative or within ±15 mV | every colour < +15 mV for 3 sweeps | **seen**: every sweep on the bench |
| `LED_OPEN` | LED missing, reversed, broken leg, resistor out | diode-check node ≈ 3300 mV | > 3000 mV | derived; healthy values in `diode_check.csv` |
| `LED_SHORT` | anode shorted to ground | diode-check node near 0 | < 50 mV | derived |
| `LED_SWAPPED` | two LEDs on each other's pins | diode-check order no longer IR < red < yellow < green < blue < violet | any inversion by > 100 mV | derived from the measured ordering |
| `SENSOR_UNPOWERED` | TEMT6000 lost VCC or GND, or SIG wire out | reading below the ADC's own floor, and flat | < 30 mV on unswept lines for 5 s | derived; floor is 91–150 mV |
| `SENSOR_SATURATED` | too much light, or SIG shorted to 3V3 | pinned at full scale | > 3000 mV for 3 s | derived |
| `SENSOR_NOISY` | loose jumper, or ambient light getting in | large spread on a still sensor | > 60 mV peak-to-peak across 100 ms means | **seen** while hand-held: 207–267 mV |
| `LID_OPEN` | room light reaching the sensors | dark reading well above the floor, or 120 Hz ripple in the signal | dark > 250 mV | derived; shaded bench reads 140–160 mV, open bench 300–830 mV |
| `PROBE_MISSING` | DS18B20 unplugged, or the 5.1 kΩ pull-up missing | `tC` null; boot banner says `absent` | `tC` null for 3 lines | derived from firmware behaviour |
| `PROBE_ERROR` | bad read | `tC` = −127.0 or 85.0 | exact match | library sentinels |
| `TEMP_JITTER` | supply or radio noise on the OneWire line | consecutive `tC` differ by more than a liquid can change | > 0.5 °C between consecutive lines | **seen**: up to ±1.5 °C with the radio on |
| `BROWNOUT_RESET` | supply sagged, usually the motor starting on USB power | boot banner reappears mid-session; `t` returns to −1; blank lost (`absT` null again) | banner seen after the first one, and `diag.reset` is `BROWNOUT`, `POWERON` or not yet known | derived; `esp_reset_reason()` confirms it from inside |
| `BOARD_RESET` | the firmware restarted itself | boot banner reappears and `diag.reset` names a software cause: `SW`, `PANIC`, `TASK_WDT`, `INT_WDT` | any such reset outside a run | derived from `esp_reset_reason()` |
| `BOARD_RESET_MIDRUN` | any reset during a run | as above while `t ≥ 0` was live | | derived |
| `STREAM_STALE` | board hung, cable out, or port lost | no line for > 3 s | normal period is 1.0 s; the longest healthy gap seen is 2.18 s | **seen** as the healthy bound |
| `LINE_GAP` | something blocked the loop | period > 1.5 s | the stirrer's start ramp causes one 2.2 s gap | **seen** |
| `RADIO_DOWN` | the board cannot get packets onto the air | `diag.radio.fail` climbing. The phone cannot see the far end: ESP-NOW broadcasts are unacknowledged, so a successful send only means the packet was queued. `diag.radio.heard` says when the face last talked back, and the face itself shows `link down` after 5 s without a `PeelPacket` | >= 20 failed sends | **seen** before the channel was pinned |
| `RADIO_DRIFT` | a radio left channel 1 | note `# radio had drifted to channel N, pulled back` | any occurrence | detector is in both firmwares; has not fired since |
| `FALSE_START` | auto t = 0 fired with no tablet | `# t = 0 detected` immediately after a swept line | guarded in firmware: swept lines neither trigger nor seed the detector | **seen**, fixed; `session_full_cycle` shows 26 s and two sweeps after a blank with no trigger |
| `WRONG_FIRMWARE` | a different sketch is on the board | no `# 17_stream ready` banner; lines are not JSON (`18_selftest` prints `trans  144 mV   scat  121 mV   tC 23.81`) | banner missing within 5 s of connect | **seen**: `selftest_*.log` |

## Two that matter most for a live demo
**Motor coupling** corrupts the very numbers being measured and looks like a real signal. It is the
reason the motor gets its own supply (`POWER.md`).
**Brownout** looks like the app losing its blank and its run for no reason. The tell is the boot
banner arriving in the middle of a session.
