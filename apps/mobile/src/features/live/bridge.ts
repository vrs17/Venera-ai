/**
 * Jonli suhbat (`/live`) - saytdagi /barno sahifasi bilan aloqa: manzil, token, xabarlar. Sof funksiyalar.
 *
 * Sahifa tomoni - `apps/web/src/appBridge.ts` (xabarlar ro'yxati o'sha yerda, ikkalasi bir xil bo'lishi shart).
 *
 * TOKEN FAQAT O'Z SAYTIMIZGA: skript `location.origin` ni tekshiradi - WebView qandaydir yo'l bilan boshqa
 * manzilga o'tib qolsa ham token u yerga tushmaydi (o'tishning o'zini `originWhitelist` to'sadi).
 */

/** Qo'ng'iroq ketayotgan holatlar (sahifa `status` xabari) - ✕ / "orqaga" avval qo'ng'iroqni tugatadi. */
export const ACTIVE_STATUSES: ReadonlySet<string> = new Set(['mic', 'connecting', 'live']);

export type LiveMessage =
  | { type: 'ready' }
  | { type: 'status'; status: string }
  | { type: 'auth' }
  | { type: 'close' };

/** `https://llm.brb-tech.uz/api` -> `https://llm.brb-tech.uz` (RN'dagi `URL` to'liq emas - regex bilan). */
export function liveOrigin(apiBaseUrl: string): string {
  const m = /^https?:\/\/[^/?#]+/i.exec(apiBaseUrl.trim());
  return m ? m[0] : apiBaseUrl.trim().replace(/\/+$/, '');
}

/** Sahifa manzili: ilova rejimi, qo'ng'iroq darhol, mavzu va til ilovaniki. */
export function liveUrl(apiBaseUrl: string, opts: { theme: 'light' | 'dark'; lang: string }): string {
  const q = `app=1&autostart=1&theme=${encodeURIComponent(opts.theme)}&lang=${encodeURIComponent(opts.lang)}`;
  return `${liveOrigin(apiBaseUrl)}/barno?${q}`;
}

export function sameOrigin(url: string | undefined, origin: string): boolean {
  if (!url) return false;
  return url === origin || url.startsWith(`${origin}/`) || url.startsWith(`${origin}?`) || url.startsWith(`${origin}#`);
}

/** Tokenni sahifaga beradi (faqat xotiraga) va kutayotgan `bootstrap` ni uyg'otadi. */
export function tokenScript(origin: string, token: string): string {
  return (
    `(function(){if(location.origin!==${JSON.stringify(origin)})return;` +
    `window.__BARNO_APP_TOKEN__=${JSON.stringify(token)};` +
    `window.dispatchEvent(new Event('barno:token'));})();true;`
  );
}

/** Sahifadagi qo'ng'iroqni tugatish (Speko'da daqiqa hisobi to'xtaydi; sahifa rahmat sahnasiga o'tadi). */
export const END_SCRIPT = '(function(){try{window.__barnoLive&&window.__barnoLive.end();}catch(e){}})();true;';

export function parseLiveMessage(data: unknown): LiveMessage | null {
  if (typeof data !== 'string' || data.length > 2000) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== 'object') return null;
  const { type, status } = raw as { type?: unknown; status?: unknown };
  if (type === 'ready' || type === 'auth' || type === 'close') return { type };
  if (type === 'status' && typeof status === 'string') return { type, status };
  return null;
}
