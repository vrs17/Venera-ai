/**
 * Xulosani kim yozgani (`summary.generatedBy`) - xulosa ostidagi jim yozuv uchun ("Tayyorladi: Barno").
 *
 * Odamga MODEL NOMI KO'RSATILMAYDI (ega, 2026-11-20): javob beruvchi ham, xulosa yozuvchi ham - doim
 * Barno. Ostidagi dvigatel almashadi (bugun Claude, keyin o'z serverimizdagi lokal LLM), foydalanuvchi
 * uchun esa bu bitta mahsulot. Qaysi model ishlagani serverda (`generatedBy`) saqlanib qoladi.
 * Server bermasa (eski xulosa, tayyor emas) - hech narsa ko'rsatilmaydi.
 */
import type { GeneratedBy } from '@/api/types';

export const ASSISTANT_NAME = 'Barno';

export function engineLabel(g: GeneratedBy | null | undefined): string | null {
  return g ? ASSISTANT_NAME : null;
}
