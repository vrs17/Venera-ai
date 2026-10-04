// Foydalanuvchi amallari xatolari -> bitta tushunarli jumla (sahifa tilida).
//
// Backend himoyalari (409) matnni O'ZBEKCHA qaytaradi va mashina kodi javobga
// chiqmaydi (`services/admin_users.py`: SELF_DEMOTE, SELF_BLOCK, BOOTSTRAP_LOCKED,
// LAST_ADMIN). Shuning uchun barqaror bo'laklarini taniymiz va o'z matnimizni
// ko'rsatamiz; tanilmagani - server matni (to'g'ri o'zbekcha matn noto'g'ri
// tarjimadan yaxshiroq), u ham bo'lmasa - umumiy "Saqlab bo'lmadi".

import { ApiError } from '../../api/http'

type Translate = (key: string) => string

export function userActionError(err: unknown, t: Translate): string {
  if (!(err instanceof ApiError)) return t('admin.toast.failed')
  const raw = (err.body?.message || '').trim()
  const m = raw.toLowerCase()
  if (err.status === 409 || err.status === 422) {
    if (m.includes('admin rolini')) return t('admin.error.selfAdmin')
    // Apostrof turi (' ʻ ’) muhim emas - so'zning qolgani yetarli.
    if (m.includes('zingizni bloklab')) return t('admin.users.selfBlock')
    if (m.includes('admin_logins')) return t('admin.users.lockedBlock')
    if (m.includes('oxirgi administrator')) return t('admin.error.lastAdmin')
    if (m.includes('rol:')) return t('admin.users.unknownRole')
  }
  if (err.status === 403) return t('admin.error.forbidden')
  if (err.status === 404) return t('admin.error.notFound')
  // 5xx (ombor yozilmadi, nginx) - server matni texnik, bizniki aniqroq.
  if (!err.status || err.status >= 500 || !raw || /^request failed/i.test(raw)) return t('admin.toast.failed')
  return raw
}
