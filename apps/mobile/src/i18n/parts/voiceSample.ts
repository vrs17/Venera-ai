/**
 * «Ovoz namunasi» (2026-11-18, ega qarori): Plaud yig'ilishlarida xodim ism-familiyasi bilan chiqishi uchun.
 * Tartib va o'qiladigan matn SERVERDAN keladi (`GET /voice-sample`) - Telegram va Slack bilan bir xil, o'zbekcha
 * (GAPI faqat o'zbek nutqini taniydi). Bu yerda faqat ekran tugmalari va holatlar. Kalitlar `vs.` bilan.
 */
const uz = {
  'vs.title': 'Ovoz namunasi',
  'vs.hubOn': 'Saqlangan · {n} ta namuna',
  'vs.hubOff': 'Yozilmagan',
  'vs.saved': "✅ Ovozingiz saqlangan ({n} ta namuna). Yangi namuna yozsangiz qo'shiladi va tanish aniqroq bo'ladi.",
  'vs.steps': 'Qanday yoziladi',
  'vs.textTitle': "O'qiladigan matn",
  'vs.start': 'Yozishni boshlash',
  'vs.stop': "To'xtatish",
  'vs.again': 'Qayta yozish',
  'vs.send': 'Yuborish',
  'vs.recording': 'Yozilmoqda… {time}',
  'vs.recorded': 'Yozildi: {time}',
  'vs.tooShort': 'Kamida 30 soniya yozing (tavsiya - taxminan 45 soniya).',
  'vs.checking': 'Tekshirilmoqda… odatda 10-60 soniya',
  'vs.delete': "Ovozimni o'chirish",
  'vs.deleteConfirm': "Ovoz namunangiz o'chirilsinmi? Yig'ilishlarda ismingiz endi avtomatik chiqmaydi.",
  'vs.micDenied': 'Mikrofonga ruxsat berilmadi - telefon sozlamalaridan ruxsat bering.',
  'vs.busyRecorder': "Yig'ilish yozilmoqda - namunani yozish uchun avval uni tugating.",
  'vs.disabled': "Ovoz namunasi hozir o'chiq.",
  'vs.failed': "Yuborib bo'lmadi - internetni tekshirib, qayta urinib ko'ring.",
};

type Keys = keyof typeof uz;

const ru: Record<Keys, string> = {
  'vs.title': 'Образец голоса',
  'vs.hubOn': 'Сохранён · образцов: {n}',
  'vs.hubOff': 'Не записан',
  'vs.saved': '✅ Ваш голос сохранён (образцов: {n}). Новый образец добавится и улучшит распознавание.',
  'vs.steps': 'Как записать',
  'vs.textTitle': 'Текст для чтения (на узбекском)',
  'vs.start': 'Начать запись',
  'vs.stop': 'Остановить',
  'vs.again': 'Записать заново',
  'vs.send': 'Отправить',
  'vs.recording': 'Идёт запись… {time}',
  'vs.recorded': 'Записано: {time}',
  'vs.tooShort': 'Запишите не меньше 30 секунд (лучше около 45).',
  'vs.checking': 'Проверяем… обычно 10-60 секунд',
  'vs.delete': 'Удалить мой голос',
  'vs.deleteConfirm': 'Удалить образец голоса? На встречах ваше имя больше не будет определяться автоматически.',
  'vs.micDenied': 'Нет доступа к микрофону - разрешите его в настройках телефона.',
  'vs.busyRecorder': 'Идёт запись встречи - сначала завершите её.',
  'vs.disabled': 'Образец голоса сейчас отключён.',
  'vs.failed': 'Не удалось отправить - проверьте интернет и попробуйте ещё раз.',
};

const en: Record<Keys, string> = {
  'vs.title': 'Voice sample',
  'vs.hubOn': 'Saved · {n} samples',
  'vs.hubOff': 'Not recorded',
  'vs.saved': '✅ Your voice is saved ({n} samples). A new sample is added and makes recognition more accurate.',
  'vs.steps': 'How to record',
  'vs.textTitle': 'Text to read (in Uzbek)',
  'vs.start': 'Start recording',
  'vs.stop': 'Stop',
  'vs.again': 'Record again',
  'vs.send': 'Send',
  'vs.recording': 'Recording… {time}',
  'vs.recorded': 'Recorded: {time}',
  'vs.tooShort': 'Record at least 30 seconds (about 45 is best).',
  'vs.checking': 'Checking… usually 10-60 seconds',
  'vs.delete': 'Delete my voice',
  'vs.deleteConfirm': 'Delete your voice sample? Your name will no longer be shown automatically in meetings.',
  'vs.micDenied': 'Microphone access denied - allow it in the phone settings.',
  'vs.busyRecorder': 'A meeting is being recorded - finish it first.',
  'vs.disabled': 'Voice samples are turned off right now.',
  'vs.failed': 'Could not send - check the connection and try again.',
};

export const voiceSamplePart = { uz, ru, en };
