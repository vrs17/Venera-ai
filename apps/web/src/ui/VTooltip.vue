<script lang="ts">
// Guruh xulqi (modul darajasida, barcha tooltip'lar uchun umumiy): bitta tooltip
// yopilgandan keyin 300ms ichida qo'shni tugmaga o'tilsa - yangisi KUTMASDAN va
// animatsiyasiz chiqadi (asboblar qatori bo'ylab sichqonchani yurgizish tabiiy tuyuladi).
let lastClosedAt = 0
let closeCurrent: (() => void) | null = null
const GROUP_WINDOW = 300
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useSlots, watch } from 'vue'
import { useFloating } from './composables/useFloating'
import type { Placement } from './composables/useFloating'
import { TOOLTIP_Z } from './composables/useClickOutside'
import { useCanHover } from './composables/useMediaQuery'
import { useId } from './composables/useId'
import VKbd from './VKbd.vue'

/**
 * Qisqa izoh: siyoh fonida 12px matn. Faqat sichqonchali qurilmalarda (sensorli
 * ekranda "hover" yo'q - u yerda tugmaning aria-label'i yetarli).
 *
 * Ikki xil ulanish:
 * 1. O'rash: `<VTooltip text="..."><button/></VTooltip>` - default slot'dagi BITTA
 *    element trigger bo'ladi. O'rama `display: contents` - tartibga ta'sir qilmaydi.
 * 2. `target` prop: `<button ref="b">...<VTooltip :target="b" text="..."/></button>` -
 *    tooltip tashqi elementga ulanadi, o'rama yo'q. VIconButton shunday qiladi: tugma
 *    komponentning ILDIZI bo'lib qoladi va chaqiruvchining `class`/scoped uslublari
 *    unga to'g'ridan-to'g'ri tushadi.
 *
 * Tavsif (aria-describedby) yashirin, doim DOM'dagi nusxaga ulanadi: ekran o'quvchi
 * fokusda uni kechikishsiz o'qiydi. `describe=false` - matn allaqachon trigger'ning
 * aria-label'i bo'lsa (VIconButton), ikki marta o'qilmasin.
 */
defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    text?: string
    shortcut?: string | string[]
    placement?: Placement
    offset?: number
    disabled?: boolean
    describe?: boolean
    delay?: number
    target?: HTMLElement | null
  }>(),
  { placement: 'top', offset: 6, describe: true, delay: 400, target: null },
)

defineSlots<{
  default?(): unknown
  content?(): unknown
}>()

const slots = useSlots()
const id = useId('v-tooltip')
const descId = `${id}-desc`
const canHover = useCanHover()

const wrapper = ref<HTMLElement | null>(null)
const bubble = ref<HTMLElement | null>(null)
const trigger = ref<HTMLElement | null>(null)
const open = ref(false)
const instant = ref(false)
// Bosilgandan keyin sichqoncha chiqib ketguncha qayta ochilmasin.
let suppressed = false
let viaKeyboard = false
let timer: ReturnType<typeof setTimeout> | undefined

const hasContent = computed(() => !!props.text || !!slots.content)

const { style: floatingStyle, side } = useFloating(trigger, bubble, {
  open,
  placement: () => props.placement,
  offset: () => props.offset,
})

function resolveTrigger(): HTMLElement | null {
  if (props.target) return props.target
  let el = wrapper.value?.firstElementChild as HTMLElement | null
  while (el && el.hasAttribute('data-v-contents')) el = el.firstElementChild as HTMLElement | null
  return el
}

function show(immediate: boolean) {
  clearTimeout(timer)
  if (props.disabled || !hasContent.value || open.value) return
  const el = resolveTrigger()
  // Trigger o'zi ochgan menyu/popover ochiq turganda tooltip uning ustiga chiqmasin.
  if (!el || el.getAttribute('aria-expanded') === 'true') return
  const grouped = Date.now() - lastClosedAt < GROUP_WINDOW || closeCurrent !== null
  const run = () => {
    if (el.getAttribute('aria-expanded') === 'true') return
    closeCurrent?.()
    trigger.value = el
    instant.value = grouped
    open.value = true
    closeCurrent = hide
  }
  if (immediate || grouped) run()
  else timer = setTimeout(run, props.delay)
}

function hide() {
  clearTimeout(timer)
  if (!open.value) return
  open.value = false
  lastClosedAt = Date.now()
  if (closeCurrent === hide) closeCurrent = null
}

function isInside(node: EventTarget | null): boolean {
  const root = props.target ?? wrapper.value
  return node instanceof Node && !!root?.contains(node)
}

function onPointerOver(e: PointerEvent) {
  if (e.pointerType === 'touch' || !canHover.value || suppressed) return
  if (isInside(e.relatedTarget)) return
  viaKeyboard = false
  show(false)
}
function onPointerOut(e: PointerEvent) {
  if (isInside(e.relatedTarget)) return
  suppressed = false
  if (!viaKeyboard) hide()
}
function onPointerDown() {
  suppressed = true
  hide()
}
function onFocusIn(e: FocusEvent) {
  const t = e.target as Element | null
  // Faqat klaviatura fokusi: sichqoncha bilan bosganda fokus ham keladi, lekin u holda
  // tooltip allaqachon hover orqali boshqariladi.
  if (!t || !t.matches(':focus-visible') || !canHover.value) return
  viaKeyboard = true
  show(true)
}
function onFocusOut(e: FocusEvent) {
  if (isInside(e.relatedTarget)) return
  viaKeyboard = false
  hide()
}
function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !open.value) return
  // WCAG 1.4.13: tooltip'ni yopish mumkin bo'lsin. Sichqoncha ochgan bo'lsa - Esc faqat
  // uni yopadi; klaviatura fokusida esa Esc dialog/menyu yopishga ham o'tadi.
  if (!viaKeyboard) e.preventDefault()
  hide()
}
function onScroll() {
  hide()
}

/* ---- `target` rejimi: tinglovchilar tashqi elementga ---- */
const LISTENERS = [
  ['pointerover', onPointerOver],
  ['pointerout', onPointerOut],
  ['pointerdown', onPointerDown],
  ['focusin', onFocusIn],
  ['focusout', onFocusOut],
  ['keydown', onKeyDown],
] as const

function bind(el: HTMLElement | null, on: boolean) {
  if (!el) return
  for (const [name, fn] of LISTENERS) {
    if (on) el.addEventListener(name, fn as EventListener)
    else el.removeEventListener(name, fn as EventListener)
  }
}

watch(
  () => props.target,
  (el, prev) => {
    bind(prev ?? null, false)
    bind(el, true)
    if (prev && prev !== el) hide()
    wireDescription()
  },
  { flush: 'post' },
)

watch(open, (on) => {
  if (on) document.addEventListener('scroll', onScroll, { passive: true, capture: true })
  else document.removeEventListener('scroll', onScroll, { capture: true })
})
watch(
  () => props.disabled,
  (d) => d && hide(),
)

// aria-describedby: mavjud qiymatlarni (masalan, maydon xatosi) saqlab, o'zimiznikini qo'shamiz.
let describedEl: HTMLElement | null = null
function wireDescription() {
  unwireDescription()
  if (!props.describe || !hasContent.value) return
  const el = resolveTrigger()
  if (!el) return
  const ids = (el.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean)
  if (!ids.includes(descId)) el.setAttribute('aria-describedby', [...ids, descId].join(' '))
  describedEl = el
}
function unwireDescription() {
  if (!describedEl) return
  const ids = (describedEl.getAttribute('aria-describedby') ?? '').split(/\s+/).filter((x) => x && x !== descId)
  if (ids.length) describedEl.setAttribute('aria-describedby', ids.join(' '))
  else describedEl.removeAttribute('aria-describedby')
  describedEl = null
}

onMounted(() => {
  bind(props.target, true)
  wireDescription()
})
watch(() => [props.describe, hasContent.value], wireDescription, { flush: 'post' })
onBeforeUnmount(() => {
  hide()
  bind(props.target, false)
  unwireDescription()
  document.removeEventListener('scroll', onScroll, { capture: true })
})

// Tashqaridan ochish: `target` hodisa paytida almashsa (v-html ichidagi iqtibos chipi),
// tinglovchilar birinchi hover'dan KEYIN ulanadi - chaqiruvchi o'zi ochib beradi.
defineExpose({ show, hide })
</script>

<template>
  <span
    v-if="!target"
    ref="wrapper"
    class="v-tooltip-anchor"
    data-v-contents
    @pointerover="onPointerOver"
    @pointerout="onPointerOut"
    @pointerdown="onPointerDown"
    @focusin="onFocusIn"
    @focusout="onFocusOut"
    @keydown="onKeyDown"
  >
    <slot />
    <span v-if="describe && hasContent" :id="descId" hidden>
      <slot name="content">{{ text }}</slot>
    </span>
  </span>
  <span v-else-if="describe && hasContent" :id="descId" hidden>
    <slot name="content">{{ text }}</slot>
  </span>
  <Teleport to="body">
    <Transition name="v-tooltip" :css="!instant">
      <div
        v-if="open"
        :id="id"
        ref="bubble"
        class="v-tooltip"
        role="tooltip"
        :data-side="side"
        :style="[floatingStyle, { zIndex: TOOLTIP_Z }]"
      >
        <slot name="content">{{ text }}</slot>
        <VKbd v-if="shortcut" :keys="shortcut" tone="inverse" size="sm" class="v-tooltip__kbd" />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.v-tooltip-anchor {
  display: contents;
}
.v-tooltip {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  max-width: 260px;
  padding: 5px var(--s-2);
  border-radius: var(--r-xs);
  background: var(--ink);
  color: var(--on-ink);
  box-shadow: var(--e2);
  font-family: var(--font-sans);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  letter-spacing: 0;
  text-wrap: balance;
  pointer-events: none;
  user-select: none;
}
.v-tooltip__kbd {
  margin-right: -3px;
}

.v-tooltip-enter-active,
.v-tooltip-leave-active {
  transition:
    opacity var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.v-tooltip-enter-from,
.v-tooltip-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
.v-tooltip-enter-from[data-side='top'] { transform: translateY(2px) scale(0.98); }
.v-tooltip-enter-from[data-side='bottom'] { transform: translateY(-2px) scale(0.98); }
.v-tooltip-enter-from[data-side='left'] { transform: translateX(2px) scale(0.98); }
.v-tooltip-enter-from[data-side='right'] { transform: translateX(-2px) scale(0.98); }
</style>
