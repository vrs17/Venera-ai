/**
 * Yuklash holati SABABI bo'yicha (spec 3.4): ro'yxat pill'i va batafsil sahifadagi
 * karta shu bitta toza funksiyadan o'qiydi.
 *
 * NIMA UCHUN: eski ekran har holatda "Internet bo'lganda o'zi yuklanadi" derdi -
 * server ishlamayotganda, bo'lim yoqilmaganda yoki sessiya tugaganda bu yolg'on
 * edi. Endi haqiqiy sabab (internet yo'q / server javob bermayapti / yoqilmagan /
 * kirish kerak / yuklanmoqda N% / yuklanmadi) va keyingi qadam aytiladi.
 *
 * Tartib muhim (birinchi mos kelgani yutadi) - `__tests__/uploadStatus.test.ts`.
 */
import * as Network from 'expo-network';
import { useEffect, useState } from 'react';

import type { QueueRow } from './queueStore';
import { isPending, SERVER_RESET } from './uploader';
import { uploadPercent } from './useQueue';

export type UploadCause = 'recording' | 'waiting' | 'uploading' | 'offline' | 'server' | 'disabled' | 'auth' | 'failed' | 'done';

export interface UploadStatus {
  cause: UploadCause;
  /** Faqat `uploading` da: 0-100 yoki hajm hali noma'lum bo'lsa null. */
  percent: number | null;
  /** Faqat `server` da: uploader keyingi urinishni qachon qiladi (epoch ms). */
  retryAt: number | null;
  errorCode: string | null;
}

export interface UploadContext {
  /** true/false - telefon tarmog'i; null - noma'lum (Jest, modul yo'q, hali o'qilmagan). */
  online: boolean | null;
}

/** Sessiya tugagan: kutish yordam bermaydi, qayta kirish kerak (navbat saqlanadi). */
const AUTH_CODES = new Set(['auth_required', 'unauthorized']);

export function uploadStatus(row: QueueRow, ctx: UploadContext): UploadStatus {
  const e = row.lastError;
  const base: UploadStatus = { cause: 'waiting', percent: null, retryAt: null, errorCode: e };
  if (row.state === 'recording') return { ...base, cause: 'recording' };
  if (row.state === 'done') return { ...base, cause: 'done' };
  if (row.state === 'failed') return { ...base, cause: 'failed' };
  if (e && AUTH_CODES.has(e)) return { ...base, cause: 'auth' };
  if (ctx.online === false) return { ...base, cause: 'offline' };
  // Tarmoq xatosi, lekin telefon onlayn - demak server yetib bo'lmayapti (internet emas).
  if (e === 'network') return { ...base, cause: ctx.online === true ? 'server' : 'offline', retryAt: ctx.online === true ? row.nextAttemptAt : null };
  // 403 yoki server id'siz 404: bo'lim (yoki bayroq) shu odamga yoqilmagan - kutish yordam bermaydi.
  if (e === 'forbidden' || (e === 'not_found' && !row.serverId)) return { ...base, cause: 'disabled' };
  // Server yarim yuklangan yozuvni tozalagan (72 soat) - uploader o'zi qayta yaratadi: oddiy navbat.
  if (e === SERVER_RESET) return { ...base, cause: 'waiting' };
  if (e) return { ...base, cause: 'server', retryAt: row.nextAttemptAt };
  if (isPending(row) && row.state !== 'stopped') return { ...base, cause: 'uploading', percent: uploadPercent(row) };
  return { ...base, cause: 'waiting' };
}

type NetState = { isConnected?: boolean | null; isInternetReachable?: boolean | null } | null | undefined;

/** Tarmoq holatidan "onlaynmi": aniq bilinmasa null (taxmin qilmaymiz). */
export function onlineFrom(s: NetState): boolean | null {
  if (!s) return null;
  if (s.isConnected === false || s.isInternetReachable === false) return false;
  if (s.isConnected === true) return true;
  return null;
}

/**
 * Telefon onlaynmi (expo-network). Hammasi try/catch ichida (`_layout` dagi kabi):
 * native modul yo'q bo'lsa yoki Jest'da - null, ekran yiqilmaydi.
 */
export function useOnline(): boolean | null {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    let sub: { remove(): void } | null = null;
    try {
      Network.getNetworkStateAsync()
        .then((s) => alive && setOnline(onlineFrom(s)))
        .catch(() => {});
    } catch {
      /* modul yo'q - noma'lum qoladi */
    }
    try {
      sub = Network.addNetworkStateListener((s) => alive && setOnline(onlineFrom(s))) ?? null;
    } catch {
      sub = null;
    }
    return () => {
      alive = false;
      try {
        sub?.remove();
      } catch {
        /* allaqachon olib tashlangan */
      }
    };
  }, []);
  return online;
}
