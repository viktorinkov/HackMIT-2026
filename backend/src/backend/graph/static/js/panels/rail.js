// Left rail (toggle: G): "Needs attention" first — the list answers *what*,
// the graph answers *why*. Then per-type filters, then a legend. Hidden
// entirely in embed/touch by chrome.css.

import { NODE_TYPES, SEVERITY, VERDICT, LINK_STYLE } from '../config.js';

const EVIDENCE_LEGEND = [
  { key: 'link.exact_lot', color: SEVERITY.critical.color },
  { key: 'link.all_lots_product', color: SEVERITY.critical.color },
  { key: 'link.product_line_match', color: LINK_STYLE.uncorroborated.color },
  { key: 'link.lot_only_match', color: LINK_STYLE.uncorroborated.color },
];

const COLLAPSE_MS = 360; // kept in sync with css/chrome.css's --t-panel token

export function mountRail(ctx) {
  const { store, scene, t, dom, formatDate, cleanText, motionMs } = ctx;
  const root = document.getElementById('rail');
  if (!root) return { toggle() {} };

  root.classList.add('atlas-panel');
  const scroll = dom.el('div', { class: 'atlas-rail-scroll' });
  root.appendChild(scroll);

  const attentionSection = buildSection(dom, t('rail.needs_attention'), true);
  const filtersSection = buildSection(dom, t('rail.filters'), true);
  const legendSection = buildSection(dom, t('rail.legend'), false);
  scroll.appendChild(attentionSection.details);
  scroll.appendChild(filtersSection.details);
  scroll.appendChild(legendSection.details);

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

  function renderLegend() {
    dom.clear(legendSection.body);
    for (const [key, sev] of Object.entries(SEVERITY)) {
      legendSection.body.appendChild(
        dom.el('div', { class: 'atlas-legend-row' }, [
          dom.el('span', { class: 'atlas-dot', style: `background:${sev.color}` }),
          dom.el('span', {}, [t(`severity.${key}`)]),
        ])
      );
    }
    legendSection.body.appendChild(
      dom.el('div', { class: 'atlas-panel-title', style: 'margin:10px 0 4px' }, [
        t('rail.legend_evidence'),
      ])
    );
    for (const item of EVIDENCE_LEGEND) {
      legendSection.body.appendChild(
        dom.el('div', { class: 'atlas-legend-row' }, [
          dom.el('span', { class: 'atlas-dot', style: `background:${item.color}` }),
          dom.el('span', {}, [t(item.key)]),
        ])
      );
    }
  }

  store.addEventListener('graph', () => {
    renderAttention();
    renderFilters();
  });
  store.addEventListener('filter', renderFilters);

  renderAttention();
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
