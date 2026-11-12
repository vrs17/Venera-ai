// `assistant.*` - Barno XOTIRASI va platforma nomlari (yordamchi 3.3, 2026-10-10). Web va
// Mini App bir xil matnni ishlatadi (Mini App umumiy i18n'ni oladi).
//
// `en` - kalitlar manbai; qolgan tillar `Mirror<typeof en>`: bitta kalit yetishmasa ham
// kompilyatsiya xatosi.
//
// USLUB. Xodim texnik emas: "xotira bandi", "item", "connector" yo'q - "Barno eslab qolgan
// narsa", "manba". O'chirish so'zi - "unutish" (chatdagi "... ni unut" bilan bir xil).
// Qaytarib bo'lmasligi doim aytiladi. Rus tilida Barno uchun o'tgan zamon fe'li yo'q
// ("запомнила/запомнил") - jinsiga bog'lanmaslik uchun neytral jumla.
// Brend nomlari (HRM, CRM) tarjima qilinmaydi. `platform.other` - eski javobdagi notanish
// tizim uchun umumiy nom (`components/chat/platforms.ts`): xom kalit odamga ko'rinmaydi.
//
// vue-i18n sintaksisi: `{x}` - o'rniga qo'yiladi; `|` - ko'plik (faqat inglizchada); `@` ishlatmang.

import type { Mirror } from './ui'

const en = {
  memory: {
    title: 'Memory',
    lead: 'What Barno remembers about you to answer better. Only you can see this list.',
    open: 'Memory',
    openHint: 'What Barno remembers about you',
    sourceUser: 'You asked to remember',
    sourceLearned: 'Learned from your questions',
    sourceRoutine: 'Learned from your CRM tasks',
    forget: 'Forget',
    forgetAria: 'Forget: {text}',
    forgetConfirm: 'Forget this?',
    forgetConfirmHint: 'Barno will stop using it. This can’t be undone.',
    forgetting: 'Forgetting…',
    forgotten: 'Forgotten',
    forgetFailed: 'Couldn’t forget it',
    forgetAll: 'Forget everything',
    forgetAllTitle: 'Forget everything?',
    forgetAllHint:
      'Barno will forget the one thing it remembers about you. Your chats stay. | Barno will forget all {n} things it remembers about you. Your chats stay.',
    forgetAllRoutines: 'Routines learned from your CRM tasks go too.',
    forgetAllAck: 'I understand this can’t be undone',
    forgetAllYes: 'Forget everything',
    forgotAll: 'Memory cleared',
    forgetAllFailed: 'Couldn’t clear memory',
    emptyTitle: 'Nothing remembered yet',
    emptyBody:
      'Barno can keep what you tell it — your branch, how you like answers — so you don’t have to repeat it. Just write in chat:',
    exampleRemember: 'Remember: I work at the Chilonzor branch',
    exampleForget: 'Forget my branch',
    tip: 'In chat you can also say “remember …” or “forget …”.',
    loadFailed: 'Couldn’t load memory',
    retry: 'Try again',
  },
  platform: {
    hrm: 'HRM',
    crm: 'CRM',
    other: 'Other source',
  },
  errors: {
    unavailable: 'Barno isn’t responding right now. Try again in a minute.',
    rateLimited: 'Too many requests. Wait a moment and try again.',
    network: 'No connection. Check the internet.',
    generic: 'Something went wrong. Try again.',
  },
}

const uz: Mirror<typeof en> = {
  memory: {
    title: 'Xotira',
    lead: 'Barno yaxshiroq javob berish uchun siz haqingizda eslab qolgan narsalar. Bu roʻyxatni faqat siz koʻrasiz.',
    open: 'Xotira',
    openHint: 'Barno siz haqingizda nimani eslab qolgan',
    sourceUser: 'Siz eslab qolishni soʻragansiz',
    sourceLearned: 'Savollaringizdan oʻrganilgan',
    sourceRoutine: 'CRM vazifalaringizdan oʻrganilgan',
    forget: 'Unutish',
    forgetAria: 'Unutish: {text}',
    forgetConfirm: 'Barno buni unutsinmi?',
    forgetConfirmHint: 'Barno endi buni eslamaydi va javoblarda ishlatmaydi. Buni qaytarib boʻlmaydi.',
    forgetting: 'Unutilmoqda…',
    forgotten: 'Unutildi',
    forgetFailed: 'Unutib boʻlmadi',
    forgetAll: 'Hammasini unutish',
    forgetAllTitle: 'Barno hammasini unutsinmi?',
    forgetAllHint: 'Barno siz haqingizda eslab qolgan {n} ta narsaning hammasini unutadi. Suhbatlar tarixi saqlanib qoladi.',
    forgetAllRoutines: 'CRM vazifalaringizdan oʻrganganlari ham unutiladi.',
    forgetAllAck: 'Tushundim, buni qaytarib boʻlmaydi',
    forgetAllYes: 'Hammasini unutish',
    forgotAll: 'Xotira tozalandi',
    forgetAllFailed: 'Xotirani tozalab boʻlmadi',
    emptyTitle: 'Barno hali hech narsani eslab qolmagan',
    emptyBody:
      'Barno siz aytgan narsani — filialingizni, javob qanday boʻlishini — eslab qoladi, qayta-qayta aytishingiz shart emas. Chatda shunchaki yozing:',
    exampleRemember: 'Eslab qol: men Chilonzor filialida ishlayman',
    exampleForget: 'Filialimni unut',
    tip: 'Chatda ham “eslab qol …” yoki “… ni unut” deb yozishingiz mumkin.',
    loadFailed: 'Xotirani yuklab boʻlmadi',
    retry: 'Qayta urinish',
  },
  platform: {
    hrm: 'HRM',
    crm: 'CRM',
    other: 'Boshqa manba',
  },
  errors: {
    unavailable: 'Barno hozir javob bermayapti. Birozdan soʻng urinib koʻring.',
    rateLimited: 'Soʻrovlar juda koʻp. Biroz kutib, qayta urinib koʻring.',
    network: 'Internet yoʻq. Ulanishni tekshiring.',
    generic: 'Nimadir xato ketdi. Qayta urinib koʻring.',
  },
}

const uzCyrl: Mirror<typeof en> = {
  memory: {
    title: 'Хотира',
    lead: 'Барно яхшироқ жавоб бериш учун сиз ҳақингизда эслаб қолган нарсалар. Бу рўйхатни фақат сиз кўрасиз.',
    open: 'Хотира',
    openHint: 'Барно сиз ҳақингизда нимани эслаб қолган',
    sourceUser: 'Сиз эслаб қолишни сўрагансиз',
    sourceLearned: 'Саволларингиздан ўрганилган',
    sourceRoutine: 'CRM вазифаларингиздан ўрганилган',
    forget: 'Унутиш',
    forgetAria: 'Унутиш: {text}',
    forgetConfirm: 'Барно буни унутсинми?',
    forgetConfirmHint: 'Барно энди буни эсламайди ва жавобларда ишлатмайди. Буни қайтариб бўлмайди.',
    forgetting: 'Унутилмоқда…',
    forgotten: 'Унутилди',
    forgetFailed: 'Унутиб бўлмади',
    forgetAll: 'Ҳаммасини унутиш',
    forgetAllTitle: 'Барно ҳаммасини унутсинми?',
    forgetAllHint: 'Барно сиз ҳақингизда эслаб қолган {n} та нарсанинг ҳаммасини унутади. Суҳбатлар тарихи сақланиб қолади.',
    forgetAllRoutines: 'CRM вазифаларингиздан ўрганганлари ҳам унутилади.',
    forgetAllAck: 'Тушундим, буни қайтариб бўлмайди',
    forgetAllYes: 'Ҳаммасини унутиш',
    forgotAll: 'Хотира тозаланди',
    forgetAllFailed: 'Хотирани тозалаб бўлмади',
    emptyTitle: 'Барно ҳали ҳеч нарсани эслаб қолмаган',
    emptyBody:
      'Барно сиз айтган нарсани — филиалингизни, жавоб қандай бўлишини — эслаб қолади, қайта-қайта айтишингиз шарт эмас. Чатда шунчаки ёзинг:',
    exampleRemember: 'Эслаб қол: мен Чилонзор филиалида ишлайман',
    exampleForget: 'Филиалимни унут',
    tip: 'Чатда ҳам “эслаб қол …” ёки “… ни унут” деб ёзишингиз мумкин.',
    loadFailed: 'Хотирани юклаб бўлмади',
    retry: 'Қайта уриниш',
  },
  platform: {
    hrm: 'HRM',
    crm: 'CRM',
    other: 'Бошқа манба',
  },
  errors: {
    unavailable: 'Барно ҳозир жавоб бермаяпти. Бироздан сўнг уриниб кўринг.',
    rateLimited: 'Сўровлар жуда кўп. Бироз кутиб, қайта уриниб кўринг.',
    network: 'Интернет йўқ. Уланишни текширинг.',
    generic: 'Нимадир хато кетди. Қайта уриниб кўринг.',
  },
}

const ru: Mirror<typeof en> = {
  memory: {
    title: 'Память',
    lead: 'Что Барно помнит о вас, чтобы отвечать точнее. Этот список видите только вы.',
    open: 'Память',
    openHint: 'Что Барно помнит о вас',
    sourceUser: 'Вы попросили запомнить',
    sourceLearned: 'Из ваших вопросов',
    sourceRoutine: 'Из ваших задач в CRM',
    forget: 'Забыть',
    forgetAria: 'Забыть: {text}',
    forgetConfirm: 'Забыть это?',
    forgetConfirmHint: 'Барно больше не будет это использовать. Отменить нельзя.',
    forgetting: 'Удаляем…',
    forgotten: 'Забыто',
    forgetFailed: 'Не удалось забыть',
    forgetAll: 'Забыть всё',
    forgetAllTitle: 'Забыть всё?',
    forgetAllHint: 'Барно забудет всё, что помнит о вас ({n} шт.). Чаты останутся.',
    forgetAllRoutines: 'Выводы из ваших задач в CRM тоже будут забыты.',
    forgetAllAck: 'Понимаю, это нельзя отменить',
    forgetAllYes: 'Забыть всё',
    forgotAll: 'Память очищена',
    forgetAllFailed: 'Не удалось очистить память',
    emptyTitle: 'Память пока пуста',
    emptyBody:
      'Барно может запомнить то, что вы скажете, — ваш филиал, каким должен быть ответ, — чтобы не повторять это каждый раз. Просто напишите в чате:',
    exampleRemember: 'Запомни: я работаю в филиале Чиланзар',
    exampleForget: 'Забудь мой филиал',
    tip: 'В чате можно написать «запомни …» или «забудь …».',
    loadFailed: 'Не удалось загрузить память',
    retry: 'Повторить',
  },
  platform: {
    hrm: 'HRM',
    crm: 'CRM',
    other: 'Другой источник',
  },
  errors: {
    unavailable: 'Барно сейчас не отвечает. Попробуйте через минуту.',
    rateLimited: 'Слишком много запросов. Подождите немного и попробуйте снова.',
    network: 'Нет соединения. Проверьте интернет.',
    generic: 'Что-то пошло не так. Попробуйте ещё раз.',
  },
}

export const assistant = { en, uz, 'uz-Cyrl': uzCyrl, ru }
