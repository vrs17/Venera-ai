// `shell.*` - kirish, parolni o'rnatish va xush kelibsiz sahifalari (spec §4.1-4.2).
// Sarlavha, maydon va tugma matnlari eski ildiz kalitlardan olinadi (signIn,
// password, authLoginSub...) - bu yerda faqat YANGI matnlar.
//
// Xato matnlari bitta gap: nima bo'ldi + nima qilish kerak (spec §5). Kalit nomlari
// `api/errors.ts::authErrorKind` qaytaradigan turlar bilan bir xil.

import type { Mirror } from './ui'

const en = {
  auth: {
    caption: 'Use your HRM / CRM account',
    wrongCredentials: 'Wrong login or password.',
    blocked: 'This account is blocked. Contact an administrator.',
    accountSetup: 'Your password is correct, but the account has an unfinished step: sign in to CRM once in a browser, then try again.',
    openCrm: 'Open CRM',
    network: 'Can’t reach Barno. Check your connection.',
    unavailable: 'Barno is temporarily unavailable. Try again shortly.',
    sso: {
      button: 'Sign in with BRB-Tech ID',
      caption: 'One corporate account for every BRB-Tech system',
      redirecting: 'Opening the BRB-Tech sign-in page…',
      finishing: 'Finishing sign-in…',
      or: 'or with a local account',
      denied: 'Sign-in was cancelled on the BRB-Tech ID page.',
      blocked: 'This account is blocked in Barno. Contact an administrator.',
      expired: 'The sign-in took too long or was already used. Try again.',
      network: 'Barno could not reach BRB-Tech ID. Try again shortly.',
      config: 'SSO is misconfigured on the server. Contact an administrator.',
      failed: 'Sign-in through BRB-Tech ID failed. Try again.',
    },
  },
  link: {
    loading: 'Checking the link…',
    barnoAccount: 'Barno account',
    confirm: 'Connect',
    cancel: 'Cancel',
    openBarno: 'Open Barno',
  },
  slack: {
    title: 'Connect Slack',
    caption: 'Barno AI in Slack will work under your account',
    account: 'Slack account',
    unknown: 'The person who pressed the button in Slack',
    warning: 'Connect only if you pressed “Connect Barno AI account” in Slack yourself. If someone else sent you this link, close the page: their Slack would get access to your recordings and answers.',
    done: 'Connected. Go back to Slack and send your message again.',
    gone: 'This link has expired or was already used. Write to Barno AI in Slack again to get a new one.',
  },
  telegram: {
    title: 'Connect Telegram',
    caption: 'Barno in Telegram will work under your account',
    account: 'Telegram account',
    unknown: 'The person who tapped the button in Telegram',
    warning: 'Connect only if you tapped “Sign in with BRB-Tech ID” in Telegram yourself. If someone else sent you this link, close the page: their Telegram would get access to your HR and CRM answers.',
    done: 'Connected. Go back to Telegram — Barno opens by itself.',
    gone: 'This link has expired or was already used. Open Barno in Telegram and tap the button again.',
  },
  desktop: {
    title: 'Desktop app',
  },
}

const uz: Mirror<typeof en> = {
  auth: {
    caption: 'HRM / CRM hisobingiz bilan',
    wrongCredentials: 'Login yoki parol notoʻgʻri.',
    blocked: 'Hisob bloklangan. Administratorga murojaat qiling.',
    accountSetup: 'Parol toʻgʻri, lekin hisobda tugallanmagan qadam bor: CRM saytiga brauzerda bir marta kiring va qayta urinib koʻring.',
    openCrm: 'CRM ni ochish',
    network: 'Barno bilan aloqa yoʻq. Internetni tekshiring.',
    unavailable: 'Barno vaqtincha ishlamayapti. Birozdan soʻng urinib koʻring.',
    sso: {
      button: 'BRB-Tech ID bilan kirish',
      caption: 'Barcha BRB-Tech tizimlari uchun bitta korporativ hisob',
      redirecting: 'BRB-Tech ID kirish sahifasi ochilmoqda…',
      finishing: 'Kirish yakunlanmoqda…',
      or: 'yoki mahalliy hisob bilan',
      denied: 'Kirish BRB-Tech ID sahifasida bekor qilindi.',
      blocked: 'Bu hisob Barno’da bloklangan. Administratorga murojaat qiling.',
      expired: 'Kirish juda uzoq davom etdi yoki allaqachon ishlatilgan. Qayta urinib koʻring.',
      network: 'Barno BRB-Tech ID bilan bogʻlana olmadi. Birozdan soʻng urinib koʻring.',
      config: 'SSO serverda notoʻgʻri sozlangan. Administratorga murojaat qiling.',
      failed: 'BRB-Tech ID orqali kirish amalga oshmadi. Qayta urinib koʻring.',
    },
  },
  link: {
    loading: 'Havola tekshirilmoqda…',
    barnoAccount: 'Barno hisobi',
    confirm: 'Ulash',
    cancel: 'Bekor qilish',
    openBarno: 'Barno’ni ochish',
  },
  slack: {
    title: 'Slack’ni ulash',
    caption: 'Slack’dagi Barno AI sizning hisobingiz nomidan ishlaydi',
    account: 'Slack hisobi',
    unknown: 'Slack’da tugmani bosgan odam',
    warning: 'Faqat Slack’da «Connect Barno AI account» tugmasini oʻzingiz bosgan boʻlsangiz ulang. Bu havolani sizga boshqa odam yuborgan boʻlsa, sahifani yoping: uning Slack’i sizning yozuvlaringiz va javoblaringizga kira oladi.',
    done: 'Ulandi. Slack’ga qayting va xabaringizni qayta yuboring.',
    gone: 'Havola eskirgan yoki allaqachon ishlatilgan. Yangisini olish uchun Slack’da Barno AI ga qayta yozing.',
  },
  telegram: {
    title: 'Telegram’ni ulash',
    caption: 'Telegram’dagi Barno sizning hisobingiz nomidan ishlaydi',
    account: 'Telegram hisobi',
    unknown: 'Telegram’da tugmani bosgan odam',
    warning: 'Faqat Telegram’da «BRB-Tech ID bilan kirish» tugmasini oʻzingiz bosgan boʻlsangiz ulang. Bu havolani sizga boshqa odam yuborgan boʻlsa, sahifani yoping: uning Telegram’i sizning HR va CRM javoblaringizga kira oladi.',
    done: 'Ulandi. Telegram’ga qayting — Barno oʻzi ochiladi.',
    gone: 'Havola eskirgan yoki allaqachon ishlatilgan. Telegram’da Barno’ni ochib, tugmani qayta bosing.',
  },
  desktop: {
    title: 'Desktop ilova',
  },
}

const uzCyrl: Mirror<typeof en> = {
  auth: {
    caption: 'HRM / CRM ҳисобингиз билан',
    wrongCredentials: 'Логин ёки парол нотўғри.',
    blocked: 'Ҳисоб блокланган. Администраторга мурожаат қилинг.',
    accountSetup: 'Парол тўғри, лекин ҳисобда тугалланмаган қадам бор: CRM сайтига браузерда бир марта киринг ва қайта уриниб кўринг.',
    openCrm: 'CRM ни очиш',
    network: 'Барно билан алоқа йўқ. Интернетни текширинг.',
    unavailable: 'Барно вақтинча ишламаяпти. Бироздан сўнг уриниб кўринг.',
    sso: {
      button: 'BRB-Tech ID билан кириш',
      caption: 'Барча BRB-Tech тизимлари учун битта корпоратив ҳисоб',
      redirecting: 'BRB-Tech ID кириш саҳифаси очилмоқда…',
      finishing: 'Кириш якунланмоқда…',
      or: 'ёки маҳаллий ҳисоб билан',
      denied: 'Кириш BRB-Tech ID саҳифасида бекор қилинди.',
      blocked: 'Бу ҳисоб Барнода блокланган. Администраторга мурожаат қилинг.',
      expired: 'Кириш жуда узоқ давом этди ёки аллақачон ишлатилган. Қайта уриниб кўринг.',
      network: 'Барно BRB-Tech ID билан боғлана олмади. Бироздан сўнг уриниб кўринг.',
      config: 'SSO серверда нотўғри созланган. Администраторга мурожаат қилинг.',
      failed: 'BRB-Tech ID орқали кириш амалга ошмади. Қайта уриниб кўринг.',
    },
  },
  link: {
    loading: 'Ҳавола текширилмоқда…',
    barnoAccount: 'Барно ҳисоби',
    confirm: 'Улаш',
    cancel: 'Бекор қилиш',
    openBarno: 'Барнони очиш',
  },
  slack: {
    title: 'Slack’ни улаш',
    caption: 'Slack’даги Barno AI сизнинг ҳисобингиз номидан ишлайди',
    account: 'Slack ҳисоби',
    unknown: 'Slack’да тугмани босган одам',
    warning: 'Фақат Slack’да «Connect Barno AI account» тугмасини ўзингиз босган бўлсангиз уланг. Бу ҳаволани сизга бошқа одам юборган бўлса, саҳифани ёпинг: унинг Slack’и сизнинг ёзувларингиз ва жавобларингизга кира олади.',
    done: 'Уланди. Slack’га қайтинг ва хабарингизни қайта юборинг.',
    gone: 'Ҳавола эскирган ёки аллақачон ишлатилган. Янгисини олиш учун Slack’да Barno AI га қайта ёзинг.',
  },
  telegram: {
    title: 'Telegram’ни улаш',
    caption: 'Telegram’даги Барно сизнинг ҳисобингиз номидан ишлайди',
    account: 'Telegram ҳисоби',
    unknown: 'Telegram’да тугмани босган одам',
    warning: 'Фақат Telegram’да «BRB-Tech ID билан кириш» тугмасини ўзингиз босган бўлсангиз уланг. Бу ҳаволани сизга бошқа одам юборган бўлса, саҳифани ёпинг: унинг Telegram’и сизнинг HR ва CRM жавобларингизга кира олади.',
    done: 'Уланди. Telegram’га қайтинг — Барно ўзи очилади.',
    gone: 'Ҳавола эскирган ёки аллақачон ишлатилган. Telegram’да Барнони очиб, тугмани қайта босинг.',
  },
  desktop: {
    title: 'Десктоп илова',
  },
}

const ru: Mirror<typeof en> = {
  auth: {
    caption: 'Учётная запись HRM / CRM',
    wrongCredentials: 'Неверный логин или пароль.',
    blocked: 'Учётная запись заблокирована. Обратитесь к администратору.',
    accountSetup: 'Пароль верный, но в учётной записи есть незавершённый шаг: один раз войдите в CRM через браузер и повторите попытку.',
    openCrm: 'Открыть CRM',
    network: 'Нет связи с сервером. Проверьте подключение.',
    unavailable: 'Сервис временно недоступен. Попробуйте чуть позже.',
    sso: {
      button: 'Войти через BRB-Tech ID',
      caption: 'Одна корпоративная учётная запись для всех систем BRB-Tech',
      redirecting: 'Открываем страницу входа BRB-Tech ID…',
      finishing: 'Завершаем вход…',
      or: 'или локальная учётная запись',
      denied: 'Вход отменён на странице BRB-Tech ID.',
      blocked: 'Эта учётная запись заблокирована в Barno. Обратитесь к администратору.',
      expired: 'Вход занял слишком много времени или уже был использован. Попробуйте снова.',
      network: 'Barno не удалось связаться с BRB-Tech ID. Попробуйте чуть позже.',
      config: 'SSO неверно настроен на сервере. Обратитесь к администратору.',
      failed: 'Вход через BRB-Tech ID не удался. Попробуйте снова.',
    },
  },
  link: {
    loading: 'Проверяем ссылку…',
    barnoAccount: 'Учётная запись Barno',
    confirm: 'Подключить',
    cancel: 'Отмена',
    openBarno: 'Открыть Barno',
  },
  slack: {
    title: 'Подключение Slack',
    caption: 'Barno AI в Slack будет работать от имени вашей учётной записи',
    account: 'Аккаунт Slack',
    unknown: 'Тот, кто нажал кнопку в Slack',
    warning: 'Подключайте, только если вы сами нажали «Connect Barno AI account» в Slack. Если эту ссылку вам прислал кто-то другой, закройте страницу: его Slack получит доступ к вашим записям и ответам.',
    done: 'Подключено. Вернитесь в Slack и отправьте сообщение ещё раз.',
    gone: 'Ссылка устарела или уже использована. Напишите Barno AI в Slack ещё раз, чтобы получить новую.',
  },
  telegram: {
    title: 'Подключение Telegram',
    caption: 'Барно в Telegram будет работать от имени вашей учётной записи',
    account: 'Аккаунт Telegram',
    unknown: 'Тот, кто нажал кнопку в Telegram',
    warning: 'Подключайте, только если вы сами нажали «Войти через BRB-Tech ID» в Telegram. Если эту ссылку вам прислал кто-то другой, закройте страницу: его Telegram получит доступ к вашим ответам по HR и CRM.',
    done: 'Подключено. Вернитесь в Telegram — Барно откроется само.',
    gone: 'Ссылка устарела или уже использована. Откройте Барно в Telegram и нажмите кнопку ещё раз.',
  },
  desktop: {
    title: 'Приложение для ПК',
  },
}

export const shell = { en, uz, 'uz-Cyrl': uzCyrl, ru }
