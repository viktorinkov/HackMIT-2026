# Peel Rive flow

Editable project: [Peel — Scan Flow](https://editor.rive.app/file/peel--scan-flow/2597304).

Authoritative plan: [peel-rive-animation-plan.md](../../docs/design/peel-rive-animation-plan.md).

## View the complete flow in Rive desktop

Select the `PeelScan` artboard, switch to **Animate**, select **State Machine 1**, and click the small play button immediately beside its tab above the state-machine graph. Enable **Preview Bound Values** in the Data panel if needed.

**Automatic demo:** while playback runs, check **Data → ViewModel2 → demoMode**. The complete flow advances automatically and repeats every 52 seconds, including research and its exit. No manual stage switching is needed. The demo toggle defaults to false and does not overwrite the host’s `stage` input.

**App-controlled playback:** leave `demoMode` unchecked. Change **Data → ViewModel2 → stage** and press Enter to advance manually. Each stage holds its idle loop until this value changes.

| stage | Scene |
| --- | --- |
| 0 | Bottle scanning |
| 1 | Pill imprint scanning |
| 2 | Device connecting; pill above device |
| 3 | Pill falls in and becomes fully hidden beneath the water |
| 4 | Water circulates; pill stays hidden and RGB lights stay fixed |
| 5 | Scan complete; device closes into orange |
| 6 | Research loop |
| 7 | Research exits and clears |

Use `PeelScan`, not the older `ScanFlow` or `FullFlowPreview` artboards. The top toolbar's global Play button currently opens the older default artboard; use the state-machine play button described above.

## Current editor contract

- Artboard: `PeelScan`, 364 × 416 (7:8), transparent background, clipping enabled.
- State machine: `State Machine 1`.
- View model: `ViewModel2`; default instance: `Instance`.
- Bound Number property: `stage`, default 0.
- Bound Boolean property: `demoMode`, default false; enable only for automatic demos.
- Script node: `PeelFlow`; script asset: `Node Script 1`.
- Script source: [PeelFlow.luau](source/PeelFlow.luau).

The script also exposes `reduceMotion`, `motionPaused`, `pillShape`, `pillForm`, `pillColorA`, `pillColorB`, `twoTone`, and `imprintText`. These are script properties in the editor; their host view-model bindings remain to be wired. Do not treat them as verified runtime view-model properties yet. An unused auto-generated `generatedNumber 1` property remains and produces an identifier warning.

## Validation and handoff status

The complete sequence 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 was exercised in native Rive desktop through the live bound `stage` control. The automatic demo was also observed advancing through placement and research, clearing, and restarting at the bottle after 52 seconds. The corrected device was checked natively at stages 2, 3, and 4: the pill falls into the water and disappears completely; two water curves circulate while all three RGB lights keep their positions. Automatic demo playback was left running. The checkerboard confirms transparent artboard background. This validates the editor preview, not an exported runtime file or application integration.

The latest source compiles with Luau. The demo sequence, repeat, pause, and preservation of the host stage input also pass the local harness. A local API-shim harness additionally checked indefinite stage holds, research exit continuity at several phases, pause behavior, reduced-motion draws, pill appearance continuity, finite geometry, and balanced renderer save/restore calls. Those shim checks do not replace native runtime validation.

A new full-flow `.riv` has not been exported. The user will export it manually from Rive. Remaining work for the Devin runtime handoff: bind the remaining script properties, clean the unused generated property, export the correct artboard, and verify the exported file in the target application runtime. Visual polish against every detail of the plan also remains.

## Earlier bottle-only artifacts

`peel_bottle_prototype.riv`, `peel-bottle-loop.mp4`, `peel-bottle-loop.webm`, and `bottle-checkpoint.jpeg` are the earlier bottle-only prototype. They do **not** contain the complete flow. The videos are eight-second previews of two four-second bottle loops rendered from that earlier export.
