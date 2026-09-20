# Atlas front-end contract

The page lives in `backend/src/backend/graph/static/` and is served at `/atlas/`. No build step.
Our code is ES modules. Two people build it in parallel: **scene** (the WebGL canvas) and
**chrome** (panels, search, API client). They meet only through the things on this page.

Data vocabulary (node types, link kinds, colours, tiers): `js/config.js`, which mirrors
`backend/src/backend/graph/models.py`. API shapes: the pydantic models in that file.

## Files and owners

| Owner | Files |
|---|---|
| lead | `js/config.js`, this document |
| scene | `index.html`, `js/boot.js`, `js/main.js`, `js/store.js`, `js/scene.js`, `js/nodes.js`, `js/links.js`, `js/labels.js`, `js/interaction.js`, `js/fx/bloom.js`, `../static_app.py` |
| chrome | `css/*.css`, `js/copy.js`, `js/api.js`, `js/bridge.js`, `js/safe.js`, `js/panels/*.js`, `fixtures/*` is backend's |

`index.html` loads, in order: the import map (first thing in `<head>`), `css/tokens.css`,
`css/chrome.css`, the vendor UMD as a classic script, then `<script type="module" src="js/main.js">`.
`main.js` imports chrome through one call: `import { mountChrome } from './panels/index.js'`.

## Mount points in `index.html`

`#canvas` (WebGL container, full bleed) · `#labels` (DOM label layer, pointer-events none) ·
`#topbar` · `#rail` (left) · `#note` (right panel; becomes a bottom sheet in embed/touch) ·
`#search` (modal) · `#chips` (persistent chips, top centre) · `#toasts` · `#hud` (`?debug=1`) ·
`#fallback` (the "3D unavailable" card + list view).

`<body>` carries `data-tier="desktop|mobile"` and `data-embed="0|1"`; chrome styles key off these.

## `js/store.js` — the only shared state

```js
export const store;               // singleton, extends EventTarget
store.state = {
  nodes: Map<id, node>, links: Map<id, link>,
  adjacency: Map<id, Set<id>>,    // undirected
  degree: Map<id, number>,
  selectedId: string|null, hoveredId: string|null,
  highlight: Set<id>,             // lit nodes (hover or selection neighbourhood or search path)
  hiddenTypes: Set<NodeType>,
  view: 'local'|'universe',
  meta: GraphMeta|null,
  deviceId: string|null, demo: boolean, tier: 'desktop'|'mobile', embed: boolean,
};
store.setGraph(graphResponse)                 // wholesale replace
store.merge(graphLike) -> {addedNodes, addedLinks, changed}   // identity-preserving, idempotent
store.select(id|null)   store.hover(id|null)
store.setHighlight(idsIterable|null)
store.toggleType(type, visible)   store.setView(view)
store.neighbours(id) -> Set<id>   store.linksOf(id) -> link[]
store.scansByAttention() -> node[]            // scans sorted by verdict severity, then date desc
```

`mergeGraph(current, incoming)` is exported separately and is pure (Node-tested): it keeps
existing node objects so `x/y/z/vx/vy/vz` survive, patches display fields in place, dedupes links
by `id`, drops links with a missing endpoint, and reports `changed:false` for a no-op.

Events (`store.addEventListener(name, e => e.detail)`):

| Event | detail | Fired when |
|---|---|---|
| `graph` | `{addedNodes, addedLinks, replaced:boolean}` | data changed |
| `select` | `{id, node}` | selection changed (id may be null) |
| `hover` | `{id}` | hover changed |
| `highlight` | `{ids:Set}` | lit set changed |
| `filter` | `{hiddenTypes}` | type visibility changed |
| `view` | `{view}` | Local / Universe toggled |
| `status` | `{kind:'loading'|'ready'|'error'|'offline'|'demo', message}` | load state |

## What scene exposes to chrome (`js/scene.js`)

```js
flyTo(id, {ms}?)            // select-less camera flight to a node
fitView(ms?)                // zoom to fit
screenOf(id) -> {x,y}|null  // CSS pixels, for anchoring popovers
setChromeHidden(bool)
setRailHidden(bool)         // the rail toggle calls this so the graph recentres in the free canvas
```

Scene listens to store events and never imports from `panels/`. Chrome never touches three.js
objects or `ForceGraph3D`; it calls the functions above and the store.

**Camera rule.** A node flight is a pan + dolly that keeps the current viewing direction; it never
rotates the view, and it always ends with the node as the orbit pivot (`controls.target`), which
then follows the node while the simulation moves it. The geometry is pure and Node-tested in
`js/camera-math.js` (`planFlight`, `flightFrame`, `followStep`). Do not call the library's
`Graph.cameraPosition()` for node flights: it places the camera on the origin→node ray and tweens
the look-at from a point 1000 units ahead, which swings the view by tens of degrees.

## What chrome exposes to scene

```js
// js/panels/index.js
mountChrome({ store, scene, api })   // builds every panel into the mount points
// js/api.js
api.graph({deviceId, demo, universe}) -> GraphResponse
api.universe() -> GraphResponse
api.expand(id, {deviceId, scanId}) -> ExpandResponse
api.node(id, {deviceId}) -> NodeDetail
api.search(q, {deviceId, signal}) -> SearchGraphResponse
api.postDemoScan() -> {scan_id}              // presenter hotkey; POST /scans with a prepared payload
// js/safe.js
cleanText(s, max)   safeUrl(s) -> string|null   dropSensitive(obj)
// js/copy.js
t(key, vars?) -> string                       // every user-facing string goes through this
```

`api.js`: 8 s timeout, one retry on network error or 502/503/504, in-flight dedupe, a new search
aborts the previous one, no custom request headers (avoids CORS preflight). With `?fixture=1` it
serves `fixtures/demo_graph.json` and the canned expand/search/node responses without touching the
network. With `?demo=1` it falls back to those only on a network failure. A live session never
falls back to demo data.

## Behaviour both sides rely on

- Click a node → `store.select(id)`; scene flies there; chrome opens the note from `api.node`.
  If `node.expandable`, interaction calls `api.expand` and `store.merge`s the result: new nodes
  spawn at the parent's position, everything outside the parent's one-hop set is pinned
  (`fx/fy/fz`) until `onEngineStop`, and a no-op merge never calls `graphData()`.
- Live refresh: every `POLL_MS`, `api.graph` then `store.merge`. New scan nodes bloom in.
- Keys: `Cmd/Ctrl+K` or `/` search · `Esc` close/clear · `F` fit · `L` Local/Universe · `H` hide
  chrome · `1`–`4` fly to `PRESENTER_STOPS` · `Shift+N` post the prepared demo scan · `?` help.
- `window.__atlas = { store, fps(), stats(), screenOf(id), select(id), search(q) }` for
  verification.
- Embed (`?embed=1`): tier forced to mobile, no rail, note becomes a bottom sheet, `js/bridge.js`
  posts `ready / graph_loaded / node_selected / open_scan / open_url / error` to
  `window.PeelBridge` and receives `set_device / focus_node` through `window.PeelAtlas.receive`.
- **Colour means one thing, everywhere on the page.** Purple is yours (your scans, and
  nothing else). White is only "what you are looking at" (hover/selection: `HIGHLIGHT_LINK`
  and `SELECTION_RING` in `config.js` — near-white, deliberately not purple, so a selected
  node never reads as a second kind of finding next to a red recall path). Red/orange/yellow
  plus three moving dots means a recall names this exact lot, the dots flowing from the
  recall to your lot (`exact_lot`/`all_lots_product`/`ndc_in_description`, `alert=True`
  only). Sand means a crowd report — your own, unverified account of a purchase
  (`REPORT_KINDS`), never a finding, never coloured by severity. A faint thin line is a plain
  relation; nothing moves on it and nothing glows.
- **The legend** lives in the rail's collapsed Legend section only; there is no floating key
  on the canvas. Its six rows state the rule above and come from `legendRows()`
  (`js/panels/key.js`). A note's header carries a small ring glyph next to the title, the same
  white as `SELECTION_RING`, so the panel and the scene's selection ring read as one thing.

## Rules that are tested

- Data reaches the DOM through `textContent` / `createTextNode` only. No `innerHTML`,
  `insertAdjacentHTML`, `outerHTML`, `document.write` with data. `nodeLabel(() => '')` and
  `linkLabel(() => '')` on the graph: the library's tooltip writes HTML.
- Links: `safeUrl()` accepts `http:`/`https:` only; anchors get `rel="noopener noreferrer"`.
- `copy.js` and `index.html` never contain the words safe, genuine, verified or authentic
  (`safe-area-inset` in CSS is fine). Backend prose that must contain them renders only inside
  `[data-backend-text]`.
- `copy.js` never contains fake, counterfeit, illegal, fraud, scam, guilty, unsafe or
  dangerous: a crowd report is one person's unverified account (`REPORT_KINDS`), and no
  string may accuse the seller or place it names of anything.
- `no_adverse_findings` is slate with no tick. "Low risk" is never shown. Expiry and hardware
  degradation are separate badges. Simulated hardware is always badged with its limitation text.
- While any `demo` node is on screen, `#chips` shows `t('chip.demo')`.
- A `seller`/`place` node never renders a severity, verdict or risk badge, whatever its
  `NodeDetail` carries — reports cluster; they never accuse.
