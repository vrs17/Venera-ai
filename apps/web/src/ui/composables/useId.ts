import { getCurrentInstance, useId as vueUseId } from 'vue'

// DOM uchun barqaror, sahifada yagona id (aria-labelledby, aria-controls va h.k.).
//
// Nega Vue'ning o'zinikini o'raymiz: `useId()` faqat setup ichida ishlaydi va
// ilova prefiksi bilan `v-0` kabi qiymat beradi. Bu yerda o'qiladigan prefiks
// qo'shamiz (`v-select-v-3` - DevTools'da qaysi komponentniki ekani ko'rinadi) va
// setup'dan tashqarida chaqirilsa ham (masalan, composable ichida) hisoblagichga
// qaytamiz - id hech qachon bo'sh qolmasin.

let fallback = 0

export function useId(prefix = 'v'): string {
  const base = getCurrentInstance() ? vueUseId() : `x${++fallback}`
  // CSS selektor va `querySelector('#...')` da xavfsiz bo'lsin.
  return `${prefix}-${base}`.replace(/[^A-Za-z0-9_-]/g, '-')
}
