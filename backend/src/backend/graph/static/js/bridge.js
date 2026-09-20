// The embed bridge: Atlas <-> a Flutter WebView, or `?embed=1&bridge=debug`
// in a plain desktop browser so the contract can be exercised without a
// phone. Only active in embed mode; every other page never touches
// `window.PeelBridge`. Message shapes (allow-lists, the `v:1` envelope,
// incoming-message parsing, the `back` decision order) are the pure
// functions in bridge-protocol.js; this file is the DOM/store/panel-touching
// half. Keep this file and backend/src/backend/graph/handoff/{FLUTTER_HANDOFF.md,graph_screen.dart}
// agreeing message-by-message — graph_screen.dart is the other reference
// implementation of the same contract.

import { buildOutbound, parseIncoming, decideBack, DETENTS } from './bridge-protocol.js';

let debugMode = false;

/** True once the page is running inside an embed (Flutter WebView or `?embed=1`). */
export function isEmbed() {
  try {
    return document.body?.dataset.embed === '1';
  } catch {
    return false;
  }
}

function bridgeUrlParam() {
  try {
    return new URLSearchParams(window.location.search).get('bridge');
  } catch {
    return null;
  }
}

/**
 * `?embed=1&bridge=debug` lets the lead exercise the whole bridge contract in
 * a desktop browser: if the host page never injected a real `PeelBridge`
 * (there is no Flutter WebView here), install a stub that just records
 * outgoing messages, before `ready` is ever posted.
 */
function installDebugStubIfNeeded() {
  if (window.PeelBridge) return;
  window.PeelBridge = {
    postMessage(message) {
      (window.__bridgeLog ||= []).push(message);
    },
  };
}

/**
 * Post one message to the host app. A safe no-op outside embed mode, if the
 * type is not on the outbound allow-list, or if `window.PeelBridge` was
 * never injected. Always carries `v:1` (via `buildOutbound`).
 */
export function post(type, payload = {}) {
  const message = buildOutbound(type, payload);
  if (!message) return;
  if (!isEmbed()) return;
  if (debugMode) console.log('[bridge] out', message);
  try {
    window.PeelBridge?.postMessage(JSON.stringify(message));
  } catch {
    // The host app is gone or the channel is missing; there is nothing to do.
  }
}

export function postOpenScan(scanId) {
  post('open_scan', { scan_id: scanId });
}

export function postOpenUrl(url) {
  post('open_url', { url });
}

export function postError(code, message) {
  post('error', { code, message });
}

/**
 * Wire the bridge into a live page. Call once, only when `isEmbed()`. Posts
 * `ready` immediately, mirrors `select`/`graph` store events outward, and
 * exposes `window.PeelAtlas.receive` for inbound messages. `search` and
 * `note` are the panel controllers `back` needs (modal open/close, sheet
 * detent) — see panels/index.js.
 */
export function mountBridge({ store, scene, api, search, note }) {
  if (!isEmbed()) return;

  debugMode = bridgeUrlParam() === 'debug';
  if (debugMode) installDebugStubIfNeeded();

  post('ready');

  store.addEventListener('graph', () => {
    post('graph_loaded', {
      nodes: store.state.nodes.size,
      links: store.state.links.size,
      demo: Boolean(store.state.demo),
    });
  });

  store.addEventListener('select', (event) => {
    const { id, node } = event.detail || {};
    if (!id || !node) return;
    post('node_selected', {
      node: {
        id: node.id,
        type: node.type,
        label: node.label,
        scan_id: node.type === 'scan' ? node.id.replace(/^scan:/, '') : undefined,
      },
    });
  });

  window.PeelAtlas = window.PeelAtlas || {};
  window.PeelAtlas.receive = (raw) => {
    if (debugMode) console.log('[bridge] in', raw);
    const parsed = parseIncoming(raw);
    if (!parsed) return; // unknown/ill-formed: ignored silently, per the allow-list

    if (parsed.type === 'set_device') {
      handleSetDevice(parsed.payload, { store });
    } else if (parsed.type === 'focus_node') {
      handleFocusNode(parsed.payload, { store, scene, api });
    } else if (parsed.type === 'back') {
      handleBack({ store, search, note });
    }
  };
}

/**
 * Update the loader's inputs and let it react. This function does NOT fetch
 * a graph itself: `store.setDevice()` dispatches a `device` event, and
 * main.js (which owns the initial-load / live-poll loop) is what listens
 * for that and reloads — keeping "who talks to the network" in one place.
 */
function handleSetDevice(payload, { store }) {
  const deviceId = typeof payload.device_id === 'string' ? payload.device_id : store.state.deviceId;
  if (payload.demo !== undefined) store.configure({ demo: Boolean(payload.demo) });
  store.setDevice(deviceId);
}

async function handleFocusNode(payload, { store, scene, api }) {
  const nodeId = typeof payload.node_id === 'string' ? payload.node_id : null;
  if (!nodeId) return;
  if (!store.state.nodes.has(nodeId) && payload.expand) {
    try {
      const response = await api.expand(nodeId, { deviceId: store.state.deviceId });
      store.merge(response);
    } catch (err) {
      postError('expand_failed', err?.message || `Could not expand ${nodeId}`);
      return;
    }
  }
  if (!store.state.nodes.has(nodeId)) return;
  store.select(nodeId);
  scene?.flyTo?.(nodeId);
}

/**
 * `back`: close the search modal, else collapse the bottom sheet one detent,
 * else clear the selection, else report unhandled so Flutter's `PopScope`
 * pops the route itself. Always replies with `back_result`.
 */
function handleBack({ store, search, note }) {
  const decision = decideBack({
    searchOpen: Boolean(search?.isOpen?.()),
    detent: note?.getDetent ? note.getDetent() : null,
    detents: DETENTS,
    hasSelection: Boolean(store.state.selectedId),
  });

  if (decision.action === 'close_search') search?.close?.();
  else if (decision.action === 'collapse_sheet') note?.setDetent?.(decision.nextDetent);
  else if (decision.action === 'clear_selection') store.select(null);

  post('back_result', { handled: decision.handled });
}
