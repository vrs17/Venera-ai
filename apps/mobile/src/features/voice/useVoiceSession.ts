/**
 * Ovozli ekran (`/voice`) uchun hook: sessiyani yaratadi, ekran fokusi va ilova holatiga
 * (fon) qarab pauza qiladi, holatni React'ga beradi.
 *
 * - Sessiya EFFEKT ichida yaratiladi (render'da emas) va unmount'da `end()` - StrictMode'da
 *   birinchi tozalash ikkinchi mount'ni buzmaydi: yangi sessiya avvalgisi to'liq yopilgach
 *   (mikrofon bo'shab, audio rejim qaytgach) boshlanadi.
 * - `actions` va `subscribeLevel` hook umri davomida barqaror - UI ularni dependency
 *   sifatida ishlatsa qayta obuna bo'lmaydi.
 * - Tuman darajasi (30 Hz) React holatiga TUSHMAYDI - faqat `subscribeLevel` orqali.
 *
 * `useFocusEffect` (expo-router) shu yerda ruxsat: bu hook faqat `/voice` ekranida.
 */
import { useAudioRecorder } from 'expo-audio';
import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';

import { createVoiceApi, createVoiceChatStream } from '@/api/voice';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { useServices, type Services } from '@/services';

import { createChatPort } from './chatPort';
import { createAudioFiles, createAudioModePort, createClipPlayer, createMicPort, hasMicPermission, keepScreenOn, requestMicPermission, VOICE_PRESET } from './native';
import { realClock, type ClipPlayer, type MicPort } from './ports';
import { stopReadAloud } from './readAloud';
import { createVoiceSession, type VoiceSession } from './session';
import { createSpeaker } from './speaker';
import { devVoiceTrace } from './trace';
import type { LevelListener, UseVoiceSession, VoiceActions, VoiceSnapshot } from './types';
import { SPEED_VALUE, useVoiceSettings } from './voiceSettings';

export const IDLE_SNAPSHOT: VoiceSnapshot = Object.freeze({
  status: 'idle',
  micMuted: false,
  hearing: false,
  suspended: false,
  error: null,
  notice: null,
  turnIds: Object.freeze([]) as readonly string[],
  pendingText: null,
  holdText: null,
  speakingId: null,
  canSpeak: false,
  earpiece: false,
  textOnly: false,
  preparing: false,
  answersSpoken: 0,
}) as VoiceSnapshot;

/** Pleer ochilmasa (juda eski qurilma) - ovozsiz, lekin navbat osilib qolmaydi. */
function silentPlayer(): ClipPlayer {
  const ends = new Set<() => void>();
  return {
    play: () => {
      setTimeout(() => ends.forEach((cb) => cb()), 0);
    },
    pause: () => {},
    resume: () => {},
    stop: () => {},
    positionMs: () => 0,
    onEnd: (cb) => {
      ends.add(cb);
      return () => ends.delete(cb);
    },
    dispose: () => ends.clear(),
  };
}

export function buildVoiceSession(services: Services, mic: MicPort): VoiceSession {
  const uiLang = () => useSettings.getState().uiLang;
  const meetingActive = () => isActive(useRecorderStore.getState().machine);
  const files = createAudioFiles();
  let player: ClipPlayer;
  try {
    player = createClipPlayer();
  } catch {
    player = silentPlayer();
  }
  const speaker = createSpeaker({
    api: createVoiceApi({ client: services.client, tokens: services.session, language: uiLang }),
    files,
    player,
    clock: realClock,
    // Har bo'lakda o'qiladi: sozlamada ovoz/tezlik o'zgarsa keyingi bo'lakdan amal qiladi.
    settings: () => {
      const v = useVoiceSettings.getState();
      return { voice: v.voice, speed: SPEED_VALUE[v.speed] };
    },
    trace: devVoiceTrace('live'),
  });
  return createVoiceSession({
    mic,
    speaker,
    chat: createChatPort(createVoiceChatStream(services.client)),
    stt: { transcribe: (uri, lang, signal) => services.chat.transcribe(uri, 'audio/aac', lang, signal) },
    mode: createAudioModePort(meetingActive),
    files,
    clock: realClock,
    uiLang,
    settings: () => useVoiceSettings.getState(),
    setEarpiece: (on) => useVoiceSettings.getState().set({ earpiece: on }),
    meetingActive,
    requestPermission: requestMicPermission,
    keepAwake: (on) => keepScreenOn('voice', on),
    stopReadAloud,
  });
}

/** Oldingi sessiya to'liq yopilguncha yangisi mikrofonni ochmaydi (bitta yozuvchi). */
let lastEnd: Promise<void> = Promise.resolve();

/**
 * Hook umri davomida yashaydigan "markaz": joriy sessiya (StrictMode'da almashadi),
 * React obunachilari, tuman obunachilari va pauza bayroqlari. Barqaror funksiyalar
 * shu yerda - UI ularni dependency qilsa qayta obuna bo'lmaydi.
 */
function createHub() {
  let session: VoiceSession | null = null;
  const listeners = new Set<() => void>();
  const levels = new Set<LevelListener>();
  let levelOff: (() => void) | null = null;
  let blurred = false;
  let background = false;
  let away = false;

  const emit = () => {
    for (const l of [...listeners]) l();
  };
  const forwardLevels = () => {
    levelOff?.();
    levelOff = null;
    if (session && levels.size) {
      levelOff = session.subscribeLevel((lv, src) => {
        for (const l of [...levels]) l(lv, src);
      });
    }
  };
  const syncAway = () => {
    const next = blurred || background;
    if (next === away) return;
    away = next;
    if (away) session?.suspend();
    else session?.resume();
  };

  const actions: VoiceActions = {
    toggleMute: () => session?.actions.toggleMute(),
    setEarpiece: (on) => session?.actions.setEarpiece(on),
    interrupt: () => session?.actions.interrupt(),
    retry: () => session?.actions.retry(),
    sendPending: () => session?.actions.sendPending(),
    dismissNotice: () => session?.actions.dismissNotice(),
    end: () => session?.actions.end() ?? lastEnd,
  };

  return {
    actions,
    attach(next: VoiceSession): () => void {
      session = next;
      const unsub = next.subscribe(emit);
      forwardLevels();
      emit();
      let cancelled = false;
      void lastEnd.then(() => {
        if (cancelled) return;
        next.start();
        if (away) next.suspend();
      });
      return () => {
        cancelled = true;
        unsub();
        if (session === next) {
          session = null;
          levelOff?.();
          levelOff = null;
        }
        lastEnd = next.actions.end().catch(() => {});
        emit();
      };
    },
    setBlurred(on: boolean) {
      blurred = on;
      syncAway();
    },
    setBackground(on: boolean) {
      background = on;
      syncAway();
    },
    subscribe(l: () => void): () => void {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
    getSnapshot: (): VoiceSnapshot => session?.getSnapshot() ?? IDLE_SNAPSHOT,
    subscribeLevel(l: LevelListener): () => void {
      levels.add(l);
      if (levels.size === 1) forwardLevels();
      return () => {
        levels.delete(l);
        if (!levels.size) {
          levelOff?.();
          levelOff = null;
        }
      };
    },
  };
}

export function useVoiceSession(): UseVoiceSession {
  const services = useServices();
  const recorder = useAudioRecorder(VOICE_PRESET);
  const [hub] = useState(createHub);

  useEffect(() => hub.attach(buildVoiceSession(services, createMicPort(recorder))), [services, recorder, hub]);

  useFocusEffect(
    useCallback(() => {
      hub.setBlurred(false);
      // Sozlamalar (⚙) ochildi: mikrofon bo'shaydi (maxfiylik belgisi o'chadi), qaytganda davom.
      return () => hub.setBlurred(true);
    }, [hub]),
  );

  useEffect(() => {
    const sub = AppState.addEventListener('change', (st) => {
      if (st === 'active') {
        hub.setBackground(false);
        // Odam "Sozlamalarni ochish" bilan mikrofon ruxsatini berib qaytdi - o'zi qayta urinamiz.
        if (hub.getSnapshot().error === 'mic_denied') {
          void hasMicPermission().then((granted) => {
            if (granted && hub.getSnapshot().error === 'mic_denied') hub.actions.retry();
          });
        }
      } else if (st === 'background') hub.setBackground(true);
    });
    return () => sub.remove();
  }, [hub]);

  const snap = useSyncExternalStore(hub.subscribe, hub.getSnapshot);
  return { snap, actions: hub.actions, subscribeLevel: hub.subscribeLevel };
}
