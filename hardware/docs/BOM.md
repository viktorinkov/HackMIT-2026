# Bill of materials

## Controllers
| part | detail |
|---|---|
| Seeed Studio XIAO ESP32-S3 | ESP32-S3, 8 MB flash, 8 MB PSRAM, headers soldered, USB-C. Native USB-Serial/JTAG, VID `0x303A`. MAC `68:EE:8F:50:27:E8` |
| Espressif ESP32-S3-BOX-3 | main unit only. Module ESP32-S3-WROOM-1-N16R16V (16 MB flash, 16 MB octal PSRAM). 2.4" 320×240 SPI LCD, capacitive touch, speaker, two mics, USB-C on the left side. 66.1 × 61.2 × 17.6 mm. MAC `80:45:6B:64:89:18` |

## Sensors
| part | qty | detail |
|---|---|---|
| TEMT6000 ambient light sensor breakout | 2 | phototransistor with daylight filter, peak ~570 nm, 10 kΩ load on the board, 3 pins VCC / GND / SIG, run at 3.3 V |
| DS18B20 waterproof probe | 1 | stainless 6 × 50 mm, 1 m cable, red = VCC, black = GND, yellow = data. ROM address `28B3872100000025` |

## Light sources, all 5 mm through-hole
| colour | nominal wavelength | series resistor | note |
|---|---|---|---|
| red | ~625 nm | 220 Ω | |
| yellow | ~590 nm | 220 Ω | |
| green | ~525 nm | 220 Ω | brightest on this rig; the always-on fast channel |
| blue | ~465 nm | 220 Ω | |
| violet ("bright purple") | ~400 nm | 100 Ω | Vf ≈ 3.2 V on a 3.3 V pin, so it runs dim |
| IR | 940 nm | 100 Ω | water-clear emitter from an emitter/receiver pair; invisible; emission unverified |

## Stirrer
| part | detail |
|---|---|
| TT gear motor | yellow, 70 × 22.5 × 18.8 mm body, dual 5.5 mm D-shaft, 3–6 V |
| 2N2222A NPN transistor | TO-92, E-B-C with the flat face toward Board A, low-side switch |
| 1 kΩ resistor | base resistor |
| 1N4007 diode | flyback, across the motor, band toward +5 V |
| 100 µF 50 V electrolytic | across the motor rail |
| Neodymium discs | 8 × 2 mm, two stacked per hub pocket; 6 × 2 mm, nine stacked as the stir bar (6 × 18 mm) |

## Passives and hardware
| part | qty | marking (5-band) |
|---|---|---|
| 220 Ω | 4 | red red black black brown |
| 100 Ω | 2 | brown black black black brown |
| 1 kΩ | 1 | brown black black brown brown |
| 5.1 kΩ | 1 | green brown black brown brown (DS18B20 pull-up) |
| 170-point mini breadboard | 2 | one yellow (Board A), one white (Board B), snapped side by side: 70 × 47 × 10 mm |
| Dupont jumpers | | 10 cm board to board, 20 cm female-to-male to the off-board parts |

## Host and power
| part | detail |
|---|---|
| Samsung Galaxy A16 (SM-A165M) | Android 15, USB-C, acts as USB host to the XIAO |
| USB-C to USB-C data cable | phone to XIAO |
| USB power bank | feeds the BOX-3 and the motor rail. See `POWER.md` |
