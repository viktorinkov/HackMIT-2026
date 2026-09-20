// The note panel (#note; a bottom sheet in embed/touch): an Obsidian-style
// reading pane for one selected node.
//
// Structural facts (type, verdict, severity, risk, demo, date) come straight
// off the store's own GraphNode — the graph already carries them, no request
// needed. Narrative facts (findings, mismatches, gaps, next steps, sources,
// backlinks, a short body) come from GET /graph/node, rendered as a skeleton
// while in flight and falling back to the node's own fields plus
// `store.linksOf(id)` if that call fails.
//
// Every string the backend authored renders inside an element carrying
// `data-backend-text`, so the assurance-word lint (which scans copy.js and
// index.html only) never has to reason about regulator prose, and so a
// reviewer can grep for exactly the surface where that vocabulary is allowed.
//
// Open/close is one GPU transition (transform + opacity, driven by the
// `.atlas-open` class in css/note.css) with the element always mounted:
// `.atlas-inert` (visibility:hidden + pointer-events:none) is added only
// after the close transition finishes, never at the same instant the class
// flips, so the panel cannot intercept clicks — or be measured as open —
// while it is still animating away, but the fade itself stays visible the
// whole time. Content changes while the panel is already open crossfade or
// fade in rather than flashing a skeleton; see `openFor()`.

import { NODE_TYPES, SEVERITY, VERDICT, UNKNOWN_TYPE, LINK_KIND_COPY } from '../config.js';
import { postOpenScan, postOpenUrl } from '../bridge.js';
import { endpointId } from '../store.js';
import { DETENTS } from '../bridge-protocol.js';

const KNOWN_PROPERTY_COPY_KEYS = {
  expiry: 'property.expiry_label',
  expiration: 'property.expiry_label',
  expiry_label: 'property.expiry_label',
  hardware_reading: 'property.hardware_reading',
};

const ATTRIBUTION_BY_ORG_SUBSTRING = [
  [/fda/i, 'attribution.fda'],
  [/who/i, 'attribution.who'],
  [/mhra/i, 'attribution.mhra'],
  [/health canada/i, 'attribution.health_canada'],
  [/nafdac/i, 'attribution.nafdac'],
  [/pillbox|nlm/i, 'attribution.pillbox'],
];

// Session cache of NodeDetail responses so revisiting a node is instant and
// never re-flashes a skeleton. Bounded, and cleared whenever the device
// changes (a Flutter host re-targeting the page via the bridge) since a
// cached detail belongs to a specific device's scans.
const MAX_DETAIL_CACHE = 64;

// Close animation duration in ms, kept in sync with css/note.css's
// `--t-panel` token (see tokens.css) so the deferred inert/visibility flip
// below always waits at least as long as the CSS transition actually runs.
const CLOSE_MS = 360;

function backendText(dom, tag, text, attrs = {}) {
  return dom.el(tag, { ...attrs, 'data-backend-text': '' }, [text]);
}

function looksSimulated(node, properties) {
  if (node?.attrs?.simulated === true) return true;
  const model = String(node?.attrs?.hardware_model || '').toLowerCase();
  if (model.includes('mock') || model.includes('simulat')) return true;
  const reading = properties.find((p) => p.key === 'hardware_reading');
  return Boolean(reading && /mock|simulat/i.test(reading.value || ''));
}

function attributionCopyKeyFor(sourceOrg) {
  if (!sourceOrg) return null;
  for (const [pattern, key] of ATTRIBUTION_BY_ORG_SUBSTRING) {
    if (pattern.test(sourceOrg)) return key;
  }
  return null;
}

export function mountNote(ctx) {
  const { store, scene, api, t, dom, cleanText, safeUrl, formatDate, motionMs } = ctx;
  const root = document.getElementById('note');
  if (!root) return { getDetent: () => null, setDetent() {} };

  root.classList.add('atlas-panel');
  // Nothing is selected yet at mount: start fully closed and non-interactive,
  // with no transition to play (there is nothing to animate from).
  if (!store.state.selectedId) root.classList.add('atlas-inert');

  const handle = dom.el('div', { class: 'atlas-sheet-handle' });
  const closeBtn = dom.el('button', {
    type: 'button',
    class: 'atlas-note-close',
    'aria-label': t('note.close'),
    onClick: () => store.select(null),
  }, ['×']);
  const scroll = dom.el('div', { class: 'atlas-note-scroll' });
  root.appendChild(handle);
  root.appendChild(closeBtn);
  root.appendChild(scroll);

  wireSheetDrag(root, handle);

  let requestToken = 0;
  let closeTimer = null;
  const detailCache = new Map();

  function cacheDetail(id, detail) {
    detailCache.delete(id); // re-insert so it counts as most-recently-used
    detailCache.set(id, detail);
    if (detailCache.size > MAX_DETAIL_CACHE) {
      detailCache.delete(detailCache.keys().next().value);
    }
  }

  store.addEventListener('device', () => detailCache.clear());

  // --- open/close: one class flip drives the transition; `.atlas-inert`
  // (visibility+pointer-events) is only added after it finishes. ------------
  function openPanel() {
    if (closeTimer) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
    root.classList.remove('atlas-inert');
    void root.offsetWidth; // force layout: some engines coalesce a same-frame class add+remove and skip the transition
    root.classList.add('atlas-open');
  }

  function closePanel() {
    root.classList.remove('atlas-open');
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(() => {
      root.classList.add('atlas-inert');
      closeTimer = null;
    }, motionMs(CLOSE_MS));
  }

  store.addEventListener('select', (event) => {
    const { id } = event.detail || {};
    if (!id) {
      closePanel();
      return;
    }
    openFor(id);
  });

  // --- content crossfade -----------------------------------------------
  function fadeInContent() {
    const ms = motionMs(120);
    scroll.style.transition = 'none';
    scroll.style.opacity = '0';
    void scroll.offsetWidth;
    scroll.style.transition = ms ? `opacity ${ms}ms linear` : '';
    scroll.style.opacity = '1';
  }

  function crossfadeSwap(renderFn) {
    const outMs = motionMs(80);
    scroll.style.transition = outMs ? `opacity ${outMs}ms linear` : '';
    scroll.style.opacity = '0';
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      scroll.removeEventListener('transitionend', onEnd);
      renderFn();
      scroll.scrollTop = 0;
      const inMs = motionMs(80);
      scroll.style.transition = 'none';
      void scroll.offsetWidth;
      scroll.style.transition = inMs ? `opacity ${inMs}ms linear` : '';
      scroll.style.opacity = '1';
    };
    const onEnd = (event) => {
      if (event.target === scroll && event.propertyName === 'opacity') finish();
    };
    scroll.addEventListener('transitionend', onEnd);
    setTimeout(finish, outMs + 40); // fallback if transitionend never fires
  }

  async function openFor(id) {
    const token = ++requestToken;
    const wasOpen = root.classList.contains('atlas-open');
    openPanel();
    if (!wasOpen && (store.state.embed || store.state.tier === 'mobile')) {
      root.dataset.detent = 'peek';
    }

    const node = store.state.nodes.get(id);
    const cached = detailCache.get(id);

    if (cached) {
      if (wasOpen) {
        crossfadeSwap(() => renderDetail(id, node, cached));
      } else {
        renderDetail(id, node, cached);
        scroll.scrollTop = 0;
        fadeInContent();
      }
      return;
    }

    // Keep whatever is already on screen; only show the skeleton if the
    // panel was closed (nothing to keep) or the fetch turns out to be slow.
    let skeletonShown = !wasOpen;
    if (!wasOpen) renderSkeleton();
    const skeletonTimer = wasOpen
      ? setTimeout(() => {
          if (token !== requestToken) return;
          skeletonShown = true;
          renderSkeleton();
        }, 250)
      : null;

    let detail = null;
    let loadError = null;
    try {
      detail = await api.node(id, { deviceId: store.state.deviceId });
    } catch (err) {
      loadError = err;
    }
    if (skeletonTimer) clearTimeout(skeletonTimer);
    if (token !== requestToken) return; // a newer selection has already superseded this fetch

    if (detail) {
      cacheDetail(id, detail);
      if (wasOpen && !skeletonShown) {
        crossfadeSwap(() => renderDetail(id, node, detail));
      } else {
        renderDetail(id, node, detail);
        scroll.scrollTop = 0;
        fadeInContent();
      }
    } else {
      renderFallbackDetail(id, node, loadError);
      scroll.scrollTop = 0;
      fadeInContent();
    }
  }

  function renderSkeleton() {
    dom.clear(scroll);
    for (let i = 0; i < 6; i += 1) {
      const width = 90 - i * 8;
      scroll.appendChild(dom.el('div', { class: 'atlas-skeleton-line', style: `width:${Math.max(width, 30)}%` }));
    }
  }

  function verdictBadges(node) {
    const badges = [];
    if (node?.verdict && VERDICT[node.verdict]) {
      const v = VERDICT[node.verdict];
      const badge = dom.el('span', { class: `atlas-badge atlas-badge--verdict-${node.verdict}` }, [
        t(v.copy),
      ]);
      if (node.verdict === 'no_adverse_findings') {
        badge.title = t('verdict.no_adverse_findings_tooltip', {
          index_date: formatDate(store.state.meta?.index_date) || '—',
        });
      }
      badges.push(badge);
    }
    if (node?.risk_level === 'medium' || node?.risk_level === 'high') {
      badges.push(
        dom.el('span', { class: `atlas-badge atlas-badge--risk-${node.risk_level}` }, [
          t(`risk.${node.risk_level}`),
        ])
      );
    }
    if (node?.demo) {
      badges.push(dom.el('span', { class: 'atlas-badge atlas-badge--demo' }, [t('note.demo_badge')]));
    }
    return badges;
  }

  function propertyRows(node, detail) {
    const rows = [];
    for (const prop of detail.properties || []) {
      const copyKey = KNOWN_PROPERTY_COPY_KEYS[prop.key];
      const labelText = copyKey ? t(copyKey) : cleanText(prop.label, 60);
      const valueCell = backendText(dom, 'td', cleanText(prop.value, 200));
      if (looksSimulated(node, detail.properties || []) && prop.key === 'hardware_reading') {
        valueCell.appendChild(
          dom.el('span', { class: 'atlas-badge atlas-badge--simulated', style: 'margin-left:6px' }, [
            t('hardware.simulated'),
          ])
        );
      }
      rows.push(dom.el('tr', {}, [dom.el('th', {}, [labelText]), valueCell]));
    }
    return rows;
  }

  function renderDetail(id, node, detail) {
    dom.clear(scroll);

    scroll.appendChild(backendText(dom, 'h1', cleanText(detail.title || node?.label || id, 120), {
      class: 'atlas-note-title',
    }));
    if (detail.subtitle) {
      scroll.appendChild(backendText(dom, 'div', cleanText(detail.subtitle, 140), { class: 'atlas-note-subtitle' }));
    }

    const badgeRow = dom.el('div', { class: 'atlas-badge-row' });
    for (const badge of verdictBadges(node)) badgeRow.appendChild(badge);
    for (const label of detail.badges || []) {
      badgeRow.appendChild(backendText(dom, 'span', cleanText(label, 40), { class: 'atlas-badge' }));
    }
    if (badgeRow.childNodes.length > 0) scroll.appendChild(badgeRow);

    if (detail.properties?.length) {
      const table = dom.el('table', { class: 'atlas-properties' });
      for (const row of propertyRows(node, detail)) table.appendChild(row);
      scroll.appendChild(table);
    }

    if (node?.verdict === 'recall_match' || node?.verdict === 'mismatch_found') {
      const callout = dom.el('div', { class: `atlas-callout atlas-callout--${node.verdict}` });
      callout.appendChild(dom.el('div', { class: 'atlas-callout-title' }, [t(VERDICT[node.verdict].copy)]));
      if (detail.body) callout.appendChild(backendText(dom, 'div', cleanText(detail.body, 600)));
      scroll.appendChild(callout);
    } else if (detail.body) {
      // No recall/mismatch verdict to frame as a callout: a plain summary
      // paragraph, still backend prose.
      scroll.appendChild(backendText(dom, 'p', cleanText(detail.body, 600)));
    }

    if (detail.findings?.length) {
      scroll.appendChild(
        section(t('note.findings'), detail.findings.map((f) => findingItem(f)))
      );
    }
    if (detail.mismatches?.length) {
      scroll.appendChild(
        section(t('note.mismatches'), detail.mismatches.map((m) => listItem(cleanText(m, 300))))
      );
    }
    if (detail.backlinks?.length) {
      scroll.appendChild(section(t('note.linked_mentions'), detail.backlinks.map((b) => backlinkRow(b))));
    }
    if (detail.gaps?.length) {
      scroll.appendChild(section(t('note.gaps'), detail.gaps.map((g) => listItem(cleanText(g, 300)))));
    }
    if (detail.next_steps?.length) {
      scroll.appendChild(
        section(
          t('note.next_steps'),
          detail.next_steps.map((s) => dom.el('div', { class: 'atlas-step' }, [backendText(dom, 'span', cleanText(s, 200))])),
          'div'
        )
      );
    }
    if (detail.sources?.length) {
      scroll.appendChild(section(t('note.sources'), detail.sources.map((s) => sourceRow(s)), 'div'));
    }

    if (store.state.embed && node?.type === 'scan') {
      const scanId = id.replace(/^scan:/, '');
      scroll.appendChild(
        dom.el('button', { type: 'button', class: 'atlas-btn atlas-btn--primary', style: 'margin-top:8px', onClick: () => postOpenScan(scanId) }, [
          t('note.open_scan'),
        ])
      );
    }

    scroll.appendChild(dom.el('div', { class: 'atlas-footer' }, [t('footer.attribution')]));
  }

  function findingItem(finding) {
    const dot = dom.el('span', {
      class: 'atlas-severity-dot',
      style: `background:${(finding.severity && SEVERITY[finding.severity]?.color) || SEVERITY.unknown.color}`,
    });
    return dom.el('li', { class: 'atlas-list-item' }, [dot, backendText(dom, 'span', cleanText(finding.statement, 300))]);
  }

  function listItem(text) {
    return dom.el('li', { class: 'atlas-list-item' }, [backendText(dom, 'span', text)]);
  }

  function backlinkRow(backlink) {
    const typeDef = NODE_TYPES[backlink.type] || UNKNOWN_TYPE;
    const dot = dom.el('span', { class: 'atlas-dot', style: `background:${typeDef.color}` });
    const label = backendText(dom, 'span', cleanText(backlink.label, 60), { class: 'atlas-attention-label' });
    const relationCopyKey = LINK_KIND_COPY[backlink.relation];
    const relation = dom.el('span', { class: 'atlas-backlink-relation' }, [
      relationCopyKey ? t(relationCopyKey) : cleanText(backlink.relation, 40),
    ]);
    return dom.el(
      'li',
      {
        class: 'atlas-backlink-row',
        tabindex: '0',
        onMouseenter: () => store.setHighlight(new Set([backlink.node_id])),
        onMouseleave: () => store.setHighlight(null),
        onClick: () => {
          store.select(backlink.node_id);
          scene?.flyTo?.(backlink.node_id);
        },
      },
      [dot, label, relation]
    );
  }

  function sourceRow(source) {
    const url = safeUrl(source.url);
    const linkText = source.link_label ? cleanText(source.link_label, 60) : cleanText(source.title, 80) || t('source.default_link_label');
    const titleEl = url
      ? dom.el(
          'a',
          store.state.embed
            ? {
                href: url,
                class: 'atlas-source-title',
                onClick: (event) => {
                  event.preventDefault();
                  postOpenUrl(url);
                },
              }
            : { href: url, target: '_blank', rel: 'noopener noreferrer', class: 'atlas-source-title' },
          [linkText]
        )
      : backendText(dom, 'span', cleanText(source.title, 80) || linkText, { class: 'atlas-source-title' });

    const metaParts = [source.source_org, formatDate(source.published_at)].filter(Boolean).join(' · ');
    const children = [titleEl];
    if (metaParts) children.push(backendText(dom, 'div', metaParts, { class: 'atlas-source-meta' }));

    const attributionCopyKey = attributionCopyKeyFor(source.source_org);
    if (source.attribution) {
      children.push(backendText(dom, 'div', cleanText(source.attribution, 200), { class: 'atlas-source-attribution' }));
    } else if (attributionCopyKey) {
      children.push(dom.el('div', { class: 'atlas-source-attribution' }, [t(attributionCopyKey)]));
    }

    return dom.el('div', { class: 'atlas-source' }, children);
  }

  function section(heading, children, wrapTag = 'ul') {
    return dom.el('div', { class: 'atlas-section' }, [
      dom.el('div', { class: 'atlas-section-heading' }, [heading]),
      dom.el(wrapTag, { class: 'atlas-list' }, children),
    ]);
  }

  function renderFallbackDetail(id, node, err) {
    dom.clear(scroll);
    if (!node) {
      scroll.appendChild(dom.el('div', { class: 'atlas-note-error' }, [t('note.load_error')]));
      return;
    }
    scroll.appendChild(dom.el('div', { class: 'atlas-note-error' }, [t('note.load_error')]));
    scroll.appendChild(backendText(dom, 'h1', cleanText(node.label, 120), { class: 'atlas-note-title' }));
    if (node.sublabel) {
      scroll.appendChild(backendText(dom, 'div', cleanText(node.sublabel, 140), { class: 'atlas-note-subtitle' }));
    }
    const badgeRow = dom.el('div', { class: 'atlas-badge-row' });
    for (const badge of verdictBadges(node)) badgeRow.appendChild(badge);
    if (badgeRow.childNodes.length > 0) scroll.appendChild(badgeRow);

    const links = typeof store.linksOf === 'function' ? store.linksOf(id) : [];
    if (links.length > 0) {
      const rows = links.map((link) => {
        // The force simulation rewrites `link.source`/`.target` from id
        // strings into node object references in place; endpointId() (also
        // exported by store.js, which relies on this) unwraps either shape.
        const sourceId = endpointId(link.source);
        const otherId = sourceId === id ? endpointId(link.target) : sourceId;
        const otherNode = store.state.nodes.get(otherId);
        return backlinkRow({
          node_id: otherId,
          type: otherNode?.type || 'cluster',
          label: otherNode?.label || otherId,
          relation: link.kind,
        });
      });
      scroll.appendChild(section(t('note.linked_mentions'), rows));
    }
    scroll.appendChild(dom.el('div', { class: 'atlas-footer' }, [t('footer.attribution')]));
    void err; // the message itself is chrome's own generic copy, never the raw error
  }

  return {
    /** The sheet's current detent, or `null` when the panel is closed (nothing to collapse). Used by bridge.js's `back` handler. */
    getDetent() {
      if (!root.classList.contains('atlas-open')) return null;
      return root.dataset.detent || 'peek';
    },
    setDetent(name) {
      if (!DETENTS.includes(name)) return;
      root.dataset.detent = name;
    },
  };
}

// Bottom-sheet drag: press the handle, drag, release to snap to the nearest
// of the three detents (peek/half/full). A tap (no meaningful movement)
// cycles to the next detent instead, so the sheet is usable without any
// drag gesture at all.

/** Pixel translateY that CSS's own `#note[data-detent=...]` rule resolves to at rest. */
function baseTranslateForDetent(detent, root) {
  const h = root.offsetHeight || 0;
  if (detent === 'peek') return Math.max(h - 96, 0);
  if (detent === 'half') return h * 0.5;
  return window.innerHeight * 0.08; // 'full'
}

function wireSheetDrag(root, handle) {
  let startY = 0;
  let startTranslate = 0;
  let dragging = false;
  let moved = false;

  handle.addEventListener('pointerdown', (event) => {
    dragging = true;
    moved = false;
    startY = event.clientY;
    startTranslate = baseTranslateForDetent(root.dataset.detent || 'peek', root);
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const delta = event.clientY - startY;
    if (Math.abs(delta) > 6) moved = true;
    // Follow the finger from wherever the sheet actually was, not from zero —
    // otherwise the first pixel of any drag snaps it to nearly full-open.
    if (moved) root.style.transform = `translateY(${Math.max(startTranslate + delta, 0)}px)`;
  });
  handle.addEventListener('pointerup', (event) => {
    dragging = false;
    handle.releasePointerCapture(event.pointerId);
    root.style.transform = ''; // hand back to the CSS transition for the snap
    if (!moved) {
      const current = DETENTS.indexOf(root.dataset.detent || 'peek');
      root.dataset.detent = DETENTS[(current + 1) % DETENTS.length];
      return;
    }
    const delta = event.clientY - startY;
    const current = DETENTS.indexOf(root.dataset.detent || 'peek');
    if (delta > 60 && current > 0) root.dataset.detent = DETENTS[current - 1];
    else if (delta < -60 && current < DETENTS.length - 1) root.dataset.detent = DETENTS[current + 1];
    else root.dataset.detent = DETENTS[current];
  });
}
