// Help overlay ("?"): every keyboard shortcut in backend/src/backend/graph/FRONTEND_CONTRACT.md,
// chrome's and the scene's alike — a person looking for shortcuts does not
// care which stream owns which key.

const SHORTCUTS = [
  { keys: 'Cmd/Ctrl K', copyKey: 'help.search' },
  { keys: '/', copyKey: 'help.search' },
  { keys: 'Esc', copyKey: 'help.esc' },
  { keys: 'F', copyKey: 'help.fit' },
  { keys: 'L', copyKey: 'help.local_universe' },
  { keys: 'H', copyKey: 'help.hide_chrome' },
  { keys: '1 – 4', copyKey: 'help.presenter_stops' },
  { keys: 'G', copyKey: 'help.rail' },
  { keys: 'Shift N', copyKey: 'help.presenter' },
  { keys: '?', copyKey: 'help.help' },
];

export function mountHelp(ctx) {
  const { t, dom } = ctx;
  // index.html's documented mount points do not include one for the help
  // overlay; chrome owns the "?" shortcut list end to end, so it creates its
  // own container the same way it creates the vignette/grain overlay.
  let root = document.getElementById('help');
  if (!root) {
    root = dom.el('div', { id: 'help' });
    document.body.appendChild(root);
  }

  const card = dom.el('div', { class: 'atlas-help-card atlas-panel' });
  card.appendChild(dom.el('h2', {}, [t('help.title')]));

  for (const { keys, copyKey } of SHORTCUTS) {
    const label = copyKey === 'help.presenter_stops' ? t(copyKey, { n: '1–4' }) : t(copyKey);
    card.appendChild(
      dom.el('div', { class: 'atlas-help-row' }, [
        dom.el('span', {}, [label]),
        dom.el('span', { class: 'atlas-kbd' }, [keys]),
      ])
    );
  }

  const closeRow = dom.el(
    'button',
    { type: 'button', class: 'atlas-btn', style: 'margin-top:12px;width:100%', onClick: () => close() },
    [t('help.close')]
  );
  card.appendChild(closeRow);
  root.appendChild(card);

  root.addEventListener('mousedown', (event) => {
    if (event.target === root) close();
  });

  function isOpen() {
    return root.classList.contains('atlas-open');
  }
  function open() {
    root.classList.add('atlas-open');
  }
  function close() {
    root.classList.remove('atlas-open');
  }
  function toggle() {
    if (isOpen()) close();
    else open();
  }

  return { open, close, toggle, isOpen };
}
