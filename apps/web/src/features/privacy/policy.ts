/**
 * Barno AI maxfiylik siyosati - llm.brb-tech.uz/privacy (2026-11-19, Google Play uchun ochiq sahifa).
 *
 * MATN KODGA MOS bo'lishi shart (Play "Data safety" javoblari ham shundan): nima yig'iladi
 * (`apps/api` meetings, voice-sample, chat), kimga boradi (GAPI - nutq va ovoz izi, Anthropic/Ollama -
 * faqat matn), qancha saqlanadi (prod: muddatsiz, odam o'chirmaguncha - MEETINGS_RETENTION_DAYS=0),
 * ilova ruxsatlari (RECORD_AUDIO, FOREGROUND_SERVICE_MICROPHONE, POST_NOTIFICATIONS, READ_MEDIA_AUDIO).
 * Kod o'zgarsa (yangi xizmat, yangi ma'lumot turi) - shu matn ham, `UPDATED` ham yangilanadi.
 */

export type PolicyLang = 'uz' | 'ru' | 'en'

/** Murojaat manzili va operator nomi - nashrdan oldin ega tasdiqlaydi. */
export const CONTACT_EMAIL = 'ai@brb-tech.uz'
export const OPERATOR = 'BRB-Tech'
export const UPDATED = '2026-11-25'

export interface PolicySection {
  title: string
  paragraphs: string[]
}

export interface PolicyText {
  title: string
  updatedLabel: string
  intro: string
  sections: PolicySection[]
}

export const POLICY: Record<PolicyLang, PolicyText> = {
  uz: {
    title: 'Barno AI — maxfiylik siyosati',
    updatedLabel: 'Oxirgi yangilanish',
    intro:
      `Bu siyosat Barno AI mobil ilovasi va u bilan bog'liq Barno xizmatlariga (veb, Telegram bot, Slack) ` +
      `tegishli. Xizmat operatori — ${OPERATOR}. Ilova faqat ${OPERATOR} xodimlari va kompaniya ruxsat bergan ` +
      `foydalanuvchilar uchun: kirish korporativ BRB-Tech ID hisobi bilan.`,
    sections: [
      {
        title: '1. Qanday ma’lumot yig’iladi',
        paragraphs: [
          'Hisob ma’lumotlari: ism-familiya, login, ish emaili, xodim identifikatori va rol — BRB-Tech ID orqali kirganingizda. Kirish tokenlari telefonning himoyalangan xotirasida saqlanadi.',
          'Yozuvlar: ilovada yozilgan yoki yuklangan yig’ilish audiosi. Video yuklasangiz, undan faqat audio ajratib olinadi va video darhol o’chiriladi. Qo’ng’iroq yozuvlarini import qilish funksiyasini o’zingiz yoqsangiz — siz tanlagan qo’ng’iroq yozuvlari.',
          'Yozuvdan tayyorlangan matnlar: transkript, qisqa xulosa, vazifalar, bayonnoma, yozuv bo’yicha chatdagi savol va javoblar.',
          'Ovoz namunasi va ovoz izi: yig’ilishda spikerlarni ism bilan ko‘rsatish uchun. Bu biometrik ma’lumot; u faqat kompaniya roziligi asosida va xodim namuna bergandan keyin ishlatiladi.',
          'Yordamchiga bergan savollaringiz va javoblar. Kompaniyaning HR va CRM tizimlaridagi ma’lumotlar faqat sizning so’rovingiz bilan va sizning huquqlaringiz doirasida o’qiladi.',
          'Texnik ma’lumotlar: ilova versiyasi, qurilma modeli, so’rov vaqti va server jurnallari — xizmat ishlashi, xavfsizlik va xarajatlar hisobi uchun.',
          'Ilova reklama identifikatori, joylashuv, kontaktlar, SMS, qo’ng’iroqlar jurnali va rasmlarni yig’maydi.',
        ],
      },
      {
        title: '2. Ilova ruxsatlari',
        paragraphs: [
          'Mikrofon — yig’ilishni yozish va ovozli savollar uchun. Bildirishnoma va fondagi xizmat — ekran o’chiq bo’lsa ham yozuv davom etishi va bu haqda ko‘rinib turishi uchun. Audio fayllarni o’qish — faqat qo’ng’iroq yozuvlarini import qilish yoqilganda.',
        ],
      },
      {
        title: '3. Ma’lumot nima uchun ishlatiladi',
        paragraphs: [
          'Yozuvni matnga aylantirish; xulosa, vazifalar va bayonnoma tayyorlash; savollaringizga javob berish; spikerlarni tanish; xizmatni ishlatish, himoyalash va yaxshilash.',
          'Ma’lumotlar reklama uchun ishlatilmaydi va sotilmaydi.',
        ],
      },
      {
        title: '4. Ma’lumot kimga uzatiladi',
        paragraphs: [
          'GAPI (console.gapi.uz, O’zbekiston) — nutqni matnga aylantirish va spikerlarni ovozidan tanish: audio va ovoz namunalari shu xizmatga yuboriladi.',
          'Anthropic PBC (Claude, AQSh) va zarur hollarda Ollama (AQSh) — sun’iy intellekt modellari: transkript va savollarning MATNI asosida xulosa, bayonnoma va javoblar tayyorlanadi. Audio bu xizmatlarga yuborilmaydi.',
          `${OPERATOR} ichki tizimlari (HR, CRM) — siz so’ragan ma’lumot uchun. Qonunda belgilangan hollarda — vakolatli davlat organlari.`,
          'Boshqa uchinchi shaxslarga ma’lumot berilmaydi.',
        ],
      },
      {
        title: '5. Qayerda va qancha saqlanadi',
        paragraphs: [
          `Ma’lumotlar ${OPERATOR} nazoratidagi serverlarda (O’zbekiston) saqlanadi. Yozuvlar va ulardan tayyorlangan matnlar siz yoki kompaniya o’chirmaguncha saqlanadi.`,
          'Ovoz izi siz uni o’chirmaguncha yoki xodim kompaniyadan ketguncha saqlanadi. GAPI nutqni matnga aylantirish natijalarini 30 kungacha saqlaydi.',
          'Matnlar sun’iy intellekt xizmatlariga AQShga uzatiladi; ular ma’lumotni o’z siyosatiga ko‘ra qisqa muddat qayta ishlaydi.',
        ],
      },
      {
        title: '6. Xavfsizlik',
        paragraphs: [
          'Barcha ulanishlar HTTPS orqali shifrlanadi. Kirish faqat BRB-Tech ID bilan, ma’lumotlarga kirish rol bo’yicha cheklangan. Har bir foydalanuvchi faqat o’z yozuvlarini ko‘radi; vakolatli administratorlar xizmatni qo’llab-quvvatlash va sifat nazorati uchun so’rovlar jurnalini ko‘ra oladi.',
        ],
      },
      {
        title: '7. Sizning huquqlaringiz',
        paragraphs: [
          'Yozuvni ilovaning o’zida o’chirishingiz mumkin — audio, transkript, xulosa va bayonnoma birga o’chadi. Ovoz namunangizni «Ovozimni o’chirish» bilan o’chirasiz.',
          `Hisobingiz va unga bog’liq barcha ma’lumotlarni o’chirishni yoki ma’lumotlaringiz nusxasini ${CONTACT_EMAIL} manziliga yozib so’rashingiz mumkin. Hisoblar kompaniya tomonidan ochiladi, shuning uchun hisobni o’chirish shu murojaat orqali bajariladi.`,
        ],
      },
      {
        title: '8. Bolalar',
        paragraphs: ['Ilova 18 yoshdan kichiklar uchun mo’ljallanmagan va ulardan ataylab ma’lumot yig’maydi.'],
      },
      {
        title: '9. Claude va ChatGPT konnektori',
        paragraphs: [
          'Xohlasangiz, Barno ma’lumotlaringizni o’zingizning Claude (Anthropic) yoki ChatGPT (OpenAI) hisobingizga ulashingiz mumkin. Konnektor sukut bo’yicha o’chiq: siz BRB-Tech ID bilan kirib, qaysi modulga (hozir faqat Plaud yig’ilishlari, faqat o’qish) ruxsat berishni o’zingiz tanlaysiz.',
          'Ruxsat bersangiz, siz so’ragan ma’lumot (yig’ilishlar ro’yxati, xulosa, transkript, vazifalar) o’sha xizmatga uzatiladi va undan keyin uning maxfiylik siyosati amal qiladi. Shaxsiy rejalarda u xizmat sozlamalarida ma’lumotni model o’qitishga berishni o’chirishni tavsiya qilamiz.',
          'Biz faqat kim, qaysi ilova, qaysi vosita va qachon chaqirilganini jurnalga yozamiz — ma’lumotning o’zi jurnalga tushmaydi. Kirish tokenlari serverda faqat xesh ko’rinishida saqlanadi. Istalgan payt Barno → «Ulangan ilovalar» dan uzishingiz mumkin; uzilgan ilova darhol kira olmaydi.',
        ],
      },
      {
        title: '10. O’zgarishlar va aloqa',
        paragraphs: [
          'Siyosat o’zgarsa, yangi matn shu sahifada e’lon qilinadi va sana yangilanadi.',
          `Savollar uchun: ${CONTACT_EMAIL} (${OPERATOR}).`,
        ],
      },
    ],
  },
  ru: {
    title: 'Barno AI — политика конфиденциальности',
    updatedLabel: 'Последнее обновление',
    intro:
      `Эта политика относится к мобильному приложению Barno AI и связанным с ним сервисам Barno (веб, ` +
      `Telegram-бот, Slack). Оператор сервиса — ${OPERATOR}. Приложение предназначено только для сотрудников ` +
      `${OPERATOR} и пользователей, допущенных компанией: вход по корпоративной учётной записи BRB-Tech ID.`,
    sections: [
      {
        title: '1. Какие данные собираются',
        paragraphs: [
          'Данные учётной записи: имя и фамилия, логин, рабочий email, идентификатор сотрудника и роль — при входе через BRB-Tech ID. Токены входа хранятся в защищённом хранилище телефона.',
          'Записи: аудио встреч, записанное в приложении или загруженное. Если вы загружаете видео, из него извлекается только аудио, а видео сразу удаляется. Если вы сами включите импорт записей звонков — выбранные вами записи звонков.',
          'Тексты, подготовленные по записи: транскрипт, краткое резюме, задачи, протокол, вопросы и ответы в чате по записи.',
          'Образец голоса и голосовой отпечаток: чтобы показывать участников встречи по именам. Это биометрические данные; они используются только с согласия компании и после того, как сотрудник записал образец.',
          'Ваши вопросы ассистенту и ответы. Данные из HR- и CRM-систем компании читаются только по вашему запросу и в пределах ваших прав.',
          'Технические данные: версия приложения, модель устройства, время запроса и серверные журналы — для работы сервиса, безопасности и учёта затрат.',
          'Приложение не собирает рекламный идентификатор, местоположение, контакты, SMS, журнал звонков и фотографии.',
        ],
      },
      {
        title: '2. Разрешения приложения',
        paragraphs: [
          'Микрофон — для записи встреч и голосовых вопросов. Уведомления и фоновая служба — чтобы запись продолжалась при выключенном экране и это было видно. Чтение аудиофайлов — только при включённом импорте записей звонков.',
        ],
      },
      {
        title: '3. Для чего используются данные',
        paragraphs: [
          'Расшифровка записи в текст; подготовка резюме, задач и протокола; ответы на ваши вопросы; распознавание участников; работа, защита и улучшение сервиса.',
          'Данные не используются для рекламы и не продаются.',
        ],
      },
      {
        title: '4. Кому передаются данные',
        paragraphs: [
          'GAPI (console.gapi.uz, Узбекистан) — распознавание речи и участников по голосу: в этот сервис отправляются аудио и образцы голоса.',
          'Anthropic PBC (Claude, США) и при необходимости Ollama (США) — модели искусственного интеллекта: по ТЕКСТУ транскрипта и вопросов готовятся резюме, протоколы и ответы. Аудио в эти сервисы не отправляется.',
          `Внутренние системы ${OPERATOR} (HR, CRM) — для запрошенных вами данных. В случаях, предусмотренных законом, — уполномоченные государственные органы.`,
          'Другим третьим лицам данные не передаются.',
        ],
      },
      {
        title: '5. Где и сколько хранятся данные',
        paragraphs: [
          `Данные хранятся на серверах под контролем ${OPERATOR} (Узбекистан). Записи и подготовленные по ним тексты хранятся, пока их не удалите вы или компания.`,
          'Голосовой отпечаток хранится, пока вы его не удалите или пока сотрудник не покинет компанию. GAPI хранит результаты распознавания до 30 дней.',
          'Тексты передаются сервисам искусственного интеллекта в США; они обрабатывают данные кратковременно согласно своей политике.',
        ],
      },
      {
        title: '6. Безопасность',
        paragraphs: [
          'Все соединения шифруются по HTTPS. Вход — только через BRB-Tech ID, доступ к данным ограничен ролями. Каждый пользователь видит только свои записи; уполномоченные администраторы могут просматривать журнал запросов для поддержки и контроля качества.',
        ],
      },
      {
        title: '7. Ваши права',
        paragraphs: [
          'Запись можно удалить в самом приложении — вместе с аудио, транскриптом, резюме и протоколом. Образец голоса удаляется кнопкой «Удалить мой голос».',
          `Удалить учётную запись и все связанные данные или получить копию своих данных можно, написав на ${CONTACT_EMAIL}. Учётные записи создаёт компания, поэтому удаление выполняется по этому обращению.`,
        ],
      },
      {
        title: '8. Дети',
        paragraphs: ['Приложение не предназначено для лиц младше 18 лет и намеренно не собирает их данные.'],
      },
      {
        title: '9. Коннектор для Claude и ChatGPT',
        paragraphs: [
          'По желанию вы можете подключить свои данные Barno к своему аккаунту Claude (Anthropic) или ChatGPT (OpenAI). По умолчанию коннектор выключен: вы входите через BRB-Tech ID и сами выбираете, к какому модулю дать доступ (сейчас только встречи Plaud, только чтение).',
          'Если вы разрешите, запрошенные вами данные (список встреч, сводки, расшифровки, задачи) передаются этому сервису, и далее действует его политика конфиденциальности. На личных тарифах рекомендуем отключить в его настройках использование данных для обучения моделей.',
          'Мы записываем в журнал только кто, какое приложение, какой инструмент и когда вызвал — сами данные в журнал не попадают. Токены доступа хранятся на сервере только в виде хеша. Отключить можно в любой момент: Barno → «Подключённые приложения»; отключённое приложение сразу теряет доступ.',
        ],
      },
      {
        title: '10. Изменения и контакты',
        paragraphs: [
          'При изменении политики новый текст публикуется на этой странице, дата обновляется.',
          `Вопросы: ${CONTACT_EMAIL} (${OPERATOR}).`,
        ],
      },
    ],
  },
  en: {
    title: 'Barno AI — Privacy Policy',
    updatedLabel: 'Last updated',
    intro:
      `This policy covers the Barno AI mobile app and the related Barno services (web, Telegram bot, Slack). ` +
      `The service is operated by ${OPERATOR}. The app is only for ${OPERATOR} employees and users the company ` +
      `admits: you sign in with a corporate BRB-Tech ID account.`,
    sections: [
      {
        title: '1. What we collect',
        paragraphs: [
          'Account data: name, login, work email, employee ID and role — when you sign in with BRB-Tech ID. Sign-in tokens are kept in the phone’s secure storage.',
          'Recordings: meeting audio recorded in the app or uploaded. If you upload a video, only its audio is extracted and the video is deleted right away. If you turn on call-recording import yourself — the call recordings you choose.',
          'Text produced from a recording: transcript, short summary, tasks, minutes, and the questions and answers in the recording’s chat.',
          'Voice sample and voiceprint: used to show meeting speakers by name. This is biometric data; it is used only with the company’s consent and after the employee has recorded a sample.',
          'Your questions to the assistant and its answers. Data from the company’s HR and CRM systems is read only at your request and within your access rights.',
          'Technical data: app version, device model, request time and server logs — to run the service, keep it secure and account for costs.',
          'The app does not collect the advertising ID, location, contacts, SMS, call log or photos.',
        ],
      },
      {
        title: '2. App permissions',
        paragraphs: [
          'Microphone — to record meetings and voice questions. Notifications and a foreground service — so a recording continues with the screen off and stays visible. Reading audio files — only when call-recording import is turned on.',
        ],
      },
      {
        title: '3. How we use data',
        paragraphs: [
          'To transcribe recordings; prepare summaries, tasks and minutes; answer your questions; recognise speakers; and to operate, protect and improve the service.',
          'Data is not used for advertising and is never sold.',
        ],
      },
      {
        title: '4. Who receives data',
        paragraphs: [
          'GAPI (console.gapi.uz, Uzbekistan) — speech-to-text and speaker recognition: audio and voice samples are sent to this service.',
          'Anthropic PBC (Claude, USA) and, where needed, Ollama (USA) — AI models: summaries, minutes and answers are produced from the TEXT of transcripts and questions. Audio is not sent to these services.',
          `${OPERATOR} internal systems (HR, CRM) — for the data you ask about. Where the law requires it — competent authorities.`,
          'Data is not shared with any other third parties.',
        ],
      },
      {
        title: '5. Where and how long data is kept',
        paragraphs: [
          `Data is stored on servers controlled by ${OPERATOR} (Uzbekistan). Recordings and the text produced from them are kept until you or the company delete them.`,
          'A voiceprint is kept until you delete it or the employee leaves the company. GAPI keeps speech-to-text results for up to 30 days.',
          'Text is transferred to AI services in the USA; they process it briefly under their own policies.',
        ],
      },
      {
        title: '6. Security',
        paragraphs: [
          'All connections are encrypted with HTTPS. Sign-in is only through BRB-Tech ID, and access to data is limited by role. Each user sees only their own recordings; authorised administrators can view the request log for support and quality control.',
        ],
      },
      {
        title: '7. Your rights',
        paragraphs: [
          'You can delete a recording in the app — its audio, transcript, summary and minutes are deleted together. You delete your voice sample with «Delete my voice».',
          `To delete your account and all related data, or to get a copy of your data, write to ${CONTACT_EMAIL}. Accounts are created by the company, so account deletion is done through this request.`,
        ],
      },
      {
        title: '8. Children',
        paragraphs: ['The app is not intended for anyone under 18 and does not knowingly collect their data.'],
      },
      {
        title: '9. Claude and ChatGPT connector',
        paragraphs: [
          'If you choose, you can connect your Barno data to your own Claude (Anthropic) or ChatGPT (OpenAI) account. The connector is off by default: you sign in with BRB-Tech ID and choose which module to allow (currently Plaud meetings only, read only).',
          'If you allow it, the data you ask for (meeting list, summaries, transcripts, action items) is sent to that service, and its privacy policy applies from then on. On personal plans we recommend turning off the use of your data for model training in that service’s settings.',
          'We log only who called which tool from which app and when — never the data itself. Access tokens are stored on our server only as hashes. You can disconnect at any time in Barno → “Connected apps”; a disconnected app loses access immediately.',
        ],
      },
      {
        title: '10. Changes and contact',
        paragraphs: [
          'If this policy changes, the new text is published on this page with a new date.',
          `Questions: ${CONTACT_EMAIL} (${OPERATOR}).`,
        ],
      },
    ],
  },
}

/** Sahifa tili: global UI tilidan (uz, uz-Cyrl -> uz; ru; qolgani - en). */
export function policyLang(locale: string | null | undefined): PolicyLang {
  const value = (locale ?? '').toLowerCase()
  if (value.startsWith('ru')) return 'ru'
  if (value.startsWith('en')) return 'en'
  return 'uz'
}
