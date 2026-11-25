/**
 * Ildiz darajasidagi yozuvchi (spec 2.3). HECH QACHON unmount bo'lmaydi:
 * `useAudioRecorder` unmount'da yozuvchini bo'shatadi - Record ekranidan
 * chiqib ketish yozuvni to'xtatib qo'ymasligi kerak.
 *
 * Holat: toza `recorderMachine` + zustand (UI shu yerdan o'qiydi).
 * Crash safety: navbat qatori (state `recording`, fayl yo'li) `record()`
 * dan OLDIN yoziladi; "Muhim" belgilari har bosishda qatorga yoziladi.
 *
 * Ekran o'chiq / ilova fonda: JS taymerlari to'xtaydi (React Native Android).
 * Shuning uchun limitda avtomatik to'xtash native - preset `maxFileSize`
 * (MediaRecorder MAX_FILESIZE_REACHED). JS 1 s tik faqat ekran yoniq paytdagi
 * aniq to'xtash va 10 daqiqa ogohlantirishi uchun.
 *
 * Native yozuvchi xatodan keyin "tayyorlangan" holatda qolib ketmasligi
 * kerak (aks holda keyingi har start AlreadyPrepared bilan yiqiladi): har
 * xato yo'lida `recorder.stop()` chaqiriladi - u reset qiladi va FGS'dan chiqaradi.
 */
import {
  requestNotificationPermissionsAsync,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  type RecordingStatus,
} from 'expo-audio';
import * as Crypto from 'expo-crypto';
import { File } from 'expo-file-system';
import * as Haptics from 'expo-haptics';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { Platform } from 'react-native';
import { create } from 'zustand';

import type { EntrySource, Lang, TemplateId } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { setRecordingState } from '@/features/entry/nativeEntry';
import { useSettings } from '@/features/settings/settingsStore';
import { newQueueRow } from '@/features/upload/queueStore';
import { isForeground, waitForForeground } from '@/lib/appState';
import { availableDiskBytes, MIN_FREE_BYTES, recordingFile, toFileUri } from '@/lib/paths';
import { uuidV4 } from '@/lib/uuid';
import { useServices } from '@/services';

import { setLastNote } from './marks';
import { createSilenceDetector, levelFromDb, METERING_INTERVAL_MS, pushLevel } from './metering';
import { MEETING_PRESET, presetFromConfig } from './preset';
import {
  classifyNativeEvent,
  DEFAULT_MAX_SEC,
  durationSec,
  initialRecorderState,
  isActive,
  limitState,
  recoverRows,
  reduce,
  type RecorderEvent,
  type RecorderState,
} from './recorderMachine';

export interface StartOptions {
  language: Lang;
  template: TemplateId;
  expectedSpeakers: number | null;
  source: EntrySource;
  title?: string | null;
}

export interface RecorderStoreState {
  machine: RecorderState;
  levels: number[];
  silent: boolean;
  /** Oxirgi saqlangan yozuv (Stop'dan keyin batafsil ekranga o'tish uchun). */
  lastSavedClientId: string | null;
  dispatch(e: RecorderEvent): void;
  setMeter(levels: number[], silent: boolean): void;
  setLastSaved(clientId: string | null): void;
}

export const useRecorderStore = create<RecorderStoreState>((set) => ({
  machine: initialRecorderState,
  levels: [],
  silent: false,
  lastSavedClientId: null,
  dispatch: (e) => set((s) => ({ machine: reduce(s.machine, e) })),
  setMeter: (levels, silent) => set({ levels, silent }),
  setLastSaved: (lastSavedClientId) => set({ lastSavedClientId }),
}));

export interface RecorderActions {
  start(opts: StartOptions): Promise<boolean>;
  pause(): void;
  resume(): void;
  /** Saqlangan clientId yoki null. */
  stop(auto?: boolean): Promise<string | null>;
  mark(note?: string | null): void;
  setLastMarkNote(note: string): void;
  reset(): void;
}

const RecorderContext = createContext<RecorderActions | null>(null);

/** Ruxsat oynasidan keyin ilova ekranga qaytishini shuncha kutamiz (Android 14+ FGS sharti). */
export const FOREGROUND_WAIT_MS = 5000;

/** `record()` paytida ilova ekranda emas - FGS boshlanmaydi, yozuv jim to'xtab qolardi. */
class NotForegroundError extends Error {
  constructor() {
    super('not_foreground');
    this.name = 'NotForegroundError';
  }
}

function removeFileQuietly(uri: string): void {
  try {
    const f = new File(uri);
    if (f.exists) f.delete();
  } catch {
    /* fayl yo'q yoki allaqachon o'chirilgan */
  }
}

export function useRecorder(): RecorderActions {
  const ctx = useContext(RecorderContext);
  if (!ctx) throw new Error('RecorderProvider yo\'q');
  return ctx;
}

/** Testlar uchun: soxta amallarni berish. */
export function RecorderActionsProvider({ value, children }: { value: RecorderActions; children: ReactNode }) {
  return <RecorderContext.Provider value={value}>{children}</RecorderContext.Provider>;
}

export function RecorderProvider({ children }: { children: ReactNode }) {
  const services = useServices();
  const finalizing = useRef<string | null>(null);
  /** Joriy sessiya fayli (file://...): eski sessiyaning kech kelgan hodisasini ajratish uchun. */
  const sessionUri = useRef<string | null>(null);
  const statusRef = useRef<(s: RecordingStatus) => void>(() => {});
  const recorder = useAudioRecorder(MEETING_PRESET, (s) => statusRef.current(s));
  const store = useRecorderStore;

  /**
   * Native yozuvchini bo'shatish. expo-audio `stop()` = stopRecording: FGS'dan
   * chiqaradi, MediaRecorder'ni release qiladi, `isPrepared=false`. Tayyorlanmagan
   * yozuvchida ham xavfsiz. Uning `isFinished` aks-sadosi listener'da e'tiborsiz
   * qoladi (holat allaqachon `stopping`/xato yoki fayl boshqa).
   */
  const releaseNative = useCallback(async () => {
    try {
      await recorder.stop();
    } catch {
      /* allaqachon to'xtagan */
    }
  }, [recorder]);

  /** Oldingi (xato bilan tugagan) sessiyadan native holat qolganmi. */
  const nativeBusy = useCallback((): boolean => {
    try {
      const st = recorder.getStatus();
      return !!(st.canRecord || st.isRecording || recorder.isRecording);
    } catch {
      return false;
    }
  }, [recorder]);

  /** Faol yozuvdagi belgilarni navbat qatoriga yozish - crash bo'lsa ham "Muhim" joylar qoladi. */
  const persistMarks = useCallback(() => {
    const m = store.getState().machine;
    if (!m.clientId || (m.status !== 'recording' && m.status !== 'paused')) return;
    void services.queue.update(m.clientId, { marks: m.marks }).catch(() => {});
  }, [services, store]);

  const finalize = useCallback(
    async (clientId: string) => {
      if (finalizing.current === clientId) return;
      finalizing.current = clientId;
      try {
        const m = store.getState().machine;
        const row = await services.queue.get(clientId);
        let fileUri = row?.fileUri ?? null;
        // Fayl expo-audio nomi bilan yozilgan - spec bo'yicha recordings/<clientId>.aac ga ko'chiramiz.
        if (fileUri) {
          try {
            const target = recordingFile(clientId);
            if (fileUri !== target.uri) {
              new File(fileUri).moveSync(target);
              fileUri = target.uri;
            }
          } catch {
            /* ko'chirib bo'lmasa asl joyida qoladi - navbat yo'lni biladi */
          }
        }
        await services.queue.update(clientId, {
          state: 'stopped',
          endedAt: new Date(m.endedAt ?? Date.now()).toISOString(),
          durationSec: durationSec(m, m.endedAt ?? Date.now()),
          marks: m.marks,
          ...(fileUri ? { fileUri } : {}),
        });
      } finally {
        sessionUri.current = null;
        setRecordingState(false);
        store.getState().dispatch({ type: 'STOPPED' });
        store.getState().setLastSaved(clientId);
        store.getState().setMeter([], false);
        finalizing.current = null;
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
        void services.uploader.runOnce().catch(() => {});
      }
    },
    [services, store],
  );

  /** Faol yozuvni xato bilan yakunlash: to'xtatish, native'ni bo'shatish, faylni saqlash, keyin xato. */
  const failActive = useCallback(
    async (clientId: string, message?: string) => {
      store.getState().dispatch({ type: 'STOP', at: Date.now() });
      await releaseNative();
      await finalize(clientId);
      store.getState().dispatch({ type: 'FAIL', status: 'recorder_error', message });
    },
    [finalize, releaseNative, store],
  );

  // Native hodisalar: bildirishnomadagi Stop, hajm limiti (ekran o'chiq bo'lsa ham), yozuvchi xatosi.
  useEffect(() => {
    statusRef.current = (status: RecordingStatus) => {
      const m = store.getState().machine;
      const clientId = m.clientId;
      if (!clientId) return;
      // Boshqa (eski) faylga tegishli kech hodisa joriy yozuvni to'xtatmasin.
      if (status.url && sessionUri.current && toFileUri(status.url) !== sessionUri.current) return;
      const kind = classifyNativeEvent(status, m.status);
      if (kind === 'ignore') return;
      if (kind === 'error') {
        void failActive(clientId, status.error ?? undefined);
        return;
      }
      // `limit`: native o'zi to'xtatgan (reset + FGS'dan chiqqan) - avtomatik to'xtash.
      // `finished`: bildirishnomadagi Stop.
      store.getState().dispatch({ type: 'STOP', at: Date.now(), auto: kind === 'limit' });
      void finalize(clientId);
    };
  }, [failActive, finalize, store]);

  // Ishga tushganda: yozuvchi faol emas, demak `recording` qatorlar - crash qoldig'i.
  useEffect(() => {
    let alive = true;
    (async () => {
      const rows = await services.queue.list();
      if (!alive) return;
      const active = isActive(store.getState().machine) ? store.getState().machine.clientId : null;
      for (const r of recoverRows(rows, active, new Date().toISOString())) {
        await services.queue.update(r.clientId, r.patch);
      }
      setRecordingState(isActive(store.getState().machine));
      void services.uploader.runOnce().catch(() => {});
    })().catch(() => {});
    return () => {
      alive = false;
    };
  }, [services, store]);

  const stop = useCallback(
    async (auto = false): Promise<string | null> => {
      const m = store.getState().machine;
      if ((m.status !== 'recording' && m.status !== 'paused') || !m.clientId) return null;
      const clientId = m.clientId;
      store.getState().dispatch({ type: 'STOP', at: Date.now(), auto });
      try {
        await recorder.stop();
      } catch {
        /* fayl baribir yaroqli ADTS */
      }
      await finalize(clientId);
      return clientId;
    },
    [finalize, recorder, store],
  );

  // Metering (150 ms) va limit (1 s) - faqat yozilayotganda VA ekran yoniq paytda
  // (fonda JS taymerlari to'xtaydi; u yerda limitni native `maxFileSize` ushlaydi).
  const status = useRecorderStore((s) => s.machine.status);
  useEffect(() => {
    if (status !== 'recording') return;
    const silence = createSilenceDetector();
    silence.reset(Date.now());
    let levels = store.getState().levels;
    const meter = setInterval(() => {
      let db: number | undefined;
      try {
        db = recorder.getStatus().metering;
      } catch {
        db = undefined;
      }
      levels = pushLevel(levels, levelFromDb(db));
      store.getState().setMeter(levels, silence.push(db, Date.now()));
    }, METERING_INTERVAL_MS);
    const tick = setInterval(() => {
      const now = Date.now();
      store.getState().dispatch({ type: 'TICK', at: now });
      if (limitState(store.getState().machine, now) === 'limit') void stop(true);
    }, 1000);
    return () => {
      clearInterval(meter);
      clearInterval(tick);
    };
  }, [status, recorder, store, stop]);

  /** Bir vaqtda faqat bitta start (deep link + tugma, ikki marta bosish): ikkinchisi o'shani kutadi. */
  const starting = useRef<Promise<boolean> | null>(null);

  const actions = useMemo<RecorderActions>(() => {
    const startOnce = async (opts: StartOptions): Promise<boolean> => {
      const before = store.getState().machine;
      if (isActive(before)) return true; // idempotent
      const dispatch = store.getState().dispatch;
      dispatch({ type: 'RESET' });
      store.getState().setLastSaved(null);

      const mic = await requestRecordingPermissionsAsync();
      if (!mic.granted) {
        dispatch({ type: 'FAIL', status: 'permission_denied' });
        return false;
      }
      if (Platform.OS === 'android' && Number(Platform.Version) >= 33) {
        // Usiz expo-audio ekran o'chganda yozuvni pauza qiladi - jim yozib bo'lmaydi.
        const n = await requestNotificationPermissionsAsync();
        if (!n.granted) {
          dispatch({ type: 'FAIL', status: 'notifications_denied' });
          return false;
        }
      }
      const free = availableDiskBytes();
      if (free != null && free < MIN_FREE_BYTES) {
        dispatch({ type: 'FAIL', status: 'disk_low' });
        return false;
      }
      // Android 14+: mikrofon FGS faqat ilova ekranda bo'lganda boshlanadi.
      if (!(await waitForForeground(FOREGROUND_WAIT_MS))) {
        dispatch({ type: 'FAIL', status: 'not_foreground' });
        return false;
      }

      const config = useAuth.getState().config;
      const settings = useSettings.getState();
      const maxSec = (config?.maxMinutes ?? DEFAULT_MAX_SEC / 60) * 60;
      const clientId = uuidV4((n) => Crypto.getRandomBytes(n));
      dispatch({ type: 'PREPARE', clientId, maxSec, source: opts.source });
      let fileUri: string | null = null;
      try {
        await setAudioModeAsync({
          playsInSilentMode: true,
          allowsRecording: true,
          allowsBackgroundRecording: true,
          interruptionMode: 'mixWithOthers',
        });
        // Oldingi xatodan native holat qolgan bo'lsa prepare AlreadyPrepared bilan yiqiladi.
        if (nativeBusy()) await releaseNative();
        const devOverride = __DEV__ ? settings.audioSourceOverride : null;
        await recorder.prepareToRecordAsync(presetFromConfig(config?.recording, devOverride, maxSec));
        const uri = recorder.uri;
        if (!uri) throw new Error('recorder uri yo\'q');
        fileUri = toFileUri(uri);
        sessionUri.current = fileUri;
        // Crash safety: qator record() dan OLDIN.
        await services.queue.insert(
          newQueueRow({
            clientId,
            fileUri,
            language: opts.language,
            template: opts.template,
            expectedSpeakers: opts.expectedSpeakers,
            source: opts.source,
            title: opts.title ?? null,
            startedAt: new Date().toISOString(),
            state: 'recording',
          }),
        );
        if (!isForeground()) throw new NotForegroundError();
        recorder.record();
        dispatch({ type: 'STARTED', at: Date.now() });
        setRecordingState(true);
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
        return true;
      } catch (e) {
        // Native yozuvchi tayyorlangan holatda qolmasin - aks holda keyingi har start yiqiladi.
        await releaseNative();
        try {
          await services.queue.remove(clientId);
        } catch {
          /* qator yozilmagan bo'lishi mumkin */
        }
        if (fileUri) removeFileQuietly(fileUri);
        sessionUri.current = null;
        setRecordingState(false);
        if (e instanceof NotForegroundError) dispatch({ type: 'FAIL', status: 'not_foreground' });
        else dispatch({ type: 'FAIL', status: 'recorder_error', message: e instanceof Error ? e.message : String(e) });
        return false;
      }
    };

    return {
      start(opts) {
        // Parallel ikkinchi start birinchisining tayyorlangan native yozuvchisini
        // "qolib ketgan" deb bo'shatib yuborardi - shuning uchun bitta va'da.
        if (starting.current) return starting.current;
        const p = startOnce(opts).finally(() => {
          starting.current = null;
        });
        starting.current = p;
        return p;
      },
      pause() {
        if (store.getState().machine.status !== 'recording') return;
        try {
          recorder.pause();
          store.getState().dispatch({ type: 'PAUSE', at: Date.now() });
        } catch {
          /* pauza qo'llanmasa yozuv davom etadi */
        }
      },
      resume() {
        const m = store.getState().machine;
        if (m.status !== 'paused' || !m.clientId) return;
        try {
          recorder.record();
          store.getState().dispatch({ type: 'RESUME', at: Date.now() });
        } catch (e) {
          // Shu paytgacha yozilgani saqlanadi; native bo'shatiladi.
          void failActive(m.clientId, e instanceof Error ? e.message : String(e));
        }
      },
      stop,
      mark(note) {
        store.getState().dispatch({ type: 'MARK', at: Date.now(), note: note ?? null });
        persistMarks();
        void Haptics.selectionAsync().catch(() => {});
      },
      setLastMarkNote(note) {
        useRecorderStore.setState((s) => ({ machine: { ...s.machine, marks: setLastNote(s.machine.marks, note) } }));
        persistMarks();
      },
      reset() {
        store.getState().dispatch({ type: 'RESET' });
      },
    };
  }, [failActive, nativeBusy, persistMarks, recorder, releaseNative, services, stop, store]);

  return <RecorderContext.Provider value={actions}>{children}</RecorderContext.Provider>;
}
