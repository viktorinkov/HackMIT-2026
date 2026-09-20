// The WebGL scene: one ForceGraph3D instance, the intensity engine that produces
// the hover effect, the camera, and the frame loop that also drives the labels.
//
// The library has no per-frame render hook (onEngineTick only fires while the
// simulation runs), so we own one rAF of our own and pause it with the renderer.

import * as THREE from 'three';
import { BG, INTENSITY, LINK_STYLE, SELECTION_RING, SIM } from './config.js';
import {
  applyNodeIntensity, animateNode, bodyPoolSize, createNodeObject, focusHalo,
  radiusOf, refreshNodeObject, ringSprite, wantsHalo,
} from './nodes.js';
import {
  LINK_RESOLUTION, PARTICLE_SPEED, alertApplies, applyLinkIntensity, linkDistance,
  linkWidthOf, materialFor, orientAlertLink, photonObject, poolSize, setStickMode,
  styleFor,
} from './links.js';
import { createLabelLayer } from './labels.js';
import { easeInOutCubic, flightFrame, followStep, isPoint, planFlight } from './camera-math.js';
import { isTypingTarget } from './interaction.js';
import { endpointId } from './store.js';

const EPS = 0.004;
const IDLE_MS = 6000;
// Relaxed from 5px: at the fitted distance almost nothing cleared the old threshold.
const LABEL_TAU = 2;
const CHARGE = -32;
const CENTRE_STRENGTH = 0.04;
const OFFSET_MS = 360;
const GUTTER = 12;
const AUTOROTATE_RAMP_MS = 1500;
const AUTOROTATE_SPEED = 0.25;
const TAP_SLOP_PX = 28;
// A photon is smallest leaving the record and largest arriving at your lot, which is
// what makes the direction of the evidence readable at a glance.
const PHOTON_SCALE_AT_RECORD = 0.78;
const PHOTON_SCALE_AT_LOT = 1.45;
// A short, hot reheat: new nodes settle in under a second and the rest stays put.
const INCREMENTAL_ALPHA_DECAY = 0.12;
const INCREMENTAL_VELOCITY_DECAY = 0.6;
const WARMUP_TICKS = 120;
const WARMUP_MAX_NODES = 300;
// exp(-(d*rho)^2) >= 0.75  =>  d*rho <= 0.5364: a node at the fitted distance keeps
// at least three quarters of its colour however large the graph grows.
const FOG_FIT_LIMIT = 0.5364;
// Keys that move the camera IN THIS APP. Pressing one cancels a flight and disarms
// the first-fit; every other key (search, help, Escape) leaves the camera alone.
//
// Only `F` (fit) and `1`-`4` (presenter stops) qualify: the vendored bundle never
// calls OrbitControls' `listenToKeyEvents`, so arrows, PageUp/Down, Home/End and
// `+`/`-` move nothing here and listing them only bought spurious cancellations --
// including from the search box, where ArrowUp/ArrowDown walk the result list.
const CAMERA_KEYS = new Set(['f', 'F', '1', '2', '3', '4']);

function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic offset on a small sphere, so an expand never looks random. */
function jitter(id, radius) {
  const h = hash(id);
  const a = ((h & 0xffff) / 0xffff) * Math.PI * 2;
  const b = Math.acos((((h >>> 16) & 0xffff) / 0xffff) * 2 - 1);
  return {
    x: radius * Math.sin(b) * Math.cos(a),
    y: radius * Math.sin(b) * Math.sin(a),
    z: radius * Math.cos(b),
  };
}

export function createScene({
  container, labelHost, store, tier, tierName, reducedMotion = false,
  onSelect = () => {}, onBackground = () => {}, onSettled = () => {},
}) {
  const ForceGraph3D = window.ForceGraph3D;
  if (typeof ForceGraph3D !== 'function') throw new Error('3d-force-graph did not load');

  const Graph = new ForceGraph3D(container, {
    controlType: 'orbit',
    rendererConfig: {
      antialias: tier.antialias,
      alpha: false,
      stencil: false,
      powerPreference: 'high-performance',
    },
  });

  const labels = createLabelLayer(labelHost, { size: tier.labels });
  // Desktop draws bonds; mobile keeps hairlines except on the alert path.
  setStickMode(tierName !== 'mobile');

  let bloomOn = false;
  let engineRunning = false;
  let pinned = [];
  let releaseTimer = 0;
  let firstLayout = true;
  let seedCounter = 0;
  let pendingFit = true;
  let chromeHidden = false;
  let railHidden = false;
  let flightUntil = 0;
  // The flight we are driving ourselves, and the node the pivot stays glued to
  // afterwards. Both are camera state only; neither touches the selection.
  let flight = null;
  let followId = null;
  // A flight asked for before the library had laid the node out. The digest that
  // assigns x/y/z is debounced, so every caller that merges and flies in one turn
  // arrives too early; the flight starts on the first frame that has coordinates.
  let pendingFly = null;
  // The selection to re-acquire once a REPLACED graph has settled, because the node
  // objects the old flight and follow pointed at no longer exist.
  let refollow = null;
  // When the library's own zoomToFit tween stops owning the camera. Its tween cannot
  // be cancelled from here, so we stay out of its way or outlast it instead.
  let fitUntil = 0;
  let contextTimer = 0;
  let hotReheat = false;
  let lastPickAt = 0;
  const embedLike = document.body.dataset.embed === '1';
  const particlesOn = !!tier.particles && !reducedMotion;
  const offset = { from: 0, to: 0, current: 0, t: OFFSET_MS };

  const activeNodes = new Set();
  const activeLinks = new Set();
  const pulses = [];
  const decorated = new Set();
  // Nodes at either end of an alert edge that applies to this device.
  const alertNodes = new Set();
  // The alert edges themselves: the only links that carry photons, and the only ones
  // the frame loop has to touch to taper them.
  const alertLinks = new Set();

  // ---------------------------------------------------------------- accessors

  function nodeVisible(node) {
    return !store.state.hiddenTypes.has(node.type);
  }

  function linkVisible(link) {
    const a = store.state.nodes.get(endpointId(link.source));
    const b = store.state.nodes.get(endpointId(link.target));
    return !!a && !!b && nodeVisible(a) && nodeVisible(b);
  }

  function nodeObject(node) {
    seedCounter += 1;
    const group = createNodeObject(node, {
      tier,
      degree: store.state.degree.get(node.id) || 0,
      seed: seedCounter,
      alertConnected: alertNodes.has(node.id),
    });
    const data = group.userData.atlas;
    data.intensity = node.__fresh ? 0.0 : INTENSITY.rest;
    data.target = INTENSITY.rest;
    if (node.__fresh) {
      data.grow = data.growDuration;
      group.scale.setScalar(0.001);
      node.__fresh = false;
    }
    if (data.grow || data.shimmer || data.spin) decorated.add(node);
    applyNodeIntensity(data, data.intensity);
    activeNodes.add(node);
    return group;
  }

  function linkMaterialFor(link) {
    const { hex, alpha, mesh, emissive } = styleFor(link, 'base', store.state.nodes, !!link.__applies);
    link.__matKey = null;
    return materialFor(hex, alpha * INTENSITY.rest, mesh, emissive);
  }

  /**
   * Only an alert edge that applies to this device carries photons. A crowd report
   * never does: `alertApplies` refuses a report kind outright, so LINK_CLASS.REPORT
   * cannot reach this path however the payload is flagged.
   */
  function particlesFor(link) {
    if (!particlesOn) return 0;
    return link.__applies ? LINK_STYLE.alert.particles : 0;
  }

  // ------------------------------------------------------------- intensity

  function markNode(node, target) {
    if (node.__it === target) return;
    node.__it = target;
    activeNodes.add(node);
  }

  function markLink(link, target, role) {
    if (link.__role !== role) { link.__role = role; link.__matKey = null; }
    else if (link.__it === target) return;
    link.__it = target;
    activeLinks.add(link);
  }

  /**
   * Hover lights the node and its neighbours; selection adds a second ring at
   * 0.45; everything else recedes to 0.12. Hover wins over selection while it lasts.
   */
  function recomputeTargets() {
    const s = store.state;
    const focus = s.hoveredId || s.selectedId;
    const highlight = s.highlight;
    const hasFocus = !!focus;
    const hasHighlight = highlight.size > 0;

    if (!hasFocus && !hasHighlight) {
      for (const node of s.nodes.values()) markNode(node, INTENSITY.rest);
      for (const link of s.links.values()) markLink(link, INTENSITY.rest, 'base');
      return;
    }

    const lit = new Set(highlight);
    const second = new Set();
    if (hasFocus) {
      lit.add(focus);
      const one = store.neighbours(focus);
      for (const id of one) lit.add(id);
      if (!s.hoveredId && s.selectedId) {
        for (const id of one) {
          for (const far of store.neighbours(id)) if (!lit.has(far)) second.add(far);
        }
      }
    }

    for (const node of s.nodes.values()) {
      const t = lit.has(node.id) ? INTENSITY.lit
        : second.has(node.id) ? INTENSITY.second
          : INTENSITY.dim;
      markNode(node, t);
    }
    for (const link of s.links.values()) {
      const a = endpointId(link.source);
      const b = endpointId(link.target);
      const aLit = lit.has(a);
      const bLit = lit.has(b);
      if (aLit && bLit) markLink(link, INTENSITY.lit, 'lit');
      else if ((aLit || bLit) && (second.has(a) || second.has(b))) markLink(link, INTENSITY.second, 'second');
      else markLink(link, INTENSITY.dim, 'dim');
    }
  }

  function stepIntensity(dtMs) {
    const k = 1 - Math.exp(-dtMs / INTENSITY.tauMs);

    for (const node of activeNodes) {
      const obj = node.__threeObj;
      if (!obj || !obj.userData.atlas) {
        // No object yet means the digest has not run; only drop what has really gone.
        if (!store.state.nodes.has(node.id) || !nodeVisible(node)) activeNodes.delete(node);
        continue;
      }
      const data = obj.userData.atlas;
      const target = node.__it === undefined ? INTENSITY.rest : node.__it;
      let i = data.intensity + (target - data.intensity) * k;
      // Shimmer, spin and growth live in `decorated`, which re-applies on its own.
      if (Math.abs(target - i) <= EPS) { i = target; activeNodes.delete(node); }
      data.intensity = i;
      applyNodeIntensity(data, i);
    }

    for (const link of activeLinks) {
      if (!link.__lineObj) {
        if (!store.state.links.has(link.id)) activeLinks.delete(link);
        continue;
      }
      const target = link.__it === undefined ? INTENSITY.rest : link.__it;
      let i = link.__i === undefined ? INTENSITY.rest : link.__i;
      i += (target - i) * k;
      if (Math.abs(target - i) <= EPS) { i = target; activeLinks.delete(link); }
      link.__i = i;
      applyLinkIntensity(link, i, link.__role || 'base', store.state.nodes, !!link.__applies);
    }
  }

  /**
   * The photons already travel from the record toward the user's lot. This makes that
   * direction readable when the path is short: a photon grows as it approaches the lot,
   * so the end that matters is the bright one.
   *
   * Cheap on purpose. It touches only the handful of links that carry particles, it
   * writes a scale the library never writes itself, and it reads `__progressRatio` --
   * the library's own 0-at-source, 1-at-target counter -- rather than recomputing it.
   * No new motion: it rescales photons that were already moving.
   */
  function stepPhotons() {
    for (const link of alertLinks) {
      const group = link.__photonsObj;
      const children = group && group.children;
      if (!children || !children.length) continue;
      for (const photon of children) {
        const p = photon.__progressRatio;
        if (typeof p !== 'number') continue;
        const t = p < 0 ? 0 : (p > 1 ? 1 : p);
        photon.scale.setScalar(PHOTON_SCALE_AT_RECORD
          + (PHOTON_SCALE_AT_LOT - PHOTON_SCALE_AT_RECORD) * t);
      }
    }
  }

  function stepDecorations(now, dtMs) {
    for (const node of decorated) {
      const obj = node.__threeObj;
      if (!obj || !obj.userData.atlas) { decorated.delete(node); continue; }
      const data = obj.userData.atlas;
      const busy = animateNode(data, now, dtMs, obj);
      applyNodeIntensity(data, data.intensity);
      if (!busy) decorated.delete(node);
    }
    for (let i = pulses.length - 1; i >= 0; i -= 1) {
      const p = pulses[i];
      p.t += dtMs;
      const t = Math.min(1, p.t / p.dur);
      p.sprite.scale.setScalar(p.r0 + (p.r1 - p.r0) * t);
      p.sprite.material.opacity = 0.75 * (1 - t) * (1 - t);
      if (t >= 1) {
        if (p.sprite.parent) p.sprite.parent.remove(p.sprite);
        p.sprite.material.dispose();
        pulses.splice(i, 1);
      }
    }
  }

  // ---------------------------------------------------------------- labels

  const camPrev = { x: 0, y: 0, z: 0, tx: 0, ty: 0, tz: 0 };
  const fwd = { x: 0, y: 0, z: -1 };

  function cameraMoved() {
    const cam = Graph.camera();
    const controls = Graph.controls();
    const t = (controls && controls.target) || { x: 0, y: 0, z: 0 };
    const moved = cam.position.x !== camPrev.x || cam.position.y !== camPrev.y
      || cam.position.z !== camPrev.z || t.x !== camPrev.tx || t.y !== camPrev.ty || t.z !== camPrev.tz;
    if (moved) {
      camPrev.x = cam.position.x; camPrev.y = cam.position.y; camPrev.z = cam.position.z;
      camPrev.tx = t.x; camPrev.ty = t.y; camPrev.tz = t.z;
    }
    return moved;
  }

  /**
   * Positions are refreshed every frame (40 elements is nothing); only the CHOICE of
   * which labels are shown is frozen while the camera is flying, so labels never pop
   * mid-flight and never lag behind their nodes.
   */
  function updateLabels(repositionOnly) {
    if (repositionOnly && labels.count > 0) {
      labels.reposition((id) => {
        const node = store.state.nodes.get(id);
        if (!node || node.x === undefined) return null;
        return Graph.graph2ScreenCoords(node.x, node.y, node.z);
      });
      return;
    }
    const cam = Graph.camera();
    const h = container.clientHeight || 1;
    const focal = h / (2 * Math.tan((cam.fov * Math.PI) / 360));
    const e = cam.matrixWorld.elements;
    fwd.x = -e[8]; fwd.y = -e[9]; fwd.z = -e[10];
    const px = cam.position.x;
    const py = cam.position.y;
    const pz = cam.position.z;

    const s = store.state;
    const focus = s.hoveredId || s.selectedId;
    const near = focus ? store.neighbours(focus) : null;
    const candidates = [];

    for (const node of s.nodes.values()) {
      if (node.x === undefined || !nodeVisible(node)) continue;
      const obj = node.__threeObj;
      if (!obj) continue;
      const depth = (node.x - px) * fwd.x + (node.y - py) * fwd.y + (node.z - pz) * fwd.z;
      if (depth <= 1) continue;
      const data = obj.userData.atlas;
      const rpx = (data.radius * focal) / depth;
      const isFocus = node.id === focus;
      const isNear = !!near && near.has(node.id);
      // The red path has to read at the fitted view, so both ends of an applicable
      // alert edge take a slot before anything is judged on projected size.
      const onAlert = alertNodes.has(node.id);
      const always = isFocus || isNear || onAlert
        || node.type === 'scan' || node.type === 'regulator';
      if (!always && rpx < LABEL_TAU * 0.5) continue;
      if (data.intensity < 0.2 && !always) continue;

      let score = rpx;
      if (isFocus) score += 4000;
      else if (isNear) score += 2000;
      if (node.type === 'scan') score += 1400;
      else if (node.type === 'regulator') score += 1200;
      else if (onAlert) score += 1000;
      if (node.severity === 'critical') score += 300;
      else if (node.severity === 'high') score += 160;
      score += (s.degree.get(node.id) || 0) * 3;

      const screen = Graph.graph2ScreenCoords(node.x, node.y, node.z);
      candidates.push({
        id: node.id, node, x: screen.x, y: screen.y, rpx,
        score, lit: isFocus, showSub: isFocus, always,
      });
      if (candidates.length > tier.labels * 6) break;
    }
    labels.render(candidates);
  }

  // ------------------------------------------------------------ frame loop

  let raf = 0;
  let last = 0;
  let paused = false;
  let labelDue = true;
  const frames = [];
  let lastIdle = performance.now();
  let autoRotate = 0;

  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = last ? Math.min(64, now - last) : 16;
    last = now;

    const offsetMoving = stepViewOffset(dt);
    trackLights();
    if (activeNodes.size || activeLinks.size) stepIntensity(dt);
    if (decorated.size || pulses.length) stepDecorations(now, dt);
    if (particlesOn && alertLinks.size) stepPhotons();

    const flying = now < flightUntil;
    const moved = cameraMoved();
    // Positions follow the camera every frame; the SET of labels is frozen while a
    // flight is running so nothing pops halfway through.
    if (moved || offsetMoving || engineRunning || labelDue || activeNodes.size > 0) {
      const repositionOnly = flying && !labelDue;
      updateLabels(repositionOnly);
      if (!repositionOnly) labelDue = false;
    }

    frames.push(now);
    if (frames.length > 90) frames.shift();

    // Last, on purpose: the labels above were positioned against the camera the
    // library had just rendered with, and the write below is the final one before
    // the next `controls.update()` reads it.
    stepCamera(now, dt);
    stepAutoRotate(now, dt);
  }

  /**
   * Auto-rotate ramps in over 1.5 s and ramps back out rather than being switched,
   * so stopping it never snaps the camera. It orbits the CURRENT `controls.target`,
   * which the flight and the follow keep on the selected node.
   *
   * It is cut dead rather than ramped down while a flight runs: the ramp exists so
   * a stop is not a jerk, and a flight is already motion. Left on for even half a
   * second it would feed `_sphericalDelta` from inside `controls.update()`, which
   * is the one place our per-frame zeroing cannot reach, and turn the view.
   */
  function stepAutoRotate(now, dtMs) {
    const controls = Graph.controls();
    if (!controls) return;
    if (flight) {
      autoRotate = 0;
      if (controls.autoRotate) controls.autoRotate = false;
      return;
    }
    const wanted = !reducedMotion && !embedLike && now - lastIdle > IDLE_MS;
    const step = dtMs / AUTOROTATE_RAMP_MS;
    autoRotate = wanted
      ? Math.min(1, autoRotate + step)
      : Math.max(0, autoRotate - step * 3);
    if (autoRotate <= 0) {
      if (controls.autoRotate) controls.autoRotate = false;
      return;
    }
    controls.autoRotate = true;
    // Ease-in-out on the ramp: the first degree of motion is as gentle as the last.
    const e = autoRotate * autoRotate * (3 - 2 * autoRotate);
    controls.autoRotateSpeed = AUTOROTATE_SPEED * e;
  }

  function stopAutoRotate() {
    lastIdle = performance.now();
  }

  function pause() {
    if (paused) return;
    paused = true;
    Graph.pauseAnimation();
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function resume() {
    if (!paused) return;
    paused = false;
    Graph.resumeAnimation();
    last = 0;
    if (!raf) raf = requestAnimationFrame(frame);
    if (engineRunning) Graph.d3ReheatSimulation();
  }

  // ------------------------------------------------------------ graph data

  function refreshApplicability() {
    const keys = new Set();
    for (const node of store.state.nodes.values()) {
      if (node.type !== 'scan') continue;
      keys.add(node.id);
      keys.add(node.id.slice(5));
      for (const id of node.scan_ids || []) keys.add(id);
    }
    alertNodes.clear();
    alertLinks.clear();
    for (const link of store.state.links.values()) {
      link.__applies = alertApplies(link, keys);
      if (!link.__applies) continue;
      alertLinks.add(link);
      alertNodes.add(endpointId(link.source));
      alertNodes.add(endpointId(link.target));
    }
  }

  function releasePins() {
    if (releaseTimer) { clearTimeout(releaseTimer); releaseTimer = 0; }
    if (!pinned.length) return;
    for (const node of pinned) { node.fx = undefined; node.fy = undefined; node.fz = undefined; }
    pinned = [];
  }

  /**
   * Hand the store's own objects to the engine. New nodes bud from their parent
   * and everything outside the parent's 1-hop set is pinned until the layout settles,
   * so an expand never lurches the whole graph.
   */
  function pushGraph({ parentId = null, added = [], replaced = false } = {}) {
    releasePins();
    if (replaced) {
      // `setGraph` builds brand-new, coordinate-free node objects and leaves the
      // selection alone. Left standing, the follow would re-acquire the same id in
      // the new layout and slew the camera across the scene chasing it. Stand down
      // and re-acquire the selection once the fresh layout has settled instead.
      pendingFit = true;
      flight = null;
      pendingFly = null;
      followId = null;
      flightUntil = 0;
      refollow = store.state.selectedId || null;
    }
    const nodes = [];
    const links = [];
    for (const node of store.state.nodes.values()) nodes.push(node);
    for (const link of store.state.links.values()) { orientAlertLink(link); links.push(link); }
    refreshApplicability();

    const parent = parentId ? store.state.nodes.get(parentId) : null;
    if (parent && parent.x !== undefined && added.length) {
      const keep = store.neighbours(parentId);
      for (const node of added) {
        if (node.x !== undefined) continue;
        const off = jitter(node.id, 16);
        node.x = parent.x + off.x;
        node.y = parent.y + off.y;
        node.z = parent.z + off.z;
        node.__fresh = true;
      }
      const fresh = new Set(added.map((n) => n.id));
      for (const node of nodes) {
        if (node.id === parentId || keep.has(node.id) || fresh.has(node.id)) continue;
        if (node.x === undefined) continue;
        node.fx = node.x; node.fy = node.y; node.fz = node.z;
        pinned.push(node);
      }
    } else {
      for (const node of added) node.__fresh = !firstLayout;
    }

    const sim = firstLayout ? SIM.initial : SIM.incremental;
    // A tab that loads hidden ticks about twice a second, so without a real warmup
    // the first visible frame is an unlaid-out blob in a corner.
    const warmup = firstLayout && nodes.length <= WARMUP_MAX_NODES
      ? WARMUP_TICKS
      : sim.warmupTicks;
    // graphData() always reheats to alpha 1; an incremental update makes that heat
    // burn off fast so only the new nodes visibly settle.
    hotReheat = !firstLayout;
    Graph.warmupTicks(warmup)
      .cooldownTicks(sim.cooldownTicks)
      .cooldownTime(sim.cooldownTime)
      .d3AlphaDecay(hotReheat ? INCREMENTAL_ALPHA_DECAY : sim.alphaDecay)
      .d3VelocityDecay(hotReheat ? INCREMENTAL_VELOCITY_DECAY : sim.velocityDecay);

    Graph.graphData({ nodes, links });
    firstLayout = false;
    labelDue = true;
    recomputeTargets();
    if (pinned.length) releaseTimer = setTimeout(releasePins, 2500);
  }

  // -------------------------------------------------------------- selection

  // The ring around the selected node. Neutral white: purple belongs to your scans and
  // to nothing else, so a selected lot can no longer read as a second kind of finding
  // next to a red recall path.
  let selectionRing = null;
  // One halo, reparented. The reference has no glow, so only you, the alert path and
  // whatever is under the pointer get one.
  const focusGlow = focusHalo();

  function moveFocusHalo() {
    const id = store.state.hoveredId || store.state.selectedId;
    const node = id ? store.state.nodes.get(id) : null;
    const obj = node && node.__threeObj;
    if (!obj || !obj.userData.atlas) {
      if (focusGlow.parent) focusGlow.parent.remove(focusGlow);
      return;
    }
    const data = obj.userData.atlas;
    // A node that already carries its own halo does not need a second one.
    if (wantsHalo(node, alertNodes.has(node.id))) {
      if (focusGlow.parent) focusGlow.parent.remove(focusGlow);
      return;
    }
    // Neutral, not the node's own hue: this halo only ever says "you are looking at
    // this", and the body underneath keeps its colour to say what it is.
    focusGlow.material.color.set(SELECTION_RING);
    focusGlow.scale.setScalar(data.radius * 5.2);
    focusGlow.material.opacity = 0.2;
    obj.add(focusGlow);
  }

  function clearSelectionRing() {
    if (selectionRing && selectionRing.parent) selectionRing.parent.remove(selectionRing);
    if (selectionRing) selectionRing.material.dispose();
    selectionRing = null;
  }

  function decorateSelection(id) {
    clearSelectionRing();
    // The selected core is tinted toward white, so any node whose flag flips has to
    // be re-applied at once: its intensity target may not have changed at all.
    for (const node of store.state.nodes.values()) {
      const obj = node.__threeObj;
      if (!obj || !obj.userData.atlas) continue;
      const data = obj.userData.atlas;
      const next = node.id === id;
      if (data.selected === next) continue;
      data.selected = next;
      applyNodeIntensity(data, data.intensity);
    }
    if (!id) return;
    const node = store.state.nodes.get(id);
    const obj = node && node.__threeObj;
    if (!obj) return;
    const data = obj.userData.atlas;
    selectionRing = ringSprite(SELECTION_RING, data.radius * 3.8, { additive: true, opacity: 0.8 });
    obj.add(selectionRing);
    if (!reducedMotion) {
      const pulse = ringSprite(SELECTION_RING, data.radius * 2, { additive: true, opacity: 0.75 });
      obj.add(pulse);
      pulses.push({ sprite: pulse, t: 0, dur: 700, r0: data.radius * 1.2, r1: data.radius * 7 });
    }
  }

  // ----------------------------------------------------------------- camera

  /** A node's live position, or null while the simulation has yet to place it. */
  function pointOf(node) {
    if (!node) return null;
    const p = { x: node.x, y: node.y, z: node.z };
    return isPoint(p) ? p : null;
  }

  /**
   * The only place the camera and the orbit pivot are written. Both move together,
   * so `camera - target` -- the viewing direction and the distance -- is whatever
   * the caller decided and nothing else.
   *
   * It does not set `labelDue`: `cameraMoved()` picks this write up on the next
   * frame, which keeps the label SET frozen for the length of the flight while the
   * positions still follow every frame.
   */
  function applyCamera(next) {
    if (!next) return;
    const cam = Graph.camera();
    const controls = Graph.controls();
    if (!cam || !controls || !controls.target) return;
    cam.position.set(next.camera.x, next.camera.y, next.camera.z);
    controls.target.set(next.target.x, next.target.y, next.target.z);
  }

  /**
   * OrbitControls keeps the rest of a gesture in `_sphericalDelta` / `_panOffset`
   * and bleeds it out at `dampingFactor` (0.08) per update -- about fifty frames.
   * During a flight that residue is exactly the rotation the flight exists to
   * avoid, so it is zeroed every frame. Private fields on the library's own
   * instance: every access is guarded rather than assumed.
   */
  function quietControls(controls) {
    const spin = controls._sphericalDelta;
    if (spin && typeof spin.set === 'function') spin.set(0, 0, 0);
    const pan = controls._panOffset;
    if (pan && typeof pan.set === 'function') pan.set(0, 0, 0);
    if (typeof controls._scale === 'number') controls._scale = 1;
  }

  /**
   * A flight is a pan plus a dolly, never a rotation: `camera-math.js` samples the
   * viewing direction once and every frame rebuilds `target + dir * dist` around
   * the node's LIVE position, so a node the simulation is still moving is still the
   * pivot at the end. Afterwards the follow keeps the pivot glued to it by
   * translating camera and target by the same vector, which cannot rotate the view
   * and so never fights a drag in progress.
   *
   * Runs at the end of our frame. The library's own cycle is
   * `controls.update()` -> render -> tweens, so this write is the last thing before
   * the next `controls.update()` reads it back.
   */
  function stepCamera(now, dtMs) {
    const cam = Graph.camera();
    const controls = Graph.controls();
    if (!cam || !controls || !controls.target) return;
    // The library disables the controls for exactly the duration of a node drag.
    // Dragging is camera-relative -- the pointer ray is re-cast through the LIVE
    // camera against a plane fixed at pointerdown -- so any camera move we made
    // here would be added straight back into the node's dragged position and the
    // two would run away from each other. The drag owns the camera; we do nothing.
    if (controls.enabled === false) return;

    if (pendingFly) drainPendingFly();

    if (flight) {
      // A zero-duration flight (reduced motion) is already applied; it only stays
      // on the books to outlast a fit tween, so it replays its end frame.
      const raw = flight.duration > 0 ? (now - flight.start) / flight.duration : 1;
      const eased = easeInOutCubic(raw);
      const live = pointOf(store.state.nodes.get(flight.id));
      applyCamera(flightFrame(flight.plan, flight.from, live, eased));
      quietControls(controls);
      // `zoomToFit` tweens the camera for its full duration and the tween cannot be
      // reached from here, so a flight that lands mid-fit keeps writing its end
      // frame until the tween is over. Letting go earlier hands the camera back to
      // the tween, which then drags it off the node it had just centred.
      if (raw >= 1 && now >= flight.holdUntil) flight = null;
      return;
    }

    if (!followId) return;
    // While a fit tween is running it owns both the camera and the pivot: its
    // look-at tween re-writes `controls.target` after our frame, and a follow
    // closing a quarter of a gap the tween re-opens every frame is a shudder.
    if (now < fitUntil) return;
    const live = pointOf(store.state.nodes.get(followId));
    if (!live) return;
    const next = followStep({
      camera: { x: cam.position.x, y: cam.position.y, z: cam.position.z },
      target: { x: controls.target.x, y: controls.target.y, z: controls.target.z },
      node: live,
      dtMs,
      reducedMotion,
    });
    if (next.moved) applyCamera(next);
  }

  /** Start a flight that was asked for before the node had been laid out. */
  function drainPendingFly() {
    const node = store.state.nodes.get(pendingFly.id);
    if (!node) { pendingFly = null; return; }
    if (!pointOf(node)) return;
    const { id, ms } = pendingFly;
    pendingFly = null;
    flyTo(id, { ms });
  }

  /**
   * Stop where we are. No snap: the camera and the pivot keep the values this
   * frame left them with, and the follow above finishes the centring smoothly.
   */
  function cancelFlight() {
    pendingFly = null;
    if (!flight) return;
    flight = null;
    flightUntil = 0;
    labelDue = true;
  }

  /**
   * ALWAYS retarget. The pivot ends on this node whatever the camera was doing
   * before, because the alternative -- leaving `controls.target` on the previous
   * node -- is what made orbiting a selection swing around a point several units
   * off centre. "Already well framed" now only means the distance survives and the
   * pan is short.
   *
   * `Graph.cameraPosition()` is deliberately not used: it tweens the look-at from a
   * point 1000 units in front of the camera rather than from the pivot, which adds
   * a rotation sweep to every flight.
   */
  function flyTo(id, { ms } = {}) {
    const node = store.state.nodes.get(id);
    if (!node) return;
    const cam = Graph.camera();
    const controls = Graph.controls();
    if (!cam || !controls || !controls.target) return;

    stopAutoRotate();
    pendingFit = false;
    refollow = null;
    // Own the follow state BEFORE anything can return. A flight that cannot be
    // planned yet must never leave the pivot glued to the previous node -- that is
    // the off-centre pivot, and it is worse than not moving at all.
    followId = id;
    flight = null;
    pendingFly = null;

    const to = pointOf(node);
    if (!to) {
      // The library's digest is `debounce(update, 1)`, so `graphData()` assigns
      // x/y/z a macrotask later. Every caller that merges and flies in one turn --
      // `?focus=`, `#node=`, search choose, the bridge's focus_node -- lands here.
      // Remember the request and fly on the first frame that has coordinates.
      pendingFly = { id, ms };
      flightUntil = 0;
      return;
    }
    const obj = node.__threeObj;
    const r = obj && obj.userData.atlas ? obj.userData.atlas.radius : radiusOf(node);
    // Start from where the camera actually is, so a selection made mid-flight
    // continues from here instead of restarting from the old flight's origin.
    const from = { x: controls.target.x, y: controls.target.y, z: controls.target.z };
    const plan = planFlight({
      camera: { x: cam.position.x, y: cam.position.y, z: cam.position.z },
      target: from,
      node: to,
      ideal: Math.max(60, 14 * r),
      minDistance: controls.minDistance,
      maxDistance: controls.maxDistance,
    });
    if (!plan) return;

    labelDue = true;
    const start = performance.now();
    const duration = reducedMotion ? 0 : (ms !== undefined ? ms : plan.durationMs);
    if (duration <= 0) {
      flightUntil = 0;
      applyCamera(flightFrame(plan, from, to, 1));
      // The cut is the whole point for a reduced-motion viewer, so the damping
      // residue of the gesture just before the click is zeroed here too -- left
      // alone it keeps swinging the view for ~50 frames after the camera lands.
      quietControls(controls);
      // Nothing left to animate; the record only survives to outlast a fit tween.
      flight = start < fitUntil
        ? { plan, from, id, start, duration: 0, holdUntil: fitUntil }
        : null;
      return;
    }
    flight = { plan, from, id, start, duration, holdUntil: fitUntil };
    flightUntil = start + duration;
  }

  /**
   * The rail and the note panel float over the canvas, so a plain zoomToFit centres
   * the graph underneath them. A camera view offset slides the frustum instead, which
   * keeps projection, picking and graph2ScreenCoords in agreement.
   */
  /**
   * The rail and the note panel float over the canvas, so a plain zoomToFit centres
   * the graph underneath them. A camera view offset slides the frustum instead, which
   * keeps projection, picking and graph2ScreenCoords in agreement.
   *
   * The target is computed from INTENDED state, never from DOM rectangles: measuring
   * mid-transition produced one value at t+0 and a different one at t+320 ms, and the
   * whole scene jumped ~180 px sideways in a single frame after every click.
   */
  function cssPixels(name, fallback) {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name);
    const value = parseFloat(raw);
    return Number.isFinite(value) ? value : fallback;
  }

  function targetViewOffset() {
    if (embedLike || tierName === 'mobile') return 0;
    const railVisible = !chromeHidden && !railHidden;
    const noteOpen = store.state.selectedId != null;
    const railW = railVisible ? cssPixels('--rail-w', 280) + GUTTER : 0;
    const noteW = noteOpen ? cssPixels('--note-w', 400) + GUTTER : 0;
    return -(railW - noteW) / 2;
  }

  function applyViewOffset(x) {
    const cam = Graph.camera();
    if (!cam || typeof cam.setViewOffset !== 'function') return;
    const w = container.clientWidth || window.innerWidth || 1;
    const h = container.clientHeight || window.innerHeight || 1;
    if (Math.abs(x) < 0.5) {
      if (cam.view && cam.view.enabled) cam.clearViewOffset();
      return;
    }
    cam.setViewOffset(w, h, x, 0, w, h);
  }

  /** Retarget an in-flight tween instead of restarting it from zero. */
  function retargetViewOffset({ instant = false } = {}) {
    const next = targetViewOffset();
    if (instant || reducedMotion) {
      offset.from = next;
      offset.to = next;
      offset.current = next;
      offset.t = OFFSET_MS;
      applyViewOffset(next);
      labelDue = true;
      return;
    }
    if (Math.abs(next - offset.to) < 0.5) return;
    offset.from = offset.current;
    offset.to = next;
    offset.t = 0;
  }

  function stepViewOffset(dtMs) {
    if (offset.t >= OFFSET_MS) return false;
    offset.t = Math.min(OFFSET_MS, offset.t + dtMs);
    const p = offset.t / OFFSET_MS;
    const e = 1 - Math.pow(1 - p, 3);
    offset.current = offset.from + (offset.to - offset.from) * e;
    applyViewOffset(offset.current);
    return true;
  }

  /**
   * The one camera move still driven by the library. It rotates nothing either --
   * `fitToBbox` keeps the current direction to the origin -- but it owns both the
   * camera and the pivot for its duration, so our own flight and follow stand down.
   */
  function fitView(ms = 900, padding = 60) {
    stopAutoRotate();
    pendingFit = false;
    flight = null;
    pendingFly = null;
    followId = null;
    retargetViewOffset({ instant: true });
    const duration = reducedMotion ? 0 : ms;
    Graph.zoomToFit(duration, padding);
    // The library keeps a position tween running for the whole duration and a
    // look-at tween for a third of it, and neither can be cancelled from here.
    // Everything else in this file reads `fitUntil` and stays out of the way.
    fitUntil = performance.now() + duration;
    flightUntil = fitUntil;
    labelDue = true;
  }

  function screenOf(id) {
    const node = store.state.nodes.get(id);
    if (!node || node.x === undefined) return null;
    const p = Graph.graph2ScreenCoords(node.x, node.y, node.z);
    return p ? { x: p.x, y: p.y } : null;
  }

  function setChromeHidden(hidden) {
    chromeHidden = !!hidden;
    document.body.dataset.chrome = hidden ? 'hidden' : 'shown';
    retargetViewOffset();
  }

  /** The chrome's own rail toggle (`G`); it moves the frame the same way `H` does. */
  function setRailHidden(hidden) {
    railHidden = !!hidden;
    retargetViewOffset();
  }

  /**
   * A poll patched display fields in place. Re-read them onto the existing objects --
   * colour, verdict ring, radius, label -- without going near graphData().
   */
  function refreshNode(node) {
    const obj = node.__threeObj;
    if (!obj || !obj.userData.atlas) return;
    refreshNodeObject(obj.userData.atlas, node, store.state.degree.get(node.id) || 0);
    labels.forget(node.id);
    labelDue = true;
  }

  function refreshLink(link) {
    link.__matKey = null;
    activeLinks.add(link);
  }

  function refresh({ patchedNodes = [], patchedLinks = [] } = {}) {
    if (patchedNodes.length) refreshApplicability();
    for (const node of patchedNodes) refreshNode(node);
    for (const link of patchedLinks) refreshLink(link);
  }

  // ------------------------------------------------------------------ setup

  function applyPixelRatio() {
    const ratio = Math.min(tier.pixelRatioCap, window.devicePixelRatio || 1);
    const renderer = Graph.renderer();
    if (renderer) renderer.setPixelRatio(ratio);
    const composer = Graph.postProcessingComposer();
    if (composer && composer.setPixelRatio) composer.setPixelRatio(ratio);
  }

  // ACESFilmicToneMapping is the numeric constant 4. Naming it rather than importing
  // it keeps the two three instances from disagreeing about an enum value.
  const ACES_FILMIC = 4;
  function applyToneMapping() {
    const renderer = Graph.renderer();
    if (!renderer) return;
    renderer.toneMapping = ACES_FILMIC;
    renderer.toneMappingExposure = 1.05;
  }

  function addStardust() {
    const count = 600;
    const positions = new Float32Array(count * 3);
    let seed = 0x9e3779b9;
    const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    for (let i = 0; i < count; i += 1) {
      const r = 1500 + rnd() * 1000;
      const theta = rnd() * Math.PI * 2;
      const phi = Math.acos(2 * rnd() - 1);
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const points = new THREE.Points(geom, new THREE.PointsMaterial({
      color: new THREE.Color('#2a2a33'), size: 1.6, sizeAttenuation: true, fog: false,
    }));
    points.raycast = () => {};
    Graph.scene().add(points);
  }

  Graph.backgroundColor(BG)
    .showNavInfo(false)
    .nodeLabel(() => '')
    .linkLabel(() => '')
    // Custom node objects carry their own radii; this only has to agree with them
    // so the library's own distance heuristics stay in the same units.
    .nodeRelSize(2)
    .nodeResolution(tier.nodeResolution)
    .enableNodeDrag(tier.drag)
    .nodeVisibility(nodeVisible)
    .linkVisibility(linkVisible)
    .nodeThreeObject(nodeObject)
    .linkMaterial(linkMaterialFor)
    .linkWidth(linkWidthOf)
    .linkResolution(LINK_RESOLUTION)
    .linkDirectionalParticles(particlesFor)
    .linkDirectionalParticleSpeed(() => PARTICLE_SPEED)
    .linkDirectionalParticleWidth(1.8)
    .linkDirectionalParticleThreeObject(photonObject)
    .onNodeHover((node) => {
      stopAutoRotate();
      store.hover(node ? node.id : null);
    })
    .onLinkHover(() => stopAutoRotate())
    .onNodeClick((node) => { lastPickAt = performance.now(); stopAutoRotate(); onSelect(node); })
    .onBackgroundClick(() => { stopAutoRotate(); onBackground(); })
    .onEngineTick(() => { engineRunning = true; labelDue = true; })
    .onEngineStop(() => {
      engineRunning = false;
      releasePins();
      refit();
      if (hotReheat) {
        hotReheat = false;
        Graph.d3AlphaDecay(SIM.initial.alphaDecay).d3VelocityDecay(SIM.initial.velocityDecay);
      }
      // A replaced graph with a selection re-acquires it here rather than fitting:
      // one camera move, and the pivot ends on the selected node instead of on the
      // bbox centre. `flyTo` disarms the fit itself.
      const again = refollow;
      refollow = null;
      if (again && store.state.nodes.has(again)) flyTo(again);
      else if (pendingFit) { pendingFit = false; fitView(900, 60); }
      onSettled();
      labelDue = true;
    });

  Graph.d3Force('charge').strength(CHARGE).distanceMax(SIM.chargeDistanceMax);
  const linkForce = Graph.d3Force('link');
  if (linkForce && linkForce.distance) linkForce.distance(linkDistance);

  /**
   * A weak pull toward each axis's origin. d3-force-3d is bundled inside the UMD and
   * never exported, and a force is only a function with an `initialize`, so this is
   * forceX/Y/Z written out: without it the personal graph and the regulator hubs
   * drift apart into two islands.
   */
  function axisForce(axis, strength) {
    const velocity = `v${axis}`;
    let bodies = [];
    const force = (alpha) => {
      const k = strength * alpha;
      for (const body of bodies) body[velocity] -= body[axis] * k;
    };
    force.initialize = (nodes) => { bodies = nodes; };
    return force;
  }
  Graph.d3Force('atlasCentreX', axisForce('x', CENTRE_STRENGTH));
  Graph.d3Force('atlasCentreY', axisForce('y', CENTRE_STRENGTH));
  Graph.d3Force('atlasCentreZ', axisForce('z', CENTRE_STRENGTH));

  applyPixelRatio();

  /**
   * A ball-and-stick rig: a warm key light that FOLLOWS THE CAMERA so the specular
   * highlight stays put while you orbit, a cool rim from behind-right, and enough
   * ambient that the shadow side never reaches black.
   *
   * Every light is built from the UMD's OWN three instance by cloning the defaults
   * it already created -- constructing lights from our module copy would put two
   * different Light classes in one scene graph.
   */
  function rigLights(existing) {
    const defaults = Graph.lights() || [];
    const ambient = defaults.find((l) => l.isAmbientLight);
    const key = defaults.find((l) => l.isDirectionalLight);
    if (!ambient || !key) return null;

    // Both defaults are already in the scene: mutate them in place.
    ambient.color.set('#cfd6e4');
    ambient.intensity = 0.55;
    key.color.set('#fff4e6');
    key.intensity = 2.4;

    // The `lights` prop has triggerUpdate false, so setting it does not schedule a
    // digest and the rim light would never reach the scene. Add it directly, then
    // record the array so a later digest re-adds the same three.
    const rim = existing && existing.rim ? existing.rim : key.clone();
    rim.color.set('#9db4ff');
    rim.intensity = 1.1;
    Graph.scene().add(rim);
    Graph.lights([ambient, key, rim]);
    return { ambient, key, rim };
  }

  let rig = rigLights();

  /**
   * Keep the key light fixed in camera space, as a molecule viewer does, so the
   * specular highlight stays put while you orbit.
   *
   * A DirectionalLight shines from its position toward its target, and the library's
   * default target is an Object3D at the origin that is not in the scene graph. So
   * the position is set RELATIVE TO THE ORIGIN along the camera-space direction --
   * adding the camera position would aim the light at the origin instead.
   */
  const LIGHT_DISTANCE = 600;
  function trackLights() {
    if (!rig) return;
    const e = Graph.camera().matrixWorld.elements;
    const rx = e[0]; const ry = e[1]; const rz = e[2];
    const ux = e[4]; const uy = e[5]; const uz = e[6];
    const fx = -e[8]; const fy = -e[9]; const fz = -e[10];
    const place = (light, right, up, forward) => {
      light.position.set(
        (right * rx + up * ux + forward * fx) * LIGHT_DISTANCE,
        (right * ry + up * uy + forward * fy) * LIGHT_DISTANCE,
        (right * rz + up * uz + forward * fz) * LIGHT_DISTANCE,
      );
    };
    // Key: over the viewer's left shoulder. Rim: behind the scene, to the right.
    place(rig.key, -0.45, 0.8, -1);
    place(rig.rim, 0.7, 0.25, 1);
  }

  const orbit = Graph.controls();
  if (orbit) {
    orbit.enableDamping = true;
    orbit.dampingFactor = 0.08;
    orbit.rotateSpeed = 0.55;
  }

  if (tier.fog) {
    Graph.scene().fog = new THREE.FogExp2(BG, 0.0016);
    addStardust();
  }

  /**
   * Fog density follows the graph's own size, so far nodes always melt out -- but it
   * is a depth cue, not a dimmer. At 0.9/sceneRadius the fitted view was washed to
   * near-invisible, so the coefficient is 0.3 and a hard clamp guarantees a node at
   * the fitted camera distance still shows at least ~75% of its colour.
   */
  function refit() {
    if (!tier.fog) return;
    const box = Graph.getGraphBbox();
    if (!box) return;
    const dx = box.x[1] - box.x[0];
    const dy = box.y[1] - box.y[0];
    const dz = box.z[1] - box.z[0];
    const radius = Math.max(60, Math.hypot(dx, dy, dz) / 2);
    const sceneRadius = radius * 2.6;

    const cam = Graph.camera();
    const cx = (box.x[0] + box.x[1]) / 2;
    const cy = (box.y[0] + box.y[1]) / 2;
    const cz = (box.z[0] + box.z[1]) / 2;
    const camDistance = Math.hypot(cam.position.x - cx, cam.position.y - cy, cam.position.z - cz);
    const fitDistance = Math.max(radius * 2, camDistance);

    const fog = Graph.scene().fog;
    if (fog) fog.density = Math.min(0.3 / sceneRadius, FOG_FIT_LIMIT / fitDistance);
  }

  // --------------------------------------------------------------- listeners

  const canvasEl = Graph.renderer() ? Graph.renderer().domElement : null;

  /** True for input aimed at the WebGL canvas, which is the only thing OrbitControls listens to. */
  function fromCanvas(event) {
    const target = event && event.target;
    if (!canvasEl || !target) return false;
    return target === canvasEl || (target.nodeType === 1 && canvasEl.contains(target));
  }

  store.addEventListener('hover', () => {
    recomputeTargets();
    moveFocusHalo();
    labelDue = true;
  });
  store.addEventListener('highlight', () => { recomputeTargets(); labelDue = true; });
  store.addEventListener('select', (e) => {
    // A selection is the user taking over: the armed first-fit must not yank the
    // camera later. Clearing one moves nothing -- it only stops the follow.
    if (e.detail.id) pendingFit = false;
    else { cancelFlight(); followId = null; refollow = null; }
    decorateSelection(e.detail.id);
    recomputeTargets();
    moveFocusHalo();
    retargetViewOffset();
    labelDue = true;
  });
  store.addEventListener('filter', () => {
    Graph.nodeVisibility(nodeVisible).linkVisibility(linkVisible);
    labelDue = true;
  });

  /**
   * Pointer or wheel input ON THE CANVAS cancels a flight where it stands -- the
   * follow then finishes the centring -- and a new selection immediately after
   * starts a fresh flight from the camera this one was left at. Input anywhere else
   * moves no camera: scrolling the note panel, which opens on every selection, must
   * not stop the flight that selection just started.
   *
   * Keys are filtered twice: not while a field has focus (typing a lot number into
   * search contains `1`-`4` and `f`), and then only the keys this app binds to a
   * camera move.
   */
  const wakePointer = (event) => {
    stopAutoRotate();
    resume();
    if (fromCanvas(event)) cancelFlight();
  };
  const wakeKey = (event) => {
    stopAutoRotate();
    resume();
    if (isTypingTarget(event.target)) return;
    if (event.metaKey || event.ctrlKey || event.altKey || !CAMERA_KEYS.has(event.key)) return;
    pendingFit = false;
    cancelFlight();
  };
  window.addEventListener('pointerdown', wakePointer, { capture: true, passive: true });
  window.addEventListener('touchstart', wakePointer, { capture: true, passive: true });
  window.addEventListener('keydown', wakeKey, { capture: true, passive: true });
  window.addEventListener('wheel', wakePointer, { capture: true, passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause(); else resume();
  });
  window.addEventListener('resize', () => {
    applyPixelRatio();
    retargetViewOffset({ instant: true });
    labelDue = true;
  }, { passive: true });

  // ------------------------------------------------- context loss and touch

  if (canvasEl) {
    // Touching the canvas disarms the first fit. A fit that lands after the viewer
    // has already started orbiting reads as the page yanking the camera away.
    canvasEl.addEventListener('pointerdown', () => { pendingFit = false; }, { passive: true });

    canvasEl.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();
      pause();
      store.setStatus('offline', 'graphics context lost');
      clearTimeout(contextTimer);
      contextTimer = setTimeout(() => {
        const fallback = document.getElementById('fallback');
        if (fallback) { fallback.hidden = false; fallback.classList.add('atlas-open'); }
        store.setStatus('error', 'graphics context could not be restored');
      }, 3000);
    });
    canvasEl.addEventListener('webglcontextrestored', () => {
      clearTimeout(contextTimer);
      contextTimer = 0;
      applyPixelRatio();
      applyToneMapping();
      rig = rigLights(rig);
      resume();
      Graph.refresh();
      store.setStatus('ready', '');
      labelDue = true;
    });

    /**
     * A finger is not a mouse. When the library's own raycast misses, take the
     * nearest node whose projected centre is within 28 CSS px of the tap.
     */
    if (tierName === 'mobile' || embedLike) {
      canvasEl.addEventListener('pointerup', (event) => {
        if (event.pointerType === 'mouse') return;
        setTimeout(() => {
          if (performance.now() - lastPickAt < 250) return;
          const rect = canvasEl.getBoundingClientRect();
          const px = event.clientX - rect.left;
          const py = event.clientY - rect.top;
          let best = null;
          let bestDistance = TAP_SLOP_PX;
          for (const node of store.state.nodes.values()) {
            if (node.x === undefined || !nodeVisible(node) || !node.__threeObj) continue;
            const p = Graph.graph2ScreenCoords(node.x, node.y, node.z);
            if (!p) continue;
            const d = Math.hypot(p.x - px, p.y - py);
            if (d < bestDistance) { bestDistance = d; best = node; }
          }
          if (best) onSelect(best);
        }, 0);
      }, { passive: true });
    }
  }

  applyToneMapping();
  retargetViewOffset({ instant: true });
  raf = requestAnimationFrame(frame);

  function fps() {
    if (frames.length < 2) return 0;
    const span = frames[frames.length - 1] - frames[0];
    return span > 0 ? Math.round(((frames.length - 1) * 1000) / span) : 0;
  }

  function stats() {
    const info = Graph.renderer() ? Graph.renderer().info : null;
    return {
      nodes: store.state.nodes.size,
      links: store.state.links.size,
      calls: info ? info.render.calls : 0,
      tier: tierName,
      bloom: bloomOn,
      labels: labels.count,
      materials: poolSize() + bodyPoolSize(),
      fps: fps(),
      paused,
    };
  }

  return {
    graph: Graph,
    pushGraph,
    refresh,
    flyTo,
    fitView,
    screenOf,
    setChromeHidden,
    setRailHidden,
    recomputeTargets,
    fps,
    stats,
    pause,
    resume,
    setBloom(on) { bloomOn = on; applyPixelRatio(); },
    get bloomOn() { return bloomOn; },
  };
}
