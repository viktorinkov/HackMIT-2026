// Topbar: wordmark, breadcrumb, the Local|Universe segmented control, and a
// live node/link count. Hidden entirely in embed/touch by chrome.css.

export function mountTopbar(ctx) {
  const { store, api, t, dom, toast } = ctx;
  const root = document.getElementById('topbar');
  if (!root) return;

  root.classList.add('atlas-panel');

  const wordmark = dom.el('div', { class: 'atlas-wordmark' }, [t('topbar.wordmark')]);
  const breadcrumb = dom.el('div', { class: 'atlas-breadcrumb' }, [t('topbar.breadcrumb_local')]);

  const localBtn = dom.el(
    'button',
    { type: 'button', 'aria-pressed': 'true', onClick: () => selectView('local') },
    [t('topbar.view_local')]
  );
  const universeBtn = dom.el(
    'button',
    { type: 'button', 'aria-pressed': 'false', onClick: () => selectView('universe') },
    [t('topbar.view_universe')]
  );
  const segmented = dom.el('div', { class: 'atlas-segmented' }, [localBtn, universeBtn]);
  const counts = dom.el('div', { class: 'atlas-counts' }, ['']);

  root.appendChild(wordmark);
  root.appendChild(breadcrumb);
  root.appendChild(segmented);
  root.appendChild(counts);

  let universeLoaded = false;

  async function selectView(view) {
    store.setView(view);
    localBtn.setAttribute('aria-pressed', String(view === 'local'));
    universeBtn.setAttribute('aria-pressed', String(view === 'universe'));
    breadcrumb.textContent =
      view === 'universe' ? t('topbar.breadcrumb_universe') : t('topbar.breadcrumb_local');

    if (view === 'universe' && !universeLoaded) {
      universeLoaded = true;
      try {
        const response = await api.universe();
        store.merge(response);
      } catch {
        universeLoaded = false; // allow a retry on the next toggle
        toast(t('state.error_body'));
      }
    }
  }

  function scanCount() {
    let n = 0;
    for (const node of store.state.nodes.values()) if (node.type === 'scan') n += 1;
    return n;
  }

  function renderCounts() {
    counts.textContent = t('topbar.counts', {
      scans: scanCount(),
      nodes: store.state.nodes.size,
    });
  }

  store.addEventListener('graph', renderCounts);
  store.addEventListener('view', (event) => {
    const view = event.detail?.view;
    if (!view) return;
    localBtn.setAttribute('aria-pressed', String(view === 'local'));
    universeBtn.setAttribute('aria-pressed', String(view === 'universe'));
    breadcrumb.textContent =
      view === 'universe' ? t('topbar.breadcrumb_universe') : t('topbar.breadcrumb_local');
  });

  renderCounts();
}
