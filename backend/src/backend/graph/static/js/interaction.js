// Pointer, keyboard and deep-link behaviour for the canvas. Panels, search and the
// note belong to the chrome; nothing here builds UI.

import { PRESENTER_STOPS } from './config.js';

/** A field the viewer is typing into. Keys there belong to the field, not the camera. */
export function isTypingTarget(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
}

export function attachInteraction({
  store, scene, api = null, params = {}, setExpandParent = () => {},
}) {
  const expanded = new Set();
  const inFlight = new Set();
  let chromeHidden = false;

  function deviceId() {
    return store.state.deviceId || params.device_id || null;
  }

  /** The scan that gives an expand its context; without one the backend must stay conservative. */
  function scanContext(node) {
    if (node.type === 'scan') return node.id.slice(5);
    const ids = node.scan_ids || [];
    return ids.length === 1 ? ids[0] : null;
  }

  async function expand(node) {
    if (!node || !node.expandable || !api || typeof api.expand !== 'function') return;
    if (expanded.has(node.id) || inFlight.has(node.id)) return;
    inFlight.add(node.id);
    try {
      const response = await api.expand(node.id, {
        deviceId: deviceId(),
        scanId: scanContext(node),
      });
      expanded.add(node.id);
      setExpandParent(node.id);
      const result = store.merge(response);
      if (!result.changed) setExpandParent(null);
    } catch (error) {
      store.setStatus('error', String((error && error.message) || error));
    } finally {
      inFlight.delete(node.id);
    }
  }

  function select(id, { fly = true } = {}) {
    store.select(id);
    if (id && fly) scene.flyTo(id);
    const node = id ? store.state.nodes.get(id) : null;
    if (node) expand(node);
  }

  function clear() {
    store.select(null);
    store.setHighlight(null);
  }

  function onNode(node) {
    if (!node) { clear(); return; }
    select(node.id);
  }

  function readHash() {
    const match = /#node=([^&]+)/.exec(window.location.hash || '');
    if (!match) return null;
    try { return decodeURIComponent(match[1]); } catch (_) { return match[1]; }
  }

  function applyHash() {
    const id = readHash();
    if (id && store.state.nodes.has(id)) select(id);
  }

  function onKeyDown(event) {
    if (event.defaultPrevented || isTypingTarget(event.target)) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;

    const key = event.key;
    if (key === 'Escape') { clear(); return; }
    if (key === 'f' || key === 'F') { event.preventDefault(); scene.fitView(); return; }
    if (key === 'h' || key === 'H') {
      event.preventDefault();
      chromeHidden = !chromeHidden;
      scene.setChromeHidden(chromeHidden);
      return;
    }
    if (key === 'l' || key === 'L') {
      event.preventDefault();
      store.setView(store.state.view === 'local' ? 'universe' : 'local');
      return;
    }
    // Shift+N (post the prepared demo scan) belongs to the chrome; handling it here
    // too would post the scan twice.
    if (key >= '1' && key <= '4') {
      const id = PRESENTER_STOPS[Number(key) - 1];
      if (id && store.state.nodes.has(id)) {
        event.preventDefault();
        select(id);
      }
    }
  }

  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('hashchange', applyHash);
  store.addEventListener('graph', (event) => {
    if (event.detail.replaced) applyHash();
  });

  return {
    select,
    clear,
    expand,
    onNode,
    onBackground: clear,
    applyHash,
    get chromeHidden() { return chromeHidden; },
    dispose() {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('hashchange', applyHash);
    },
  };
}

export default attachInteraction;
