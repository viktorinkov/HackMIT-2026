// Test for the pure hit-to-row mapping in js/panels/search.js. The function
// under test never touches `document`/`window` (only code inside
// `mountSearch()` does, and that never runs at import time), so importing
// the module in Node is safe.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { rowsFromSearchResponse } from '../../../src/backend/graph/static/js/panels/search.js';

const RESPONSE = {
  query: 'subpotent thyroid tablets',
  nodes: [
    { id: 'rec:fda-enf-D-0785-2026', type: 'record', label: 'Levothyroxine Sodium recall', sublabel: 'FDA · Class II' },
    { id: 'topic:subpotent', type: 'topic', label: 'Subpotent drug', sublabel: 'Reason' },
  ],
  links: [],
  hits: [
    { node_id: 'rec:fda-enf-D-0785-2026', score: 9.1, highlight: 'subpotent thyroid tablets recalled' },
    { node_id: 'topic:subpotent', score: 4.2, highlight: null },
    { node_id: 'lot:D2402430', score: 3.0, highlight: null },
  ],
  highlight: ['scan:demo-1'],
  meta: { scans: 1, generated_at: null, source: 'live', demo: false, truncated: false },
};

test('rowsFromSearchResponse resolves each hit to its node label, never the raw id', () => {
  const rows = rowsFromSearchResponse(RESPONSE);
  assert.equal(rows[0].id, 'rec:fda-enf-D-0785-2026');
  assert.equal(rows[0].label, 'Levothyroxine Sodium recall');
  assert.equal(rows[1].label, 'Subpotent drug');
});

test('rowsFromSearchResponse carries the type through from the matching node', () => {
  const rows = rowsFromSearchResponse(RESPONSE);
  assert.equal(rows[0].type, 'record');
  assert.equal(rows[1].type, 'topic');
});

test('rowsFromSearchResponse prefers the hit highlight snippet for detail text', () => {
  const rows = rowsFromSearchResponse(RESPONSE);
  assert.equal(rows[0].detail, 'subpotent thyroid tablets recalled');
});

test('rowsFromSearchResponse falls back to the node sublabel when a hit has no highlight', () => {
  const rows = rowsFromSearchResponse(RESPONSE);
  assert.equal(rows[1].detail, 'Reason');
});

test('rowsFromSearchResponse falls back to the raw id only when no node matches the hit', () => {
  const rows = rowsFromSearchResponse(RESPONSE);
  const orphan = rows.find((r) => r.id === 'lot:D2402430');
  assert.equal(orphan.label, 'lot:D2402430');
  assert.equal(orphan.type, undefined);
  assert.equal(orphan.detail, '');
});

test('rowsFromSearchResponse preserves hit order', () => {
  const rows = rowsFromSearchResponse(RESPONSE);
  assert.deepEqual(rows.map((r) => r.id), ['rec:fda-enf-D-0785-2026', 'topic:subpotent', 'lot:D2402430']);
});

test('rowsFromSearchResponse returns an empty array for a response with no hits', () => {
  assert.deepEqual(rowsFromSearchResponse({ nodes: [], hits: [] }), []);
});

test('rowsFromSearchResponse tolerates a missing nodes or hits array', () => {
  assert.deepEqual(rowsFromSearchResponse({}), []);
  assert.deepEqual(rowsFromSearchResponse(null), []);
});
