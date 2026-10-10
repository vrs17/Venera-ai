/**
 * Ovozli suhbat sessiyasi: holat mashinasini (`machine.ts`) haqiqiy dunyo bilan ulaydi -
 * mikrofon segmentlari, VAD, STT navbati, chat, Barno ovozi, taymerlar va tuman darajasi.
 *
 * Hodisalar NAVBAT bilan qayta ishlanadi (run-to-completion): effekt ichida chaqirilgan
 * `dispatch` (masalan chat.send -> SENT) joriy o'tish tugagandan keyin bajariladi -
 * mashina hech qachon yarim holatni ko'rmaydi.
 *
 * Mikrofon ishlari (boshlash, to'xtatish, kesish, audio rejim) BITTA ketma-ket zanjirda:
 * MediaRecorder bir vaqtda ikki buyruqni ko'tarmaydi (prepare paytida stop yiqiladi).
 */
import { ApiError, StreamAbortedError } from '@/api/client';
import type { UiLang } from '@/i18n';

import { adtsDurationMs, trimAdts } from './adts';
import { createSentenceQueue, type SentenceQueue } from './chunker';
import { isEchoOf, isStopCommand } from './echo';
import { micLevel, smoothLevel } from './level';
import {
  FRAME_MS,
  LEVEL_TICK_MS,
  LISTEN_IDLE_MS,
  MAX_CAPTURE_OFFSET_MS,
  NOTICE_MS,
  POST_SPEECH_GUARD_MS,
  POSTROLL_MS,
  PREROLL_MS,
  RESUME_FRESH_MS,
  ROTATE_QUIET_LISTEN_MS,
  ROTATE_QUIET_THINK_MS,
  SEGMENT_ROTATE_MS,
  STALE_RECORDING_MS,
  STT_TIMEOUT_MS,
} from './limits';
import { initialState, reduce, type Effect, type MachineEvent, type MachineState } from './machine';
import type { AudioFiles, AudioModePort, ChatPort, Clock, MicFrame, MicPort, SttPort } from './ports';
import { ttsOffThisRun, type Speaker, type SpeakerOutput } from './speaker';
import type { FogSource, LevelListener, VoiceActions, VoiceSettings, VoiceSnapshot } from './types';
import { createVad, type Vad, type VadMode } from './vad';

export interface VoiceSessionDeps {
  mic: MicPort;
  speaker: Speaker;
  chat: ChatPort;
  stt: SttPort;
  mode: AudioModePort;
  files: AudioFiles;
  clock: Clock;
  uiLang: () => UiLang;
  settings: () => VoiceSettings;
  /** Quloq/karnay tanlovini saqlash (voiceSettings). */
  setEarpiece: (on: boolean) => void;
  meetingActive: () => boolean;
  requestPermission: () => Promise<boolean>;
  /** Ekranni yoqiq ushlash - holatdan kelib chiqadi (faqat o'zgarganda chaqiriladi). */
  keepAwake: (on: boolean) => void;
  stopReadAloud?: () => void;
  vad?: Vad;
}

export interface VoiceSession {
  start(): void;
  getSnapshot(): VoiceSnapshot;
  subscribe(listener: () => void): () => void;
  subscribeLevel(listener: LevelListener): () => void;
  dispatch(e: MachineEvent): void;
  /** Ekran yashirindi / ilova fonga o'tdi. */
  suspend(): void;
  resume(): void;
  readonly actions: VoiceActions;
  /** Testlar uchun: mashina holati. */
  readonly state: MachineState;
}

/** Kesilgan gap shundan qisqa bo'lsa STT'ga yaramaydi. */
const MIN_CLIP_MS = 300;
/** O'ylash/tanish paytida tuman va halqa foydalanuvchi ovozini shuncha kuchsizroq ko'rsatadi. */
const WAITING_LEVEL_DAMP = 0.25;

/** STT navbatidagi bitta gap: fayl, uning balandligi va bo'lib gapirishdanmi. */
interface SttItem {
  file: string | null;
  levelDb: number | null;
  barge: boolean;
  /** Bo'lib gapirish paytida yangrayotgan Barno matni (aks-sado tekshiruvi uchun). */
  echo: readonly string[];
}

function toSnapshot(s: MachineState): VoiceSnapshot {
  return {
    status: s.status,
    micMuted: s.micMuted,
    hearing: s.hearing,
    suspended: s.suspended,
    error: s.error,
    notice: s.notice,
    turnIds: s.turnIds,
    pendingText: s.pendingText,
    holdText: s.holdText,
    speakingId: s.speakingId,
    canSpeak: s.canSpeak,
    earpiece: s.earpiece,
    textOnly: s.textOnly,
    preparing: s.status === 'thinking' && s.answerStarted,
    answersSpoken: s.answersSpoken,
  };
}

function sameSnapshot(a: VoiceSnapshot, b: VoiceSnapshot): boolean {
  return (Object.keys(a) as (keyof VoiceSnapshot)[]).every((k) => a[k] === b[k]);
}

let utteranceSeq = 0;

export function createVoiceSession(deps: VoiceSessionDeps): VoiceSession {
  const { clock, files, speaker } = deps;
  const vad = deps.vad ?? createVad();
  const ttsOff = ttsOffThisRun();
  let state = initialState({ canSpeak: deps.uiLang() === 'uz', ttsOff, earpiece: deps.settings().earpiece });
  let snap = toSnapshot(state);
  const listeners = new Set<() => void>();
  const levelListeners = new Set<LevelListener>();

  const queue: MachineEvent[] = [];
  let processing = false;
  let started = false;
  let ended = false;
  let endPromise: Promise<void> | null = null;
  let awake = false;

  // --- mikrofon ---
  let micWanted = false;
  let micChain: Promise<void> = Promise.resolve();
  /** Kesish/almashtirish ketyapti - eski segment kadrlari VAD'ga bormaydi. */
  let micBusy = false;
  let segmentHadPlayback = false;
  let quietSince: number | null = null;
  let lastMicDb = -160;
  /** Oxirgi tugagan gapning balandligi (VAD hodisasidan; `mic.cut` effekti uni oladi). */
  let cutLevelDb: number | null = null;
  /** Bo'lib gapirish boshlanganda yangrayotgan Barno matni. */
  let bargeEcho: readonly string[] = [];

  // --- STT ---
  const sttQueue: SttItem[] = [];
  let sttRunning = false;
  let sttCtl: AbortController | null = null;
  let sttFile: string | null = null;
  let sttTimer: unknown = null;

  // --- javob ---
  let answerQueue: SentenceQueue | null = null;
  let watched: { id: string; holds: number; answer: string; status: string } | null = null;
  let guardUntil = 0;
  /** Pauzada to'xtagan javob: qaytganda shu joydan davom etadi. */
  let resumeAt: { id: string; spoken: number } | null = null;
  let suspendedAt: number | null = null;

  // --- taymerlar ---
  let frameTimer: unknown = null;
  let levelTimer: unknown = null;
  let idleTimer: unknown = null;
  let noticeTimer: unknown = null;
  let noticeArmedSeq = -1;
  let level = 0;

  let unsubChat: (() => void) | null = null;
  let unsubSpeaker: (() => void) | null = null;

  // ------------------------------------------------------------------ dispatch
  function dispatch(e: MachineEvent) {
    if (ended) return;
    queue.push(e);
    if (processing) return;
    processing = true;
    try {
      while (queue.length) {
        const ev = queue.shift() as MachineEvent;
        const prev = state;
        const t = reduce(state, ev);
        state = t.state;
        for (const fx of t.effects) run(fx);
        afterChange(prev);
        if (state.ended) {
          queue.length = 0;
          break;
        }
      }
    } finally {
      processing = false;
    }
  }

  function afterChange(prev: MachineState) {
    const next = toSnapshot(state);
    if (!sameSnapshot(next, snap)) {
      snap = next;
      for (const l of [...listeners]) l();
    }
    syncIdleTimer();
    syncNoticeTimer();
    syncLevelTimer();
    syncKeepAwake();
    if (state.ended) {
      teardown();
      return;
    }
    const unparked = !!prev.parked && !state.parked;
    if (state.currentId !== prev.currentId || (prev.suspended && !state.suspended) || (prev.answerStarted && !state.answerStarted) || unparked) {
      // Kuzatuv qaytadan: shu paytgacha kelgan javob (masalan bo'lib gapirish tekshirilayotganda)
      // yangi holatga qayta beriladi. Xuddi shu savolning ESKI kutish kliplari esa qayta
      // o'ynalmaydi ("Bir daqiqa..." shovqindan keyin yana eshitilmasin).
      const sameId = state.currentId !== null && state.currentId === prev.currentId;
      const holds = sameId && watched?.id === state.currentId ? watched.holds : 0;
      watched = sameId ? { id: state.currentId as string, holds, answer: '', status: '' } : null;
      if (!state.answerStarted) answerQueue = null;
      onChat();
    }
  }

  // ------------------------------------------------------------------ effektlar
  function run(fx: Effect) {
    switch (fx.type) {
      case 'perm.request':
        deps.requestPermission().then(
          (granted) => dispatch({ type: 'PERMISSION', granted }),
          () => dispatch({ type: 'PERMISSION', granted: false }),
        );
        break;
      case 'readAloud.stop':
        try {
          deps.stopReadAloud?.();
        } catch {
          /* o'qish allaqachon to'xtagan */
        }
        break;
      case 'audio.enter':
        micEnqueue(() => deps.mode.enter({ earpiece: fx.earpiece }).catch(() => {}));
        break;
      case 'audio.earpiece':
        try {
          deps.setEarpiece(fx.on);
        } catch {
          /* saqlanmasa ham joriy sessiyada ishlaydi */
        }
        micEnqueue(() => deps.mode.setEarpiece(fx.on).catch(() => {}));
        break;
      case 'audio.restore':
        // MAJBURIY: aks holda MODE_IN_COMMUNICATION qolib, keyingi har qanday ovoz quloqdan chiqadi.
        micEnqueue(() => deps.mode.restore().catch(() => {}));
        break;
      case 'mic.start':
        micWant(true);
        break;
      case 'mic.release':
        micWant(false);
        break;
      case 'mic.cut':
        micCut(fx.fromMs, fx.toMs, fx.preroll);
        break;
      case 'stt.next':
        startNextStt();
        break;
      case 'stt.abort':
        sttAbort();
        break;
      case 'chat.send': {
        let id: string | null = null;
        try {
          id = deps.chat.sendVoice(fx.text);
        } catch {
          id = null;
        }
        dispatch(id ? { type: 'SENT', id } : { type: 'SEND_BUSY', text: fx.text });
        break;
      }
      case 'chat.stop':
        deps.chat.stop();
        break;
      case 'speaker.hold': {
        const id = fx.id;
        // Tarmoqdan kelgach ham: hali shu savol kutilyaptimi va javob navbatga tushmaganmi.
        speaker.hold(fx.cue, () => !ended && state.status === 'thinking' && state.currentId === id && !state.suspended && state.canSpeak && !state.answerStarted);
        break;
      }
      case 'speaker.speak': {
        answerQueue = createSentenceQueue();
        // Pauzadan qaytdik: aytib bo'lingan qism qayta o'qilmaydi.
        if (resumeAt && resumeAt.id === fx.id) answerQueue.skip(resumeAt.spoken);
        resumeAt = null;
        speaker.speak(fx.id, answerQueue, deps.chat.exchange(fx.id)?.turnId ?? null);
        break;
      }
      case 'speaker.push':
        answerQueue?.push(fx.text, fx.done);
        speaker.pump();
        break;
      case 'speaker.stop': {
        if (fx.keep) {
          const p = speaker.progress();
          resumeAt = p.key && p.remaining ? { id: p.key, spoken: p.spoken } : null;
        } else resumeAt = null;
        speaker.stop();
        answerQueue = null;
        break;
      }
      case 'speaker.stopHold':
        speaker.stopHold();
        break;
      case 'speaker.pause':
        speaker.pause();
        break;
      case 'speaker.resume':
        speaker.resume();
        break;
      case 'vad.guard':
        guardUntil = clock.now() + POST_SPEECH_GUARD_MS;
        break;
      case 'vad.bargeDiscard':
        vad.noteDiscardAfterBarge();
        break;
      case 'files.clear':
        micEnqueue(async () => {
          try {
            files.clear('voice');
          } catch {
            /* kesh baribir tozalanadi */
          }
        });
        break;
      default:
        break;
    }
  }

  // ------------------------------------------------------------------ mikrofon
  function micEnqueue(op: () => Promise<void>): Promise<void> {
    micChain = micChain.then(op).catch(() => {});
    return micChain;
  }

  async function safeStop(): Promise<string | null> {
    try {
      return await deps.mic.stop();
    } catch {
      // expo-audio ~0.5 s dan qisqa segmentda stop() da yiqilishi mumkin.
      return null;
    }
  }

  function onSegmentStart() {
    vad.reset();
    segmentHadPlayback = speaker.output().source !== null;
    quietSince = null;
  }

  async function startSegment(): Promise<boolean> {
    try {
      await deps.mic.start();
      onSegmentStart();
      return true;
    } catch {
      micWanted = false;
      dispatch({ type: 'MIC_FAILED' });
      return false;
    }
  }

  async function ensureMic() {
    if (ended) micWanted = false;
    if (micWanted && !deps.mic.recording) {
      if (await startSegment()) dispatch({ type: 'MIC_READY' });
    } else if (!micWanted && deps.mic.recording) {
      files.remove(await safeStop());
    }
  }

  function micWant(on: boolean) {
    micWanted = on;
    micEnqueue(ensureMic);
  }

  /** Segment hozir qayerda (devor soati bo'yicha) - fayl bilan farqni o'lchash uchun. */
  function segmentNowMs(): number | null {
    try {
      return deps.mic.poll()?.tMs ?? null;
    } catch {
      return null;
    }
  }

  /**
   * Gap tugadi: segment yopiladi, DARHOL yangisi ochiladi va SHU PAYTDA gap kesib olinib
   * STT'ga ketadi (yangi segment tayyor bo'lishini kutmaydi - har savolga 100-300 ms tejaladi).
   */
  function micCut(fromMs: number, toMs: number, preroll: boolean) {
    micBusy = true;
    const item = { levelDb: cutLevelDb, barge: state.bargeUtterance, echo: state.bargeUtterance ? bargeEcho : [] };
    cutLevelDb = null;
    micEnqueue(async () => {
      try {
        if (!deps.mic.recording) {
          enqueueStt({ ...item, file: null });
          return;
        }
        const hadPlayback = segmentHadPlayback;
        const endMs = segmentNowMs();
        const uri = await safeStop();
        const restart = micWanted && !ended ? startSegment() : Promise.resolve(false);
        const clip = uri ? await extractUtterance(uri, fromMs, toMs, hadPlayback, endMs, preroll) : null;
        if (uri && clip !== uri) files.remove(uri);
        enqueueStt({ ...item, file: clip });
        await restart;
      } finally {
        micBusy = false;
      }
    });
  }

  async function extractUtterance(uri: string, fromMs: number, toMs: number, hadPlayback: boolean, endMs: number | null, preroll: boolean): Promise<string | null> {
    let bytes: Uint8Array;
    try {
      bytes = await files.read(uri);
    } catch {
      // O'qib bo'lmadi: Barno ovozi yozilmagan bo'lsa butun segment yaraydi.
      return hadPlayback ? null : uri;
    }
    try {
      // VAD vaqti - `record()` dan beri devor soati; fayl esa mikrofon ochilgach boshlanadi.
      // Farq (kechikish) segment OXIRIDA o'lchanadi: devor soati - fayl davomiyligi.
      const fileMs = adtsDurationMs(bytes);
      const offset = endMs !== null && fileMs > 0 ? Math.min(MAX_CAPTURE_OFFSET_MS, Math.max(0, endMs - fileMs)) : 0;
      // Bo'lib gapirishda oldingi qism faqat Barno aks-sadosi - STT uni savol boshiga yopishtirardi.
      const pre = preroll ? PREROLL_MS : 0;
      const trimmed = trimAdts(bytes, Math.max(0, fromMs - pre - offset), toMs + POSTROLL_MS - offset);
      if (trimmed && adtsDurationMs(trimmed) >= MIN_CLIP_MS) return files.write('voice', `utt-${Date.now().toString(36)}-${++utteranceSeq}.aac`, trimmed);
    } catch {
      /* quyida zaxira */
    }
    // Kesib bo'lmadi: segmentda Barno ovozi bo'lmasa butun fayl; bo'lsa - o'z ovozini savol qilmaymiz.
    return hadPlayback ? null : uri;
  }

  function rotate() {
    micBusy = true;
    micEnqueue(async () => {
      try {
        if (!deps.mic.recording) return;
        files.remove(await safeStop());
        if (micWanted && !ended) await startSegment();
      } finally {
        micBusy = false;
      }
    });
  }

  // ------------------------------------------------------------------ STT
  function enqueueStt(item: SttItem) {
    // Xato yoki pauza paytida kesib bo'lingan gap endi kerak emas.
    if (ended || state.status === 'error' || state.suspended) {
      files.remove(item.file);
      return;
    }
    sttQueue.push(item);
    if (!sttRunning) startNextStt();
  }

  function finishStt() {
    if (sttTimer != null) clock.clearTimeout(sttTimer);
    sttTimer = null;
    sttRunning = false;
    sttCtl = null;
    files.remove(sttFile);
    sttFile = null;
  }

  /** Tanilgan matn: bo'lib gapirish bo'lsa - avval aks-sado va "to'xta" tekshiriladi. */
  function sttResult(item: SttItem, text: string, lowConfidence: boolean) {
    if (text.length < 2) {
      dispatch({ type: 'STT_EMPTY' });
      return;
    }
    if (item.barge && !lowConfidence && isEchoOf(text, item.echo)) {
      dispatch({ type: 'STT_ECHO' });
      return;
    }
    if (item.barge && isStopCommand(text)) {
      dispatch({ type: 'STT_STOP' });
      return;
    }
    // Egasining ovozi balandligi: shovqinli xonada hamkasb gapini ajratish uchun.
    if (!item.barge && !lowConfidence && item.levelDb !== null) vad.noteUserLevel(item.levelDb);
    dispatch({ type: 'STT_OK', text, lowConfidence });
  }

  function startNextStt() {
    if (sttRunning || !sttQueue.length || ended) return;
    const item = sttQueue.shift() as SttItem;
    const file = item.file;
    if (file === null) {
      dispatch({ type: 'STT_EMPTY' });
      return;
    }
    sttRunning = true;
    sttFile = file;
    const ctl = new AbortController();
    sttCtl = ctl;
    let timedOut = false;
    sttTimer = clock.setTimeout(() => {
      timedOut = true;
      ctl.abort();
    }, STT_TIMEOUT_MS);
    deps.stt.transcribe(file, deps.uiLang(), ctl.signal).then(
      (res) => {
        if (sttCtl !== ctl) return;
        finishStt();
        sttResult(item, (res?.text ?? '').trim(), !!res?.lowConfidence);
      },
      (err: unknown) => {
        if (sttCtl !== ctl) return;
        finishStt();
        if (timedOut) dispatch({ type: 'STT_TIMEOUT' });
        else if (err instanceof StreamAbortedError) dispatch({ type: 'STT_TIMEOUT' });
        else dispatch({ type: 'STT_FAILED', network: err instanceof ApiError && err.code === 'network' });
      },
    );
  }

  function sttAbort() {
    const ctl = sttCtl;
    finishStt();
    ctl?.abort();
    for (const it of sttQueue) files.remove(it.file);
    sttQueue.length = 0;
  }

  // ------------------------------------------------------------------ kadrlar (VAD)
  function vadMode(out: SpeakerOutput): VadMode {
    if (state.suspended || state.micMuted) return 'off';
    switch (state.status) {
      case 'listening':
      case 'transcribing':
        return 'listen';
      case 'thinking':
        return out.source === 'hold' ? 'thinking_hold' : 'thinking';
      case 'speaking':
        return 'speaking';
      default:
        return 'off';
    }
  }

  function onFrame() {
    if (ended || state.suspended || micBusy) return;
    let frame: MicFrame | null = null;
    try {
      frame = deps.mic.poll();
    } catch {
      frame = null;
    }
    if (!frame) return;
    lastMicDb = frame.db;
    const out = speaker.output();
    if (out.source) segmentHadPlayback = true;
    const ev = vad.push(frame, {
      mode: vadMode(out),
      outDbMax: out.source ? out.db : null,
      clipAgeMs: out.clipAgeMs,
      earpiece: state.earpiece,
      guard: clock.now() < guardUntil,
    });
    if (ev) {
      if (ev.type === 'barge_in') {
        // Mashina ovozni to'xtatishidan OLDIN: hozir nima yangrayotgan edi (aks-sado tekshiruvi).
        const texts = speaker.recentText();
        bargeEcho = state.holdText ? [...texts, state.holdText] : texts;
      }
      if (ev.type === 'speech_end' || ev.type === 'max_reached') cutLevelDb = ev.levelDb;
      dispatch({ type: 'VAD', event: ev });
    }
    maybeRotate(frame, out);
  }

  /**
   * Uzoq segment almashtiriladi (fayl kichik qolsin) - faqat odam gapirmaydigan paytda:
   * tinglashda 2.5 s jimlikdan keyin yoki javob kutilayotganda (klip yo'q, hech kim gapirmaydi).
   */
  function maybeRotate(frame: MicFrame, out: SpeakerOutput) {
    if (micBusy || vad.inSpeech || frame.tMs < SEGMENT_ROTATE_MS) {
      if (vad.inSpeech) quietSince = null;
      return;
    }
    if (frame.db < vad.startDb - 6) quietSince = quietSince ?? frame.tMs;
    else quietSince = null;
    if (quietSince === null) return;
    const quiet = frame.tMs - quietSince;
    const listening = state.status === 'listening' && !state.parked && quiet >= ROTATE_QUIET_LISTEN_MS;
    const waiting = state.status === 'thinking' && !out.source && !vad.bargeBuilding && quiet >= ROTATE_QUIET_THINK_MS;
    if (listening || waiting) rotate();
  }

  // ------------------------------------------------------------------ chat kuzatuvi
  function onChat() {
    if (ended) return;
    if (state.pendingAuto && state.pendingText && !deps.chat.busy()) {
      dispatch({ type: 'SEND_PENDING', busy: false, auto: true });
    }
    const id = state.currentId;
    if (!id) {
      watched = null;
      return;
    }
    const ex = deps.chat.exchange(id);
    if (!ex) {
      // Yangi suhbat ochildi yoki tarix almashdi - bu savol endi yo'q.
      dispatch({ type: 'ANSWER_FAILED', id });
      return;
    }
    if (!watched || watched.id !== id) watched = { id, holds: 0, answer: '', status: '' };
    const w = watched;
    const holds = ex.holds ?? [];
    if (holds.length > w.holds) {
      const fresh = holds.slice(w.holds);
      w.holds = holds.length;
      for (const cue of fresh) dispatch({ type: 'HOLD', id, cue });
    }
    if (ex.answer !== w.answer || ex.status !== w.status) {
      w.answer = ex.answer;
      w.status = ex.status;
      const failed = ex.status === 'error' || ex.status === 'cancelled' || (ex.status === 'stopped' && !ex.answer);
      if (failed) {
        dispatch({ type: 'ANSWER_FAILED', id });
        return;
      }
      const done = ex.status === 'done' || ex.status === 'stopped';
      if (ex.answer || done) dispatch({ type: 'ANSWER', id, text: ex.answer, done, proposal: !!ex.proposal });
    }
  }

  // ------------------------------------------------------------------ taymerlar
  function syncIdleTimer() {
    const armed = !ended && state.status === 'listening' && !state.hearing && !state.micMuted && !state.suspended && !state.parked;
    if (armed && idleTimer == null) {
      idleTimer = clock.setTimeout(() => {
        idleTimer = null;
        dispatch({ type: 'IDLE_TIMEOUT' });
      }, LISTEN_IDLE_MS);
    } else if (!armed && idleTimer != null) {
      clock.clearTimeout(idleTimer);
      idleTimer = null;
    }
  }

  function syncNoticeTimer() {
    if (!state.notice || ended) {
      if (noticeTimer != null) clock.clearTimeout(noticeTimer);
      noticeTimer = null;
      noticeArmedSeq = -1;
      return;
    }
    if (noticeArmedSeq === state.noticeSeq) return;
    if (noticeTimer != null) clock.clearTimeout(noticeTimer);
    const seq = state.noticeSeq;
    noticeArmedSeq = seq;
    noticeTimer = clock.setTimeout(() => {
      noticeTimer = null;
      dispatch({ type: 'NOTICE_EXPIRED', seq });
    }, NOTICE_MS);
  }

  /**
   * Ekran yoqiq: suhbat jonli bo'lganda (tinglash, o'ylash, gapirish). Mikrofon o'chiq kutish,
   * xato va pauzada - odatiy uyqu (tashlab ketilgan sessiya ekranni abadiy yoqiq ushlamasin).
   */
  function syncKeepAwake() {
    const want = started && !ended && !state.suspended && state.status !== 'muted' && state.status !== 'error';
    if (want === awake) return;
    awake = want;
    try {
      deps.keepAwake(want);
    } catch {
      /* ekranni yoqiq ushlab bo'lmasa ham ishlaydi */
    }
  }

  function levelTick() {
    const out = speaker.output();
    let target = 0;
    let source: FogSource = 'none';
    if (out.source && !vad.bargeBuilding) {
      source = 'barno';
      target = out.level;
    } else if (!state.micMuted && !state.suspended && deps.mic.recording) {
      source = 'user';
      target = micLevel(lastMicDb, vad.startDb);
      // O'ylash va tanish "tinglayapman" dan farq qilsin: xona shovqini tumanni ko'tarmaydi.
      // Odam haqiqatan gapira boshlasa (bo'lib gapirish yig'ilyapti) - to'liq ko'rinadi.
      if ((state.status === 'thinking' || state.status === 'transcribing') && !state.hearing && !vad.bargeBuilding) target *= WAITING_LEVEL_DAMP;
    }
    level = smoothLevel(level, target);
    for (const l of [...levelListeners]) l(level, source);
  }

  function syncLevelTimer() {
    const want = !ended && started && levelListeners.size > 0 && !state.suspended;
    if (want && levelTimer == null) levelTimer = clock.setInterval(levelTick, LEVEL_TICK_MS);
    else if (!want && levelTimer != null) {
      clock.clearInterval(levelTimer);
      levelTimer = null;
    }
  }

  // ------------------------------------------------------------------ hayot sikli
  function teardown() {
    if (ended) return;
    ended = true;
    for (const h of [idleTimer, noticeTimer, sttTimer]) if (h != null) clock.clearTimeout(h);
    for (const h of [frameTimer, levelTimer]) if (h != null) clock.clearInterval(h);
    frameTimer = levelTimer = idleTimer = noticeTimer = sttTimer = null;
    unsubChat?.();
    unsubSpeaker?.();
    unsubChat = unsubSpeaker = null;
    if (awake) {
      awake = false;
      try {
        deps.keepAwake(false);
      } catch {
        /* no-op */
      }
    }
    endPromise = micChain.then(() => {
      try {
        speaker.dispose();
      } catch {
        /* allaqachon bo'shatilgan */
      }
    });
  }

  function pendingAnswer(): boolean {
    const id = state.currentId;
    if (!id) return false;
    const ex = deps.chat.exchange(id);
    return !!ex && (ex.status === 'pending' || ex.status === 'streaming');
  }

  /** Qaytganda javobni davom ettirish kerakmi: tayyor, aytilmagan qismi bor va eskirmagan. */
  function resumableAnswer(): boolean {
    const id = state.currentId;
    if (!id) return false;
    const ex = deps.chat.exchange(id);
    if (!ex || !ex.answer || (ex.status !== 'done' && ex.status !== 'stopped')) return false;
    if (resumeAt?.id === id) return true;
    // Hali boshlanmagan javob yo'qligimizda keldi - yaqinda bo'lsa o'qiymiz (odam uni kutgan edi).
    return state.status === 'thinking' && suspendedAt !== null && clock.now() - suspendedAt < RESUME_FRESH_MS;
  }

  const actions: VoiceActions = {
    toggleMute: () => dispatch(state.micMuted ? { type: 'UNMUTE', meetingActive: deps.meetingActive() } : { type: 'MUTE' }),
    setEarpiece: (on) => dispatch({ type: 'SET_EARPIECE', on }),
    interrupt: () => dispatch({ type: 'TAP_INTERRUPT' }),
    retry: () => dispatch({ type: 'RETRY', meetingActive: deps.meetingActive() }),
    sendPending: () => dispatch({ type: 'SEND_PENDING', busy: deps.chat.busy() }),
    dismissNotice: () => dispatch({ type: 'DISMISS_NOTICE' }),
    end: () => {
      if (!ended) {
        if (!started) {
          // Hech narsa ochilmagan - faqat tozalash.
          state = { ...state, ended: true };
          teardown();
        } else dispatch({ type: 'END' });
      }
      return endPromise ?? Promise.resolve();
    },
  };

  return {
    start() {
      if (started || ended) return;
      started = true;
      // Oldingi (yiqilgan) sessiyalardan qolgan yozuv segmentlari.
      try {
        files.sweepRecordings?.(STALE_RECORDING_MS);
      } catch {
        /* keyingi safar */
      }
      unsubChat = deps.chat.subscribe(onChat);
      unsubSpeaker = speaker.subscribe((event) => {
        if (event.type === 'hold_end' || event.type === 'speech_end') guardUntil = clock.now() + POST_SPEECH_GUARD_MS;
        dispatch({ type: 'SPEAKER', event });
      });
      frameTimer = clock.setInterval(onFrame, FRAME_MS);
      syncLevelTimer();
      dispatch({ type: 'START', meetingActive: deps.meetingActive() });
    },
    getSnapshot: () => snap,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    subscribeLevel(listener) {
      levelListeners.add(listener);
      syncLevelTimer();
      return () => {
        levelListeners.delete(listener);
        syncLevelTimer();
      };
    },
    dispatch,
    suspend: () => {
      if (!state.suspended) suspendedAt = clock.now();
      dispatch({ type: 'SUSPEND' });
    },
    resume: () => dispatch({ type: 'RESUME', pending: pendingAnswer(), resumable: resumableAnswer(), meetingActive: deps.meetingActive() }),
    actions,
    get state() {
      return state;
    },
  };
}
