import { getCurrentScope, onScopeDispose, readonly, ref, toValue, watch } from 'vue'
import type { MaybeRefOrGetter, Ref } from 'vue'

/* Tashqariga bosish va "qatlamlar" (layers).

   Muammo: popover/menyu/dialog'lar <body> ga teleport qilinadi, ya'ni DOM'da bir-
   birining ichida EMAS. Dialog ichidagi VSelect ro'yxati ochiq turganda:
   - Esc faqat ro'yxatni yopishi kerak, dialogni emas;
   - ro'yxatga bosish dialog uchun "tashqariga bosish" hisoblanmasligi kerak;
   - dialog ichiga bosish esa faqat ro'yxatni yopadi.
   Shuning uchun ochiq qatlamlarning bitta global steki bor: Esc va tashqariga bosish
   eng yuqoridagi qatlamdan pastga qarab hal qilinadi, modal qatlamda to'xtaydi.
   z-index ham shu yerda: dialog ichida ochilgan popover dialogdan YUQORIDA bo'lishi
   kerak, ammo `--z-popover` (40) `--z-dialog` (60) dan past - stek chuqurligi hisobga
   olinadi. */

type Target = Element | null | undefined

export type LayerKind = 'popover' | 'sheet' | 'dialog'
export type DismissReason = 'escape' | 'outside'

/** Shu atributli element ichidagi bosish/fokus hech bir qatlamni yopmaydi (toast'lar). */
export const LAYER_IGNORE_ATTR = 'data-v-layer-ignore'

// tokens.css dagi --z-* qiymatlari bilan bir xil TARTIB (faqat solishtirish uchun;
// CSS'ga baribir `var(--z-...)` yoziladi).
const ORDER: Record<LayerKind, number> = { popover: 40, sheet: 50, dialog: 60 }

/** Tooltip hamma qatlamdan yuqorida, faqat toast'dan past. */
export const TOOLTIP_Z = 'calc(var(--z-toast) - 1)'

interface LayerEntry {
  kind: LayerKind
  modal: boolean
  elements: () => Target[]
  onDismiss: (reason: DismissReason, event: Event) => void
  escape: () => boolean
  outside: () => boolean
}

const stack: LayerEntry[] = []

function toElement(node: EventTarget | null): Element | null {
  if (!node) return null
  if (node instanceof Element) return node
  return node instanceof Node ? node.parentElement : null
}

function isIgnored(node: EventTarget | null): boolean {
  return !!toElement(node)?.closest(`[${LAYER_IGNORE_ATTR}]`)
}

function inside(entry: LayerEntry, node: Node): boolean {
  return entry.elements().some((el) => !!el && el.contains(node))
}

/** Tugun shu qatlamda yoki undan yuqoridagi (bola) qatlamlardan birida. */
function inLayerOrAbove(entry: LayerEntry, node: Node): boolean {
  const from = stack.indexOf(entry)
  if (from < 0) return inside(entry, node)
  for (let i = from; i < stack.length; i++) if (inside(stack[i], node)) return true
  return false
}

/* ---- global tinglovchilar (stek bo'sh bo'lmaganda) ---- */

// Sensorli ekranda pointerdown - bu hali "bosish" emas, balki aylantirish boshlanishi
// bo'lishi mumkin. Menyu barmoq sahifani surishi bilan yopilib qolmasin: touch uchun
// qaror barmoq ko'tarilganda (pointerup) qilinadi - agar u joyidan deyarli siljimagan
// bo'lsa. (`click` ga tayanmaymiz: iOS Safari "bosiladigan" bo'lmagan bo'sh joyga
// tegilganda click hodisasini umuman yubormaydi.) Brauzer aylantirishni o'z qo'liga
// olsa - pointercancel keladi va hech narsa yopilmaydi.
let touch: { id: number; x: number; y: number; target: EventTarget | null } | null = null
const TAP_SLOP = 10

function handleOutside(target: EventTarget | null, e: Event) {
  if (!(target instanceof Node) || !stack.length || isIgnored(target)) return
  for (let i = stack.length - 1; i >= 0; i--) {
    const layer = stack[i]
    if (inLayerOrAbove(layer, target)) break
    // Modal qatlam (dialog) faqat eng yuqorida bo'lsa yopiladi: uning ichidagi menyuni
    // yopish uchun qilingan bosish dialogni ham yopib yubormasin.
    if (layer.modal && i !== stack.length - 1) break
    if (!layer.outside()) break
    layer.onDismiss('outside', e)
    if (layer.modal) break
  }
}

function onPointerDown(e: PointerEvent) {
  if (e.pointerType === 'touch') {
    touch = { id: e.pointerId, x: e.clientX, y: e.clientY, target: e.target }
    return
  }
  touch = null
  handleOutside(e.target, e)
}

function onPointerUp(e: PointerEvent) {
  if (!touch || e.pointerId !== touch.id) return
  const moved = Math.hypot(e.clientX - touch.x, e.clientY - touch.y) > TAP_SLOP
  const target = touch.target
  touch = null
  if (!moved) handleOutside(target, e)
}

function onPointerCancel(e: PointerEvent) {
  if (touch && e.pointerId === touch.id) touch = null
}

// ChatView va boshqalar Escape'ni window'da tinglab, `defaultPrevented` bo'lsa o'tkazib
// yuboradi - shuning uchun faqat preventDefault (stopPropagation emas). Ichki komponent
// (masalan, VInput tozalash) Esc'ni o'zi ishlatib bo'lgan bo'lsa - qatlamga tegmaymiz.
function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.isComposing || e.defaultPrevented) return
  const top = stack[stack.length - 1]
  if (!top) return
  e.preventDefault()
  if (top.escape()) top.onDismiss('escape', e)
}

let attached = false
function attach() {
  if (attached || typeof document === 'undefined') return
  attached = true
  document.addEventListener('pointerdown', onPointerDown, true)
  document.addEventListener('pointerup', onPointerUp, true)
  document.addEventListener('pointercancel', onPointerCancel, true)
  document.addEventListener('keydown', onKeyDown)
}
function detach() {
  if (!attached) return
  attached = false
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('pointerup', onPointerUp, true)
  document.removeEventListener('pointercancel', onPointerCancel, true)
  document.removeEventListener('keydown', onKeyDown)
  touch = null
}

/* ---- ommaviy API ---- */

export interface LayerOptions {
  kind?: LayerKind
  /** Modal (dialog/sheet): tashqariga bosish faqat u eng yuqorida bo'lganda ishlaydi. */
  modal?: boolean
  /** Qatlamga tegishli elementlar: panel va (bo'lsa) uni ochgan tugma. */
  elements: () => Target[]
  onDismiss: (reason: DismissReason, event: Event) => void
  closeOnEscape?: MaybeRefOrGetter<boolean>
  closeOnOutside?: MaybeRefOrGetter<boolean>
}

export interface LayerHandle {
  /** `z-index` qiymati (CSS ifodasi) - qatlam ochilgan paytda hisoblanadi. */
  zIndex: Readonly<Ref<string>>
  /** Tugun shu qatlamda yoki uning ustidagi qatlamlarda (fokus tuzog'i uchun). */
  contains: (node: Node | null) => boolean
  isTop: () => boolean
}

export function useLayer(active: MaybeRefOrGetter<boolean>, options: LayerOptions): LayerHandle {
  const kind = options.kind ?? 'popover'
  const zIndex = ref(`var(--z-${kind})`)
  let entry: LayerEntry | null = null

  function add() {
    if (entry) return
    // Pastdagi eng "baland" qatlam turi: dialog ichidagi popover dialog darajasida turadi.
    let base: LayerKind = kind
    for (const l of stack) if (ORDER[l.kind] > ORDER[base]) base = l.kind
    zIndex.value = `calc(var(--z-${base}) + ${stack.length})`
    entry = {
      kind,
      modal: !!options.modal,
      elements: options.elements,
      onDismiss: options.onDismiss,
      escape: () => toValue(options.closeOnEscape) ?? true,
      outside: () => toValue(options.closeOnOutside) ?? true,
    }
    stack.push(entry)
    attach()
  }

  function remove() {
    if (!entry) return
    const i = stack.indexOf(entry)
    if (i >= 0) stack.splice(i, 1)
    entry = null
    if (!stack.length) detach()
  }

  // `pre` flush: z-index panel chizilishidan OLDIN tayyor bo'ladi.
  watch(
    () => !!toValue(active),
    (on) => (on ? add() : remove()),
    { immediate: true },
  )
  onScopeDispose(remove)

  return {
    zIndex: readonly(zIndex),
    contains: (node) => !!node && (isIgnored(node) || (entry ? inLayerOrAbove(entry, node) : false)),
    isTop: () => !!entry && stack[stack.length - 1] === entry,
  }
}

/**
 * Oddiy "tashqariga bosildi" tinglovchisi - qatlam steki kerak bo'lmagan joylar uchun
 * (masalan, kengaytirilgan qator, inline tahrirlash). Overlay'lar uchun `useLayer`.
 */
export function useClickOutside(
  targets: MaybeRefOrGetter<Target | Target[]>,
  handler: (e: PointerEvent) => void,
  options: { enabled?: MaybeRefOrGetter<boolean> } = {},
): () => void {
  function listener(e: PointerEvent) {
    if (options.enabled !== undefined && !toValue(options.enabled)) return
    const t = e.target
    if (!(t instanceof Node) || isIgnored(t)) return
    const raw = toValue(targets)
    const list = Array.isArray(raw) ? raw : [raw]
    if (list.some((el) => !!el && el.contains(t))) return
    handler(e)
  }
  // SSR / testda `document` yo'q - tinglovchi ham, uni olib tashlash ham bo'lmaydi.
  if (typeof document === 'undefined') return () => {}
  document.addEventListener('pointerdown', listener, true)
  let stopped = false
  const stop = () => {
    if (stopped) return
    stopped = true
    document.removeEventListener('pointerdown', listener, true)
  }
  if (getCurrentScope()) onScopeDispose(stop)
  return stop
}
