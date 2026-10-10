/**
 * Ovozli suhbat holat mashinasi - TOZA funksiya: (holat, hodisa) -> (yangi holat, effektlar).
 *
 * NIMA UCHUN toza: mikrofon, tarmoq, pleer va taymerlar bir-biriga chalkashadigan joy -
 * qoidalar (spec 4.2 jadvali) shu yerda bir joyda, har biri testda tekshiriladi;
 * `session.ts` faqat effektlarni bajaradi va natijani hodisa qilib qaytaradi.
 *
 * Bo'lib gapirish "to'xtab turish" (parked) bilan: Barno gapirayotganda yoki javob
 * kutilayotganda mikrofon ovoz eshitsa - ovoz PAUZA qilinadi (yoki kutish klipi
 * to'xtaydi), lekin savol/javob BEKOR QILINMAYDI. Faqat STT haqiqiy matn qaytarsa (2+
 * belgi, ishonchli, Barnoning o'z gapi emas) - eski javob tashlanib yangi savol ketadi.
 * Shovqin, yo'tal, hamkasb gapi yoki o'z aks-sadosi bo'lsa - hech narsa yo'qolmaydi: kutish
 * davom etadi yoki Barno to'xtagan joyidan gapiraveradi. NIMA UCHUN: 12 s kutishni yoki
 * yarim javobni yo'talga almashtirish - kech bo'lib gapirishdan ancha qimmat.
 */
import type { HoldCue } from '@/features/chat/chatStore';

import { STT_MAX_FAILURES } from './limits';
import type { SpeakerEvent } from './speaker';
import { isSpeakable } from './speechText';
import type { VoiceErrorKind, VoiceNoticeKind, VoiceStatus } from './types';
import type { VadEvent } from './vad';

export interface MachineState {
  status: VoiceStatus;
  /** Foydalanuvchi o'chirdi yoki o'zi o'chdi - mikrofon bo'sh. */
  micMuted: boolean;
  /** VAD hozir gapni eshityapti. */
  hearing: boolean;
  /** Ekran yashirin / ilova fonda - mikrofon va ovoz to'xtagan. */
  suspended: boolean;
  error: VoiceErrorKind | null;
  notice: VoiceNoticeKind | null;
  /** Har yangi eslatmada oshadi - 4 s taymeri shunga bog'lanadi. */
  noticeSeq: number;
  /** Shu sessiyada yaratilgan savollar (chat exchange id). */
  turnIds: readonly string[];
  /** Javobi kutilayotgan savol. */
  currentId: string | null;
  /** Tanilgan, lekin yuborilmagan (ishonchsiz yoki chat band). */
  pendingText: string | null;
  /** Chat bo'shashi bilan o'zi yuboriladi (faqat "band" holatida, "ishonchsiz"da emas). */
  pendingAuto: boolean;
  /** Davomli gapning birinchi qismi (odam 1 s dan uzoq to'xtab yana gapirdi). */
  prefix: string | null;
  /** Tanilayotganda yana gapira boshladi (VAD hozir gapda). */
  continuation: boolean;
  /** Tanilish navbatida turgan (kesilgan) gaplar soni. */
  sttQueued: number;
  sttFailures: number;
  holdText: string | null;
  speakingId: string | null;
  canSpeak: boolean;
  ttsOff: boolean;
  earpiece: boolean;
  uzOnlyShown: boolean;
  /** Joriy javob uchun ovoz navbati ochilgan. */
  answerStarted: boolean;
  /** Joriy gap Barnoni bo'lishdan boshlangan (o'z ovozini eshitish ehtimoli). */
  bargeUtterance: boolean;
  /**
   * Bo'lib gapirish tekshirilyapti: `currentId` savoli tirik - 'thinking' (javob kutilyapti,
   * so'rov bekor qilinmagan) yoki 'speaking' (Barno pauzada). Gap shovqin bo'lib chiqsa shu
   * holatga qaytiladi.
   */
  parked: 'thinking' | 'speaking' | null;
  /** Oxirgi yuborilgan savol matni (javob boshlanmasdan bo'lib gapirilsa - birlashtiriladi). */
  sentText: string | null;
  /** Joriy savolga javob matni kela boshlagan. */
  answerSeen: boolean;
  /** Oxirgi javob ovozda to'liq aytilmadi (ru/en, xato, uzun...) - matn ekranda ko'rinsin. */
  textOnly: boolean;
  /** Shu sessiyada ovozda boshlangan javoblar soni (ko'rsatma faqat birinchilarida). */
  answersSpoken: number;
  ended: boolean;
}

export type MachineEvent =
  | { type: 'START'; meetingActive: boolean }
  | { type: 'PERMISSION'; granted: boolean }
  | { type: 'MIC_READY' }
  | { type: 'MIC_FAILED' }
  | { type: 'VAD'; event: VadEvent }
  | { type: 'STT_OK'; text: string; lowConfidence: boolean }
  /** Bo'lib gapirish matni Barnoning o'z gapi bilan mos keldi - aks-sado. */
  | { type: 'STT_ECHO' }
  /** Bo'lib gapirish matni - to'xtatish buyrug'i ("to'xta", "bas", "stop"). */
  | { type: 'STT_STOP' }
  | { type: 'STT_EMPTY' }
  | { type: 'STT_FAILED'; network: boolean }
  | { type: 'STT_TIMEOUT' }
  | { type: 'SENT'; id: string }
  | { type: 'SEND_BUSY'; text: string }
  | { type: 'HOLD'; id: string; cue: HoldCue }
  | { type: 'ANSWER'; id: string; text: string; done: boolean; proposal: boolean }
  | { type: 'ANSWER_FAILED'; id: string }
  | { type: 'SPEAKER'; event: SpeakerEvent }
  | { type: 'TAP_INTERRUPT' }
  | { type: 'MUTE' }
  | { type: 'UNMUTE'; meetingActive?: boolean }
  | { type: 'IDLE_TIMEOUT' }
  | { type: 'SUSPEND' }
  /** `resumable` - javob tayyor va hali to'liq aytilmagan (qaytganda davom ettiriladi). */
  | { type: 'RESUME'; pending: boolean; resumable?: boolean; meetingActive?: boolean }
  | { type: 'RETRY'; meetingActive: boolean }
  | { type: 'SEND_PENDING'; busy: boolean; auto?: boolean }
  | { type: 'SET_EARPIECE'; on: boolean }
  | { type: 'NOTICE_EXPIRED'; seq: number }
  | { type: 'DISMISS_NOTICE' }
  | { type: 'END' };

export type Effect =
  | { type: 'perm.request' }
  | { type: 'readAloud.stop' }
  | { type: 'audio.enter'; earpiece: boolean }
  | { type: 'audio.earpiece'; on: boolean }
  | { type: 'audio.restore' }
  | { type: 'mic.start' }
  | { type: 'mic.release' }
  /** `preroll: false` - bo'lib gapirish: gapdan oldingi qismda faqat Barno aks-sadosi bor. */
  | { type: 'mic.cut'; fromMs: number; toMs: number; preroll: boolean }
  | { type: 'stt.next' }
  | { type: 'stt.abort' }
  | { type: 'chat.send'; text: string }
  | { type: 'chat.stop' }
  | { type: 'speaker.hold'; id: string; cue: HoldCue }
  | { type: 'speaker.speak'; id: string }
  | { type: 'speaker.push'; id: string; text: string; done: boolean }
  /** `keep` - qayerda to'xtagani eslab qolinadi (pauzadan qaytganda davom etadi). */
  | { type: 'speaker.stop'; keep?: boolean }
  | { type: 'speaker.stopHold' }
  | { type: 'speaker.pause' }
  | { type: 'speaker.resume' }
  | { type: 'vad.guard' }
  | { type: 'vad.bargeDiscard' }
  | { type: 'files.clear' };

export interface Transition {
  state: MachineState;
  effects: Effect[];
}

export function initialState(o: { canSpeak: boolean; ttsOff: boolean; earpiece: boolean }): MachineState {
  return {
    status: 'idle',
    micMuted: false,
    hearing: false,
    suspended: false,
    error: null,
    notice: null,
    noticeSeq: 0,
    turnIds: [],
    currentId: null,
    pendingText: null,
    pendingAuto: false,
    prefix: null,
    continuation: false,
    sttQueued: 0,
    sttFailures: 0,
    holdText: null,
    speakingId: null,
    canSpeak: o.canSpeak && !o.ttsOff,
    ttsOff: o.ttsOff,
    earpiece: o.earpiece,
    uzOnlyShown: false,
    answerStarted: false,
    bargeUtterance: false,
    parked: null,
    sentText: null,
    answerSeen: false,
    textOnly: false,
    answersSpoken: 0,
    ended: false,
  };
}

/** "Davomli gap" birlashtirish: bo'shliqlar bitta. */
export function joinText(a: string | null, b: string | null): string {
  return [a, b]
    .filter((x): x is string => !!x && !!x.trim())
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const same = (state: MachineState): Transition => ({ state, effects: [] });
/** Foydalanuvchini kutadigan holat: mikrofon o'chiq bo'lsa "muted". */
const rest = (s: MachineState): VoiceStatus => (s.micMuted ? 'muted' : 'listening');
const withNotice = (s: MachineState, notice: VoiceNoticeKind): MachineState => ({ ...s, notice, noticeSeq: s.noticeSeq + 1 });
/** Javob ovozda to'liq aytilmaydigan eslatmalar - matn ekranda ko'rinishi shart. */
const TEXT_ONLY_NOTICES: ReadonlySet<VoiceNoticeKind> = new Set(['uz_only', 'not_uzbek', 'tts_failed', 'tts_off', 'shortened', 'see_screen']);
const textNotice = (s: MachineState, notice: VoiceNoticeKind): MachineState => ({ ...withNotice(s, notice), textOnly: s.textOnly || TEXT_ONLY_NOTICES.has(notice) });

/** Javob kutish/ovoz tugadi - foydalanuvchini tinglashga qaytamiz. */
function toRest(s: MachineState): MachineState {
  return { ...s, status: rest(s), currentId: null, speakingId: null, holdText: null, answerStarted: false, hearing: false, parked: null };
}

function fail(s: MachineState, error: VoiceErrorKind): Transition {
  return {
    state: {
      ...s,
      status: 'error',
      error,
      hearing: false,
      continuation: false,
      sttQueued: 0,
      prefix: null,
      holdText: null,
      speakingId: null,
      currentId: null,
      answerStarted: false,
      parked: null,
      bargeUtterance: false,
    },
    effects: [{ type: 'mic.release' }, { type: 'speaker.stop' }, { type: 'stt.abort' }],
  };
}

function send(s: MachineState, text: string): Transition {
  return {
    state: {
      ...s,
      status: 'thinking',
      prefix: null,
      pendingText: null,
      pendingAuto: false,
      hearing: false,
      continuation: false,
      holdText: null,
      currentId: null,
      speakingId: null,
      answerStarted: false,
      parked: null,
      bargeUtterance: false,
      sentText: text,
      answerSeen: false,
      textOnly: false,
    },
    effects: [{ type: 'chat.send', text }],
  };
}

/**
 * Bo'lib gapirish yolg'on chiqdi (shovqin, aks-sado, bo'sh matn): to'xtab turgan savolga
 * qaytamiz - kutish davom etadi yoki Barno pauzadan davom etadi. Ogohlantirish YO'Q:
 * odam hech narsa demagan, "qaytadan ayting" deyish noto'g'ri.
 */
function unpark(s: MachineState, effects: Effect[] = []): Transition {
  const base: MachineState = { ...s, parked: null, bargeUtterance: false, hearing: false, continuation: false, prefix: null };
  if (s.parked === 'speaking') return { state: { ...base, status: 'speaking' }, effects: [...effects, { type: 'speaker.resume' }] };
  if (s.parked === 'thinking') return { state: { ...base, status: 'thinking' }, effects };
  return { state: { ...base, status: rest(base) }, effects };
}

/** Tanilish natijasidan keyin yuboradigan narsa yo'q: navbat, davom etayotgan gap yoki tinglash. */
function afterResult(s: MachineState, effects: Effect[] = []): Transition {
  if (s.sttQueued > 0) return { state: { ...s, status: 'transcribing', sttQueued: s.sttQueued - 1 }, effects: [...effects, { type: 'stt.next' }] };
  if (s.continuation) return { state: { ...s, status: 'listening', hearing: true, continuation: false }, effects };
  return { state: { ...s, status: rest(s), hearing: false }, effects };
}

/** Odam haqiqatan gapirdi: bo'lib gapirish tekshirilayotgan bo'lsa eski savol/ovoz endi tashlanadi. */
function sendSpoken(s: MachineState, joined: string, effects: Effect[]): Transition {
  const pre: Effect[] = [...effects];
  let question = joined;
  if (s.parked === 'thinking') {
    // Endi aniq: odam yangi narsa dedi - kutilayotgan so'rov bekor ("bekor qilindi" chatda).
    pre.push({ type: 'chat.stop' });
    // Javob hali boshlanmagan: odam savolini o'rtada to'xtab davom ettirgan bo'lishi mumkin -
    // ikkalasi BITTA savol bo'lib qayta ketadi (birinchi yarmi yo'qolmaydi).
    if (!s.answerSeen && s.sentText) question = joinText(s.sentText, joined);
  } else if (s.parked === 'speaking') {
    pre.push({ type: 'speaker.stop' });
  }
  const sent = send(s, question);
  return { state: sent.state, effects: [...pre, ...sent.effects] };
}

function onSttText(s0: MachineState, text: string | null, lowConfidence: boolean): Transition {
  const barge = s0.bargeUtterance;
  let s: MachineState = { ...s0, sttFailures: 0 };
  const t = (text ?? '').trim();
  const raw = t.length >= 2 ? t : '';
  const discard: Effect[] = (!raw || lowConfidence) && barge ? [{ type: 'vad.bargeDiscard' }] : [];
  if (raw && lowConfidence && !s.parked) {
    // Router: ishonchsiz matnda so'z xatosi ~60-70% - o'zimiz yubormaymiz, odam qaror qiladi.
    s = withNotice({ ...s, pendingText: joinText(s.prefix, raw), pendingAuto: false, prefix: null, bargeUtterance: false }, 'unsure');
    return afterResult(s, discard);
  }
  // Bo'lib gapirish tekshirilayotganda ishonchsiz matn tashlanadi: ko'pincha shovqin yoki hamkasb.
  const usable = lowConfidence ? '' : raw;
  const joined = usable ? joinText(s.prefix, usable) : s.prefix ?? '';
  if (s.sttQueued > 0) {
    return { state: { ...s, prefix: joined || null, sttQueued: s.sttQueued - 1, status: 'transcribing' }, effects: [...discard, { type: 'stt.next' }] };
  }
  if (s.continuation) {
    // Odam hali gapiryapti: birinchi qism kutib turadi, ikkalasi BITTA savol bo'lib ketadi.
    return { state: { ...s, prefix: joined || null, continuation: false, status: 'listening', hearing: true }, effects: discard };
  }
  if (joined.length >= 2) return sendSpoken(s, joined, discard);
  if (s.parked) return unpark(s, discard);
  // Bo'lib gapirish bo'sh chiqdi: odam hech narsa demagan - "qaytadan ayting" demaymiz.
  if (barge) return { state: { ...s, status: rest(s), prefix: null, hearing: false, bargeUtterance: false }, effects: discard };
  return { state: withNotice({ ...s, status: rest(s), prefix: null, hearing: false }, 'no_speech'), effects: discard };
}

function onSttFailure(s: MachineState, network: boolean): Transition {
  if (network) return fail(s, 'offline');
  const failures = s.sttFailures + 1;
  if (failures >= STT_MAX_FAILURES) return fail({ ...s, sttFailures: failures }, 'stt_failed');
  let next: MachineState = withNotice({ ...s, sttFailures: failures, bargeUtterance: false }, 'stt_retry');
  if (next.parked && next.sttQueued === 0 && !next.continuation) {
    // Bo'lib gapirgan gap tanilmadi: kutish / Barno davom etadi, odam qaytadan aytadi.
    const prefix = next.prefix;
    const back = unpark(next);
    return prefix ? { ...back, state: { ...back.state, pendingText: prefix, pendingAuto: false } } : back;
  }
  if (next.prefix && next.sttQueued === 0 && !next.continuation) {
    // Birinchi qism tanilgan edi - yo'qolmasin, odam o'zi yuboradi.
    next = { ...next, pendingText: next.prefix, pendingAuto: false, prefix: null };
  }
  return afterResult(next);
}

function onVad(s: MachineState, e: VadEvent): Transition {
  if (s.suspended || s.micMuted) return same(s);
  switch (s.status) {
    case 'listening':
      if (e.type === 'speech_start') return same({ ...s, hearing: true, notice: null, bargeUtterance: s.parked ? s.bargeUtterance : false });
      if (e.type === 'speech_end' || e.type === 'max_reached') {
        return {
          state: { ...s, status: 'transcribing', hearing: false },
          effects: [{ type: 'mic.cut', fromMs: e.fromMs, toMs: e.toMs, preroll: !s.bargeUtterance }],
        };
      }
      if (e.type === 'speech_discard') {
        const effects: Effect[] = s.bargeUtterance ? [{ type: 'vad.bargeDiscard' }] : [];
        // Davomi shovqin bo'lib chiqdi - birinchi qismning o'zi yuboriladi.
        if (s.prefix) return sendSpoken({ ...s, hearing: false }, s.prefix, effects);
        if (s.parked) return unpark(s, effects);
        return { state: { ...s, hearing: false, bargeUtterance: false }, effects };
      }
      return same(s);
    case 'transcribing':
      if (e.type === 'speech_start') return same({ ...s, continuation: true, hearing: true });
      if (e.type === 'speech_end' || e.type === 'max_reached') {
        return {
          state: { ...s, continuation: false, hearing: false, sttQueued: s.sttQueued + 1 },
          effects: [{ type: 'mic.cut', fromMs: e.fromMs, toMs: e.toMs, preroll: true }],
        };
      }
      if (e.type === 'speech_discard') return same({ ...s, continuation: false, hearing: false });
      return same(s);
    case 'thinking':
      if (e.type !== 'barge_in') return same(s);
      // Kutish klipi (va navbatdagi javob ovozi) to'xtaydi, lekin SO'ROV BEKOR EMAS - avval
      // eshitamiz: haqiqiy savolmi yoki shovqin.
      return {
        state: { ...s, status: 'listening', hearing: true, holdText: null, answerStarted: false, bargeUtterance: true, parked: 'thinking' },
        effects: [{ type: 'speaker.stop' }],
      };
    case 'speaking':
      if (e.type !== 'barge_in') return same(s);
      // Barno PAUZADA - gap shovqin bo'lib chiqsa shu joydan davom etadi; javob chatda to'liq.
      return {
        state: { ...s, status: 'listening', hearing: true, holdText: null, bargeUtterance: true, parked: 'speaking' },
        effects: [{ type: 'speaker.pause' }],
      };
    default:
      return same(s);
  }
}

function onAnswer(s: MachineState, e: Extract<MachineEvent, { type: 'ANSWER' }>): Transition {
  if (s.suspended || e.id !== s.currentId) return same(s);
  const seen: MachineState = e.text.trim() && !s.answerSeen ? { ...s, answerSeen: true } : s;
  if (s.parked === 'speaking') return { state: seen, effects: [{ type: 'speaker.push', id: e.id, text: e.text, done: e.done }] };
  if (s.parked) return same(seen);
  if (s.status === 'speaking' || (s.status === 'thinking' && s.answerStarted)) {
    return { state: seen, effects: [{ type: 'speaker.push', id: e.id, text: e.text, done: e.done }] };
  }
  if (s.status !== 'thinking') return same(seen);
  if (!s.canSpeak) {
    if (!e.done) return same(seen);
    const notice: VoiceNoticeKind | null = s.ttsOff ? null : s.uzOnlyShown ? null : 'uz_only';
    const base: MachineState = { ...toRest(seen), uzOnlyShown: true, textOnly: true };
    return same(notice ? withNotice(base, notice) : base);
  }
  if (e.text.trim() && isSpeakable(e.text, 'uz')) {
    return {
      state: { ...seen, answerStarted: true },
      effects: [
        { type: 'speaker.speak', id: e.id },
        { type: 'speaker.push', id: e.id, text: e.text, done: e.done },
      ],
    };
  }
  if (!e.done) return same(seen);
  // Ruscha javob yoki faqat taklif kartasi - o'qib bo'lmaydi, ekranda turibdi.
  return { state: textNotice(toRest(seen), e.text.trim() ? 'not_uzbek' : 'see_screen'), effects: [{ type: 'speaker.stopHold' }] };
}

function onSpeaker(s: MachineState, e: SpeakerEvent): Transition {
  switch (e.type) {
    case 'hold_start':
      return s.status === 'thinking' ? same({ ...s, holdText: e.text }) : same(s);
    case 'hold_end':
      return s.holdText ? same({ ...s, holdText: null }) : same(s);
    case 'speech_start':
      if (s.status !== 'thinking' || e.key !== s.currentId) return same(s);
      return same({ ...s, status: 'speaking', speakingId: e.key, holdText: null, hearing: false, answersSpoken: s.answersSpoken + 1 });
    case 'chunk':
      return same(s);
    case 'speech_end': {
      if (s.parked === 'speaking' && e.key === s.speakingId) {
        // Pauzadagi javob baribir tugadi (qolgan bo'laklar sintez qilinmadi) - davom etadigan
        // narsa yo'q; odamning gapi esa oddiy (bo'lib gapirish) gap bo'lib davom etadi.
        const base: MachineState = { ...s, parked: null, currentId: null, speakingId: null, answerStarted: false };
        return same(e.shortened ? textNotice(base, 'shortened') : base);
      }
      const mine = (s.status === 'speaking' && e.key === s.speakingId) || (s.status === 'thinking' && s.answerStarted && e.key === s.currentId);
      if (!mine) return same(s);
      let next = toRest(s);
      if (e.shortened) next = textNotice(next, 'shortened');
      else if (e.played === 0 && !s.notice) next = textNotice(next, 'see_screen');
      return { state: next, effects: [{ type: 'vad.guard' }] };
    }
    case 'error':
      if (e.code === 'off') return same(textNotice({ ...s, ttsOff: true, canSpeak: false }, 'tts_off'));
      return same(textNotice(s, 'tts_failed'));
    default:
      return same(s);
  }
}

export function reduce(s: MachineState, e: MachineEvent): Transition {
  if (s.ended) return same(s);
  switch (e.type) {
    case 'START':
      if (s.status !== 'idle') return same(s);
      if (e.meetingActive) return same({ ...s, status: 'error', error: 'mic_busy' });
      // O'qib berish (Tinglash) to'xtaydi - aks holda mikrofon uni savol deb yozardi.
      // Ekranni yoqiq ushlash holatdan kelib chiqadi (session `syncKeepAwake`).
      return { state: s, effects: [{ type: 'perm.request' }, { type: 'readAloud.stop' }] };

    case 'RETRY': {
      if (s.status !== 'error') return same(s);
      const base: MachineState = {
        ...s,
        status: 'idle',
        error: null,
        notice: null,
        hearing: false,
        micMuted: false,
        prefix: null,
        continuation: false,
        sttQueued: 0,
        sttFailures: 0,
        holdText: null,
        speakingId: null,
        currentId: null,
        answerStarted: false,
        parked: null,
        bargeUtterance: false,
      };
      return reduce(base, { type: 'START', meetingActive: e.meetingActive });
    }

    case 'PERMISSION':
      if (s.status !== 'idle') return same(s);
      if (!e.granted) return same({ ...s, status: 'error', error: 'mic_denied' });
      return { state: s, effects: [{ type: 'audio.enter', earpiece: s.earpiece }, { type: 'mic.start' }] };

    case 'MIC_READY':
      return s.status === 'idle' ? same({ ...s, status: rest(s) }) : same(s);

    case 'MIC_FAILED':
      if (s.status === 'error') return same(s);
      return fail(s, 'mic_failed');

    case 'VAD':
      return onVad(s, e.event);

    case 'STT_OK':
      if (s.status !== 'transcribing' || s.suspended) return same(s);
      return onSttText(s, e.text, e.lowConfidence);

    case 'STT_ECHO':
      if (s.status !== 'transcribing' || s.suspended) return same(s);
      // Barno o'z gapini eshitdi: savol emas. Aks-sado hisobiga (chegara ko'tariladi).
      return onSttText({ ...s, bargeUtterance: true }, null, false);

    case 'STT_STOP': {
      if (s.status !== 'transcribing' || s.suspended) return same(s);
      if (!s.parked) return onSttText(s, null, false);
      // "To'xta" / "bas": kutish bekor yoki ovoz to'xtaydi - savol sifatida yuborilmaydi.
      const effects: Effect[] = s.parked === 'thinking' ? [{ type: 'chat.stop' }] : [{ type: 'speaker.stop' }];
      const next: MachineState = { ...toRest(s), bargeUtterance: false, sttFailures: 0, prefix: null, continuation: false };
      return { state: next, effects: [...effects, { type: 'vad.guard' }] };
    }

    case 'STT_EMPTY':
      if (s.status !== 'transcribing' || s.suspended) return same(s);
      return onSttText(s, null, false);

    case 'STT_FAILED':
      if (s.status !== 'transcribing' || s.suspended) return same(s);
      return onSttFailure(s, e.network);

    case 'STT_TIMEOUT':
      if (s.status !== 'transcribing' || s.suspended) return same(s);
      return onSttFailure(s, false);

    case 'SENT':
      if (s.status !== 'thinking' || s.currentId) return same(s);
      return same({ ...s, currentId: e.id, turnIds: [...s.turnIds, e.id], sttFailures: 0, answerStarted: false, answerSeen: false });

    case 'SEND_BUSY':
      if (s.status !== 'thinking' || s.currentId) return same(s);
      // Oldingi javob hali ketyapti - matn yo'qolmaydi, chat bo'shashi bilan o'zi ketadi.
      return same(withNotice({ ...s, status: rest(s), pendingText: e.text, pendingAuto: true }, 'chat_busy'));

    case 'HOLD':
      if (s.status !== 'thinking' || e.id !== s.currentId || !s.canSpeak || s.suspended || s.answerStarted || !e.cue.clip) return same(s);
      return { state: s, effects: [{ type: 'speaker.hold', id: e.id, cue: e.cue }] };

    case 'ANSWER':
      return onAnswer(s, e);

    case 'ANSWER_FAILED':
      if (e.id !== s.currentId) return same(s);
      if (s.parked) {
        // Kutilayotgan so'rov o'zi yiqildi - odamning gapi oddiy gap bo'lib davom etadi.
        return { state: { ...s, parked: null, currentId: null, speakingId: null, answerStarted: false }, effects: [{ type: 'speaker.stop' }] };
      }
      if (s.status !== 'thinking' && s.status !== 'speaking') return same(s);
      return { state: toRest(s), effects: [{ type: 'speaker.stop' }] };

    case 'SPEAKER':
      return onSpeaker(s, e.event);

    case 'TAP_INTERRUPT':
      if (s.status === 'thinking' && s.holdText) return { state: s, effects: [{ type: 'speaker.stopHold' }] };
      if (s.status === 'speaking') return { state: toRest(s), effects: [{ type: 'speaker.stop' }, { type: 'vad.guard' }] };
      return same(s);

    case 'MUTE': {
      if (s.micMuted || s.status === 'idle' || s.status === 'error') return same(s);
      const effects: Effect[] = s.suspended ? [] : [{ type: 'mic.release' }];
      if (s.status === 'listening' && s.parked) {
        // Endi eshitib bo'lmaydi - bo'lib gapirish tekshiruvi tugadi, savol/javobga qaytamiz.
        const back = unpark({ ...s, micMuted: true });
        return { state: back.state, effects: [...effects, ...back.effects] };
      }
      if (s.status === 'listening') {
        const pending = s.prefix ? { pendingText: s.prefix, pendingAuto: false, prefix: null } : {};
        return { state: { ...s, ...pending, status: 'muted', micMuted: true, hearing: false }, effects };
      }
      return { state: { ...s, micMuted: true, hearing: false, continuation: false }, effects };
    }

    case 'UNMUTE': {
      if (!s.micMuted || s.status === 'idle' || s.status === 'error') return same(s);
      // Yig'ilish yozilayotgan bo'lsa ikkinchi yozuvchi ochilmaydi (uning xizmati buziladi).
      if (e.meetingActive) return fail({ ...s, micMuted: false }, 'mic_busy');
      const effects: Effect[] = s.suspended ? [] : [{ type: 'mic.start' }];
      if (s.status === 'muted') return { state: { ...s, status: 'listening', micMuted: false }, effects };
      return { state: { ...s, micMuted: false }, effects };
    }

    case 'IDLE_TIMEOUT':
      if (s.status !== 'listening' || s.hearing || s.suspended || s.micMuted || s.parked) return same(s);
      return { state: withNotice({ ...s, status: 'muted', micMuted: true }, 'auto_muted'), effects: [{ type: 'mic.release' }] };

    case 'SUSPEND': {
      if (s.suspended || s.status === 'idle' || s.status === 'error') return same(s);
      // Bo'lib gapirish tekshirilayotgan edi - gap yo'qoladi (STT bekor), savol/javobga qaytamiz.
      const status: VoiceStatus = s.parked ?? s.status;
      return {
        state: { ...s, status, suspended: true, hearing: false, continuation: false, sttQueued: 0, prefix: null, holdText: null, parked: null, bargeUtterance: false },
        effects: [{ type: 'mic.release' }, { type: 'speaker.stop', keep: true }, { type: 'stt.abort' }],
      };
    }

    case 'RESUME': {
      if (!s.suspended) return same(s);
      const base: MachineState = { ...s, suspended: false };
      // Yo'qligimizda yig'ilish yozuvi boshlangan (plitka / launcher) - mikrofonga tegmaymiz.
      if (e.meetingActive) return fail(base, 'mic_busy');
      // Audio rejim qayta qo'yiladi: qo'ng'iroq yoki boshqa ilova uni o'zgartirgan bo'lishi
      // mumkin (quloq tanlangan-u, ovoz karnaydan chiqib aks-sado chegarasini buzardi).
      const effects: Effect[] = [{ type: 'audio.enter', earpiece: s.earpiece }, ...(s.micMuted ? [] : [{ type: 'mic.start' } as Effect])];
      if (s.status === 'listening' || s.status === 'muted') return { state: { ...base, status: rest(base) }, effects };
      if ((e.pending || e.resumable) && s.currentId && (s.status === 'thinking' || s.status === 'speaking')) {
        // Javob hali kelmoqda yoki to'liq aytilmagan - to'xtagan joyidan davom etamiz.
        return { state: { ...base, status: 'thinking', speakingId: null, answerStarted: false }, effects };
      }
      // Javob allaqachon aytib bo'lingan yoki eskirgan - u ekranda.
      return { state: toRest(base), effects };
    }

    case 'SEND_PENDING':
      if (!s.pendingText || s.suspended || s.parked || (s.status !== 'listening' && s.status !== 'muted')) return same(s);
      if (e.auto && !s.pendingAuto) return same(s);
      if (e.busy) return same(e.auto ? s : withNotice({ ...s, pendingAuto: true }, 'chat_busy'));
      return send(s, s.pendingText);

    case 'SET_EARPIECE':
      if (s.earpiece === e.on) return same(s);
      return { state: { ...s, earpiece: e.on }, effects: [{ type: 'audio.earpiece', on: e.on }] };

    case 'NOTICE_EXPIRED':
      return e.seq === s.noticeSeq && s.notice ? same({ ...s, notice: null }) : same(s);

    case 'DISMISS_NOTICE':
      return s.notice ? same({ ...s, notice: null }) : same(s);

    case 'END':
      // Chat so'rovi BEKOR QILINMAYDI: javob chatda matn bo'lib qoladi.
      return {
        state: { ...s, ended: true, status: 'idle', hearing: false, holdText: null, speakingId: null, continuation: false, sttQueued: 0, parked: null },
        effects: [{ type: 'mic.release' }, { type: 'speaker.stop' }, { type: 'stt.abort' }, { type: 'audio.restore' }, { type: 'files.clear' }],
      };

    default:
      return same(s);
  }
}
