/**
 * Jonli ovozli suhbat ("Jonli") va javobni o'qib berish ("Tinglash") - UI ko'radigan tiplar.
 *
 * NIMA UCHUN alohida fayl: ekran (UI) faqat shu tiplar va `@/features/voice` barrel'i
 * orqali dvigatelga tegadi - dvigatel ichki portlari (mikrofon, pleer, fayllar) UI'ga
 * ko'rinmaydi va testlarda soxtasi bilan almashtiriladi.
 */
import type { VoiceId } from '@/api/voice';

export type { VoiceId };

export type VoiceStatus = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'muted' | 'error';
export type VoiceErrorKind = 'mic_denied' | 'mic_busy' | 'mic_failed' | 'offline' | 'stt_failed';
export type VoiceNoticeKind =
  | 'no_speech'
  | 'unsure'
  | 'stt_retry'
  | 'chat_busy'
  | 'uz_only'
  | 'not_uzbek'
  | 'tts_failed'
  | 'tts_off'
  | 'shortened'
  | 'auto_muted'
  | 'see_screen';
/** Tuman rangi: foydalanuvchi ovozi (sovuq) yoki Barno ovozi (iliq). */
export type FogSource = 'user' | 'barno' | 'none';
export type LevelListener = (level: number, source: FogSource) => void;
export type VoiceSpeed = 'slow' | 'normal' | 'fast';

export interface VoiceSettings {
  voice: VoiceId;
  speed: VoiceSpeed;
  showText: boolean;
  earpiece: boolean;
}

/** Immutable: yangi obyekt faqat o'zgarishda (useSyncExternalStore barqaror snapshot talab qiladi). */
export interface VoiceSnapshot {
  status: VoiceStatus;
  micMuted: boolean;
  hearing: boolean;
  suspended: boolean;
  error: VoiceErrorKind | null;
  notice: VoiceNoticeKind | null;
  turnIds: readonly string[];
  pendingText: string | null;
  holdText: string | null;
  speakingId: string | null;
  canSpeak: boolean;
  earpiece: boolean;
  /**
   * Oxirgi javob ovozda to'liq aytilmadi (ru/en, o'zbekcha emas, ovoz xatosi, uzun javob) -
   * "matnsiz" rejimda ham matn ekranda ko'rsatiladi (aks holda javob hech qayerda yo'q).
   */
  textOnly: boolean;
  /** Javob matni keldi, birinchi bo'lak sintez qilinmoqda ("O'ylayapman" emas, "Tayyorlanmoqda"). */
  preparing: boolean;
  /** Shu sessiyada ovozda boshlangan javoblar (bo'lish ko'rsatmasi faqat birinchilarida). */
  answersSpoken: number;
}

export interface VoiceActions {
  toggleMute(): void;
  /** voiceSettings'ga saqlanadi + audio rejim (quloq/karnay). */
  setEarpiece(on: boolean): void;
  /** Bosish: gapirish / kutish ovozini to'xtatib tinglashga o'tadi. */
  interrupt(): void;
  /** Xatodan qayta boshlash. */
  retry(): void;
  sendPending(): void;
  dismissNotice(): void;
  /** Idempotent; chat so'rovi davom etadi (javob chatda matn bo'lib qoladi). */
  end(): Promise<void>;
}

export interface UseVoiceSession {
  snap: VoiceSnapshot;
  /** Sessiya davomida barqaror (har chizishda yangi obyekt emas). */
  actions: VoiceActions;
  /** ~30 Hz, React holatidan TASHQARIDA (tuman animatsiyasi qayta chizilmasin). */
  subscribeLevel(listener: LevelListener): () => void;
}

export interface ReadAloudState {
  /** Exchange id yoki '__preview__' (sozlamalardagi namuna). */
  key: string | null;
  phase: 'idle' | 'loading' | 'playing' | 'paused';
  /** 1 dan boshlab - hozir yangrayotgan bo'lak (yuklanayotganda 0). */
  index: number;
  /** Navbat tugagach ma'lum bo'ladi. */
  total: number | null;
}

export interface ReadAloudControls {
  /** Shu kalit o'qilayotgan bo'lsa - to'xtatadi. */
  toggle(key: string, markdown: string, turnId: string | null): void;
  pause(): void;
  resume(): void;
  stop(): void;
  /** Sozlamalar: tanlangan ovoz va tezlikdagi namuna. */
  preview(): void;
}
