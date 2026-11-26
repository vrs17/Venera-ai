/**
 * Barno konnektori - ochiq qo'llanma (llm.brb-tech.uz/connector). Claude va ChatGPT
 * kataloglari "hujjat sahifasi" talab qiladi; xodimlar ham shu yerdan o'qiydi.
 * Shakl `features/privacy/policy.ts` niki (bitta sahifa komponenti - `PrivacyView.vue`).
 * Konnektor o'zgarsa (yangi modul, yangi vosita) - matn ham, `GUIDE_UPDATED` ham yangilanadi.
 */
import { OPERATOR, type PolicyLang, type PolicyText } from '../privacy/policy'

export const GUIDE_UPDATED = '2026-11-26'
/** Konnektor bo'yicha yordam manzili (ega bergan, 2026-11-26) - qo'llanma, shartlar va katalog arizalari. */
export const SUPPORT_EMAIL = 'y.mamajonov@brb-tech.uz'
export const TERMS_URL = 'https://llm.brb-tech.uz/connector/terms'
export const MCP_URL = 'https://llm.brb-tech.uz/mcp'

export const GUIDE: Record<PolicyLang, PolicyText> = {
  uz: {
    title: 'Barno konnektori — Claude va ChatGPT uchun',
    updatedLabel: 'Yangilangan',
    intro: 'Barno’dagi ma’lumotlaringizni o’zingizning Claude yoki ChatGPT hisobingizdan, istalgan joydan o’qing. Faqat BRB-Tech xodimlari uchun: kirish BRB-Tech ID bilan.',
    sections: [
      {
        title: '1. Nima o’qiy oladi',
        paragraphs: [
          'Hozir faqat Plaud moduli, faqat o’qish: yig’ilishlaringiz ro’yxati va qidiruv, xulosa, transkript, bayonnoma va vazifalar. Faqat O’ZINGIZNING yozuvlaringiz — boshqa xodimning yig’ilishi hech qachon ko’rinmaydi.',
          'Keyingi bosqichlarda CRM, HRM va Telegram guruhlari bittadan qo’shiladi; har biriga alohida ruxsat so’raladi.',
        ],
      },
      {
        title: '2. Claude’ga qo’shish',
        paragraphs: [
          `Claude → Settings → Connectors → «Add custom connector». Manzil: ${MCP_URL}. «Connect» ni bosing, BRB-Tech ID bilan kiring va Barno sahifasida modulni belgilab «Ruxsat berish» ni bosing.`,
          'Team va Enterprise rejalarda konnektorni tashkilot egasi bir marta qo’shadi, keyin har xodim o’z hisobi bilan ulanadi. Claude web, desktop, telefon va Claude Code’da ishlaydi.',
        ],
      },
      {
        title: '3. ChatGPT’ga qo’shish',
        paragraphs: [
          `ChatGPT → Settings → Apps & Connectors → «Create» (kerak bo’lsa avval Developer mode). Manzil: ${MCP_URL}, kirish turi OAuth. So’ng BRB-Tech ID bilan kiring va Barno sahifasida ruxsat bering.`,
          'ChatGPT’da maxsus konnektorlar Business, Enterprise va Edu rejalarida to’liq, Pro’da faqat o’qish uchun ishlaydi; hozircha faqat web’da.',
        ],
      },
      {
        title: '4. Maxfiylik',
        paragraphs: [
          'Siz so’ragan ma’lumot o’zingizning Claude yoki ChatGPT hisobingizga ketadi va undan keyin o’sha xizmatning siyosati amal qiladi. Shaxsiy rejada u xizmat sozlamalarida ma’lumotni model o’qitishga berishni o’chiring.',
          'Barno faqat kim, qaysi ilova, qaysi vosita va qachon chaqirilganini yozadi — ma’lumotning o’zi jurnalga tushmaydi. Batafsil: llm.brb-tech.uz/privacy.',
        ],
      },
      {
        title: '5. Uzish va yordam',
        paragraphs: [
          'Barno → hisob menyusi → «Ulangan ilovalar» → «Uzish». Uzilgan ilova darhol kira olmaydi.',
          `Savollar va yordam: ${SUPPORT_EMAIL} (${OPERATOR}). Foydalanish shartlari: ${TERMS_URL}.`,
        ],
      },
    ],
  },
  ru: {
    title: 'Коннектор Barno — для Claude и ChatGPT',
    updatedLabel: 'Обновлено',
    intro: 'Читайте свои данные из Barno в своём аккаунте Claude или ChatGPT, откуда угодно. Только для сотрудников BRB-Tech: вход через BRB-Tech ID.',
    sections: [
      {
        title: '1. Что доступно',
        paragraphs: [
          'Сейчас только модуль Plaud, только чтение: список и поиск ваших встреч, сводки, расшифровки, протоколы и задачи. Только ВАШИ записи — чужие встречи никогда не видны.',
          'На следующих этапах по одному добавятся CRM, HRM и группы Telegram; для каждого запрашивается отдельное разрешение.',
        ],
      },
      {
        title: '2. Подключить в Claude',
        paragraphs: [
          `Claude → Settings → Connectors → «Add custom connector». Адрес: ${MCP_URL}. Нажмите «Connect», войдите через BRB-Tech ID и на странице Barno отметьте модуль и нажмите «Разрешить».`,
          'На тарифах Team и Enterprise коннектор один раз добавляет владелец организации, затем каждый сотрудник подключается своим аккаунтом. Работает в Claude web, desktop, на телефоне и в Claude Code.',
        ],
      },
      {
        title: '3. Подключить в ChatGPT',
        paragraphs: [
          `ChatGPT → Settings → Apps & Connectors → «Create» (при необходимости сначала Developer mode). Адрес: ${MCP_URL}, тип входа OAuth. Затем войдите через BRB-Tech ID и дайте разрешение на странице Barno.`,
          'В ChatGPT собственные коннекторы полностью работают на тарифах Business, Enterprise и Edu, на Pro — только чтение; пока только в веб-версии.',
        ],
      },
      {
        title: '4. Конфиденциальность',
        paragraphs: [
          'Запрошенные вами данные уходят в ваш аккаунт Claude или ChatGPT, и далее действует политика этого сервиса. На личном тарифе отключите в его настройках использование данных для обучения моделей.',
          'Barno записывает только кто, какое приложение, какой инструмент и когда вызвал — сами данные в журнал не попадают. Подробнее: llm.brb-tech.uz/privacy.',
        ],
      },
      {
        title: '5. Отключение и поддержка',
        paragraphs: [
          'Barno → меню аккаунта → «Подключённые приложения» → «Отключить». Отключённое приложение сразу теряет доступ.',
          `Вопросы и поддержка: ${SUPPORT_EMAIL} (${OPERATOR}). Условия использования: ${TERMS_URL}.`,
        ],
      },
    ],
  },
  en: {
    title: 'Barno connector — for Claude and ChatGPT',
    updatedLabel: 'Updated',
    intro: 'Read your Barno data from your own Claude or ChatGPT account, from anywhere. For BRB-Tech staff only: sign-in with BRB-Tech ID.',
    sections: [
      {
        title: '1. What it can read',
        paragraphs: [
          'Currently the Plaud module only, read only: list and search your meetings, summaries, transcripts, minutes and action items. Only YOUR recordings — another employee’s meetings are never visible.',
          'CRM, HRM and Telegram groups will be added one by one in later stages; each asks for its own permission.',
        ],
      },
      {
        title: '2. Add it to Claude',
        paragraphs: [
          `Claude → Settings → Connectors → “Add custom connector”. URL: ${MCP_URL}. Press “Connect”, sign in with BRB-Tech ID, tick the module on the Barno page and press “Allow”.`,
          'On Team and Enterprise plans an organization owner adds the connector once; then each employee connects with their own account. Works in Claude on the web, desktop, mobile and in Claude Code.',
        ],
      },
      {
        title: '3. Add it to ChatGPT',
        paragraphs: [
          `ChatGPT → Settings → Apps & Connectors → “Create” (turn on Developer mode first if needed). URL: ${MCP_URL}, authentication OAuth. Then sign in with BRB-Tech ID and allow access on the Barno page.`,
          'In ChatGPT, custom connectors work fully on Business, Enterprise and Edu plans and read-only on Pro; currently on the web only.',
        ],
      },
      {
        title: '4. Privacy',
        paragraphs: [
          'The data you ask for goes to your own Claude or ChatGPT account, and that service’s policy applies from then on. On a personal plan, turn off the use of your data for model training in its settings.',
          'Barno logs only who called which tool from which app and when — never the data itself. Details: llm.brb-tech.uz/privacy.',
        ],
      },
      {
        title: '5. Disconnect and support',
        paragraphs: [
          'Barno → account menu → “Connected apps” → “Disconnect”. A disconnected app loses access immediately.',
          `Questions and support: ${SUPPORT_EMAIL} (${OPERATOR}). Terms of use: ${TERMS_URL}.`,
        ],
      },
    ],
  },
}
