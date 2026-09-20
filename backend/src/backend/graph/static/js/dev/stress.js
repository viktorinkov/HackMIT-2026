// `?stress=N` swaps in a generated graph of N nodes so the FPS and draw-call
// numbers in the HUD come from something the real data will never exceed.
// Deterministic: the same N always produces the same graph.

const TYPES = ['record', 'lot', 'product', 'medicine', 'manufacturer', 'web_page', 'country', 'topic'];
const SEVERITIES = ['critical', 'high', 'moderate', 'unknown'];

function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export function stressGraph(count) {
  const n = Math.max(10, Math.min(3000, Math.round(count) || 300));
  const rnd = rng(0x5eed1234);
  const nodes = [];
  const links = [];

  const scans = Math.max(2, Math.round(n / 40));
  for (let i = 0; i < scans; i += 1) {
    nodes.push({
      id: `scan:stress-${i}`, type: 'scan', label: `Stress scan ${i + 1}`,
      personal: true, demo: true, val: 3, status: 'complete',
      verdict: i % 3 === 0 ? 'recall_match' : 'no_adverse_findings',
      date: `2026-09-${String((i % 27) + 1).padStart(2, '0')}`,
      scan_ids: [`stress-${i}`], attrs: {},
    });
  }
  nodes.push({ id: 'reg:fda', type: 'regulator', label: 'FDA', demo: true, val: 3, attrs: {} });
  nodes.push({ id: 'reg:who', type: 'regulator', label: 'WHO', demo: true, val: 3, attrs: {} });

  while (nodes.length < n) {
    const i = nodes.length;
    const type = TYPES[Math.floor(rnd() * TYPES.length)];
    const node = {
      id: `${type === 'record' ? 'rec' : type.slice(0, 4)}:stress-${i}`,
      type,
      label: `${type} ${i}`,
      demo: true,
      val: 1 + rnd() * 2,
      attrs: {},
    };
    if (type === 'record') {
      node.severity = SEVERITIES[Math.floor(rnd() * SEVERITIES.length)];
      node.source_org = rnd() > 0.5 ? 'openFDA' : 'WHO';
    }
    nodes.push(node);
  }

  const byId = nodes.map((node) => node.id);
  for (let i = scans + 2; i < nodes.length; i += 1) {
    const anchor = byId[Math.floor(rnd() * (i - 1))];
    const alert = nodes[i].type === 'record' && rnd() < 0.05;
    links.push({
      id: `${anchor}>related>${byId[i]}`,
      source: anchor,
      target: byId[i],
      kind: alert ? 'exact_lot' : (rnd() < 0.3 ? 'lot_only_match' : 'related'),
      strong: rnd() < 0.35,
      alert,
      weight: rnd(),
      count: 1,
      scan_ids: [],
    });
  }
  // A second pass gives the layout a few cross edges, which is what actually costs.
  const extra = Math.round(nodes.length * 0.8);
  for (let i = 0; i < extra; i += 1) {
    const a = byId[Math.floor(rnd() * byId.length)];
    const b = byId[Math.floor(rnd() * byId.length)];
    if (a === b) continue;
    const id = `${a}>web_related>${b}`;
    links.push({ id, source: a, target: b, kind: 'web_related', strong: false, alert: false, weight: 0.2, count: 1, scan_ids: [] });
  }

  return {
    nodes,
    links,
    meta: { scans, source: 'demo', demo: true, truncated: false, counts: {}, timeline: [] },
  };
}

export default stressGraph;
