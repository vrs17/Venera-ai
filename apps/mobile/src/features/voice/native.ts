/**
 * Native adapterlar: expo-audio (yozuvchi, pleer, audio rejim), expo-file-system va
 * ekranni yoqiq ushlash.
 *
 * MUHIM: native modullar faqat funksiya ICHIDA (`require`) yuklanadi - modul darajasida
 * emas. Jest'dagi expo-audio mock'ida `createAudioPlayer` yo'q; ekran testlari bu faylni
 * import qilganda yiqilmasligi kerak.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
import type { AudioPlayer, AudioRecorder, AudioStatus, RecordingOptions } from 'expo-audio';

import { MEETING_PRESET } from '@/features/recorder/preset';

import type { AudioFiles, AudioModePort, ClipPlayer, MicFrame, MicPort, VoiceDir } from './ports';

/**
 * Ovozli rejim mikrofoni.
 *  - `voice_communication`: Android'ning AEC/NS/AGC beradigan YAGONA manbasi (expo-audio
 *    boshqa yo'l bermaydi) - Barno ovozi mikrofonga kamroq qaytadi, bo'lib gapirish mumkin.
 *  - ADTS 16 kHz: diktovka va Gapi STT allaqachon qabul qiladigan format, JS'da kadrma-kadr
 *    kesiladi (`adts.ts`).
 *  - Metering: VAD shu o'lchovda ishlaydi.
 */
export const VOICE_PRESET: RecordingOptions = {
  extension: '.aac',
  sampleRate: 16000,
  numberOfChannels: 1,
  bitRate: 32000,
  isMeteringEnabled: true,
  directory: 'cache',
  android: {
    extension: '.aac',
    outputFormat: 'aac_adts',
    audioEncoder: 'aac',
    audioSource: 'voice_communication',
    sampleRate: 16000,
  },
  ios: { ...MEETING_PRESET.ios, sampleRate: 16000 },
  web: { mimeType: 'audio/webm', bitsPerSecond: 32000 },
};

/** Yozuvchining faqat bizga kerak qismi (testda soxtasi). */
export type RecorderLike = Pick<AudioRecorder, 'prepareToRecordAsync' | 'record' | 'stop' | 'getStatus' | 'uri'>;

export function createMicPort(recorder: RecorderLike): MicPort {
  let recording = false;
  let segmentUri: string | null = null;

  async function releaseNative() {
    try {
      await recorder.stop();
    } catch {
      /* allaqachon bo'sh */
    }
  }

  return {
    async start() {
      if (recording) return;
      // Oldingi urinishda `record()` yiqilgan bo'lsa native yozuvchi "tayyor" holatda qolib
      // ketadi va har keyingi `prepare` AlreadyPrepared bilan yiqiladi ("Qayta urinish" hech
      // qachon ishlamasdi). Bunday holatni avval bo'shatamiz (RecorderProvider'dagi kabi).
      let stuck = false;
      try {
        const st = recorder.getStatus();
        stuck = !!(st?.canRecord || st?.isRecording);
      } catch {
        stuck = false;
      }
      if (stuck) await releaseNative();
      await recorder.prepareToRecordAsync(VOICE_PRESET);
      // Har prepare yangi fayl ochadi - uri'ni hozir olamiz (stop'dan keyin keyingisi yozilishi mumkin).
      segmentUri = recorder.uri ?? null;
      try {
        recorder.record();
      } catch (err) {
        // Mikrofon band (qo'ng'iroq, boshqa VoIP ilova): tayyorlangan yozuvchini bo'shatamiz.
        segmentUri = null;
        await releaseNative();
        throw err;
      }
      recording = true;
    },
    poll(): MicFrame | null {
      if (!recording) return null;
      const st = recorder.getStatus();
      return { tMs: Number(st.durationMillis) || 0, db: typeof st.metering === 'number' && Number.isFinite(st.metering) ? st.metering : -160 };
    },
    async stop() {
      if (!recording) return null;
      recording = false;
      const uri = segmentUri ?? recorder.uri ?? null;
      segmentUri = null;
      try {
        await recorder.stop();
      } catch {
        // Juda qisqa segment - fayl yaroqsiz bo'lishi mumkin, baribir o'chiriladi.
      }
      return uri;
    },
    get recording() {
      return recording;
    },
  };
}

/** `replace` dan keyin eski klipning kechikkan "tugadi" hodisasi yangisini to'xtatmasin. */
const STALE_FINISH_MS = 150;

type PlayerFactory = () => AudioPlayer;

/**
 * Bitta klip pleyeri.
 *
 * NIMA UCHUN `stop()` native pleyerni butunlay YO'Q QILADI (keyingi `play()` da yangisi):
 * expo-audio ilova fonga o'tganda yoki qo'ng'iroqda yangrayotgan pleyerni o'zi "pauza" deb
 * belgilaydi va qaytganda (yoki audio fokus qaytganda) O'ZI QAYTA YOQADI - JS `pause()` bu
 * belgini tozalamaydi. Natijada to'xtatilgan Barno gapi qaytib yangrar, mikrofon uni savol
 * deb yozib olardi. Yo'q qilingan pleyerni hech kim qayta yoqa olmaydi.
 *
 * Pauza (o'qishni to'xtatib turish) uchun esa "xohlanmagan ijro" qo'riqchisi: holat
 * yangilanishida `playing` bo'lsa-yu biz xohlamasak - darhol yana pauza.
 *
 * Pozitsiya: `player.currentTime` Android'da UI oqimida bloklovchi chaqiruv (~47 marta/s
 * bo'lardi) - o'rniga 100 ms lik holat yangilanishidagi vaqt + devor soati.
 */
export function createClipPlayer(factory?: PlayerFactory): ClipPlayer {
  let make: PlayerFactory;
  if (factory) make = factory;
  else {
    // Modul yo'q bo'lsa (Jest mock'i, juda eski APK) - DARHOL yiqilamiz: chaqiruvchi jim pleerga o'tadi.
    const { createAudioPlayer } = require('expo-audio') as typeof import('expo-audio');
    if (typeof createAudioPlayer !== 'function') throw new Error('createAudioPlayer missing');
    make = () => createAudioPlayer(null, { updateInterval: 100 });
  }
  const callbacks = new Set<() => void>();
  let player: AudioPlayer | null = null;
  let sub: { remove(): void } | null = null;
  let startedAt = 0;
  let wanted = false;
  let isPlaying = false;
  let lastPos = 0;
  let lastPosAt = 0;

  function onStatus(p: AudioPlayer, s: AudioStatus) {
    if (p !== player) return;
    if (typeof s.currentTime === 'number' && Number.isFinite(s.currentTime)) {
      lastPos = s.currentTime * 1000;
      lastPosAt = Date.now();
    }
    if (typeof s.playing === 'boolean') isPlaying = s.playing;
    if (s.playing && !wanted) {
      // Native o'zi qayta yoqdi (fokus qaytdi / ilova oldinga chiqdi) - biz buni xohlamaymiz.
      try {
        p.pause();
      } catch {
        /* no-op */
      }
      return;
    }
    const error = (s as { error?: unknown }).error;
    const ended = s.didJustFinish || (typeof error === 'string' && error.length > 0);
    if (!ended || !wanted || Date.now() - startedAt < STALE_FINISH_MS) return;
    wanted = false;
    isPlaying = false;
    // Pleer xatosi ham "tugadi": navbat keyingi bo'lakka o'tadi, osilib qolmaydi.
    for (const cb of [...callbacks]) cb();
  }

  function ensure(): AudioPlayer {
    if (player) return player;
    const p = make();
    player = p;
    sub = p.addListener('playbackStatusUpdate', (s: AudioStatus) => onStatus(p, s));
    return p;
  }

  function release() {
    const p = player;
    player = null;
    isPlaying = false;
    try {
      sub?.remove();
    } catch {
      /* allaqachon */
    }
    sub = null;
    if (!p) return;
    try {
      p.pause();
    } catch {
      /* allaqachon */
    }
    try {
      p.remove();
    } catch {
      /* allaqachon */
    }
  }

  return {
    play(uri) {
      const p = ensure();
      startedAt = Date.now();
      wanted = true;
      lastPos = 0;
      lastPosAt = startedAt;
      // NIMA UCHUN AudioPlaylist emas: tugagan pleylistga qo'shish xatti-harakati hujjatlanmagan;
      // `replace` orasidagi ~100 ms gaplar orasidagi tabiiy pauzadek eshitiladi.
      p.replace({ uri });
      p.play();
    },
    pause() {
      wanted = false;
      try {
        player?.pause();
      } catch {
        /* no-op */
      }
    },
    resume() {
      if (!player) return;
      wanted = true;
      lastPosAt = Date.now();
      player.play();
    },
    stop() {
      wanted = false;
      release();
    },
    positionMs() {
      if (!player) return 0;
      return isPlaying && wanted ? lastPos + (Date.now() - lastPosAt) : lastPos;
    },
    onEnd(cb) {
      callbacks.add(cb);
      return () => callbacks.delete(cb);
    },
    dispose() {
      callbacks.clear();
      wanted = false;
      release();
    },
  };
}

export function createAudioFiles(): AudioFiles {
  const FS = () => require('expo-file-system') as typeof import('expo-file-system');
  const dirOf = (dir: VoiceDir, name?: string) => {
    const { Directory, Paths } = FS();
    const parts = name ? name.split('/').slice(0, -1) : [];
    const d = new Directory(Paths.cache, dir, ...parts);
    if (!d.exists) d.create({ intermediates: true, idempotent: true });
    return d;
  };
  const base = (name: string) => name.split('/').pop() as string;
  return {
    write(dir, name, bytes) {
      const { File } = FS();
      const f = new File(dirOf(dir, name), base(name));
      if (f.exists) f.delete();
      f.create();
      f.write(bytes);
      return f.uri;
    },
    async read(uri) {
      const { File } = FS();
      return new File(uri).bytes();
    },
    find(dir, name) {
      try {
        const { File, Paths } = FS();
        const f = new File(Paths.cache, dir, name);
        return f.exists ? f.uri : null;
      } catch {
        return null;
      }
    },
    remove(uri) {
      if (!uri) return;
      try {
        const { File } = FS();
        const f = new File(uri);
        if (f.exists) f.delete();
      } catch {
        /* kesh baribir tozalanadi */
      }
    },
    clear(dir) {
      try {
        const { Directory, Paths } = FS();
        const d = new Directory(Paths.cache, dir);
        if (d.exists) d.delete();
      } catch {
        /* keyingi safar */
      }
    },
    sweepRecordings(olderThanMs) {
      // expo-audio segmentlarni `cache/Audio/recording-*.aac` ga yozadi; ilova segment
      // o'rtasida yopilsa ular qolib ketadi. Faqat ESKI fayllar: diktovka ham shu papkada.
      try {
        const { Directory, File, Paths } = FS();
        const d = new Directory(Paths.cache, 'Audio');
        if (!d.exists) return;
        const cutoff = Date.now() - olderThanMs;
        for (const item of d.list()) {
          if (!(item instanceof File) || !/^recording-.*\.aac$/.test(item.name)) continue;
          const mtime = item.modificationTime;
          if (typeof mtime === 'number' && mtime > 0 && mtime < cutoff) item.delete();
        }
      } catch {
        /* keyingi safar */
      }
    },
  };
}

/**
 * Audio rejim. DIQQAT: har `setAudioModeAsync` jonli yozuvchilarga `allowsBackgroundRecording`
 * ni ham yozadi - yig'ilish yozilayotganda chaqirilsa uning foreground xizmati buziladi.
 * Shuning uchun yig'ilish faol bo'lsa (`meetingActive`) HECH QAYSI rejim o'zgarmaydi.
 */
export function createAudioModePort(meetingActive: () => boolean): AudioModePort {
  const setMode = (mode: Parameters<typeof import('expo-audio').setAudioModeAsync>[0]) => {
    const { setAudioModeAsync } = require('expo-audio') as typeof import('expo-audio');
    return setAudioModeAsync(mode);
  };
  const live = async (earpiece: boolean) => {
    if (meetingActive()) return;
    await setMode({
      playsInSilentMode: true,
      interruptionMode: 'doNotMix',
      // Quloq rejimi MODE_IN_COMMUNICATION ni yoqadi - aksariyat qurilmalarda AEC eng yaxshi shunda.
      shouldRouteThroughEarpiece: earpiece,
      allowsRecording: true,
      allowsBackgroundRecording: false,
      shouldPlayInBackground: false,
    });
  };
  return {
    enter: ({ earpiece }) => live(earpiece),
    setEarpiece: (on) => live(on),
    async playbackOnly() {
      if (meetingActive()) return;
      await setMode({ playsInSilentMode: true, interruptionMode: 'duckOthers', shouldRouteThroughEarpiece: false, allowsBackgroundRecording: false });
    },
    async restore() {
      if (meetingActive()) return;
      // MAJBURIY: aks holda keyingi har qanday ovoz (yig'ilish pleyeri) quloqdan chiqadi.
      await setMode({
        playsInSilentMode: true,
        interruptionMode: 'mixWithOthers',
        shouldRouteThroughEarpiece: false,
        allowsRecording: false,
        allowsBackgroundRecording: false,
        shouldPlayInBackground: false,
      });
    },
  };
}

export async function requestMicPermission(): Promise<boolean> {
  const { requestRecordingPermissionsAsync } = require('expo-audio') as typeof import('expo-audio');
  const res = await requestRecordingPermissionsAsync();
  return !!res.granted;
}

/** Ruxsat hozir bormi (so'ramasdan) - sozlamalardan qaytganda. */
export async function hasMicPermission(): Promise<boolean> {
  try {
    const { getRecordingPermissionsAsync } = require('expo-audio') as typeof import('expo-audio');
    const res = await getRecordingPermissionsAsync();
    return !!res.granted;
  } catch {
    return false;
  }
}

interface KeepAwakeNative {
  activate(tag: string): Promise<void>;
  deactivate(tag: string): Promise<void>;
}

/**
 * Ekranni yoqiq ushlash (`FLAG_KEEP_SCREEN_ON`): ovozli suhbatda odam telefonga tegmaydi -
 * savol, ~12 s kutish, 20-200 s javob. Ekran o'chsa ilova fonga o'tib sessiya to'xtardi.
 *
 * NIMA UCHUN `ExpoKeepAwake` native modulini to'g'ridan-to'g'ri: `expo-keep-awake` bizning
 * package.json'da yo'q (yangi bog'liqlik qo'shilmaydi), lekin u `expo` ning bog'liqligi va
 * autolinking uni APK'ga allaqachon qo'shgan (`expo-modules-autolinking search` bilan
 * tekshirildi). Teglar native tomonda sanaladi: jonli suhbat va "Tinglash" bir-birini
 * o'chirib qo'ymaydi. Modul yo'q bo'lsa (Jest, iOS sinovi) - jim no-op.
 */
export function keepScreenOn(holder: 'voice' | 'read' | 'live', on: boolean): void {
  try {
    const { requireOptionalNativeModule } = require('expo') as typeof import('expo');
    const mod = requireOptionalNativeModule<KeepAwakeNative>('ExpoKeepAwake');
    if (!mod) return;
    const tag = `barno-${holder}`;
    const p = on ? mod.activate(tag) : mod.deactivate(tag);
    void Promise.resolve(p).catch(() => {});
  } catch {
    /* no-op */
  }
}
