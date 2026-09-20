// The geometry of a camera flight, as plain numbers. No three.js, no DOM, no
// globals: every function takes and returns `{x, y, z}` literals so the whole
// flight can be replayed frame by frame in a Node test.
//
// One invariant runs through the file: a flight is a PAN plus a DOLLY, never a
// rotation. The viewing direction is sampled once, when the flight is planned,
// and every later frame rebuilds the camera as `target + dir * dist`. There is
// no code path that can turn the view, which is the point -- the stock "fly to
// node" recipe aims at a point on the ray from the ORIGIN through the node, so
// it threw the camera to whichever side of the graph the node happened to be on.

const EPSILON = 1e-6;
// Below this the pivot is already on the node; chasing further only adds jitter.
const FOLLOW_EPSILON = 0.01;
// 1 - exp(-16.7/58) = 0.25, i.e. the asked-for quarter of the gap per 60 Hz frame,
// expressed as a time constant so a 30 Hz frame closes twice as much of it.
const FOLLOW_TAU_MS = 58;
// Keep the distance the viewer already chose unless it is well outside the band.
const NEAR_RATIO = 0.6;
const FAR_RATIO = 1.6;
const DURATION_BASE_MS = 450;
const DURATION_PER_UNIT = 1.1;
const DURATION_MIN_MS = 500;
const DURATION_MAX_MS = 1100;

function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

/** A usable point: all three coordinates present and finite. */
export function isPoint(p) {
  return !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z);
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

export function easeInOutCubic(t) {
  const x = clamp(t, 0, 1);
  return x < 0.5 ? 4 * x * x * x : 1 - ((-2 * x + 2) ** 3) / 2;
}

/**
 * Everything a flight needs, decided once:
 *   dir    unit vector from the pivot to the camera -- the direction to PRESERVE
 *   dist0  the distance the camera is at now
 *   dist1  the distance it should end at
 *   durationMs  scaled by how far the pivot has to travel, not by the dolly
 *
 * Returns null for a node whose coordinates the simulation has not produced yet;
 * the caller treats that as "no flight", never as a flight to the origin.
 */
export function planFlight({
  camera, target, node, ideal, minDistance, maxDistance,
} = {}) {
  if (!isPoint(camera) || !isPoint(target) || !isPoint(node)) return null;

  const away = { x: camera.x - target.x, y: camera.y - target.y, z: camera.z - target.z };
  const dist0 = Math.hypot(away.x, away.y, away.z);
  // A camera sitting on its own pivot has no viewing direction to preserve. +z is
  // the library's own default axis, so the fallback is stable rather than random.
  const dir = dist0 < EPSILON
    ? { x: 0, y: 0, z: 1 }
    : { x: away.x / dist0, y: away.y / dist0, z: away.z / dist0 };

  const d = Number.isFinite(ideal) && ideal > 0 ? ideal : dist0;
  // Re-zooming a node the viewer is already looking at is the most jarring thing
  // the camera can do, so a distance inside the band survives the flight untouched.
  let dist1 = (dist0 >= d * NEAR_RATIO && dist0 <= d * FAR_RATIO) ? dist0 : d;
  const lo = Number.isFinite(minDistance) ? minDistance : 0;
  const hi = Number.isFinite(maxDistance) ? maxDistance : Infinity;
  if (hi >= lo) dist1 = clamp(dist1, lo, hi);

  const durationMs = clamp(
    DURATION_BASE_MS + DURATION_PER_UNIT * distance(node, target),
    DURATION_MIN_MS,
    DURATION_MAX_MS,
  );
  return { dir, dist0, dist1, durationMs };
}

/**
 * One frame of a flight. `e` is the EASED fraction, and `nodeNow` is read fresh
 * every frame so a node the simulation is still moving is still the pivot at the
 * end. A node that loses its coordinates mid-flight holds the pivot at the start
 * point rather than snapping the camera to the origin.
 */
export function flightFrame(plan, T0, nodeNow, e) {
  if (!plan || !isPoint(T0)) return null;
  const to = isPoint(nodeNow) ? nodeNow : T0;
  const t = clamp(e, 0, 1);
  const target = {
    x: T0.x + (to.x - T0.x) * t,
    y: T0.y + (to.y - T0.y) * t,
    z: T0.z + (to.z - T0.z) * t,
  };
  const dist = plan.dist0 + (plan.dist1 - plan.dist0) * t;
  return {
    target,
    camera: {
      x: target.x + plan.dir.x * dist,
      y: target.y + plan.dir.y * dist,
      z: target.z + plan.dir.z * dist,
    },
  };
}

/**
 * Glue the pivot to a node that is still moving. Camera and target are translated
 * by the SAME vector, so `camera - target` -- and therefore the view direction, the
 * distance, and any rotation the user is in the middle of -- is left alone.
 *
 * `reducedMotion` closes the whole gap in one step. The flight is already a cut for
 * those viewers, and the layout keeps nudging a selected node for seconds after it,
 * so easing here would hand them exactly the long unrequested glide the setting asks
 * the page not to produce. It is still the same translation, so it still cannot turn
 * the view.
 *
 * The caller must stop calling this while the followed node is being DRAGGED. Node
 * dragging is camera-relative -- the library re-casts the pointer ray through the
 * live camera against a plane fixed at pointerdown -- so a camera translation feeds
 * straight back into the node's position and the error grows instead of decaying.
 */
export function followStep({ camera, target, node, dtMs, reducedMotion = false } = {}) {
  if (!isPoint(camera) || !isPoint(target) || !isPoint(node)) {
    return { camera, target, moved: false };
  }
  const delta = { x: node.x - target.x, y: node.y - target.y, z: node.z - target.z };
  if (Math.hypot(delta.x, delta.y, delta.z) <= FOLLOW_EPSILON) {
    return { camera, target, moved: false };
  }
  const dt = Number.isFinite(dtMs) && dtMs > 0 ? dtMs : 16.7;
  const k = reducedMotion ? 1 : 1 - Math.exp(-dt / FOLLOW_TAU_MS);
  const step = { x: delta.x * k, y: delta.y * k, z: delta.z * k };
  return {
    camera: { x: camera.x + step.x, y: camera.y + step.y, z: camera.z + step.z },
    target: { x: target.x + step.x, y: target.y + step.y, z: target.z + step.z },
    moved: true,
  };
}
