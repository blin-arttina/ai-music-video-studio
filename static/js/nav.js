// Hamburger menu drawer: opens from the left, works with mouse, keyboard,
// and touch. Present on every page via base.html.
(function () {
  const toggle = document.getElementById('nav-toggle');
  const drawer = document.getElementById('site-nav-drawer');
  const overlay = document.getElementById('nav-overlay');
  const closeBtn = document.getElementById('nav-close');
  if (!toggle || !drawer || !overlay) return;

  function openDrawer() {
    drawer.classList.add('open');
    overlay.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
    drawer.setAttribute('aria-hidden', 'false');
    const firstFocusable = drawer.querySelector('a, button');
    if (firstFocusable) firstFocusable.focus();
    document.body.classList.add('nav-open');
  }

  function closeDrawer() {
    drawer.classList.remove('open');
    overlay.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('nav-open');
    toggle.focus();
  }

  toggle.addEventListener('click', () => {
    if (drawer.classList.contains('open')) closeDrawer(); else openDrawer();
  });
  closeBtn.addEventListener('click', closeDrawer);
  overlay.addEventListener('click', closeDrawer);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drawer.classList.contains('open')) {
      closeDrawer();
      return;
    }
    // Simple focus trap while the drawer is open.
    if (e.key === 'Tab' && drawer.classList.contains('open')) {
      const focusables = drawer.querySelectorAll('a, button');
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  // Clicking a link inside the drawer closes it once navigation happens,
  // so returning to a page later doesn't show a stuck-open menu.
  drawer.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => { drawer.classList.remove('open'); });
  });
})();
