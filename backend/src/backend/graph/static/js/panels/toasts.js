// Toasts (#toasts): small, transient, bottom-stacked notices. Used by the
// presenter hotkey (Shift+N) and by any panel that needs to report a
// non-blocking failure.

const DEFAULT_DURATION_MS = 4200;

export function mountToasts(ctx) {
  const root = document.getElementById('toasts');
  if (!root) return { show() {} };

  function show(message, { duration = DEFAULT_DURATION_MS } = {}) {
    const toast = ctx.dom.el('div', { class: 'atlas-toast', role: 'status' }, [
      ctx.cleanText(message, 200),
    ]);
    root.appendChild(toast);
    const timer = setTimeout(() => remove(toast), duration);
    toast.addEventListener('click', () => {
      clearTimeout(timer);
      remove(toast);
    });
  }

  function remove(toast) {
    if (!toast.isConnected) return;
    toast.classList.add('atlas-toast--leaving');
    toast.addEventListener(
      'animationend',
      () => {
        toast.remove();
      },
      { once: true }
    );
  }

  return { show };
}
