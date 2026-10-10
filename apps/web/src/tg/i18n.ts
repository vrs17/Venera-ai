// `tg.*` - faqat Telegram Mini App matnlari. Ish vaqtida umumiy i18n'ga qo'shiladi
// (`installTgMessages`, main.ts) - `src/i18n.ts` ga tegilmaydi va web ilova bu
// matnlarni yuklamaydi.
//
// Ingliz tili - kalitlar manbai; qolgan uch til `Mirror<typeof en>`: `en` ga kalit
// qo'shilsa, qolganlarida yo'qligi darhol kompilyatsiya xatosi bo'ladi.
//
// USLUB: telefon ekrani tor va odam bir qo'lda ushlaydi - matnlar QISQA. Tugma 1-2
// so'z, izoh bitta qator. Web ilovada bor kalitlar (report.*, pro.*, history*,
// composer.dictate.*) qayta ishlatiladi - bu yerda faqat Mini App'ga xoslari.
//
// vue-i18n sintaksisi: `{x}` - o'rniga qo'yiladi; `@`, `|` - maxsus (ishlatmang).

import type { Mirror } from '../i18n/ui'
import { i18n, LOCALES } from '../i18n'

const en = {
  login: {
    lead: 'Sign in once with your HRM / CRM login',
    username: 'Login',
    usernamePlaceholder: 'e.g. a.karimov',
    password: 'Password',
    submit: 'Sign in',
    busy: 'Signing in…',
    required: 'Enter your login and password',
    footnote: 'Next time Barno opens on its own',
    passwordChange: 'Set a new password in the web app first, then sign in here.',
  },
  boot: {
    failed: 'Couldn’t reach Barno',
    hint: 'Check the connection and try again.',
  },
  top: {
    history: 'Chats',
    newChat: 'New chat',
    settings: 'Settings',
  },
  welcome: {
    morning: 'Good morning, {name}',
    day: 'Good afternoon, {name}',
    evening: 'Good evening, {name}',
    morningAnon: 'Good morning!',
    dayAnon: 'Good afternoon!',
    eveningAnon: 'Good evening!',
    lead: 'What can I help with?',
    resume: 'Continue: {title}',
  },
  suggest: {
    late: { label: 'Was I late today?', hint: 'Attendance', q: 'Was I late for work today?' },
    tasks: { label: 'My tasks', hint: 'CRM', q: 'What are my CRM tasks?' },
  },
  chat: {
    copied: 'Answer copied',
    actions: 'Message actions',
    sourcesShort: '{n} sources',
    notConnected: 'Your {system} account isn’t connected. Sign in again and it connects automatically.',
    reconnect: 'Reconnect',
    selectText: 'Select text',
  },
  sources: {
    title: 'Sources',
    open: 'Open',
    opening: 'Opening…',
    failed: 'Couldn’t open',
    webOnly: 'This document opens in the web app for now',
    lookups: 'From the system',
    section: '§{n}',
  },
  proposal: {
    minutes: '{n} min',
    underMinute: '<1 min',
  },
  artifact: {
    preparing: 'Preparing…',
    failed: 'Couldn’t prepare the file',
  },
  mic: {
    denied: 'Allow the microphone for Telegram in your phone settings',
  },
  history: {
    search: 'Search chats',
    delete: 'Delete',
    rename: 'Rename',
    renameTitle: 'Chat name',
    save: 'Save',
    actions: 'Chat actions',
    empty: 'No chats yet',
    emptyHint: 'Your questions will be kept here',
  },
  settings: {
    title: 'Settings',
    themeNote: 'The theme follows Telegram',
    readAloud: 'Read answers aloud',
    readAloudHint: 'Adds a speaker button under answers',
    connections: 'Connections',
    viaLogin: 'Connected automatically with your login',
    connected: 'Connected',
    notConnected: 'Not connected',
    expired: 'Expired',
    unavailable: 'Not set up',
    logout: 'Sign out',
    logoutConfirm: 'Sign out of your account?',
    logoutMessage: 'Next time you’ll need your login and password.',
  },
  offline: 'No connection',
}

const uz: Mirror<typeof en> = {
  login: {
    lead: 'HRM / CRM login bilan bir marta kiring',
    username: 'Login',
    usernamePlaceholder: 'masalan, a.karimov',
    password: 'Parol',
    submit: 'Kirish',
    busy: 'Kirilmoqda…',
    required: 'Login va parolni kiriting',
    footnote: 'Keyingi safar Barno oʻzi ochiladi',
    passwordChange: 'Avval veb ilovada yangi parol qoʻying, soʻng shu yerda kiring.',
  },
  boot: {
    failed: 'Barnoga ulanib boʻlmadi',
    hint: 'Internetni tekshirib, qayta urinib koʻring.',
  },
  top: {
    history: 'Suhbatlar',
    newChat: 'Yangi suhbat',
    settings: 'Sozlamalar',
  },
  welcome: {
    morning: 'Xayrli tong, {name}',
    day: 'Xayrli kun, {name}',
    evening: 'Xayrli kech, {name}',
    morningAnon: 'Xayrli tong!',
    dayAnon: 'Xayrli kun!',
    eveningAnon: 'Xayrli kech!',
    lead: 'Nimada yordam beray?',
    resume: 'Davom ettirish: {title}',
  },
  suggest: {
    late: { label: 'Bugun kechikdimmi?', hint: 'Davomat', q: 'Bugun ishga kechikdimmi?' },
    tasks: { label: 'Vazifalarim', hint: 'CRM', q: 'CRM dagi vazifalarim qaysilar?' },
  },
  chat: {
    copied: 'Javob nusxalandi',
    actions: 'Xabar amallari',
    sourcesShort: '{n} manba',
    notConnected: '{system} hisobingiz ulanmagan. Qayta kirsangiz, avtomatik ulanadi.',
    reconnect: 'Qayta ulash',
    selectText: 'Matnni belgilash',
  },
  sources: {
    title: 'Manbalar',
    open: 'Ochish',
    opening: 'Ochilmoqda…',
    failed: 'Ochib boʻlmadi',
    webOnly: 'Bu hujjat hozircha veb ilovada ochiladi',
    lookups: 'Tizimdan olindi',
    section: '{n}-band',
  },
  proposal: {
    minutes: '{n} daq',
    underMinute: '<1 daq',
  },
  artifact: {
    preparing: 'Tayyorlanmoqda…',
    failed: 'Fayl tayyorlanmadi',
  },
  mic: {
    denied: 'Telefon sozlamalarida Telegramʼga mikrofon ruxsatini bering',
  },
  history: {
    search: 'Suhbatlarni qidirish',
    delete: 'Oʻchirish',
    rename: 'Nomini oʻzgartirish',
    renameTitle: 'Suhbat nomi',
    save: 'Saqlash',
    actions: 'Suhbat amallari',
    empty: 'Hali suhbat yoʻq',
    emptyHint: 'Savollaringiz shu yerda saqlanadi',
  },
  settings: {
    title: 'Sozlamalar',
    themeNote: 'Mavzu Telegramʼga ergashadi',
    readAloud: 'Javobni ovoz bilan oʻqish',
    readAloudHint: 'Javob ostida karnay tugmasi chiqadi',
    connections: 'Ulanishlar',
    viaLogin: 'Login orqali avtomatik ulanadi',
    connected: 'Ulangan',
    notConnected: 'Ulanmagan',
    expired: 'Muddati tugagan',
    unavailable: 'Sozlanmagan',
    logout: 'Chiqish',
    logoutConfirm: 'Hisobdan chiqasizmi?',
    logoutMessage: 'Keyingi safar login va parol soʻraladi.',
  },
  offline: 'Internet yoʻq',
}

const uzCyrl: Mirror<typeof en> = {
  login: {
    lead: 'HRM / CRM логин билан бир марта киринг',
    username: 'Логин',
    usernamePlaceholder: 'масалан, a.karimov',
    password: 'Парол',
    submit: 'Кириш',
    busy: 'Кирилмоқда…',
    required: 'Логин ва паролни киритинг',
    footnote: 'Кейинги сафар Барно ўзи очилади',
    passwordChange: 'Аввал веб иловада янги парол қўйинг, сўнг шу ерда киринг.',
  },
  boot: {
    failed: 'Барнога уланиб бўлмади',
    hint: 'Интернетни текшириб, қайта уриниб кўринг.',
  },
  top: {
    history: 'Суҳбатлар',
    newChat: 'Янги суҳбат',
    settings: 'Созламалар',
  },
  welcome: {
    morning: 'Хайрли тонг, {name}',
    day: 'Хайрли кун, {name}',
    evening: 'Хайрли кеч, {name}',
    morningAnon: 'Хайрли тонг!',
    dayAnon: 'Хайрли кун!',
    eveningAnon: 'Хайрли кеч!',
    lead: 'Нимада ёрдам берай?',
    resume: 'Давом эттириш: {title}',
  },
  suggest: {
    late: { label: 'Бугун кечикдимми?', hint: 'Давомат', q: 'Бугун ишга кечикдимми?' },
    tasks: { label: 'Вазифаларим', hint: 'CRM', q: 'CRM даги вазифаларим қайсилар?' },
  },
  chat: {
    copied: 'Жавоб нусхаланди',
    actions: 'Хабар амаллари',
    sourcesShort: '{n} манба',
    notConnected: '{system} ҳисобингиз уланмаган. Қайта кирсангиз, автоматик уланади.',
    reconnect: 'Қайта улаш',
    selectText: 'Матнни белгилаш',
  },
  sources: {
    title: 'Манбалар',
    open: 'Очиш',
    opening: 'Очилмоқда…',
    failed: 'Очиб бўлмади',
    webOnly: 'Бу ҳужжат ҳозирча веб иловада очилади',
    lookups: 'Тизимдан олинди',
    section: '{n}-банд',
  },
  proposal: {
    minutes: '{n} дақ',
    underMinute: '<1 дақ',
  },
  artifact: {
    preparing: 'Тайёрланмоқда…',
    failed: 'Файл тайёрланмади',
  },
  mic: {
    denied: 'Телефон созламаларида Telegram’га микрофон рухсатини беринг',
  },
  history: {
    search: 'Суҳбатларни қидириш',
    delete: 'Ўчириш',
    rename: 'Номини ўзгартириш',
    renameTitle: 'Суҳбат номи',
    save: 'Сақлаш',
    actions: 'Суҳбат амаллари',
    empty: 'Ҳали суҳбат йўқ',
    emptyHint: 'Саволларингиз шу ерда сақланади',
  },
  settings: {
    title: 'Созламалар',
    themeNote: 'Мавзу Telegram’га эргашади',
    readAloud: 'Жавобни овоз билан ўқиш',
    readAloudHint: 'Жавоб остида карнай тугмаси чиқади',
    connections: 'Уланишлар',
    viaLogin: 'Логин орқали автоматик уланади',
    connected: 'Уланган',
    notConnected: 'Уланмаган',
    expired: 'Муддати тугаган',
    unavailable: 'Созланмаган',
    logout: 'Чиқиш',
    logoutConfirm: 'Ҳисобдан чиқасизми?',
    logoutMessage: 'Кейинги сафар логин ва парол сўралади.',
  },
  offline: 'Интернет йўқ',
}

const ru: Mirror<typeof en> = {
  login: {
    lead: 'Войдите один раз с логином HRM / CRM',
    username: 'Логин',
    usernamePlaceholder: 'например, a.karimov',
    password: 'Пароль',
    submit: 'Войти',
    busy: 'Вход…',
    required: 'Введите логин и пароль',
    footnote: 'В следующий раз Барно откроется сама',
    passwordChange: 'Сначала задайте новый пароль в веб-приложении, затем войдите здесь.',
  },
  boot: {
    failed: 'Не удалось связаться с Барно',
    hint: 'Проверьте соединение и попробуйте снова.',
  },
  top: {
    history: 'Чаты',
    newChat: 'Новый чат',
    settings: 'Настройки',
  },
  welcome: {
    morning: 'Доброе утро, {name}',
    day: 'Добрый день, {name}',
    evening: 'Добрый вечер, {name}',
    morningAnon: 'Доброе утро!',
    dayAnon: 'Добрый день!',
    eveningAnon: 'Добрый вечер!',
    lead: 'Чем помочь?',
    resume: 'Продолжить: {title}',
  },
  suggest: {
    late: { label: 'Было ли опоздание сегодня?', hint: 'Посещаемость', q: 'Было ли у меня опоздание сегодня?' },
    tasks: { label: 'Мои задачи', hint: 'CRM', q: 'Какие у меня задачи в CRM?' },
  },
  chat: {
    copied: 'Ответ скопирован',
    actions: 'Действия с сообщением',
    sourcesShort: 'Источники: {n}',
    notConnected: 'Аккаунт {system} не подключён. Войдите заново, и он подключится сам.',
    reconnect: 'Переподключить',
    selectText: 'Выделить текст',
  },
  sources: {
    title: 'Источники',
    open: 'Открыть',
    opening: 'Открываем…',
    failed: 'Не удалось открыть',
    webOnly: 'Этот документ пока открывается в веб-приложении',
    lookups: 'Из системы',
    section: 'п. {n}',
  },
  proposal: {
    minutes: '{n} мин',
    underMinute: '<1 мин',
  },
  artifact: {
    preparing: 'Готовим…',
    failed: 'Не удалось подготовить файл',
  },
  mic: {
    denied: 'Разрешите Telegram доступ к микрофону в настройках телефона',
  },
  history: {
    search: 'Поиск по чатам',
    delete: 'Удалить',
    rename: 'Переименовать',
    renameTitle: 'Название чата',
    save: 'Сохранить',
    actions: 'Действия с чатом',
    empty: 'Чатов пока нет',
    emptyHint: 'Здесь сохранятся ваши вопросы',
  },
  settings: {
    title: 'Настройки',
    themeNote: 'Тема как в Telegram',
    readAloud: 'Озвучивать ответы',
    readAloudHint: 'Под ответом появится кнопка динамика',
    connections: 'Подключения',
    viaLogin: 'Подключаются автоматически по вашему логину',
    connected: 'Подключено',
    notConnected: 'Не подключено',
    expired: 'Истекло',
    unavailable: 'Не настроено',
    logout: 'Выйти',
    logoutConfirm: 'Выйти из аккаунта?',
    logoutMessage: 'В следующий раз понадобятся логин и пароль.',
  },
  offline: 'Нет соединения',
}

export const tgMessages = { en, uz, 'uz-Cyrl': uzCyrl, ru }

/** main.ts dan, ilova o'rnatilishidan OLDIN: `tg.*` kalitlari har tilga qo'shiladi. */
export function installTgMessages(): void {
  for (const { code } of LOCALES) i18n.global.mergeLocaleMessage(code, { tg: tgMessages[code] })
}

/** Takliflar tartibi - kartalar (odatda bir qatorda ikkita) shu tartibda. */
export const SUGGESTIONS = ['late', 'tasks'] as const
export type SuggestionKey = (typeof SUGGESTIONS)[number]

/** Asbob nomlari endi umumiy (`i18n/tools.ts`, `tools.*`) - web ham ishlatadi. Eski import
 *  yo'li buzilmasin deb shu yerdan ham eksport. */
export { KNOWN_TOOLS } from '../i18n/tools'
