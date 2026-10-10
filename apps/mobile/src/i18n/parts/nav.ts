/**
 * Navigatsiya matnlari (drawer, chat tepa paneli, yozuv holati). Kalitlar `nav.` bilan.
 *
 * NIMA UCHUN alohida fayl: UI qayta ishlanishida bir nechta quruvchi parallel
 * ishlaydi - har biri faqat o'z qismiga kalit qo'shadi, asosiy `uz/ru/en.ts`
 * birlashishda to'qnashmaydi. `uz.ts` bu yerdagi `uz` ni o'z `as const` ichiga
 * yoyadi - `TKey` ularni ham qamraydi. Bu fayl `uz.ts`ni import QILMAYDI (sikl bo'lmasin).
 */
const uz = {
  'nav.menu': 'Menyu',
  'nav.search': 'Suhbatlardan qidirish',
  'nav.searchClose': 'Qidiruvni yopish',
  'nav.noResults': 'Hech narsa topilmadi',
  'nav.recordings': 'Yozuvlar',
  'nav.record': 'Yozish',
  'nav.recordingLive': 'Yozilmoqda {time}',
  'nav.pausedLive': 'Pauzada {time}',
  'nav.pendingA11y': '{n} ta yozuv yuklanmagan',
  'nav.open': 'Ochish',
  'nav.profileA11y': 'Profil va sozlamalar',
  'nav.chatHint': "Nomini o'zgartirish yoki o'chirish uchun bosib turing",
} as const;

type K = keyof typeof uz;

const ru: Record<K, string> = {
  'nav.menu': 'Меню',
  'nav.search': 'Поиск по чатам',
  'nav.searchClose': 'Закрыть поиск',
  'nav.noResults': 'Ничего не найдено',
  'nav.recordings': 'Записи',
  'nav.record': 'Записать',
  'nav.recordingLive': 'Запись {time}',
  'nav.pausedLive': 'Пауза {time}',
  'nav.pendingA11y': 'Не загружено записей: {n}',
  'nav.open': 'Открыть',
  'nav.profileA11y': 'Профиль и настройки',
  'nav.chatHint': 'Удерживайте, чтобы переименовать или удалить',
};

const en: Record<K, string> = {
  'nav.menu': 'Menu',
  'nav.search': 'Search chats',
  'nav.searchClose': 'Close search',
  'nav.noResults': 'Nothing found',
  'nav.recordings': 'Recordings',
  'nav.record': 'Record',
  'nav.recordingLive': 'Recording {time}',
  'nav.pausedLive': 'Paused {time}',
  'nav.pendingA11y': 'Not uploaded: {n}',
  'nav.open': 'Open',
  'nav.profileA11y': 'Profile and settings',
  'nav.chatHint': 'Long-press to rename or delete',
};

export const nav = { uz, ru, en };
