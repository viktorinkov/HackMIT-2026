// Entry point. Decides the tier, proves WebGL2, builds the scene, hands the chrome
// its mount, loads data and keeps it fresh. Everything that can fail is wrapped:
// the scene must survive a missing chrome, and the chrome must survive a missing GPU.

import { POLL_MS } from './config.js';
import {
  applyBodyFlags, installErrorGuards, isTruthy, pickTier, prefersReducedMotion,
  probeWebGL2, readParams, tierConfig,
} from './boot.js';
import { store } from './store.js';
import { createScene } from './scene.js';
import { attachInteraction } from './interaction.js';

const params = readParams(window.location.search);
const embed = isTruthy(params.embed);
const tierName = pickTier(params);
const tier = tierConfig(tierName);
const reducedMotion = prefersReducedMotion();
const debug = isTruthy(params.debug);

applyBodyFlags(document.body, { tier: tierName, embed });
store.configure({
  deviceId: params.device_id || null,
  demo: isTruthy(params.demo),
  tier: tierName,
  embed,
  budget: { maxNodes: tier.maxNodes, maxLinks: tier.maxLinks },
});

let scene = null;
let api = null;
let interaction = null;
let bloom = { ok: false };
let pendingParent = null;
let pollTimer = 0;
let focusDone = false;

function report(error) {
  const message = String((error && error.message) || error || 'unknown error');
  store.setStatus('error', message);
  if (debug) console.error('[atlas]', message);
}
installErrorGuards(report);

// ------------------------------------------------------------------ data

async function loadApiClient() {
  try {
    const mod = await import('./api.js');
    return mod.api || mod.default || null;
  } catch (error) {
    report(new Error('The graph API client is unavailable.'));
    return null;
  }
}

async function fetchGraph() {
  if (params.stress || isTruthy(params.fixture) || store.state.demo) {
    throw new Error('Simulated graphs are disabled. Use real scan data.');
  }
  const universe = store.state.view === 'universe' || isTruthy(params.universe);
  if (api && typeof api.graph === 'function') {
    return api.graph({
      deviceId: store.state.deviceId,
      demo: store.state.demo,
      universe,
    });
  }
  throw new Error('The graph API client is unavailable.');
}

function isLiveSession() {
  if (!api || params.stress || isTruthy(params.fixture)) return false;
  return !!store.state.deviceId || store.state.demo;
}

function startPolling() {
  if (pollTimer || !isLiveSession()) return;
  pollTimer = setInterval(async () => {
    if (document.hidden) return;
    try {
      const response = await fetchGraph();
      store.merge(response);
      applyFocusParam();
    } catch (error) {
      report(error);
    }
  }, POLL_MS);
}

async function loadInitial() {
  store.setStatus('loading', '');
  try {
    const response = await fetchGraph();
    store.setGraph(response);
    store.setStatus(store.state.demo || (response.meta && response.meta.demo) ? 'demo' : 'ready', '');
    startPolling();
  } catch (error) {
    report(error);
  }
}

/**
 * `?focus=<node id>` is how the Flutter app deep-links from a scan result
 * (`?embed=1&focus=scan:<id>`). The id may not be in the graph on the first layout,
 * so try again once the first poll has landed.
 */
let focusTries = 0;
function applyFocusParam() {
  const id = params.focus;
  if (!id || focusDone || !interaction) return;
  if (store.state.nodes.has(id)) {
    focusDone = true;
    interaction.select(id);
    return;
  }
  focusTries += 1;
  if (focusTries > 3) focusDone = true;
}

/**
 * Embed waits for the bridge's `set_device` before loading: a WebView opened from a
 * scan has no device id in the URL, and a live session must never start from demo
 * data. After 1.5 s with nothing, show the empty state.
 */
function waitForDevice() {
  if (!embed) return Promise.resolve();
  if (store.state.deviceId || store.state.demo || isTruthy(params.fixture)) return Promise.resolve();
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      store.removeEventListener('device', done);
      resolve();
    };
    const timer = setTimeout(() => {
      if (settled) return;
      store.setStatus('ready', 'waiting for a device');
      done();
    }, 1500);
    store.addEventListener('device', done);
  });
}

// ----------------------------------------------------------------- chrome

// Without a GPU the panels still run, so they always get the four scene functions.
const NO_SCENE = {
  flyTo() {}, fitView() {}, screenOf() { return null; }, setChromeHidden() {},
};

async function mountChromeSafely() {
  try {
    const mod = await import('./panels/index.js');
    if (mod && typeof mod.mountChrome === 'function') {
      mod.mountChrome({ store, scene: scene || NO_SCENE, api });
    }
  } catch (error) {
    console.info('[atlas] chrome not mounted:', String((error && error.message) || error));
  }
}

// -------------------------------------------------------------------- HUD

function startHud() {
  if (!debug) return;
  const hud = document.getElementById('hud');
  if (!hud) return;
  hud.hidden = false;
  setInterval(() => {
    const s = scene ? scene.stats() : { nodes: store.state.nodes.size, links: store.state.links.size };
    hud.textContent = [
      `fps      ${s.fps !== undefined ? s.fps : '-'}`,
      `calls    ${s.calls !== undefined ? s.calls : '-'}`,
      `nodes    ${s.nodes} / ${tier.maxNodes}`,
      `links    ${s.links} / ${tier.maxLinks}`,
      `labels   ${s.labels !== undefined ? s.labels : '-'}`,
      `tier     ${tierName}${embed ? ' embed' : ''}`,
      `bloom    ${bloom.ok ? 'on' : 'off'}`,
      `paused   ${s.paused ? 'yes' : 'no'}`,
    ].join('\n');
  }, 500);
}

// ------------------------------------------------------------------- boot

async function boot() {
  api = await loadApiClient();

  const probe = probeWebGL2();
  if (!probe.ok) {
    const fallback = document.getElementById('fallback');
    if (fallback) {
      fallback.hidden = false;
      fallback.classList.add('atlas-open');
    }
    store.setStatus('error', 'WebGL2 is unavailable on this device');
    await mountChromeSafely();
    await loadInitial();
    exposeGlobals();
    return;
  }

  scene = createScene({
    container: document.getElementById('canvas'),
    labelHost: document.getElementById('labels'),
    store,
    tier,
    tierName,
    reducedMotion,
    onSelect: (node) => interaction && interaction.onNode(node),
    onBackground: () => interaction && interaction.clear(),
    onSettled: () => applyFocusParam(),
  });

  interaction = attachInteraction({
    store,
    scene,
    api,
    params,
    setExpandParent: (id) => { pendingParent = id; },
  });

  store.addEventListener('graph', (event) => {
    const detail = event.detail;
    if (!detail.structural) {
      // Display fields only: repaint in place. Calling graphData() here would reheat
      // the simulation to alpha 1 and jiggle all 148 nodes every five seconds.
      scene.refresh(detail);
      return;
    }
    scene.pushGraph({
      parentId: pendingParent,
      added: detail.addedNodes,
      replaced: detail.replaced,
    });
    pendingParent = null;
    scene.refresh(detail);
  });
  store.addEventListener('view', () => { loadInitial().catch(report); });

  await mountChromeSafely();

  if (tier.bloom && !isTruthy(params.embed)) {
    try {
      const { enableBloom } = await import('./fx/bloom.js');
      bloom = await enableBloom(scene.graph);
      scene.setBloom(bloom.ok);
    } catch (error) {
      console.info('[atlas] bloom module unavailable:', String((error && error.message) || error));
    }
  }

  exposeGlobals();
  // Registered before the wait: a bridge that delivers set_device late -- after the
  // 1.5 s empty state -- must still be able to start the session.
  store.addEventListener('device', () => { loadInitial().catch(report); });

  await waitForDevice();
  startHud();
  if (embed && !store.state.deviceId && !store.state.demo && !isTruthy(params.fixture)) {
    return;
  }
  await loadInitial();
  applyFocusParam();
}

// ------------------------------------------------------------- __atlas

async function search(query) {
  if (!api || typeof api.search !== 'function') return null;
  const response = await api.search(query, { deviceId: store.state.deviceId });
  store.merge(response);
  const ids = (response && response.highlight) || [];
  store.setHighlight(ids);
  const first = (response && response.hits && response.hits[0]) || null;
  if (first && scene) {
    store.select(first.node_id);
    scene.flyTo(first.node_id);
  }
  return response;
}

function exposeGlobals() {
  window.__atlas = {
    store,
    graph: scene ? scene.graph : null,
    scene,
    params,
    fps: () => (scene ? scene.fps() : 0),
    stats: () => (scene ? scene.stats() : {
      nodes: store.state.nodes.size,
      links: store.state.links.size,
      calls: 0,
      tier: tierName,
      bloom: false,
    }),
    screenOf: (id) => (scene ? scene.screenOf(id) : null),
    select: (id) => (interaction ? interaction.select(id) : store.select(id)),
    search,
  };
}

boot().catch(report);

export { store, search };
