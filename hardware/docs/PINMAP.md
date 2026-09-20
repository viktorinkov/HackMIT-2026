# Pin map

## XIAO ESP32-S3
| function | XIAO pin | GPIO | ADC | direction | notes |
|---|---|---|---|---|---|
| IR 940 LED | D0 | 1 | ADC1_CH0 | out | 100 Ω in series |
| violet LED | D1 | 2 | ADC1_CH1 | out | 100 Ω |
| red LED | D2 | 3 | ADC1_CH2 | out | 220 Ω |
| yellow LED | D3 | 4 | ADC1_CH3 | out | 220 Ω |
| green LED | D4 | 5 | ADC1_CH4 | out | 220 Ω, fast channel |
| blue LED | D5 | 6 | ADC1_CH5 | out | 220 Ω |
| free | D6 | 43 | – | – | UART0 TX; emits ROM boot text at reset |
| stirrer PWM | D7 | 44 | – | out | 20 kHz, to the 2N2222A base through 1 kΩ |
| DS18B20 data | D8 | 7 | ADC1_CH6 | in/out | OneWire, 5.1 kΩ pull-up to 3V3 |
| transmission sensor | D9 | 8 | ADC1_CH7 | in | TEMT6000 SIG, at 180° to the LEDs |
| scatter sensor | D10 | 9 | ADC1_CH8 | in | TEMT6000 SIG, at 90° |
| 5V | 5V | – | – | power | USB VBUS |
| 3V3 | 3V3 | – | – | power | regulator output, feeds both sensors and the probe |
| GND | GND | – | – | power | |

Every LED pin is an ADC1 channel, which is what makes the diode check possible (`BASELINES.md`).
Both sensors are on ADC1: ADC2 is unusable while the radio is on. No ADC-capable pin is free.
On-board: user LED on GPIO21 (active low), used as a per-report heartbeat.

## ESP32-S3-BOX-3
| function | GPIO | notes |
|---|---|---|
| LCD DC | 4 | |
| LCD CS | 5 | |
| LCD MOSI | 6 | |
| LCD SCK | 7 | |
| LCD reset | 48 | **active HIGH**, shared with the touch reset. See `BOX3.md` |
| LCD backlight | 47 | PWM-dimmable, high = on |
| I2C SDA / SCL | 8 / 18 | touch controller, codec control |
| touch interrupt | 3 | |
| I2S MCLK / BCLK / LRCK | 2 / 17 / 45 | |
| I2S DOUT (to ES8311) | 15 | speaker path |
| I2S DIN (from ES7210) | 16 | microphones |
| amplifier enable | 46 | high = on |
| mute button | 1 | active low, used as the face's single control |
| boot button | 0 | |
| dock I2C SCL / SDA | 40 / 41 | unused |
