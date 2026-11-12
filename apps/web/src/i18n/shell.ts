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
  slack: {
    title: 'Connect Slack',
    caption: 'Barno AI in Slack will work under your account',
    loading: 'Checking the link…',
    slackAccount: 'Slack account',
    slackUnknown: 'The person who pressed the button in Slack',
    barnoAccount: 'Barno account',
    warning: 'Connect only if you pressed “Connect Barno AI account” in Slack yourself. If someone else sent you this link, close the page: their Slack would get access to your recordings and answers.',
    confirm: 'Connect',
    cancel: 'Cancel',
    done: 'Connected. Go back to Slack and send your message again.',
    gone: 'This link has expired or was already used. Write to Barno AI in Slack again to get a new one.',
    openBarno: 'Open Barno',
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
  slack: {
    title: 'Slack’ni ulash',
    caption: 'Slack’dagi Barno AI sizning hisobingiz nomidan ishlaydi',
    loading: 'Havola tekshirilmoqda…',
    slackAccount: 'Slack hisobi',
    slackUnknown: 'Slack’da tugmani bosgan odam',
    barnoAccount: 'Barno hisobi',
    warning: 'Faqat Slack’da «Connect Barno AI account» tugmasini oʻzingiz bosgan boʻlsangiz ulang. Bu havolani sizga boshqa odam yuborgan boʻlsa, sahifani yoping: uning Slack’i sizning yozuvlaringiz va javoblaringizga kira oladi.',
    confirm: 'Ulash',
    cancel: 'Bekor qilish',
    done: 'Ulandi. Slack’ga qayting va xabaringizni qayta yuboring.',
    gone: 'Havola eskirgan yoki allaqachon ishlatilgan. Yangisini olish uchun Slack’da Barno AI ga qayta yozing.',
    openBarno: 'Barno’ni ochish',
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
  slack: {
    title: 'Slack’ни улаш',
    caption: 'Slack’даги Barno AI сизнинг ҳисобингиз номидан ишлайди',
    loading: 'Ҳавола текширилмоқда…',
    slackAccount: 'Slack ҳисоби',
    slackUnknown: 'Slack’да тугмани босган одам',
    barnoAccount: 'Барно ҳисоби',
    warning: 'Фақат Slack’да «Connect Barno AI account» тугмасини ўзингиз босган бўлсангиз уланг. Бу ҳаволани сизга бошқа одам юборган бўлса, саҳифани ёпинг: унинг Slack’и сизнинг ёзувларингиз ва жавобларингизга кира олади.',
    confirm: 'Улаш',
    cancel: 'Бекор қилиш',
    done: 'Уланди. Slack’га қайтинг ва хабарингизни қайта юборинг.',
    gone: 'Ҳавола эскирган ёки аллақачон ишлатилган. Янгисини олиш учун Slack’да Barno AI га қайта ёзинг.',
    openBarno: 'Барнони очиш',
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
  slack: {
    title: 'Подключение Slack',
    caption: 'Barno AI в Slack будет работать от имени вашей учётной записи',
    loading: 'Проверяем ссылку…',
    slackAccount: 'Аккаунт Slack',
    slackUnknown: 'Тот, кто нажал кнопку в Slack',
    barnoAccount: 'Учётная запись Barno',
    warning: 'Подключайте, только если вы сами нажали «Connect Barno AI account» в Slack. Если эту ссылку вам прислал кто-то другой, закройте страницу: его Slack получит доступ к вашим записям и ответам.',
    confirm: 'Подключить',
    cancel: 'Отмена',
    done: 'Подключено. Вернитесь в Slack и отправьте сообщение ещё раз.',
    gone: 'Ссылка устарела или уже использована. Напишите Barno AI в Slack ещё раз, чтобы получить новую.',
    openBarno: 'Открыть Barno',
  },
  desktop: {
    title: 'Приложение для ПК',
  },
}

export const shell = { en, uz, 'uz-Cyrl': uzCyrl, ru }
