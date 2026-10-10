/**
 * Yuborish natijasi -> foydalanuvchiga qisqa xabar. Sabab va (bo'lsa) keyingi qadam
 * aytiladi: "telefonda joy kam", "format mos emas" - "xatolik yuz berdi" emas.
 */
import type { CallImportErrorCode } from '@/features/entry/nativeEntry';
import type { TFn } from '@/i18n';
import { showToast } from '@/ui/errors';

import type { SendOutcome } from './send';

/** Nusxa xatosi -> odamga tushunarli sabab (keyingi qadam bilan). */
export function sendErrorReason(t: TFn, code: CallImportErrorCode | 'queue'): string {
  if (code === 'ERR_NO_SPACE') return t('calls.err.space');
  if (code === 'ERR_READ' || code === 'ERR_EMPTY') return t('calls.err.read');
  if (code === 'ERR_PERMISSION' || code === 'ERR_BAD_URI') return t('calls.err.permission');
  return t('calls.err.generic');
}

/** Server chegarasi MB'da ("150") - "150 MB dan katta" deyish uchun (foydalanuvchi nima mumkinligini bilsin). */
export function limitMb(bytes: number): string {
  return String(Math.max(1, Math.round(bytes / (1024 * 1024))));
}

/**
 * Yuborish natijasi -> qisqa toast (navbatga qo'shildi yoki nega yo'q). Sabab gap ichida
 * kichik harf bilan ("Yuborib bo'lmadi: fayl 150 MB dan katta") - pill yorlig'i qayta ishlatilmaydi.
 */
export function toastSendOutcome(t: TFn, out: SendOutcome): void {
  if (out.kind === 'queued' || out.kind === 'already') showToast(t('calls.queued'));
  else if (out.kind === 'too_large') showToast(t('calls.sendFailed', { reason: t('calls.err.tooLarge', { mb: limitMb(out.maxBytes) }) }));
  else if (out.kind === 'unsupported') showToast(t('calls.sendFailed', { reason: t('calls.err.format') }));
  else if (out.kind === 'missing') showToast(t('calls.sendFailed', { reason: t('calls.err.read') }));
  else if (out.kind === 'not_ready') showToast(t('calls.sendFailed', { reason: t('calls.err.notReady') }));
  else showToast(t('calls.sendFailed', { reason: sendErrorReason(t, out.code) }));
}
