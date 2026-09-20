# Flutter hand-off: embedding Peel Atlas in a WebView

This is written for whoever owns `hardware/peel_app` (`origin/hardware-component`).
Nothing here has been run on this machine — there is no Flutter SDK in this
worktree — so treat every step as unverified until you've done it once
yourself. The companion file is `backend/src/backend/graph/handoff/graph_screen.dart`; copy it into
`lib/` more or less as-is.

## What to load

```
$PEEL_API/atlas/?embed=1
$PEEL_API/atlas/?embed=1&demo=1                    # the seeded demo device
$PEEL_API/atlas/?embed=1&focus=scan:<scan_id>       # deep-link from a scan result
```

The graph page and the rest of Peel's API are the **same FastAPI app** —
whatever base URL the app already uses to talk to Peel's API is `$PEEL_API`
here too; there is nothing separate to configure. For local dev on this
branch, that's:

```
uv run --project backend uvicorn backend.app:app --host 0.0.0.0 --port 8010
flutter run --dart-define=PEEL_API=http://<laptop-ip>:8010
```

`--host 0.0.0.0` (not the default `127.0.0.1`) is required or the phone
can't reach it at all. The local launch config binds `127.0.0.1` on purpose;
leave it alone and run the `0.0.0.0` process separately, alongside it.

The device id travels over the bridge (`set_device`), never in this URL —
see the bridge contract below.

## The page cannot be bundled as a Flutter asset

`/atlas/` is plain ES modules making same-origin `fetch()` calls to `/graph/*`
— both of those things require an `http(s)://` origin. Loading it from
`file://` or `android_asset` (`WebViewController.loadFlutterAsset`) breaks
both: ES module `import` resolution and `fetch` behave differently or refuse
to run entirely from those schemes, and even if the HTML rendered, there
would be no backend on the other end of `fetch('/graph')` for it to call. The
page must always be loaded over the network from the FastAPI backend, per
"What to load" above — there is no offline/bundled path today (see "What's
deliberately not here").

## The failure mode that changes how you use this screen

**If Android kills or reclaims the WebView's renderer process** (GPU pressure,
low memory — plausible on the venue's phone after a bloom-lit WebGL scene has
been sitting in the background), **`webview_flutter` has no hook for this.**
`WebViewClientProxyApi` overrides `onPageStarted` / `onPageFinished` /
`onReceivedError` / `shouldOverrideUrlLoading` and others, but not
`onRenderProcessGone`. Android's own docs are blunt about what happens next:
*"If you don't handle these terminations, your app will exit too."* There is
no Dart-side catch for this — the **whole app process exits**, not just this
screen.

That matters specifically because the phone's USB port is occupied by the
spectrometer board for the duration of a reading. If the graph screen takes
the app down mid-reading, the reading is gone too.

**Consequence for how this ships:** open the graph screen on demand — a
button the presenter taps deliberately — and never as something that's
sitting open or auto-launched while a spectrometer session might be running.
Treat it as its own excursion: open it, show the graph, back out.

## Do this tonight, before any graph code exists

Add `webview_flutter: ^4.14.1` to the pubspec, run `flutter pub get`, drop a
**bare `WebViewWidget`** pointing at any LAN URL (your router's admin page is
fine) into any screen, and run a debug build. The app is on AGP 9.1.0 with
`android.builtInKotlin=false` in `gradle.properties`, and `usb_serial` already
needed a Gradle-9 patch — a webview plugin is exactly the kind of dependency
that surfaces an AGP 9 / Kotlin / `minSdk` problem the first time it's added.
Finding that out at 22:30 costs you an hour with people awake to help; finding
it out at 05:00, building the real graph screen for the first time, does not.
If Gradle complains about `minSdk`, set `minSdk = 24`.

## Pick `webview_flutter: ^4.14.1`

- Maintained by the Flutter team; `webview_flutter_android` 4.14.1 needs
  Flutter ≥3.44 / Dart ^3.12, and the app is already on Dart ^3.13.4.
- The alternative, `flutter_inappwebview`, was last published in October
  2024 — a stale plugin is the biggest build risk on an AGP-9 app, not a
  missing feature.
- Both wrap the same Chromium System WebView, so WebGL2 support is
  identical. `hardwareAccelerated="true"` is already set in the manifest.
- Everything this screen needs — a JS channel, `runJavaScript`, console
  capture — is in the base `webview_flutter` API; no platform-specific
  package is required.

## Manifest edits (both required, in `src/main/AndroidManifest.xml` — not `debug/` or `profile/`)

Today `INTERNET` is granted **only** in the debug and profile manifests, so a
release build has no network at all.

```xml
<uses-permission android:name="android.permission.INTERNET"/>
```

And, because the backend is served over plain `http://` on the local network
for the demo (no TLS cert to hand out at a hackathon):

```xml
<application ... android:usesCleartextTraffic="true">
```

Drop `usesCleartextTraffic` only if you switch to an HTTPS tunnel (e.g. a
Runpod proxy URL) instead of the LAN address. If Gradle complains about
`minSdk` after adding the plugin (see "Do this tonight"), set `minSdk = 24`
in the app's `build.gradle.kts`.

## Networking at the venue

- The backend must listen on all interfaces, not just localhost:
  `uv run --project backend uvicorn backend.app:app --host 0.0.0.0 --port 8010`.
  (The local launch config binds `127.0.0.1` on purpose — leave it alone and
  run the `--host 0.0.0.0` process separately for the phone.)
- **Phone and laptop on the same hotspot.** The phone's USB port is occupied
  by the spectrometer board, so `adb reverse` over USB is not available —
  wireless `adb` works fine for installing/debugging over Wi-Fi instead.
- Point the app at the laptop's hotspot IP:
  `flutter run --dart-define=PEEL_API=http://<laptop-ip>:8010`. The
  `10.0.2.2` default in `graph_screen.dart` only resolves on the Android
  *emulator* — it does nothing on a real phone.

## Backend dependency

The graph package (`backend/src/backend/graph/`) needs the Elastic knowledge
layer that is on `main`. **It does not exist on `run-pod-eleven-labs`** or
any branch that hasn't picked up that merge — pointing `PEEL_API` at a
backend started from the wrong branch gets you a 404 at `/atlas/`, not a
graph. If the team's Runpod deployment tracks a different branch, either
redeploy it from this one or run the backend locally per "Networking at the
venue" for the demo.

## The fallback that always works

If the WebView misbehaves in any way at the venue — a renderer death, a
plugin/Gradle problem discovered too late, anything — the exact same page is
reachable with **zero Flutter changes**: open the phone's own Chrome and go to

```
http://<laptop-ip>:8010/atlas/?embed=1
```

That's `?embed=1`, the same query param the WebView uses, so it gets the same
layout (no rail/topbar, the bottom sheet, the floating search button). Treat
the in-app WebView as a bonus on top of this, not a dependency for the demo
to work at all.

## How to test the bridge without a phone

`?embed=1&bridge=debug` makes the page install a stub `PeelBridge` in a plain
desktop browser (since there's no real Flutter host to inject one), so the
whole handshake below can be exercised from DevTools alone:

1. Open `http://127.0.0.1:8010/atlas/?embed=1&fixture=1&bridge=debug` in
   Chrome (Chrome DevTools → device toolbar, any phone preset, is enough to
   see the mobile layout — it doesn't need to be a real device).
2. Open the console. Every message the page sends is logged as
   `[bridge] out {...}`, and it's also collected in `window.__bridgeLog`.
3. Drive the page from the console, exactly like the app would:
   ```js
   PeelAtlas.receive(JSON.stringify({type: 'set_device', device_id: 'peel-graph-demo'}))
   PeelAtlas.receive(JSON.stringify({type: 'focus_node', node_id: 'lot:D2402430', expand: true}))
   PeelAtlas.receive(JSON.stringify({type: 'back'}))
   ```
4. Confirm each produces the expected `[bridge] in`/`[bridge] out` pair
   (`set_device` triggers a graph reload and a fresh `graph_loaded`;
   `focus_node` selects and flies to the node and posts `node_selected`;
   `back` posts `back_result {handled}`).

## 15-minute integration checklist

1. **(Tonight, see above)** bare `WebViewWidget` smoke test on a debug build.
2. Add `webview_flutter: ^4.14.1` to `pubspec.yaml`, `flutter pub get` (2 min).
3. Copy `graph_screen.dart` into `lib/` (1 min).
4. The two manifest edits above (2 min).
5. Add a launch point — an `Icons.hub_outlined` AppBar action, for example —
   that pushes `GraphScreen(deviceId: ..., demo: ...)` (2 min). Per the
   warning above, don't wire this into anything that opens automatically.
6. Start the backend on all interfaces and point the app at it (5 min):
   - `uv run --project backend uvicorn backend.app:app --host 0.0.0.0 --port 8010`
   - phone on the same hotspot as the laptop
   - `flutter run --dart-define=PEEL_API=http://<laptop-ip>:8010`
7. Smoke test (3 min): the graph renders, a tap opens the note sheet, the
   Android back button closes the sheet/modal before it ever pops the route
   (see "Bridge contract v1" → `back`), `[atlas]` lines appear in
   `flutter logs` (from `setOnConsoleMessage`), and the `PeelBridge`
   handshake (`ready` → `set_device`) is visible in those logs too if you add
   a debug print for it.

Update the phone's Android System WebView from the Play Store before the
venue if you can — `chrome://inspect` from a laptop Chrome, with the phone on
USB (borrow one when the spectrometer isn't attached), lets you inspect the
live WebView content if something looks wrong.

## Bridge contract v1

Channel name: **`PeelBridge`**. This is copied verbatim from
`backend/src/backend/graph/static/js/bridge.js` (the allow-lists and message
shapes are pure functions in `js/bridge-protocol.js`, which `bridge.js`
wires into the store/scene/panels) — if this table and that code ever
disagree, the JS is the source of truth. Every message carries `v: 1`; an
unknown or ill-formed message on either side is dropped silently.

JS sends: `window.PeelBridge.postMessage(JSON.stringify(msg))`.
JS receives: `window.PeelAtlas.receive(jsonString)` — accepts either a JSON
string or an already-parsed object (the debug console snippet above uses a
string, matching what a real WebView channel always sends).

**Page → app:**

| type | payload |
|---|---|
| `ready` | — sent once, before any data loads |
| `graph_loaded` | `{nodes, links, demo}` |
| `node_selected` | `{node: {id, type, label, scan_id?}}` |
| `open_scan` | `{scan_id}` |
| `open_url` | `{url}` |
| `error` | `{code, message}` |
| `back_result` | `{handled}` — reply to an app-initiated `back` |

**App → page:**

| type | payload |
|---|---|
| `set_device` | `{device_id, demo?}` — sent immediately on `ready` |
| `focus_node` | `{node_id, expand?}` |
| `back` | — Android back gesture/button; see below |

`set_device` only updates the page's device id/demo flag and lets the
page's own loader react (a `device` store event) — it does not, itself, make
a network call from the bridge's side. `focus_node` selects the node and
flies the camera to it, expanding it first via `/graph/expand` if it isn't
loaded yet and `expand:true` was set.

**`back`** asks the page to handle the system back gesture itself, in order:
close the search modal, else collapse the bottom sheet one detent, else
clear the current selection, else reply `handled:false`. `graph_screen.dart`
wraps the screen in a `PopScope` that intercepts every back press, sends
`back`, and waits **up to 300ms** for `back_result` before deciding whether
to pop the route — long enough for a normal reply, short enough that a
wedged or slow WebView can never make the back button stop working.

The device id travels **only** over `set_device`, never as a URL query
parameter — so it never ends up in a WebView navigation log or history entry.

## What's deliberately not here

- A `?tier=`/quality override: the page already forces the mobile tier under
  `?embed=1`.
- Any offline/asset-bundle mode (loading `assets/graph/` via `file://` or
  `android_asset`) — see "The page cannot be bundled as a Flutter asset"
  above. If venue Wi-Fi turns out to be the blocker rather than the WebView
  itself, that's a separate, larger change — raise it before attempting it,
  don't improvise it at the table.
