// Pure-module tests for js/copy.js. No DOM, no fetch: run with
//   node --test "backend/tests/graph/js/**/*.test.mjs"
// from the repo root.
//
// This file intentionally does NOT import js/config.js (chrome tests import
// only the pure modules it owns, safe.js and copy.js). Instead the keys below
// are transcribed from config.js's VERDICT.*.copy and LINK_KIND_COPY tables —
// if either changes, update this list and copy.js together.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { t, hasKey, STRINGS, formatDate } from '../../../src/backend/graph/static/js/copy.js';

const COPY_JS_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../src/backend/graph/static/js/copy.js'
);

// Every copy key that backend/src/backend/graph/static/js/config.js resolves
// through `t()` — the VERDICT table's `.copy` fields and every distinct value
// in LINK_KIND_COPY.
const CONFIG_JS_KEYS = [
  'verdict.recall_match',
  'verdict.mismatch_found',
  'verdict.insufficient_evidence',
  'verdict.no_adverse_findings',
  'link.exact_lot',
  'link.all_lots_product',
  'link.ndc_in_description',
  'link.product_line_match',
  'link.lot_only_match',
  'link.lot_listed',
  'link.stated_manufacturer',
  'link.conflicts_with',
  'link.bought_from',
  'link.bought_in',
  'link.located_in',
  'link.also_reported',
];

test('copy has every key config.js references', () => {
  for (const key of CONFIG_JS_KEYS) {
    assert.equal(hasKey(key), true, `copy.js is missing the key "${key}"`);
  }
});

test('t() substitutes named variables into the template', () => {
  assert.equal(
    t('verdict.no_adverse_findings_tooltip', { index_date: '2026-09-19' }),
    'Not a confirmation of quality. Records current to 2026-09-19.'
  );
});

test('t() returns the literal string when no variables are given', () => {
  assert.equal(t('verdict.recall_match'), 'Recall match');
});

test('t() marks a missing key instead of throwing', () => {
  assert.equal(t('nonexistent.key'), '[[nonexistent.key]]');
});

test('the chip.demo copy matches the exact demo-chip sentence', () => {
  assert.equal(
    t('chip.demo'),
    'Demo scans — the recalls and lots are real regulator records'
  );
});

test('the no_adverse_findings verdict never contains a checkmark or tick word', () => {
  const value = STRINGS['verdict.no_adverse_findings'];
  assert.doesNotMatch(value.toLowerCase(), /\btick\b|\bcheck ?mark\b|✓/);
});

test('no risk chip string is "low risk"', () => {
  for (const value of Object.values(STRINGS)) {
    assert.doesNotMatch(value.toLowerCase(), /\blow risk\b/);
  }
});

test('formatDate drops the year for a date in the current year', () => {
  const thisYear = new Date().getFullYear();
  assert.equal(formatDate(`${thisYear}-09-18T09:12:00Z`), 'Sep 18');
});

test('formatDate keeps the year for a date in a past year', () => {
  assert.equal(formatDate('2025-01-05'), 'Jan 5, 2025');
});

test('formatDate never prints a timezone or a time of day', () => {
  const out = formatDate('2026-09-18T09:12:00Z');
  assert.doesNotMatch(out, /:|Z|GMT|UTC/);
});

test('formatDate passes through a value that is not an ISO date', () => {
  assert.equal(formatDate('current as of publication'), 'current as of publication');
});

test('formatDate returns an empty string for a missing date', () => {
  assert.equal(formatDate(null), '');
  assert.equal(formatDate(undefined), '');
  assert.equal(formatDate(''), '');
});

test('ui copy never uses an assurance word', () => {
  const source = readFileSync(COPY_JS_PATH, 'utf8');
  const banned = /\b(safe|genuine|verified|authentic)\b/i;
  const match = source.match(banned);
  assert.equal(match, null, `copy.js contains a banned assurance word: ${match && match[0]}`);
});

// A report is one person's unverified account, never evidence (graph/models.py
// REPORT_KINDS). No string anywhere in copy.js may accuse a seller of anything
// or claim an assurance the graph never gives.
test('no string ever accuses a seller or alarms about a crowd report', () => {
  const banned = /\b(fake|counterfeit|illegal|fraud|scam|guilty|unsafe|dangerous)\b/i;
  for (const [key, value] of Object.entries(STRINGS)) {
    const match = value.match(banned);
    assert.equal(match, null, `${key} contains a banned word: ${match && match[0]}`);
  }
});

test('the key panel names every colour on screen and matches the shared legend rows', () => {
  for (const key of [
    'key.title', 'key.pill', 'key.row_scan', 'key.row_alert', 'key.row_alert_sub',
    'key.row_uncorroborated', 'key.row_relation', 'key.row_report', 'key.row_selected',
  ]) {
    assert.equal(hasKey(key), true, `copy.js is missing the key "${key}"`);
  }
});

test('a crowd report link never claims to check or corroborate the seller', () => {
  // link.bought_from / bought_in / located_in / also_reported must read as
  // provenance, not as a finding: no "match", "corroborat*" or verdict word.
  const reportKeys = ['link.bought_from', 'link.bought_in', 'link.located_in', 'link.also_reported'];
  const findingish = /\b(match|corroborat\w*|recall|alert)\b/i;
  for (const key of reportKeys) {
    assert.doesNotMatch(STRINGS[key], findingish, key);
  }
});
