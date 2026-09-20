// Left rail (toggle: G): "Needs attention" first — the list answers *what*,
// the graph answers *why*. Then reported sources (crowd reports on this
// device's own scans), per-type filters, then a legend. Hidden entirely in
// embed/touch by chrome.css.

import { NODE_TYPES, SEVERITY, VERDICT } from '../config.js';
import { endpointId } from '../store.js';
import { legendRows } from './key.js';

const COLLAPSE_MS = 360; // kept in sync with css/chrome.css's --t-panel token

export function mountRail(ctx) {
  const { store, scene, t, dom, formatDate, cleanText, motionMs } = ctx;
  const root = document.getElementById('rail');
  if (!root) return { toggle() {} };

  root.classList.add('atlas-panel');
  const scroll = dom.el('div', { class: 'atlas-rail-scroll' });
  root.appendChild(scroll);

  const attentionSection = buildSection(dom, t('rail.needs_attention'), true);
  const reportedSection = buildSection(dom, t('rail.reported_sources'), true);
  const filtersSection = buildSection(dom, t('rail.filters'), true);
  const legendSection = buildSection(dom, t('rail.legend'), false);
  scroll.appendChild(attentionSection.details);
  scroll.appendChild(reportedSection.details);
  scroll.appendChild(filtersSection.details);
  scroll.appendChild(legendSection.details);
  // Hidden when this device has reported no sellers; see renderReportedSources().
  reportedSection.details.hidden = true;

  function renderAttention() {
    dom.clear(attentionSection.body);
    const scans = typeof store.scansByAttention === 'function' ? store.scansByAttention() : [];
    if (scans.length === 0) {
      attentionSection.body.appendChild(
        dom.el('div', { class: 'atlas-empty-row' }, [t('rail.needs_attention_empty')])
      );
      return;
    }
    for (const node of scans) {
      attentionSection.body.appendChild(attentionRow(ctx, node));
    }
  }

  /** This seller's place, found by walking its own `located_in` edge — never
   *  the raw `purchase_location.label` a person typed (see keys.py R3). */
  function placeOf(sellerId) {
    for (const link of store.linksOf(sellerId)) {
      if (link.kind !== 'located_in' || endpointId(link.source) !== sellerId) continue;
      const place = store.state.nodes.get(endpointId(link.target));
      if (place && place.type === 'place') return place;
    }
    return null;
  }

  function reportedSellerNodes() {
    const out = [];
    for (const node of store.state.nodes.values()) {
      if (node.type === 'seller' && node.personal) out.push(node);
    }
    // Most-reported-by-you first, so the row someone is looking for is near the top.
    return out.sort((a, b) => (b.scan_ids?.length || 0) - (a.scan_ids?.length || 0));
  }

  function renderReportedSources() {
    dom.clear(reportedSection.body);
    const sellers = reportedSellerNodes();
    reportedSection.details.hidden = sellers.length === 0;
    if (sellers.length === 0) return;
    for (const node of sellers) {
      reportedSection.body.appendChild(reportedSourceRow(ctx, node, placeOf(node.id)));
    }
  }

  function typeCounts() {
    const counts = new Map();
    for (const node of store.state.nodes.values()) {
      counts.set(node.type, (counts.get(node.type) || 0) + 1);
    }
    return counts;
  }

  function renderFilters() {
    dom.clear(filtersSection.body);
    const counts = typeCounts();
    for (const [typeKey, typeDef] of Object.entries(NODE_TYPES)) {
      const count = counts.get(typeKey) || 0;
      if (count === 0) continue;
      const hidden = store.state.hiddenTypes?.has(typeKey);
      const swatch = dom.el('span', { class: 'atlas-swatch', style: `background:${typeDef.color}` });
      const label = dom.el('span', { class: 'atlas-attention-label' }, [typeDef.label]);
      const countEl = dom.el('span', { class: 'atlas-filter-count' }, [String(count)]);
      const pill = dom.el('span', {
        class: 'atlas-pill-toggle',
        role: 'switch',
        'aria-pressed': String(!hidden),
      });
      const row = dom.el(
        'button',
        {
          type: 'button',
          class: 'atlas-filter-row',
          onClick: () => {
            const nextVisible = Boolean(hidden);
            store.toggleType(typeKey, nextVisible);
            renderFilters();
          },
        },
        [swatch, label, countEl, pill]
      );
      filtersSection.body.appendChild(row);
    }
  }

  // Same six rows the always-on Key panel shows (panels/key.js), so the rail's
  // Legend can never drift from what the canvas actually does.
  function renderLegend() {
    dom.clear(legendSection.body);
    for (const rowEl of legendRows(ctx)) legendSection.body.appendChild(rowEl);
  }

  store.addEventListener('graph', () => {
    renderAttention();
    renderReportedSources();
    renderFilters();
  });
  store.addEventListener('filter', renderFilters);

  renderAttention();
  renderReportedSources();
  renderFilters();
  renderLegend();

  // G collapses the rail with a fade+slide, matching the note panel's
  // treatment: the class flip drives the transition, `.atlas-inert`
  // (visibility+pointer-events) lands only after it finishes, so the rail
  // never intercepts a click while it's mid-fade and never leaves an
  // interactive-but-invisible strip along the left edge afterward.
  let collapsed = false;
  let collapseTimer = null;

  return {
    toggle() {
      collapsed = !collapsed;
      // The scene recentres the graph in the free canvas area as the rail moves.
      scene?.setRailHidden?.(collapsed);
      if (collapsed) {
        root.classList.add('atlas-collapsed');
        if (collapseTimer) clearTimeout(collapseTimer);
        collapseTimer = setTimeout(() => {
          root.classList.add('atlas-inert');
          collapseTimer = null;
        }, motionMs(COLLAPSE_MS));
      } else {
        if (collapseTimer) {
          clearTimeout(collapseTimer);
          collapseTimer = null;
        }
        root.classList.remove('atlas-inert');
        void root.offsetWidth; // force layout so the un-collapse transition actually plays
        root.classList.remove('atlas-collapsed');
      }
    },
  };
}

function buildSection(dom, title, open) {
  const summary = dom.el('summary', {}, [title]);
  const body = dom.el('div', { class: 'atlas-rail-body' });
  const attrs = { class: 'atlas-rail-section' };
  if (open) attrs.open = true;
  const details = dom.el('details', attrs, [summary, body]);
  return { details, summary, body };
}

/**
 * A two-line Needs-attention row: dot + label on top (the label needs the
 * whole line to itself before it can ellipsize sanely), verdict chip + a
 * short formatted date underneath. Shared with panels/fallback.js so the
 * no-WebGL list view reads identically.
 */
export function attentionRow(ctx, node, { onSelect } = {}) {
  const { store, scene, t, dom, formatDate, cleanText } = ctx;
  const verdict = node.verdict ? VERDICT[node.verdict] : null;
  const dot = dom.el('span', {
    class: 'atlas-dot',
    style: `background:${verdict ? verdict.color : SEVERITY.unknown.color}`,
  });
  const label = dom.el('span', { class: 'atlas-attention-label' }, [cleanText(node.label, 60)]);
  const chip = dom.el('span', { class: 'atlas-attention-chip' }, [verdict ? t(verdict.copy) : '']);
  const date = dom.el('span', { class: 'atlas-attention-date' }, [formatDate(node.date)]);
  return dom.el(
    'button',
    {
      type: 'button',
      class: 'atlas-attention-row',
      onClick: () => {
        store.select(node.id);
        scene?.flyTo?.(node.id);
        onSelect?.(node);
      },
    },
    [
      dom.el('span', { class: 'atlas-attention-row-line1' }, [dot, label]),
      dom.el('span', { class: 'atlas-attention-row-line2' }, [chip, date]),
    ]
  );
}

/**
 * One row of "Reported sources": a seller this device's own reports named, the
 * place it gave (if any) and how many of this device's own scans name it —
 * never another device's report. Same shape as `attentionRow`, but the
 * swatch is a square (config.js draws sellers as a box, never a risk shape).
 */
function reportedSourceRow(ctx, node, place) {
  const { store, scene, t, dom, cleanText } = ctx;
  const swatch = dom.el('span', { class: 'atlas-swatch', style: `background:${NODE_TYPES.seller.color}` });
  const label = dom.el('span', { class: 'atlas-attention-label' }, [cleanText(node.label, 60)]);
  const scanCount = node.scan_ids?.length || 0;
  const subParts = [];
  if (place) subParts.push(cleanText(place.label, 40));
  subParts.push(t('rail.reported_source_scans', { n: scanCount }));
  const sub = dom.el('span', { class: 'atlas-attention-chip' }, [subParts.join(' · ')]);
  return dom.el(
    'button',
    {
      type: 'button',
      class: 'atlas-attention-row',
      onClick: () => {
        store.select(node.id);
        scene?.flyTo?.(node.id);
      },
    },
    [
      dom.el('span', { class: 'atlas-attention-row-line1' }, [swatch, label]),
      dom.el('span', { class: 'atlas-attention-row-line2' }, [sub]),
    ]
  );
}
