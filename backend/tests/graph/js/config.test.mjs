// Pure-module tests for js/config.js, the vocabulary the scene and the chrome share.
// Run with: node --test "backend/tests/graph/js/**/*.test.mjs" from the repo root.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BG, INTENSITY, LINK_CLASS, LINK_STYLE, NODE_TYPES, PRESENTER_STOPS, SEVERITY,
  SIM, TIERS, UNCORROBORATED_KINDS, UNKNOWN_TYPE, VERDICT,
  linkClass, nodeColor, nodeRadius, typeOf,
} from '../../../src/backend/graph/static/js/config.js';

const HEX = /^#[0-9a-f]{6}$/i;

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
