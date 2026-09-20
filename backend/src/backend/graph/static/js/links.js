// Link styling: ball-and-stick bonds on desktop, 1px lines on mobile.
//
// Every link material is opaque and shared. "Faint" is a colour lerped toward the
// background, never an alpha, so nothing has to sort and a weak edge can never be
// mistaken for a strong one. Dashes are impossible here: the library rewrites line
// positions every tick without recomputing line distances.
//
// `linkWidth` is in the library's object-flush list, so it is derived from the link's
// CLASS only -- never from hover or selection, which are expressed by swapping the
// material reference.

import * as THREE from 'three';
import {
  BG, HIGHLIGHT_LINK, LINK_CLASS, LINK_STYLE, PARTICLE_COLOR, SEVERITY, linkClass,
} from './config.js';
import { endpointId } from './store.js';

const BG_COLOR = new THREE.Color(BG);
const STEPS = 16;

// Scene-side overrides of config.js (which the lead owns).
export const BOND_COLOR = {
  strong: '#c4c4cf',
  weak: '#8a8a99',
  uncorroborated: '#7a6f55',
  conflict: '#e9973f',
};
export const BOND_WIDTH = {
  strong: 0.5,
  weak: 0.28,
  uncorroborated: 0.28,
  conflict: 0.4,
  alert: 1.0,
};
export const ALERT_EMISSIVE = 0.35;
export const DISTANCE_SCALE = 0.6;
export const LINK_RESOLUTION = 8;

// Desktop draws bonds; mobile keeps hairlines for everything but the alert path.
let sticks = true;
export function setStickMode(on) { sticks = !!on; }
export function stickMode() { return sticks; }

const pool = new Map();

function poolKey(hex, step, mesh, emissive) {
  return `${mesh ? 'm' : 'l'}|${hex}|${step}|${emissive ? 'e' : '_'}`;
}

/** At most (colours x 16 x 2 x 2) materials exist for the whole session. */
export function materialFor(hex, t, mesh, emissive = 0) {
  const step = Math.max(0, Math.min(STEPS, Math.round(t * STEPS)));
  const key = poolKey(hex, step, mesh, emissive > 0);
  let material = pool.get(key);
  if (material) return material;

  const base = new THREE.Color(hex);
  const color = BG_COLOR.clone().lerp(base, step / STEPS);
  if (!mesh) {
    material = new THREE.LineBasicMaterial({ color, fog: true });
  } else {
    material = new THREE.MeshStandardMaterial({
      color,
      roughness: 0.55,
      metalness: 0,
      fog: true,
      emissive: emissive > 0 ? base.clone() : new THREE.Color(0x000000),
      emissiveIntensity: emissive > 0 ? emissive * (step / STEPS) : 0,
    });
  }
  material.userData = { key, step };
  pool.set(key, material);
  return material;
}

export function poolSize() {
  return pool.size;
}

export function classOf(link) {
  return linkClass(link);
}

/** The severity colour of a record endpoint, which is what an alert edge wears. */
export function alertColor(link, nodes) {
  const a = nodes.get(endpointId(link.source));
  const b = nodes.get(endpointId(link.target));
  const record = (a && a.type === 'record') ? a : (b && b.type === 'record' ? b : null);
  const sev = record && record.severity ? SEVERITY[record.severity] : null;
  return sev ? sev.color : SEVERITY.critical.color;
}

/**
 * An alert on a shared lot node belongs to the scans named in the link, so a
 * colliding product is never one hover from someone else's red edge. With no
 * scan ids on either side, treat it as applicable.
 */
export function alertApplies(link, scanKeys) {
  if (!link.alert) return false;
  const ids = link.scan_ids || [];
  if (!ids.length) return true;
  if (!scanKeys || !scanKeys.size) return true;
  for (const id of ids) {
    if (scanKeys.has(id) || scanKeys.has(`scan:${id}`)) return true;
  }
  return false;
}

/**
 * Alert links are stored lot/product -> record, but the evidence has to be seen
 * flowing from the record toward the user's lot. Negative particle speeds do not
 * wrap in this library (progress only wraps above 1), so reverse the endpoints
 * once and remember the stored orientation on the link. `link.id` still encodes the
 * stored direction, which is what lets a merge recognise a reversed link as itself.
 */
export function orientAlertLink(link) {
  if (link.__oriented) return link;
  link.__oriented = true;
  const sourceId = endpointId(link.source);
  const targetId = endpointId(link.target);
  link.__stored = { source: sourceId, target: targetId };
  if (link.alert && typeof targetId === 'string' && targetId.startsWith('rec:')) {
    const s = link.source;
    link.source = link.target;
    link.target = s;
    link.__reversed = true;
  }
  return link;
}

/** Descriptive style for a link in a given lit/dim role. */
export function styleFor(link, role, nodes, applicable) {
  const cls = applicable ? classOf(link) : (link.strong ? LINK_CLASS.STRONG : LINK_CLASS.WEAK);
  const style = LINK_STYLE[cls] || LINK_STYLE.weak;
  const alert = cls === LINK_CLASS.ALERT;
  let hex = alert ? alertColor(link, nodes) : (BOND_COLOR[cls] || BOND_COLOR.weak);
  if (!alert && role === 'lit') hex = HIGHLIGHT_LINK;
  return {
    cls,
    hex,
    alpha: style.alpha,
    mesh: alert || sticks,
    emissive: alert ? ALERT_EMISSIVE : 0,
  };
}

/** Swap the material reference; allocate nothing unless a new pool slot is needed. */
export function applyLinkIntensity(link, intensity, role, nodes, applicable) {
  const obj = link.__lineObj;
  if (!obj) return;
  const { hex, alpha, mesh, emissive } = styleFor(link, role, nodes, applicable);
  const boost = role === 'lit' ? 1.15 : 1;
  const t = Math.max(0, Math.min(1, alpha * intensity * boost));
  const step = Math.max(0, Math.min(STEPS, Math.round(t * STEPS)));
  const key = poolKey(hex, step, mesh, emissive > 0);
  if (link.__matKey === key) return;
  link.__matKey = key;
  obj.material = materialFor(hex, t, mesh, emissive);
}

let _photonMaterial = null;
let _photonGeometry = null;

function photonMaterial() {
  if (_photonMaterial) return _photonMaterial;
  _photonMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color(PARTICLE_COLOR),
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
    fog: false,
    opacity: 0.95,
  });
  return _photonMaterial;
}

function photonGeometry() {
  if (!_photonGeometry) _photonGeometry = new THREE.SphereGeometry(0.9, 8, 8);
  return _photonGeometry;
}

/**
 * A fresh Mesh per particle over shared geometry and a shared material.
 *
 * It must be a Mesh, never a Sprite: our objects come from the second three
 * instance, so three-forcegraph does not keep the object we return -- it rebuilds
 * the photon as its own `Mesh(obj.geometry, obj.material)`. A Mesh carrying a
 * SpriteMaterial makes the renderer read `object.center`, which a Mesh does not
 * have, and every frame throws before anything reaches the canvas.
 *
 * A fresh wrapper is still required: the library only clones when the accessor
 * itself is an object, so one shared instance would be reused for every photon.
 */
export function photonObject() {
  const mesh = new THREE.Mesh(photonGeometry(), photonMaterial());
  mesh.raycast = () => {};
  mesh.renderOrder = 4;
  return mesh;
}

export const PARTICLE_SPEED = 0.0055;

/** Rest distance per class, fed to the d3 link force. Tightened scene-side. */
export function linkDistance(link) {
  const style = LINK_STYLE[classOf(link)] || LINK_STYLE.weak;
  return style.distance * DISTANCE_SCALE;
}

/**
 * Bond radius, from the link's CLASS alone. Never from hover or selection: this
 * accessor is in the library's flush list, so a value that changed with interaction
 * would rebuild every link object on every mouse move.
 */
export function linkWidthOf(link) {
  if (link.__applies) return BOND_WIDTH.alert;
  if (!sticks) return 0;
  return BOND_WIDTH[classOf(link)] || BOND_WIDTH.weak;
}
