// `report.*` - "Xabar berish" oynasi (spec §4.4): foydalanuvchi butun suhbatni yoki
// bitta javobni jamoaga yuboradi. Sabab va izoh ixtiyoriy - tugmani bosishning o'zi
// ham foydali signal, shuning uchun matn qisqa va hech narsani majburlamaydi.
//
// Sabab kalitlari backend bilan bir xil (`schemas/reports.py::REASONS`), tartibi ham.

import type { Mirror } from './ui'

const en = {
  title: 'Report',
  subtitle: 'The whole conversation will be sent to the team.',
  reasonLabel: 'Reason',
  reason: {
    wrong: 'Wrong',
    incomplete: 'Incomplete',
    outdated: 'Outdated',
    unsafe: 'Unsafe',
    other: 'Other',
  },
  commentLabel: 'Comment',
  placeholder: 'What went wrong? (optional)',
  send: 'Send',
  cancel: 'Cancel',
  sent: 'Sent. Thank you!',
  error: 'Couldn’t send. Try again.',
  rateLimited: 'Too many reports. Try again in an hour.',
  // 429 matni. Dialog `tooMany` ni o'qiydi; `rateLimited` - eski nomi, boshqalar ishlatgan bo'lishi mumkin.
  tooMany: 'Too many reports. Try again in an hour.',
  reportedTooltip: 'Reported',
  reportConversation: 'Report conversation',
  reportAnswer: 'Report answer',
  unavailable: 'Available after the first answer',
}

const uz: Mirror<typeof en> = {
  title: 'Xabar berish',
  subtitle: 'Butun suhbat jamoaga yuboriladi.',
  reasonLabel: 'Sabab',
  reason: {
    wrong: 'Notoʻgʻri',
    incomplete: 'Toʻliq emas',
    outdated: 'Eskirgan',
    unsafe: 'Xavfli',
    other: 'Boshqa',
  },
  commentLabel: 'Izoh',
  placeholder: 'Nima notoʻgʻri? (ixtiyoriy)',
  send: 'Yuborish',
  cancel: 'Bekor qilish',
  sent: 'Yuborildi. Rahmat!',
  error: 'Yuborib boʻlmadi. Qayta urinib koʻring.',
  rateLimited: 'Xabarlar juda koʻp. Bir soatdan keyin urinib koʻring.',
  tooMany: 'Xabarlar juda koʻp. Bir soatdan keyin urinib koʻring.',
  reportedTooltip: 'Xabar berilgan',
  reportConversation: 'Suhbat haqida xabar berish',
  reportAnswer: 'Javob haqida xabar berish',
  unavailable: 'Birinchi javobdan keyin',
}

const uzCyrl: Mirror<typeof en> = {
  title: 'Хабар бериш',
  subtitle: 'Бутун суҳбат жамоага юборилади.',
  reasonLabel: 'Сабаб',
  reason: {
    wrong: 'Нотўғри',
    incomplete: 'Тўлиқ эмас',
    outdated: 'Эскирган',
    unsafe: 'Хавфли',
    other: 'Бошқа',
  },
  commentLabel: 'Изоҳ',
  placeholder: 'Нима нотўғри? (ихтиёрий)',
  send: 'Юбориш',
  cancel: 'Бекор қилиш',
  sent: 'Юборилди. Раҳмат!',
  error: 'Юбориб бўлмади. Қайта уриниб кўринг.',
  rateLimited: 'Хабарлар жуда кўп. Бир соатдан кейин уриниб кўринг.',
  tooMany: 'Хабарлар жуда кўп. Бир соатдан кейин уриниб кўринг.',
  reportedTooltip: 'Хабар берилган',
  reportConversation: 'Суҳбат ҳақида хабар бериш',
  reportAnswer: 'Жавоб ҳақида хабар бериш',
  unavailable: 'Биринчи жавобдан кейин',
}

const ru: Mirror<typeof en> = {
  title: 'Сообщить о проблеме',
  subtitle: 'Команда получит весь диалог.',
  reasonLabel: 'Причина',
  reason: {
    wrong: 'Неверно',
    incomplete: 'Неполно',
    outdated: 'Устарело',
    unsafe: 'Опасно',
    other: 'Другое',
  },
  commentLabel: 'Комментарий',
  placeholder: 'Что не так? (необязательно)',
  send: 'Отправить',
  cancel: 'Отмена',
  sent: 'Отправлено. Спасибо!',
  error: 'Не удалось отправить. Попробуйте ещё раз.',
  rateLimited: 'Слишком много жалоб. Попробуйте через час.',
  tooMany: 'Слишком много жалоб. Попробуйте через час.',
  reportedTooltip: 'Жалоба отправлена',
  reportConversation: 'Пожаловаться на диалог',
  reportAnswer: 'Пожаловаться на ответ',
  unavailable: 'Доступно после первого ответа',
}

export const report = { en, uz, 'uz-Cyrl': uzCyrl, ru }
