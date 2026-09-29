import { computed, onScopeDispose, ref, toValue, watch } from 'vue'
import type { CSSProperties, MaybeRefOrGetter, Ref } from 'vue'

/* Suzuvchi element (popover, menyu, tooltip) joylashuvi - kutubxonasiz.

   Algoritm (Floating UI'ning eng kerakli qismi):
   1. Tanlangan tomonga (top/bottom/left/right) + tekislashga (start/center/end) qo'yamiz.
   2. flip: o'sha tomonda joy yetmasa va qarama-qarshi tomonda ko'proq bo'lsa - o'giramiz.
   3. shift: ko'ndalang o'q bo'yicha ekran chetidan 8px ichkarida ushlab turamiz.
   4. Balandlik yetmasa `maxHeight` beramiz - uzun ro'yxat ekrandan chiqmay, ichida aylanadi.
   `position: fixed` + left/top: animatsiya uchun `transform` bo'sh qoladi (scale .98).
   O'lcham `offsetWidth/Height` dan - ular transform'ni hisobga olmaydi, ya'ni kirish
   animatsiyasi paytidagi .98 masshtab joylashuvni buzmaydi. */

export type Side = 'top' | 'right' | 'bottom' | 'left'
export type Align = 'start' | 'center' | 'end'
export type Placement = Side | `${Side}-start` | `${Side}-end`

/** Haqiqiy element bo'lmagan langar (masalan, sichqoncha nuqtasi yoki grafik kursori). */
export interface VirtualElement {
  getBoundingClientRect(): DOMRect
}
export type FloatingAnchor = Element | VirtualElement

export interface UseFloatingOptions {
  open: MaybeRefOrGetter<boolean>
  placement?: MaybeRefOrGetter<Placement | undefined>
  /** Langar bilan orasidagi masofa, px. */
  offset?: MaybeRefOrGetter<number | undefined>
  /** Ekran chetidan minimal masofa, px. */
  padding?: number
  flip?: boolean
  shift?: boolean
  /** Kengligi langardan kam bo'lmasin (select ro'yxati). */
  matchWidth?: MaybeRefOrGetter<boolean | undefined>
  /** Balandlikni mavjud joy bilan cheklash. */
  constrainHeight?: boolean
}

const OPPOSITE: Record<Side, Side> = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' }

export function splitPlacement(p: Placement): [Side, Align] {
  const [side, align] = p.split('-') as [Side, Align | undefined]
  return [side, align ?? 'center']
}

function roundByDpr(v: number): number {
  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
  return Math.round(v * dpr) / dpr
}

export function useFloating(
  anchor: MaybeRefOrGetter<FloatingAnchor | null | undefined>,
  floating: Ref<HTMLElement | null>,
  options: UseFloatingOptions,
) {
  const pad = options.padding ?? 8
  const x = ref(0)
  const y = ref(0)
  // Boshlang'ich qiymat so'ralgan tomondan: kirish animatsiyasining birinchi kadri
  // (o'lchashdan oldin) ham to'g'ri yo'nalishda bo'lsin.
  const [initSide, initAlign] = splitPlacement(toValue(options.placement) ?? 'bottom')
  const side = ref<Side>(initSide)
  const align = ref<Align>(initAlign)
  const maxHeight = ref<number | null>(null)
  const minWidth = ref<number | null>(null)
  const origin = ref('center')
  /** Birinchi o'lchashdan oldin element ko'rinmasin (0,0 da "chaqnab" qolmasin). */
  const ready = ref(false)

  function compute() {
    const a = toValue(anchor)
    const f = floating.value
    if (!a || !f || !toValue(options.open)) return
    // Langar DOM'dan olib tashlangan bo'lsa - eski joyida qoladi.
    if (a instanceof Element && !a.isConnected) return

    const ar = a.getBoundingClientRect()
    const vw = document.documentElement.clientWidth
    const vh = document.documentElement.clientHeight
    const off = toValue(options.offset) ?? 6
    const [prefSide, prefAlign] = splitPlacement(toValue(options.placement) ?? 'bottom')

    const match = !!toValue(options.matchWidth)
    const fw = match ? Math.max(f.offsetWidth, ar.width) : f.offsetWidth
    // Tabiiy balandlik: avvalgi maxHeight cheklovi bo'lsa ham kontentning to'liq bo'yi.
    const chrome = f.offsetHeight - f.clientHeight
    const natural = Math.max(f.offsetHeight, f.scrollHeight + chrome)

    const space: Record<Side, number> = {
      top: ar.top - off - pad,
      bottom: vh - ar.bottom - off - pad,
      left: ar.left - off - pad,
      right: vw - ar.right - off - pad,
    }
    const need = (s: Side) => (s === 'top' || s === 'bottom' ? natural : fw)

    let s = prefSide
    if (options.flip !== false && space[s] < need(s) && space[OPPOSITE[s]] > space[s]) s = OPPOSITE[s]

    let fh = natural
    let mh: number | null = null
    if (options.constrainHeight !== false && (s === 'top' || s === 'bottom') && natural > space[s]) {
      mh = Math.max(96, Math.floor(space[s]))
      fh = Math.min(natural, mh)
    }

    let px = 0
    let py = 0
    if (s === 'top' || s === 'bottom') {
      py = s === 'top' ? ar.top - off - fh : ar.bottom + off
      px = prefAlign === 'start' ? ar.left : prefAlign === 'end' ? ar.right - fw : ar.left + ar.width / 2 - fw / 2
      if (options.shift !== false) px = Math.min(Math.max(px, pad), Math.max(pad, vw - fw - pad))
    } else {
      px = s === 'left' ? ar.left - off - fw : ar.right + off
      py = prefAlign === 'start' ? ar.top : prefAlign === 'end' ? ar.bottom - fh : ar.top + ar.height / 2 - fh / 2
      if (options.shift !== false) py = Math.min(Math.max(py, pad), Math.max(pad, vh - fh - pad))
    }

    // Masshtab animatsiyasi langar tomonidan "o'sib chiqsin": origin langar markaziga qaratiladi.
    if (s === 'top' || s === 'bottom') {
      const ox = Math.min(Math.max(ar.left + ar.width / 2 - px, 0), fw)
      origin.value = `${Math.round(ox)}px ${s === 'top' ? '100%' : '0'}`
    } else {
      const oy = Math.min(Math.max(ar.top + ar.height / 2 - py, 0), fh)
      origin.value = `${s === 'left' ? '100%' : '0'} ${Math.round(oy)}px`
    }

    x.value = roundByDpr(px)
    y.value = roundByDpr(py)
    side.value = s
    align.value = prefAlign
    maxHeight.value = mh
    minWidth.value = match ? Math.round(ar.width) : null
    ready.value = true
  }

  // Aylantirish/o'lcham o'zgarishida kadrda bir marta hisoblaymiz.
  let frame = 0
  function schedule() {
    if (frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      compute()
    })
  }

  // Panelning O'Z ichidagi aylantirish (uzun ro'yxat) joylashuvni o'zgartirmaydi.
  function onScroll(e: Event) {
    const f = floating.value
    if (f && e.target instanceof Node && f.contains(e.target)) return
    schedule()
  }

  let ro: ResizeObserver | null = null
  let listening = false

  function start() {
    if (listening) return
    listening = true
    window.addEventListener('resize', schedule, { passive: true })
    // capture: har qanday aylanuvchi ota-element (sidebar, jadval) ham hisobga olinadi.
    document.addEventListener('scroll', onScroll, { passive: true, capture: true })
    window.visualViewport?.addEventListener('resize', schedule, { passive: true })
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(schedule)
      const a = toValue(anchor)
      if (a instanceof Element) ro.observe(a)
      if (floating.value) ro.observe(floating.value)
    }
  }

  function stop() {
    if (!listening) return
    listening = false
    window.removeEventListener('resize', schedule)
    document.removeEventListener('scroll', onScroll, { capture: true })
    window.visualViewport?.removeEventListener('resize', schedule)
    ro?.disconnect()
    ro = null
    if (frame) cancelAnimationFrame(frame)
    frame = 0
  }

  // `post`: element DOM'ga qo'yilgandan keyin, lekin brauzer chizishidan OLDIN
  // sinxron o'lchaymiz - birinchi kadrdayoq to'g'ri joyda turadi.
  watch(
    () => [!!toValue(options.open), floating.value, toValue(anchor)] as const,
    ([open, el]) => {
      if (open && el) {
        stop()
        compute()
        start()
      } else {
        stop()
        if (!open) ready.value = false
      }
    },
    { flush: 'post', immediate: true },
  )
  // Joylashuv sozlamasi o'zgarsa (masalan, placement prop) - qayta hisoblash.
  watch(
    () => [toValue(options.placement), toValue(options.offset), toValue(options.matchWidth)],
    () => compute(),
    { flush: 'post' },
  )
  onScopeDispose(stop)

  const style = computed<CSSProperties>(() => ({
    position: 'fixed',
    left: `${x.value}px`,
    top: `${y.value}px`,
    transformOrigin: origin.value,
    maxHeight: maxHeight.value != null ? `${maxHeight.value}px` : undefined,
    minWidth: minWidth.value != null ? `${minWidth.value}px` : undefined,
    visibility: ready.value ? undefined : 'hidden',
  }))

  return { x, y, side, align, maxHeight, origin, ready, style, update: compute }
}
