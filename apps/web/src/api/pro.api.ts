// "Pro" byudjeti - faqat HTTP; holat `composables/usePro.ts` da.
//
// Kimlik SERVERDAN qo'yiladi (`venera:{actorId}`), brauzer `user_id`
// yubormaydi - aks holda birovning byudjetini ko'rish mumkin bo'lardi.
// Chegaralar ham shu yerdan keladi va QOTIRILMAYDI: ular rolga qarab
// o'zgaradi.
//
// `engine` - odam tanlagan versiya (`chat/engines` -> `selectable`). Berilsa
// `available` AYNAN shu versiya bo'yicha keladi: "Pro" tugmasi tanlovga ergashadi.
// Ruxsat etilmagan qiymatni server jimgina e'tiborsiz qoldiradi (o'z default'i).

import { apiFetch } from './http'
import type { ProQuota } from '../types'

export function proQuota(engine?: string | null): Promise<ProQuota> {
  const q = engine ? `?engine=${encodeURIComponent(engine)}` : ''
  return apiFetch<ProQuota>(`/api/v1/pro/quota${q}`)
}
