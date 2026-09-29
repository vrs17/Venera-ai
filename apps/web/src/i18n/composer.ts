// `composer.*` - yozish maydoni va uning oynalari (spec §4.3): "+" menyusi, ulanishlar,
// tasdiq kartasi, hujjat ko'ruvchi, ovoz rejimi. Eski kalitlar (`connectTo`, `action*`,
// `viewer*`, `voice*`...) ildizda qoladi va ishlatiladi - bu yerda faqat YANGI matnlar.
//
// Qoida (spec §5): yorliq 1-2 so'z, tugma - fe'l, xato - nima bo'ldi + nima qilish kerak.

import type { Mirror } from './ui'

const en = {
  placeholder: 'Ask anything',
  message: 'Message',
  add: 'Add',
  attach: 'Attach file',
  soon: 'Soon',
  disclaimer: 'Venera can make mistakes.',
  notConnected: 'Not connected',
  back: 'Back',
  sessionUntil: 'Session until {time}',
  useInChat: 'Use in chat',
  reconnectNeedsPassword: 'Reconnecting will need your password.',
  toggleFailed: 'Couldn’t switch. Try again.',
  disconnectFailed: 'Couldn’t disconnect. Try again.',
  actionSafe: 'Nothing changes until you confirm',
  minutesLeft: '{n} min left',
  underMinute: 'Under a minute left',
  fit: 'Fit to width',
  voiceHint: 'Tap the orb and speak',
}

const uz: Mirror<typeof en> = {
  placeholder: 'Savol bering',
  message: 'Xabar',
  add: 'Qoʻshish',
  attach: 'Fayl biriktirish',
  soon: 'Tez orada',
  disclaimer: 'Venera xato qilishi mumkin.',
  notConnected: 'Ulanmagan',
  back: 'Orqaga',
  sessionUntil: 'Sessiya {time} gacha',
  useInChat: 'Chatda ishlatish',
  reconnectNeedsPassword: 'Qayta ulanish uchun parol kerak boʻladi.',
  toggleFailed: 'Oʻzgartirib boʻlmadi. Qayta urinib koʻring.',
  disconnectFailed: 'Uzib boʻlmadi. Qayta urinib koʻring.',
  actionSafe: 'Tasdiqlamaguningizcha hech narsa oʻzgarmaydi',
  minutesLeft: '{n} daqiqa qoldi',
  underMinute: 'Bir daqiqadan kam qoldi',
  fit: 'Kenglikka moslash',
  voiceHint: 'Sharni bosing va gapiring',
}

const uzCyrl: Mirror<typeof en> = {
  placeholder: 'Савол беринг',
  message: 'Хабар',
  add: 'Қўшиш',
  attach: 'Файл бириктириш',
  soon: 'Тез орада',
  disclaimer: 'Венера хато қилиши мумкин.',
  notConnected: 'Уланмаган',
  back: 'Орқага',
  sessionUntil: 'Сессия {time} гача',
  useInChat: 'Чатда ишлатиш',
  reconnectNeedsPassword: 'Қайта уланиш учун парол керак бўлади.',
  toggleFailed: 'Ўзгартириб бўлмади. Қайта уриниб кўринг.',
  disconnectFailed: 'Узиб бўлмади. Қайта уриниб кўринг.',
  actionSafe: 'Тасдиқламагунингизча ҳеч нарса ўзгармайди',
  minutesLeft: '{n} дақиқа қолди',
  underMinute: 'Бир дақиқадан кам қолди',
  fit: 'Кенгликка мослаш',
  voiceHint: 'Шарни босинг ва гапиринг',
}

const ru: Mirror<typeof en> = {
  placeholder: 'Спросите что угодно',
  message: 'Сообщение',
  add: 'Добавить',
  attach: 'Прикрепить файл',
  soon: 'Скоро',
  disclaimer: 'Венера может ошибаться.',
  notConnected: 'Не подключено',
  back: 'Назад',
  sessionUntil: 'Сессия до {time}',
  useInChat: 'Использовать в чате',
  reconnectNeedsPassword: 'Для повторного подключения понадобится пароль.',
  toggleFailed: 'Не удалось переключить. Попробуйте ещё раз.',
  disconnectFailed: 'Не удалось отключить. Попробуйте ещё раз.',
  actionSafe: 'Без подтверждения ничего не изменится',
  minutesLeft: 'Осталось {n} мин',
  underMinute: 'Осталось меньше минуты',
  fit: 'По ширине',
  voiceHint: 'Нажмите на шар и говорите',
}

export const composer = { en, uz, 'uz-Cyrl': uzCyrl, ru }
