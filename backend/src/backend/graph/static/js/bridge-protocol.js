// Pure protocol logic for the Flutter embed bridge: the allow-lists, the
// outbound envelope shape, incoming-message parsing, and the `back` decision
// order. No `window`/`document` reference anywhere in this file, so it
// imports cleanly into a Node test — bridge.js is the DOM-touching half that
// wires these into the store/scene/search/note panels.

export const OUTBOUND_TYPES = Object.freeze([
  'ready',
  'graph_loaded',
  'node_selected',
  'open_scan',
  'open_url',
  'error',
  'back_result',
]);

export const INBOUND_TYPES = Object.freeze(['set_device', 'focus_node', 'back']);

// The bottom sheet's three detents, most-collapsed to most-open. Shared by
// panels/note.js (which renders them) and bridge.js's `back` handler (which
// walks down this list one step at a time) so the two can never drift.
export const DETENTS = Object.freeze(['peek', 'half', 'full']);

const OUTBOUND_SET = new Set(OUTBOUND_TYPES);
const INBOUND_SET = new Set(INBOUND_TYPES);

/**
 * `{v:1, type, ...payload}`, or `null` if `type` is not on the outbound
 * allow-list. Every outgoing message carries `v:1`; this is the one place
 * that constant is written.
 */
export function buildOutbound(type, payload = {}) {
  if (!OUTBOUND_SET.has(type)) return null;
  return { v: 1, type, ...payload };
}

/**
 * Accepts either a JSON string (what a real WebView channel always sends)
 * or an already-parsed plain object (what `?bridge=debug`'s console helper
 * and tests often hand over) — `receive()` must accept both. Returns
 * `{type, payload}` with `type`/`v` stripped out of payload, or `null` for
 * anything unparsable, non-object, or not on the inbound allow-list. Unknown
 * or ill-formed messages are dropped silently by design: this is a boundary
 * an embedding app can send arbitrary JSON across, not a trusted RPC layer.
 */
export function parseIncoming(raw) {
  let message = raw;
  if (typeof raw === 'string') {
    try {
      message = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!message || typeof message !== 'object' || Array.isArray(message)) return null;
  if (!INBOUND_SET.has(message.type)) return null;
  const { type, v, ...payload } = message;
  void v; // accepted but not required or validated on the way in
  return { type, payload };
}

/**
 * The `back` decision order: close the search modal first, else collapse the
 * bottom sheet one detent, else clear the current selection, else report
 * unhandled so Flutter's `PopScope` knows to pop the route itself.
 *
 * `detents` is the ordered list from most-collapsed to most-open (e.g.
 * `['peek','half','full']`); `detent` is where the sheet currently sits, or
 * `null`/`undefined` when there is no sheet to collapse (the sheet is only
 * ever mounted in embed mode, so in practice this is always non-null when
 * `back` fires, but the function stays correct either way).
 */
export function decideBack({ searchOpen, detent, detents, hasSelection }) {
  if (searchOpen) return { action: 'close_search', handled: true };
  if (detent && Array.isArray(detents)) {
    const index = detents.indexOf(detent);
    if (index > 0) return { action: 'collapse_sheet', handled: true, nextDetent: detents[index - 1] };
  }
  if (hasSelection) return { action: 'clear_selection', handled: true };
  return { action: 'none', handled: false };
}
