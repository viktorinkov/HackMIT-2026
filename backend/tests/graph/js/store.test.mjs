// Pure-module tests for js/store.js. No DOM, no three.js: run with
//   node --test "backend/tests/graph/js/**/*.test.mjs"
// from the repo root.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAdjacency, endpointId, mergeGraph, nodePriority, sortScansByAttention,
} from '../../../src/backend/graph/static/js/store.js';

function empty() {
  return { nodes: new Map(), links: new Map() };
}

function node(id, extra = {}) {
  return { id, type: 'record', label: id, ...extra };
}

function link(source, kind, target, extra = {}) {
  return { id: `${source}>${kind}>${target}`, source, target, kind, ...extra };
}

test('an endpoint given as an id reads back as that id', () => {
  assert.equal(endpointId('lot:A'), 'lot:A');
});

test('an endpoint the force engine rewrote into a node object still reads back as its id', () => {
  assert.equal(endpointId({ id: 'lot:A', x: 1, y: 2 }), 'lot:A');
});

test('an endpoint that is neither an id nor a node reads back as null', () => {
  assert.equal(endpointId(undefined), null);
  assert.equal(endpointId(42), null);
});

test('merging into an empty graph reports every node and link as added', () => {
  const current = empty();
  const result = mergeGraph(current, {
    nodes: [node('lot:A'), node('rec:B')],
    links: [link('lot:A', 'exact_lot', 'rec:B')],
  });
  assert.equal(result.addedNodes.length, 2);
  assert.equal(result.addedLinks.length, 1);
  assert.equal(result.changed, true);
});

test('merging the same payload twice changes nothing the second time', () => {
  const current = empty();
  const payload = {
    nodes: [node('lot:A'), node('rec:B')],
    links: [link('lot:A', 'exact_lot', 'rec:B')],
  };
  mergeGraph(current, payload);
  const again = mergeGraph(current, {
    nodes: [node('lot:A'), node('rec:B')],
    links: [link('lot:A', 'exact_lot', 'rec:B')],
  });
  assert.equal(again.changed, false);
  assert.equal(again.addedNodes.length, 0);
  assert.equal(again.addedLinks.length, 0);
});

test('merging an identical live response twice reports no change', () => {
  // The poll re-parses the same JSON every five seconds: every array and object in it
  // is a fresh instance, so nothing here may be compared by identity.
  const payload = () => ({
    nodes: [
      {
        id: 'scan:s1',
        type: 'scan',
        label: 'Levothyroxine 50 mcg',
        verdict: 'recall_match',
        status: 'complete',
        scan_ids: ['s1'],
        attrs: { lot: 'D2402430', source_org: 'openFDA' },
      },
      {
        id: 'rec:r1',
        type: 'record',
        label: 'Class II recall',
        severity: 'critical',
        match_tier: 'match',
        scan_ids: ['s1'],
        attrs: {},
      },
    ],
    links: [{
      id: 'lot:A>exact_lot>rec:r1',
      source: 'scan:s1',
      target: 'rec:r1',
      kind: 'exact_lot',
      alert: true,
      scan_ids: ['s1'],
    }],
  });
  const current = empty();
  mergeGraph(current, payload());
  const again = mergeGraph(current, payload());
  assert.equal(again.changed, false);
  assert.equal(again.patched, false);
  assert.equal(again.patchedNodes.length, 0);
  assert.equal(again.patchedLinks.length, 0);
});

test('a verdict change patches the node without reporting a structural change', () => {
  const current = empty();
  mergeGraph(current, {
    nodes: [node('scan:s1', { type: 'scan', verdict: 'insufficient_evidence' })],
    links: [],
  });
  const result = mergeGraph(current, {
    nodes: [node('scan:s1', { type: 'scan', verdict: 'recall_match' })],
    links: [],
  });
  assert.equal(result.changed, false);
  assert.equal(result.patched, true);
  assert.equal(result.patchedNodes.length, 1);
  assert.equal(result.patchedNodes[0], current.nodes.get('scan:s1'));
  assert.equal(current.nodes.get('scan:s1').verdict, 'recall_match');
});

test('a new attrs key patches the node but an identical attrs object does not', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('rec:r1', { attrs: { a: 1 } })], links: [] });
  assert.equal(mergeGraph(current, { nodes: [node('rec:r1', { attrs: { a: 1 } })], links: [] }).patched, false);
  assert.equal(mergeGraph(current, { nodes: [node('rec:r1', { attrs: { a: 2 } })], links: [] }).patched, true);
});

test('a reversed alert link is recognised as the same link', () => {
  // The scene swaps an alert edge's endpoints so photons flow from the record toward
  // the user's lot. The id still encodes the stored direction, which is what makes
  // the next poll merge it as itself instead of adding a duplicate.
  const current = empty();
  mergeGraph(current, {
    nodes: [node('lot:A', { type: 'lot' }), node('rec:B')],
    links: [link('lot:A', 'exact_lot', 'rec:B', { alert: true })],
  });
  const stored = current.links.get('lot:A>exact_lot>rec:B');
  stored.source = current.nodes.get('rec:B');
  stored.target = current.nodes.get('lot:A');
  stored.__reversed = true;

  const result = mergeGraph(current, {
    nodes: [],
    links: [link('lot:A', 'exact_lot', 'rec:B', { alert: true })],
  });
  assert.equal(result.addedLinks.length, 0);
  assert.equal(result.changed, false);
  assert.equal(current.links.size, 1);
  assert.equal(endpointId(current.links.get('lot:A>exact_lot>rec:B').source), 'rec:B');
});

test('an added node is a structural change but a patched one is not', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('rec:a')], links: [] });
  assert.equal(mergeGraph(current, { nodes: [node('rec:b')], links: [] }).changed, true);
  assert.equal(mergeGraph(current, { nodes: [node('rec:b', { label: 'new' })], links: [] }).changed, false);
});

test('a merge keeps the existing node object so simulation coordinates survive', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('lot:A')], links: [] });
  const held = current.nodes.get('lot:A');
  held.x = 11;
  held.y = 12;
  held.z = 13;
  held.vx = 0.5;

  mergeGraph(current, { nodes: [node('lot:A', { label: 'renamed' })], links: [] });

  assert.equal(current.nodes.get('lot:A'), held);
  assert.equal(held.x, 11);
  assert.equal(held.y, 12);
  assert.equal(held.z, 13);
  assert.equal(held.vx, 0.5);
  assert.equal(held.label, 'renamed');
});

test('an incoming payload never overwrites coordinates the engine owns', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('lot:A')], links: [] });
  const held = current.nodes.get('lot:A');
  held.x = 7;
  mergeGraph(current, { nodes: [node('lot:A', { x: 999, fx: 999 })], links: [] });
  assert.equal(held.x, 7);
  assert.equal(held.fx, undefined);
});

test('a link whose endpoints arrive as node objects is accepted', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('lot:A'), node('rec:B')], links: [] });
  const result = mergeGraph(current, {
    nodes: [],
    links: [{
      id: 'lot:A>exact_lot>rec:B',
      source: { id: 'lot:A' },
      target: { id: 'rec:B' },
      kind: 'exact_lot',
    }],
  });
  assert.equal(result.addedLinks.length, 1);
  assert.equal(endpointId(current.links.get('lot:A>exact_lot>rec:B').source), 'lot:A');
});

test('a link with a missing endpoint is dropped rather than added', () => {
  const current = empty();
  const result = mergeGraph(current, {
    nodes: [node('lot:A')],
    links: [link('lot:A', 'exact_lot', 'rec:missing')],
  });
  assert.equal(result.addedLinks.length, 0);
  assert.equal(current.links.size, 0);
});

test('links are deduped by id even when the same edge arrives twice in one payload', () => {
  const current = empty();
  const result = mergeGraph(current, {
    nodes: [node('lot:A'), node('rec:B')],
    links: [link('lot:A', 'exact_lot', 'rec:B'), link('lot:A', 'exact_lot', 'rec:B')],
  });
  assert.equal(result.addedLinks.length, 1);
  assert.equal(current.links.size, 1);
});

test('the closer match tier wins when the same record arrives twice', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('rec:B', { match_tier: 'context' })], links: [] });
  mergeGraph(current, { nodes: [node('rec:B', { match_tier: 'match' })], links: [] });
  mergeGraph(current, { nodes: [node('rec:B', { match_tier: 'product' })], links: [] });
  assert.equal(current.nodes.get('rec:B').match_tier, 'match');
});

test('the higher severity wins when the same record arrives twice', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('rec:B', { severity: 'moderate' })], links: [] });
  mergeGraph(current, { nodes: [node('rec:B', { severity: 'critical' })], links: [] });
  mergeGraph(current, { nodes: [node('rec:B', { severity: 'unknown' })], links: [] });
  assert.equal(current.nodes.get('rec:B').severity, 'critical');
});

test('scan ids from two payloads are unioned onto one node', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('lot:A', { scan_ids: ['s1'] })], links: [] });
  mergeGraph(current, { nodes: [node('lot:A', { scan_ids: ['s2', 's1'] })], links: [] });
  assert.deepEqual(current.nodes.get('lot:A').scan_ids.sort(), ['s1', 's2']);
});

test('the node budget admits the most important nodes and rejects the rest', () => {
  const current = empty();
  const incoming = {
    nodes: [
      node('web:1', { type: 'web_page' }),
      node('scan:1', { type: 'scan' }),
      node('rec:1', { severity: 'critical' }),
      node('web:2', { type: 'web_page' }),
    ],
    links: [],
  };
  const result = mergeGraph(current, incoming, { maxNodes: 2 });
  assert.equal(current.nodes.size, 2);
  assert.equal(current.nodes.has('scan:1'), true);
  assert.equal(current.nodes.has('rec:1'), true);
  assert.equal(result.rejected.length, 2);
});

test('the link budget stops new links without touching the ones already held', () => {
  const current = empty();
  mergeGraph(current, {
    nodes: [node('a'), node('b'), node('c')],
    links: [link('a', 'related', 'b')],
  });
  const result = mergeGraph(current, { nodes: [], links: [link('b', 'related', 'c')] }, { maxLinks: 1 });
  assert.equal(result.addedLinks.length, 0);
  assert.equal(current.links.size, 1);
});

test('a scan is never evicted to make room for anything else', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('scan:1', { type: 'scan' }), node('web:1', { type: 'web_page' })], links: [] });
  mergeGraph(current, { nodes: [node('rec:new', { severity: 'critical' })], links: [] }, { maxNodes: 2 });
  assert.equal(current.nodes.has('scan:1'), true);
  assert.equal(current.nodes.has('rec:new'), true);
  assert.equal(current.nodes.has('web:1'), false);
});

test('a protected id survives eviction even when it is low priority', () => {
  const current = empty();
  mergeGraph(current, { nodes: [node('web:1', { type: 'web_page' }), node('web:2', { type: 'web_page' })], links: [] });
  mergeGraph(
    current,
    { nodes: [node('rec:new', { severity: 'critical' })], links: [] },
    { maxNodes: 2, protect: new Set(['web:1']) },
  );
  assert.equal(current.nodes.has('web:1'), true);
  assert.equal(current.nodes.has('web:2'), false);
});

test('evicting a node also drops the links that pointed at it', () => {
  const current = empty();
  mergeGraph(current, {
    nodes: [node('web:1', { type: 'web_page' }), node('web:2', { type: 'web_page' })],
    links: [link('web:1', 'web_related', 'web:2')],
  });
  mergeGraph(current, { nodes: [node('scan:1', { type: 'scan' })], links: [] }, { maxNodes: 2 });
  assert.equal(current.links.size, 0);
});

test('a scan outranks a personal node, which outranks a plain record', () => {
  assert.ok(nodePriority(node('scan:1', { type: 'scan' })) > nodePriority(node('lot:1', { personal: true })));
  assert.ok(nodePriority(node('lot:1', { personal: true })) > nodePriority(node('rec:1')));
});

test('a backdrop node ranks below anything from the device', () => {
  assert.ok(nodePriority(node('rec:1', { backdrop: true })) < nodePriority(node('rec:2')));
});

test('adjacency is undirected and degree counts both directions', () => {
  const links = new Map();
  for (const l of [link('a', 'k', 'b'), link('b', 'k', 'c')]) links.set(l.id, l);
  const { adjacency, degree } = buildAdjacency(links);
  assert.deepEqual([...adjacency.get('b')].sort(), ['a', 'c']);
  assert.equal(degree.get('b'), 2);
  assert.equal(degree.get('a'), 1);
});

test('scans sort by verdict severity first and by date within a verdict', () => {
  const scans = [
    { id: 'scan:3', verdict: 'no_adverse_findings', date: '2026-09-18' },
    { id: 'scan:1', verdict: 'recall_match', date: '2026-09-10' },
    { id: 'scan:2', verdict: 'recall_match', date: '2026-09-12' },
    { id: 'scan:4', verdict: 'mismatch_found', date: '2026-01-01' },
  ];
  assert.deepEqual(sortScansByAttention(scans).map((s) => s.id), ['scan:2', 'scan:1', 'scan:4', 'scan:3']);
});

test('sorting scans leaves the caller array untouched', () => {
  const scans = [
    { id: 'scan:1', verdict: 'no_adverse_findings', date: '2026-01-01' },
    { id: 'scan:2', verdict: 'recall_match', date: '2026-01-02' },
  ];
  sortScansByAttention(scans);
  assert.equal(scans[0].id, 'scan:1');
});
