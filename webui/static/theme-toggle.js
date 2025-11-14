(function () {
  const BODY = document.body;
  const BTN = document.getElementById('themeToggle');
  const LABEL = document.getElementById('themeLabel');

  const THEMES = {
    LIGHT: 'theme-light',
    DARK: 'theme-dark'
  };

  function applyTheme(themeClass) {
    BODY.classList.remove(THEMES.LIGHT, THEMES.DARK);
    BODY.classList.add(themeClass);
    const name = themeClass === THEMES.DARK ? 'Dark' : 'Light';
    if (LABEL) LABEL.textContent = name;
    localStorage.setItem('casharr_theme', name.toLowerCase());
  }

  // Initial load (DEFAULT: DARK unless saved)
  const saved = (localStorage.getItem('casharr_theme') || 'dark').toLowerCase();
  applyTheme(saved === 'dark' ? THEMES.DARK : THEMES.LIGHT);

  // Handler
  if (BTN) {
    BTN.addEventListener('click', () => {
      const isDark = BODY.classList.contains(THEMES.DARK);
      applyTheme(isDark ? THEMES.LIGHT : THEMES.DARK);
    });
  }
})();
