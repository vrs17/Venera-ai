// Pre-paint bootstrap: set the theme and <html lang> BEFORE the app loads, to
// avoid a flash of the wrong palette/locale. Externalized (not inline) so the CSP
// can be a strict `script-src 'self'` with no inline-hash to keep in sync.
//
// Mavzu: saqlangan tanlov 'light' | 'dark' | 'system' (theme.ts bilan bir xil kalit).
// 'system' yoki hech narsa - OS sozlamasi. data-theme HAR DOIM qo'yiladi: xotira
// yopiq bo'lsa ham (maxfiy rejim) OS mavzusi ishlaydi.
// Mobil ilova ichida (WebView, /barno?app=1 - `src/appBridge.ts`): mavzu va til ilovadan, URL'da keladi.
// Saqlanadi (WebView xotirasi - ilovaniki, brauzerniki emas), keyin pastda odatdagidek o'qiladi.
(function () {
  try {
    var q = new URLSearchParams(location.search)
    if (q.get('app') !== '1') return
    var th = q.get('theme')
    if (th === 'light' || th === 'dark') localStorage.setItem('venera_theme', th)
    var l = q.get('lang')
    if (l === 'uz' || l === 'uz-Cyrl' || l === 'ru' || l === 'en') localStorage.setItem('venera_locale', l)
  } catch (e) {}
})();
(function () {
  var dark = false
  try {
    dark = window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch (e) {}
  var t = dark ? 'dark' : 'light'
  try {
    var saved = localStorage.getItem('venera_theme')
    if (saved === 'light' || saved === 'dark') t = saved
  } catch (e) {}
  var root = document.documentElement
  root.setAttribute('data-theme', t)
  // Brauzer paneli (mobil) ilova mavzusiga ergashsin, faqat OS ga emas.
  try {
    var metas = document.querySelectorAll('meta[name="theme-color"]')
    for (var i = 0; i < metas.length; i++) {
      metas[i].setAttribute('content', t === 'dark' ? '#0e0e0f' : '#ffffff')
    }
  } catch (e) {}
})();
(function () {
  try {
    var map = { uz: 'uz-Latn', 'uz-Cyrl': 'uz-Cyrl', ru: 'ru', en: 'en' }
    var l = localStorage.getItem('venera_locale')
    document.documentElement.setAttribute('lang', map[l] || 'uz-Latn')
  } catch (e) {}
})()
