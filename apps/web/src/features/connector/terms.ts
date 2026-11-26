/**
 * Barno konnektori - foydalanish shartlari (llm.brb-tech.uz/connector/terms, 2026-11-26). Claude va ChatGPT
 * kataloglari "Terms of use" manzilini talab qiladi; rozilik sahifasi (`ConnectView.vue`) ham shunga havola beradi.
 * Shakl `features/privacy/policy.ts` niki (bitta sahifa komponenti - `PrivacyView.vue`).
 *
 * MATN KODGA MOS bo'lishi shart: faqat o'qish (`plaud_tools.py`), daqiqasiga 60 chaqiruv (`mcp.RATE_LIMIT`),
 * jurnal 90 kun va matnsiz (`store.CALLS_KEEP`, `core.record_call`), hisob bloklansa yoki admin "hamma
 * sessiyalarni tugatsa" ruxsat bekor (`core.user_for_grant`, `admin_users` signout). Kod o'zgarsa - matn ham, `TERMS_UPDATED` ham yangilanadi.
 */
import { OPERATOR, type PolicyLang, type PolicyText } from '../privacy/policy'
import { SUPPORT_EMAIL } from './guide'

export const TERMS_UPDATED = '2026-11-26'

export const TERMS: Record<PolicyLang, PolicyText> = {
  uz: {
    title: 'Barno konnektori — foydalanish shartlari',
    updatedLabel: 'Yangilangan',
    intro:
      `Bu shartlar Barno konnektoriga tegishli: u Barno AI’dagi ma’lumotlaringizdan o’zingizning Claude (Anthropic) ` +
      `yoki ChatGPT (OpenAI) hisobingizda foydalanish imkonini beradi. Xizmat operatori — ${OPERATOR}. AI ilovani ` +
      `Barno’ga ulash orqali siz shu shartlarni qabul qilasiz. Ular Barno AI maxfiylik siyosati ` +
      `(llm.brb-tech.uz/privacy) va kompaniyangizning ichki qoidalari bilan birga amal qiladi.`,
    sections: [
      {
        title: '1. Kim foydalana oladi',
        paragraphs: [
          'Konnektor BRB-Tech xodimlari va kompaniya ruxsat bergan boshqa foydalanuvchilar uchun. Siz o’z BRB-Tech ID hisobingiz bilan kirasiz; hisobingizni boshqalarga bermang va ulanishingizdan boshqalar foydalanishiga yo’l qo’ymang.',
          'Kompaniya konnektorni hamma uchun yoki faqat sizning hisobingiz uchun istalgan vaqtda o’chirib qo’yishi mumkin.',
        ],
      },
      {
        title: '2. Konnektor nima qiladi',
        paragraphs: [
          'Hozirgi bosqichda u Barno’dagi o’zingizning yig’ilishlaringizni (Plaud va Barno yozuvchisi) faqat o’qish imkonini beradi: yig’ilishlar ro’yxati va qidiruv, xulosa, transkript, bayonnoma va vazifalar. U Barno’da hech narsa yaratmaydi, o’zgartirmaydi va o’chirmaydi.',
          'U faqat Barno’da o’zingiz ko’ra oladigan ma’lumotni ko’rsatadi. Boshqa odamlarning yig’ilishlari hech qachon qaytarilmaydi.',
          'Keyinroq yangi modullar (masalan, CRM yoki HRM) qo’shilishi mumkin. Har biri siz Barno ruxsat sahifasida tasdiqlamaguningizcha o’chiq turadi.',
        ],
      },
      {
        title: '3. Ruxsatingiz va uni qaytarib olish',
        paragraphs: [
          'Barno ruxsat sahifasida ulanishni tasdiqlamaguningizcha hech qanday ma’lumot berilmaydi; modullarni o’sha yerda tanlaysiz.',
          'Istalgan ilovani istalgan vaqtda uzishingiz mumkin: Barno → hisob menyusi → «Ulangan ilovalar» → «Uzish». Ilova darhol kira olmay qoladi. Barno hisobingiz bloklansa yoki administrator sizni barcha qurilmalardan chiqarsa, ruxsat avtomatik bekor bo’ladi.',
        ],
      },
      {
        title: '4. Uchinchi tomon AI xizmatlari',
        paragraphs: [
          'Claude va ChatGPT — BRB-Tech’ning emas, Anthropic va OpenAI kompaniyalarining xizmatlari. Yordamchi siz uchun Barno ma’lumotini o’qiganda, bu ma’lumot o’sha provayderga yuboriladi va siz u bilan tuzgan shartnoma hamda uning maxfiylik siyosati asosida qayta ishlanadi. BRB-Tech ular ma’lumotni qanday saqlashi yoki ishlatishini nazorat qilmaydi.',
          'Konnektordan faqat kompaniyangiz ruxsat bergan AI hisobi va sozlamalar bilan foydalaning. Shaxsiy rejada provayderga suhbatlaringizdan modelni o’qitish uchun foydalanishga ruxsat beruvchi sozlamani o’chiring.',
        ],
      },
      {
        title: '5. Sizning majburiyatlaringiz',
        paragraphs: [
          'Yig’ilishlarda kompaniya, hamkasblar va mijozlar haqida maxfiy ma’lumot bo’lishi mumkin. Uni AI yordamchiga faqat kompaniya qoidalari ruxsat bergan hollarda bering va yordamchining javoblariga ham asl ma’lumotga bo’lgandek ehtiyotkorlik bilan munosabatda bo’ling.',
          'Konnektordan qonun yoki kompaniya qoidalarini buzish, kirish cheklovlarini chetlab o’tish, xizmatni haddan tashqari yuklash yoki ma’lumotni ommaviy yig’ish uchun foydalanmang. Har bir ulanish uchun daqiqasiga 60 ta chaqiruv chegarasi bor.',
        ],
      },
      {
        title: '6. AI javoblari',
        paragraphs: [
          'Javoblarni siz tanlagan AI modeli tayyorlaydi va ular to’liq bo’lmasligi yoki xato bo’lishi mumkin. Muhim faktlarga tayanishdan oldin ularni Barno’dagi asl yig’ilish bilan solishtiring.',
        ],
      },
      {
        title: '7. Biz saqlaydigan yozuvlar',
        paragraphs: [
          'Xavfsizlik va audit uchun Barno har bir chaqiruvni yozib boradi: kim, qaysi ilova, qaysi vosita, qachon, muvaffaqiyatli bo’ldimi va javob hajmi. Yig’ilish mazmunining o’zi yozilmaydi. Bu yozuvlar 90 kun saqlanadi.',
        ],
      },
      {
        title: '8. Ishlash va o’zgarishlar',
        paragraphs: [
          'Konnektor ish uchun «boricha» taqdim etiladi. Biz uni o’zgartirishimiz, vaqtincha yoki butunlay to’xtatishimiz, shuningdek bu shartlarni yangilashimiz mumkin; eng so’nggi versiya sanasi yuqorida ko’rsatilgan. O’zgarishdan keyin konnektordan foydalanishda davom etsangiz, yangi shartlar amal qiladi.',
          'Shartlar yoki kompaniya qoidalari buzilsa yoki xizmatni himoya qilish uchun kirishni uzib qo’yishimiz mumkin.',
        ],
      },
      {
        title: '9. Javobgarlik va qonun',
        paragraphs: [
          'Qonun ruxsat bergan darajada BRB-Tech uchinchi tomon AI xizmatlari, AI modellari tayyorlagan javoblar yoki konnektordan shu shartlarga zid foydalanish natijasida yetgan zarar uchun javobgar emas.',
          'Bu shartlar O’zbekiston Respublikasi qonunlariga muvofiq tartibga solinadi.',
        ],
      },
      {
        title: '10. Aloqa',
        paragraphs: [`Savollar va yordam: ${SUPPORT_EMAIL} (${OPERATOR}).`],
      },
    ],
  },
  ru: {
    title: 'Коннектор Barno — условия использования',
    updatedLabel: 'Обновлено',
    intro:
      `Эти условия относятся к коннектору Barno: он позволяет пользоваться данными Barno AI из вашего собственного ` +
      `аккаунта Claude (Anthropic) или ChatGPT (OpenAI). Оператор сервиса — ${OPERATOR}. Подключая AI-приложение ` +
      `к Barno, вы принимаете эти условия. Они действуют вместе с политикой конфиденциальности Barno AI ` +
      `(llm.brb-tech.uz/privacy) и внутренними правилами вашей компании.`,
    sections: [
      {
        title: '1. Кто может пользоваться',
        paragraphs: [
          'Коннектор предназначен для сотрудников BRB-Tech и других пользователей, которым компания дала доступ. Вы входите со своей учётной записью BRB-Tech ID; не передавайте её другим и не позволяйте другим пользоваться вашим подключением.',
          'Компания может в любой момент отключить коннектор для всех или только для вашей учётной записи.',
        ],
      },
      {
        title: '2. Что делает коннектор',
        paragraphs: [
          'На текущем этапе он даёт доступ только для чтения к вашим собственным встречам в Barno (Plaud и диктофон Barno): список встреч и поиск, резюме, расшифровки, протоколы и задачи. Он ничего не создаёт, не изменяет и не удаляет в Barno.',
          'Он показывает только те данные, которые вы и так видите в Barno. Чужие встречи никогда не возвращаются.',
          'Позже могут появиться новые модули (например, CRM или HRM). Каждый остаётся выключенным, пока вы не подтвердите его на странице разрешений Barno.',
        ],
      },
      {
        title: '3. Ваше разрешение и его отзыв',
        paragraphs: [
          'До подтверждения подключения на странице разрешений Barno никакие данные не передаются; там же вы выбираете модули.',
          'Вы можете отключить любое приложение в любой момент: Barno → меню аккаунта → «Подключённые приложения» → «Отключить». Приложение сразу теряет доступ. Доступ также отзывается автоматически, если ваша учётная запись Barno заблокирована или администратор завершил все ваши сеансы.',
        ],
      },
      {
        title: '4. Сторонние AI-сервисы',
        paragraphs: [
          'Claude и ChatGPT — сервисы компаний Anthropic и OpenAI, а не BRB-Tech. Когда ассистент читает для вас данные Barno, они передаются этому провайдеру и обрабатываются по вашему договору с ним и его политике конфиденциальности. BRB-Tech не контролирует, как провайдер их хранит и использует.',
          'Используйте коннектор только с тем AI-аккаунтом и настройками, которые разрешает ваша компания. На личном тарифе отключите настройку, позволяющую провайдеру обучать модели на ваших переписках.',
        ],
      },
      {
        title: '5. Ваши обязанности',
        paragraphs: [
          'Встречи могут содержать конфиденциальную информацию о компании, коллегах и клиентах. Передавайте её AI-ассистенту только тогда, когда это разрешают правила компании, и относитесь к ответам ассистента так же бережно, как к исходным данным.',
          'Не используйте коннектор для нарушения закона или правил компании, обхода ограничений доступа, чрезмерной нагрузки на сервис или массового сбора данных. Действует лимит 60 вызовов в минуту на одно подключение.',
        ],
      },
      {
        title: '6. Ответы AI',
        paragraphs: [
          'Ответы формирует выбранная вами AI-модель, и они могут быть неполными или ошибочными. Прежде чем полагаться на важные факты, сверяйте их с исходной встречей в Barno.',
        ],
      },
      {
        title: '7. Какие записи мы храним',
        paragraphs: [
          'Для безопасности и аудита Barno записывает каждый вызов: кто, какое приложение, какой инструмент, когда, успешно ли и размер ответа. Само содержание встреч не записывается. Эти записи хранятся 90 дней.',
        ],
      },
      {
        title: '8. Работа сервиса и изменения',
        paragraphs: [
          'Коннектор предоставляется для работы «как есть». Мы можем изменить его, приостановить или прекратить, а также обновить эти условия; дата последней версии указана вверху. Если вы продолжаете пользоваться коннектором после изменений, действуют новые условия.',
          'Мы можем отключить доступ при нарушении этих условий или правил компании либо для защиты сервиса.',
        ],
      },
      {
        title: '9. Ответственность и право',
        paragraphs: [
          'В пределах, допустимых законом, BRB-Tech не отвечает за убытки, вызванные сторонними AI-сервисами, ответами AI-моделей или использованием коннектора в нарушение этих условий.',
          'Эти условия регулируются законодательством Республики Узбекистан.',
        ],
      },
      {
        title: '10. Контакты',
        paragraphs: [`Вопросы и поддержка: ${SUPPORT_EMAIL} (${OPERATOR}).`],
      },
    ],
  },
  en: {
    title: 'Barno connector — terms of use',
    updatedLabel: 'Updated',
    intro:
      `These terms cover the Barno connector, which lets you use your Barno AI data from your own Claude (Anthropic) ` +
      `or ChatGPT (OpenAI) account. The service is operated by ${OPERATOR}. By connecting an AI app to Barno you ` +
      `accept these terms. They apply together with the Barno AI privacy policy (llm.brb-tech.uz/privacy) and your ` +
      `company’s internal rules.`,
    sections: [
      {
        title: '1. Who can use it',
        paragraphs: [
          'The connector is for BRB-Tech employees and other users the company has authorised. You sign in with your own BRB-Tech ID account; do not share your account or let others use your connection.',
          'The company may switch the connector off for everyone, or for your account only, at any time.',
        ],
      },
      {
        title: '2. What the connector does',
        paragraphs: [
          'At this stage it gives read-only access to your own meetings in Barno (Plaud and the Barno recorder): the meeting list and search, summaries, transcripts, minutes and action items. It cannot create, change or delete anything in Barno.',
          'It only shows data you can already see in Barno. Other people’s meetings are never returned.',
          'New modules (for example CRM or HRM) may be added later. Each stays off until you approve it on the Barno permission screen.',
        ],
      },
      {
        title: '3. Your permission and how to withdraw it',
        paragraphs: [
          'No data is shared until you approve a connection on the Barno permission screen, where you also choose the modules.',
          'You can disconnect any app at any time: Barno → account menu → “Connected apps” → “Disconnect”. The app loses access immediately. Access is also removed automatically if your Barno account is blocked or an administrator signs you out of all devices.',
        ],
      },
      {
        title: '4. Third-party AI services',
        paragraphs: [
          'Claude and ChatGPT are services of Anthropic and OpenAI, not of BRB-Tech. When the assistant reads Barno data for you, that data is sent to the provider and handled under your agreement with them and their privacy policy. BRB-Tech does not control how the provider stores or uses it.',
          'Use the connector only with an AI account and settings your company allows. On a personal plan, turn off the setting that lets the provider use your conversations to train its models.',
        ],
      },
      {
        title: '5. Your responsibilities',
        paragraphs: [
          'Meetings may contain confidential information about the company, colleagues and clients. Share it with an AI assistant only when company rules allow it, and treat the assistant’s answers with the same care as the original data.',
          'Do not use the connector to break the law or company rules, to get around access controls, to overload the service or to collect data in bulk. Each connection is limited to 60 calls per minute.',
        ],
      },
      {
        title: '6. AI answers',
        paragraphs: [
          'Answers are produced by the AI model you chose and can be incomplete or wrong. Check important facts against the original meeting in Barno before relying on them.',
        ],
      },
      {
        title: '7. Records we keep',
        paragraphs: [
          'For security and audit, Barno records each call: who, which app, which tool, when, whether it succeeded and the size of the answer. The meeting content itself is not recorded. These records are kept for 90 days.',
        ],
      },
      {
        title: '8. Availability and changes',
        paragraphs: [
          'The connector is provided for work use “as is”. We may change, pause or stop it, and we may update these terms; the date at the top shows the latest version. If you keep using the connector after a change, the new terms apply.',
          'We may disconnect access if these terms or company rules are broken, or to protect the service.',
        ],
      },
      {
        title: '9. Liability and governing law',
        paragraphs: [
          'To the extent the law allows, BRB-Tech is not responsible for losses caused by third-party AI services, by answers produced by AI models, or by use of the connector against these terms.',
          'These terms are governed by the laws of the Republic of Uzbekistan.',
        ],
      },
      {
        title: '10. Contact',
        paragraphs: [`Questions and support: ${SUPPORT_EMAIL} (${OPERATOR}).`],
      },
    ],
  },
}
