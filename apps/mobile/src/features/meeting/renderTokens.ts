/**
 * `[S1]` tokenlarini ismga almashtirish (spec 6.2 "Rendering rules").
 *
 * Model matnda odamlarni FAQAT `[S#]` bilan ataydi; ism foydalanuvchi
 * tasdiqlagan `speaker.name` dan, bo'lmasa "1-ishtirokchi" / "Участник 1" /
 * "Speaker 1". Birlashtirilgan spiker (`mergedInto`) qabul qilgan spikerga
 * aylanadi - shuning uchun nom o'zgarsa xulosani qayta yaratish shart emas.
 */
import type { Lang, Speaker } from '@/api/types';

const TOKEN_RE = /\[(S\d{1,2})\]/g;

export function speakerNumber(id: string | null | undefined): number | null {
  const m = /^S(\d{1,2})$/.exec(id ?? '');
  return m ? Number(m[1]) : null;
}

/** mergedInto zanjiri bo'yicha oxirgi spiker (aylana bo'lsa ham to'xtaydi). */
export function resolveSpeakerId(id: string, speakers: Speaker[]): string {
  let cur = id;
  for (let hop = 0; hop < 8; hop++) {
    const sp = speakers.find((s) => s.id === cur);
    if (!sp?.mergedInto || sp.mergedInto === cur) return cur;
    cur = sp.mergedInto;
  }
  return cur;
}

export function fallbackSpeakerLabel(n: number, lang: Lang): string {
  if (lang === 'ru') return `Участник ${n}`;
  if (lang === 'en') return `Speaker ${n}`;
  return `${n}-ishtirokchi`;
}

export function unknownSpeakerLabel(lang: Lang): string {
  if (lang === 'ru') return 'Неизвестно';
  if (lang === 'en') return 'Unknown';
  return "Noma'lum";
}

/** Ovozi tanilgan, ismi yo'q spiker (mehmon yoki namuna yozmagan xodim) - doimiy raqami bilan (server bilan bir xil). */
export function personLabel(personId: number, lang: Lang): string {
  if (lang === 'ru') return `Неизвестный #${personId}`;
  if (lang === 'en') return `Unknown #${personId}`;
  return `Noma'lum #${personId}`;
}

export function speakerLabel(id: string | null | undefined, speakers: Speaker[], lang: Lang): string {
  if (!id) return unknownSpeakerLabel(lang);
  const resolved = resolveSpeakerId(id, speakers);
  const sp = speakers.find((s) => s.id === resolved);
  if (sp?.name) return sp.name;
  if (sp?.personId) return personLabel(sp.personId, lang);
  const n = speakerNumber(resolved);
  return n != null ? fallbackSpeakerLabel(n, lang) : resolved;
}

export function renderTokens(text: string | null | undefined, speakers: Speaker[], lang: Lang): string {
  if (!text) return '';
  return text.replace(TOKEN_RE, (_m, id: string) => speakerLabel(id, speakers, lang));
}

/** Ko'rinadigan (birlashtirilmagan) spikerlar - chip qatori uchun. */
export function visibleSpeakers(speakers: Speaker[]): Speaker[] {
  return speakers.filter((s) => !s.mergedInto);
}
