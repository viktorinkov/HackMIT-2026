// Persistent chips (#chips), top centre: the demo-data disclosure and a
// connectivity/status indicator. Neither is dismissible — while any demo node
// is on screen the chip stays, because a judge (or a pharmacist) should never
// have to remember that fact from earlier in the demo.

export function mountChips(ctx) {
  const { store, t, dom } = ctx;
  const root = document.getElementById('chips');
  if (!root) return;

  let statusKind = null; // 'offline' | 'demo' | null
  let sawFirstGraph = false;

  function anyDemoNode() {
    for (const node of store.state.nodes.values()) {
      if (node.demo) return true;
    }
    return false;
  }

  function render() {
    dom.clear(root);

    if (!sawFirstGraph) {
      root.appendChild(dom.el('div', { class: 'atlas-chip' }, [t('state.loading')]));
      return;
    }

    if (anyDemoNode()) {
      root.appendChild(dom.el('div', { class: 'atlas-chip atlas-chip--demo' }, [t('chip.demo')]));
    }

    if (statusKind === 'offline') {
      root.appendChild(dom.el('div', { class: 'atlas-chip atlas-chip--offline' }, [t('chip.offline')]));
    } else if (statusKind === 'demo') {
      root.appendChild(dom.el('div', { class: 'atlas-chip atlas-chip--demo' }, [t('chip.demo_data')]));
    }
  }

  store.addEventListener('graph', () => {
    sawFirstGraph = true;
    render();
  });
  store.addEventListener('status', (event) => {
    const kind = event.detail?.kind;
    if (kind === 'offline' || kind === 'demo') statusKind = kind;
    else if (kind === 'ready') statusKind = null;
    render();
  });

  render();
}
