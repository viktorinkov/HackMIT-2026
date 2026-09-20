// The legend rows: what the colours mean and why something is moving. There is no
// floating key on the canvas; the rail's collapsed Legend section (panels/rail.js) is the
// only place these rows appear, and it builds them here so there is one source of truth.

import { LINK_STYLE, NODE_TYPES, PARTICLE_COLOR, SELECTION_RING } from '../config.js';

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
