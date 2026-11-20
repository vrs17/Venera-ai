/**
 * Yozuv chati (`ChatView`) uchun sof mantiq - ekransiz test qilinadi: server javobini keshdagi
 * tarixga qo'shish, xabarning idempotentlik kaliti (`clientId`) va xabar yetib borganmi, javobi
 * noma'lum xato, xato matni, chat 404 ining ikki ma'nosi, modelning ko'rinadigan nomi va yozish
 * maydoni ostidagi bo'shliq.
 */
import * as Crypto from 'expo-crypto';

import { ApiError } from '@/api/client';
import type { ChatHistory, ChatTurn } from '@/api/types';
import type { TFn } from '@/i18n';
import { UUID_RE, uuidV4 } from '@/lib/uuid';
import { errorText } from '@/ui/errors';


/** Xabar uzunligi chegarasi (server `ChatRequest.message`: 1-1000 belgi). */
export const CHAT_MAX_CHARS = 1000;
/** Hisoblagich shundan boshlab ko'rinadi - chegaraga yaqinlashganini odam oldindan bilsin. */
export const CHAT_COUNTER_FROM = 900;
/**
 * Javobi noma'lum xatodan (`chatOutcomeUnknown`) keyin tarix shuncha vaqtdan so'ng YANA bir marta
 * o'qiladi: proksi kutishdan to'xtagan paytda server odatda javobni bir necha soniyada tugatib saqlaydi.
 */
export const CHAT_RECHECK_MS = 8_000;

/**
 * Xabarning idempotentlik kaliti (server `ChatRequest.clientId`: 8-64 belgi, `[A-Za-z0-9_-]`) - UUID v4,
 * 36 belgi (`@/lib/uuid`, yozuvning `clientId`si bilan bir xil yo'l). Har yangi xabar yangi kalit oladi;
 * "Qayta yuborish" O'SHA kalitni qayta yuboradi - server shu kalitli savol-javob bor bo'lsa uni qaytaradi
 * (yoki yo'ldagi urinishni kutadi), ikkinchisini yaratmaydi.
 *
 * Tasodifiy baytlar odatda expo-crypto'dan. Native modul ishlamasa (xato yoki yaroqsiz natija) - zaxira
 * `Math.random` baytlari: kalit sir emas, faqat shu yozuv va shu odam ichida takrorlanmasligi kerak.
 */
export function newChatClientId(randomBytes: (n: number) => Uint8Array = (n) => Crypto.getRandomBytes(n)): string {
  try {
    const id = uuidV4(randomBytes);
    if (UUID_RE.test(id)) return id;
  } catch {
    // native tasodif yo'q - pastdagi zaxira
  }
  return uuidV4((n) => Uint8Array.from({ length: n }, () => Math.floor(Math.random() * 256)));
}

/** Server qaytargan savol-javob tarix oxiriga (shu id allaqachon bo'lsa - o'z joyida yangilanadi, takrorlanmaydi). */
export function withTurn(old: ChatHistory | undefined, turn: ChatTurn): ChatHistory {
  if (!old) return { items: [turn], model: turn.model ?? '' };
  const at = old.items.findIndex((x) => x.id === turn.id);
  if (at < 0) return { ...old, items: [...old.items, turn] };
  const items = old.items.slice();
  items[at] = turn;
  return { ...old, items };
}

/**
 * Javob kutilayotgan yoki xato bilan tugagan xabar aslida yetib borganmi: tarixda shu `clientId` li
 * savol-javob bor. Tarmoq uzilsa, proksi kutishdan to'xtasa (HTML 504) yoki telefon `AI_TIMEOUT_MS`
 * dan keyin kutmay qo'ysa, server javobni baribir yozib saqlaydi - tarix qayta o'qilganda u keladi.
 * Savol MATNI solishtirilmaydi: shu savol oldinroq ham berilgan bo'lishi mumkin (o'sha qatorning
 * kaliti boshqa), vaqt (`createdAt`) ham - telefon va server soati bir xil emas. Kalitsiz xabar
 * (yoki kalit qaytarmaydigan server) hech qachon "yetib borgan" sanalmaydi - "Qayta yuborish" qoladi.
 */
export function wasDelivered(items: readonly ChatTurn[] | undefined, clientId: string | null | undefined): boolean {
  if (!clientId || !items?.length) return false;
  return items.some((x) => x.clientId === clientId);
}

/**
 * Xabarning taqdiri noma'lum: so'rov serverga yetganmi, javob saqlanganmi - bilib bo'lmaydi.
 *  - `status 0` - tarmoq uzildi yoki telefon kutishdan to'xtadi (`timeout`);
 *  - konvertsiz 5xx - proksi yoki nginx sahifasi (502/504...): server hali javob yozayotgan bo'lishi mumkin.
 * Bizning konvertli xatolar (503 `llm_unavailable`, 429, 409...) aniq: xabar saqlanmagan. Noma'lum
 * xatodan keyin tarix `CHAT_RECHECK_MS` dan so'ng yana o'qiladi; "Qayta yuborish" baribir xavfsiz
 * (o'sha `clientId` - takror savol-javob yaratilmaydi).
 */
export function chatOutcomeUnknown(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 0 || (err.status >= 500 && !err.body));
}

/**
 * Chat xatosi -> matn. Bizning API xatoni doim JSON konvert bilan beradi: HTML sahifali (yoki
 * bo'sh) 403 - yo'ldagi himoya (WAF) yoki proksi so'rovni to'xtatgan. Bu "ruxsat yo'q" emas -
 * xabar serverga yetib bormagan, shuning uchun umumiy "qayta yuboring".
 */
export function chatErrorText(t: TFn, err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'rate_limited') return t('err.rate_limited');
    if (err.code === 'llm_unavailable') return t('err.llm_unavailable');
    if (err.code === 'not_ready') return t('ask.notReady');
    if (err.status === 403 && !err.body) return t('mchat.failed');
  }
  return errorText(t, err);
}

/**
 * Server konvertidagi mashina kodi (`{..., code}`). Uni faqat bizning endpoint'lar beradi: yo'l
 * umuman topilmasa (eski server) konvertda `code` yo'q, nginx/WAF sahifasida konvertning o'zi yo'q.
 * `ApiError.code` bunga yaramaydi - client.ts kodsiz 404 ga ham `not_found` qo'yadi.
 */
function serverCode(err: ApiError): string | null {
  const code: unknown = err.body?.code;
  return typeof code === 'string' && code ? code : null;
}

/**
 * Tarixni o'qishda KODSIZ 404: yo'l topilmadi - serverda chat yo'llari hali yo'q (eski backend;
 * `assistantErrorKind` dagi qoida). Qayta urinish befoyda.
 */
export function chatMissingOnServer(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && !serverCode(err);
}

/**
 * Istalgan chat so'rovida (tarix YOKI xabar) `not_found` kodli 404: chat yo'li bor, yozuvning o'zi
 * yo'q - o'chirilgan yoki begona (backend begonasini ham "topilmadi" deydi). Bu "eski server" emas;
 * yozish ham, qayta urinish ham befoyda.
 */
export function chatRecordingGone(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && serverCode(err) === 'not_found';
}

/**
 * Yozish maydoni ostidagi bo'shliq. `keyboard` - klaviatura bo'shlig'i (`useKeyboardPadding`, 0 -
 * yopiq), `navInset` - navigatsiya paneli, `below` - tab maydoni ostidagi pleer balandligi.
 * Klaviatura ochilganda pleer uning ostida qoladi (ijro to'xtamaydi): maydon pleer ustida emas,
 * klaviatura ustida tursin. Yopiq bo'lsa navigatsiya panelini pleer o'zi qoplaydi; pleer yo'q
 * bo'lsa - panel chekinishi (asosiy chatdagi `kb.paddingBottom || insets.bottom` qoidasi).
 */
export function composerInset(p: { keyboard: number; navInset: number; below: number }): number {
  return Math.max(0, (p.keyboard > 0 ? p.keyboard : p.navInset) - Math.max(0, p.below));
}
