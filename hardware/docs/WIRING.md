# Wiring, hole by hole

Two 170-point mini breadboards snapped side by side. **Board A is yellow, Board B is white.**
Each has rows 1–17 and columns `a b c d e | channel | f g h i j`. A mini board has no power
rails: only the five holes of one row on one side of the channel are connected.

## Board A: the XIAO

The XIAO sits in **d1–d7** and **h1–h7**, USB-C hanging off the row 1 edge, components up. Its
body covers columns e, f and g in rows 1–7, so those holes are unreachable. That leaves, per row:

| row | left group (a b c) | right group (i j) |
|---|---|---|
| 1 | D0 | 5V |
| 2 | D1 | GND |
| 3 | D2 | 3V3 |
| 4 | D3 | D10 |
| 5 | D4 | D9 |
| 6 | D5 | D8 |
| 7 | D6 | D7 |

| Board A hole | goes to | carries |
|---|---|---|
| a1 | B a8 | D0 → IR LED |
| a2 | B a9 | D1 → violet LED |
| a3 | B a4 | D2 → red LED |
| a4 | B a5 | D3 → yellow LED |
| a5 | B a6 | D4 → green LED |
| a6 | B a7 | D5 → blue LED |
| i3 — i6 | 5.1 kΩ resistor | DS18B20 pull-up, 3V3 to D8 |
| i2 | green + blue LED cathodes (twisted, one wire) | GND |
| i4 | scatter TEMT6000 SIG | D10 |
| i5 | transmission TEMT6000 SIG | D9 |
| j6 | DS18B20 yellow | D8 |
| j1 | B b16 | 5 V to the motor rail. **Remove when the power bank feeds the motor** (`POWER.md`) |
| j2 | B f1 | GND to Board B |
| j3 | B a1 | 3V3 to Board B |
| j7 | B a14 | D7 → stirrer driver |

## Board B: everything else

**Rails, made from rows**
| holes | net | what is in them |
|---|---|---|
| row 1 left, a1–e1 | **3V3** | a1 from A j3 · b1 transmission VCC · c1 scatter VCC · d1 DS18B20 red |
| row 1 right, f1–j1 | **GND** | f1 from A j2 · g1 transmission GND · h1 scatter GND · i1 DS18B20 black · j1 jumper to j2 |
| row 2 right, f2–j2 | **GND** | f2 red + yellow cathodes · g2 from a10 · h2 from a17 · i2 IR LED cathode · j2 from j1 |
| row 10 left, a10–e10 | **GND** (emitter) | a10 jumper to g2 · c10 emitter · d10 violet LED cathode · b10 power bank minus |

**LED drivers.** One row each: signal in at column a, series resistor across the channel from d to
g, LED anode (long leg) at column j.
| row | LED | resistor d → g | anode |
|---|---|---|---|
| 4 | red | 220 Ω | j4 |
| 5 | yellow | 220 Ω | j5 |
| 6 | green | 220 Ω | j6 |
| 7 | blue | 220 Ω | j7 |
| 8 | IR 940 | 100 Ω | j8 |
| 9 | violet | 100 Ω | j9 |

Cathodes (short legs): red + yellow → B f2 · green + blue → A i2 · IR → B i2 · violet → B d10.

**Stirrer driver**, rows 10–17, left side
| hole | part |
|---|---|
| c10 / c11 / c12 | 2N2222A emitter / base / collector, flat face toward Board A |
| b11 — b14 | 1 kΩ, base to the D7 signal row |
| a14 | D7 in, from A j7 |
| d12 — d16 | 1N4007, band at d16 |
| a12 | motor − |
| a16 | motor + |
| b16 | +5 V in (from A j1, or the power bank's plus) |
| e16 / e17 | 100 µF, plus at e16, minus at e17 |
| a17 | jumper to h2 (GND) |

```
        +5 V (row 16) ──┬─────────┬──────────┐
                     motor     1N4007     100 µF
                        │      (band up)     │
   collector (row 12) ──┴─────────┘          │
   D7 ── 1 kΩ ── base (row 11)               │
   emitter (row 10) ── GND ──────────────────┘
```

Off-board parts are on 20 cm female-to-male jumpers so they reach the carrier, the shelf and the
lid once the boards sit on the enclosure floor.
