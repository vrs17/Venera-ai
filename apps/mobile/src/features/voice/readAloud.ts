/**
 * "Tinglash" - chatdagi javobni ovoz chiqarib o'qish (javob ostidagi 🔊 va kichik pleer).
 *
 * Jonli suhbat bilan AYNI dvigatel (`speaker.ts` + gap navbati): birinchi bo'lak (<=60 belgi,
 * ~2.2 s sintez) yangraydi, qolgani o'qilayotganda tayyorlanadi. Bir vaqtda BITTA javob o'qiladi -
 * boshqasi bosilsa avvalgisi to'xtaydi (web `readAloud.ts` bilan bir xil qoida).
 *
 * Dvigatel birinchi bosishda yaratiladi (import paytida EMAS): native pleer faqat kerak
 * bo'lganda ochiladi va Jest'da modulni import qilish xavfsiz.
 *
 * DIQQAT: bu fayl expo-router'ni ishlatmaydi - chat ekrani testlari uni faqat
 * `{ router }` bilan mock qiladi.
 */
import { useMemo } from 'react';
import { AppState } from 'react-native';
import { create } from 'zustand';

import { createVoiceApi } from '@/api/voice';
import { useChat } from '@/features/chat/chatStore';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { currentT, useSettings } from '@/features/settings/settingsStore';
import type { TKey, UiLang } from '@/i18n';
import { useServices, type Services } from '@/services';
import { showToast } from '@/ui/errors';

import { createSentenceQueue, type SentenceQueue } from './chunker';
import { createAudioFiles, createAudioModePort, createClipPlayer, keepScreenOn } from './native';
import { realClock, type AudioFiles, type AudioModePort, type ClipPlayer } from './ports';
import { createSpeaker, ttsOffThisRun, type Speaker, type SpeakerDeps, type SpeakerEvent } from './speaker';
import { answerBody, cleanForSpeech, isSpeakable } from './speechText';
import { devVoiceTrace } from './trace';
import type { ReadAloudControls, ReadAloudState } from './types';
import { SPEED_VALUE, useVoiceSettings } from './voiceSettings';

export const PREVIEW_KEY = '__preview__';
/** Sozlamalardagi namuna - ovoz mazmuni (o'qiladigan matn), interfeys yozuvi emas. */
export const PREVIEW_TEXT = "Salom! Men Barno. Savolingizni ovoz bilan bering, men javobni o'qib beraman.";

/** Kalitlar `nav.ts` qismida (UI qatlami qo'shadi) - topilmasa kalitning o'zi ko'rinadi. */
const tkey = (k: string) => k as TKey;
const TOAST: Record<'off' | 'failed' | 'shortened', TKey> = {
  off: tkey('nav.voice.ttsOff'),
  failed: tkey('nav.voice.ttsFailed'),
  shortened: tkey('nav.voice.shortened'),
};

const IDLE: ReadAloudState = { key: null, phase: 'idle', index: 0, total: null };

export const useReadAloud = create<ReadAloudState>(() => ({ ...IDLE }));

export interface ReadAloudEngine {
  speaker: Speaker;
  mode: AudioModePort;
}

/** Native qismlar (testda soxtasi): API, fayllar, pleer, audio rejim. */
export interface ReadAloudParts {
  api: SpeakerDeps['api'];
  files: AudioFiles;
  player: ClipPlayer;
  mode: AudioModePort;
  /** Ekranni yoqiq ushlash (testda soxtasi). */
  keepAwake?: (on: boolean) => void;
}

type PartsFactory = (services: Services) => ReadAloudParts;

let engine: ReadAloudEngine | null = null;
let queue: SentenceQueue | null = null;
let factory: PartsFactory | null = null;
let unsubSpeaker: (() => void) | null = null;
let watchers: (() => void) | null = null;
let keepAwake: (on: boolean) => void = (on) => keepScreenOn('read', on);
let awake = false;

const meetingActive = () => isActive(useRecorderStore.getState().machine);

function defaultParts(services: Services): ReadAloudParts {
  return {
    api: createVoiceApi({ client: services.client, tokens: services.session, language: () => useSettings.getState().uiLang }),
    files: createAudioFiles(),
    player: createClipPlayer(),
    mode: createAudioModePort(meetingActive),
    keepAwake: (on) => keepScreenOn('read', on),
  };
}

function buildEngine(parts: ReadAloudParts): ReadAloudEngine {
  const speaker = createSpeaker({
    api: parts.api,
    files: parts.files,
    player: parts.player,
    clock: realClock,
    // O'z papkasi: jonli suhbat yopilganda `voice/` tozalanadi - o'qish fayli o'chib ketmasin.
    dir: 'voice-read',
    // Har bo'lakda o'qiladi - sozlamada tanlangan ovoz va tezlik darhol amal qiladi.
    settings: () => {
      const v = useVoiceSettings.getState();
      return { voice: v.voice, speed: SPEED_VALUE[v.speed] };
    },
    trace: devVoiceTrace('read'),
  });
  return { speaker, mode: parts.mode };
}

/** O'qib bo'ladimi: faqat uz interfeys, ovoz serverda yoqilgan va javobda o'qiladigan matn bor. */
export function canReadAloud(markdown: string, uiLang: UiLang): boolean {
  if (uiLang !== 'uz' || ttsOffThisRun()) return false;
  const body = answerBody(markdown ?? '');
  return isSpeakable(body, 'uz') && cleanForSpeech(body).length > 0;
}

/** Istalgan joydan, istalgan paytda xavfsiz (jonli suhbat va diktovka boshlanishida). */
export function stopReadAloud(): void {
  engine?.speaker.stop();
  queue = null;
  if (useReadAloud.getState().key !== null) useReadAloud.setState({ ...IDLE });
}

function onEvent(e: SpeakerEvent) {
  const st = useReadAloud.getState();
  if (st.key === null) return;
  const t = currentT();
  switch (e.type) {
    case 'speech_start':
      if (e.key === st.key && st.phase === 'loading') useReadAloud.setState({ phase: 'playing' });
      break;
    case 'chunk':
      if (e.key !== st.key) break;
      useReadAloud.setState({
        index: e.index,
        total: queue?.finished ? queue.taken : null,
        phase: st.phase === 'paused' ? 'paused' : 'playing',
      });
      break;
    case 'speech_end':
      if (e.key !== st.key) break;
      if (e.shortened) showToast(t(TOAST.shortened));
      queue = null;
      useReadAloud.setState({ ...IDLE });
      break;
    case 'error':
      if (e.key !== st.key) break;
      // Tayyor bo'laklar baribir oxirigacha o'qiladi; keyin `speech_end` holatni tozalaydi.
      showToast(t(e.code === 'off' ? TOAST.off : TOAST.failed));
      break;
    default:
      break;
  }
}

/**
 * O'qilayotganda ekran o'chmasin: uzun javob 1-3 daqiqa tegmasdan tinglanadi, ekran
 * o'chsa ilova fonga o'tib o'qish to'xtardi. Pauzada va tugaganda - odatiy uyqu.
 */
function syncAwake(phase: ReadAloudState['phase']) {
  const want = phase === 'loading' || phase === 'playing';
  if (want === awake) return;
  awake = want;
  try {
    keepAwake(want);
  } catch {
    /* ekran baribir o'chishi mumkin - o'qish ishlayveradi */
  }
}

function ensureEngine(services: Services): ReadAloudEngine {
  if (engine) return engine;
  const parts = (factory ?? defaultParts)(services);
  if (parts.keepAwake) keepAwake = parts.keepAwake;
  const made = buildEngine(parts);
  engine = made;
  unsubSpeaker = made.speaker.subscribe(onEvent);
  if (!watchers) {
    // Yangi suhbat / tarix almashdi yoki ilova fonga o'tdi - o'qish to'xtaydi.
    const offChat = useChat.subscribe((s, prev) => {
      if (s.epoch !== prev.epoch) stopReadAloud();
    });
    const app = AppState.addEventListener('change', (s) => {
      if (s === 'background') stopReadAloud();
    });
    const offPhase = useReadAloud.subscribe((s) => syncAwake(s.phase));
    watchers = () => {
      offChat();
      app.remove();
      offPhase();
    };
  }
  return made;
}

function start(services: Services, key: string, markdown: string, turnId: string | null) {
  stopReadAloud();
  let eng: ReadAloudEngine;
  try {
    eng = ensureEngine(services);
  } catch {
    showToast(currentT()(TOAST.failed));
    return;
  }
  // Yig'ilish yozilayotganda audio rejimga tegilmaydi (adapter o'zi o'tkazib yuboradi).
  void eng.mode.playbackOnly().catch(() => {});
  const q = createSentenceQueue();
  q.push(markdown, true);
  queue = q;
  useReadAloud.setState({ key, phase: 'loading', index: 0, total: null });
  eng.speaker.speak(key, q, turnId);
}

export function useReadAloudControls(): ReadAloudControls {
  const services = useServices();
  return useMemo<ReadAloudControls>(() => {
    const toggle = (key: string, markdown: string, turnId: string | null) => {
      if (useReadAloud.getState().key === key) {
        stopReadAloud();
        return;
      }
      start(services, key, markdown, turnId);
    };
    return {
      toggle,
      pause() {
        const st = useReadAloud.getState();
        if (!engine || (st.phase !== 'playing' && st.phase !== 'loading')) return;
        engine.speaker.pause();
        useReadAloud.setState({ phase: 'paused' });
      },
      resume() {
        const st = useReadAloud.getState();
        if (!engine || st.phase !== 'paused') return;
        // Oldindan tayyorlangan bo'laklar saqlangan - davom etish darhol.
        engine.speaker.resume();
        useReadAloud.setState({ phase: st.index > 0 ? 'playing' : 'loading' });
      },
      stop: stopReadAloud,
      preview: () => toggle(PREVIEW_KEY, PREVIEW_TEXT, null),
    };
  }, [services]);
}

/** Test uchun: soxta native qismlar (pleer, API, fayllar) va to'liq tozalash. */
export function __setReadAloudParts(f: PartsFactory | null): void {
  factory = f;
}

export function __resetReadAloud(): void {
  try {
    engine?.speaker.dispose();
  } catch {
    /* allaqachon */
  }
  unsubSpeaker?.();
  unsubSpeaker = null;
  watchers?.();
  watchers = null;
  engine = null;
  queue = null;
  awake = false;
  keepAwake = (on) => keepScreenOn('read', on);
  useReadAloud.setState({ ...IDLE });
}
