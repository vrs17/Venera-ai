import { nextTick, onScopeDispose, toValue, watch } from 'vue'
import type { MaybeRefOrGetter, Ref } from 'vue'

/* Modal oynalar uchun ikki yordamchi: fokus tuzog'i va sahifa aylantirishini qulflash.

   Fokus tuzog'i: Tab / Shift+Tab modal ichida aylanadi; fokus tashqariga "qochsa"
   (sichqoncha bilan orqadagi elementga, yoki DOM'dan o'chgan elementdan) - qaytariladi.
   Yopilganda fokus modalni ochgan elementga qaytadi.

   Bir nechta tuzoq ustma-ust bo'lishi mumkin (sheet ichida tasdiqlash dialogi) - faqat
   eng oxirgi faollashgani ishlaydi. Teleport qilingan bola qatlamlar (dialog ichidagi
   menyu) DOM'da tuzoqdan tashqarida - ularga `allowOutside` orqali ruxsat beriladi. */

const FOCUSABLE = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'audio[controls]',
  'video[controls]',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]',
].join(',')

function isVisible(el: HTMLElement): boolean {
  // `display: contents` o'ramalarimizda getClientRects bo'sh - ularni tekshirmaymiz.
  return el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'
}

/** Tab bilan yetib boriladigan elementlar, DOM tartibida. */
export function getTabbables(root: Element | null | undefined): HTMLElement[] {
  if (!root) return []
  const out: HTMLElement[] = []
  root.querySelectorAll<HTMLElement>(FOCUSABLE).forEach((el) => {
    if (el.tabIndex < 0 || el.closest('[inert]')) return
    if (!isVisible(el)) return
    out.push(el)
  })
  return out
}

export function focusElement(el: HTMLElement | null | undefined): boolean {
  if (!el || !el.isConnected) return false
  el.focus({ preventScroll: true })
  return document.activeElement === el
}

export interface FocusTrapOptions {
  /** Ochilganda fokus qayerga. `false` - fokusni siljitmaslik. Bo'sh - birinchi tabbable. */
  initialFocus?: () => HTMLElement | null | undefined | false
  /** Yopilganda fokusni ochgan elementga qaytarish (standart: ha). */
  returnFocus?: MaybeRefOrGetter<boolean>
  /** Tuzoqdan tashqarida bo'lsa ham ruxsat etilgan tugunlar (bola qatlamlar, toast). */
  allowOutside?: (node: Node) => boolean
}

interface TrapEntry {
  container: () => HTMLElement | null
  allow: (node: Node) => boolean
  lastInside: HTMLElement | null
}

const traps: TrapEntry[] = []

function onFocusIn(e: FocusEvent) {
  const top = traps[traps.length - 1]
  const box = top?.container()
  const target = e.target
  if (!top || !box || !(target instanceof Node)) return
  if (box.contains(target)) {
    top.lastInside = target instanceof HTMLElement ? target : top.lastInside
    return
  }
  if (top.allow(target)) return
  // Fokus orqa fonga o'tdi - oxirgi ichki elementga (yoki birinchisiga) qaytaramiz.
  if (!focusElement(top.lastInside)) focusElement(getTabbables(box)[0] ?? box)
}

let listening = false
function syncListener() {
  if (typeof document === 'undefined') return
  if (traps.length && !listening) document.addEventListener('focusin', onFocusIn)
  if (!traps.length && listening) document.removeEventListener('focusin', onFocusIn)
  listening = traps.length > 0
}

export function useFocusTrap(
  container: Ref<HTMLElement | null>,
  active: MaybeRefOrGetter<boolean>,
  options: FocusTrapOptions = {},
): void {
  let entry: TrapEntry | null = null
  let returnTo: HTMLElement | null = null
  // Tinglovchi qaysi elementga qo'yilganini eslab qolamiz: yopilish paytida `container`
  // allaqachon null (v-if) yoki boshqa element bo'lishi mumkin - baribir aynan o'sha
  // elementdan olib tashlanadi.
  let boundBox: HTMLElement | null = null

  function onKeyDown(e: KeyboardEvent) {
    if (e.key !== 'Tab' || e.defaultPrevented || !entry || traps[traps.length - 1] !== entry) return
    const box = container.value
    if (!box) return
    const items = getTabbables(box)
    if (!items.length) {
      e.preventDefault()
      focusElement(box)
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const current = document.activeElement
    if (e.shiftKey && (current === first || current === box)) {
      e.preventDefault()
      focusElement(last)
    } else if (!e.shiftKey && (current === last || current === box)) {
      e.preventDefault()
      focusElement(first)
    }
  }

  async function activate() {
    if (entry) return
    const prev = document.activeElement
    returnTo = prev instanceof HTMLElement && prev !== document.body ? prev : null
    entry = {
      container: () => container.value,
      allow: (node) => !!options.allowOutside?.(node),
      lastInside: null,
    }
    traps.push(entry)
    syncListener()

    // Panel hali chizilmagan bo'lishi mumkin (v-if + Transition) - bir tick kutamiz.
    await nextTick()
    const box = container.value
    if (!box || !entry) return
    // Shu tick ichida fokus boshqa joyga qaytgan bo'lishi mumkin: menyu bandi dialogni
    // ochadi va menyu yopilib fokusni ⋯ tugmasiga qaytaradi. Qaytish nuqtasi o'sha
    // tugma bo'lsin - menyu bandi DOM'dan o'chib ketadi.
    const late = document.activeElement
    if (late instanceof HTMLElement && late !== document.body && !box.contains(late)) returnTo = late
    box.addEventListener('keydown', onKeyDown)
    boundBox = box
    if (box.contains(document.activeElement)) return
    const wanted = options.initialFocus?.()
    if (wanted === false) return
    if (!focusElement(wanted || undefined)) {
      if (!focusElement(getTabbables(box)[0])) focusElement(box)
    }
  }

  function deactivate() {
    if (!entry) return
    const box = boundBox ?? container.value
    boundBox?.removeEventListener('keydown', onKeyDown)
    boundBox = null
    const i = traps.indexOf(entry)
    if (i >= 0) traps.splice(i, 1)
    entry = null
    syncListener()

    const shouldReturn = toValue(options.returnFocus) ?? true
    const active = document.activeElement
    // Foydalanuvchi o'zi boshqa joyni tanlagan bo'lsa (masalan, tashqaridagi maydonga
    // bosib yopgan) - fokusni tortib olmaymiz; faqat fokus modal ichida yoki "yo'q"
    // (body) bo'lsa qaytaramiz.
    const focusIsOurs = !active || active === document.body || (!!box && box.contains(active))
    if (shouldReturn && focusIsOurs && returnTo?.isConnected) focusElement(returnTo)
    returnTo = null
  }

  watch(
    () => !!toValue(active),
    (on) => (on ? void activate() : deactivate()),
    { immediate: true },
  )
  onScopeDispose(deactivate)
}

/* ---- sahifa aylantirishini qulflash (hisoblagichli) ----
   Ikki modal ustma-ust ochilsa, birinchisi yopilganda sahifa qulfdan chiqib qolmasin. */

let locks = 0
let saved: { overflow: string; paddingRight: string } | null = null

function lock() {
  if (typeof document === 'undefined') return
  if (locks++ > 0) return
  const body = document.body
  // Aylantirish paneli yo'qolganda sahifa o'ngga "sakramasin" - uning kengligini
  // padding bilan to'ldiramiz.
  const gap = window.innerWidth - document.documentElement.clientWidth
  saved = { overflow: body.style.overflow, paddingRight: body.style.paddingRight }
  body.style.overflow = 'hidden'
  if (gap > 0) {
    const current = parseFloat(getComputedStyle(body).paddingRight) || 0
    body.style.paddingRight = `${current + gap}px`
  }
}

function unlock() {
  if (typeof document === 'undefined' || locks === 0) return
  if (--locks > 0) return
  if (saved) {
    document.body.style.overflow = saved.overflow
    document.body.style.paddingRight = saved.paddingRight
  }
  saved = null
}

export function useScrollLock(active: MaybeRefOrGetter<boolean>): void {
  let held = false
  function set(on: boolean) {
    if (on === held) return
    held = on
    if (on) lock()
    else unlock()
  }
  watch(() => !!toValue(active), set, { immediate: true })
  onScopeDispose(() => set(false))
}
