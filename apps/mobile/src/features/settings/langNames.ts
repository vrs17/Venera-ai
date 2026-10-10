/**
 * Til nomlari O'Z yozuvida (endonim): "O'zbekcha", "Русский", "English".
 *
 * NIMA UCHUN i18n emas: til tanlash ro'yxatida har til o'z yozuvida turishi kerak -
 * interfeys tili tushunilmasa ham odam "Русский"ni taniydi. `uz` lug'atida esa kirill
 * harfi bo'lishi mumkin emas (i18n testi), shuning uchun bu kod konstantasi.
 * Sozlamalar hub'idagi "Til" qatori va til sahifasi shu bitta manbadan o'qiydi.
 */
import type { UiLang } from '@/i18n';

export const LANG_ENDONYM: Record<UiLang, string> = {
  uz: "O'zbekcha",
  ru: 'Русский',
  en: 'English',
};
