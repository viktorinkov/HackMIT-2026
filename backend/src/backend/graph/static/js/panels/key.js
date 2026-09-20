// The Key ("How to read this"): the answer to "what do these colours mean and
// why is something moving". Always on screen, anchored bottom-left of the free
// canvas above #chips, collapsible to a "Key" pill (remembered in
// localStorage), and — on mobile/embed, where there is no room for it inline —
// reachable through a small "?" button that opens the same rows as a sheet.
//
// `legendRows()` is the one place the six-row legend is built. panels/rail.js
// imports it for the rail's own Legend section so the two can never drift: a
// change here is a change everywhere the legend appears.
//
// Not one of index.html's documented mount points (like panels/help.js, this
// panel owns its own container end to end), so it creates its own elements
// and appends them to `document.body` rather than looking one up.

import { LINK_STYLE, NODE_TYPES, PARTICLE_COLOR, SELECTION_RING } from '../config.js';

const STORAGE_KEY = 'atlas.key.collapsed';

function readStoredCollapsed() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false; // private browsing / blocked storage: default to expanded
  }
}

function writeStoredCollapsed(collapsed) {
  try {
    window.localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
  } catch {
    // Nothing to fall back to; the panel still works for this session.
  }
}

function keyRow(dom, swatch, text, sub) {
  const textChildren = [dom.el('span', { class: 'atlas-key-row-line' }, [text])];
  if (sub) textChildren.push(dom.el('span', { class: 'atlas-key-sub' }, [sub]));
  return dom.el('div', { class: 'atlas-key-row' }, [
    dom.el('span', { class: 'atlas-key-swatch' }, [swatch]),
    dom.el('span', { class: 'atlas-key-row-text' }, textChildren),
  ]);
}

/**
 * The six rows, in order: your scans, a recall on this exact lot (the only
 * one that moves), an uncorroborated match, a plain relation, your own
 * purchase report, and the selection ring. Every swatch is drawn with CSS —
 * no images — and coloured straight from config.js, so a palette change there
 * updates the legend on its own.
 */
export function legendRows(ctx) {
  const { t, dom } = ctx;

  const scanDot = dom.el('span', {
    class: 'atlas-key-dot',
    style: `background:${NODE_TYPES.scan.color}`,
  });

  const particle = () =>
    dom.el('span', { class: 'atlas-key-particle', style: `background:${PARTICLE_COLOR}` });
  const alertLine = dom.el('span', { class: 'atlas-key-line atlas-key-line--alert' }, [
    particle(),
    particle(),
    particle(),
  ]);

  // "Faint" is a real property of this line in the scene, not just a word —
  // it is drawn at LINK_STYLE.uncorroborated.alpha there too.
  const uncorroboratedLine = dom.el('span', {
    class: 'atlas-key-line',
    style: `background:${LINK_STYLE.uncorroborated.color};opacity:${LINK_STYLE.uncorroborated.alpha}`,
  });

  const relationLine = dom.el('span', {
    class: 'atlas-key-line atlas-key-line--thin',
    style: `background:${LINK_STYLE.weak.color}`,
  });

  const reportSwatch = dom.el('span', { class: 'atlas-key-report-swatch' }, [
    dom.el('span', { class: 'atlas-key-square', style: `background:${NODE_TYPES.seller.color}` }),
    dom.el('span', { class: 'atlas-key-line', style: `background:${LINK_STYLE.report.color}` }),
  ]);

  const selectionRing = dom.el('span', {
    class: 'atlas-key-ring',
    style: `border-color:${SELECTION_RING}`,
  });

  return [
    keyRow(dom, scanDot, t('key.row_scan')),
    keyRow(dom, alertLine, t('key.row_alert'), t('key.row_alert_sub')),
    keyRow(dom, uncorroboratedLine, t('key.row_uncorroborated')),
    keyRow(dom, relationLine, t('key.row_relation')),
    keyRow(dom, reportSwatch, t('key.row_report')),
    keyRow(dom, selectionRing, t('key.row_selected')),
  ];
}

export function mountKey(ctx) {
  const { t, dom } = ctx;

  const root = dom.el('div', { class: 'atlas-panel atlas-key', id: 'atlas-key' });
  const titleLabel = dom.el('span', { class: 'atlas-key-toggle-label' }, [t('key.title')]);
  const toggle = dom.el(
    'button',
    {
      type: 'button',
      class: 'atlas-key-toggle',
      'aria-expanded': 'true',
      onClick: () => setCollapsed(!collapsed),
    },
    [titleLabel]
  );
  const body = dom.el('div', { class: 'atlas-key-body' });
  for (const rowEl of legendRows(ctx)) body.appendChild(rowEl);
  root.appendChild(toggle);
  root.appendChild(body);
  document.body.appendChild(root);

  let collapsed = readStoredCollapsed();

  function setCollapsed(next) {
    collapsed = next;
    root.classList.toggle('atlas-key--collapsed', collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    titleLabel.textContent = collapsed ? t('key.pill') : t('key.title');
    writeStoredCollapsed(collapsed);
  }
  setCollapsed(collapsed);

  // Mobile / embed: chrome.css hides `.atlas-key` outright (no room for a
  // fifth floating panel on a phone). A small "?" FAB opens the same six rows
  // as a bottom sheet instead — built from the very same `legendRows()`.
  const fab = dom.el(
    'button',
    { type: 'button', class: 'atlas-key-fab', 'aria-label': t('key.open') },
    ['?']
  );
  document.body.appendChild(fab);

  const sheet = dom.el('div', { class: 'atlas-key-sheet' });
  const card = dom.el('div', { class: 'atlas-key-sheet-card atlas-panel' });
  const sheetTitle = dom.el('div', { class: 'atlas-key-sheet-title' }, [t('key.title')]);
  const sheetBody = dom.el('div', { class: 'atlas-key-body atlas-key-body--sheet' });
  for (const rowEl of legendRows(ctx)) sheetBody.appendChild(rowEl);
  const closeBtn = dom.el(
    'button',
    { type: 'button', class: 'atlas-btn', style: 'margin-top:12px;width:100%', onClick: () => closeSheet() },
    [t('help.close')]
  );
  card.appendChild(sheetTitle);
  card.appendChild(sheetBody);
  card.appendChild(closeBtn);
  sheet.appendChild(card);
  document.body.appendChild(sheet);

  sheet.addEventListener('mousedown', (event) => {
    if (event.target === sheet) closeSheet();
  });

  function isSheetOpen() {
    return sheet.classList.contains('atlas-open');
  }
  function openSheet() {
    sheet.classList.add('atlas-open');
  }
  function closeSheet() {
    sheet.classList.remove('atlas-open');
  }
  fab.addEventListener('click', () => (isSheetOpen() ? closeSheet() : openSheet()));

  return {
    isCollapsed: () => collapsed,
    setCollapsed,
    isSheetOpen,
    openSheet,
    closeSheet,
  };
}
