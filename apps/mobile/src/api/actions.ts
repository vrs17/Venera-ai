/**
 * Yordamchi TAKLIF qilgan yozuv amallari (`/api/v1/actions`) - chatdagi (web
 * `apps/web/src/api/actions.api.ts`) AYNI yo'l. Faqat HTTP: holatni karta saqlaydi.
 *
 * Ilova FAQAT taklif kalitini yuboradi. Kim tasdiqlayotgani va CRM tokeni serverda
 * qo'shiladi - taklif qilingan odamning o'zi; boshqa odam bu taklifni tasdiqlay olmaydi.
 */
import { ACTION_TIMEOUT_MS, ApiClient, ApiError } from './client';
import { API_PREFIX } from './meetings';
import type { ActionResult } from './types';

const A = `${API_PREFIX}/actions`;
const enc = encodeURIComponent;

export function createActionsApi(client: ApiClient) {
  return {
    confirm: (token: string) =>
      client.request<ActionResult>(`${A}/${enc(token)}/confirm`, { method: 'POST', timeoutMs: ACTION_TIMEOUT_MS }),
    cancel: (token: string) =>
      client.request<ActionResult>(`${A}/${enc(token)}/cancel`, { method: 'POST', timeoutMs: ACTION_TIMEOUT_MS }),
    get: (token: string) => client.request<ActionResult>(`${A}/${enc(token)}`),
  };
}

export type ActionsApi = ReturnType<typeof createActionsApi>;

/**
 * Taklifni endi tasdiqlab bo'lmaydi: server 404 (kalitni tanimadi) yoki 410 (`expired`,
 * 2026-10 dan; taklif 15 daqiqa yashaydi) qaytaradi. Karta buni xizmat xatosi emas,
 * "Muddati tugagan" deb ko'rsatadi (web `isExpiredError` bilan bir xil qoida).
 */
export function isExpiredError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 410);
}
