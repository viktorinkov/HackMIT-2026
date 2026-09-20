// The one place Atlas talks to the network. Same-origin, relative URLs;
// `?api=` may override the base but only to `https:` or to `localhost`/
// `127.0.0.1`, so an embedded WebView on an untrusted network can never be
// pointed at an arbitrary host through a query string.
//
// Not imported by the Node test suite (it touches `fetch`/`AbortController`
// and, for status reporting, the shared `store`), so it is exercised only
// through the browser-pane verification the lead runs — see
// backend/src/backend/graph/FRONTEND_CONTRACT.md.

import { dropSensitive } from './safe.js';
import { store } from './store.js';

const TIMEOUT_MS = 8000;
const RETRY_DELAY_MS = 600;
const MAX_CONCURRENT = 3;
const RETRYABLE_STATUS = new Set([502, 503, 504]);

function readUrlParam(name) {
  try {
    return new URLSearchParams(window.location.search).get(name);
  } catch {
    return null;
  }
}

function isAllowedApiOverride(raw) {
  let url;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    return false;
  }
  if (url.protocol === 'https:') return true;
  if (url.protocol === 'http:' && (url.hostname === 'localhost' || url.hostname === '127.0.0.1')) {
    return true;
  }
  return false;
}

function computeBaseUrl() {
  const override = readUrlParam('api');
  if (override && isAllowedApiOverride(override)) {
    return override.replace(/\/$/, '');
  }
  return '';
}

const BASE_URL = computeBaseUrl();

// True when this session should ask the backend for its committed fixture /
// canned responses instead of live Elasticsearch-backed data. `?fixture=1`
// forces it; `?demo=1` is the same request-shape but the backend only falls
// back to canned data there if the live path fails. Either way this is a
// query flag sent to the backend — there is no local fixture file for chrome
// to fetch.
function isDemoSession() {
  return readUrlParam('fixture') === '1' || readUrlParam('demo') === '1' || Boolean(store.state?.demo);
}

function setStatus(kind, message) {
  try {
    store.setStatus(kind, message);
  } catch {
    // store may not be constructed yet during very early boot; never let a
    // status report crash the caller.
  }
}

function buildUrl(path, params = {}) {
  const url = new URL(BASE_URL + path, window.location.href);
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- concurrency gate -------------------------------------------------
let inFlightCount = 0;
const waiters = [];

async function acquireSlot() {
  if (inFlightCount < MAX_CONCURRENT) {
    inFlightCount += 1;
    return;
  }
  await new Promise((resolve) => waiters.push(resolve));
  inFlightCount += 1;
}

function releaseSlot() {
  inFlightCount = Math.max(0, inFlightCount - 1);
  const next = waiters.shift();
  if (next) next();
}

// --- in-flight GET dedupe, keyed by the final URL ----------------------
const inFlightGets = new Map();

function isNetworkFailure(err) {
  return err instanceof TypeError || err?.name === 'AbortError';
}

/**
 * Fetch JSON with an 8s timeout, one retry after a network error or a
 * 502/503/504, in-flight dedupe by URL, and a hard cap on concurrent
 * requests. GET requests only; carries no custom headers.
 */
async function getJson(url, { signal } = {}) {
  const existing = inFlightGets.get(url);
  if (existing) return existing;

  const promise = (async () => {
    await acquireSlot();
    try {
      return await attempt(url, signal, /* retried */ false);
    } finally {
      releaseSlot();
      inFlightGets.delete(url);
    }
  })();

  inFlightGets.set(url, promise);
  return promise;
}

async function attempt(url, externalSignal, retried) {
  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), TIMEOUT_MS);
  const onExternalAbort = () => timeoutController.abort();
  if (externalSignal) {
    if (externalSignal.aborted) timeoutController.abort();
    else externalSignal.addEventListener('abort', onExternalAbort);
  }
  try {
    const res = await fetch(url, { method: 'GET', signal: timeoutController.signal, credentials: 'same-origin' });
    if (!res.ok) {
      if (!retried && RETRYABLE_STATUS.has(res.status)) {
        await sleep(RETRY_DELAY_MS);
        return attempt(url, externalSignal, true);
      }
      const kind = res.status >= 500 ? 'error' : 'error';
      setStatus(kind, `Request failed (${res.status})`);
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    const data = await res.json();
    return dropSensitive(data);
  } catch (err) {
    if (externalSignal?.aborted) throw err; // caller cancelled on purpose; not a failure to report
    if (isNetworkFailure(err) && !retried) {
      await sleep(RETRY_DELAY_MS);
      return attempt(url, externalSignal, true);
    }
    if (isNetworkFailure(err)) {
      setStatus('offline', 'The network could not be reached.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener('abort', onExternalAbort);
  }
}

async function postJson(path, body) {
  await acquireSlot();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(buildUrl(path), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      setStatus('error', `Request failed (${res.status})`);
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    const data = await res.json();
    return dropSensitive(data);
  } catch (err) {
    if (isNetworkFailure(err)) setStatus('offline', 'The network could not be reached.');
    throw err;
  } finally {
    clearTimeout(timer);
    releaseSlot();
  }
}

export const api = {
  /** GET /graph — the personal graph, plus an optional universe backdrop. */
  async graph({ deviceId, demo, universe } = {}) {
    const url = buildUrl('/graph', {
      device_id: deviceId,
      universe: universe ? 1 : undefined,
      demo: demo || isDemoSession() ? 1 : undefined,
    });
    return getJson(url);
  },

  /** GET /graph/universe — the committed corpus-backdrop snapshot. */
  async universe() {
    return getJson(buildUrl('/graph/universe'));
  },

  /** GET /graph/expand — lazy neighbours for one node. */
  async expand(id, { deviceId, scanId } = {}) {
    const url = buildUrl('/graph/expand', {
      id,
      device_id: deviceId,
      scan_id: scanId,
      demo: isDemoSession() ? 1 : undefined,
    });
    return getJson(url);
  },

  /** GET /graph/node — the note panel's detail payload. */
  async node(id, { deviceId } = {}) {
    const url = buildUrl('/graph/node', {
      id,
      device_id: deviceId,
      demo: isDemoSession() ? 1 : undefined,
    });
    return getJson(url);
  },

  /**
   * GET /graph/search — a new call aborts whatever search is still
   * in-flight, in addition to any `signal` the caller supplies.
   */
  async search(q, { deviceId, signal } = {}) {
    if (this._lastSearchController) this._lastSearchController.abort();
    const ownController = new AbortController();
    this._lastSearchController = ownController;
    const combined = combineSignals(signal, ownController.signal);
    const url = buildUrl('/graph/search', {
      q,
      device_id: deviceId,
      demo: isDemoSession() ? 1 : undefined,
    });
    return getJson(url, { signal: combined });
  },
  _lastSearchController: null,

  /**
   * Presenter hotkey (Shift+N): POST a prepared ScanCreate so a node blooms
   * in on the live graph even if the phone flow is not ready. Body matches
   * backend/README.md "Demo script" scenario A exactly.
   */
  async postDemoScan() {
    const deviceId = store.state?.deviceId || 'peel-graph-demo';
    const body = {
      device_id: deviceId,
      demo: true,
      country: 'United States',
      bottle: {
        is_medication_container: true,
        generic_name: 'Levothyroxine Sodium',
        strength: '200 mcg',
        form: 'tablet',
        ndc: '16729-457-15',
        manufacturer: 'Accord Healthcare',
        lot_number: 'D2402430',
        expiration: '10/2026',
        confidence: 0.93,
      },
      imprint: { is_pill: true, color: 'pink', shape: 'round', confidence: 0.7 },
      hardware: {
        status: 'substandard',
        spectrum: [0.1, 0.1, 0.1, 0.1],
        degraded: false,
        pill_type: 'levothyroxine',
        confidence: 0.78,
      },
      hardware_model: 'mock-spectrometry',
    };
    const data = await postJson('/scans', body);
    return { scan_id: data.scan_id ?? data.id ?? null };
  },
};

function combineSignals(a, b) {
  if (!a) return b;
  if (!b) return a;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (a.aborted || b.aborted) controller.abort();
  else {
    a.addEventListener('abort', abort);
    b.addEventListener('abort', abort);
  }
  return controller.signal;
}
