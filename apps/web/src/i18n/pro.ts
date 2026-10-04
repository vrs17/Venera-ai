// `pro.*` - "Pro" rejimi (kiritish panelidagi kalit va javob ostidagi belgi).
//
// "Pro" HAR XABAR uchun yoqiladi: yordamchi tashqi modeldan maslahat oladi, bu pulga
// tushadi va odamning byudjetidan yeydi. Shuning uchun matnlar qisqa, lekin byudjet
// qayerga ketganini aniq aytadi: belgining uch holati (ishlatildi / kerak bo'lmadi /
// berilmadi) ATAYLAB farqlanadi - byudjet faqat birinchisida yeyiladi.
//
// Ildizdagi eski `pro*` kalitlari (`src/i18n.ts`) o'zgarmay qoladi - yangi interfeys
// shu fayldan o'qiydi.
//
// IKKI QAVAT: `badge*` / `why*` - javob ostida KO'RINIB turadigan qisqa yozuv
// ("ishlatildi (1 ta murojaat)"), `used` / `notNeeded` / `denied` + `reason*` - uning
// tooltip'i va admin izidagi to'liq gap. `hint` - xizmat jamoasi bergan matn (uz -
// so'zma-so'z), qolgan tillar - uning aniq tarjimasi. `badgeUsed` faqat inglizchada
// `|` bilan (ko'plik), rus tilida "вызовов: {n}" - uch shaklni sanamaslik uchun.

import type { Mirror } from './ui'

const en = {
  label: 'Pro',
  toggle: 'Pro mode',
  hint: 'Pro — for complex questions: the assistant consults an external model, within the limit.',
  left: '{n} left',
  exhausted: 'Pro limit reached. It refills over time.',
  used: 'Answered with the external model',
  notNeeded: 'External model wasn’t needed',
  denied: 'Pro not granted: {why}',
  reasonLimit: 'limit reached',
  reasonNoUser: 'user not identified',
  reasonEngine: 'this assistant version has no Pro mode',
  badgeUsed: 'used ({n} call) | used ({n} calls)',
  badgeUsedPlain: 'used',
  badgeNotNeeded: 'not needed',
  badgeDenied: 'not granted ({why})',
  whyLimit: 'limit',
  whyNoUser: 'no user',
  whyEngine: 'engine',
}

const uz: Mirror<typeof en> = {
  label: 'Pro',
  toggle: 'Pro rejimi',
  hint: 'Pro — murakkab savollar uchun: yordamchi tashqi modeldan maslahat oladi, limit doirasida.',
  left: '{n} ta qoldi',
  exhausted: 'Pro limiti tugadi. Vaqt oʻtishi bilan tiklanadi.',
  used: 'Tashqi model bilan javob berildi',
  notNeeded: 'Tashqi model kerak boʻlmadi',
  denied: 'Pro berilmadi: {why}',
  reasonLimit: 'limit tugagan',
  reasonNoUser: 'foydalanuvchi aniqlanmadi',
  reasonEngine: 'yordamchining bu versiyasida Pro yoʻq',
  badgeUsed: 'ishlatildi ({n} ta murojaat)',
  badgeUsedPlain: 'ishlatildi',
  badgeNotNeeded: 'kerak boʻlmadi',
  badgeDenied: 'berilmadi ({why})',
  whyLimit: 'limit',
  whyNoUser: 'foydalanuvchi yoʻq',
  whyEngine: 'versiya',
}

const uzCyrl: Mirror<typeof en> = {
  label: 'Pro',
  toggle: 'Pro режими',
  hint: 'Pro — мураккаб саволлар учун: ёрдамчи ташқи моделдан маслаҳат олади, лимит доирасида.',
  left: '{n} та қолди',
  exhausted: 'Pro лимити тугади. Вақт ўтиши билан тикланади.',
  used: 'Ташқи модел билан жавоб берилди',
  notNeeded: 'Ташқи модел керак бўлмади',
  denied: 'Pro берилмади: {why}',
  reasonLimit: 'лимит тугаган',
  reasonNoUser: 'фойдаланувчи аниқланмади',
  reasonEngine: 'ёрдамчининг бу версиясида Pro йўқ',
  badgeUsed: 'ишлатилди ({n} та мурожаат)',
  badgeUsedPlain: 'ишлатилди',
  badgeNotNeeded: 'керак бўлмади',
  badgeDenied: 'берилмади ({why})',
  whyLimit: 'лимит',
  whyNoUser: 'фойдаланувчи йўқ',
  whyEngine: 'версия',
}

const ru: Mirror<typeof en> = {
  label: 'Pro',
  toggle: 'Режим Pro',
  hint: 'Pro — для сложных вопросов: ассистент консультируется с внешней моделью, в пределах лимита.',
  left: 'Осталось {n}',
  exhausted: 'Лимит Pro исчерпан. Он восстанавливается со временем.',
  used: 'Ответ с внешней моделью',
  notNeeded: 'Внешняя модель не понадобилась',
  denied: 'Pro не предоставлен: {why}',
  reasonLimit: 'лимит исчерпан',
  reasonNoUser: 'пользователь не определён',
  reasonEngine: 'в этой версии ассистента нет Pro',
  badgeUsed: 'использован (вызовов: {n})',
  badgeUsedPlain: 'использован',
  badgeNotNeeded: 'не понадобился',
  badgeDenied: 'не предоставлен ({why})',
  whyLimit: 'лимит',
  whyNoUser: 'нет пользователя',
  whyEngine: 'версия',
}

export const pro = { en, uz, 'uz-Cyrl': uzCyrl, ru }
