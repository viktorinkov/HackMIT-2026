// Pure-module tests for js/config.js, the vocabulary the scene and the chrome share.
// Run with: node --test "backend/tests/graph/js/**/*.test.mjs" from the repo root.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BG, HIGHLIGHT_LINK, INTENSITY, LINK_CLASS, LINK_STYLE, NODE_TYPES, PRESENTER_STOPS,
  REPORT_KINDS, SELECTION_RING, SEVERITY, SIM, TIERS, UNCORROBORATED_KINDS,
  UNKNOWN_TYPE, VERDICT, linkClass, nodeColor, nodeRadius, typeOf,
} from '../../../src/backend/graph/static/js/config.js';

const HEX = /^#[0-9a-f]{6}$/i;

function channels(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

/** How far a colour is from grey: 0 is neutral, 255 is a fully saturated hue. */
function chroma(hex) {
  const rgb = channels(hex);
  return Math.max(...rgb) - Math.min(...rgb);
}

test('no node, severity or verdict colour is green', () => {
  const hues = [];
  const collect = (hex) => {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    // Green reads as assurance, and Peel never gives one.
    if (g > r + 24 && g > b + 24) hues.push(hex);
  };
  for (const entry of Object.values(NODE_TYPES)) collect(entry.color);
  for (const entry of Object.values(SEVERITY)) collect(entry.color);
  for (const entry of Object.values(VERDICT)) collect(entry.color);
  assert.deepEqual(hues, []);
});

test('every node type declares a six-digit hex colour and a positive base radius', () => {
  for (const [name, entry] of Object.entries(NODE_TYPES)) {
    assert.match(entry.color, HEX, `${name} colour`);
    assert.ok(entry.r0 > 0, `${name} r0`);
    assert.ok(typeof entry.label === 'string' && entry.label.length > 0, `${name} label`);
  }
  assert.match(UNKNOWN_TYPE.color, HEX);
  assert.match(BG, HEX);
});

test('an unknown node type falls back to the placeholder rather than throwing', () => {
  assert.equal(typeOf({ type: 'not_a_type' }), UNKNOWN_TYPE);
  assert.equal(nodeColor({ type: 'not_a_type' }), UNKNOWN_TYPE.color);
});

test('a record node takes its colour from its severity, not its type', () => {
  assert.equal(nodeColor({ type: 'record', severity: 'critical' }), SEVERITY.critical.color);
  assert.equal(nodeColor({ type: 'record' }), NODE_TYPES.record.color);
});

test('a node type without bySeverity ignores a severity field', () => {
  assert.equal(nodeColor({ type: 'lot', severity: 'critical' }), NODE_TYPES.lot.color);
});

test('radius grows with degree and never exceeds 2.4 times the base', () => {
  const base = nodeRadius({ type: 'lot' }, 0);
  assert.equal(base, NODE_TYPES.lot.r0);
  assert.ok(nodeRadius({ type: 'lot' }, 8) > base);
  assert.ok(nodeRadius({ type: 'lot' }, 100000) <= NODE_TYPES.lot.r0 * 2.4 + 1e-9);
});

test('a critical record is drawn larger than a moderate one at the same degree', () => {
  const critical = nodeRadius({ type: 'record', severity: 'critical' }, 3);
  const moderate = nodeRadius({ type: 'record', severity: 'moderate' }, 3);
  assert.ok(critical > moderate);
});

test('an alert link is classed as an alert whatever its kind says', () => {
  assert.equal(linkClass({ kind: 'lot_only_match', alert: true }), LINK_CLASS.ALERT);
});

test('every uncorroborated kind classes as uncorroborated, never as strong', () => {
  for (const kind of UNCORROBORATED_KINDS) {
    assert.equal(linkClass({ kind, strong: true }), LINK_CLASS.UNCORROBORATED, kind);
  }
});

test('a conflict link is its own class', () => {
  assert.equal(linkClass({ kind: 'conflicts_with' }), LINK_CLASS.CONFLICT);
});

test('an unrecognised kind falls back to strong or weak but is never an alert', () => {
  assert.equal(linkClass({ kind: 'invented_kind', strong: true }), LINK_CLASS.STRONG);
  assert.equal(linkClass({ kind: 'invented_kind' }), LINK_CLASS.WEAK);
});

test('an uncorroborated edge is fainter and longer than a strong one', () => {
  assert.ok(LINK_STYLE.uncorroborated.alpha < LINK_STYLE.strong.alpha);
  assert.ok(LINK_STYLE.uncorroborated.distance > LINK_STYLE.strong.distance);
});

test('only alert links carry particles', () => {
  for (const [name, style] of Object.entries(LINK_STYLE)) {
    if (name === LINK_CLASS.ALERT) assert.ok(style.particles > 0);
    else assert.equal(style.particles, 0, name);
  }
});

test('every link class has a style entry the scene can look up', () => {
  for (const cls of Object.values(LINK_CLASS)) {
    assert.ok(LINK_STYLE[cls], cls);
    assert.ok(LINK_STYLE[cls].distance > 0, cls);
  }
});

test('the intensity ladder descends from lit to dimmed', () => {
  assert.ok(INTENSITY.lit > INTENSITY.rest);
  assert.ok(INTENSITY.rest > INTENSITY.second);
  assert.ok(INTENSITY.second > INTENSITY.dim);
  assert.ok(INTENSITY.tauMs > 0);
});

test('the mobile tier is strictly cheaper than the desktop tier', () => {
  assert.ok(TIERS.mobile.maxNodes < TIERS.desktop.maxNodes);
  assert.ok(TIERS.mobile.maxLinks < TIERS.desktop.maxLinks);
  assert.ok(TIERS.mobile.labels < TIERS.desktop.labels);
  assert.ok(TIERS.mobile.pixelRatioCap <= TIERS.desktop.pixelRatioCap);
  assert.ok(TIERS.mobile.nodeResolution < TIERS.desktop.nodeResolution);
  assert.equal(TIERS.mobile.bloom, false);
});

test('the incremental simulation settles faster than the opening layout', () => {
  assert.ok(SIM.incremental.cooldownTime < SIM.initial.cooldownTime);
  assert.ok(SIM.incremental.cooldownTicks < SIM.initial.cooldownTicks);
  assert.ok(SIM.incremental.alphaDecay > SIM.initial.alphaDecay);
  assert.ok(SIM.charge < 0);
});

test('every presenter stop is a prefixed node id', () => {
  assert.equal(PRESENTER_STOPS.length, 4);
  for (const id of PRESENTER_STOPS) assert.match(id, /^[a-z]+:.+/);
});

test('no adverse findings is slate and shares no colour with a recall match', () => {
  assert.notEqual(VERDICT.no_adverse_findings.color, VERDICT.recall_match.color);
  assert.equal(VERDICT.recall_match.color, SEVERITY.critical.color);
});

// ------------------------------------------------------------- what a colour means
//
// One recalled lot showed a red path with moving dots while another sat inside a
// purple ring with purple lines, and the two read as two different findings. They
// were never that: the red path is a recall, the purple was only "selected". These
// tests hold the vocabulary apart -- purple is yours, white is what you are looking
// at, and a severity colour is the only thing that means a finding.

test('hover and selection are neutral, and share no colour with your scans', () => {
  assert.match(HIGHLIGHT_LINK, HEX);
  assert.match(SELECTION_RING, HEX);
  // Near-grey: a highlight that carried a hue would compete with the severity colours.
  assert.ok(chroma(HIGHLIGHT_LINK) <= 16, HIGHLIGHT_LINK);
  assert.ok(chroma(SELECTION_RING) <= 16, SELECTION_RING);
  assert.notEqual(HIGHLIGHT_LINK.toLowerCase(), NODE_TYPES.scan.color.toLowerCase());
  assert.notEqual(SELECTION_RING.toLowerCase(), NODE_TYPES.scan.color.toLowerCase());
});

test('the scan purple belongs to your scans and to nothing else', () => {
  const scan = NODE_TYPES.scan.color.toLowerCase();
  for (const [name, entry] of Object.entries(NODE_TYPES)) {
    if (name === 'scan') continue;
    assert.notEqual(entry.color.toLowerCase(), scan, name);
  }
  for (const entry of Object.values(SEVERITY)) assert.notEqual(entry.color.toLowerCase(), scan);
  for (const entry of Object.values(VERDICT)) assert.notEqual(entry.color.toLowerCase(), scan);
});

test('a severity colour is more saturated than anything highlighting can produce', () => {
  for (const [name, entry] of Object.entries(SEVERITY)) {
    if (name === 'unknown') continue;
    assert.ok(chroma(entry.color) > chroma(HIGHLIGHT_LINK), name);
    assert.ok(chroma(entry.color) > chroma(SELECTION_RING), name);
  }
});

test('a crowd report is its own link class, ahead of an uncorroborated match', () => {
  for (const kind of REPORT_KINDS) {
    assert.equal(linkClass({ kind }), LINK_CLASS.REPORT, kind);
    assert.equal(linkClass({ kind, strong: true }), LINK_CLASS.REPORT, kind);
  }
  assert.ok(LINK_STYLE[LINK_CLASS.REPORT], 'the scene needs a report style to pool');
});

test('a report edge is sand, never a severity colour, and carries no particles', () => {
  const report = LINK_STYLE.report.color;
  assert.match(report, HEX);
  assert.equal(LINK_STYLE.report.particles, 0);
  for (const [name, entry] of Object.entries(SEVERITY)) {
    assert.notEqual(report.toLowerCase(), entry.color.toLowerCase(), name);
  }
  // The edge and the seller it leads to are the same sand, so a report reads as one thing.
  assert.equal(report.toLowerCase(), NODE_TYPES.seller.color.toLowerCase());
  assert.ok(LINK_STYLE.report.alpha < LINK_STYLE.alert.alpha);
});

test('a reported seller or place is never coloured or sized by severity', () => {
  for (const type of ['seller', 'place']) {
    assert.ok(!NODE_TYPES[type].bySeverity, type);
    assert.equal(nodeColor({ type, severity: 'critical' }), NODE_TYPES[type].color, type);
  }
});

test('a seller is a cube and a purchase place is a plain sphere', () => {
  assert.equal(NODE_TYPES.seller.shape, 'box');
  assert.equal(NODE_TYPES.place.shape, 'sphere');
});

test('every declared shape is one js/nodes.js knows how to build', () => {
  // nodes.js falls back to a sphere for anything else; this says so out loud, so a new
  // shape in the vocabulary is a deliberate change on both sides.
  const shapes = new Set(['sphere', 'ring', 'octa', 'hub', 'cloud', 'box']);
  for (const [name, entry] of Object.entries(NODE_TYPES)) {
    assert.ok(shapes.has(entry.shape || 'sphere'), `${name}: ${entry.shape}`);
  }
  assert.ok(shapes.has(UNKNOWN_TYPE.shape || 'sphere'));
});
