# Peel — final Rive animation plan

Replace the animation placeholders in the existing [Scan and device design](https://www.figma.com/design/lPyn5YG33z3lPlWiaKjsK9/Peel-Figma?node-id=41-615). The visual story is **bottle → pill → orange device → whole orange → research across the web**.

This document describes the proposed artwork and motion. The frame sizes and scene concepts come from Figma; object sizes, timing, and movement amounts below are proposed design values to refine in the animation preview. The existing page layout, headings, buttons, and step labels stay as designed.

## Visual direction

Use warm, simple vector illustrations with a little depth: rounded silhouettes, dark brown outlines, broad areas of flat color, and small solid highlights. Match the cream and orange colors already used in Figma. The pill can use any supported scan color; the orange device keeps its brand color.

The movement should feel calm, deliberate, and connected. Give each scene one main action. Secondary movement supports that action: a small phone adjustment, a slight liquid wave, or a gently bending leaf. Avoid shaking, rapid bouncing, elastic overshoot, glitter, and continuous whole-scene rotation.

Every animation uses a **364 × 416** artboard matching the existing placeholder, with a **7:8 aspect ratio (width:height)**. Scale proportionally when the display size changes. Keep the main artwork within a roughly 24 px inset, except when an object is entering or leaving. **Export the Rive artboard with a transparent background; the host app supplies the background color.** Keep the host background stable throughout the sequence. Clip moving objects at the placeholder edge so they never cross the screen heading, step labels, or buttons.

Outline strokes should read as approximately 2–3 px at the design size. Suggest depth with an offset edge or a solid highlight shape; the illustration should still look clear as a small graphic.

## Color definitions

All values below are six-digit **sRGB hex colors at 100% opacity**. Keep their opacity constant during animation. Use movement and solid color regions for highlights, depth, and reveals.

### Scene palette — existing Figma colors

These values were read from the Figma variables and checked against the scan placeholders. Their assignments to the new illustration objects are specified here.

| Figma token | Hex | Use in the design |
| --- | --- | --- |
| `--peel-soft` | **#FFF0D9** | Small cream highlights; optional placeholder background supplied by the host app. |
| `--peel-canvas` | **#FFFCF7** | Existing page background outside the placeholder; bottle cap, bottle label, and device inner rim. |
| `--peel-surface` | **#FFFFFF** | Phone screen and research document fills. |
| `--peel-orange` | **#FF9F1C** | Bottle body, device shell, completed orange, and rolling research oranges. |
| `--peel-deep` | **#B94700** | Bottle side shading, orange lower edge, and peel marks. |
| `--peel-ink` | **#2B2118** | Main outlines, phone body, label marks, and dark imprint lettering. |
| `--peel-muted` | **#66584C** | Secondary illustration lines, cap grip lines, and document content marks. |
| `--peel-teal` | **#276B65** | Camera brackets, scan line, liquid wave lines, orange leaf, and research connection paths. |
| `--peel-tealSoft` | **#E5F3EF** | Liquid surface fill. |
| `--peel-line` | **#E6DCCF** | Existing subtle placeholder border and nonessential separators. |

The exported animation has **no opaque background**. The host app may use **#FFF0D9** for the placeholder and **#FFFCF7** for the surrounding page, or provide another background appropriate to its theme. Background transparency is a fixed export property, not an animated fade. Keep illustration fills opaque. Use Ink or Teal for meaningful object boundaries; the pale Line color is only a decorative divider.

### Color placement by object

| Object | Fill and detail colors |
| --- | --- |
| Bottle | Orange body; Deep side edge; Canvas cap and label; Ink outline and label marks. |
| Phone | Ink body; Surface screen; Teal brackets and scan line. Its miniature bottle or pill uses the same colors as the larger object. |
| Device | Orange shell; Deep lower edge; Canvas inner rim; Teal Soft liquid with Teal wave lines. |
| Whole orange | Orange skin; Deep peel marks; Soft highlight; Teal leaf; Ink stem and outline. |
| Research cards | Surface fill; Ink outline; Muted content marks; Teal connecting paths. |
| Pill | The scan palette below; no brand-color tint from the surrounding scene. |

The three stationary device lights use **red #C64B4B**, **green #6EA879**, and **blue #5C8FD6**. These are proposed illustration colors, not existing Figma tokens. Each segment stays fixed in the rim and keeps its assigned color and brightness; there is no RGB cycling, flashing, or orbiting. Motion comes from the water.

### Pill palette — proposed scan color matches

The vision response provides color names, not hex values. Use this authored palette to give those descriptions consistent visual matches. These colors are proposed additions to the animation specification, not colors sampled from a pill photo or existing Figma pill artwork.

| Recognized color | Pill fill | Optional imprint color |
| --- | --- | --- |
| White | **#FFFFFF** | **#2B2118** |
| Off-white / ivory / cream | **#F5F1E8** | **#2B2118** |
| Yellow | **#F2D65C** | **#2B2118** |
| Pink | **#E8A0B6** | **#2B2118** |
| Orange | **#E98B39** | **#2B2118** |
| Red | **#C64B4B** | **#FFFFFF** |
| Blue | **#5C8FD6** | **#2B2118** |
| Green | **#6EA879** | **#2B2118** |
| Purple | **#9A7DC2** | **#2B2118** |
| Brown | **#8D654B** | **#FFFFFF** |
| Black / near-black | **#35312F** | **#FFFFFF** |
| Missing or unsupported description | **#F5F1E8** | Blank by default; **#2B2118** if an imprint is available. |

Use **#2B2118** for the pill's outer outline. For a dark pill, add a narrow **#FFFFFF** inner edge so the silhouette and capsule join remain visible. Use the imprint color listed above for a capsule join on that fill. The listed imprint/fill pairs all exceed a calculated 4.5:1 contrast ratio.

For a clearly split two-color capsule, assign one palette color to each half. A single-color capsule uses the same fill on both halves. Keep the colors attached to those halves throughout the movement. Place the optional imprint within one half using that half's lettering color; leave it blank if it cannot fit legibly.

**Complete default:** an oval tablet filled with **#F5F1E8**, outlined in **#2B2118**, with no imprint. A recognized scan color changes the pill and its phone preview only; the bottle, orange device, and research scene retain their scene colors.

## 1. Bottle

**Visual idea:** a phone carefully frames a bottle label for a photo.

### Composition

Place the bottle slightly left of center and the phone to its right. The bottle is the larger object, approximately 110 px wide and 180 px tall. The phone is approximately 90 px wide and 160 px tall, with a small tilt toward the bottle.

Give the bottle an amber-orange body, a cream cap with a few broad grip lines, and a large cream label. The label contains three short dark lines of different lengths, suggesting text without inventing a medicine name. Keep the label facing the viewer.

Draw the phone as a simple rounded frame with a small camera detail. Its screen contains a simplified bottle silhouette and four camera brackets. The simplified bottle moves with the illustrated bottle so the framing feels connected.

### Entrance — approximately 0.8 seconds

| Time | Movement |
| --- | --- |
| 0.00–0.45 s | The bottle slides in from the left with a slight 6° tilt. It slows as it reaches its position. |
| 0.15–0.65 s | The phone slides in from the right. Its tilt settles toward the bottle. |
| 0.45–0.80 s | The bottle straightens. Camera brackets extend from the corners of the phone's scan area and frame the label. |

The objects settle without a bounce. All artwork is fully visible as it crosses into the frame; nothing fades in.

### Continuous loop — 4 seconds

| Time | Movement |
| --- | --- |
| 0.0–1.0 s | The phone shifts about 4 px toward the bottle. The camera brackets move inward by about 3 px. |
| 1.0–2.0 s | A narrow horizontal scan line moves down the miniature label inside the phone screen. The physical bottle stays steady. |
| 2.0–3.0 s | The line returns upward. The phone eases back to its original position. |
| 3.0–4.0 s | The brackets return to their starting spacing, ready for the next pass. |

There is no camera flash, repeated success checkmark, or blinking light. The scan line and framing movement carry the action.

### Handoff to imprint — approximately 0.9 seconds

The cap lifts a short distance. The bottle leans gently toward the center, and one pill travels out of its opening along a shallow curved path. As the pill approaches the center, the bottle and cap continue offscreen to the left.

The phone moves slightly right to make room. Its miniature bottle moves out of the scan window as the pill takes its place. The pill becomes the largest object in the next scene.

## 2. Imprint

**Visual idea:** the same phone now examines the pill closely.

### Composition

Make the pill the focal point, centered slightly above the vertical middle of the slot. An elongated pill is approximately 140 px wide and 70 px tall; a round tablet is approximately 100 px across. These are presentation sizes, not physical measurements.

Place the phone behind and to the right of the pill. Keep the pill face unobstructed. The phone's scan window frames a small copy of the same pill, using the same shape and colors.

Start with the default pill if the scan has not supplied its appearance. The optional imprint sits near the center of the visible face and stays upright enough to read.

### Arrival — approximately 0.6 seconds after the bottle handoff

The pill slows at the center and grows from its small bottle-exit size to its display size. It rotates no more than about 10° to present its face. The phone's scan brackets tighten around its miniature pill.

The enlargement should feel like bringing the pill closer to inspect it, without a camera zoom across the whole scene.

### Continuous loop — 4 seconds

| Time | Movement |
| --- | --- |
| 0.0–2.0 s | A thin scan line passes slowly from top to bottom across the large pill. It remains clipped to the pill silhouette. |
| 2.0–4.0 s | The line returns from bottom to top. The camera brackets gently expand back to their starting position. |

The pill itself stays nearly still. At most, give it a 2–3 px vertical drift that returns exactly to its starting position. Avoid spinning it over: the visible face and imprint should remain easy to follow.

### Matching the scan — approximately 0.45 seconds

When the scan supplies the appearance, the outline reshapes smoothly into the selected shape. A capsule join can draw across the surface as a short line; a tablet has a continuous face.

Use the next scan-line pass to reveal the new fill colors and optional imprint behind it. This is a moving reveal with a clear boundary, not an opacity fade. If the appearance is already known before this scene starts, show it immediately without replaying the change.

The selected appearance stays consistent throughout the remaining scenes. Do not keep morphing between different pills during the loop.

### Handoff to device — approximately 0.7 seconds

The phone slides offscreen to the right. The scan line travels beyond the pill and exits its clipped area. The pill moves slightly upward and becomes smaller, leaving room beneath it for the orange device.

Its shape, color split, and optional imprint remain the same during this movement.

## 3. Device connecting

**Visual idea:** the orange half-sphere arrives beneath the pill and gently comes to life.

### Composition

Place the open device in the lower half of the slot, about 230 px wide. Its silhouette resembles the bottom half of an orange. Show a broad elliptical opening so it reads as a vessel seen slightly from above.

The outer shell is orange with a darker lower edge. A pale inner rim separates the shell from the liquid. Use a light, muted teal liquid so it is distinct from the orange shell. Give the liquid a slightly curved surface rather than a perfectly flat line.

The pill sits above the center of the opening, approximately 70–90 px wide for an elongated pill. Leave a clear gap between it and the liquid.

### Entrance — approximately 0.75 seconds

The device rises from below the animation area. It slows into place beneath the pill, with the opening kept level. As the vessel settles, one shallow wave travels across the liquid and becomes the slower waiting movement.

Three short light segments are built into the rim. They have fixed positions, steady colors, and steady brightness. The water movement suggests activity.

### Continuous loop — 5 seconds

The surface rises a few pixels on one side while lowering on the other, then reverses. Use a wave height of roughly 3–4 px. The device shell remains still.

All three RGB light segments remain stationary in the rim. Two shallow circulating curves make the water swivel inside the fixed shell.

The pill moves only a couple of pixels vertically. It stays above the opening during this scene.

## 4. Device connected / pill placement

**Visual idea:** the pill moves into the liquid in one clear action, following the existing Figma placeholder.

### Placement — approximately 0.8 seconds

| Time | Movement |
| --- | --- |
| 0.00–0.15 s | The pill aligns with the center of the opening. Its visible face stays toward the viewer. |
| 0.15–0.45 s | The pill descends into the liquid along a short, gently accelerating path. |
| 0.45–0.65 s | A shallow depression forms in the surface. Two curved ripple lines spread outward. |
| 0.65–0.80 s | The pill sinks fully below the opaque surface and becomes completely hidden. The depression relaxes and the ripple lines move behind the rim. |

Keep the contact restrained: no splash outside the device, flying droplets, or large bounce. The pill stays intact and recognizable.

The opaque water physically covers the pill as it falls in. Once submerged, no part of the pill remains visible. Do not show a half-submerged pill or an orange core, and do not fade the pill's opacity.

### Continuous loop — 5 seconds

After placement, the liquid returns to its small wave movement. The pill remains fully hidden beneath the opaque surface. It does not jump out or fall in again each cycle.

As the design moves into Checking pill, increase the circulation of the surface curves smoothly while all rim lights stay fixed, while preserving the same composition.

## 5. Checking pill

**Visual idea:** the orange device quietly examines the same pill.

### Composition

Keep the vessel at the same position and scale as the placement scene. The pill stays completely hidden beneath the opaque water. Preserve its observed appearance internally; do not draw a pill-shaped core in the opening.

Add two broad curved lines on the liquid surface to suggest circulation. Keep these lines sparse; the scene should read clearly without small decorative particles.

### Continuous loop — 6 seconds

| Time | Movement |
| --- | --- |
| 0.0–1.5 s | The liquid curves bend gently toward the right. The pill remains hidden. |
| 1.5–3.0 s | The curves travel around the opening and pass behind the front rim. The RGB lights stay fixed in the rim. |
| 3.0–4.5 s | The liquid curves continue their circulation inside the stationary shell. |
| 4.5–6.0 s | The liquid curves return to their starting poses and movement direction. |

Three small red, green, and blue segments are fixed in the rim at steady brightness. They never orbit, swivel, flash, or change color. The water carries the circulating motion.

Keep the body of the machine still. There is no full-scene spinning, color wash over the pill, rising liquid level, or implied progress percentage.

### Handoff to completion — approximately 0.5 seconds

The liquid curves straighten. The pill remains hidden under the water. The light segments stay fixed until the closing upper shell physically covers them.

The upper half of the orange begins moving down toward the opening.

## 6. Scan complete

**Visual idea:** the machine closes into a familiar whole orange.

### Transformation — approximately 0.9 seconds

The upper shell enters from above and aligns with the open vessel. It follows the same outline and orange color as the lower shell.

| Time | Movement |
| --- | --- |
| 0.00–0.45 s | The upper shell lowers toward the rim. The visible liquid and pill are progressively covered by the closing shell. |
| 0.45–0.70 s | The two halves meet. The thick rim narrows into a shallow peel contour so the silhouette reads as one orange. |
| 0.70–0.90 s | A short stem extends from the top and a small leaf unfolds from behind it. |

The closure has a gentle stop, without a snap or bounce. The pill disappears through physical occlusion, not by fading or dissolving.

Keep the orange centered. A few broad peel marks make it recognizable, using the same illustration style as the bottle and device.

### Continuous loop — 5 seconds

The orange stays still while the leaf bends a few degrees and returns. This keeps a little life in the scene without repeatedly performing the closure.

Do not add a green approval badge, confetti, or a success burst. The visual message is that the scan is finished.

### Handoff to Starting Research — approximately 0.9 seconds

The orange begins to roll toward the right while becoming smaller, as though moving farther away. A curved path draws in beneath it, and the first document slides into view ahead of it.

The first research scene starts with that orange in the same position, at the same size, and moving in the same direction. There is no cut to an unrelated loader.

## 7. Starting Research

**Visual idea:** oranges roll across a small web of connected documents, following the [new Starting Research frame](https://www.figma.com/design/lPyn5YG33z3lPlWiaKjsK9/Peel-Figma?node-id=186-1285).

### Composition

Use three simple document or browser-card outlines arranged as a loose triangle: one toward the upper left, one toward the upper right, and one lower down. Cards are approximately 60–75 px wide with rounded corners, a small top bar, and two or three short lines suggesting content.

Connect the cards with broad curved paths. Avoid a dense network; three cards and a few connections are enough to communicate the web. Leave open space around the paths.

Use two small oranges, approximately 24–30 px across. One is the orange carried over from Scan complete. Keep their sizes similar and their paths separated so the motion feels organized rather than busy.

### Entrance — approximately 0.8 seconds after the handoff begins

The first card slides in from the right. A connecting line extends toward it. The other two cards move into their places from the sides while their paths grow into view.

The leading orange continues along the first path. The second orange enters from outside the clipped area slightly later. The cards settle and remain stationary during the repeating animation.

### Continuous loop — 6 seconds

**Repeat indefinitely while research is running.** Six seconds is the length of one repeat, not the expected research duration. The animation can run for seconds or minutes without changing speed, becoming more intense, or suggesting it is nearly finished. Its entrance plays only once.

The timing below follows the leading orange. The second orange follows its lower route with a **3-second offset**, so one remains visible while the other passes outside the frame.

| Time | Movement |
| --- | --- |
| 0.0–1.5 s | The leading orange rolls toward the upper-right document. The second follows a separate lower path. |
| 1.5–3.0 s | The leading orange passes partly behind a document, creating depth without transparency. Its path remains visible around the card. |
| 3.0–4.5 s | The leading orange emerges and follows the next curved connection. The second orange reaches its own document at a different moment. |
| 4.5–6.0 s | The leading orange continues beyond a clipped edge and returns from the beginning of its route while the second remains visible. Its hidden reset restores the starting rotation as well as position. |

Show the oranges rolling through the changing position of their leaf and a few peel marks. Rotation should follow the distance travelled: no spinning in place or sliding without turning. Keep their speed steady along the main paths and soften changes of direction.

At least one orange remains visible while the other resets outside the frame. There should be no empty beat, obvious restart, or moment where both oranges teleport. The stationary documents and background make the continuous travel easy to follow. At the six-second join, every visible object's position, rotation, and movement speed match the start of the next repeat.

### Completion exit — approximately 0.65 seconds, from any point

**Start the exit when research actually completes.** Do not wait for the current six-second repeat to finish. Do not restart the animation, jump to a preset pose, or play another entrance before exiting.

| Time from completion | Movement |
| --- | --- |
| 0.00 s | Continue from the exact visible arrangement. Stop recycling oranges: an orange already outside the frame stays outside. |
| 0.00–0.50 s | Slide the entire web illustration—cards, paths, and visible oranges—toward the left as one group. Ease into the movement so there is no jump in position. The oranges continue their small local rolling movement while being carried out with the web. |
| 0.50–0.65 s | Carry the trailing edge completely beyond the clipped left boundary. The existing background stays still and fully visible. The illustration has now cleared the slot. |

Moving the web together gives a consistent exit whether an orange is on a path, behind a card, or already offscreen. Preserve the current shapes and relative positions during the exit; no object needs to return to a specific starting point.

If research completes during the entrance, clear the composition from its current position using the same exit. If reduced motion is enabled or animation is paused, update directly to the completed screen without this movement. An interrupted or cancelled research task uses the existing app navigation; the loop itself never announces completion.

Do not fade the illustration, collapse it to a point, or add a final burst. A fixed timer or number of loops must never trigger completion. Allow at most this short exit when moving to the results; never hold results for a full loop.

## The scanned pill

Only shape, form, color, and optional imprint customize the pill. The current vision response returns these as text descriptions. Match recognized descriptions to a small set of visual options; use defaults for anything missing or unsupported.

| Property | Visual treatment | Default |
| --- | --- | --- |
| **Shape** | Round: circular face. Oval: continuous curved outline. Oblong: longer body with straighter sides and rounded ends. | Oval. |
| **Form** | Tablet: one continuous solid body with a subtle edge. Capsule: rounded elongated body with a narrow join between its two halves. | Tablet. |
| **Color** | Use the closest supported color. A clearly described two-tone capsule has one color on each half. | Off-white. |
| **Imprint — optional** | Use the returned characters when they fit clearly on the visible face. Use dark lettering on light pills and light lettering on dark pills. | Blank. |

A capsule uses the standard elongated capsule silhouette. Supported tablet shapes are round, oval, and oblong. The complete fallback is an **off-white oval tablet with no imprint**.

Use the exact fills in the **Pill palette** under **Color definitions**: white/off-white, yellow, pink, orange, red, blue, green, purple, brown, and near-black. These are visual approximations of the description. Keep a white pill white even though the surrounding design is orange.

For a single-color capsule, both halves use the same color and remain separated by the join. For a clearly split two-color capsule, use the two colors consistently on the same halves. If the description does not clearly map to the supported treatment, use the default instead of inventing another pattern.

Show the imprint on one face only. Preserve its spelling and punctuation. If it would be too small or cramped, leave the illustration blank. Do not add decorative letters as a substitute.

The phone preview and the pill entering the device use the same appearance. Changing scenes must never restore a different default pill.

## Continuity and motion rules

| Element | What stays consistent |
| --- | --- |
| Bottle → imprint | The exiting bottle, emerging pill, and retained phone share one continuous movement. |
| Imprint → device | The pill keeps its shape, color, and orientation as it moves above the vessel. |
| Connecting → placement → checking | The device stays at the same position and scale. Movement changes in the liquid and pill. |
| Checking → complete | The lower device shell becomes the lower half of the whole orange. |
| Complete → research | The completed orange becomes the first rolling orange. |

Use gentle acceleration and deceleration for entrances and landings. Use steady speed for rolling and travelling lights. Curves should be broad enough to follow easily, with no abrupt direction changes.

At a loop boundary, position, shape, and movement speed must match. Backgrounds and headings stay still. Keep opacity constant throughout: objects enter from an edge, emerge from behind another object, change shape, or are revealed by a moving boundary.

The entrance and handoff play once. The small waiting movement repeats. Continuous animation does not mean repeatedly dropping the pill, closing the machine, or replaying every entrance.

## Accessible presentation

Reduced motion uses a clear static composition for each placeholder:

| Scene | Static pose |
| --- | --- |
| Bottle | Bottle and phone aligned, with brackets around the label. |
| Imprint | Matching pill facing forward, with stationary framing brackets. |
| Device connecting | Open orange vessel with the pill above it. |
| Device connected / checking | Pill resting in the opening with a still liquid surface. |
| Scan complete | Closed orange with its leaf. |
| Starting Research | Connected document cards with one orange resting on a path. |

Use direct changes between these poses when reduced motion is enabled. Pausing animation also leaves a clear composition while the existing text continues to explain the current step.

No flashing lights, camera flash, rapid color cycling, or large repeated zooms. Keep pale pills visible with a dark outline; use a lighter edge where needed for a near-black pill. Do not change the observed fill color just to improve visibility.

The existing native instructions and status text communicate the task independently of the illustration. The user should understand every screen with the animation paused.

## Review criteria

The design is ready when each placeholder reads clearly at its actual screen size, every repeating movement joins smoothly, and the same pill and orange can be followed through the sequence. Check the default pill, a round pink tablet, a white oblong tablet, and a two-tone capsule in both the imprint and device scenes.

Watch the research loop for at least ten cycles: the cards should stay stable, the oranges should visibly roll, and their offscreen resets should be imperceptible. Preview completion at 0, 1.5, 3, and 4.5 seconds into the loop, and during the entrance. Every exit should begin from the current pose and clear the slot in approximately 0.65 seconds, with no new orange entering afterward. Watch the full sequence with motion reduced as well; each static composition should still explain its scene.
