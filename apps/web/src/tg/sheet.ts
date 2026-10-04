// Mini App pastki oynalari (VSheet) uchun umumiy xulq - bitta joyda:
//
//   1. Telegram "Orqaga" tugmasi oynani yopadi (backStack.ts).
//   2. KONTENTDAN PASTGA TORTIB YOPISH. VSheet o'zi faqat tutqich va sarlavhadan
//      tortishni biladi; iOS odami esa ro'yxat tepasida turganda oynani istalgan
//      joyidan pastga tortadi. Shart: ro'yxat eng tepada (scrollTop = 0) va birinchi
//      8 px harakat PASTGA - aks holda bu oddiy aylantirish, tegilmaydi. Gorizontal
//      harakat (tarix qatorini surish) ham tegilmaydi.
//      `touch*` hodisalari (pointer emas): brauzer aylantirishni o'z qo'liga olganda
//      pointer hodisalari `pointercancel` bilan uziladi; `touchmove` ni esa
//      `preventDefault` bilan ushlab qolish mumkin (passive: false).
//   3. CHUQURLIK (faqat to'liq bo'yli oyna - tarix): ochiq paytda ortdagi ilova 0.94
//      ga kichrayadi va burchaklari yumaloqlanadi (iOS "card" uslubi) - odam oyna
//      ilova USTIDA ekanini, pastga tortsa qaytishini sezadi. Faqat `transform`
//      (arzon). `prefers-reduced-motion` da CSS uni o'chiradi (styles.css).

import { getCurrentScope, onScopeDispose, watch } from 'vue'
import type { Ref } from 'vue'
import type VSheet from '../ui/VSheet.vue'
import { useBackButton } from './backStack'

type SheetInstance = InstanceType<typeof VSheet>

export interface TgSheetOptions {
  /** Yopish (standart: `open = false`). */
  close?: () => void
  /** Yopish mumkinmi (masalan yuborish paytida - yo'q). */
  canClose?: () => boolean
  /** Ortdagi ilovani kichraytirish (to'liq bo'yli oyna). */
  depth?: boolean
}

const SLOP_PX = 8

let depthOwners = 0

export function useTgSheet(open: Ref<boolean>, sheet: Ref<SheetInstance | null>, options: TgSheetOptions = {}): void {
  const close = options.close ?? (() => (open.value = false))
  const canClose = options.canClose ?? (() => true)
  useBackButton(open, () => {
    if (canClose()) close()
  })

  /* ── Pastga tortish ── */
  let body: HTMLElement | null = null
  let mode: 'idle' | 'maybe' | 'pull' | 'off' = 'idle'
  let startX = 0
  let startY = 0
  let dy = 0
  let lastY = 0
  let lastT = 0
  let velocity = 0
  let suppressClickUntil = 0

  const panel = (): HTMLElement | null => (sheet.value?.panel as HTMLElement | null | undefined) ?? null

  function isField(target: EventTarget | null): boolean {
    return target instanceof Element && !!target.closest('input, textarea, select, [contenteditable]')
  }

  function onStart(e: TouchEvent) {
    if (e.touches.length !== 1 || !body || !canClose() || body.scrollTop > 0 || isField(e.target)) {
      mode = 'off'
      return
    }
    const t = e.touches[0]
    mode = 'maybe'
    startX = t.clientX
    startY = lastY = t.clientY
    lastT = e.timeStamp
    velocity = 0
    dy = 0
  }

  function onMove(e: TouchEvent) {
    if (mode === 'off' || mode === 'idle' || !body) return
    const t = e.touches[0]
    const el = panel()
    if (!t || !el) return
    if (mode === 'maybe') {
      const dx = t.clientX - startX
      const d = t.clientY - startY
      if (Math.abs(dx) < SLOP_PX && Math.abs(d) < SLOP_PX) return
      if (d > 0 && Math.abs(d) > Math.abs(dx) && body.scrollTop <= 0) {
        mode = 'pull'
        startY = t.clientY
        el.style.transition = 'none'
      } else {
        mode = 'off'
        return
      }
    }
    e.preventDefault()
    dy = Math.max(0, t.clientY - startY)
    velocity = (t.clientY - lastY) / Math.max(1, e.timeStamp - lastT)
    lastY = t.clientY
    lastT = e.timeStamp
    el.style.transform = `translateY(${dy}px)`
  }

  function onEnd() {
    const was = mode
    mode = 'idle'
    if (was !== 'pull') return
    const el = panel()
    if (!el) return
    // Tortish tugadi - barmoq ostidagi qator "bosilib" ketmasin.
    suppressClickUntil = Date.now() + 350
    const h = el.offsetHeight || 1
    if (dy > h * 0.25 || (velocity > 0.5 && dy > 16)) {
      el.style.transition = 'transform var(--dur-2) var(--ease-out)'
      el.style.transform = 'translateY(100%)'
      close()
    } else {
      el.style.transition = 'transform var(--dur-3) var(--ease-sheet)'
      el.style.transform = ''
      el.addEventListener('transitionend', () => (el.style.transition = ''), { once: true })
    }
  }

  function onClickCapture(e: MouseEvent) {
    if (Date.now() < suppressClickUntil) {
      e.preventDefault()
      e.stopPropagation()
    }
  }

  function detach() {
    if (!body) return
    body.removeEventListener('touchstart', onStart)
    body.removeEventListener('touchmove', onMove)
    body.removeEventListener('touchend', onEnd)
    body.removeEventListener('touchcancel', onEnd)
    body.removeEventListener('click', onClickCapture, true)
    body = null
    mode = 'idle'
  }

  function attach(el: HTMLElement) {
    body = el
    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('touchend', onEnd)
    el.addEventListener('touchcancel', onEnd)
    el.addEventListener('click', onClickCapture, true)
  }

  // Panel faqat ochiq paytda DOM'da (v-if) - tana paydo bo'lganda ulanadi.
  watch(
    () => (open.value ? ((sheet.value?.body as HTMLElement | null | undefined) ?? null) : null),
    (el) => {
      if (el === body) return
      detach()
      if (el) attach(el)
    },
    { flush: 'post' },
  )

  /* ── Chuqurlik ── */
  if (options.depth) {
    let mine = false
    const set = (on: boolean) => {
      if (on === mine) return
      mine = on
      depthOwners += on ? 1 : -1
      document.documentElement.classList.toggle('sheet-depth', depthOwners > 0)
    }
    watch(open, set, { immediate: true })
    if (getCurrentScope()) onScopeDispose(() => set(false))
  }

  if (getCurrentScope()) onScopeDispose(detach)
}
