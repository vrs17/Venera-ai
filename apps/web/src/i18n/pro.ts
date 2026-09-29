// `pro.*` - "Pro" rejimi (kiritish panelidagi kalit va javob ostidagi belgi).
//
// "Pro" HAR XABAR uchun yoqiladi: yordamchi tashqi modeldan maslahat oladi, bu pulga
// tushadi va odamning byudjetidan yeydi. Shuning uchun matnlar qisqa, lekin byudjet
// qayerga ketganini aniq aytadi: belgining uch holati (ishlatildi / kerak bo'lmadi /
// berilmadi) ATAYLAB farqlanadi - byudjet faqat birinchisida yeyiladi.
//
// Ildizdagi eski `pro*` kalitlari (`src/i18n.ts`) o'zgarmay qoladi - yangi interfeys
// shu fayldan o'qiydi.

import type { Mirror } from './ui'

const en = {
  label: 'Pro',
  toggle: 'Pro mode',
  hint: 'External model for hard questions',
  left: '{n} left',
  exhausted: 'Pro limit reached. It refills over time.',
  used: 'Answered with the external model',
  notNeeded: 'External model wasn’t needed',
  denied: 'Pro not granted: {why}',
  reasonLimit: 'limit reached',
  reasonNoUser: 'user not identified',
}

const uz: Mirror<typeof en> = {
  label: 'Pro',
  toggle: 'Pro rejimi',
  hint: 'Murakkab savollar uchun tashqi model',
  left: '{n} ta qoldi',
  exhausted: 'Pro limiti tugadi. Vaqt oʻtishi bilan tiklanadi.',
  used: 'Tashqi model bilan javob berildi',
  notNeeded: 'Tashqi model kerak boʻlmadi',
  denied: 'Pro berilmadi: {why}',
  reasonLimit: 'limit tugagan',
  reasonNoUser: 'foydalanuvchi aniqlanmadi',
}

const uzCyrl: Mirror<typeof en> = {
  label: 'Pro',
  toggle: 'Pro режими',
  hint: 'Мураккаб саволлар учун ташқи модел',
  left: '{n} та қолди',
  exhausted: 'Pro лимити тугади. Вақт ўтиши билан тикланади.',
  used: 'Ташқи модел билан жавоб берилди',
  notNeeded: 'Ташқи модел керак бўлмади',
  denied: 'Pro берилмади: {why}',
  reasonLimit: 'лимит тугаган',
  reasonNoUser: 'фойдаланувчи аниқланмади',
}

const ru: Mirror<typeof en> = {
  label: 'Pro',
  toggle: 'Режим Pro',
  hint: 'Внешняя модель для сложных вопросов',
  left: 'Осталось {n}',
  exhausted: 'Лимит Pro исчерпан. Он восстанавливается со временем.',
  used: 'Ответ с внешней моделью',
  notNeeded: 'Внешняя модель не понадобилась',
  denied: 'Pro не предоставлен: {why}',
  reasonLimit: 'лимит исчерпан',
  reasonNoUser: 'пользователь не определён',
}

export const pro = { en, uz, 'uz-Cyrl': uzCyrl, ru }
