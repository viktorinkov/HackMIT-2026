// Pure-module tests for js/camera-math.js, the geometry behind a node flight.
// No three.js, no DOM: run with
//   node --test "backend/tests/graph/js/**/*.test.mjs"
// from the repo root.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  easeInOutCubic, flightFrame, followStep, isPoint, planFlight,
} from '../../../src/backend/graph/static/js/camera-math.js';

const IDEAL = 60;

function sub(a, b) { return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z }; }
function length(a) { return Math.hypot(a.x, a.y, a.z); }

/**
 * Degrees between two directions -- the number the defect was measured in.
 * atan2 of the cross product against the dot product, because acos of a normalised
 * dot loses half its digits near zero and cannot resolve a turn below ~1e-6 deg.
 */
function turnDegrees(a, b) {
  const cross = {
    x: a.y * b.z - a.z * b.y,
    y: a.z * b.x - a.x * b.z,
    z: a.x * b.y - a.y * b.x,
  };
  return (Math.atan2(length(cross), a.x * b.x + a.y * b.y + a.z * b.z) * 180) / Math.PI;
}

/** Replay a whole flight at 60 Hz and hand back every frame. */
function replay(plan, from, node, frames = 40) {
  const out = [];
  for (let i = 0; i <= frames; i += 1) {
    const next = typeof node === 'function' ? node(i / frames) : node;
    out.push(flightFrame(plan, from, next, easeInOutCubic(i / frames)));
  }
  return out;
}

test('a flight keeps the viewing direction exactly', () => {
  // The reported defect: consecutive selections turned the view by 62-156 degrees
  // because the destination sat on the ray from the origin through the node.
  const camera = { x: 0, y: 40, z: 180 };
  const target = { x: 0, y: 0, z: 0 };
  // A node on the far side of the graph: the worst case for the old recipe.
  const node = { x: -140, y: -90, z: -110 };
  const plan = planFlight({ camera, target, node, ideal: IDEAL });
  const before = sub(camera, target);

  for (const frame of replay(plan, target, node)) {
    assert.ok(turnDegrees(before, sub(frame.camera, frame.target)) < 1e-9);
  }
});

test('a flight ends with the node as the orbit target at the planned distance', () => {
  const camera = { x: 120, y: 0, z: 0 };
  const target = { x: 0, y: 0, z: 0 };
  const node = { x: -30, y: 55, z: 12 };
  const plan = planFlight({ camera, target, node, ideal: IDEAL });
  const end = flightFrame(plan, target, node, easeInOutCubic(1));

  assert.ok(length(sub(end.target, node)) < 1e-12);
  assert.ok(Math.abs(length(sub(end.camera, end.target)) - plan.dist1) < 1e-9);
});

test('a well framed node keeps its distance and only pans', () => {
  // 72 sits inside [0.6 * 60, 1.6 * 60]: nothing justifies a zoom.
  const camera = { x: 0, y: 0, z: 72 };
  const target = { x: 0, y: 0, z: 0 };
  const node = { x: 18, y: -6, z: 0 };
  const plan = planFlight({ camera, target, node, ideal: IDEAL });

  assert.equal(plan.dist0, 72);
  assert.equal(plan.dist1, 72);

  const end = flightFrame(plan, target, node, 1);
  assert.ok(Math.abs(length(sub(end.camera, end.target)) - 72) < 1e-9);
  // A pure pan: the camera moved by exactly the vector the pivot moved by.
  const camShift = sub(end.camera, camera);
  const pivotShift = sub(end.target, target);
  assert.ok(length(sub(camShift, pivotShift)) < 1e-9);
});

test('a far node dollies to the ideal distance', () => {
  const target = { x: 0, y: 0, z: 0 };
  const node = { x: 10, y: 0, z: 0 };

  const far = planFlight({ camera: { x: 0, y: 0, z: 400 }, target, node, ideal: IDEAL });
  assert.equal(far.dist1, IDEAL);

  const near = planFlight({ camera: { x: 0, y: 0, z: 9 }, target, node, ideal: IDEAL });
  assert.equal(near.dist1, IDEAL);

  // minDistance / maxDistance, when the controls set them, win over the ideal.
  const capped = planFlight({
    camera: { x: 0, y: 0, z: 400 }, target, node, ideal: IDEAL, minDistance: 90,
  });
  assert.equal(capped.dist1, 90);
});

test('following translates camera and target by the same vector so the view never rotates', () => {
  const camera = { x: 0, y: 0, z: 60 };
  const target = { x: 0, y: 0, z: 0 };
  // The simulation has carried the node off the pivot, as an incremental reheat does.
  const node = { x: 3.8, y: -1.2, z: 0.4 };
  const step = followStep({ camera, target, node, dtMs: 16.7 });

  assert.equal(step.moved, true);
  const camShift = sub(step.camera, camera);
  const pivotShift = sub(step.target, target);
  assert.ok(length(sub(camShift, pivotShift)) < 1e-12);
  assert.ok(turnDegrees(sub(camera, target), sub(step.camera, step.target)) < 1e-9);
  // A quarter of the gap per 60 Hz frame, and it converges rather than overshooting.
  assert.ok(Math.abs(length(camShift) / length(sub(node, target)) - 0.25) < 0.01);

  let live = step;
  for (let i = 0; i < 120; i += 1) live = followStep({ ...live, node, dtMs: 16.7 });
  assert.ok(length(sub(live.target, node)) < 0.01);

  // A pivot already on the node is left completely alone.
  const still = followStep({ camera, target, node: { x: 0, y: 0, z: 0 }, dtMs: 16.7 });
  assert.equal(still.moved, false);
});

test('a coincident camera and target falls back to a stable direction', () => {
  const at = { x: 12, y: -4, z: 7 };
  const plan = planFlight({ camera: at, target: at, node: { x: 40, y: 40, z: 40 }, ideal: IDEAL });

  assert.deepEqual(plan.dir, { x: 0, y: 0, z: 1 });
  assert.equal(plan.dist0, 0);
  assert.equal(plan.dist1, IDEAL);

  const end = flightFrame(plan, at, { x: 40, y: 40, z: 40 }, 1);
  assert.deepEqual(end.camera, { x: 40, y: 40, z: 40 + IDEAL });
});

test('a node that moves during the flight is still the target at the end', () => {
  const camera = { x: 0, y: 0, z: 200 };
  const target = { x: 0, y: 0, z: 0 };
  const start = { x: 60, y: 0, z: 0 };
  // An expand reheats the parent's one-hop set, so the node drifts all flight long.
  const moving = (t) => ({ x: start.x + 24 * t, y: -18 * t, z: 9 * t });
  const plan = planFlight({ camera, target, node: start, ideal: IDEAL });
  const frames = replay(plan, target, moving);
  const end = frames[frames.length - 1];
  const before = sub(camera, target);

  assert.ok(length(sub(end.target, moving(1))) < 1e-12);
  assert.ok(Math.abs(length(sub(end.camera, end.target)) - plan.dist1) < 1e-9);
  // The node moving does not buy the flight a rotation either.
  for (const frame of frames) {
    assert.ok(turnDegrees(before, sub(frame.camera, frame.target)) < 1e-9);
  }
});

test('a flight duration grows with the pan and stays inside its clamp', () => {
  const camera = { x: 0, y: 0, z: 60 };
  const target = { x: 0, y: 0, z: 0 };
  const near = planFlight({ camera, target, node: { x: 5, y: 0, z: 0 }, ideal: IDEAL });
  const mid = planFlight({ camera, target, node: { x: 300, y: 0, z: 0 }, ideal: IDEAL });
  const far = planFlight({ camera, target, node: { x: 4000, y: 0, z: 0 }, ideal: IDEAL });

  assert.equal(near.durationMs, 500);
  assert.equal(mid.durationMs, 450 + 1.1 * 300);
  assert.equal(far.durationMs, 1100);
});

test('a node with no coordinates yet plans no flight and is never followed', () => {
  const camera = { x: 0, y: 0, z: 60 };
  const target = { x: 0, y: 0, z: 0 };

  assert.equal(isPoint({ x: 1, y: 2, z: 3 }), true);
  assert.equal(isPoint({ x: 1, y: 2 }), false);
  assert.equal(isPoint({ x: NaN, y: 0, z: 0 }), false);

  assert.equal(planFlight({ camera, target, node: { x: 1, y: 2 }, ideal: IDEAL }), null);
  assert.equal(planFlight({ camera, target, node: { x: NaN, y: 0, z: 0 }, ideal: IDEAL }), null);

  const step = followStep({ camera, target, node: undefined, dtMs: 16.7 });
  assert.equal(step.moved, false);
  assert.deepEqual(step.camera, camera);
  assert.deepEqual(step.target, target);

  // A node that loses its coordinates mid-flight holds the pivot where it started.
  const plan = planFlight({ camera, target, node: { x: 40, y: 0, z: 0 }, ideal: IDEAL });
  const frame = flightFrame(plan, target, { x: undefined, y: 0, z: 0 }, 0.5);
  assert.deepEqual(frame.target, target);
  assert.equal(flightFrame(null, target, { x: 0, y: 0, z: 0 }, 0.5), null);
});

test('a flight deferred until the node has coordinates plans from the camera it finally starts at', () => {
  // The library assigns x/y/z inside a debounced digest, so every caller that merges
  // and flies in one turn -- ?focus=, #node=, search choose, the bridge's focus_node
  // -- asks for a flight the geometry cannot plan yet.
  const camera = { x: 0, y: 40, z: 180 };
  const target = { x: 0, y: 0, z: 0 };
  const node = { x: -140, y: -90, z: -110 };
  assert.equal(planFlight({ camera, target, node: {}, ideal: IDEAL }), null);
  assert.equal(planFlight({ camera, target, node: { id: 'lot:1' }, ideal: IDEAL }), null);

  // By the time the coordinates land the camera has moved on, so the deferred flight
  // has to be planned against the CURRENT camera and pivot, not the ones it was asked
  // from -- and it still owes the viewer the direction they are looking in now.
  const laterCamera = { x: 30, y: 44, z: 175 };
  const laterTarget = { x: 4, y: 1, z: -2 };
  const plan = planFlight({ camera: laterCamera, target: laterTarget, node, ideal: IDEAL });
  assert.ok(plan);
  const before = sub(laterCamera, laterTarget);
  for (const frame of replay(plan, laterTarget, node)) {
    assert.ok(turnDegrees(before, sub(frame.camera, frame.target)) < 1e-9);
  }
  const end = flightFrame(plan, laterTarget, node, 1);
  assert.ok(length(sub(end.target, node)) < 1e-12);
});

test('replaying the end frame of a finished flight holds the node centred without drifting', () => {
  // The library's zoomToFit tween keeps writing camera.position for its full duration
  // and cannot be cancelled, so a flight that lands mid-fit has to keep re-asserting
  // its end frame. Doing that must be idempotent, and must still track a live node.
  const camera = { x: 0, y: 0, z: 140 };
  const target = { x: 0, y: 0, z: 0 };
  const node = { x: 20, y: -35, z: 8 };
  const plan = planFlight({ camera, target, node, ideal: IDEAL });
  const end = flightFrame(plan, target, node, 1);

  assert.deepEqual(flightFrame(plan, target, node, 1), end);
  assert.deepEqual(flightFrame(plan, target, node, 1.4), end);

  const drifted = { x: node.x + 5, y: node.y - 2, z: node.z + 1 };
  const held = flightFrame(plan, target, drifted, 1);
  assert.ok(length(sub(held.target, drifted)) < 1e-12);
  assert.ok(Math.abs(length(sub(held.camera, held.target)) - plan.dist1) < 1e-9);
  assert.ok(turnDegrees(sub(camera, target), sub(held.camera, held.target)) < 1e-9);
});

test('a reduced motion follow snaps the pivot onto the node instead of gliding to it', () => {
  // The flight is a cut for these viewers; easing the pivot afterwards would hand
  // them the long unrequested camera move the setting exists to prevent, and the
  // layout keeps nudging a selected node for seconds after every expand.
  const camera = { x: 0, y: 0, z: 60 };
  const target = { x: 0, y: 0, z: 0 };
  const node = { x: 3.8, y: -1.2, z: 0.4 };
  const step = followStep({ camera, target, node, dtMs: 16.7, reducedMotion: true });

  assert.equal(step.moved, true);
  assert.ok(length(sub(step.target, node)) < 1e-12);
  // Still one translation applied to both, so a snap cannot turn the view either.
  assert.ok(length(sub(sub(step.camera, camera), sub(step.target, target))) < 1e-12);
  assert.ok(turnDegrees(sub(camera, target), sub(step.camera, step.target)) < 1e-9);
});

test('a node dragged with the camera never converges, so the follow must stand down during a drag', () => {
  // Node dragging is camera-relative: the library re-casts the pointer ray through
  // the LIVE camera against a plane fixed at pointerdown, so a camera translation of
  // d moves the dragged node by d as well. Feeding the follow into that loop leaves
  // the error undamped and the camera velocity growing for as long as the drag lasts.
  const pointerPerFrame = { x: 0.5, y: 0, z: 0 };
  function run({ cameraRelative }) {
    let camera = { x: 0, y: 0, z: 60 };
    let target = { x: 0, y: 0, z: 0 };
    let node = { x: 2, y: 0, z: 0 };
    const errors = [];
    const speeds = [];
    for (let i = 0; i < 60; i += 1) {
      const step = followStep({ camera, target, node, dtMs: 16.7 });
      const shift = sub(step.camera, camera);
      camera = step.camera;
      target = step.target;
      node = {
        x: node.x + pointerPerFrame.x + (cameraRelative ? shift.x : 0),
        y: node.y + pointerPerFrame.y + (cameraRelative ? shift.y : 0),
        z: node.z + pointerPerFrame.z + (cameraRelative ? shift.z : 0),
      };
      errors.push(length(sub(node, target)));
      speeds.push(length(shift));
    }
    return { errors, speeds };
  }

  // A node the SIMULATION is moving reaches a small steady state: the follow is a
  // damped chase and that is exactly what it is for.
  const free = run({ cameraRelative: false });
  assert.ok(free.errors[free.errors.length - 1] < 3);

  // The same node under a drag does not: the error grows without bound, and so does
  // the per-frame camera translation. Hence the drag guard in scene.js.
  const dragged = run({ cameraRelative: true });
  assert.ok(dragged.errors[dragged.errors.length - 1] > 10 * free.errors[free.errors.length - 1]);
  assert.ok(dragged.speeds[59] > dragged.speeds[9] * 3);
});

test('the flight easing starts and ends at rest and is clamped at both ends', () => {
  assert.equal(easeInOutCubic(0), 0);
  assert.equal(easeInOutCubic(1), 1);
  assert.equal(easeInOutCubic(0.5), 0.5);
  assert.equal(easeInOutCubic(-3), 0);
  assert.equal(easeInOutCubic(7), 1);
  // The first and last tenth cover less ground than the middle one: no lurch.
  assert.ok(easeInOutCubic(0.1) < 0.1);
  assert.ok(easeInOutCubic(0.9) > 0.9);
});
