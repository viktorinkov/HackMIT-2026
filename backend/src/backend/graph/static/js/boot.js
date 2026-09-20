// Boot-time decisions: URL parameters, the static tier, the WebGL2 probe.
// Nothing here touches three.js or ForceGraph3D, so a failure is always legible.

import { TIERS, URL_PARAMS } from './config.js';

/** Only the documented parameters survive; anything else is ignored. */
export function readParams(search) {
  const out = {};
  const params = new URLSearchParams(search || '');
  for (const key of URL_PARAMS) {
    const value = params.get(key);
    if (value !== null) out[key] = value;
  }
  return out;
}

export function isTruthy(value) {
  return value === '' || value === '1' || value === 'true' || value === 'yes';
}

/**
 * One tier for the session; no runtime governor. A governor that samples while
 * the layout is running would ratchet the projector down to the worst tier on load.
 */
export function pickTier(params, env = {}) {
  const asked = params.tier;
  if (asked === 'mobile' || asked === 'desktop') return asked;
  if (isTruthy(params.embed)) return 'mobile';
  const coarse = env.coarsePointer !== undefined
    ? env.coarsePointer
    : (typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches);
  const shortSide = env.shortSide !== undefined
    ? env.shortSide
    : Math.min(window.innerWidth || 0, window.innerHeight || 0);
  if (coarse && shortSide < 820) return 'mobile';
  return 'desktop';
}

export function tierConfig(name) {
  return TIERS[name] || TIERS.desktop;
}

export function prefersReducedMotion() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Probe for WebGL2 and release the context at once: Android allows about eight
 * live contexts, and the real renderer needs one of them.
 */
export function probeWebGL2() {
  let canvas = null;
  try {
    canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { failIfMajorPerformanceCaveat: false });
    if (!gl) return { ok: false, renderer: null };
    let renderer = null;
    try {
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      if (ext) renderer = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '');
    } catch (_) { /* the string is a nicety, not a requirement */ }
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
    return { ok: true, renderer };
  } catch (error) {
    return { ok: false, renderer: null, error };
  } finally {
    if (canvas) canvas.width = canvas.height = 1;
  }
}

export function applyBodyFlags(body, { tier, embed }) {
  body.dataset.tier = tier;
  body.dataset.embed = embed ? '1' : '0';
}

/** Nothing may reach the console as an unhandled rejection during a demo. */
export function installErrorGuards(report) {
  const handler = (event) => {
    const error = event.reason || event.error || event.message;
    try { report(error); } catch (_) { /* reporting must never throw */ }
  };
  window.addEventListener('unhandledrejection', handler);
  window.addEventListener('error', handler);
}
