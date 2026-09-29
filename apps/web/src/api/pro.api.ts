// "Pro" byudjeti - faqat HTTP; holat `composables/usePro.ts` da.
//
// Kimlik SERVERDAN qo'yiladi (`venera:{actorId}`), brauzer `user_id`
// yubormaydi - aks holda birovning byudjetini ko'rish mumkin bo'lardi.
// Chegaralar ham shu yerdan keladi va QOTIRILMAYDI: ular rolga qarab
// o'zgaradi.

import { apiFetch } from './http'
import type { ProQuota } from '../types'

export function proQuota(): Promise<ProQuota> {
  return apiFetch<ProQuota>('/api/v1/pro/quota')
}
