// Pre-paint bootstrap: set the theme and <html lang> BEFORE the app loads, to
// avoid a flash of the wrong palette/locale. Externalized (not inline) so the CSP
// can be a strict `script-src 'self'` with no inline-hash to keep in sync.
(function () {
  try {
    var t = localStorage.getItem('venera_theme')
    if (t !== 'light' && t !== 'dark') {
      t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    document.documentElement.setAttribute('data-theme', t)
  } catch (e) {}
})();
(function () {
  try {
    var map = { uz: 'uz-Latn', 'uz-Cyrl': 'uz-Cyrl', ru: 'ru', en: 'en' }
    var l = localStorage.getItem('venera_locale')
    document.documentElement.setAttribute('lang', map[l] || 'uz-Latn')
  } catch (e) {}
})()
