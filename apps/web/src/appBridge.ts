// Mobil ilova (Barno, Android) ichidagi WebView bilan aloqa - /barno sahifasining "ilova rejimi".
//
// Ilova chat ekranidagi asosiy ovoz tugmasidan shu sahifani `/barno?app=1&autostart=1&theme=..&lang=..` bilan
// ochadi (`apps/mobile/src/app/live.tsx`). Ilova rejimida: sayt sarlavhasi yo'q (yopish tugmasi ilovaniki),
// qo'ng'iroq o'zi boshlanadi, "Bosh sahifa" o'rniga "Yopish" (ilovaga qaytadi), kirish sahifasiga
// yo'naltirilmaydi - token ilovadan keladi. Mavzu va tilni `public/bootstrap.js` URL'dan oladi.
//
// TOKEN. Ilova o'z JWT sini (sayt bilan bir xil server tokeni) `window.__BARNO_APP_TOKEN__` ga qo'yadi - faqat
// xotirada, localStorage ga yozilmaydi: ilova ekrani yopilgach WebView'da token qolmaydi. Android WebView
// "sahifadan oldin" skriptni kafolatlamaydi (u `onPageStarted` da ishlaydi), shuning uchun sahifa `ready`
// xabarini yuboradi va token kelguncha (ko'pi bilan `APP_TOKEN_WAIT_MS`) kutadi (`useAuth.bootstrap`).
//
// XABARLAR, sahifa -> ilova (`window.ReactNativeWebView.postMessage`, JSON):
//   {type:'ready'}            - token kerak;
//   {type:'status', status}   - qo'ng'iroq holati: idle | mic | connecting | live | ended;
//   {type:'auth'}             - token yaroqsiz (401): ilova yangisini olib sahifani qayta ochadi;
//   {type:'close'}            - odam "Yopish" ni bosdi.
// Ilova -> sahifa: `window.__BARNO_APP_TOKEN__ = '…'` + `barno:token` hodisasi; `window.__barnoLive.end()` -
// qo'ng'iroqni tugatish (ilovadagi ✕, "orqaga", ilova uzoq fonda qolsa).

export type AppMessage =
  | { type: 'ready' }
  | { type: 'status'; status: string }
  | { type: 'auth' }
  | { type: 'close' }

declare global {
  interface Window {
    ReactNativeWebView?: { postMessage(message: string): void }
    __BARNO_APP_TOKEN__?: string
    __barnoLive?: { end(): void }
  }
}

/** Ilova tokeni kelmasa shuncha kutiladi, keyin sahifa mehmon sifatida ochiladi (va ilovaga `auth` deydi). */
const APP_TOKEN_WAIT_MS = 3000
const TOKEN_EVENT = 'barno:token'

/** Sahifa mobil ilova ichida ochilganmi: `?app=1` VA ilova ko'prigi bor (oddiy brauzerda `?app=1` hech narsa qilmaydi). */
export function inApp(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return (
      new URLSearchParams(window.location.search).get('app') === '1' &&
      typeof window.ReactNativeWebView?.postMessage === 'function'
    )
  } catch {
    return false
  }
}

/** Ilova bergan URL parametri (`autostart` va h.k.) - faqat ilova rejimida. */
export function appParam(name: string): string | null {
  if (!inApp()) return null
  try {
    return new URLSearchParams(window.location.search).get(name)
  } catch {
    return null
  }
}

export function postToApp(message: AppMessage): void {
  if (!inApp()) return
  try {
    window.ReactNativeWebView?.postMessage(JSON.stringify(message))
  } catch {
    /* ilova ekrani yopilib bo'lgan */
  }
}

/** Ilova bergan token (faqat xotirada) yoki null. */
export function appToken(): string | null {
  if (typeof window === 'undefined') return null
  const token = window.__BARNO_APP_TOKEN__
  return typeof token === 'string' && token ? token : null
}

export function forgetAppToken(): void {
  if (typeof window !== 'undefined') delete window.__BARNO_APP_TOKEN__
}

/** Ilova rejimida token kelguncha kutish. Token allaqachon bor yoki bu oddiy brauzer - darhol. */
export function appTokenReady(timeoutMs = APP_TOKEN_WAIT_MS): Promise<void> {
  if (!inApp() || appToken()) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      window.removeEventListener(TOKEN_EVENT, done)
      window.clearTimeout(timer)
      resolve()
    }
    const timer = window.setTimeout(done, timeoutMs)
    window.addEventListener(TOKEN_EVENT, done)
    postToApp({ type: 'ready' })
  })
}
