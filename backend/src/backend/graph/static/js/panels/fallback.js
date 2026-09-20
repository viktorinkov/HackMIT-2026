// Fallback (#fallback): the plain list view shown when main.js decides WebGL
// is unavailable ("3D isn't available on this device"). Renders the same
// Needs-attention ordering as the rail, plus a flat list of every node, so
// nothing the graph would have shown is actually lost.
//
// main.js reveals this panel (adds the `atlas-open` class, or sets it
// visible) once it decides 3D cannot run; this module renders into it
// proactively on every graph update and re-renders whenever it is revealed,
// so its content is never stale regardless of which happens first.

import { NODE_TYPES, UNKNOWN_TYPE } from '../config.js';
import { attentionRow } from './rail.js';

export function mountFallback(ctx) {
  const { store, t, dom, cleanText } = ctx;
  const root = document.getElementById('fallback');
  if (!root) return;

  function render() {
    dom.clear(root);
    root.appendChild(dom.el('div', { class: 'atlas-fallback-notice' }, [t('state.no_webgl')]));

    const list = dom.el('div', { class: 'atlas-fallback-list' });
    root.appendChild(list);

    const attentionHeading = dom.el('h2', { class: 'atlas-panel-title' }, [t('rail.needs_attention')]);
    list.appendChild(attentionHeading);
    const scans = typeof store.scansByAttention === 'function' ? store.scansByAttention() : [];
    if (scans.length === 0) {
      list.appendChild(dom.el('div', { class: 'atlas-empty-row' }, [t('rail.needs_attention_empty')]));
    }
    for (const node of scans) {
      list.appendChild(attentionRow(ctx, node));
    }

    const allHeading = dom.el('h2', { class: 'atlas-panel-title', style: 'margin-top:20px' }, [
      t('fallback.all_nodes'),
    ]);
    list.appendChild(allHeading);
    for (const node of store.state.nodes.values()) {
      list.appendChild(nodeRow(node));
    }
  }

  function nodeRow(node) {
    const typeDef = NODE_TYPES[node.type] || UNKNOWN_TYPE;
    const dot = dom.el('span', { class: 'atlas-dot', style: `background:${typeDef.color}` });
    const label = dom.el('span', { class: 'atlas-attention-label' }, [cleanText(node.label, 60)]);
    const type = dom.el('span', { class: 'atlas-attention-chip' }, [typeDef.label]);
    return dom.el(
      'button',
      { type: 'button', class: 'atlas-filter-row', onClick: () => store.select(node.id) },
      [dot, label, type]
    );
  }

  // main.js reveals this panel by clearing the native `hidden` attribute
  // index.html ships it with (`<section id="fallback" hidden>`), not by
  // adding a class. Re-render on every graph change (cheap, and correct
  // whether or not the panel happens to be visible yet) and once more right
  // when it is revealed, in case a change arrived while it was hidden and
  // got coalesced away by nothing in particular.
  store.addEventListener('graph', render);

  const observer = new MutationObserver(() => {
    if (!root.hidden) render();
  });
  observer.observe(root, { attributes: true, attributeFilter: ['hidden'] });

  render();
}
