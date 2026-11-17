/**
 * Ilova servislari bilan ulash: yuborish bog'liqliklari, joriy variantlar (egasi, til,
 * server chegarasi) va avtomatik yuborish triggerlari (ilova ochilishi va oldinga chiqishi).
 *
 * `<CallAutoSend />` ildiz layout'ga bir marta qo'yiladi (integratsiya eslatmasi). U qo'yilmaguncha
 * "Qo'ng'iroqlar" bo'limi ham shu hook'ni ishlatadi - skan single-flight, ikki joydan chaqirilsa
 * ham bitta ishlaydi, yuborish esa clientId bo'yicha idempotent.
 */
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { useAuth } from '@/features/auth/authStore';
import { copyToAppStorage, hasAudioReadPermission, listCallRecordings } from '@/features/entry/nativeEntry';
import { currentT, useSettings } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { toFileUri } from '@/lib/paths';
import { useServices, type Services } from '@/services';

import { runAutoSendOnce, type AutoSendResult, type SizeMemory } from './autoSend';
import { useCalls } from './callsStore';
import { callsSupported } from './permission';
import { sendCallRecording, type CallSendDeps, type SendOptions } from './send';

/** "Tinch" bo'lishini kutayotgan yozuv bo'lsa qayta skan oralig'i. */
export const RECHECK_MS = 20_000;
/** Ketma-ket qayta skanlar chegarasi (hajmi to'xtamay o'zgarayotgan g'alati fayl uchun). */
export const MAX_RECHECKS = 12;

export function callSendDeps(services: Pick<Services, 'queue' | 'uploader' | 'files'>): CallSendDeps {
  return {
    queue: services.queue,
    uploader: services.uploader,
    copy: copyToAppStorage,
    removeFile: (uri) => services.files.remove(uri),
    markSent: (key, clientId) => useCalls.getState().markSent(key, clientId),
    toFileUri,
  };
}

/** Egasi: kirgan foydalanuvchi; hali o'qilmagan bo'lsa (oflayn ochilish) - oxirgi egasi. */
export function currentSendOptions(t?: TFn): SendOptions {
  const calls = useCalls.getState();
  const auth = useAuth.getState();
  return {
    owner: auth.user ? String(auth.user.actorId) : calls.owner,
    language: calls.language ?? useSettings.getState().lastLanguage,
    maxBytes: auth.config?.maxUploadBytes || null,
    maxVideoBytes: auth.config?.maxVideoUploadBytes || null,
    t: t ?? currentT(),
  };
}

const memory: SizeMemory = new Map();
let inflight: Promise<AutoSendResult> | null = null;
const NOTHING: AutoSendResult = { sent: 0, recheck: false };

/** Bitta avtomatik skan (single-flight). Shartlar bajarilmasa hech narsa qilmaydi. */
export function kickCallAutoSend(services: Pick<Services, 'queue' | 'uploader' | 'files'>): Promise<AutoSendResult> {
  if (inflight) return inflight;
  const p = (async (): Promise<AutoSendResult> => {
    const auth = useAuth.getState();
    // Foydalanuvchi aniq bo'lmaguncha yubormaymiz: boshqa odamning sozlamasi bilan yuborilmasin.
    if (auth.status !== 'signedIn' || !auth.user) return NOTHING;
    if (auth.config && !auth.config.enabled) return NOTHING;
    useCalls.getState().adoptOwner(String(auth.user.actorId));
    const st = useCalls.getState();
    if (!callsSupported() || !st.enabled || !st.autoSend || st.consentAt == null) return NOTHING;
    if (!hasAudioReadPermission()) return NOTHING;
    const deps = callSendDeps(services);
    const opts = currentSendOptions();
    return runAutoSendOnce({
      list: listCallRecordings,
      state: () => useCalls.getState(),
      send: (r) => sendCallRecording(deps, r, opts),
      memory,
      maxBytes: opts.maxBytes,
    });
  })()
    .catch(() => NOTHING)
    .finally(() => {
      inflight = null;
    });
  inflight = p;
  return p;
}

/** Test uchun: skan xotirasi va single-flight holatini tozalash. */
export function __resetCallAutoSend(): void {
  memory.clear();
  inflight = null;
}

/** Kirgan foydalanuvchini calls holatining egasi qiladi (boshqa odam bo'lsa holat tozalanadi). */
export function useCallsOwner(): void {
  const actorId = useAuth((s) => s.user?.actorId ?? null);
  useEffect(() => {
    if (actorId != null) useCalls.getState().adoptOwner(String(actorId));
  }, [actorId]);
}

/** Ilova ochilganda va oldinga chiqqanda (yoqilgan bo'lsa) yangi qo'ng'iroqlarni yuboradi. */
export function useCallAutoSend(): void {
  const services = useServices();
  const status = useAuth((s) => s.status);
  const actorId = useAuth((s) => s.user?.actorId ?? null);
  const on = useCalls((s) => s.enabled && s.autoSend && s.consentAt != null);
  useCallsOwner();

  useEffect(() => {
    if (!on || status !== 'signedIn' || actorId == null || !callsSupported()) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let rechecks = 0;
    const run = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      void kickCallAutoSend(services).then((r) => {
        if (!alive) return;
        if (!r.recheck) {
          rechecks = 0;
          return;
        }
        if (rechecks >= MAX_RECHECKS) return;
        rechecks++;
        timer = setTimeout(() => {
          timer = null;
          // Fonda skanlamaymiz: qo'ng'iroq davom etayotgan bo'lishi mumkin; qaytganda 'active' turtadi.
          if (alive && AppState.currentState === 'active') run();
        }, RECHECK_MS);
      });
    };
    run();
    const sub = AppState.addEventListener('change', (s) => {
      if (s !== 'active') return;
      rechecks = 0;
      run();
    });
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      sub.remove();
    };
  }, [on, status, actorId, services]);
}

/** Ildiz layout uchun: hech narsa chizmaydi, faqat avtomatik yuborish triggerlari. */
export function CallAutoSend(): null {
  useCallAutoSend();
  return null;
}
