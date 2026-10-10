/**
 * Ovozli ekran holat yozuvi: sessiya holatidan BITTA qisqa qator (spec §2.3 jadvali,
 * birinchi mos kelgani yutadi). Ekran pastidagi yozuv va "matnsiz" rejimdagi katta sarlavha
 * shu bitta funksiyadan olinadi - ikkalasi hech qachon bir-biriga zid gapirmasin.
 */
import type { TFn, TKey } from '@/i18n';

import type { VoiceErrorKind, VoiceNoticeKind, VoiceSnapshot, VoiceSpeed } from '../types';

export const ERROR_KEY: Record<VoiceErrorKind, TKey> = {
  mic_denied: 'dict.denied',
  mic_busy: 'dict.meetingBusy',
  mic_failed: 'nav.voice.micFailed',
  offline: 'nav.voice.offline',
  stt_failed: 'dict.failed',
};

export const NOTICE_KEY: Record<VoiceNoticeKind, TKey> = {
  no_speech: 'nav.voice.noSpeech',
  unsure: 'nav.voice.unsure',
  stt_retry: 'nav.voice.noSpeech',
  chat_busy: 'nav.voice.chatBusy',
  uz_only: 'nav.voice.uzOnly',
  not_uzbek: 'nav.voice.notUzbek',
  tts_failed: 'nav.voice.ttsFailed',
  tts_off: 'nav.voice.ttsOff',
  shortened: 'nav.voice.shortened',
  auto_muted: 'nav.voice.autoMuted',
  see_screen: 'nav.voice.seeScreen',
};

export const SPEED_KEY: Record<VoiceSpeed, TKey> = {
  slow: 'nav.voice.slow',
  normal: 'nav.voice.normal',
  fast: 'nav.voice.fast',
};

export type StatusLine = { text: string; kind: 'error' | 'notice' | 'state' };

/**
 * "Gapiring yoki bosing" ko'rsatmasi faqat sessiyadagi birinchi shuncha javobda. NIMA UCHUN:
 * har javobda takrorlanadigan yo'riqnoma (matnsiz rejimda 28 px sarlavha!) shovqin -
 * odam ikki marta ko'rgach biladi; Claude bu yerda hech narsa ko'rsatmaydi.
 */
export const HINT_ANSWERS = 2;

/** Holatning o'zi (xato va eslatmasiz) - "matnsiz" rejim sarlavhasi ham shu. */
export function stateText(snap: VoiceSnapshot, t: TFn): string {
  if (snap.suspended) return t('nav.voice.paused');
  switch (snap.status) {
    case 'idle':
      return t('nav.voice.connecting');
    case 'listening':
      return t(snap.hearing ? 'nav.voice.hearing' : 'nav.voice.listening');
    case 'transcribing':
      return t('nav.voice.transcribing');
    case 'thinking':
      // Javob matni keldi, ovoz tayyorlanmoqda - "o'ylayapman" endi to'g'ri emas.
      return snap.holdText ?? t(snap.preparing ? 'nav.voice.preparing' : 'nav.voice.thinking');
    case 'speaking':
      // Mikrofon o'chiq - gapirib to'xtatib bo'lmaydi, faqat bosib.
      if (snap.micMuted) return t('nav.voice.tapToStop');
      return snap.answersSpoken <= HINT_ANSWERS ? t('nav.voice.interruptHint') : t('nav.voice.speaking');
    case 'muted':
      return t('nav.voice.muted');
    case 'error':
      return snap.error ? t(ERROR_KEY[snap.error]) : t('dict.failed');
    default:
      return '';
  }
}

export function statusLine(snap: VoiceSnapshot, t: TFn): StatusLine {
  if (snap.status === 'error' && snap.error) return { text: t(ERROR_KEY[snap.error]), kind: 'error' };
  if (snap.notice) return { text: t(NOTICE_KEY[snap.notice]), kind: 'notice' };
  return { text: stateText(snap, t), kind: 'state' };
}
