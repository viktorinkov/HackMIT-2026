// Quick switcher (Cmd/Ctrl+K or "/"): instant local fuzzy hits over loaded
// node labels, plus debounced /graph/search results underneath, as ONE
// arrow-key-navigable list. Search text never touches the URL or browser
// history.

import { NODE_TYPES, UNKNOWN_TYPE } from '../config.js';

const DEBOUNCE_MS = 150;
const MAX_LOCAL_HITS = 8;
const MAX_REMOTE_HITS = 8;

function fuzzyScore(label, query) {
  const hay = label.toLowerCase();
  const needle = query.toLowerCase();
  const idx = hay.indexOf(needle);
  if (idx === -1) return -1;
  // Earlier and tighter matches score higher.
  return 1000 - idx - Math.abs(hay.length - needle.length) * 0.1;
}

function typeLabel(type) {
  return (NODE_TYPES[type] || UNKNOWN_TYPE).label;
}

/**
 * Pure: map a SearchGraphResponse's `hits` (each `{node_id, score, highlight}`)
 * to switcher rows, resolving the real label/type through `response.nodes`
 * (`hits` themselves carry only the id) rather than ever showing the raw id.
 * `detail` is the muted right-hand text: the search snippet if the backend
 * sent one, else the node's own sublabel.
 */
export function rowsFromSearchResponse(response) {
  const nodesById = new Map((response?.nodes || []).map((node) => [node.id, node]));
  return (response?.hits || []).map((hit) => {
    const node = nodesById.get(hit.node_id);
    return {
      id: hit.node_id,
      label: node ? node.label : hit.node_id,
      type: node ? node.type : undefined,
      // Elasticsearch wraps matches in <em>; rows are plain text, so drop the tags.
      detail: (hit.highlight || node?.sublabel || '').replace(/<\/?em>/g, ''),
    };
  });
}

export function mountSearch(ctx) {
  const { store, scene, api, t, dom, toast, cleanText, motionMs } = ctx;
  const root = document.getElementById('search');
  if (!root) return { open() {}, close() {}, isOpen: () => false, toggle() {} };

  // index.html ships `<div id="search" hidden>`; clear that ONE TIME here so
  // chrome.css's opacity/scale transition (not the native `hidden` attribute,
  // whose `[hidden]{display:none!important}` rule cannot be animated) governs
  // visibility from now on. The panel stays mounted; `.atlas-inert` below is
  // the closed/non-interactive state instead of `hidden`.
  root.hidden = false;
  root.classList.add('atlas-inert');

  const panel = dom.el('div', { class: 'atlas-switcher atlas-panel' });
  const input = dom.el('input', {
    class: 'atlas-switcher-input',
    type: 'text',
    placeholder: t('search.placeholder'),
    autocomplete: 'off',
    spellcheck: 'false',
  });
  const results = dom.el('div', { class: 'atlas-switcher-results' });
  const footer = dom.el('div', { class: 'atlas-switcher-footer' }, [t('search.footer_hint')]);
  panel.appendChild(input);
  panel.appendChild(results);
  panel.appendChild(footer);
  root.appendChild(panel);

  root.addEventListener('mousedown', (event) => {
    if (event.target === root) close();
  });

  let items = []; // {id, label, type, detail, kind:'local'|'remote'}
  let selectedIndex = -1;
  let debounceTimer = null;
  let lastRemoteResponse = null;
  let requestToken = 0;
  let closeTimer = null;

  function isOpen() {
    return root.classList.contains('atlas-open');
  }

  function open() {
    if (closeTimer) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
    root.classList.remove('atlas-inert');
    void root.offsetWidth; // force layout so the fade-in actually plays instead of being coalesced away
    root.classList.add('atlas-open');
    input.value = '';
    lastRemoteResponse = null;
    renderLocalOnly('');
    input.focus();
  }

  function close() {
    root.classList.remove('atlas-open');
    input.value = '';
    if (debounceTimer) clearTimeout(debounceTimer);
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(() => {
      root.classList.add('atlas-inert');
      closeTimer = null;
    }, motionMs(120));
  }

  function toggle() {
    if (isOpen()) close();
    else open();
  }

  function localHits(query) {
    if (!query) return [];
    const scored = [];
    for (const node of store.state.nodes.values()) {
      const score = fuzzyScore(node.label || '', query);
      if (score < 0) continue;
      scored.push({ node, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, MAX_LOCAL_HITS).map(({ node }) => ({
      id: node.id,
      label: node.label,
      type: node.type,
      detail: typeLabel(node.type),
      kind: 'local',
    }));
  }

  function renderLocalOnly(query) {
    items = localHits(query);
    selectedIndex = items.length > 0 ? 0 : -1;
    paint();
  }

  function paint() {
    dom.clear(results);
    if (items.length === 0) {
      results.appendChild(dom.el('div', { class: 'atlas-switcher-heading' }, [t('search.no_results')]));
      return;
    }
    let sawRemoteHeading = false;
    let activeRow = null;
    items.forEach((item, index) => {
      if (item.kind === 'remote' && !sawRemoteHeading) {
        sawRemoteHeading = true;
        results.appendChild(
          dom.el('div', { class: 'atlas-switcher-heading' }, [t('search.wider_index')])
        );
      }
      const typeDef = NODE_TYPES[item.type] || UNKNOWN_TYPE;
      const dot = dom.el('span', { class: 'atlas-dot', style: `background:${typeDef.color}` });
      const label = dom.el('span', { class: 'atlas-switcher-label' }, [cleanText(item.label, 60)]);
      const detail = dom.el('span', { class: 'atlas-switcher-sublabel' }, [
        cleanText(item.detail, 40),
      ]);
      const row = dom.el(
        'div',
        {
          class: 'atlas-switcher-row',
          role: 'option',
          'aria-selected': String(index === selectedIndex),
          // Selection fires on pointerdown, not click. A `<div>` row is not
          // natively focusable, so a plain click's mousedown-then-mouseup
          // would first blur the input (moving focus to <body> per the
          // browser's default action) before the click event ever lands —
          // and this row list also rebuilds itself on every hover
          // transition (see onPointerenter below), so the element a
          // deferred `click` would need to land on may already have been
          // replaced by the time mouseup fires. preventDefault() here stops
          // the focus-shift outright and commits the choice on the first
          // event of the gesture, before any of that can happen.
          onPointerdown: (event) => {
            event.preventDefault();
            choose(index);
          },
          onPointerenter: () => {
            selectedIndex = index;
            paint();
          },
        },
        [dot, label, detail]
      );
      results.appendChild(row);
      if (index === selectedIndex) activeRow = row;
    });
    activeRow?.scrollIntoView({ block: 'nearest' });
  }

  async function runRemoteSearch(query) {
    const token = ++requestToken;
    try {
      const response = await api.search(query, { deviceId: store.state.deviceId });
      if (token !== requestToken || input.value.trim() !== query) return; // stale
      lastRemoteResponse = response;
      const remoteHits = rowsFromSearchResponse(response)
        .slice(0, MAX_REMOTE_HITS)
        .map((row) => ({ ...row, kind: 'remote' }));
      const localOnly = items.filter((item) => item.kind === 'local');
      items = [...localOnly, ...remoteHits.filter((r) => !localOnly.some((l) => l.id === r.id))];
      if (selectedIndex === -1 && items.length > 0) selectedIndex = 0;
      paint();
    } catch {
      // A cancelled or failed search just leaves the local hits on screen.
    }
  }

  function onInput() {
    const query = input.value.trim();
    renderLocalOnly(query);
    if (debounceTimer) clearTimeout(debounceTimer);
    if (!query) {
      lastRemoteResponse = null;
      return;
    }
    debounceTimer = setTimeout(() => runRemoteSearch(query), DEBOUNCE_MS);
  }

  function choose(index) {
    const item = items[index];
    if (!item) return;
    try {
      if (lastRemoteResponse) {
        store.merge(lastRemoteResponse);
        const highlight = new Set([...(lastRemoteResponse.highlight || []), item.id]);
        store.setHighlight(highlight);
      } else {
        store.setHighlight(new Set([item.id]));
      }
      store.select(item.id);
      scene?.flyTo?.(item.id);
    } catch {
      toast(t('state.error_body'));
    }
    close();
  }

  input.addEventListener('input', onInput);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (items.length === 0) return;
      selectedIndex = (selectedIndex + 1) % items.length;
      paint();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (items.length === 0) return;
      selectedIndex = (selectedIndex - 1 + items.length) % items.length;
      paint();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (selectedIndex >= 0) choose(selectedIndex);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  });

  return { open, close, toggle, isOpen };
}
