# Enclosure ("the orange")

A 150 mm sphere that unscrews just above the equator. Heights are **z, in mm from the sphere's
centre**. 0° is the screen face, 180° the cable window, 270° the alignment line.

## Shell
| | |
|---|---|
| outside radius / wall | 75 / 1.8 |
| flat base | z = −50 (inner floor −48.2); sits on a 112 mm footprint |
| seam, where the lid unscrews | z = +51 |
| thread | 3-start trapezoidal, 4 mm pitch, 2 mm deep, z 41–51, 0.4 mm clearance on diameter |
| top opening | **100 mm**: everything inside has to pass through it |
| flat top | z = 64–65.8, with an 18 mm drop port for the tablet and a 6.6 mm hole for the probe at (0, −15.5) |
| screen face | flat cut at x = +60, 92 mm across; 2 mm bezel; window 53 × 41 over a 49 × 36.7 screen |
| BOX-3 pocket | 66.9 × 62.0 × 17.6 deep, entered from inside; 45° shelf under it |
| BOX-3 USB-C port | 12 × 18 obround through the shell at −y, centred 7.6 mm behind the unit's face |
| cable window | 32 × 14 at 180°, centred y = −15, z = −33, on the XIAO's USB-C |

## Stack, bottom to top
| z | what |
|---|---|
| −48.2 | floor; corral 49 × 72 locating the snapped breadboards, row 1 toward the cable window |
| −38.2 | top of the breadboards |
| −32.9 | XIAO USB-C centre |
| −20.5 … −18.5 | shelf plate, 96 mm, D-cut at x = 39.5, on four floor posts at (−15, ±40) and (18, ±38) |
| −18.5 … 0.3 | TT motor on its side, lower shaft snipped to a 2 mm stub in the centre hole, can toward 180° |
| 1.4 … 9.4 | magnet hub on the upper shaft |
| 10.9 … 12.9 | optics floor, 2 mm, on three posts standing on the shelf plate |
| 12.9 | vial floor; liquid floor at 14.4 |
| **26.4** | **optical axis** |
| 38.6 | 32 mL fill line |
| 48.9 | vial rim |

## Optics
| | |
|---|---|
| vial | 46 mm OD, 41 mm ID, 36 tall, 0.8 mm windows at 0°, 90°, 180° |
| carrier | 76 mm OD ring with four pillars; 8 mm apertures on the optical axis |
| stations | **LEDs at 0°** (all six share one aperture), **scatter sensor at 90°**, **transmission sensor at 180°**; a light baffle at 45° between the LEDs and the scatter sensor |
| magnet gap | 5.0 mm from magnet top to liquid floor (must stay 3–6) |
| stir bar | clears the beam by 2.0 mm; liquid surface 8.2 mm above it |

Which sensor goes where is fixed by wiring: the TEMT6000 whose SIG is in **A i5** (D9) is the
transmission sensor and goes at 180°; the one in **A i4** (D10) is scatter and goes at 90°.
