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
 *
 * Bayonnoma ham shu chatda (ega so'rovi, 2026-11-12): ko'rsatma (`mchat.mode.note`), tayyor hujjatni
 * o'zgartirish (`mchat.mode.revise`) va javob ostidagi karta (`mchat.minutes.*`). Emoji yo'q - faqat belgilar.
 */
const uz = {
  'mchat.placeholder': "Savol bering yoki bayonnoma bo'yicha yozing",
  'mchat.send': 'Yuborish',
  'mchat.empty':
    "Bu yozuv bo'yicha savol bering yoki bayonnoma uchun ko'rsatma yozing. Barno faqat shu audio matni va xulosasiga tayanadi va suhbatni eslab qoladi.",
  'mchat.typing': 'Barno yozmoqda…',
  'mchat.resend': 'Qayta yuborish',
  'mchat.reset': 'Yangi suhbat',
  'mchat.resetConfirm':
    "Oldingi savol-javoblar va bayonnoma ko'rsatmalari ro'yxatdan olinadi, Barno ularni endi hisobga olmaydi. Tayyor bayonnomalar saqlanib qoladi. Davom etasizmi?",
  'mchat.resetOk': 'Boshlash',
  'mchat.model': 'Barno javob beradi',
  // HTML sahifali 403 (yo'ldagi himoya yoki proksi): xabar serverga yetib bormagan.
  'mchat.failed': "Xabar yetib bormadi - qayta yuboring",
  'mchat.historyFailed': "Oldingi savol-javoblarni yuklab bo'lmadi",
  'mchat.notOnServer': 'Chat serverda hali yoqilmagan - server yangilangach ishlaydi',
  // Bayonnoma chatda: bo'sh holat izohi va tezkor chip (xabar avto-tasniflanadi - "tayyorla").
  'mchat.minutesHint':
    "Bayonnoma uchun ko'rsatma ham shu yerda yoziladi - masalan: «Rais - A.Karimov, moliyaviy qismga e'tibor bering». Tayyor bayonnomada nimani o'zgartirishni yozsangiz, Barno yangi versiyasini tayyorlaydi.",
  'mchat.quickMinutes': 'Bayonnoma tayyorla',
  'mchat.quickMinutesText': 'Bayonnoma tayyorlab ber',
  // Yozish maydoni ustidagi rejim chipi (varaqdan): keyingi xabar - ko'rsatma yoki o'zgartirish so'rovi.
  'mchat.mode.note': "Bayonnoma uchun ko'rsatma",
  'mchat.mode.revise': "Bayonnomani o'zgartirish ({lang})",
  'mchat.mode.clear': 'Bekor qilish',
  // Javob ostidagi bayonnoma kartasi.
  'mchat.minutes.noteSaved': "Bayonnoma uchun ko'rsatma eslab qolindi (jami {n} ta)",
  'mchat.minutes.noteHint': 'Bayonnoma tayyorlanganda hisobga olinadi',
  'mchat.minutes.creating': 'Bayonnoma tayyorlanmoqda - odatda 1-3 daqiqa',
  'mchat.minutes.revising': 'Bayonnomaning yangi versiyasi tayyorlanmoqda - odatda 1-3 daqiqa',
  'mchat.minutes.slow': 'Odatdagidan uzoq davom etyapti - natija «Bayonnoma» oynasida chiqadi',
  'mchat.minutes.ready': 'Bayonnoma tayyor: {version}-versiya',
  'mchat.minutes.open': 'Ochish',
  'mchat.minutes.gone': 'Bu bayonnoma topilmadi',
  'mchat.minutes.notStarted': 'Bayonnoma ishi boshlanmadi: {reason}',
} as const;

type K = keyof typeof uz;

const ru: Record<K, string> = {
  'mchat.placeholder': 'Задайте вопрос или напишите о протоколе',
  'mchat.send': 'Отправить',
  'mchat.empty': 'Задайте вопрос по этой записи или дайте указания для протокола. Barno опирается только на текст и резюме этого аудио и помнит ход беседы.',
  'mchat.typing': 'Barno печатает…',
  'mchat.resend': 'Отправить снова',
  'mchat.reset': 'Новый чат',
  'mchat.resetConfirm':
    'Прежние вопросы, ответы и указания для протокола уйдут из списка, и Barno больше не будет их учитывать. Готовые протоколы сохранятся. Продолжить?',
  'mchat.resetOk': 'Начать',
  'mchat.model': 'Отвечает Barno',
  'mchat.failed': 'Сообщение не дошло - отправьте ещё раз',
  'mchat.historyFailed': 'Не удалось загрузить прежние вопросы и ответы',
  'mchat.notOnServer': 'Чат на сервере ещё не включён - заработает после обновления сервера',
  'mchat.minutesHint':
    'Здесь же можно дать указания для протокола - например: «Председатель - А. Каримов, обратите внимание на финансовую часть». Если написать, что изменить в готовом протоколе, Barno подготовит новую версию.',
  'mchat.quickMinutes': 'Подготовить протокол',
  'mchat.quickMinutesText': 'Подготовь официальный протокол',
  'mchat.mode.note': 'Указание для протокола',
  'mchat.mode.revise': 'Изменение протокола ({lang})',
  'mchat.mode.clear': 'Отменить',
  'mchat.minutes.noteSaved': 'Указание для протокола сохранено (всего: {n})',
  'mchat.minutes.noteHint': 'Будет учтено при подготовке протокола',
  'mchat.minutes.creating': 'Протокол готовится - обычно 1-3 минуты',
  'mchat.minutes.revising': 'Готовится новая версия протокола - обычно 1-3 минуты',
  'mchat.minutes.slow': 'Дольше обычного - результат появится в окне протокола',
  'mchat.minutes.ready': 'Протокол готов: версия {version}',
  'mchat.minutes.open': 'Открыть',
  'mchat.minutes.gone': 'Этот протокол не найден',
  'mchat.minutes.notStarted': 'Работа над протоколом не началась: {reason}',
};

const en: Record<K, string> = {
  'mchat.placeholder': 'Ask a question or write about the minutes',
  'mchat.send': 'Send',
  'mchat.empty': "Ask about this recording or give directions for the minutes. Barno relies only on this audio's transcript and summary, and remembers the conversation.",
  'mchat.typing': 'Barno is typing…',
  'mchat.resend': 'Send again',
  'mchat.reset': 'New chat',
  'mchat.resetConfirm':
    'Earlier questions, answers and directions for the minutes will leave the list, and Barno will no longer use them. Finished minutes are kept. Continue?',
  'mchat.resetOk': 'Start',
  'mchat.model': 'Answered by Barno',
  'mchat.failed': "The message didn't go through - send it again",
  'mchat.historyFailed': "Couldn't load the earlier questions and answers",
  'mchat.notOnServer': "Chat isn't enabled on the server yet - it will work once the server is updated",
  'mchat.minutesHint':
    'You can also give directions for the minutes here - e.g. "Chair: A. Karimov, focus on the financial part". Say what to change in finished minutes and Barno will prepare a new version.',
  'mchat.quickMinutes': 'Prepare the minutes',
  'mchat.quickMinutesText': 'Please prepare the official minutes',
  'mchat.mode.note': 'Direction for the minutes',
  'mchat.mode.revise': 'Change the minutes ({lang})',
  'mchat.mode.clear': 'Cancel',
  'mchat.minutes.noteSaved': 'Direction for the minutes saved ({n} in total)',
  'mchat.minutes.noteHint': 'Will be applied when the minutes are prepared',
  'mchat.minutes.creating': 'Preparing the minutes - usually 1-3 minutes',
  'mchat.minutes.revising': 'Preparing a new version of the minutes - usually 1-3 minutes',
  'mchat.minutes.slow': 'Taking longer than usual - the result will appear in the minutes sheet',
  'mchat.minutes.ready': 'Minutes ready: version {version}',
  'mchat.minutes.open': 'Open',
  'mchat.minutes.gone': 'These minutes were not found',
  'mchat.minutes.notStarted': "Work on the minutes didn't start: {reason}",
};

export const meetingChatPart = { uz, ru, en };
