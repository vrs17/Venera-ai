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
  },
  desktop: {
    title: 'Приложение для ПК',
  },
}

export const shell = { en, uz, 'uz-Cyrl': uzCyrl, ru }
