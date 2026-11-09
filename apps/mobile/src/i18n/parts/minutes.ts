/**
 * Bayonnoma varag'i (`features/meeting/MinutesSheet`) - yig'ilish yozuvidan rasmiy hujjat loyihasi.
 * Kalitlar `minutes.` bilan.
 *
 * NIMA UCHUN alohida fayl: bo'limlar parallel yoziladi - har biri faqat o'z qismiga kalit qo'shadi
 * (`parts/nav.ts` dagi izohga qarang). Bu fayl `uz.ts`ni import QILMAYDI (sikl bo'lmasin).
 *
 * Matn qoidalari Slack/Telegram'dagi «📄 Bayonnoma» bilan bir xil: hujjat LOYIHA, «________»
 * joylarini kotib yoki hujjat tizimi to'ldiradi; xato SABABni va keyingi qadamni aytadi. Hujjat
 * tillari nomlari (endonim) bu yerda emas - `minutesModel.MINUTES_LANG_NAME`.
 */
const uz = {
  'minutes.title': 'Bayonnoma',
  'minutes.lead': 'Rasmiy hujjat loyihasi: kun tartibi, bayon va raqamlangan qaror bandlari',
  'minutes.language': 'Hujjat tili',
  'minutes.prepare': 'Tayyorlash',
  'minutes.redo': 'Qayta yozish',
  'minutes.check': 'Qayta tekshirish',
  'minutes.running': 'Bayonnoma yozilmoqda - odatda 1-3 daqiqa',
  'minutes.runningHint': "Oynani yopsangiz ham ish davom etadi - qayta ochsangiz natija shu yerda bo'ladi.",
  'minutes.slow': "Bayonnoma odatdagidan uzoq yozilmoqda. Keyinroq qayta oching - tayyor bo'lsa shu yerda chiqadi.",
  'minutes.ready': "Bayonnoma tayyor: {sections} bo'lim, {items} band",
  'minutes.draftPill': 'Loyiha',
  'minutes.draft': "Bu loyiha: «________» joylarini (bank nomi, rais, qatnashuvchilar, №, sana) kotib yoki hujjat tizimi to'ldiradi.",
  'minutes.notes': 'Aniqlashtirish kerak',
  'minutes.warnings': "Tekshiruvda {n} ta ogohlantirish - hujjatni diqqat bilan ko'zdan kechiring",
  'minutes.stale': "Matn o'zgargan - avvalgi bayonnoma eskirgan. Yangisini tayyorlang.",
  // Xato bilan tugagan qator - FAQAT `error.code` bo'yicha (server `message`i texnik sabab).
  'minutes.failedNoReason': "Bayonnoma yozilmadi - qayta urinib ko'ring",
  'minutes.interrupted': "Bayonnoma yozish uzilib qoldi - qayta urinib ko'ring",
  'minutes.modelLimited': "Model chegarasiga yetdi - birozdan keyin qayta urinib ko'ring",
  'minutes.internal': "Serverda ichki xato - qayta urinib ko'ring",
  'minutes.offline': "Internet yo'q. Bayonnoma serverda yoziladi - ulanish qaytgach qayta urinib ko'ring.",
  'minutes.rateLimited': "Bir soatlik bayonnoma chegarasi tugadi - keyinroq urinib ko'ring",
  'minutes.rateLimitedIn': "Bir soatlik bayonnoma chegarasi tugadi - {wait}dan keyin urinib ko'ring",
  'minutes.waitMin': '{n} daqiqa',
  'minutes.waitSec': '{n} soniya',
  'minutes.busy': "Model hozir band - birozdan keyin qayta urinib ko'ring",
  'minutes.transcriptEmpty': "Yozuvda nutq topilmadi - bayonnoma uchun gapirilgan yig'ilish yozuvi kerak",
  'minutes.transcriptNotReady': "Yozuv hali matnga o'girilmagan - matn tayyor bo'lgach bayonnoma yozish mumkin",
  'minutes.notConfigured': 'Bayonnoma xizmati hali sozlanmagan - administratorga murojaat qiling',
  'minutes.writeFailed': "Model bayonnomani yozolmadi - qayta urinib ko'ring",
  'minutes.gone': 'Bayonnoma topilmadi - qaytadan tayyorlang',
  'minutes.docNotReady': 'Bayonnoma hali tayyor emas - holatini qayta tekshiring',
  'minutes.notOnServer': 'Bayonnoma serverda hali yoqilmagan - server yangilangach ishlaydi',
} as const;

type K = keyof typeof uz;

const ru: Record<K, string> = {
  // "Протокол" - xulosa shabloni nomi (server bilan bir xil); rasmiy hujjat menyuda adashmasin.
  'minutes.title': 'Официальный протокол',
  'minutes.lead': 'Черновик официального документа: повестка, ход обсуждения и пронумерованные решения',
  'minutes.language': 'Язык документа',
  'minutes.prepare': 'Подготовить',
  'minutes.redo': 'Составить заново',
  'minutes.check': 'Проверить снова',
  'minutes.running': 'Протокол составляется - обычно 1-3 минуты',
  'minutes.runningHint': 'Окно можно закрыть - работа продолжится, а результат появится здесь.',
  'minutes.slow': 'Протокол составляется дольше обычного. Откройте позже - готовый протокол появится здесь.',
  'minutes.ready': 'Протокол готов: разделов - {sections}, пунктов - {items}',
  'minutes.draftPill': 'Черновик',
  'minutes.draft': 'Это черновик: поля «________» (название банка, председатель, участники, №, дата) заполняет секретарь или система документооборота.',
  'minutes.notes': 'Нужно уточнить',
  'minutes.warnings': 'Предупреждений проверки: {n} - внимательно просмотрите документ',
  'minutes.stale': 'Текст изменился - прежний протокол устарел. Подготовьте новый.',
  'minutes.failedNoReason': 'Протокол не составлен - попробуйте снова',
  'minutes.interrupted': 'Составление протокола прервалось - попробуйте снова',
  'minutes.modelLimited': 'Модель упёрлась в лимит запросов - попробуйте чуть позже',
  'minutes.internal': 'Внутренняя ошибка сервера - попробуйте снова',
  'minutes.offline': 'Нет интернета. Протокол составляется на сервере - попробуйте снова, когда связь вернётся.',
  'minutes.rateLimited': 'Часовой лимит протоколов исчерпан - попробуйте позже',
  'minutes.rateLimitedIn': 'Часовой лимит протоколов исчерпан - попробуйте через {wait}',
  'minutes.waitMin': '{n} мин',
  'minutes.waitSec': '{n} с',
  'minutes.busy': 'Модель сейчас занята - попробуйте чуть позже',
  'minutes.transcriptEmpty': 'В записи не найдено речи - для протокола нужна запись встречи, где говорят люди',
  'minutes.transcriptNotReady': 'Запись ещё не расшифрована - протокол можно составить, когда будет готов текст',
  'minutes.notConfigured': 'Служба протоколов ещё не настроена - обратитесь к администратору',
  'minutes.writeFailed': 'Модели не удалось составить протокол - попробуйте снова',
  'minutes.gone': 'Протокол не найден - подготовьте заново',
  'minutes.docNotReady': 'Протокол ещё не готов - проверьте его состояние снова',
  'minutes.notOnServer': 'Протоколы на сервере ещё не включены - заработают после обновления сервера',
};

const en: Record<K, string> = {
  // "Minutes" - xulosa shabloni nomi (server bilan bir xil); rasmiy hujjat menyuda adashmasin.
  'minutes.title': 'Official minutes',
  'minutes.lead': 'A draft of the formal document: agenda, discussion and numbered decisions',
  'minutes.language': 'Document language',
  'minutes.prepare': 'Prepare',
  'minutes.redo': 'Write again',
  'minutes.check': 'Check again',
  'minutes.running': 'Writing the minutes - usually 1-3 minutes',
  'minutes.runningHint': 'You can close this - the work goes on and the result will be here.',
  'minutes.slow': 'This is taking longer than usual. Check back later - the minutes will be here when ready.',
  'minutes.ready': 'Minutes ready - sections: {sections}, items: {items}',
  'minutes.draftPill': 'Draft',
  'minutes.draft': 'This is a draft: the «________» blanks (bank name, chair, attendees, No., date) are filled in by the secretary or the document system.',
  'minutes.notes': 'Needs clarification',
  'minutes.warnings': 'Check warnings: {n} - review the document carefully',
  'minutes.stale': 'The transcript changed - the earlier minutes are out of date. Prepare new ones.',
  'minutes.failedNoReason': "The minutes weren't written - try again",
  'minutes.interrupted': 'Writing the minutes was interrupted - try again',
  'minutes.modelLimited': 'The model hit its request limit - try again in a moment',
  'minutes.internal': 'Internal server error - try again',
  'minutes.offline': "No internet. The minutes are written on the server - try again when you're back online.",
  'minutes.rateLimited': 'Hourly minutes limit reached - try again later',
  'minutes.rateLimitedIn': 'Hourly minutes limit reached - try again in {wait}',
  'minutes.waitMin': '{n} min',
  'minutes.waitSec': '{n} s',
  'minutes.busy': 'The model is busy right now - try again in a moment',
  'minutes.transcriptEmpty': 'No speech found in the recording - minutes need a recording of people talking',
  'minutes.transcriptNotReady': "The recording isn't transcribed yet - minutes can be written once the transcript is ready",
  'minutes.notConfigured': "The minutes service isn't set up yet - contact your administrator",
  'minutes.writeFailed': "The model couldn't write the minutes - try again",
  'minutes.gone': 'The minutes were not found - prepare them again',
  'minutes.docNotReady': "The minutes aren't ready yet - check their status again",
  'minutes.notOnServer': "Minutes aren't enabled on the server yet - they'll work once the server is updated",
};

export const minutesPart = { uz, ru, en };
