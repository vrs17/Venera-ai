// Yordamchi versiyasi - faqat HTTP; holat `composables/useEngines.ts` da.
//
// Kanal brauzer yuborgan `X-Venera-Client` sarlavhasidan (apiFetch - `web`), odam esa
// sessiyadan: brauzer `user_id` ham, kanal nomini tanada ham yubormaydi - aks holda
// birovga berilgan versiyani so'rab olish mumkin bo'lardi.

import { apiFetch } from './http'
import type { EngineChoice } from '../types'

export function chatEngines(signal?: AbortSignal): Promise<EngineChoice> {
  return apiFetch<EngineChoice>('/api/v1/chat/engines', { signal })
}
