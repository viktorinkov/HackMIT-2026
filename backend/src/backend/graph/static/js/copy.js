// Every user-facing string in Atlas lives here. Nothing else may put text in
// front of a person directly; other modules call `t(key, vars)`.
//
// Hard rule, tested by backend/tests/graph/test_static.py and
// backend/tests/graph/js/copy.test.mjs: no assurance-style adjective (the kind
// that would tell someone a product is fine) ever appears below. Peel does
// not give assurances; a scan with nothing found is neutral, never good.
// Backend prose that must legitimately use that vocabulary (regulator text,
// mandated disclaimers) renders through `[data-backend-text]` instead.

export const STRINGS = {
  // Topbar
  'topbar.wordmark': 'Peel · Atlas',
  'topbar.breadcrumb_local': 'Local graph',
  'topbar.breadcrumb_universe': 'Universe',
  'topbar.view_local': 'Local',
  'topbar.view_universe': 'Universe',
  'topbar.counts': '{scans} scans · {nodes} nodes',

  // Left rail
  'rail.needs_attention': 'Needs attention',
  'rail.needs_attention_empty': 'Nothing flagged yet.',
  'rail.filters': 'Filters',
  'rail.legend': 'Legend',
  'rail.legend_evidence': 'Evidence',
  'rail.reported_sources': 'Reported sources',
  'rail.reported_source_scans': '{n} of your scans',

  // Severity legend (order: critical, high, moderate, unknown)
  'severity.critical': 'Critical',
  'severity.high': 'High',
  'severity.moderate': 'Moderate',
  'severity.unknown': 'Unclassified',

  // Verdict chips (config.js VERDICT[*].copy points here)
  'verdict.recall_match': 'Recall match',
  'verdict.mismatch_found': 'Mismatch found',
  'verdict.insufficient_evidence': 'Not enough evidence',
  'verdict.no_adverse_findings': 'No adverse findings in the sources checked',
  'verdict.no_adverse_findings_tooltip':
    'Not a confirmation of quality. Records current to {index_date}.',

  // Risk chips — medium/high only. "Low risk" is never a string in this file.
  'risk.medium': 'Elevated',
  'risk.high': 'High',

  // Link-kind captions (config.js LINK_KIND_COPY points here)
  'link.exact_lot': 'Exact lot match',
  'link.all_lots_product': 'Whole product line recalled',
  'link.ndc_in_description': 'Named in the recall text — not a lot match',
  'link.product_line_match': 'Same product line — not this lot',
  'link.lot_only_match': 'Lot string only — not corroborated',
  'link.lot_listed': 'Lot string appears in this record — product not checked',
  'link.stated_manufacturer': 'Name printed on the label',
  'link.conflicts_with': 'Label and pill reference disagree',

  // Crowd reports: one person's own account of a purchase, which Peel has not checked. Never
  // evidence, never strong, never an alert — see graph/models.py REPORT_KINDS.
  'link.bought_from': 'Where you said you bought it',
  'link.bought_in': 'Where you said you bought it',
  'link.located_in': 'Located in',
  'link.also_reported': "Other people's reports — counts only",

  // Note panel
  'note.properties': 'Properties',
  'note.findings': 'Findings',
  'note.mismatches': 'Mismatches',
  'note.linked_mentions': 'Linked mentions',
  'note.gaps': 'Gaps',
  'note.next_steps': 'Next steps',
  'note.sources': 'Sources',
  'note.open_scan': 'Open scan',
  'note.no_details': 'No further detail recorded.',
  'note.load_error': 'Could not load this note. Showing what the graph already knows.',
  'note.demo_badge': 'Demo',
  'note.select_prompt': 'Select a node to open its note.',
  'note.close': 'Close',

  // Crowd reports: a cluster carrying counts from OTHER people's reports
  // (never their scan ids, dates, free-text labels or coordinates — see R2 in
  // backend/src/backend/graph/FRONTEND_CONTRACT.md).
  'note.also_reported_count': 'Named by {n} other people',
  'note.also_reported_flagged': '{n} of them on scans with findings',
  'note.reports_unverified': 'Peel has not checked these reports.',

  // Properties that must never collapse into one status
  'property.expiry_label': 'Expiry (label)',
  'property.hardware_reading': 'Hardware reading',

  // Hardware
  'hardware.simulated': 'SIMULATED',

  // Chips
  'chip.demo': 'Demo scans — the recalls and lots are real regulator records',
  'chip.offline': 'Offline',
  'chip.demo_data': 'Demo data',

  // Quick switcher
  'search.placeholder': 'Jump to a node…',
  'search.wider_index': 'In the wider index',
  'search.footer_hint': '↑↓ navigate · ↵ fly · esc close',
  'search.no_results': 'No matches',
  'search.searching': 'Searching…',

  // Toasts
  'toast.demo_scan_posted': 'Posted the demo scan ({scan_id}) — watch it bloom in',
  'toast.demo_scan_failed': 'Could not post the demo scan',
  'toast.link_copied': 'Link copied',

  // Key panel ("How to read this") — panels/key.js builds both the always-on
  // panel and the rail's Legend section from these same six rows, so the two
  // can never drift apart.
  'key.title': 'How to read this',
  'key.pill': 'Key',
  'key.open': 'How to read this',
  'key.row_scan': 'Your scans',
  'key.row_alert': 'A recall names this exact lot — dots flow from the recall to your lot.',
  'key.row_alert_sub': 'Red critical · orange high · yellow moderate',
  'key.row_uncorroborated': 'Same product line or lot string only — not a match',
  'key.row_relation': 'How things are related',
  'key.row_report': 'Where you said you bought it — your own report, not checked',
  'key.row_selected': 'Selected — what you are looking at',

  // Help overlay
  'help.title': 'Keyboard shortcuts',
  'help.search': 'Open search',
  'help.help': 'Show this help',
  'help.rail': 'Toggle the left rail',
  'help.presenter': 'Post the prepared demo scan',
  'help.esc': 'Close a panel',
  'help.fit': 'Fit the graph to view',
  'help.local_universe': 'Toggle Local / Universe',
  'help.hide_chrome': 'Hide chrome',
  'help.presenter_stops': 'Fly to presenter stop {n}',
  'help.close': 'Close',

  // Load states
  'state.loading': 'Mapping your evidence…',
  'state.empty_title': 'No scans yet',
  'state.empty_body': 'Scan a bottle in the Peel app and it appears here.',
  'state.error_title': 'Something went wrong',
  'state.error_body': 'The graph could not be loaded.',
  'state.retry': 'Retry',
  'state.offline': 'Offline — showing your last graph',
  'state.no_webgl': "3D isn't available on this device — showing the list",

  // Fallback list view (no WebGL)
  'fallback.all_nodes': 'All nodes',

  // Sources / attribution
  'source.default_link_label': 'Source',
  'attribution.fda': 'openFDA (CC0) — see openFDA terms/disclaimer',
  'attribution.who': '© WHO, CC BY-NC-SA 3.0 IGO — summarised and linked',
  'attribution.mhra':
    'Contains public sector information licensed under the Open Government Licence v3.0',
  'attribution.health_canada': 'Open Government Licence – Canada',
  'attribution.nafdac': 'Summary with link; no published licence',
  'attribution.pillbox':
    'NLM Pillbox archive (frozen Jan 2021) — absence is not a finding',

  // Footer
  'footer.attribution':
    'Data: openFDA · WHO · Health Canada · MHRA · NAFDAC · NLM. Peel does not replace a pharmacist.',
};

/**
 * `t(key, vars)` — the only way user-facing text is produced in Atlas.
 * Missing keys render as `[[key]]` rather than throwing, so a typo shows up
 * on screen during development instead of crashing the panel.
 */
export function t(key, vars) {
  const template = STRINGS[key];
  if (template === undefined) return `[[${key}]]`;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match
  );
}

/** True if `key` has an entry. Used only for tests/dev tooling. */
export function hasKey(key) {
  return Object.prototype.hasOwnProperty.call(STRINGS, key);
}

const MONTH_ABBR = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/**
 * The one date formatter for every date shown anywhere in the chrome (rail
 * rows, the note panel, search rows): "Sep 18" for the current year, "Sep
 * 18, 2025" otherwise, no time and no timezone text. Reads the calendar date
 * straight out of the ISO string's own digits rather than through `Date`
 * parsing, so a UTC midnight timestamp never shifts to the previous day in a
 * browser west of Greenwich. A value that is not `YYYY-MM-DD...` (already a
 * formatted string, or empty) passes through unchanged.
 */
export function formatDate(iso) {
  if (!iso) return '';
  const raw = String(iso);
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
  if (!match) return raw;
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  const day = Number(match[3]);
  if (monthIndex < 0 || monthIndex > 11 || !Number.isFinite(day)) return raw;
  const label = `${MONTH_ABBR[monthIndex]} ${day}`;
  const currentYear = new Date().getFullYear();
  return year === currentYear ? label : `${label}, ${year}`;
}
