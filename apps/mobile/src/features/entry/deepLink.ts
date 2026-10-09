/**
 * Yagona kirish deep link'i (spec 2.2):
 *   venera-rec://record?src=<tile|launcher|volume|shortcut|notification|app|link>&k=<installKey>[&action=stop][&n=<nonce>]
 *
 * Xavfsizlik: istalgan ilova deep link yubora oladi. Shuning uchun yozish
 * AVTOMATIK faqat `k` bizning installKey'ga teng bo'lsa boshlanadi. Begona
 * yoki kalitsiz havola faqat Record ekranini "tayyor" holatda ochadi.
 * Idempotent: yozuv ketayotgan bo'lsa havola uni faqat ko'rsatadi.
 *
 * `n` - har bosishga noyob raqam (plitka/launcher: elapsedRealtime, yorliq:
 * Date.now). NIMA UCHUN: Record ekrani ochiq turganda AYNAN bir xil havola
 * kelsa expo-router qayta render bermaydi va ikkinchi bosish yo'qolardi
 * (masalan, ruxsatni sozlamada yoqib, yon tugmani qayta bosganda).
 */
import type { EntrySource } from '@/api/types';
import type { RecorderStatus } from '@/features/recorder/recorderMachine';

export const ENTRY_SOURCES: EntrySource[] = ['tile', 'launcher', 'volume', 'shortcut', 'notification', 'app', 'link'];
export const KEY_RE = /^[0-9a-f]{64}$/;
export const NONCE_RE = /^[0-9]{1,20}$/;

export interface EntryParams {
  src: EntrySource;
  k: string | null;
  action: 'stop' | null;
  /** Noyob bosish raqami (ixtiyoriy). */
  n?: string | null;
}

type RawParams = Record<string, string | string[] | undefined | null>;

const first = (v: string | string[] | undefined | null): string | null => (Array.isArray(v) ? (v[0] ?? null) : (v ?? null));

export function parseEntryParams(raw: RawParams): EntryParams {
  const src = first(raw.src);
  const k = first(raw.k);
  const action = first(raw.action);
  const n = first(raw.n);
  return {
    src: src && (ENTRY_SOURCES as string[]).includes(src) ? (src as EntrySource) : 'link',
    k: k && KEY_RE.test(k) ? k : null,
    action: action === 'stop' ? 'stop' : null,
    n: n && NONCE_RE.test(n) ? n : null,
  };
}

function parseQuery(qs: string): RawParams {
  const out: RawParams = {};
  for (const part of qs.replace(/^\?/, '').split('&')) {
    if (!part) continue;
    const [k, v = ''] = part.split('=');
    try {
      out[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, ' '));
    } catch {
      /* buzilgan qism tashlanadi */
    }
  }
  return out;
}

export function buildRecordPath(p: EntryParams): string {
  const parts = [`src=${p.src}`];
  if (p.k) parts.push(`k=${p.k}`);
  if (p.action) parts.push(`action=${p.action}`);
  if (p.n) parts.push(`n=${p.n}`);
  return `/record?${parts.join('&')}`;
}

/**
 * `+native-intent` uchun: kiruvchi URL/yo'lni tozalash. Record havolasi
 * bo'lsa faqat src, k, action, n qoladi; boshqa ichki yo'llar o'zgarmaydi;
 * tanimagan narsa bosh sahifaga.
 */
export function sanitizeIncomingPath(path: string): string {
  if (!path) return '/';
  let rest = path.trim();
  const scheme = /^([a-z][a-z0-9+.-]*):\/\/(.*)$/i.exec(rest);
  if (scheme) {
    if (scheme[1].toLowerCase() !== 'venera-rec') return '/';
    rest = `/${scheme[2]}`;
  }
  if (!rest.startsWith('/')) rest = `/${rest}`;
  rest = rest.replace(/^\/+/, '/');
  const qIdx = rest.indexOf('?');
  const pathname = (qIdx >= 0 ? rest.slice(0, qIdx) : rest).replace(/\/+$/, '') || '/';
  const query = qIdx >= 0 ? rest.slice(qIdx + 1) : '';
  if (pathname === '/record') return buildRecordPath(parseEntryParams(parseQuery(query)));
  if (['/', '/meetings', '/settings', '/action-items', '/login'].includes(pathname)) return pathname;
  if (/^\/meeting\/[A-Za-z0-9_-]{1,64}$/.test(pathname)) return pathname;
  return '/';
}

/** Taymingga chidamli taqqoslash (kalit uzunligi qat'iy). */
export function keysEqual(a: string | null, b: string | null): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export type EntryDecision = 'start' | 'stop' | 'show' | 'ready';

const ACTIVE: RecorderStatus[] = ['preparing', 'recording', 'paused', 'stopping'];

export function decideEntry(p: EntryParams, trustedKey: string | null, status: RecorderStatus): EntryDecision {
  const trusted = keysEqual(p.k, trustedKey);
  const active = ACTIVE.includes(status);
  if (p.action === 'stop') {
    if (trusted && (status === 'recording' || status === 'paused')) return 'stop';
    // Yon tugma, ovoz tugmasi va plitka - ALMASHTIRGICH: "to'xtat" keldi-yu, hech narsa yozilmayapti
    // (bayroq eskirgan - ilova yozuv paytida o'ldirilgan). Odam uchun bu bosish "yoz" degani.
    // Bildirishnomadagi Stop'ga tegmaymiz - u eski bildirishnomadan kelishi mumkin.
    if (trusted && !active && (p.src === 'launcher' || p.src === 'volume' || p.src === 'tile')) return 'start';
    return active ? 'show' : 'ready';
  }
  if (active) return 'show';
  return trusted ? 'start' : 'ready';
}

/** Bir xil intent ikki marta qayta ishlanmasin (re-render, fokus); yangi `n` - yangi intent. */
export function entrySignature(p: EntryParams, nonce: string | number = ''): string {
  return `${p.src}|${p.k ?? ''}|${p.action ?? ''}|${p.n ?? ''}|${nonce}`;
}
