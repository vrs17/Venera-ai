/**
 * Barno ovozi: gap navbati -> `/tts/clip` -> fayl -> pleer. Jonli suhbat ham, "Tinglash" ham
 * shu dvigateldan foydalanadi.
 *
 * Qoidalar (har biri o'lchovdan):
 *  - Bir vaqtda ko'pi bilan BITTA SINTEZ: serverdagi 2 ta TTS o'rni HAMMA foydalanuvchilar
 *    uchun umumiy; ikkinchi parallel sintez boshqalarni 503 ga tushirardi.
 *  - Keyingi bo'lak oldingisining SARLAVHASI kelishi bilan so'raladi, tanasini kutmaydi.
 *    Server sarlavhani sintez tugagach yuboradi (TTS o'rni shu paytda bo'shagan), 77-440 KB
 *    tana esa hali yo'lda. Ilgari keyingi so'rov tana to'liq kelib, faylga yozilgach ketardi:
 *    har chegarada GPU 0.4-1 s bo'sh turdi, tana kechiksa (2026-10-10: proksi har >64 KB
 *    javobni 5 s ushlab turgan) bu kechikish gaplar orasidagi jimlikka aylanardi.
 *  - Oldinda ko'pi bilan 2 ta bo'lak (sintez/yuklanish/tayyor) - keyingi gap oldingisi
 *    yangrayotganda tayyor. Ijro QAT'IY tartibda: oldingisi yuklanmaguncha keyingisi kutadi.
 *  - Kutish ovozi (hold) HECH QACHON kesilmaydi: javob o'sha klip tugashini kutadi (web'da
 *    yarim gapda kesilgan klip "buzilgan" eshitilgan). Lekin javobning birinchi bo'lagi shu
 *    vaqtda SINTEZ qilinaveradi - kutish kechikish qo'shmaydi. Javob navbatga tushgach
 *    kechikib kelgan kutish klipi umuman o'ynalmaydi (aks holda javob uni kutib qolardi).
 *  - Bir vaqtda bitta kutish ovozi; keyingisi navbatga qo'yilmaydi, tashlanadi.
 *  - 503 / tarmoq uzilishi - 400 ms va 1200 ms dan keyin qayta; ovoz hali yangrayotgan
 *    bo'lsa (bufer bor) yana 2 s va 4 s kutib urinadi - bitta uzilish javobning qolganini
 *    o'chirib yubormasin. Tana sarlavhadan keyin uzilsa - o'sha bo'lak o'z o'rnida qayta
 *    so'raladi (tartib buzilmaydi). 400/422 (bitta g'alati bo'lak) - o'sha bo'lak tashlanadi,
 *    qolgani o'qiladi. 501 - ovoz serverda yoqilmagan (ilova ishlayotgan davomida qayta
 *    so'ralmaydi). Boshqa xato - javob shu bo'lakdan kesiladi (undan keyingilari ham tashlanadi).
 *  - Har klipga "qo'riqchi" taymer (davomiyligi + 1.5 s): pleer "tugadi" demasa ham (buzuq
 *    fayl, pleer xatosi) navbat osilib qolmaydi.
 */
import { ApiError } from '@/api/client';
import type { VoiceApi, VoiceId } from '@/api/voice';

import type { SentenceQueue } from './chunker';
import { TTS_RETRY_MS } from './limits';
import type { AudioFiles, ClipPlayer, Clock } from './ports';
import { envelopeAt, envelopeMaxDb, envelopeOf, parseWav, type Envelope } from './wav';

export type SpeakerEvent =
  | { type: 'hold_start'; text: string }
  | { type: 'hold_end' }
  | { type: 'speech_start'; key: string }
  | { type: 'chunk'; key: string; index: number }
  | { type: 'speech_end'; key: string; shortened: boolean; played: number }
  | { type: 'error'; key: string; code: 'busy' | 'off' | 'failed' };

export interface SpeakerDeps {
  api: Pick<VoiceApi, 'clip' | 'hold'>;
  files: AudioFiles;
  player: ClipPlayer;
  clock: Clock;
  settings: () => { voice: VoiceId; speed: number };
  /**
   * Vaqtinchalik bo'laklar papkasi. Jonli suhbat va "Tinglash" alohida papkada: suhbat
   * yopilganda o'z papkasini tozalaydi - shu payt boshlangan o'qishning fayli o'chib ketmasin.
   */
  dir?: 'voice' | 'voice-read';
  /**
   * Kechikish izi (faqat dev build ulaydi, `trace.ts`). NIMA UCHUN: javob tugagandan birinchi
   * bo'lak so'rovigacha ~1.8 s (prod, 2026-10-10) - server log'i bu vaqtning telefondagi
   * qismini ajrata olmaydi. Iz: speak -> req -> sent -> headers -> body -> play.
   */
  trace?: (event: SpeakerTraceEvent, detail: string) => void;
}

export type SpeakerTraceEvent = 'speak' | 'req' | 'sent' | 'headers' | 'body' | 'play';

export interface SpeakerOutput {
  level: number;
  db: number | null;
  clipAgeMs: number;
  source: 'hold' | 'answer' | null;
}

/** Joriy javob qayergacha aytilgani (pauzadan keyin davom ettirish uchun). */
export interface SpeakerProgress {
  key: string | null;
  /** Oxirigacha yangragan bo'laklar: har biri `uzunlik + 1` (chunker `skip()` o'lchovi). */
  spoken: number;
  /** Aytilmagan narsa qoldimi (yangrayotgan bo'lak ham hisob). */
  remaining: boolean;
}

export interface Speaker {
  /** `valid` - tarmoqdan kelgach ham hali kerakmi (holat o'zgargan bo'lishi mumkin). */
  hold(cue: { text: string; clip: string | null }, valid?: () => boolean): void;
  speak(key: string, source: SentenceQueue, turnId: string | null): void;
  pump(): void;
  stop(): void;
  stopHold(): void;
  pause(): void;
  resume(): void;
  output(): SpeakerOutput;
  progress(): SpeakerProgress;
  /** Hozir yangrayotgan va oldingi matn - bo'lib gapirish o'z aks-sadomizmi, tekshirish uchun. */
  recentText(): string[];
  subscribe(listener: (e: SpeakerEvent) => void): () => void;
  dispose(): void;
}

let ttsOff = false;

/** Shu ishga tushishda server 501 qaytarganmi (ovoz sozlanmagan) - qayta so'ralmaydi. */
export function ttsOffThisRun(): boolean {
  return ttsOff;
}

export function __resetTtsOff(): void {
  ttsOff = false;
}

/** Klip egri chizig'i bo'lmasa (buzuq kesh) - bo'lib gapirish chegarasi uchun "baland" deb olamiz. */
const UNKNOWN_OUT_DB = -20;
/** Qo'riqchi: klip davomiyligidan keyin shuncha kutib, "tugadi" deb hisoblanadi. */
export const WATCHDOG_EXTRA_MS = 1500;
/** Davomiyligi noma'lum klip (kutish klipi 2.5-3.3 s) uchun. */
const UNKNOWN_CLIP_MS = 6000;
/** Ovoz yangrab turgan paytdagi qo'shimcha qayta urinishlar (503 / tarmoq). */
const EXTRA_RETRY_MS: readonly number[] = [2000, 4000];
/** Ketma-ket shuncha bo'lak o'ynamasa - javob tashlanadi. */
const MAX_PLAY_FAILURES = 3;
/** Oldinda (yangrayotgandan tashqari) ko'pi bilan shuncha bo'lak: sintez + yuklanish + tayyor. */
const AHEAD_MAX = 2;
/**
 * Qisqa ochilish ("Albatta!") keyingi gapni ko'pi bilan shuncha kutadi - matn o'smasa.
 * NIMA UCHUN: oqim kirish gapidan keyin to'xtashi mumkin (agent vosita chaqiradi); bu paytda
 * kutish ovozi ham o'chiq (javob boshlangan) - chegarasiz kutish to'liq jimlik bo'lardi.
 * Token oqimida keyingi so'zlar 0.1-0.3 s da keladi, 0.5 s esa ochilishning o'zidan qisqa.
 */
export const OPENER_WAIT_MS = 500;

/**
 * Javobning bitta bo'lagi, tartib bilan:
 *  - synth: so'rov ketdi, server sintez qilyapti (sarlavha hali yo'q) - SINTEZ O'RNI shu bo'lakda;
 *  - body: sarlavha keldi (sintez tugadi), tana yuklanmoqda;
 *  - backoff: xatodan keyin kutish (sarlavhagacha bo'lsa sintez o'rnini ushlab turadi);
 *  - retry: qayta so'rashga navbatda (sintez o'rni bo'shashi bilan, yangi matndan OLDIN);
 *  - ready: fayl diskda, ijroga tayyor.
 */
interface Slot {
  /** Javobdagi tartib raqami (1 dan) - faqat iz uchun. */
  n: number;
  text: string;
  phase: 'synth' | 'body' | 'backoff' | 'retry' | 'ready';
  ctl: AbortController | null;
  uri: string | null;
  env: Envelope | null;
  attempt: number;
  extraAttempt: number;
  dead: boolean;
}

interface Playing {
  kind: 'hold' | 'answer';
  uri: string;
  env: Envelope | null;
  startedAt: number;
  /** Javob bo'lagi - o'ynab bo'lgach o'chiriladi; kutish ovozi keshda qoladi. */
  temp: boolean;
  text: string;
}

let fileSeq = 0;

function retryable(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 503 || (err.status === 0 && err.code === 'network'));
}

function skippable(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 400 || err.status === 422);
}

export function createSpeaker(deps: SpeakerDeps): Speaker {
  const { files, player, clock } = deps;
  const dir = deps.dir ?? 'voice';
  const listeners = new Set<(e: SpeakerEvent) => void>();
  /** stop() har safar oshiradi - eski asinxron natijalar tashlanadi. */
  let gen = 0;
  let key: string | null = null;
  let source: SentenceQueue | null = null;
  let turnId: string | null = null;
  /** Yangrayotgandan keyingi bo'laklar, ijro tartibida. */
  const ahead: Slot[] = [];
  /** Sintez o'rnini egallagan bo'lak (sarlavhasi hali kelmagan) - bir vaqtda bittadan ko'p emas. */
  let synthSlot: Slot | null = null;
  let playing: Playing | null = null;
  let holdFetch: AbortController | null = null;
  let started = false;
  let played = 0;
  let spoken = 0;
  let failed = false;
  let playFailures = 0;
  let paused = false;
  let disposed = false;
  let lastText: string | null = null;
  let slotSeq = 0;
  /** Ochilish kutish taymeri va u qo'yilgandagi matn uzunligi (o'sish belgisi). */
  let openerTimer: unknown = null;
  let openerMark: number | null = null;
  const trace = deps.trace;
  // --- qo'riqchi taymer ---
  let watchdog: unknown = null;
  let watchdogLeft = 0;
  let watchdogArmedAt = 0;

  const emit = (e: SpeakerEvent) => {
    for (const l of [...listeners]) l(e);
  };

  const offEnd = player.onEnd(onEnd);

  function clearWatchdog() {
    if (watchdog != null) clock.clearTimeout(watchdog);
    watchdog = null;
  }

  function armWatchdog(ms: number) {
    clearWatchdog();
    watchdogLeft = ms;
    watchdogArmedAt = clock.now();
    const p = playing;
    watchdog = clock.setTimeout(() => {
      watchdog = null;
      if (playing !== p || !p) return;
      // Pleer "tugadi" demadi (buzuq fayl, pleer xatosi) - navbat osilib qolmasin.
      try {
        player.stop();
      } catch {
        /* allaqachon to'xtagan */
      }
      onEnd();
    }, ms);
  }

  function startPlaying(p: Playing) {
    playing = p;
    player.play(p.uri);
    const dur = p.env ? p.env.durationMs : UNKNOWN_CLIP_MS;
    armWatchdog(dur + WATCHDOG_EXTRA_MS);
  }

  function killSlot(slot: Slot) {
    slot.dead = true;
    slot.ctl?.abort();
    slot.ctl = null;
    if (slot.uri) files.remove(slot.uri);
    slot.uri = null;
    if (synthSlot === slot) synthSlot = null;
  }

  function clearOpener() {
    if (openerTimer != null) clock.clearTimeout(openerTimer);
    openerTimer = null;
    openerMark = null;
  }

  /** `take()` ochilishni kutib null berdi - matn o'smasa OPENER_WAIT_MS dan keyin yolg'iz aytiladi. */
  function armOpener() {
    const src = source;
    const mark = src?.openerWait ?? null;
    if (!src || mark === null) {
      clearOpener();
      return;
    }
    // Matn o'smagan - eski taymer davom etadi (har pump'da qayta qo'yilsa hech qachon tugamasdi).
    if (openerTimer != null && openerMark === mark) return;
    clearOpener();
    openerMark = mark;
    const g = gen;
    openerTimer = clock.setTimeout(() => {
      openerTimer = null;
      openerMark = null;
      if (g !== gen || source !== src) return;
      src.releaseOpener();
      pump();
    }, OPENER_WAIT_MS);
  }

  function resetAnswer() {
    clearOpener();
    for (const slot of ahead.splice(0)) killSlot(slot);
    synthSlot = null;
    slotSeq = 0;
    if (playing?.kind === 'answer') {
      clearWatchdog();
      try {
        player.stop();
      } catch {
        /* allaqachon to'xtagan */
      }
      files.remove(playing.uri);
      playing = null;
    }
    key = null;
    source = null;
    turnId = null;
    started = false;
    played = 0;
    spoken = 0;
    failed = false;
    playFailures = 0;
  }

  function maybeDone() {
    if (!key || !source) return;
    if (!(failed || source.finished) || ahead.length || playing) return;
    const k = key;
    const e: SpeakerEvent = { type: 'speech_end', key: k, shortened: source.shortened, played };
    key = null;
    source = null;
    turnId = null;
    started = false;
    played = 0;
    spoken = 0;
    failed = false;
    playFailures = 0;
    emit(e);
  }

  function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      clock.setTimeout(resolve, ms);
    });
  }

  function fail(forKey: string, code: 'busy' | 'off' | 'failed') {
    if (code === 'off') ttsOff = true;
    // Bitta javobga bitta xato xabari. NIMA UCHUN: endi bir vaqtda ikki bo'lak yo'lda bo'lishi
    // mumkin (biri sintezda, oldingisi tana yuklayapti) - ikkalasi ham yiqilsa foydalanuvchi
    // ikkita "ovoz ishlamadi" xabarini ko'rardi. Javob birinchi xatodayoq kesilgan.
    const reported = failed && forKey === key;
    failed = true;
    if (!reported) {
      const g = gen;
      emit({ type: 'error', key: forKey, code });
      if (g !== gen) return;
    }
    pump();
  }

  /** `slot` uchun so'rov (yangi yoki qayta). Sintez o'rnini sarlavha kelguncha egallaydi. */
  function request(slot: Slot) {
    const myGen = gen;
    const ctl = new AbortController();
    slot.ctl = ctl;
    slot.phase = 'synth';
    synthSlot = slot;
    const { voice, speed } = deps.settings();
    const forKey = key as string;
    const turn = turnId;
    const stale = () => myGen !== gen || slot.dead || slot.ctl !== ctl;
    const onHeaders = () => {
      if (stale() || slot.phase !== 'synth') return;
      trace?.('headers', `#${slot.n}`);
      // Sarlavha = sintez tugadi: keyingi bo'lak shu zahoti so'raladi, tana yuklanishini kutmaydi.
      slot.phase = 'body';
      if (synthSlot === slot) synthSlot = null;
      pump();
    };
    const onSent = trace ? () => trace('sent', `#${slot.n}`) : undefined;
    trace?.('req', `#${slot.n} ${slot.text.length}ch`);
    void (async () => {
      try {
        const wav = await deps.api.clip(slot.text, { voice, speed, turnId: turn, signal: ctl.signal, onHeaders, onSent });
        if (stale()) return;
        trace?.('body', `#${slot.n} ${wav.bytes.length}B`);
        const env = envelopeOf(parseWav(wav.bytes));
        const uri = files.write(dir, `clip-${Date.now().toString(36)}-${++fileSeq}.wav`, wav.bytes);
        slot.ctl = null;
        slot.uri = uri;
        slot.env = env;
        slot.phase = 'ready';
        if (synthSlot === slot) synthSlot = null;
        pump();
      } catch (err) {
        if (stale()) return;
        if (retryable(err)) {
          // Avval qisqa qayta urinishlar; ovoz hali yangrayotgan bo'lsa (kutish bepul) - uzunroq.
          let wait: number | null = null;
          if (slot.attempt < TTS_RETRY_MS.length) wait = TTS_RETRY_MS[slot.attempt++];
          else if ((playing?.kind === 'answer' || ahead.some((s) => s !== slot && s.phase === 'ready')) && slot.extraAttempt < EXTRA_RETRY_MS.length) {
            wait = EXTRA_RETRY_MS[slot.extraAttempt++];
          }
          if (wait !== null) {
            // Sarlavhagacha uzilgan bo'lsa sintez o'rni kutish davomida ham shu bo'lakda qoladi
            // (yangi bo'lak so'ralmaydi); tana uzilgan bo'lsa o'rin allaqachon boshqasida bo'lishi mumkin.
            slot.phase = 'backoff';
            await sleep(wait);
            if (stale()) return;
            if (synthSlot === slot) synthSlot = null;
            slot.phase = 'retry';
            pump();
            return;
          }
        }
        if (skippable(err)) {
          // Bitta bo'lakni server o'qiy olmadi - uni tashlab, keyingisiga o'tamiz.
          dropSlot(slot);
          pump();
          return;
        }
        const code: 'busy' | 'off' | 'failed' = err instanceof ApiError && err.status === 501 ? 'off' : retryable(err) ? 'busy' : 'failed';
        // Javob shu bo'lakdan kesiladi: undan keyingilar ham tashlanadi (teshik bilan o'qilmasin).
        const at = ahead.indexOf(slot);
        for (const s of at >= 0 ? ahead.splice(at) : [slot]) killSlot(s);
        fail(forKey, code);
      }
    })();
  }

  function dropSlot(slot: Slot) {
    killSlot(slot);
    const at = ahead.indexOf(slot);
    if (at >= 0) ahead.splice(at, 1);
  }

  function playNext() {
    const clip = ahead.shift() as Slot;
    const uri = clip.uri as string;
    const k = key as string;
    trace?.('play', `#${clip.n}`);
    try {
      startPlaying({ kind: 'answer', uri, env: clip.env, startedAt: clock.now(), temp: true, text: clip.text });
    } catch {
      clearWatchdog();
      files.remove(uri);
      playing = null;
      // Bitta bo'lak o'ynamadi - keyingisi bilan davom etamiz; bir necha marta ketma-ket bo'lsa - xato.
      if (++playFailures >= MAX_PLAY_FAILURES) {
        fail(k, 'failed');
        return;
      }
      pump();
      return;
    }
    playFailures = 0;
    const g = gen;
    if (!started) {
      started = true;
      emit({ type: 'speech_start', key: k });
      if (g !== gen) return;
    }
    played++;
    emit({ type: 'chunk', key: k, index: played });
  }

  function stop() {
    gen++;
    holdFetch?.abort();
    holdFetch = null;
    resetAnswer();
    clearWatchdog();
    if (playing) {
      try {
        player.stop();
      } catch {
        /* allaqachon to'xtagan */
      }
      if (playing.temp) files.remove(playing.uri);
      playing = null;
    }
    paused = false;
    lastText = null;
  }

  function pump() {
    if (disposed || !key || !source) return;
    // Avval ijro (faqat navbat BOSHIDAGI bo'lak tayyor bo'lsa - tartib qat'iy), keyin sintez -
    // oldinda 2 tadan oshmasin, lekin bo'sh ham qolmasin.
    if (!playing && !paused && ahead[0]?.phase === 'ready') playNext();
    if (!key || !source) return;
    if (!synthSlot) {
      // Qayta so'raladigan bo'lak yangi matndan oldin (u tartibda oldinroq). `failed` bo'lsa ham:
      // xatodan OLDINGI bo'lak tushib qolmasin.
      const again = ahead.find((s) => s.phase === 'retry');
      if (again) request(again);
      else if (!failed && ahead.length < AHEAD_MAX) {
        const text = source.take();
        if (text) {
          clearOpener();
          const slot: Slot = { n: ++slotSeq, text, phase: 'synth', ctl: null, uri: null, env: null, attempt: 0, extraAttempt: 0, dead: false };
          ahead.push(slot);
          request(slot);
        } else armOpener();
      }
    }
    maybeDone();
  }

  function onEnd() {
    if (!playing) return;
    clearWatchdog();
    const was = playing;
    playing = null;
    lastText = was.text;
    if (was.temp) files.remove(was.uri);
    if (was.kind === 'hold') {
      const g = gen;
      emit({ type: 'hold_end' });
      if (g !== gen) return;
    } else {
      spoken += was.text.length + 1;
    }
    pump();
  }

  return {
    hold(cue, valid) {
      const clip = cue.clip;
      if (!clip || ttsOff || disposed) return;
      // Bittasi yangrayapti yoki olinmoqda, yoki javob navbatga tushgan - keyingisi tashlanadi.
      if (playing || holdFetch || started || key) return;
      const myGen = gen;
      const ctl = new AbortController();
      holdFetch = ctl;
      const { voice } = deps.settings();
      const name = `${voice}/${clip}.wav`;
      void (async () => {
        let uri: string | null = null;
        let bytes: Uint8Array | null = null;
        try {
          uri = files.find('voice-hold', name);
          if (uri) bytes = await files.read(uri);
          else {
            const res = await deps.api.hold(clip, voice, ctl.signal);
            if (!res) return;
            bytes = res.bytes;
            // Klip kaliti matn xeshini o'z ichiga oladi - fayl hech qachon eskirmaydi.
            uri = files.write('voice-hold', name, res.bytes);
          }
        } catch {
          return;
        } finally {
          if (holdFetch === ctl) holdFetch = null;
        }
        if (myGen !== gen || ctl.signal.aborted || disposed) return;
        if (valid && !valid()) return;
        // Kechikib keldi: javob allaqachon navbatda bo'lsa klip o'ynalmaydi - javob uni kutmasin.
        if (playing || started || paused || key || !uri) return;
        let env: Envelope | null = null;
        try {
          env = bytes ? envelopeOf(parseWav(bytes)) : null;
        } catch {
          env = null;
        }
        try {
          startPlaying({ kind: 'hold', uri, env, startedAt: clock.now(), temp: false, text: cue.text });
        } catch {
          clearWatchdog();
          playing = null;
          return;
        }
        emit({ type: 'hold_start', text: cue.text });
      })();
    },

    speak(k, src, turn) {
      if (disposed) return;
      // Avvalgi javob (bo'lsa) to'xtaydi; yangrayotgan kutish ovozi esa kesilmaydi.
      resetAnswer();
      key = k;
      source = src;
      turnId = turn;
      trace?.('speak', k);
      if (ttsOff) {
        failed = true;
        const g = gen;
        emit({ type: 'error', key: k, code: 'off' });
        if (g !== gen) return;
      }
      pump();
    },

    pump,

    stop,

    stopHold() {
      holdFetch?.abort();
      holdFetch = null;
      if (playing?.kind !== 'hold') return;
      clearWatchdog();
      try {
        player.stop();
      } catch {
        /* allaqachon to'xtagan */
      }
      playing = null;
      const g = gen;
      emit({ type: 'hold_end' });
      if (g === gen) pump();
    },

    pause() {
      if (paused) return;
      paused = true;
      if (playing) {
        // Qo'riqchi to'xtaydi - pauza paytida "tugadi" deb hisoblanmasin.
        if (watchdog != null) watchdogLeft = Math.max(0, watchdogLeft - (clock.now() - watchdogArmedAt));
        clearWatchdog();
        player.pause();
      }
    },

    resume() {
      if (!paused) return;
      paused = false;
      if (playing) {
        player.resume();
        armWatchdog(Math.max(WATCHDOG_EXTRA_MS, watchdogLeft));
      } else pump();
    },

    output() {
      if (!playing || paused) return { level: 0, db: null, clipAgeMs: 0, source: null };
      const age = clock.now() - playing.startedAt;
      let pos = player.positionMs();
      // Ba'zi qurilmalarda pozitsiya kechikib yangilanadi - devor soati bilan taxmin.
      if (!(pos > 0)) pos = Math.max(0, age - 80);
      if (!playing.env) return { level: 0.5, db: UNKNOWN_OUT_DB, clipAgeMs: age, source: playing.kind };
      const at = envelopeAt(playing.env, pos);
      // Cho'qqi (RMS emas): mikrofon o'lchovi ham cho'qqi - bir xil shkalada solishtiriladi.
      const db = envelopeMaxDb(playing.env, pos - 160, pos, 'peak') ?? at.db;
      return { level: at.level, db, clipAgeMs: age, source: playing.kind };
    },

    progress() {
      const remaining = !!key && (!!playing || ahead.length > 0 || !(source?.finished ?? true));
      return { key, spoken, remaining };
    },

    recentText() {
      const out: string[] = [];
      if (playing?.text) out.push(playing.text);
      if (lastText) out.push(lastText);
      return out;
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    dispose() {
      if (disposed) return;
      stop();
      disposed = true;
      offEnd();
      listeners.clear();
      try {
        player.dispose();
      } catch {
        /* allaqachon bo'shatilgan */
      }
    },
  };
}
