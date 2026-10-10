// `tools.*` - jonli so'rov asboblarining ODAMGA tushunarli nomlari ("Bugungi kechikish",
// "Vazifa maʼlumoti"). Web chat, Mini App va (kelajakda) boshqa yuzalar uchun BITTA lug'at.
//
// NEGA UMUMIY (2026-10-10, UX ko'rigi): avval bu lug'at faqat Mini App'da (`tg.tools`) edi,
// web esa xom asbob nomini ko'rsatardi ("DWH · Branch kpi", "Biznes 24/7 · Kpi"). Endi
// ikkala yuzada bitta qoida (`components/chat/sources.ts` `lookupTitle`): tarjimasi bor
// asbob - "CRM · Vazifa maʼlumoti", yo'q - faqat platforma nomi ("DWH"), natija qisqasi
// (`digest`) ostida. Xom nom (slug) foydalanuvchiga HECH QACHON ko'rinmaydi - u admin izida.
//
// Yangi asbob (DWH, Biznes 24/7, Superapp...) - agent jamoasi aniq nomlarni bergach shu
// yerga bitta qator (4 tilda). `en` - kalitlar manbai, qolganlari `Mirror<typeof en>`.

import type { Mirror } from './ui'

const en = {
  hrm_vacation_balance: 'Vacation balance',
  hrm_today_late: 'Today’s lateness',
  hrm_month_attendance: 'Monthly attendance',
  hrm_schedule: 'Work schedule',
  hrm_payslip: 'Payslip',
  hrm_payslip_last: 'Latest payslip',
  hrm_payroll_schedule: 'Pay dates',
  hrm_leave_history: 'Leave history',
  hrm_employee: 'Employee info',
  hrm_employee_profile: 'Your profile',
  hrm_employee_search: 'Employee search',
  hrm_department_leaves: 'Team leave',
  crm_my_issues: 'My tasks',
  crm_issue_get: 'Task details',
  crm_issue_status: 'Task status',
  crm_create_issue: 'New task',
  crm_project_get: 'Project details',
  crm_customer: 'Customer details',
  crm_customer_deals: 'Customer deals',
  crm_my_meetings: 'My meetings',
}

const uz: Mirror<typeof en> = {
  hrm_vacation_balance: 'Taʼtil qoldigʻi',
  hrm_today_late: 'Bugungi kechikish',
  hrm_month_attendance: 'Oylik davomat',
  hrm_schedule: 'Ish jadvali',
  hrm_payslip: 'Hisob-varaq',
  hrm_payslip_last: 'Oxirgi hisob-varaq',
  hrm_payroll_schedule: 'Maosh sanalari',
  hrm_leave_history: 'Taʼtillar tarixi',
  hrm_employee: 'Xodim maʼlumoti',
  hrm_employee_profile: 'Profilingiz',
  hrm_employee_search: 'Xodim qidiruvi',
  hrm_department_leaves: 'Boʻlim taʼtillari',
  crm_my_issues: 'Vazifalarim',
  crm_issue_get: 'Vazifa maʼlumoti',
  crm_issue_status: 'Vazifa holati',
  crm_create_issue: 'Yangi vazifa',
  crm_project_get: 'Loyiha maʼlumoti',
  crm_customer: 'Mijoz maʼlumoti',
  crm_customer_deals: 'Mijoz bitimlari',
  crm_my_meetings: 'Uchrashuvlarim',
}

const uzCyrl: Mirror<typeof en> = {
  hrm_vacation_balance: 'Таътил қолдиғи',
  hrm_today_late: 'Бугунги кечикиш',
  hrm_month_attendance: 'Ойлик давомат',
  hrm_schedule: 'Иш жадвали',
  hrm_payslip: 'Ҳисоб-варақ',
  hrm_payslip_last: 'Охирги ҳисоб-варақ',
  hrm_payroll_schedule: 'Маош саналари',
  hrm_leave_history: 'Таътиллар тарихи',
  hrm_employee: 'Ходим маълумоти',
  hrm_employee_profile: 'Профилингиз',
  hrm_employee_search: 'Ходим қидируви',
  hrm_department_leaves: 'Бўлим таътиллари',
  crm_my_issues: 'Вазифаларим',
  crm_issue_get: 'Вазифа маълумоти',
  crm_issue_status: 'Вазифа ҳолати',
  crm_create_issue: 'Янги вазифа',
  crm_project_get: 'Лойиҳа маълумоти',
  crm_customer: 'Мижоз маълумоти',
  crm_customer_deals: 'Мижоз битимлари',
  crm_my_meetings: 'Учрашувларим',
}

const ru: Mirror<typeof en> = {
  hrm_vacation_balance: 'Остаток отпуска',
  hrm_today_late: 'Опоздание сегодня',
  hrm_month_attendance: 'Посещаемость за месяц',
  hrm_schedule: 'График работы',
  hrm_payslip: 'Расчётный лист',
  hrm_payslip_last: 'Последний расчётный лист',
  hrm_payroll_schedule: 'Даты выплат',
  hrm_leave_history: 'История отпусков',
  hrm_employee: 'Данные сотрудника',
  hrm_employee_profile: 'Ваш профиль',
  hrm_employee_search: 'Поиск сотрудника',
  hrm_department_leaves: 'Отпуска отдела',
  crm_my_issues: 'Мои задачи',
  crm_issue_get: 'Данные задачи',
  crm_issue_status: 'Статус задачи',
  crm_create_issue: 'Новая задача',
  crm_project_get: 'Данные проекта',
  crm_customer: 'Данные клиента',
  crm_customer_deals: 'Сделки клиента',
  crm_my_meetings: 'Мои встречи',
}

export const tools = { en, uz, 'uz-Cyrl': uzCyrl, ru }

/** Nomi tarjimada bor asboblar. Boshqasi - faqat platforma nomi (xom nom emas). */
export const KNOWN_TOOLS: ReadonlySet<string> = new Set(Object.keys(en))
