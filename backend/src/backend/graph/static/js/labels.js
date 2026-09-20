// A pooled DOM label layer. DOM stays crisp under bloom, costs no GPU texture and
// reaches the screen through textContent only.
//
// Two rules keep it cheap: sizes are measured with a 2D canvas (never a layout read
// inside the frame loop), and placement is greedy with rectangle rejection so the
// view never becomes a wall of text.

import { NODE_TYPES, typeOf } from './config.js';

// px of projected radius at which a label starts to appear. Relaxed from 5: at the
// fitted camera distance almost every node projects smaller than that.
const FADE_TAU = 2;

const ALWAYS = new Set(['scan', 'regulator']);

function measurer() {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  return (text, mono, lit) => {
    ctx.font = `${lit ? 600 : 500} ${mono ? 11 : 12}px ${mono
      ? 'ui-monospace, SFMono-Regular, Menlo, monospace'
      : 'ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif'}`;
    return Math.min(180, Math.ceil(ctx.measureText(text).width) + 2);
  };
}

export function createLabelLayer(host, { size = 40 } = {}) {
  const measure = measurer();
  const pool = [];
  const sizes = new Map();

  for (let i = 0; i < size; i += 1) {
    const el = document.createElement('div');
    el.className = 'lbl';
    const main = document.createElement('span');
    const sub = document.createElement('span');
    sub.className = 'sub';
    el.appendChild(main);
    el.appendChild(sub);
    host.appendChild(el);
    pool.push({ el, main, sub, text: '', subText: '', cls: '', id: '', w: 0, rpx: 0 });
  }

  let placed = 0;

  function hideFrom(index) {
    for (let i = index; i < pool.length; i += 1) {
      if (pool[i].el.style.opacity !== '0') pool[i].el.style.opacity = '0';
      pool[i].id = '';
    }
  }

  /**
   * candidates: [{id, node, x, y, rpx, score, lit, showSub}] already projected to
   * CSS pixels, best score first is not required -- we sort here.
   */
  function render(candidates) {
    candidates.sort((a, b) => b.score - a.score);
    const taken = [];
    let index = 0;

    for (const c of candidates) {
      if (index >= pool.length) break;
      const opacity = (c.lit || c.always)
        ? 1
        : Math.max(0, Math.min(1, (c.rpx - FADE_TAU) / (FADE_TAU * 0.5)));
      if (opacity <= 0.02) continue;

      const type = typeOf(c.node);
      const mono = !!type.mono;
      const text = String(c.node.label || '');
      if (!text) continue;

      let w = sizes.get(c.id);
      if (w === undefined || c.lit) {
        w = measure(text, mono, c.lit);
        sizes.set(c.id, w);
      }
      const h = c.showSub && c.node.sublabel ? 30 : 16;
      const left = c.x - w / 2;
      const top = c.y + c.rpx + 6;

      let blocked = false;
      for (const r of taken) {
        if (left < r.x1 && left + w > r.x0 && top < r.y1 && top + h > r.y0) { blocked = true; break; }
      }
      if (blocked) continue;
      taken.push({ x0: left, y0: top, x1: left + w, y1: top + h });

      const slot = pool[index];
      index += 1;
      slot.id = c.id;
      slot.w = w;
      slot.rpx = c.rpx;

      const cls = `lbl${mono ? ' mono' : ''}${c.lit ? ' lit' : ''}`;
      if (slot.cls !== cls) { slot.el.className = cls; slot.cls = cls; }
      if (slot.text !== text) { slot.main.textContent = text; slot.text = text; }

      const subText = c.showSub && c.node.sublabel ? String(c.node.sublabel) : '';
      if (slot.subText !== subText) { slot.sub.textContent = subText; slot.subText = subText; }

      slot.el.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
      slot.el.style.opacity = String(opacity);
    }

    hideFrom(index);
    placed = index;
  }

  /**
   * Move the labels already on screen without re-deciding which ones they are.
   * Used during a camera flight: the set is frozen, the positions are not.
   */
  function reposition(project) {
    for (let i = 0; i < placed; i += 1) {
      const slot = pool[i];
      if (!slot.id) continue;
      const p = project(slot.id);
      if (!p) { slot.el.style.opacity = '0'; continue; }
      const left = p.x - slot.w / 2;
      const top = p.y + slot.rpx + 6;
      slot.el.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
    }
  }

  function clear() {
    hideFrom(0);
    for (const slot of pool) slot.id = '';
    placed = 0;
    sizes.clear();
  }

  function destroy() {
    for (const slot of pool) slot.el.remove();
    pool.length = 0;
  }

  return {
    render,
    reposition,
    clear,
    destroy,
    get count() { return placed; },
    get capacity() { return pool.length; },
    forget(id) { sizes.delete(id); },
  };
}

/** Labels that always win a slot regardless of distance. */
export function alwaysLabelled(node) {
  return ALWAYS.has(node.type);
}

export const LABEL_TYPES = Object.keys(NODE_TYPES);
