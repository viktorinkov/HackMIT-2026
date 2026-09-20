// The only state shared between the scene and the chrome.
//
// Everything above `store` is pure so Node can test it: no window, no document,
// no three.js, no ForceGraph3D at module scope.

import { SEVERITY, VERDICT } from './config.js';

const POSITION_KEYS = ['x', 'y', 'z', 'vx', 'vy', 'vz', 'fx', 'fy', 'fz', 'index'];

// Fields a later payload is allowed to overwrite on a node we already hold.
const NODE_DISPLAY_KEYS = [
  'type', 'label', 'sublabel', 'val', 'personal', 'backdrop', 'expandable',
  'count', 'date', 'url', 'verdict', 'risk_level', 'status', 'source_org',
  'freshness', 'demo', 'attrs',
];

const LINK_DISPLAY_KEYS = ['kind', 'strong', 'alert', 'weight', 'count', 'match_kind'];

const TIER_RANK = { match: 3, product: 2, context: 1 };

/** Endpoints arrive as ids, but the force engine rewrites them into node objects. */
export function endpointId(end) {
  if (end == null) return null;
  if (typeof end === 'string') return end;
  if (typeof end === 'object' && typeof end.id === 'string') return end.id;
  return null;
}

function severityRank(value) {
  const entry = SEVERITY[value];
  return entry ? entry.rank : 0;
}

/** Best tier wins, max severity wins; a record reached through two paths keeps the closer one. */
function mergePrecedence(existing, incoming) {
  let changed = false;
  const a = TIER_RANK[existing.match_tier] || 0;
  const b = TIER_RANK[incoming.match_tier] || 0;
  if (b > a) { existing.match_tier = incoming.match_tier; changed = true; }
  if (severityRank(incoming.severity) > severityRank(existing.severity)) {
    existing.severity = incoming.severity;
    changed = true;
  }
  const scans = new Set(existing.scan_ids || []);
  const before = scans.size;
  for (const id of incoming.scan_ids || []) scans.add(id);
  if (scans.size !== before) { existing.scan_ids = Array.from(scans); changed = true; }
  return changed;
}

/** True when every key of `next` already holds the same value on `prev`. */
function shallowContains(prev, next) {
  if (!prev || !next) return false;
  for (const key of Object.keys(next)) {
    if (prev[key] !== next[key]) return false;
  }
  return true;
}

function patch(target, source, keys) {
  let changed = false;
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(source, key)) continue;
    const next = source[key];
    if (next === undefined) continue;
    const prev = target[key];
    if (prev === next) continue;
    if (key === 'attrs') {
      // A fresh `{}` from JSON.parse is never identity-equal to the one we hold, so
      // comparing by identity here reported a change on every poll and reheated the
      // whole simulation to alpha 1 every five seconds.
      if (next && typeof next === 'object') {
        if (!prev || typeof prev !== 'object') { target.attrs = { ...next }; changed = true; }
        else if (!shallowContains(prev, next)) { Object.assign(prev, next); changed = true; }
      }
      continue;
    }
    target[key] = next;
    changed = true;
  }
  return changed;
}

/** Higher survives when the node budget bites. Scans are never evicted. */
export function nodePriority(node) {
  if (!node) return 0;
  if (node.type === 'scan') return 1000;
  if (node.personal) return 800;
  if (node.type === 'regulator') return 600;
  const sev = severityRank(node.severity);
  const base = node.backdrop ? 100 : 400;
  return base + sev * 10 + (node.type === 'cluster' ? -50 : 0);
}

function cloneIncomingNode(node) {
  const copy = {};
  for (const key of Object.keys(node)) {
    if (key.startsWith('__') || POSITION_KEYS.includes(key)) continue;
    copy[key] = node[key];
  }
  copy.scan_ids = Array.isArray(node.scan_ids) ? node.scan_ids.slice() : [];
  copy.attrs = node.attrs && typeof node.attrs === 'object' ? { ...node.attrs } : {};
  return copy;
}

function cloneIncomingLink(link, sourceId, targetId) {
  const copy = {};
  for (const key of Object.keys(link)) {
    if (key.startsWith('__')) continue;
    copy[key] = link[key];
  }
  copy.source = sourceId;
  copy.target = targetId;
  copy.scan_ids = Array.isArray(link.scan_ids) ? link.scan_ids.slice() : [];
  return copy;
}

/**
 * Fold `incoming` into `current` without losing object identity.
 *
 * `current` is `{nodes: Map, links: Map}` and is mutated in place: the node objects
 * the force engine is simulating must survive, or every merge restarts the layout
 * from a fresh explosion. Pure in the sense that matters for tests -- no globals.
 *
 * `changed` means the SHAPE of the graph moved: a node or link was added or removed.
 * A display-field update (label, verdict, severity, count, attrs, ...) is applied in
 * place and reported through `patchedNodes` / `patchedLinks` instead, because handing
 * the same 148 nodes back to `graphData()` reheats the simulation to alpha 1 and makes
 * the whole graph jiggle.
 *
 * opts: {maxNodes, maxLinks, protect: Set<id>}
 * returns {addedNodes, addedLinks, removed, changed, patched, patchedNodes,
 *          patchedLinks, rejected, evicted}
 */
export function mergeGraph(current, incoming, opts = {}) {
  const nodes = current.nodes;
  const links = current.links;
  const protect = opts.protect instanceof Set ? opts.protect : new Set();
  const maxNodes = Number.isFinite(opts.maxNodes) ? opts.maxNodes : Infinity;
  const maxLinks = Number.isFinite(opts.maxLinks) ? opts.maxLinks : Infinity;

  const addedNodes = [];
  const rejected = [];
  const evicted = [];
  const patchedNodes = [];
  const patchedLinks = [];

  const candidates = [];
  for (const node of incoming.nodes || []) {
    if (!node || typeof node.id !== 'string') continue;
    const existing = nodes.get(node.id);
    if (existing) {
      let touched = patch(existing, node, NODE_DISPLAY_KEYS);
      touched = mergePrecedence(existing, node) || touched;
      if (touched) patchedNodes.push(existing);
      continue;
    }
    candidates.push(node);
  }

  // Room first: evict the least valuable unprotected node before dropping new evidence.
  let room = maxNodes - nodes.size;
  if (candidates.length > room) {
    candidates.sort((a, b) => nodePriority(b) - nodePriority(a));
    const want = Math.min(candidates.length, maxNodes) - room;
    if (want > 0) {
      const evictable = [];
      for (const node of nodes.values()) {
        if (protect.has(node.id) || node.type === 'scan' || node.personal) continue;
        evictable.push(node);
      }
      evictable.sort((a, b) => nodePriority(a) - nodePriority(b));
      for (const node of evictable.slice(0, want)) {
        nodes.delete(node.id);
        evicted.push(node.id);
      }
      room = maxNodes - nodes.size;
    }
  }

  for (const node of candidates) {
    if (room <= 0) { rejected.push(node.id); continue; }
    const copy = cloneIncomingNode(node);
    nodes.set(copy.id, copy);
    addedNodes.push(copy);
    room -= 1;
  }

  const removed = evicted.slice();
  if (evicted.length) {
    for (const [id, link] of links) {
      const s = endpointId(link.source);
      const t = endpointId(link.target);
      if (!nodes.has(s) || !nodes.has(t)) { links.delete(id); removed.push(id); }
    }
  }

  const addedLinks = [];
  let linkRoom = maxLinks - links.size;
  for (const link of incoming.links || []) {
    if (!link || typeof link.id !== 'string') continue;
    // Deduping by id is what makes a reversed alert edge (the scene swaps the
    // endpoints so photons flow from the record toward your lot) merge as itself.
    const existing = links.get(link.id);
    if (existing) {
      if (patch(existing, link, LINK_DISPLAY_KEYS)) patchedLinks.push(existing);
      continue;
    }
    const sourceId = endpointId(link.source);
    const targetId = endpointId(link.target);
    if (!sourceId || !targetId) continue;
    if (!nodes.has(sourceId) || !nodes.has(targetId)) continue;
    if (linkRoom <= 0) { rejected.push(link.id); continue; }
    const copy = cloneIncomingLink(link, sourceId, targetId);
    links.set(copy.id, copy);
    addedLinks.push(copy);
    linkRoom -= 1;
  }

  return {
    addedNodes,
    addedLinks,
    removed,
    changed: addedNodes.length > 0 || addedLinks.length > 0 || removed.length > 0,
    patched: patchedNodes.length > 0 || patchedLinks.length > 0,
    patchedNodes,
    patchedLinks,
    rejected,
    evicted,
  };
}

/** Adjacency and degree, rebuilt from the link map. Pure. */
export function buildAdjacency(links) {
  const adjacency = new Map();
  const degree = new Map();
  const add = (a, b) => {
    let set = adjacency.get(a);
    if (!set) { set = new Set(); adjacency.set(a, set); }
    set.add(b);
  };
  for (const link of links.values()) {
    const s = endpointId(link.source);
    const t = endpointId(link.target);
    if (!s || !t) continue;
    add(s, t);
    add(t, s);
  }
  for (const [id, set] of adjacency) degree.set(id, set.size);
  return { adjacency, degree };
}

const VERDICT_ORDER = ['recall_match', 'mismatch_found', 'insufficient_evidence', 'no_adverse_findings'];

/** Scans by verdict severity, then newest first. Pure. */
export function sortScansByAttention(scans) {
  return scans.slice().sort((a, b) => {
    const av = VERDICT_ORDER.indexOf(a.verdict);
    const bv = VERDICT_ORDER.indexOf(b.verdict);
    const ai = av === -1 ? VERDICT_ORDER.length : av;
    const bi = bv === -1 ? VERDICT_ORDER.length : bv;
    if (ai !== bi) return ai - bi;
    return String(b.date || '').localeCompare(String(a.date || ''));
  });
}

export function verdictColor(node) {
  const entry = node && node.verdict ? VERDICT[node.verdict] : null;
  return entry ? entry.color : null;
}

class Store extends EventTarget {
  constructor() {
    super();
    this.state = {
      nodes: new Map(),
      links: new Map(),
      adjacency: new Map(),
      degree: new Map(),
      selectedId: null,
      hoveredId: null,
      highlight: new Set(),
      hiddenTypes: new Set(),
      view: 'local',
      meta: null,
      deviceId: null,
      demo: false,
      tier: 'desktop',
      embed: false,
    };
    this.budget = { maxNodes: Infinity, maxLinks: Infinity };
  }

  emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail }));
  }

  configure({ deviceId, demo, tier, embed, budget } = {}) {
    if (deviceId !== undefined) this.state.deviceId = deviceId;
    if (demo !== undefined) this.state.demo = !!demo;
    if (tier !== undefined) this.state.tier = tier;
    if (embed !== undefined) this.state.embed = !!embed;
    if (budget) this.budget = budget;
  }

  reindex() {
    const { adjacency, degree } = buildAdjacency(this.state.links);
    this.state.adjacency = adjacency;
    this.state.degree = degree;
  }

  protectedIds() {
    const keep = new Set();
    const { selectedId, nodes } = this.state;
    for (const node of nodes.values()) if (node.type === 'scan') keep.add(node.id);
    if (selectedId) {
      keep.add(selectedId);
      for (const id of this.neighbours(selectedId)) keep.add(id);
    }
    return keep;
  }

  setGraph(response) {
    this.state.nodes = new Map();
    this.state.links = new Map();
    const result = mergeGraph(this.state, response || { nodes: [], links: [] }, {
      ...this.budget,
      protect: new Set(),
    });
    if (response && response.meta) this.state.meta = response.meta;
    this.reindex();
    this.emit('graph', {
      addedNodes: result.addedNodes,
      addedLinks: result.addedLinks,
      removed: result.removed,
      patchedNodes: result.patchedNodes,
      patchedLinks: result.patchedLinks,
      structural: true,
      replaced: true,
    });
    return result;
  }

  merge(graphLike) {
    const result = mergeGraph(this.state, graphLike || { nodes: [], links: [] }, {
      ...this.budget,
      protect: this.protectedIds(),
    });
    if (graphLike && graphLike.meta) this.state.meta = graphLike.meta;
    if (result.changed) this.reindex();
    if (result.changed || result.patched) {
      // `structural` is what tells the scene whether graphData() has to be called.
      this.emit('graph', {
        addedNodes: result.addedNodes,
        addedLinks: result.addedLinks,
        removed: result.removed,
        patchedNodes: result.patchedNodes,
        patchedLinks: result.patchedLinks,
        structural: result.changed,
        replaced: false,
      });
    }
    return result;
  }

  /** The Flutter bridge supplies the device id after the page has already booted. */
  setDevice(deviceId) {
    const next = deviceId || null;
    if (this.state.deviceId === next) return;
    this.state.deviceId = next;
    this.emit('device', { deviceId: next });
  }

  select(id) {
    const next = id || null;
    if (this.state.selectedId === next) return;
    this.state.selectedId = next;
    this.emit('select', { id: next, node: next ? this.state.nodes.get(next) || null : null });
  }

  hover(id) {
    const next = id || null;
    if (this.state.hoveredId === next) return;
    this.state.hoveredId = next;
    this.emit('hover', { id: next });
  }

  setHighlight(ids) {
    const next = new Set(ids || []);
    const prev = this.state.highlight;
    if (next.size === prev.size) {
      let same = true;
      for (const id of next) if (!prev.has(id)) { same = false; break; }
      if (same) return;
    }
    this.state.highlight = next;
    this.emit('highlight', { ids: next });
  }

  toggleType(type, visible) {
    const hidden = this.state.hiddenTypes;
    const wasHidden = hidden.has(type);
    if (visible === undefined) {
      if (wasHidden) hidden.delete(type); else hidden.add(type);
    } else if (visible) {
      if (!wasHidden) return;
      hidden.delete(type);
    } else {
      if (wasHidden) return;
      hidden.add(type);
    }
    this.emit('filter', { hiddenTypes: hidden });
  }

  setView(view) {
    if (this.state.view === view) return;
    this.state.view = view;
    this.emit('view', { view });
  }

  setStatus(kind, message) {
    this.emit('status', { kind, message: message || '' });
  }

  neighbours(id) {
    return this.state.adjacency.get(id) || new Set();
  }

  linksOf(id) {
    const out = [];
    for (const link of this.state.links.values()) {
      if (endpointId(link.source) === id || endpointId(link.target) === id) out.push(link);
    }
    return out;
  }

  scansByAttention() {
    const scans = [];
    for (const node of this.state.nodes.values()) if (node.type === 'scan') scans.push(node);
    return sortScansByAttention(scans);
  }
}

export const store = new Store();
export default store;
