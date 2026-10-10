/**
 * UI matnlari: uz (asosiy, lotin), ru, en. Default - o'zbekcha.
 *
 * Xulosa MAZMUNI tarjima qilinmaydi - u server tomonidan tanlangan tilda
 * keladi; bu yerda faqat interfeys yozuvlari.
 */
import { en } from './en';
import { ru } from './ru';
import { uz, type TKey } from './uz';

export type UiLang = 'uz' | 'ru' | 'en';
export type { TKey };
export type TParams = Record<string, string | number>;
export type TFn = (key: TKey, params?: TParams) => string;

export const DICTS: Record<UiLang, Record<TKey, string>> = { uz, ru, en };
export const UI_LANGS: UiLang[] = ['uz', 'ru', 'en'];

export function interpolate(template: string, params?: TParams): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k]) : m));
}

export function translate(lang: UiLang, key: TKey, params?: TParams): string {
  const dict = DICTS[lang] ?? uz;
  return interpolate(dict[key] ?? uz[key] ?? key, params);
}

export function makeT(lang: UiLang): TFn {
  return (key, params) => translate(lang, key, params);
}

export function isUiLang(v: unknown): v is UiLang {
  return v === 'uz' || v === 'ru' || v === 'en';
}
