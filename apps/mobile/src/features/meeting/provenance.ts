/**
 * Xulosani qaysi model yozgani (`summary.generatedBy`) - xulosa ostidagi jim yozuv uchun.
 *
 * Foydalanuvchiga ko'rinadigan nomlar: v3 - "Barno Core" (yordamchining o'z dvigateli),
 * OpenAI - "GPT (<model>)", Ollama - "Gemma" (serverdagi gemma4:31b). Server bermasa
 * (eski xulosa, tayyor emas) - hech narsa ko'rsatilmaydi.
 */
import type { GeneratedBy } from '@/api/types';

export function engineLabel(g: GeneratedBy | null | undefined): string | null {
  if (!g) return null;
  const model = (g.model ?? '').trim();
  if (g.provider === 'v3') return 'Barno Core';
  if (g.provider === 'openai') return model ? `GPT (${model})` : 'GPT';
  // Ollama'da boshqa model qo'yilsa uni "Gemma" deb atamaymiz - o'z nomi bilan.
  if (g.provider === 'ollama') return !model || /gemma/i.test(model) ? 'Gemma' : model;
  return null;
}
