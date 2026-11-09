/**
 * "Boshqa tilda qayta o'girish" (Slack'da har kartada "boshqa til" tugmalari bor): maqsad -
 * yig'ilishning hozirgi tilidan boshqa tillar. Qayta o'girish limitdan yana hisoblanadi va eski
 * xulosalarni o'chiradi - shuning uchun til tanlangandan keyin mavjud tasdiq oynasi
 * (`detail.retranscribeConfirm`) va mavjud `retranscribe` mutatsiyasi.
 */
import type { Lang } from '@/api/types';
import type { TKey } from '@/i18n';

export const RETRANSCRIBE_LANGS: readonly Lang[] = ['uz', 'ru', 'en'];

/** Menyu qatori va tasdiq oynasi sarlavhasi: "Rus tilida qayta o'girish". */
export const RETRANSCRIBE_TITLE: Record<Lang, TKey> = {
  uz: 'detail.retranscribeUz',
  ru: 'detail.retranscribeRu',
  en: 'detail.retranscribeEn',
};

/** Yig'ilishning hozirgi tilidan boshqa tillar (tartib doim uz, ru, en). */
export function retranscribeTargets(current: Lang | string | null | undefined): Lang[] {
  return RETRANSCRIBE_LANGS.filter((l) => l !== current);
}
