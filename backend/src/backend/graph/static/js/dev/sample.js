// A hand-written 14-node graph in the contract's shape, used only when the real
// API client is not on disk yet. Every node carries demo:true, so the page shows
// the demo chip exactly as it would for seeded scans.

export const SAMPLE_GRAPH = {
  nodes: [
    {
      id: 'scan:s-levo', type: 'scan', label: 'Levothyroxine 50 mcg',
      sublabel: 'scanned 12 Sep', personal: true, demo: true, expandable: true,
      verdict: 'recall_match', risk_level: 'high', status: 'complete',
      date: '2026-09-12', val: 3, scan_ids: ['s-levo'], attrs: {},
    },
    {
      id: 'scan:s-chlor', type: 'scan', label: 'Chlorpromazine 100 mg',
      sublabel: 'scanned 14 Sep', personal: true, demo: true, expandable: true,
      verdict: 'insufficient_evidence', status: 'partial',
      date: '2026-09-14', val: 3, scan_ids: ['s-chlor'], attrs: {},
    },
    {
      id: 'med:levothyroxine', type: 'medicine', label: 'Levothyroxine sodium',
      personal: true, demo: true, val: 2, attrs: {},
    },
    {
      id: 'product:0378-1805', type: 'product', label: 'NDC 0378-1805',
      sublabel: 'Levothyroxine sodium tablets', personal: true, demo: true,
      expandable: true, val: 2, attrs: {},
    },
    {
      id: 'lot:D2402430', type: 'lot', label: 'D2402430', personal: true, demo: true,
      expandable: true, match_tier: 'match', val: 2, scan_ids: ['s-levo'], attrs: {},
    },
    {
      id: 'lot:D2402999', type: 'lot', label: 'D2402999', personal: true, demo: true,
      sublabel: 'same product line', val: 1.6, scan_ids: ['s-levo'], attrs: {},
    },
    {
      id: 'lot:Z400069', type: 'lot', label: 'Z400069', personal: true, demo: true,
      expandable: true, val: 1.6, scan_ids: ['s-chlor'], attrs: {},
    },
    {
      id: 'mfr:mylan', type: 'manufacturer', label: 'Mylan Pharmaceuticals',
      demo: true, expandable: true, val: 2, attrs: {},
    },
    {
      id: 'rec:fda-d-2402', type: 'record', label: 'Class II recall D-2402-2026',
      sublabel: 'subpotent tablets', demo: true, expandable: true,
      severity: 'critical', match_tier: 'match', source_org: 'openFDA',
      date: '2026-08-30', val: 3, scan_ids: ['s-levo'], attrs: {},
    },
    {
      id: 'rec:who-2024-6', type: 'record', label: 'WHO alert 2026/6',
      sublabel: 'falsified chlorpromazine', demo: true, expandable: true,
      severity: 'high', match_tier: 'context', source_org: 'WHO',
      date: '2026-06-04', val: 2.4, scan_ids: ['s-chlor'], attrs: {},
    },
    { id: 'reg:fda', type: 'regulator', label: 'FDA', demo: true, val: 3, attrs: {} },
    { id: 'reg:who', type: 'regulator', label: 'WHO', demo: true, val: 3, attrs: {} },
    { id: 'country:ng', type: 'country', label: 'Nigeria', demo: true, val: 1.4, attrs: {} },
    {
      id: 'cluster:fda-more', type: 'cluster', label: '+243 recalls', demo: true,
      expandable: true, count: 243, val: 1.2, attrs: {},
    },
  ],
  links: [
    { id: 'scan:s-levo>labelled_lot>lot:D2402430', source: 'scan:s-levo', target: 'lot:D2402430', kind: 'labelled_lot', strong: true, weight: 1, scan_ids: ['s-levo'] },
    { id: 'scan:s-levo>names>med:levothyroxine', source: 'scan:s-levo', target: 'med:levothyroxine', kind: 'names', strong: true, weight: 0.8, scan_ids: ['s-levo'] },
    { id: 'scan:s-levo>labelled_ndc>product:0378-1805', source: 'scan:s-levo', target: 'product:0378-1805', kind: 'labelled_ndc', strong: true, weight: 0.8, scan_ids: ['s-levo'] },
    { id: 'scan:s-levo>labelled_maker>mfr:mylan', source: 'scan:s-levo', target: 'mfr:mylan', kind: 'labelled_maker', strong: true, weight: 0.6, scan_ids: ['s-levo'] },
    { id: 'product:0378-1805>contains>med:levothyroxine', source: 'product:0378-1805', target: 'med:levothyroxine', kind: 'contains', strong: true, weight: 0.6 },
    { id: 'product:0378-1805>registered_to>lot:D2402999', source: 'product:0378-1805', target: 'lot:D2402999', kind: 'registered_to', strong: false, weight: 0.3 },
    { id: 'lot:D2402430>exact_lot>rec:fda-d-2402', source: 'lot:D2402430', target: 'rec:fda-d-2402', kind: 'exact_lot', strong: true, alert: true, weight: 1, match_kind: 'exact_lot', scan_ids: ['s-levo'] },
    { id: 'lot:D2402999>product_line_match>rec:fda-d-2402', source: 'lot:D2402999', target: 'rec:fda-d-2402', kind: 'product_line_match', strong: false, weight: 0.3, match_kind: 'product_line_match', scan_ids: ['s-levo'] },
    { id: 'rec:fda-d-2402>issued_by>reg:fda', source: 'rec:fda-d-2402', target: 'reg:fda', kind: 'issued_by', strong: true, weight: 0.7 },
    { id: 'rec:fda-d-2402>stated_manufacturer>mfr:mylan', source: 'rec:fda-d-2402', target: 'mfr:mylan', kind: 'stated_manufacturer', strong: false, weight: 0.4 },
    { id: 'scan:s-chlor>labelled_lot>lot:Z400069', source: 'scan:s-chlor', target: 'lot:Z400069', kind: 'labelled_lot', strong: true, weight: 1, scan_ids: ['s-chlor'] },
    { id: 'lot:Z400069>lot_only_match>rec:who-2024-6', source: 'lot:Z400069', target: 'rec:who-2024-6', kind: 'lot_only_match', strong: false, weight: 0.25, match_kind: 'lot_only_match', scan_ids: ['s-chlor'] },
    { id: 'rec:who-2024-6>issued_by>reg:who', source: 'rec:who-2024-6', target: 'reg:who', kind: 'issued_by', strong: true, weight: 0.7 },
    { id: 'rec:who-2024-6>affects>country:ng', source: 'rec:who-2024-6', target: 'country:ng', kind: 'affects', strong: false, weight: 0.4 },
    { id: 'reg:fda>more>cluster:fda-more', source: 'reg:fda', target: 'cluster:fda-more', kind: 'more', strong: false, weight: 0.2 },
  ],
  meta: {
    device_id: null, scans: 2, source: 'demo', demo: true, truncated: false,
    counts: { scan: 2, record: 2, lot: 3 }, timeline: [],
    notice: 'Sample data built into the page while the API client is unavailable.',
  },
};

export default SAMPLE_GRAPH;
