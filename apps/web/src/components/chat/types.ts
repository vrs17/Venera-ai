// Chat sahifasining ichki (faqat UI) turlari.
//
// `UIExchange` (src/types.ts) - umumiy shartnoma; bu yerda faqat chat ekrani uchun
// qo'shimchalar: backendning savol kaliti va "yarmida to'xtatilgan" belgisi.

import type { UIExchange } from '../../types'

export interface ChatExchange extends UIExchange {
  /** `X-Venera-Turn` - backend shu savolga bergan kalit (`turns.id`). Shikoyat
   *  (`/reports` turnId) va admin izi (`/admin/turns/:id`) shu bilan bog'lanadi.
   *  Tarixdan ochilgan suhbatlarda yo'q: server xabar bo'yicha kalit bermaydi. */
  turnId?: string | null
  /** Javob kela boshlagandan keyin "To'xtatish" bosildi: kelgan qism qoladi,
   *  ostida kichik "To'xtatildi" yozuvi turadi. */
  stopped?: boolean
}
