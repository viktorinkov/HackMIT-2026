# Peel Rive animation plan

Proposed motion specification, based on the live [Figma scan and device section](https://www.figma.com/design/lPyn5YG33z3lPlWiaKjsK9/Peel-Figma?node-id=41-615) and the repository's current vision schemas. This is a build plan; no Rive file or runtime integration has been created.

Scope: bottle, imprint, device connecting/ready/checking, scan completion, and the newly visible [Starting Research screen](https://www.figma.com/design/lPyn5YG33z3lPlWiaKjsK9/Peel-Figma?node-id=186-1285). Onboarding and results animations are outside this plan. The research frame's current name and visible heading are both “Starting Research.”

Use one continuous visual story: bottle → observed pill → orange device → whole orange → research. Retain the warm background, orange accents, and dark brown outlines. The scan slots are 364 × 416 in the 412-wide Figma screens. Keep headings, actions, and step labels in native Flutter UI.

All timings below are starting values for prototyping. The app determines when work is complete; animation time never determines backend progress.

## Motion descriptions

| Stage | Entrance and action | Continuous waiting loop | Transition forward |
| --- | --- | --- | --- |
| Bottle | Over about 700 ms, a bottle slides in from the left and a phone from the right. The bottle turns slightly until its label faces the phone. Four camera brackets move inward around the label. | A 4-second loop: brackets gently approach and return while the phone makes a small positioning adjustment. Keep the bottle readable. Show capture once after an actual photo submission: brackets contract and reopen, without a flash. | After the bottle step is accepted, the cap lifts and a single illustrative pill moves out of the bottle. The bottle and cap leave left; the phone remains to frame the pill. |
| Imprint | Over about 650 ms, the pill moves to the center and enlarges. The phone's framing area contracts to the pill. Begin with a clearly illustrative neutral pill because its appearance is not known yet. | A 4-second loop: a narrow scan line travels down and back across the stationary pill, clipped inside the phone's scan window. Small bracket movement keeps the scene alive without making the imprint hard to read. | When a valid imprint response arrives, reshape the pill once to the observed silhouette, apply its observed color approximation, and reveal any legible imprint through a moving mask. Keep that same appearance through the rest of this scan. The phone exits right and the device rises from below. |
| Device connecting | The orange half-sphere moves up beneath the pill. Its liquid surface has a gentle curve; a connector extends toward the phone before the phone leaves. | A 5-second loop: one small connector segment travels along the connection path while the liquid slowly changes curvature. Keep the pill above the vessel. | Only a real connection event—or an explicitly indicated demo state—aligns and joins the connector. Move to the ready pose. |
| Device ready | Maintain the same vessel and personalized pill. The surface continues its gentle movement. | The pill stays poised above the opening; do not repeatedly drop and recover it. | On “Check pill,” lower the pill into the liquid over about 650 ms. Two ripple paths expand and retract. This placement runs once. The Figma placement cue is deferred to this action so it does not imply measurement started merely because connection succeeded. |
| Checking pill | Keep the pill recognizable inside a stylized cutaway. Slight movement of the liquid suggests analysis. | A 6-second loop: the liquid surface deforms gently, and three small colored segments travel around the device rim at steady brightness. Keep the vessel still and the pill's observed colors unchanged. This replaces the Figma note's RGB flashing. | When the measurement ends, bring the segments into the rim, flatten the liquid curve, and lower the upper shell to close the sphere. |
| Scan complete | Over about 600 ms, the shell closes into a whole orange. The seam reshapes into a peel contour; a small leaf unfolds. | If a brief wait is needed, use a slow 5-second leaf bend. Completion is an event, so do not repeatedly reopen and close the device. | The same orange rolls toward the research scene. Completion means the scan step ended, not that the pill is safe or authentic. |
| Search / Starting Research | Continue the orange's rolling movement as simple connected document outlines enter from the right. This interprets the Figma note about oranges rolling across the web. | A seamless 6-second loop: a small orange rolls along connected paths, passes behind a document, then continues to the next. Reuse a small set of document illustrations, recycling them only outside the clipped stage. Avoid a moving full-screen background. | When useful results arrive, offer access immediately. On leaving this scene, documents slide left and the orange rolls right. Do not make the user watch another loop before seeing results. |

The liquid and orange vessel follow the Figma metaphor; their movement is illustrative, not a rendering of measured spectra or a replacement for hardware operating instructions. The current `/pill` endpoint returns mock spectrometry. The host UI must distinguish demo activity from a physical measurement.

## Continuity without fades

- Use one persistent Rive artboard/controller across these stages so the phone, pill, and orange retain their positions and identity.
- Give each waiting loop matching positions, shape vertices, and velocities at its beginning and end. Rolling uses linear timing; directional reversals use gentle easing.
- Use roughly 300–650 ms for stage bridges. Continue from the current pose; do not restart the source loop before leaving it. Validate exits at several points in each loop.
- Hold opacity constant. Use movement, clipping, path deformation, path trimming, and physical occlusion for entrances and exits. Do not substitute animated blur, brightness pulses, or alpha-based state changes for fades.
- Recolor once when new scan data arrives. Reveal changed fills with a moving clipped region if the update needs animation; do not cycle through possible pill colors.
- Allow Back, Cancel, errors, and reduced-motion changes to interrupt immediately. When an offstage object must reset, reset only after it is fully outside the clip.
- Pause rendering when the app is backgrounded or the animation is offscreen. Resume at the latest application state without replaying completed capture or placement actions.

## What the vision model actually returns

The [imprint schema](../../backend/src/backend/photo_identification/imprint.py) returns `result.is_pill`, nullable strings `imprint`, `color`, `shape`, `form`, `score`, `additional_markings`, and `notes`, plus a single `confidence` between 0 and 1. Confidence describes readability, not drug identity. The [vision client](../../backend/src/backend/photo_identification/vision.py) currently uses GPT-4o structured output and returns the observation after the photo request completes.

It does not return RGB/hex colors, dimensions, a segmentation mask, a 3D model, per-feature confidence, or a verified reverse-side imprint. The [bottle schema](../../backend/src/backend/photo_identification/bottle.py) describes label contents, not the container's geometry or color. Therefore the bottle stays a generic illustration and the pill becomes an approximation only after the imprint response.

| Observation | Proposed visual mapping |
| --- | --- |
| `shape` | Normalize recognized terms into authored round, oval, oblong, capsule-like, triangular, and rounded-polygon silhouettes. Unsupported or ambiguous descriptions keep a neutral illustrative silhouette; preserve the original wording in native text. |
| `form` | Add a capsule join only when capsule form is observed. An oblong tablet does not automatically receive a capsule seam. |
| `color` | Map recognized color names to an authored palette. Use one fill for a single color. Use two regions only when the wording describes a split pattern clearly. “Blue and white” alone does not establish which end is which or whether the pattern is split or speckled. |
| `imprint` | Bind the observed string exactly, preserving case, spaces, and punctuation. Use one visible face; do not manufacture characters or mirror the text during rotation. If too long to fit readably, omit it from the tiny illustration and show the full text outside it. |
| `score` | Show an authored score line only for a recognized description. Keep scoring separate from a capsule join. |
| `additional_markings` | Render only supported, unambiguous markings. Preserve other descriptions as text rather than generating an invented logo. |
| Missing data / low readability | Leave uncertain features unspecified and offer retake. Do not choose an arbitrary confidence threshold without testing real scans. Never infer pill appearance from the bottle's expected drug. |
| `is_pill = false` | Leave the instruction illustration generic and show the failed-capture state. Do not continue as though a pill was observed. |

For example, a response describing a pink round tablet produces a pink round tablet throughout device checking. It should never revert to the orange-and-white capsule used as a brand illustration. Keep observed appearance separate from brand colors and result-status colors.

For a first build, normalize existing strings in the app with explicit lookup rules and an unknown fallback. A later schema extension could add controlled shape/color categories, color-pattern information, and per-feature uncertainty; those are proposed additions, not available fields today.

## Rive construction and application contract

Create `peel_scan.riv` with a primary `ScanFlow` artboard sized 364 × 416 and reusable bottle, phone, pill, device, orange, and document groups or nested artboards. Use an explicit `ScanFlow` state machine with stage-specific idle loops and short transition animations. Rive supports [view-model-driven transitions](https://rive.app/docs/editor/state-machine/transitions) and Flutter binding of strings, colors, enums, booleans, and numbers through [data binding](https://rive.app/docs/runtimes/flutter/data-binding).

Author the pill as a shared outline with a consistent vertex count and ordering across supported silhouette poses. Move the same vertices and handles to produce the shape morph; Rive supports editing them in [Animate mode](https://rive.app/docs/editor/fundamentals/edit-vertices). Clip color regions and surface markings to that outline. Avoid attempting to import arbitrary model-generated paths at runtime. Unsupported topology uses the generic fallback, or an authored variant exchanged behind the phone's occlusion.

Proposed view model properties, created by the app adapter rather than assumed to be raw API fields:

| Property | Type and purpose |
| --- | --- |
| `stage` | Enum: bottle, imprint, connecting, ready, checking, scanComplete, research, error. |
| `pillShape`, `pillForm`, `colorPattern`, `scorePattern` | Enums selecting supported authored geometry and features. |
| `pillColorA`, `pillColorB` | Color values derived from recognized descriptions. Same values remain bound throughout the scan. |
| `imprintText` | String containing only the observed imprint. |
| `appearanceKnown`, `showImprint` | Booleans controlling supported detail; visibility changes use clipping/occlusion, not fades. |
| `captureSubmitted`, `placePill` | One-shot triggers sent only for actual corresponding user actions. |
| `reduceMotion`, `motionPaused` | Booleans selecting stable poses and disabling decorative loops. |
| `researchState` | Enum reflecting pending, partial, complete, or error. |

Keep backend requests, navigation, connection status, and scan-session identity in Flutter. Apply the latest valid response for the active scan only; ignore cancelled or superseded requests. Commit appearance fields together before advancing the animation so users never see a new shape with the previous scan's imprint.

Keep geometry morph timelines separate from looping position/rotation timelines so the idle loop cannot overwrite the chosen silhouette. Bind fills to data, rather than keyframing prototype colors into each timeline. Prototype one round pink tablet and one two-tone capsule in the actual target Flutter runtime before authoring the remaining variants.

Research already has `pending → partial → complete` and `error` states. A partial report should become accessible while research continues. Revision numbers are update counters, not percentages. The local README also documents runs remaining partial after a backend restart: add a host-side stale/timeout state with retry access instead of letting the loop conceal stalled work. Neither the animation nor an elapsed timer may fabricate a completed result.

## Accessibility and acceptance

- Respect Flutter's [disableAnimations setting](https://api.flutter.dev/flutter/widgets/MediaQuery/disableAnimationsOf.html). Select an informative static pose for each stage and update it directly when the stage changes. Reduced motion disables rolling, swirling, repeated scanning, and large morphs; no fade replacement is needed.
- Provide a native “Pause animation” control for continuous decorative movement. Pausing must not stop scanning, research, status updates, or access to results. This follows the intent of [WCAG Pause, Stop, Hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html).
- Expose native text for the current instruction and status. Exclude decorative Rive children from screen-reader traversal. Announce meaningful stage changes once, never each loop; keep keyboard and screen-reader focus on stable controls.
- Preserve observed pill colors. Add a contrasting outline or backing rather than changing a white or pale-yellow pill into a different color for visibility. Target [3:1 for meaningful graphic boundaries](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) and [4.5:1 for ordinary text](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
- Use labels and structural changes alongside colors. Connected means the connector joins and the native text says ready; color alone never communicates it. Use no flashing capture effect or RGB flashing.
- Keep critical instructions available with motion paused, text enlarged, or the canvas unavailable. Provide a native static fallback if the Rive asset fails to load.
- Validate loops and mid-loop exits, white/yellow/black and two-color pills, all supported shapes, null and unexpected strings, long imprints, non-pill photos, delayed and out-of-order responses, Back/Cancel, connection loss, partial results, errors, and reduced-motion changes during playback. Verify on the chosen Flutter runtime and a physical device; none of those implementation checks has been run for this planning document.

Build order: prototype the continuous bottle-to-imprint transition and data-bound pill; add the device states; carry the orange into research; add static poses and pause behavior; then validate the full state and appearance matrix.
