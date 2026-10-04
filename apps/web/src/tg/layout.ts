// Ilova ramkasining balandligi va klaviatura - CSS o'zgaruvchilari orqali.
//
// MUAMMO. Telegram WebView'da `100vh`/`100dvh` klaviaturani bilmaydi: iOS WebView'ni
// qisqartirmaydi (klaviatura ustiga chiqadi va sahifani suradi), Android esa
// qisqartiradi, lekin Telegram'ning ochilish animatsiyasi paytida balandlik har kadrda
// o'zgaradi. Natija - kompozer klaviatura ostida qoladi yoki "sakraydi".
//
// YECHIM. Ramka (`.tg-app`, styles.css) `position: fixed` va bo'yi = ko'rinadigan oyna:
//
//   --app-h   = min(visualViewport.height, Telegram viewportStableHeight)
//   --app-top = visualViewport.offsetTop (iOS klaviatura surgan masofa)
//
// `viewportStableHeight`, `viewportHeight` EMAS: ikkinchisi ochilish animatsiyasida
// tebranadi. visualViewport esa klaviaturani aytadi (ikkala platformada) - ikkalasining
// kichigi: klaviatura ochilganda ramka qisqaradi, Telegram animatsiyasi esa ramkani
// "silkitmaydi".
//
// KLAVIATURANI OLDINDAN BILISH. iOS WebView'da `visualViewport.resize` klaviatura
// animatsiyasi TUGAGANDAN keyin keladi: ~250 ms kompozer klaviatura ostida turadi, keyin
// "sakraydi". Shuning uchun matn maydoni fokus olgan ZAHOTI oxirgi marta o'lchangan
// klaviatura balandligi (shu kenglik uchun, localStorage) qo'llanadi va ramka
// klaviatura bilan BIR XIL egri chiziqda (iOS: 250 ms, cubic-bezier(.38,.7,.125,1))
// qisqaradi. Haqiqiy hodisa kelganda qiymat tuzatiladi va yangi o'lchov saqlanadi;
// kelmasa (jismoniy klaviatura, tashqi qurilma) - 700 ms dan keyin taxmin bekor.
// Yopilishda ham xuddi shunday: fokus ketdi - ramka darhol to'liq bo'yga qaytadi.
//
// `kb-open` sinfi: klaviatura ochiq - uy chizig'i uchun pastki bo'shliq kerak emas.
// U ramka balandligi bilan BIR kadrda qo'yiladi: aks holda avval ramka, keyin 34px
// bo'shliq - ikki alohida harakat ko'rinardi.

import { onViewportChange, viewportStableHeight } from './telegram'

/** Undan katta farq - klaviatura (manzil satri, panel o'zgarishi - kichikroq). */
const KEYBOARD_PX = 120
const CACHE_KEY = 'venera_tg_kb'
/** Taxmin qilingan holat shuncha vaqtda tasdiqlanmasa - bekor. */
const PREDICT_MS = 700
/** `kb-anim` (balandlik o'tishi) shuncha turadi - iOS klaviatura animatsiyasidan biroz uzun. */
const ANIM_MS = 320

let started = false
/** Shu yo'nalishdagi eng katta balandlik - klaviatura yopiq holat. */
let tallest = 0
let lastWidth = 0
let frame = 0
let predicting: 'open' | 'close' | null = null
let predictTimer = 0
let animTimer = 0

const touchScreen = (() => {
  try {
    return window.matchMedia('(pointer: coarse)').matches
  } catch {
    return false
  }
})()

function isEditable(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  return el.isContentEditable || el.matches('input:not([type="checkbox"]):not([type="radio"]):not([type="button"]), textarea, select')
}

function editableFocused(): boolean {
  return isEditable(document.activeElement)
}

/* ── Klaviatura balandligi keshi (kenglik bo'yicha: portret / albom alohida) ── */

function readCache(): Record<string, number> {
  try {
    const raw = JSON.parse(localStorage.getItem(CACHE_KEY) || '{}') as unknown
    return raw && typeof raw === 'object' ? (raw as Record<string, number>) : {}
  } catch {
    return {}
  }
}

function remember(px: number): void {
  const cache = readCache()
  const key = String(window.innerWidth)
  if (Math.abs((cache[key] ?? 0) - px) < 2) return
  cache[key] = px
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache))
  } catch {
    /* saqlanmaydi - keyingi safar yana o'lchanadi */
  }
}

/* ── Qo'llash ─────────────────────────────────────────────────────────────── */

/** Balandlik o'zgarishini silliq qiladi (faqat taxmin va uning tuzatilishi uchun -
 *  oddiy aylantirish/ochilish paytida ramka "suzib" yurmasin). */
function animate(): void {
  const root = document.documentElement
  root.classList.add('kb-anim')
  window.clearTimeout(animTimer)
  animTimer = window.setTimeout(() => root.classList.remove('kb-anim'), ANIM_MS)
}

function apply(height: number, top: number, visual: number, keyboard: boolean): void {
  const root = document.documentElement
  root.style.setProperty('--app-h', `${height}px`)
  root.style.setProperty('--app-top', `${top}px`)
  // Fixed elementlar (toast) layout viewport'ga bog'langan: iOS'da klaviatura ochiq
  // bo'lsa ular klaviatura ostida qoladi - shu farqqa ko'tariladi.
  const gap = Math.max(0, Math.round(window.innerHeight - (visual + top)))
  root.style.setProperty('--app-bottom-gap', `${gap}px`)
  root.classList.toggle('kb-open', keyboard)
}

function endPrediction(): void {
  if (!predicting) return
  predicting = null
  window.clearTimeout(predictTimer)
}

function sync(): void {
  frame = 0
  const vv = window.visualViewport
  const visual = vv ? vv.height : window.innerHeight
  const stable = viewportStableHeight()
  const height = Math.round(Math.min(visual, stable > 0 ? stable : visual))
  const top = vv ? Math.max(0, Math.round(vv.offsetTop)) : 0
  // Aylantirish (orientation) - kenglik o'zgardi, "eng katta" qaytadan o'lchanadi.
  if (window.innerWidth !== lastWidth) {
    lastWidth = window.innerWidth
    tallest = 0
  }
  const keyboard = tallest - height > KEYBOARD_PX && editableFocused()
  if (!keyboard) tallest = Math.max(tallest, height)

  // Taxmin hali tasdiqlanmagan: klaviatura hodisasi kelguncha taxminni bosib ketmaymiz.
  if (predicting === 'open' && !keyboard) return
  if (predicting === 'close' && keyboard) return
  if (predicting) {
    // Tasdiq keldi: farq bo'lsa - silliq tuzatamiz (sakrash emas).
    animate()
    endPrediction()
  }
  if (keyboard) remember(tallest - height)
  apply(height, top, visual, keyboard)
}

function schedule(): void {
  if (!frame) frame = requestAnimationFrame(sync)
}

function predictOpen(): void {
  const root = document.documentElement
  if (!touchScreen || root.classList.contains('kb-open') || !tallest) return
  const kb = readCache()[String(window.innerWidth)]
  if (!kb || kb < KEYBOARD_PX) return
  predicting = 'open'
  animate()
  root.style.setProperty('--app-h', `${Math.round(tallest - kb)}px`)
  root.classList.add('kb-open')
  window.clearTimeout(predictTimer)
  predictTimer = window.setTimeout(() => {
    // Klaviatura chiqmadi (jismoniy klaviatura, tashqi qurilma) - haqiqiy o'lchovga.
    predicting = null
    animate()
    sync()
  }, PREDICT_MS)
}

function predictClose(): void {
  const root = document.documentElement
  if (!touchScreen || !root.classList.contains('kb-open') || !tallest) return
  predicting = 'close'
  animate()
  root.style.setProperty('--app-h', `${tallest}px`)
  root.classList.remove('kb-open')
  window.clearTimeout(predictTimer)
  predictTimer = window.setTimeout(() => {
    predicting = null
    sync()
  }, PREDICT_MS)
}

export function startLayout(): void {
  if (started) return
  started = true
  sync()
  const vv = window.visualViewport
  vv?.addEventListener('resize', schedule)
  vv?.addEventListener('scroll', schedule)
  window.addEventListener('resize', schedule)
  window.addEventListener('orientationchange', schedule)
  onViewportChange(schedule)
  document.addEventListener('focusin', (e) => {
    if (isEditable(e.target)) predictOpen()
    schedule()
  })
  // Fokus boshqa maydonga o'tgan bo'lsa (login -> parol) klaviatura yopilmaydi.
  document.addEventListener('focusout', () =>
    setTimeout(() => {
      if (!editableFocused()) predictClose()
      schedule()
    }, 60),
  )
  // iOS ba'zan klaviatura yopilgach hujjatni surilgan holda qoldiradi - qaytaramiz
  // (body aylanmaydi, ya'ni bu faqat brauzerning o'z siljishini tozalaydi).
  window.addEventListener('scroll', () => {
    if (window.scrollY !== 0 && !editableFocused()) window.scrollTo(0, 0)
  })
}
