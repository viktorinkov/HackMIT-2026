// mountChrome({store, scene, api}) — the one call main.js makes into chrome.
// Builds every panel into its mount point, wires the hotkeys chrome owns,
// and (only in embed mode) starts the Flutter bridge.
//
// DOM APIs and textContent only, everywhere below and in every panel this
// module mounts — none of the string-to-markup sinks a security review
// greps for. `el()` is the one place a string becomes a DOM attribute or
// text node, and it always goes through setAttribute/textContent.

import { t, formatDate } from '../copy.js';
import { cleanText, safeUrl } from '../safe.js';
import { mountBridge, isEmbed } from '../bridge.js';

import { mountTopbar } from './topbar.js';
import { mountRail } from './rail.js';
import { mountNote } from './note.js';
import { mountSearch } from './search.js';
import { mountChips } from './chips.js';
import { mountToasts } from './toasts.js';
import { mountFallback } from './fallback.js';
import { mountHelp } from './help.js';
import { mountKey } from './key.js';

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      node.setAttribute(key, '');
    } else {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === '') continue;
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function addVignetteAndGrain() {
  if (document.querySelector('.atlas-vignette')) return; // idempotent across re-mounts
  document.body.appendChild(el('div', { class: 'atlas-vignette', 'aria-hidden': 'true' }));
  document.body.appendChild(el('div', { class: 'atlas-grain', 'aria-hidden': 'true' }));
}

// index.html links css/tokens.css and css/chrome.css but not css/note.css
// (which chrome owns and index.html predates); load it here instead of
// editing that file.
function ensureNoteStylesheet() {
  if (document.querySelector('link[href="css/note.css"]')) return;
  document.head.appendChild(el('link', { rel: 'stylesheet', href: 'css/note.css' }));
}

/**
 * A small always-on-top card for the two states that need to block the view
 * entirely: the first load ("Mapping your evidence…") and a hard error. A
 * non-fatal offline/demo-data condition is a chip (see panels/chips.js), not
 * this card. Not one of the named mount points — chrome owns its own
 * lifecycle for this element, the same way it owns the vignette/grain
 * overlay.
 */
function mountStateCard({ store, api, t: translate, toast }) {
  const card = el('div', { class: 'atlas-state-card atlas-panel', style: 'display:none' });
  document.body.appendChild(card);

  function hide() {
    card.style.display = 'none';
  }

  function showLoading() {
    clear(card);
    card.style.display = 'block';
    card.appendChild(el('p', {}, [el('span', { class: 'atlas-state-dot' }), translate('state.loading')]));
  }

  function showEmpty() {
    clear(card);
    card.style.display = 'block';
    card.appendChild(el('h2', {}, [translate('state.empty_title')]));
    card.appendChild(el('p', {}, [translate('state.empty_body')]));
  }

  function showError() {
    clear(card);
    card.style.display = 'block';
    card.appendChild(el('h2', {}, [translate('state.error_title')]));
    card.appendChild(el('p', {}, [translate('state.error_body')]));
    card.appendChild(
      el(
        'button',
        {
          type: 'button',
          class: 'atlas-btn atlas-btn--primary',
          onClick: async () => {
            showLoading();
            try {
              const response = await api.graph({ deviceId: store.state.deviceId, demo: store.state.demo });
              store.setGraph(response);
              hide();
            } catch {
              showError();
              toast(translate('state.error_body'));
            }
          },
        },
        [translate('state.retry')]
      )
    );
  }

  let sawFirstGraph = false;
  showLoading();

  store.addEventListener('graph', (event) => {
    sawFirstGraph = true;
    if (store.state.nodes.size === 0 && event.detail?.replaced !== false) showEmpty();
    else hide();
  });
  store.addEventListener('status', (event) => {
    const kind = event.detail?.kind;
    if (kind === 'error' && !sawFirstGraph) showError();
    else if (kind === 'error' && store.state.nodes.size === 0) showError();
  });
}

// `prefers-reduced-motion` collapses every CSS transition/animation to
// ~0ms (chrome.css's global media query), but a few panels also drive a
// *timer* keyed to a transition's normal duration (deferring
// visibility/pointer-events until a close animation finishes). `motionMs`
// keeps those timers in step so reduced motion doesn't leave a panel
// invisible-but-still-interactive (or vice versa) for the timer's full
// un-reduced duration.
function prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

export function mountChrome({ store, scene, api }) {
  const dom = { el, clear };
  const toastsController = mountToasts({ dom, cleanText });
  const toast = toastsController.show;
  const reducedMotion = prefersReducedMotion();
  const motionMs = (ms) => (reducedMotion ? 0 : ms);

  const ctx = { store, scene, api, t, formatDate, cleanText, safeUrl, dom, toast, motionMs };

  addVignetteAndGrain();
  ensureNoteStylesheet();
  mountStateCard({ store, api, t, toast });

  const chips = mountChips(ctx);
  const topbar = mountTopbar(ctx);
  const rail = mountRail(ctx);
  const note = mountNote(ctx);
  const search = mountSearch(ctx);
  const help = mountHelp(ctx);
  const fallback = mountFallback(ctx);
  const key = mountKey(ctx);

  if (isEmbed()) mountBridge({ store, scene, api, search, note });

  async function runPresenterHotkey() {
    try {
      const { scan_id: scanId } = await api.postDemoScan();
      toast(t('toast.demo_scan_posted', { scan_id: scanId || '—' }));
    } catch {
      toast(t('toast.demo_scan_failed'));
    }
  }

  document.addEventListener('keydown', (event) => {
    const targetTag = event.target && event.target.tagName;
    const isTyping =
      targetTag === 'INPUT' || targetTag === 'TEXTAREA' || event.target?.isContentEditable;

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      search.open();
      return;
    }
    if (event.key === '/' && !isTyping) {
      event.preventDefault();
      search.open();
      return;
    }
    if (event.key === '?' && !isTyping) {
      event.preventDefault();
      help.toggle();
      return;
    }
    if ((event.key === 'g' || event.key === 'G') && !isTyping) {
      rail.toggle();
      return;
    }
    if (event.shiftKey && (event.key === 'N' || event.key === 'n') && !isTyping) {
      event.preventDefault();
      runPresenterHotkey();
      return;
    }
    if (event.key === 'Escape') {
      // Ours only if one of our own modals is actually open; otherwise this
      // is the scene's to handle (clearing a selection).
      if (help.isOpen()) {
        help.close();
      } else if (search.isOpen()) {
        search.close();
      } else if (key.isSheetOpen()) {
        key.closeSheet();
      }
    }
  });

  return { topbar, rail, note, search, chips, help, fallback, key };
}
