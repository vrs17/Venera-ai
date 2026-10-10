/**
 * Dvigatelning tashqi dunyo bilan chegaralari (portlar). Ilovada `native.ts` dagi
 * adapterlar (expo-audio, expo-file-system), testlarda soxtalari beriladi - mantiq
 * hech qachon native modulni to'g'ridan-to'g'ri chaqirmaydi.
 */
import type { TranscriptResponse } from '@/api/chat';
import type { Exchange } from '@/features/chat/chatStore';
import type { UiLang } from '@/i18n';

/**
 * Bitta o'lchov: segment boshidan o'tgan vaqt va dBFS cho'qqi. DIQQAT: Android'da `tMs`
 * - `record()` dan beri DEVOR SOATI; fayl esa mikrofon ochilish kechikishidan (~0.2-0.5 s)
 * keyin boshlanadi. Kesishda farq segment oxirida o'lchab tuzatiladi (`session.micCut`).
 */
export interface MicFrame {
  tMs: number;
  db: number;
}

export interface MicPort {
  /** Yangi segment: tayyorlash + yozish (yarim tayyor qolgan yozuvchini avval bo'shatadi). */
  start(): Promise<void>;
  /** Yozilmayotgan bo'lsa null. */
  poll(): MicFrame | null;
  /** Segment fayli (uri). */
  stop(): Promise<string | null>;
  readonly recording: boolean;
}

export interface ClipPlayer {
  play(uri: string): void;
  pause(): void;
  resume(): void;
  stop(): void;
  positionMs(): number;
  /** Faqat tabiiy tugashda (stop() da emas). */
  onEnd(cb: () => void): () => void;
  dispose(): void;
}

/** `voice` - jonli suhbat, `voice-read` - "Tinglash" (alohida: biri tozalanganda ikkinchisiga tegmasin). */
export type VoiceDir = 'voice' | 'voice-hold' | 'voice-read';

export interface AudioFiles {
  /** file:// uri qaytaradi (papkalarni o'zi yaratadi; `name` ichida `a/b.wav` bo'lishi mumkin). */
  write(dir: VoiceDir, name: string, bytes: Uint8Array): string;
  read(uri: string): Promise<Uint8Array>;
  find(dir: 'voice-hold', name: string): string | null;
  remove(uri: string | null | undefined): void;
  clear(dir: 'voice' | 'voice-read'): void;
  /**
   * Ilova yiqilib qolgan yozuv segmentlari (expo-audio `cache/Audio/recording-*.aac`) -
   * shundan eski bo'lsa o'chiriladi. Ixtiyoriy (soxtalarda yo'q).
   */
  sweepRecordings?(olderThanMs: number): void;
}

export interface AudioModePort {
  enter(o: { earpiece: boolean }): Promise<void>;
  setEarpiece(on: boolean): Promise<void>;
  /** Yig'ilish yozilayotgan bo'lsa adapter o'tkazib yuboradi. */
  playbackOnly(): Promise<void>;
  restore(): Promise<void>;
}

export interface ChatPort {
  /** Ovozli savol - xuddi shu suhbat (chatId) ichida; band bo'lsa null. */
  sendVoice(text: string): string | null;
  stop(): void;
  exchange(id: string): Exchange | undefined;
  busy(): boolean;
  subscribe(listener: () => void): () => void;
}

export interface SttPort {
  transcribe(uri: string, lang: UiLang, signal: AbortSignal): Promise<TranscriptResponse>;
}

export interface Clock {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(h: unknown): void;
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(h: unknown): void;
}

export const realClock: Clock = {
  now: () => Date.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
  setInterval: (fn, ms) => setInterval(fn, ms),
  clearInterval: (h) => clearInterval(h as ReturnType<typeof setInterval>),
};
