import { computed, onScopeDispose, readonly, ref, watch } from 'vue'
import type { ComputedRef, Ref } from 'vue'

// Chap panel kengligini tortib o'zgartirish (chat yon paneli, admin menyusi).
//
// Holat EGASI - sahifa (ChatView / AdminLayout): yig'iq/ochiq tanlovi o'sha yerda
// saqlanadi va Esc kabi boshqa yo'llar bilan ham o'zgaradi. Bu composable faqat
// kenglikni (eslab qolinadi) va tortish jarayonini boshqaradi; panel elementiga
// ikkita CSS o'zgaruvchi beradi:
//   --panel-w          - panelning hozirgi tashqi kengligi (yig'iq bo'lsa - ustun);
//   --panel-content-w  - ichidagi matn joylashadigan kenglik. Ochish/yig'ish
//                        animatsiyasida u O'ZGARMAYDI - yozuvlar qayta joylashib
//                        "titramaydi", faqat torayayotgan panel ularni kesadi.
//
// Nega reaktiv holat (DOM'ga to'g'ridan-to'g'ri yozish emas): panel uslubi
// shablonda bog'langan; kenglik boshqa joyda yozilsa, oqib kelayotgan javob kabi
// begona qayta chizish uni eski qiymatga qaytarib, tortish paytida miltillatardi.
// Har kadrda ko'pi bilan bitta yangilanish (rAF) - bu yetarlicha arzon.

export interface ResizablePanelOptions {
  /** localStorage kaliti: ochiq paneldagi kenglik (px). */
  storageKey: string
  min: number
  max: number
  /** Standart kenglik - tokens.css dagi qiymat bilan bir xil bo'lsin. */
  initial: number
  /** Yig'iq ustun kengligi (tokens.css: --rail-w / --admin-rail-w). */
  rail: number
  /** Yig'iq holat - egasi saqlaydi. */
  collapsed: () => boolean
  setCollapsed: (value: boolean) => void
  /** Tortish faqat katta ekranda (>=1120). O'chiq bo'lsa panel standart kenglikda. */
  enabled?: () => boolean
  /** `min` dan shuncha tor qo'yib yuborilsa - panel ustunga yig'iladi. */
  snap?: number
}

export interface ResizablePanel {
  readonly min: number
  readonly max: number
  readonly initial: number
  readonly rail: number
  /** Eslab qolingan ochiq kenglik (yig'iq paytida ham saqlanadi). */
  width: Readonly<Ref<number>>
  dragging: Readonly<Ref<boolean>>
  enabled: ComputedRef<boolean>
  collapsed: ComputedRef<boolean>
  /** Panel ustun ko'rinishida: yig'iq, yoki tortib yig'ish chegarasidan o'tilgan. */
  folded: ComputedRef<boolean>
  /** Panel elementiga: `--panel-w`, `--panel-content-w`. */
  style: ComputedRef<Record<string, string>>
  setWidth: (px: number) => void
  reset: () => void
  onPointerDown: (e: PointerEvent) => void
  onKeyDown: (e: KeyboardEvent) => void
  onDoubleClick: (e: MouseEvent) => void
}

/** Tortish paytida <body> sinfi (base.css: kursor hamma joyda col-resize, matn belgilanmaydi). */
const BODY_CLASS = 'is-col-resizing'
/** Shundan kam siljish - oddiy bosish (ikki marta bosish kenglikni o'zgartirib qo'ymasin). */
const DRAG_SLOP = 3

function readWidth(key: string): number | null {
  try {
    const raw = localStorage.getItem(key)
    const n = raw === null ? NaN : Number.parseInt(raw, 10)
    return Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}

function writeWidth(key: string, px: number) {
  try {
    localStorage.setItem(key, String(px))
  } catch {
    /* xususiy rejim / bloklangan - faqat shu sessiyada eslab qolinadi */
  }
}

export function useResizablePanel(options: ResizablePanelOptions): ResizablePanel {
  const { storageKey, min, max, initial, rail } = options
  const snap = options.snap ?? 48
  const clamp = (px: number) => Math.round(Math.min(max, Math.max(min, px)))

  // Saqlangan kenglik SETUP paytida o'qiladi: panel birinchi chizilishidayoq to'g'ri
  // kenglikda - standartdan saqlanganga "sakrash" animatsiyasi bo'lmaydi.
  const stored = readWidth(storageKey)
  const width = ref(stored === null ? initial : clamp(stored))
  /** Tortilayotgan xom kenglik (chegaralanmagan); tortilmayotganda - null. */
  const live = ref<number | null>(null)
  const dragging = ref(false)

  const enabled = computed(() => options.enabled?.() ?? true)
  const collapsed = computed(() => options.collapsed())
  // Kichik ekranda (planshet) eslab qolingan keng qiymat emas, standart: u yerda
  // kontentga joy kerak va tortib bo'lmaydi.
  const restWidth = computed(() => (enabled.value ? width.value : initial))

  const folded = computed(() => (live.value !== null ? live.value < min - snap : collapsed.value))

  const style = computed(() => {
    const outer =
      live.value !== null
        ? Math.round(Math.min(max, Math.max(rail, live.value)))
        : collapsed.value
          ? rail
          : restWidth.value
    // Matn kengligi `min` dan torroq bo'lmaydi: tor qilib tortilganda yozuvlar
    // siqilmaydi, panel ularni kesadi (yig'ilish shu ko'rinishda boshlanadi).
    const content = live.value !== null ? clamp(live.value) : restWidth.value
    return { '--panel-w': `${outer}px`, '--panel-content-w': `${content}px` }
  })

  function setWidth(px: number) {
    width.value = clamp(px)
    writeWidth(storageKey, width.value)
  }

  function reset() {
    setWidth(initial)
    if (collapsed.value) options.setCollapsed(false)
  }

  /* ---- sichqoncha / barmoq bilan tortish ---- */

  interface Drag {
    id: number
    el: HTMLElement
    startX: number
    startW: number
    x: number
    moved: boolean
    frame: number
  }
  let drag: Drag | null = null

  function apply() {
    if (!drag) return
    drag.frame = 0
    live.value = drag.startW + (drag.x - drag.startX)
  }

  function onMove(e: PointerEvent) {
    if (!drag || e.pointerId !== drag.id) return
    drag.x = e.clientX
    if (!drag.moved) {
      if (Math.abs(drag.x - drag.startX) < DRAG_SLOP) return
      drag.moved = true
      dragging.value = true
    }
    // Bir kadrga bitta yangilanish: sichqoncha 1000 Hz da hodisa yuborsa ham
    // panel kadrdan tez qayta joylashtirilmaydi.
    if (!drag.frame) drag.frame = requestAnimationFrame(apply)
  }

  /** Tortishni yakunlaydi; `commitX` berilsa - natija saqlanadi, aks holda bekor. */
  function finish(commitX?: number) {
    const d = drag
    if (!d) return
    drag = null
    if (d.frame) cancelAnimationFrame(d.frame)
    d.el.removeEventListener('pointermove', onMove)
    d.el.removeEventListener('pointerup', onUp)
    d.el.removeEventListener('pointercancel', onCancel)
    d.el.removeEventListener('lostpointercapture', onCancel)
    window.removeEventListener('keydown', onDragKey, true)
    try {
      if (d.el.hasPointerCapture(d.id)) d.el.releasePointerCapture(d.id)
    } catch {
      /* element allaqachon DOM'dan chiqqan */
    }
    document.body.classList.remove(BODY_CLASS)
    // Hammasi BITTA yangilanishda: tortish sinfi olinadi (o'tish yana yoqiladi) va
    // yakuniy kenglik qo'yiladi - panel qo'yib yuborilgan joyidan silliq yetib boradi
    // (min ga qaytadi yoki ustunga yig'iladi).
    live.value = null
    dragging.value = false
    if (commitX === undefined || !d.moved) return
    const raw = d.startW + (commitX - d.startX)
    if (raw < min - snap) {
      // Ochiq kenglik o'zgarmaydi - keyin ochilganda panel avvalgi kengligiga qaytadi.
      if (!collapsed.value) options.setCollapsed(true)
      return
    }
    setWidth(raw)
    if (collapsed.value) options.setCollapsed(false)
  }

  function onUp(e: PointerEvent) {
    if (drag && e.pointerId === drag.id) finish(e.clientX)
  }
  function onCancel(e: PointerEvent) {
    if (drag && e.pointerId === drag.id) finish()
  }
  // Tortish paytida Esc - bekor qilish. Ushlash (capture) bosqichida va
  // preventDefault bilan: ChatView'ning Esc'i (panelni yig'ish) bu bosishni ko'rmasin.
  function onDragKey(e: KeyboardEvent) {
    if (e.key !== 'Escape') return
    e.preventDefault()
    e.stopPropagation()
    finish()
  }

  function onPointerDown(e: PointerEvent) {
    if (!enabled.value || drag || e.button !== 0) return
    const el = e.currentTarget as HTMLElement | null
    if (!el) return
    // Matn belgilanishi va tugmaga fokus o'tishi boshlanmasin.
    e.preventDefault()
    drag = {
      id: e.pointerId,
      el,
      startX: e.clientX,
      startW: collapsed.value ? rail : restWidth.value,
      x: e.clientX,
      moved: false,
      frame: 0,
    }
    try {
      el.setPointerCapture(e.pointerId)
    } catch {
      /* eski brauzer - hodisalar baribir elementga keladi, faqat chetdan chiqmaguncha */
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onCancel)
    el.addEventListener('lostpointercapture', onCancel)
    window.addEventListener('keydown', onDragKey, true)
    document.body.classList.add(BODY_CLASS)
  }

  function onDoubleClick(e: MouseEvent) {
    if (!enabled.value) return
    e.preventDefault()
    reset()
  }

  /* ---- klaviatura (WAI-ARIA "window splitter") ---- */

  function onKeyDown(e: KeyboardEvent) {
    if (!enabled.value || e.altKey || e.ctrlKey || e.metaKey) return
    const step = e.shiftKey ? 48 : 16
    let next: number
    switch (e.key) {
      case 'Enter':
        e.preventDefault()
        options.setCollapsed(!collapsed.value)
        return
      case 'ArrowLeft':
        e.preventDefault()
        // Yig'iq ustunni klaviatura bilan yana toraytirib bo'lmaydi - yig'ish Enter'da.
        if (collapsed.value) return
        next = width.value - step
        break
      case 'ArrowRight':
        // Yig'iq paneldagi birinchi bosish - eslab qolingan kenglikda ochish.
        next = collapsed.value ? width.value : width.value + step
        break
      case 'Home':
        next = min
        break
      case 'End':
        next = max
        break
      default:
        return
    }
    e.preventDefault()
    setWidth(next)
    if (collapsed.value) options.setCollapsed(false)
  }

  // Katta ekrandan chiqildi (oyna toraydi) yoki komponent yo'q bo'ldi - tortish
  // yarim yo'lda qolmasin: <body> sinfi va tinglovchilar tozalanadi.
  watch(enabled, (on) => {
    if (!on) finish()
  })
  onScopeDispose(() => finish())

  return {
    min,
    max,
    initial,
    rail,
    width: readonly(width),
    dragging: readonly(dragging),
    enabled,
    collapsed,
    folded,
    style,
    setWidth,
    reset,
    onPointerDown,
    onKeyDown,
    onDoubleClick,
  }
}
