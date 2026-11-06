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
  desktop: {
    title: 'Приложение для ПК',
  },
}

export const shell = { en, uz, 'uz-Cyrl': uzCyrl, ru }
