// Sinov uchun boshlang'ich namunalar - har sinov turi o'z "qiyin" holatlari bilan
// (sana, vaqt, MChJ, loyiha kodi, telefon...), ya'ni bosish bilanoq bosqichlar
// nimani o'zgartirgani ko'rinadi. Bu MAZMUN (o'zbekcha), interfeys matni emas -
// shuning uchun i18n da emas. Hammasi o'ylab topilgan, haqiqiy odam ma'lumoti yo'q.

const GROUP = [
  "Aziz: Server xotirasi 92% ga yetdi, bugun 18:00 gacha tozalash kerak",
  "Dilnoza: DVSIB-266 vazifasini juma kuni topshiraman",
  "Aziz: Mijoz +998 90 123 45 67 raqamidan qo'ng'iroq qildi, shartnoma 25.10.2026 da tugaydi",
  "Bekzod: Kelishdik, men ertaga mijoz bilan gaplashaman",
].join('\n')

const MEETING = [
  "S1: Assalomu alaykum, bugun DVSIB loyihasi bo'yicha yig'ilish",
  "S2: Hisobotni tayyorladim, faqat moliya bo'limi ma'lumotlari yetishmayapti",
  "S1: Moliya bo'limidan ma'lumotni kim so'raydi",
  "S2: Men so'rayman, juma kungacha yuboraman",
  "S1: Yaxshi, unda keyingi hafta seshanba kuni taqdimot qilamiz",
  "S2: Kelishdik, taqdimotni ham men tayyorlayman",
  "S1: Server xarajatlari bo'yicha savol ochiq qoldi, uni keyingi yig'ilishda ko'ramiz",
].join('\n')

export const SAMPLES: Record<string, { text: string; question?: string }> = {
  stt: { text: '' },
  'tts-text': {
    text: "**Ta'til:** “BRB-TECH” MChJ da ish vaqti 09:00-18:00 [T1]. DVSIB loyihasi bo'yicha muddat 25.10.2026.",
  },
  'tts-speak': { text: "Salom! Men Barno. DVSIB loyihasi bo'yicha hisobot 25.10.2026 gacha tayyor bo'ladi." },
  wake: { text: 'Salom Barno' },
  hold: { text: "Ertaga ta'tilga chiqsam bo'ladimi?" },
  mask: { text: "Aliga qo'ng'iroq qiling: +998 90 123 45 67, pochta: ali" + '@' + 'misol.uz, karta 8600 1234 5678 9012' },
  agent: { text: '' },
  health: { text: '' },
  'brain:group_summary': { text: GROUP },
  'brain:group_ask': { text: GROUP, question: 'Shartnoma qachon tugaydi?' },
  'brain:brief_extract': { text: GROUP },
  'brain:brief_crm': { text: 'Dilnoza: DVSIB-266 vazifasini topshirish\nAziz: Server xotirasini tozalash' },
  'brain:meeting_summary': { text: MEETING },
  'brain:meeting_ask': { text: MEETING, question: "Moliya bo'limidan ma'lumotni kim so'raydi?" },
  'brain:hold_classify': { text: '', question: "Ertaga ta'tilga chiqsam bo'ladimi?" },
  'brain:group_crm': { text: GROUP, question: 'Shu yozishmadan vazifa taklif qil' },
  'brain:meeting_crm': { text: "Moliya bo'limidan ma'lumotni so'rash\nMen so'rayman, juma kungacha yuboraman" },
}

/** Miya funksiyalari: savol maydoni kerakmi, `execute` mumkinmi (backend 409 bilan bir xil). */
export const BRAIN: Record<string, { question: boolean; input: boolean; execute: boolean; kind?: boolean }> = {
  group_summary: { question: true, input: true, execute: true },
  group_ask: { question: true, input: true, execute: true },
  brief_extract: { question: false, input: true, execute: true, kind: true },
  brief_crm: { question: false, input: true, execute: false },
  meeting_summary: { question: false, input: true, execute: false },
  meeting_ask: { question: true, input: true, execute: false },
  hold_classify: { question: true, input: false, execute: true },
  group_crm: { question: true, input: true, execute: false },
  meeting_crm: { question: false, input: true, execute: false },
}
