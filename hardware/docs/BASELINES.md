# Measured electrical baselines

Measured on this build on 2026-09-19. Each figure names the capture it came from in `data/`.
Bench condition throughout: parts loose on the table, room lit by LED fixtures, USB power.

## ADC
| quantity | value | source |
|---|---|---|
| dark floor, TEMT6000 covered or face down | **91–150 mV** (not zero: ESP32-S3 ADC offset at 11 dB) | `selftest_lockin_100ms.log`, `light_response.csv` |
| lowest reading ever seen on a live sensor | 21 mV (`scat`), 0 mV on swept lines only | `session_full_cycle.csv` |
| shaded bench | 140–160 mV | `light_response.csv` |
| room light, sensor facing up | 300–830 mV | `light_response.csv` |
| under a desk lamp | 1140–1280 mV | `light_response.csv` |
| full scale | ~3100 mV | ADC, 11 dB attenuation, 12 bit |
| resolution as reported | 1 mV | `analogReadMilliVolts()` |

## Noise and averaging
| window | behaviour | source |
|---|---|---|
| 24 samples over ~12 ms (`18_selftest`'s first build; `17_stream` uses 24 over ~6 ms) | shorter than one 8.3 ms ripple cycle or barely longer, so it aliases 120 Hz lighting: ±100 mV slow wander, period ~8 s, with nothing changing | `selftest_short_window.log` |
| 250 samples ≈ 100 ms | 38–51 mV peak-to-peak over 1.2 s on a still sensor | `selftest_lockin_100ms.log` |
| lock-in, 6 on/off pairs at 100 ms | residual within **±4 mV** with no optical path; +30 mV or more when an LED faces the sensor | `selftest_lockin_100ms.log` |

## LEDs: forward-drop node voltage at ~70 µA
| LED | mV |
|---|---|
| IR 940 | 246 |
| red | 547 |
| yellow | 624 |
| green | 1208 |
| blue | 1510 |
| violet | 1763 |

Monotonic in photon energy. Open or reversed ≈ 3300 mV; shorted < 50 mV. Source `diode_check.csv`.

## Sweep lines
On the line where a sweep ran (`swept: true`), `trans` reads **0–218 mV (mean 66)** against a
332 mV unswept mean, and `scat` reads **197–386 mV (mean 258)** against 54. Seven of seven sweeps.
Source `session_full_cycle.csv`.

## Stirrer on
`17_stream`, 100 % PWM at 20 kHz, TT motor on the USB 5 V rail: `scat` rises from a 54 mV mean to
**166–312 mV**, `trans` from 332 to **385–599 mV**, and both become erratic second to second.
Source `session_full_cycle.csv`, 52–58 s.
A small DC motor driven fully on, same rail: **both channels +2000 mV**, 300 → 2400 mV, steady for
as long as it ran, and straight back when it stopped. Source `motor_coupling_dc.csv`.

## Temperature
| condition | behaviour | source |
|---|---|---|
| radio off (`18_selftest`) | smooth, consecutive readings within 0.06–0.13 °C | `light_response.csv` |
| radio on (`17_stream`) | consecutive readings differ by up to ±1.5 °C, sd 0.52 °C | `session_full_cycle.csv` |

## Timing
| quantity | value |
|---|---|
| report period | mean 1.016 s, min 0.91 s |
| longest gap | 2.18 s, during the stirrer's start ramp (250 ms kick, then 40→100 % in 5 % steps) |
| sweep | every 10 s; 12 ms settle per colour |
| DS18B20 conversion | 750 ms at 12 bit, requested one report ahead |
| boot to first line | ~2 s |

## Radio
| quantity | value | source |
|---|---|---|
| packets lost at bench range | about 1 in 10 | `espnow_link_test.log` |
| packet age at the receiver | 27–190 ms typical, up to ~1.2 s after a loss | `box3_face_heartbeat.log` |
| face frame rate with the link up | 20 fps | `box3_face_heartbeat.log` |
