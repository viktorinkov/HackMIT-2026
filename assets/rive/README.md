# Peel Rive flow

Editable project: [Peel — Scan Flow](https://editor.rive.app/file/peel--scan-flow/2597304).

Authoritative plan: [peel-rive-animation-plan.md](../../docs/design/peel-rive-animation-plan.md).

## View the complete flow in Rive desktop

Select the `PeelScan` artboard, switch to **Animate**, select **State Machine 1**, and click the small play button immediately beside its tab above the state-machine graph. Enable **Preview Bound Values** in the Data panel if needed.

While playback runs, change **Data → ViewModel2 → stage** and press Enter. Advance through the values in order to see each connected transition. Each stage holds its idle loop until this value changes; there is no timed workflow progression.

| stage | Scene |
| --- | --- |
| 0 | Bottle scanning |
| 1 | Pill imprint scanning |
| 2 | Device connecting; pill above device |
| 3 | Pill placed in liquid |
| 4 | Device checking |
| 5 | Scan complete; device closes into orange |
| 6 | Research loop |
| 7 | Research exits and clears |

Use `PeelScan`, not the older `ScanFlow` or `FullFlowPreview` artboards. The top toolbar's global Play button currently opens the older default artboard; use the state-machine play button described above.

## Current editor contract

- Artboard: `PeelScan`, 364 × 416 (7:8), transparent background, clipping enabled.
- State machine: `State Machine 1`.
- View model: `ViewModel2`; default instance: `Instance`.
- Bound Number property: `stage`, default 0.
- Script node: `PeelFlow`; script asset: `Node Script 1`.
- Script source: [PeelFlow.luau](source/PeelFlow.luau).

The script also exposes `reduceMotion`, `motionPaused`, `pillShape`, `pillForm`, `pillColorA`, `pillColorB`, `twoTone`, and `imprintText`. These are script properties in the editor; their host view-model bindings remain to be wired. Do not treat them as verified runtime view-model properties yet. An unused auto-generated `generatedNumber 1` property remains and produces an identifier warning.

## Validation and handoff status

The complete sequence 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 was exercised in native Rive desktop through the live bound `stage` control. The research loop stayed active while held, and stage 7 cleared the scene. Playback was then returned to stage 0. The checkerboard confirms transparent artboard background. This validates the editor preview, not an exported runtime file or application integration.

The latest source compiles with Luau. A local API-shim harness additionally checked indefinite stage holds, research exit continuity at several phases, pause behavior, reduced-motion draws, pill appearance continuity, finite geometry, and balanced renderer save/restore calls. Those shim checks do not replace native runtime validation.

A new full-flow `.riv` has not been exported. The user will export it manually from Rive. Remaining work for the Devin runtime handoff: bind the remaining script properties, clean the unused generated property, export the correct artboard, and verify the exported file in the target application runtime. Visual polish against every detail of the plan also remains.

## Earlier bottle-only artifacts

`peel_bottle_prototype.riv`, `peel-bottle-loop.mp4`, `peel-bottle-loop.webm`, and `bottle-checkpoint.jpeg` are the earlier bottle-only prototype. They do **not** contain the complete flow. The videos are eight-second previews of two four-second bottle loops rendered from that earlier export.
