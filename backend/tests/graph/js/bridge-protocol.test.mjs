// Pure-module tests for js/bridge-protocol.js. No DOM/window: run with
//   node --test "backend/tests/graph/js/**/*.test.mjs"
// from the repo root.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  OUTBOUND_TYPES,
  INBOUND_TYPES,
  DETENTS,
  buildOutbound,
  parseIncoming,
  decideBack,
} from '../../../src/backend/graph/static/js/bridge-protocol.js';

test('the inbound allow-list is exactly set_device, focus_node, and back', () => {
  assert.deepEqual([...INBOUND_TYPES].sort(), ['back', 'focus_node', 'set_device']);
});

test('buildOutbound stamps v:1 on every allow-listed message', () => {
  for (const type of OUTBOUND_TYPES) {
    const message = buildOutbound(type, { extra: 1 });
    assert.equal(message.v, 1);
    assert.equal(message.type, type);
    assert.equal(message.extra, 1);
  }
});

test('buildOutbound refuses a type that is not on the outbound allow-list', () => {
  assert.equal(buildOutbound('set_device', { device_id: 'x' }), null);
  assert.equal(buildOutbound('totally_made_up', {}), null);
});

test('parseIncoming accepts a JSON string', () => {
  const result = parseIncoming(JSON.stringify({ type: 'set_device', device_id: 'peel-graph-demo' }));
  assert.deepEqual(result, { type: 'set_device', payload: { device_id: 'peel-graph-demo' } });
});

test('parseIncoming accepts an already-parsed object', () => {
  const result = parseIncoming({ type: 'focus_node', node_id: 'lot:D2402430', expand: true });
  assert.deepEqual(result, { type: 'focus_node', payload: { node_id: 'lot:D2402430', expand: true } });
});

test('parseIncoming strips the v field out of the returned payload', () => {
  const result = parseIncoming({ v: 1, type: 'back' });
  assert.deepEqual(result, { type: 'back', payload: {} });
});

test('parseIncoming rejects a type that is not on the inbound allow-list', () => {
  assert.equal(parseIncoming({ type: 'ready' }), null); // ready is outbound-only
  assert.equal(parseIncoming({ type: 'evil_rpc_call' }), null);
});

test('parseIncoming rejects malformed JSON instead of throwing', () => {
  assert.equal(parseIncoming('{not json'), null);
});

test('parseIncoming rejects null, arrays, and non-object primitives', () => {
  assert.equal(parseIncoming(null), null);
  assert.equal(parseIncoming(undefined), null);
  assert.equal(parseIncoming(['set_device']), null);
  assert.equal(parseIncoming(42), null);
  assert.equal(parseIncoming('"just a string"'), null);
});

test('decideBack closes the search modal first, even with a sheet and a selection open', () => {
  const result = decideBack({ searchOpen: true, detent: 'full', detents: DETENTS, hasSelection: true });
  assert.deepEqual(result, { action: 'close_search', handled: true });
});

test('decideBack collapses the sheet one detent when the modal is closed', () => {
  const result = decideBack({ searchOpen: false, detent: 'full', detents: DETENTS, hasSelection: true });
  assert.deepEqual(result, { action: 'collapse_sheet', handled: true, nextDetent: 'half' });
});

test('decideBack collapses from half to peek', () => {
  const result = decideBack({ searchOpen: false, detent: 'half', detents: DETENTS, hasSelection: true });
  assert.equal(result.nextDetent, 'peek');
});

test('decideBack clears the selection once the sheet is already at its lowest detent', () => {
  const result = decideBack({ searchOpen: false, detent: 'peek', detents: DETENTS, hasSelection: true });
  assert.deepEqual(result, { action: 'clear_selection', handled: true });
});

test('decideBack reports unhandled when there is nothing left to do', () => {
  const result = decideBack({ searchOpen: false, detent: 'peek', detents: DETENTS, hasSelection: false });
  assert.deepEqual(result, { action: 'none', handled: false });
});

test('decideBack clears the selection when there is no sheet at all', () => {
  const result = decideBack({ searchOpen: false, detent: null, detents: DETENTS, hasSelection: true });
  assert.deepEqual(result, { action: 'clear_selection', handled: true });
});
