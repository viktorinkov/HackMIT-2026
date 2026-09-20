# Peel Rive prototype

Editable project: [Peel — Scan Flow](https://editor.rive.app/file/peel--scan-flow/2597304).

Visual specification: [peel-rive-review.md](../../docs/design/peel-rive-review.md).

## Implemented in Rive desktop

- `ScanFlow` artboard: 364 × 416, clipping enabled, transparent background. The app supplies the background color.
- Editable bottle, cap, phone, miniature bottle, framing brackets, and scan line, using the specified illustration palette.
- Four-second looping `BottleIdle` timeline. The phone moves 4 px toward the bottle and returns; the scan line travels 20 px down the miniature label and returns; the brackets contract about 3 px and release.
- Cubic easing `(0.42, 0, 0.58, 1)` and matching endpoint poses. No opacity animation.
- Default `ScanFlow` state machine enters `BottleIdle`.

`peel_bottle_prototype.riv` is the runtime export. `source/peel-bottle.svg` is the editable vector artwork source, without a background rectangle. `bottle-checkpoint.jpeg` shows the desktop checkpoint.

The Rive project retains the imported Background shape with its fill at a constant 0%; the artboard fill is also 0%. Illustration objects remain opaque. Transparency follows the user's correction to the original cream-background specification.

## Video previews

- [MP4 preview](peel-bottle-loop.mp4): white background for broad playback compatibility.
- [Transparent WebM](peel-bottle-loop.webm): VP9 with alpha; use a player that supports transparent WebM.

Both videos contain two complete four-second loops at 30 fps, rendered at 728 × 832 from the exported `.riv` with the official `@rive-app/canvas-advanced` runtime (2.42.2). The preview background is not part of the Rive animation.

## Timing

Offsets below are relative to each object's design pose:

| Time | Phone X offset | ScanLine Y offset | Bracket scale X / Y |
| --- | --- | --- | --- |
| 0 s | 0 px | 0 px | 100% / 100% |
| 1 s | −4 px | 0 px | 89% / 93.4% |
| 2 s | −4 px | 20 px | Held |
| 3 s | 0 px | 0 px | 89% / 93.4% |
| 4 s | 0 px | 0 px | 100% / 100% |

## Validation and remaining work

The native Rive hierarchy, dimensions, timeline keys, easing, loop playback, default state connection, and transparency checkerboard were inspected in the desktop editor. The exported file has a RIVE header and contains the `ScanFlow` and `BottleIdle` names. The exported animation was also rendered with the official Rive web runtime: its 0 s and 4 s frames match exactly, both recorded cycles match, and transparent pixels survive WebM encoding and decoding. Both videos were checked for their eight-second duration, dimensions, and frame rate. Flutter/device playback has not been tested; this repository currently contains no Flutter application.

This is the first scene's idle prototype. Still pending: the one-shot entrance, bottle-to-pill handoff, the remaining six scenes, pill appearance binding, reduced-motion/pause controls, and application integration. A still design pose is available, but no dedicated reduced-motion state has been authored.

Rive's current account UI marks editable backup export as requiring an upgrade. Runtime export is available; its dialog says removing the Rive splash screen requires a paid workspace. Continue editing in the linked Rive project; the `.riv` is the runtime artifact, not an editable backup.
