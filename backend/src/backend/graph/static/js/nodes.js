// Node objects: a glossy lit ball per node, ball-and-stick style, plus the four
// special shapes the vocabulary needs.
//
// Two rules survive from the unlit version. Dimming lerps the body colour toward the
// background (opaque, no sorting) while a small emissive of the same hue keeps a
// dimmed or fogged node's colour identity instead of letting it go black. Halos and
// rings fade by opacity, never toward the background colour -- an additive sprite
// tinted #131316 adds a grey disc.
//
// Body materials are POOLED by (hue, intensity step, selected, flat): a few dozen
// materials serve every node, and the intensity engine swaps the reference.

import * as THREE from 'three';
import { BG, NODE_TYPES, SEVERITY, VERDICT, nodeColor, nodeRadius, typeOf } from './config.js';

const BG_COLOR = new THREE.Color(BG);
const WHITE = new THREE.Color('#ffffff');

// Halved with the halos now restricted to scans, alert ends and the focused node.
const HALO_REST = 0.17;
const HALO_REST_SCAN = 0.23;
const HALO_SCALE = 5.2;
const HALO_SCALE_BIG = 6.0;
const RING_REST = 0.85;

const EMISSIVE = 0.12;
const STEPS = 12;

/** World units per config radius unit. The scene's other distances follow this. */
export const RADIUS_SCALE = 0.8;

let _halo = null;
let _ring = null;
let _disc = null;

function canvas(size) {
  const el = document.createElement('canvas');
  el.width = size;
  el.height = size;
  return el;
}

function toTexture(el) {
  const tex = new THREE.CanvasTexture(el);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

/** Soft radial falloff, the one texture every halo shares. */
export function haloTexture() {
  if (_halo) return _halo;
  const el = canvas(128);
  const ctx = el.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0.00, 'rgba(255,255,255,1)');
  g.addColorStop(0.16, 'rgba(255,255,255,0.58)');
  g.addColorStop(0.38, 'rgba(255,255,255,0.18)');
  g.addColorStop(0.68, 'rgba(255,255,255,0.045)');
  g.addColorStop(1.00, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  _halo = toTexture(el);
  return _halo;
}

/** A thin annulus: the scan's verdict ring, the selection accent and the click pulse. */
export function ringTexture() {
  if (_ring) return _ring;
  const el = canvas(128);
  const ctx = el.getContext('2d');
  ctx.strokeStyle = 'rgba(255,255,255,1)';
  ctx.lineWidth = 4.5;
  ctx.beginPath();
  ctx.arc(64, 64, 55, 0, Math.PI * 2);
  ctx.stroke();
  _ring = toTexture(el);
  return _ring;
}

/** Soft disc for the cluster nebulae. */
export function discTexture() {
  if (_disc) return _disc;
  const el = canvas(64);
  const ctx = el.getContext('2d');
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0.0, 'rgba(255,255,255,1)');
  g.addColorStop(0.35, 'rgba(255,255,255,0.45)');
  g.addColorStop(1.0, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  _disc = toTexture(el);
  return _disc;
}

// ------------------------------------------------------------------ geometry

const geometryCache = new Map();

function geometry(key, make) {
  let g = geometryCache.get(key);
  if (!g) { g = make(); geometryCache.set(key, g); }
  return g;
}

/**
 * One unit sphere per tier; every node scales it. Desktop gets the segment count a
 * ball-and-stick model needs for a clean specular highlight.
 */
function sphereGeometry(tier) {
  const w = tier.nodeResolution >= 12 ? 32 : 14;
  const h = tier.nodeResolution >= 12 ? 24 : 10;
  return geometry(`sphere:${w}x${h}`, () => new THREE.SphereGeometry(1, w, h));
}

export function radiusOf(node, degree = 0) {
  return nodeRadius(node, degree) * RADIUS_SCALE;
}

// ------------------------------------------------------------------ materials

const bodyPool = new Map();
let physicalFailed = false;

function makeBody(color, emissive, flat) {
  const options = {
    color,
    emissive,
    emissiveIntensity: 1,
    roughness: 0.38,
    metalness: 0,
    flatShading: flat,
    fog: true,
  };
  if (!physicalFailed) {
    try {
      return new THREE.MeshPhysicalMaterial({
        ...options,
        clearcoat: 0.55,
        clearcoatRoughness: 0.25,
      });
    } catch (error) {
      physicalFailed = true;
      console.info('[atlas] MeshPhysicalMaterial unavailable, using MeshStandardMaterial');
    }
  }
  return new THREE.MeshStandardMaterial(options);
}

/**
 * The body material for one hue at one intensity step. `t` is the eased intensity
 * clamped to 0..1; `selected` tints toward white; `flat` is the faceted lot crystal.
 */
export function bodyMaterial(hex, t, { selected = false, flat = false } = {}) {
  const step = Math.max(0, Math.min(STEPS, Math.round(t * STEPS)));
  const key = `${hex}|${step}|${selected ? 's' : '_'}|${flat ? 'f' : '_'}`;
  let material = bodyPool.get(key);
  if (material) return material;

  const base = new THREE.Color(hex);
  const color = BG_COLOR.clone().lerp(base, step / STEPS);
  if (selected) color.lerp(WHITE, 0.35);
  material = makeBody(color, base.clone(), flat);
  // The emissive floor is what stops a dimmed or heavily fogged node going black.
  material.emissiveIntensity = EMISSIVE * (0.35 + 0.65 * (step / STEPS));
  material.userData = { key, step };
  bodyPool.set(key, material);
  return material;
}

export function bodyPoolSize() {
  return bodyPool.size;
}

// -------------------------------------------------------------------- sprites

function haloSprite(color, radius, scale, opacity) {
  const material = new THREE.SpriteMaterial({
    map: haloTexture(),
    color: new THREE.Color(color),
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
    fog: false,
    opacity,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.setScalar(radius * scale);
  sprite.raycast = () => {};
  sprite.renderOrder = 2;
  return sprite;
}

/** Camera-facing ring. `additive` for the selection accent and the click pulse. */
export function ringSprite(color, radius, { additive = false, opacity = RING_REST } = {}) {
  const material = new THREE.SpriteMaterial({
    map: ringTexture(),
    color: new THREE.Color(color),
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    transparent: true,
    depthWrite: false,
    fog: false,
    opacity,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.setScalar(radius);
  sprite.raycast = () => {};
  sprite.renderOrder = 3;
  return sprite;
}

/** One reusable halo the scene reparents onto whatever is hovered or selected. */
export function focusHalo() {
  return haloSprite('#ffffff', 1, 1, HALO_REST_SCAN);
}

function nebula(color, count, radius) {
  const n = Math.max(12, Math.min(160, count));
  const positions = new Float32Array(n * 3);
  // Deterministic gaussian-ish cloud: no Math.random, so a re-render never twitches.
  let seed = 0x2f6e2b1;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  for (let i = 0; i < n; i += 1) {
    const g = (rnd() + rnd() + rnd() - 1.5) * 0.9;
    const theta = rnd() * Math.PI * 2;
    const phi = Math.acos(2 * rnd() - 1);
    const r = radius * (0.35 + Math.abs(g));
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = r * Math.cos(phi);
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    map: discTexture(),
    color: new THREE.Color(color),
    size: Math.max(1.2, radius * 0.22),
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
    fog: false,
    opacity: 0.55,
  });
  const points = new THREE.Points(geom, material);
  points.raycast = () => {};
  return points;
}

/** The reference has no glow: only you, the alert path and the focused node bloom. */
export function wantsHalo(node, alertConnected) {
  return node.type === 'scan' || !!alertConnected;
}

// ---------------------------------------------------------------------- build

export function createNodeObject(node, { tier, degree = 0, seed = 0, alertConnected = false }) {
  const type = typeOf(node);
  const radius = radiusOf(node, degree);
  const color = nodeColor(node);
  const shape = type.shape || 'sphere';
  const flat = shape === 'octa';
  const group = new THREE.Group();

  const body = bodyMaterial(color, 1, { flat });
  let core;
  if (flat) {
    core = new THREE.Mesh(geometry('octa', () => new THREE.OctahedronGeometry(1, 0)), body);
    core.scale.setScalar(radius * 1.35);
  } else {
    core = new THREE.Mesh(sphereGeometry(tier), body);
    core.scale.setScalar(radius);
  }
  group.add(core);

  const data = {
    id: node.id,
    core,
    base: new THREE.Color(color),
    baseHex: color,
    flat,
    radius,
    halo: null,
    ring: null,
    shell: null,
    shellMaterial: null,
    cloud: null,
    haloRest: HALO_REST,
    shimmer: node.type === 'scan' || node.severity === 'critical',
    spin: node.type === 'scan' && (node.status === 'pending' || node.status === 'partial'),
    intensity: 1,
    grow: 0,
    selected: false,
    matKey: null,
  };

  if (wantsHalo(node, alertConnected)) {
    const big = node.type === 'scan' || node.type === 'regulator' || node.type === 'record';
    data.haloRest = node.type === 'scan' ? HALO_REST_SCAN : HALO_REST;
    data.halo = haloSprite(color, radius, big ? HALO_SCALE_BIG : HALO_SCALE, data.haloRest);
    group.add(data.halo);
  }

  if (shape === 'ring') {
    const verdict = node.verdict && VERDICT[node.verdict] ? VERDICT[node.verdict].color : '#8a8a93';
    data.ring = ringSprite(verdict, radius * 3.1);
    group.add(data.ring);
  } else if (shape === 'hub') {
    const shellMaterial = new THREE.MeshBasicMaterial({
      color: new THREE.Color(color),
      wireframe: true,
      transparent: true,
      opacity: 0.35,
      fog: true,
    });
    const shell = new THREE.Mesh(geometry('ico', () => new THREE.IcosahedronGeometry(1, 0)), shellMaterial);
    shell.scale.setScalar(radius * 2.3);
    shell.raycast = () => {};
    data.shell = shell;
    data.shellMaterial = shellMaterial;
    group.add(shell);
  } else if (shape === 'cloud') {
    // The remainder is read as volume: a larger "+N more" is visibly a larger cloud.
    const total = Math.max(2, node.count || 2);
    const count = Math.round(12 * Math.log2(total + 1));
    const spread = (6 + 3 * Math.log10(total)) * RADIUS_SCALE * 0.525;
    data.cloud = nebula(color, count, spread);
    group.add(data.cloud);
  }

  initNodeAnimation(data, seed);
  group.userData.atlas = data;
  return group;
}

/**
 * Re-read the display fields a poll may have patched -- verdict, severity, status,
 * degree -- without touching the object's identity or the simulation.
 */
export function refreshNodeObject(data, node, degree = 0) {
  const color = nodeColor(node);
  if (color !== data.baseHex) {
    data.baseHex = color;
    data.base.set(color);
    data.matKey = null;
    if (data.halo) data.halo.material.color.set(color);
    if (data.shellMaterial) data.shellMaterial.color.set(color);
  }
  const radius = radiusOf(node, degree);
  if (Math.abs(radius - data.radius) > 0.01) {
    data.radius = radius;
    data.core.scale.setScalar(data.flat ? radius * 1.35 : radius);
    if (data.shell) data.shell.scale.setScalar(radius * 2.3);
  }
  if (data.ring) {
    const verdict = node.verdict && VERDICT[node.verdict] ? VERDICT[node.verdict].color : '#8a8a93';
    data.ring.material.color.set(verdict);
    data.spin = node.status === 'pending' || node.status === 'partial';
    if (!data.spin) data.ring.material.rotation = 0;
  }
  data.shimmer = node.type === 'scan' || node.severity === 'critical';
  applyNodeIntensity(data, data.intensity);
}

// ------------------------------------------------------------------ intensity

/** i is the eased intensity; 1.0 is "lit", 0.7 rest, 0.12 dimmed. */
export function applyNodeIntensity(data, i) {
  const clamped = Math.max(0, Math.min(1, i));
  const step = Math.round(clamped * STEPS);
  const key = `${step}|${data.selected ? 's' : '_'}`;
  if (data.matKey !== key) {
    data.matKey = key;
    data.core.material = bodyMaterial(data.baseHex, clamped, {
      selected: data.selected,
      flat: data.flat,
    });
  }

  if (data.halo) data.halo.material.opacity = data.haloRest * clamped * clamped * data.haloFlash();
  if (data.ring) data.ring.material.opacity = RING_REST * clamped;
  if (data.shellMaterial) {
    data.shellMaterial.opacity = 0.35 * clamped;
    data.shellMaterial.color.copy(BG_COLOR).lerp(data.base, clamped);
  }
  if (data.cloud) data.cloud.material.opacity = 0.55 * clamped;
}

function easeOutBack(t) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const u = t - 1;
  return 1 + c3 * u * u * u + c1 * u * u;
}

/** Per-frame decoration: growth on expand, shimmer, the pending ring's rotation. */
export function animateNode(data, elapsedMs, dtMs, group) {
  let busy = false;
  if (data.grow > 0) {
    data.grow = Math.max(0, data.grow - dtMs);
    const t = 1 - data.grow / data.growDuration;
    group.scale.setScalar(Math.max(0.001, easeOutBack(t)));
    data.growFlash = 1 + 1.5 * (1 - t);
    busy = true;
    if (data.grow === 0) { group.scale.setScalar(1); data.growFlash = 1; }
  }
  if (data.spin && data.ring) {
    data.ring.material.rotation = (elapsedMs / 2600) * Math.PI * 2;
    busy = true;
  }
  if (data.shimmer && data.halo) {
    data.shimmerPhase = 1 + 0.04 * Math.sin(elapsedMs / 780 + data.phase);
    busy = true;
  }
  return busy;
}

export function initNodeAnimation(data, seedIndex) {
  data.phase = (seedIndex % 17) * 0.37;
  data.growDuration = 500;
  data.growFlash = 1;
  data.shimmerPhase = 1;
  data.haloFlash = function haloFlash() {
    return this.growFlash * this.shimmerPhase;
  };
}

export const NODE_TYPE_KEYS = Object.keys(NODE_TYPES);
export const SEVERITY_KEYS = Object.keys(SEVERITY);
