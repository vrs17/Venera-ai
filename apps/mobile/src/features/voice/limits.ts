/**
 * Ovozli suhbat chegaralari va vaqtlari - bitta joyda (spec 4.3, 5.3, 6).
 * Qiymatlar o'lchovga asoslangan; o'zgartirsangiz testlar (voiceVad, voiceMachine) qayta
 * ko'rib chiqilsin.
 */

/** 45 s gap boshlanmasa mikrofon o'zi o'chadi (maxfiylik va batareya). */
export const LISTEN_IDLE_MS = 45_000;
/** Bitta gap shundan uzoq bo'lsa majburan yakunlanadi. */
export const MAX_UTTERANCE_MS = 60_000;
/** `transcribe` uchun klient chegarasi - tugasa bekor qilinib qayta tinglanadi. */
export const STT_TIMEOUT_MS = 45_000;
/** Ketma-ket shuncha STT xatosi - xato holati. */
export const STT_MAX_FAILURES = 3;
/** Vaqtinchalik eslatma ko'rinish vaqti. */
export const NOTICE_MS = 4_000;
/** 503 (TTS band) bo'lsa shu kutishlardan keyin qayta so'raladi. */
export const TTS_RETRY_MS: readonly number[] = [400, 1200];
/** Gap boshlanmagan segment shuncha vaqtdan keyin almashtiriladi (fayl kichik qolsin). */
export const SEGMENT_ROTATE_MS = 30_000;
/**
 * Tinglashda segment faqat shuncha jimlikdan keyin almashtiriladi. NIMA UCHUN 0.5 s emas:
 * Barno gapirib bo'lgach odam odatda 0.5-2 s ichida javob beradi - almashtirishning
 * 100-300 ms "ko'r" oralig'i aynan birinchi bo'g'inni kesib qo'yardi.
 */
export const ROTATE_QUIET_LISTEN_MS = 2_500;
/** Javob kutilayotganda (klip yo'q, hech kim gapirmayapti) - odam kutyapti, qisqa jimlik yetadi. */
export const ROTATE_QUIET_THINK_MS = 500;
/** Yo'qligimizda tugagan javob qaytganda shuncha vaqt ichida bo'lsa o'qiladi (eskisi - faqat ekranda). */
export const RESUME_FRESH_MS = 120_000;
/** Yiqilib qolgan yozuv segmentlari shundan eski bo'lsa o'chiriladi. */
export const STALE_RECORDING_MS = 60 * 60 * 1000;
/** Mikrofon ochilish kechikishi (devor soati - fayl vaqti) shundan oshmaydi deb olinadi. */
export const MAX_CAPTURE_OFFSET_MS = 800;

/** Mikrofon o'lchovi davri. */
export const FRAME_MS = 60;
/** Gap boshidan oldin saqlanadigan qism - birinchi bo'g'in kesilmasin. */
export const PREROLL_MS = 300;
/** Gap oxiridan keyin qo'shiladigan qism (so'nggi undosh yo'qolmasin). */
export const POSTROLL_MS = 200;
/** Barno gapirib bo'lgach shu vaqt ichida xona aks-sadosi gap deb olinmasin. */
export const POST_SPEECH_GUARD_MS = 300;
/** Ekrandagi daraja (tuman) yangilanish davri - ~30 Hz. */
export const LEVEL_TICK_MS = 33;
