/**
 * Yozuv chati (`features/meeting/ChatView`, yozuv sahifasidagi "Chat" tabi) - bitta audio
 * bo'yicha Barno bilan suhbat. Kalitlar `mchat.` bilan.
 *
 * NIMA UCHUN alohida fayl: bo'limlar parallel yoziladi - har biri faqat o'z qismiga kalit qo'shadi
 * (`parts/nav.ts` dagi izohga qarang). Bu fayl `uz.ts`ni import QILMAYDI (sikl bo'lmasin).
 *
 * Matn qoidalari Slack/Telegram'dagi chat bilan bir xil: Barno faqat SHU yozuv matni va xulosasiga
 * tayanadi va suhbatni eslab qoladi; "Yangi suhbat" eskisini o'chirmaydi - modelga boshqa yubormaydi.
 * Tezkor savollar (`ask.quick.*`) va "matn tayyor emas" (`ask.notReady`) - asosiy lug'atda.
 */
const uz = {
  'mchat.placeholder': "Shu yozuv bo'yicha savol bering",
  'mchat.send': 'Yuborish',
  'mchat.empty': "Bu yozuv bo'yicha savol bering. Barno faqat shu audio matni va xulosasiga tayanadi va suhbatni eslab qoladi.",
  'mchat.typing': 'Barno yozmoqda…',
  'mchat.resend': 'Qayta yuborish',
  'mchat.reset': 'Yangi suhbat',
  'mchat.resetConfirm': "Oldingi savol-javoblar ro'yxatdan olinadi va Barno ularni endi hisobga olmaydi. Davom etasizmi?",
  'mchat.resetOk': 'Boshlash',
  'mchat.model': 'Javob beradi: {model}',
  // HTML sahifali 403 (yo'ldagi himoya yoki proksi): xabar serverga yetib bormagan.
  'mchat.failed': "Xabar yetib bormadi - qayta yuboring",
  'mchat.historyFailed': "Oldingi savol-javoblarni yuklab bo'lmadi",
  'mchat.notOnServer': 'Chat serverda hali yoqilmagan - server yangilangach ishlaydi',
} as const;

type K = keyof typeof uz;

const ru: Record<K, string> = {
  'mchat.placeholder': 'Спросите об этой записи',
  'mchat.send': 'Отправить',
  'mchat.empty': 'Задайте вопрос по этой записи. Barno опирается только на текст и резюме этого аудио и помнит ход беседы.',
  'mchat.typing': 'Barno печатает…',
  'mchat.resend': 'Отправить снова',
  'mchat.reset': 'Новый чат',
  'mchat.resetConfirm': 'Прежние вопросы и ответы уйдут из списка, и Barno больше не будет их учитывать. Продолжить?',
  'mchat.resetOk': 'Начать',
  'mchat.model': 'Отвечает: {model}',
  'mchat.failed': 'Сообщение не дошло - отправьте ещё раз',
  'mchat.historyFailed': 'Не удалось загрузить прежние вопросы и ответы',
  'mchat.notOnServer': 'Чат на сервере ещё не включён - заработает после обновления сервера',
};

const en: Record<K, string> = {
  'mchat.placeholder': 'Ask about this recording',
  'mchat.send': 'Send',
  'mchat.empty': "Ask a question about this recording. Barno relies only on this audio's transcript and summary, and remembers the conversation.",
  'mchat.typing': 'Barno is typing…',
  'mchat.resend': 'Send again',
  'mchat.reset': 'New chat',
  'mchat.resetConfirm': 'Earlier questions and answers will leave the list, and Barno will no longer take them into account. Continue?',
  'mchat.resetOk': 'Start',
  'mchat.model': 'Answered by {model}',
  'mchat.failed': "The message didn't go through - send it again",
  'mchat.historyFailed': "Couldn't load the earlier questions and answers",
  'mchat.notOnServer': "Chat isn't enabled on the server yet - it will work once the server is updated",
};

export const meetingChatPart = { uz, ru, en };
