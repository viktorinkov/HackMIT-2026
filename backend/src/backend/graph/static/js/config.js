// Mirrors backend/src/backend/graph/models.py. Change one, change both.
// Pure data: no DOM, no three.js, so Node can import it in tests.

export const BG = '#131316';

// Purple = you, cool = identity, warm = regulatory risk. No green anywhere:
// green reads as assurance, and Peel never gives one.
export const NODE_TYPES = {
  scan:         { prefix: 'scan',    label: 'Your scans',     color: '#a882ff', r0: 5.0, shape: 'ring',   always: true },
  medicine:     { prefix: 'med',     label: 'Medicines',      color: '#9fb3ff', r0: 3.2, shape: 'sphere' },
  product:      { prefix: 'product', label: 'NDC products',   color: '#53dfdd', r0: 2.4, shape: 'sphere' },
  lot:          { prefix: 'lot',     label: 'Lots',           color: '#c9c9d1', r0: 2.2, shape: 'octa',   mono: true },
  manufacturer: { prefix: 'mfr',     label: 'Manufacturers',  color: '#5f8fd6', r0: 3.0, shape: 'sphere' },
  record:       { prefix: 'rec',     label: 'Recalls & alerts', color: '#9b8f86', r0: 2.6, shape: 'sphere', bySeverity: true },
  regulator:    { prefix: 'reg',     label: 'Regulators',     color: '#f2e9dc', r0: 4.2, shape: 'hub',    always: true },
  country:      { prefix: 'country', label: 'Countries',      color: '#7f8ea3', r0: 2.0, shape: 'sphere' },
  web_page:     { prefix: 'web',     label: 'Web pages',      color: '#8f8f9a', r0: 1.6, shape: 'sphere' },
  imprint:      { prefix: 'imprint', label: 'Imprints',       color: '#9fe8e6', r0: 1.8, shape: 'sphere', mono: true },
  pill_ref:     { prefix: 'pillref', label: 'Pill references', color: '#9fe8e6', r0: 1.6, shape: 'sphere' },
  topic:        { prefix: 'topic',   label: 'Reasons',        color: '#b9a48c', r0: 1.8, shape: 'sphere' },
  cluster:      { prefix: 'cluster', label: 'More',           color: '#6b6b76', r0: 1.2, shape: 'cloud' },
  // Crowd reports: where someone says they bought the medicine. Sand, and a box rather
  // than a sphere: a different kind of thing from the regulatory data, and never a risk colour.
  seller:       { prefix: 'seller',  label: 'Reported sellers', color: '#e0b98a', r0: 2.8, shape: 'box' },
  place:        { prefix: 'place',   label: 'Purchase places',  color: '#8fa3b8', r0: 2.0, shape: 'sphere' },
};
export const UNKNOWN_TYPE = { prefix: '?', label: 'Other', color: '#8f8f9a', r0: 1.6, shape: 'sphere' };

export const SEVERITY = {
  critical: { color: '#fb464c', k: 1.35, rank: 4, label: 'Critical' },
  high:     { color: '#e9973f', k: 1.15, rank: 3, label: 'High' },
  moderate: { color: '#e0c45c', k: 1.0,  rank: 2, label: 'Moderate' },
  unknown:  { color: '#9b8f86', k: 0.85, rank: 1, label: 'Unclassified' },
};

// Verdict colours the scan's ring and chip only. `no_adverse_findings` is slate
// with no tick: nothing found is not the same as nothing wrong.
export const VERDICT = {
  recall_match:          { color: '#fb464c', copy: 'verdict.recall_match' },
  mismatch_found:        { color: '#e9973f', copy: 'verdict.mismatch_found' },
  insufficient_evidence: { color: '#8a8a93', copy: 'verdict.insufficient_evidence' },
  no_adverse_findings:   { color: '#9aa7b8', copy: 'verdict.no_adverse_findings' },
};

// Link classes decide how an edge is drawn. Weak edges are faint, never dashed:
// the library rewrites line positions every tick without recomputing dash distances.
export const LINK_CLASS = { ALERT: 'alert', STRONG: 'strong', WEAK: 'weak', UNCORROBORATED: 'uncorroborated', CONFLICT: 'conflict', REPORT: 'report' };

// A person's own account of a purchase. Drawn as a thin dotted-looking sand line class,
// never red, never with particles.
export const REPORT_KINDS = new Set(['bought_from', 'bought_in', 'located_in', 'also_reported']);

export const UNCORROBORATED_KINDS = new Set([
  'lot_only_match', 'lot_listed', 'all_lots_sibling', 'product_line_match',
]);

export function linkClass(link) {
  if (link.alert) return LINK_CLASS.ALERT;
  if (link.kind === 'conflicts_with') return LINK_CLASS.CONFLICT;
  if (REPORT_KINDS.has(link.kind)) return LINK_CLASS.REPORT;
  if (UNCORROBORATED_KINDS.has(link.kind)) return LINK_CLASS.UNCORROBORATED;
  return link.strong ? LINK_CLASS.STRONG : LINK_CLASS.WEAK;
}

export const LINK_STYLE = {
  alert:          { color: null /* severity of the record end */, alpha: 0.8, width: 0.7, particles: 3, distance: 28 },
  strong:         { color: '#5a5a66', alpha: 0.85, width: 0, particles: 0, distance: 28 },
  weak:           { color: '#5a5a66', alpha: 0.30, width: 0, particles: 0, distance: 70 },
  uncorroborated: { color: '#7a6f55', alpha: 0.45, width: 0, particles: 0, distance: 55 },
  conflict:       { color: '#e9973f', alpha: 0.70, width: 0, particles: 0, distance: 45 },
  report:         { color: '#e0b98a', alpha: 0.60, width: 0, particles: 0, distance: 40 },
};
export const PARTICLE_COLOR = '#ffd7d9';
// Hover and selection are NEUTRAL. They used to be the same purple as "your scans", so a
// selected lot (purple ring, purple links) read as a second kind of finding next to a red
// recall path. Purple now means only "yours"; white means only "what you are looking at".
export const HIGHLIGHT_LINK = '#e9e9f2';
export const SELECTION_RING = '#ffffff';

// copy.js key for the caption shown when an edge of this kind is hovered.
export const LINK_KIND_COPY = {
  exact_lot: 'link.exact_lot',
  all_lots_product: 'link.all_lots_product',
  ndc_in_description: 'link.ndc_in_description',
  product_line_match: 'link.product_line_match',
  all_lots_sibling: 'link.product_line_match',
  lot_only_match: 'link.lot_only_match',
  lot_listed: 'link.lot_listed',
  stated_manufacturer: 'link.stated_manufacturer',
  conflicts_with: 'link.conflicts_with',
  bought_from: 'link.bought_from',
  bought_in: 'link.bought_in',
  located_in: 'link.located_in',
  also_reported: 'link.also_reported',
};

// Intensity targets for the hover / selection dimming.
export const INTENSITY = { lit: 1.0, rest: 0.7, second: 0.45, dim: 0.12, tauMs: 70 };

// A static tier is chosen once at boot (?tier=, else embed/touch => mobile).
// Bloom is off: with the library's composer the UnrealBloomPass output lifts the whole
// frame to grey and crushes node colours (seen in Chrome, independent of threshold,
// strength and MSAA). The additive halos carry the glow on their own.
export const TIERS = {
  desktop: { maxNodes: 600, maxLinks: 1200, labels: 40, pixelRatioCap: 2,   bloom: false, antialias: true,  fog: true,  particles: true,  halos: 'all',      nodeResolution: 12, drag: true },
  mobile:  { maxNodes: 150, maxLinks: 260,  labels: 14, pixelRatioCap: 1.5, bloom: false, antialias: false, fog: false, particles: true,  halos: 'personal', nodeResolution: 6,  drag: false },
};

export const SIM = {
  initial:     { warmupTicks: 40, cooldownTicks: 200, cooldownTime: 6000, alphaDecay: 0.035, velocityDecay: 0.45 },
  incremental: { warmupTicks: 0,  cooldownTicks: 90,  cooldownTime: 2500, alphaDecay: 0.05,  velocityDecay: 0.55 },
  charge: -60, chargeDistanceMax: 250,
};

export const POLL_MS = 5000;
export const API_TIMEOUT_MS = 8000;

// URL parameters the page understands. Anything else is ignored.
// `bridge=debug` installs a stub PeelBridge so the Flutter contract can be exercised in a desktop browser.
export const URL_PARAMS = ['device_id', 'demo', 'fixture', 'embed', 'tier', 'debug', 'focus', 'api', 'stress', 'universe', 'bridge'];

// Keys 1-4 fly to these nodes during the demo.
export const PRESENTER_STOPS = [
  'lot:D2402430',
  'lot:D2402999',
  'lot:Z400069',
  'lot:H02605',
];

export function typeOf(node) {
  return NODE_TYPES[node.type] || UNKNOWN_TYPE;
}

export function nodeColor(node) {
  const t = typeOf(node);
  if (t.bySeverity && node.severity && SEVERITY[node.severity]) return SEVERITY[node.severity].color;
  return t.color;
}

// r = r0 * sevK * (1 + 0.28 ln(1 + degree)), capped at 2.4 r0.
export function nodeRadius(node, degree = 0) {
  const t = typeOf(node);
  const k = node.severity && SEVERITY[node.severity] ? SEVERITY[node.severity].k : 1;
  return Math.min(t.r0 * k * (1 + 0.28 * Math.log(1 + degree)), 2.4 * t.r0);
}
