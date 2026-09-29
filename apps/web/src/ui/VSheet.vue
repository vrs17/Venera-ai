<script lang="ts">
export type SheetCloseReason = 'escape' | 'outside' | 'button' | 'drag'
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useSlots } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'
import VIconButton from './VIconButton.vue'
import { useLayer } from './composables/useClickOutside'
import { getTabbables, useFocusTrap, useScrollLock } from './composables/useFocusTrap'
import { useId } from './composables/useId'
import { useIsPhone, usePrefersReducedMotion } from './composables/useMediaQuery'

/**
 * Modal panel: o'ng/chap yon panel, pastki "sheet" yoki markaziy oyna.
 *
 * Bu barcha modal overlay'larning YAGONA dvigateli: VDialog ham shu komponentni
 * `side="center"` bilan chizadi. Shuning uchun fokus tuzog'i, sahifa qulfi, qatlam
 * (Esc / tashqariga bosish / z-index), animatsiya va telefonda pastga tortib yopish
 * bir joyda. Telefonda (<768px) yon panel va markaziy oyna avtomatik pastki sheet'ga
 * aylanadi - element QAYTA yaratilmaydi, faqat sinfi o'zgaradi (yozilgan matn saqlanadi).
 *
 * Yopilish sabablari `close` hodisasida: 'escape' | 'outside' | 'button' | 'drag'.
 * `dismissible=false` - hech qaysi yo'l bilan yopilmaydi (masalan, yuborish paytida).
 * Qo'shimcha atributlar (`class`, `style`) PANELga tushadi.
 */
defineOptions({ inheritAttrs: false })

type Side = 'right' | 'left' | 'bottom' | 'center'

const props = withDefaults(
  defineProps<{
    side?: Side
    size?: 'sm' | 'md' | 'lg'
    width?: number | string
    title?: string
    description?: string
    ariaLabel?: string
    dismissible?: boolean
    closeOnEscape?: boolean
    closeOnOutside?: boolean
    hideClose?: boolean
    /** Telefonda pastki sheet'ga aylansinmi (standart: ha). */
    responsive?: boolean
    /** Ochilganda fokus: 'auto' | 'panel' | CSS selektor | funksiya. */
    initialFocus?: string | (() => HTMLElement | null | undefined)
    /** Tana ichki bo'shlig'i. */
    padding?: 'none' | 'md'
    /** Tasdiqlash oynalari uchun 'alertdialog'. */
    role?: 'dialog' | 'alertdialog'
    /** Ichki: qatlam turi (VDialog 'dialog' beradi - z-index darajasi). */
    layer?: 'sheet' | 'dialog'
  }>(),
  {
    side: 'right',
    size: 'md',
    dismissible: true,
    closeOnEscape: true,
    closeOnOutside: true,
    responsive: true,
    initialFocus: 'auto',
    padding: 'md',
    role: 'dialog',
    layer: 'sheet',
  },
)

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{
  close: [reason: SheetCloseReason]
  'after-enter': []
  'after-leave': []
}>()

defineSlots<{
  header?(props: { titleId: string; close: () => void }): unknown
  default?(props: { close: () => void }): unknown
  footer?(props: { close: () => void }): unknown
}>()

const { t } = useI18n({ useScope: 'global' })
const isPhone = useIsPhone()
const reduced = usePrefersReducedMotion()

const id = useId('v-sheet')
const titleId = `${id}-title`
const descId = `${id}-desc`
const panel = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)

const side = computed<Side>(() => (props.responsive && isPhone.value ? 'bottom' : props.side))

const WIDTHS: Record<'sheet' | 'center', Record<'sm' | 'md' | 'lg', number>> = {
  sheet: { sm: 480, md: 560, lg: 640 },
  center: { sm: 440, md: 560, lg: 720 },
}
const panelWidth = computed(() => {
  if (side.value === 'bottom') return undefined
  if (props.width !== undefined) return typeof props.width === 'number' ? `${props.width}px` : props.width
  return `${WIDTHS[side.value === 'center' ? 'center' : 'sheet'][props.size]}px`
})

// JS davomiyliklari tokens.css bilan mos: --dur-3 280 / --dur-2 180 / --dur-1 120.
const duration = computed(() => {
  if (reduced.value) return 0
  return side.value === 'center' ? { enter: 180, leave: 120 } : { enter: 280, leave: 180 }
})

function close(reason: SheetCloseReason) {
  if (!props.dismissible || !open.value) return
  open.value = false
  emit('close', reason)
}

const layer = useLayer(open, {
  kind: props.layer,
  modal: true,
  elements: () => [panel.value],
  onDismiss: (reason) => close(reason),
  closeOnEscape: () => props.dismissible && props.closeOnEscape,
  closeOnOutside: () => props.dismissible && props.closeOnOutside,
})

function pickInitialFocus(): HTMLElement | null | false {
  const box = panel.value
  if (!box) return null
  const wanted = props.initialFocus
  if (typeof wanted === 'function') return wanted() ?? box
  if (wanted === 'panel') return box
  if (wanted !== 'auto') return box.querySelector<HTMLElement>(wanted) ?? box
  const explicit = box.querySelector<HTMLElement>('[data-autofocus], [autofocus]')
  if (explicit) return explicit
  // Telefonda maydonga fokus berilsa klaviatura darhol ochilib, sheet'ning yarmini
  // yopadi - panelning o'ziga fokus beramiz. Yon panelda ham shunday: u odatda
  // ma'lumot ko'rsatadi, birinchi tugmaga "sakrash" chalg'itadi.
  if (side.value !== 'center') return box
  return getTabbables(body.value)[0] ?? getTabbables(box.querySelector('.v-sheet__foot'))[0] ?? box
}

useFocusTrap(panel, open, {
  initialFocus: pickInitialFocus,
  allowOutside: (node) => layer.contains(node),
})
useScrollLock(open)

/* ---- pastga tortib yopish (faqat pastki sheet) ---- */
let drag: { id: number; startY: number; y: number; lastY: number; lastT: number; v: number } | null = null

function isInteractive(el: EventTarget | null): boolean {
  return el instanceof Element && !!el.closest('button, a, input, textarea, select, [role="button"], [contenteditable]')
}

function onDragStart(e: PointerEvent) {
  if (side.value !== 'bottom' || !props.dismissible || e.button !== 0 || isInteractive(e.target)) return
  const el = panel.value
  if (!el) return
  drag = { id: e.pointerId, startY: e.clientY, y: 0, lastY: e.clientY, lastT: e.timeStamp, v: 0 }
  el.style.transition = 'none'
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
  window.addEventListener('pointercancel', onDragEnd)
}

function onDragMove(e: PointerEvent) {
  if (!drag || e.pointerId !== drag.id || !panel.value) return
  const dy = e.clientY - drag.startY
  // Yuqoriga tortilsa - kuchli qarshilik (sheet "cho'ziladi", lekin ko'tarilmaydi).
  drag.y = dy > 0 ? dy : dy * 0.15
  const dt = Math.max(1, e.timeStamp - drag.lastT)
  drag.v = (e.clientY - drag.lastY) / dt
  drag.lastY = e.clientY
  drag.lastT = e.timeStamp
  panel.value.style.transform = `translateY(${drag.y}px)`
}

function onDragEnd(e: PointerEvent) {
  if (!drag || e.pointerId !== drag.id) return
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
  window.removeEventListener('pointercancel', onDragEnd)
  const el = panel.value
  const { y, v } = drag
  drag = null
  if (!el) return
  const h = el.offsetHeight || 1
  if (y > h * 0.25 || (v > 0.5 && y > 16)) {
    // Joriy joyidan davom etib pastga ketsin (sinf animatsiyasi inline transform'ni
    // bosib o'tolmaydi - shuning uchun inline).
    el.style.transition = 'transform var(--dur-2) var(--ease-out)'
    el.style.transform = 'translateY(100%)'
    close('drag')
  } else {
    el.style.transition = 'transform var(--dur-3) var(--ease-sheet)'
    el.style.transform = ''
    el.addEventListener('transitionend', () => (el.style.transition = ''), { once: true })
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
  window.removeEventListener('pointercancel', onDragEnd)
})

const slots = useSlots()
const hasHeader = computed(() => !!props.title || !!props.description)
// Nom faqat haqiqiy sarlavhadan (faqat izoh bo'lsa - aria-label ishlatiladi).
const labelled = computed(() => !!props.title || !!slots.header)
const showClose = computed(() => props.dismissible && !props.hideClose)

defineExpose({ panel, body, close: () => close('button') })
</script>

<template>
  <Teleport to="body">
    <Transition
      name="v-sheet"
      :duration="duration"
      @after-enter="emit('after-enter')"
      @after-leave="emit('after-leave')"
    >
      <div v-if="open" class="v-sheet-root" :class="`is-${side}`" :style="{ zIndex: layer.zIndex.value }">
        <div class="v-sheet-scrim" aria-hidden="true" />
        <div
          ref="panel"
          v-bind="$attrs"
          class="v-sheet"
          :class="{ 'v-sheet--flush': padding === 'none' }"
          :role="role"
          aria-modal="true"
          :aria-labelledby="labelled ? titleId : undefined"
          :aria-label="labelled ? undefined : ariaLabel"
          :aria-describedby="description ? descId : undefined"
          tabindex="-1"
          :style="{ width: panelWidth }"
        >
          <div v-if="side === 'bottom' && dismissible" class="v-sheet__handle" aria-hidden="true" @pointerdown="onDragStart">
            <span />
          </div>
          <header
            v-if="hasHeader || $slots.header || showClose"
            class="v-sheet__head"
            :class="{ 'is-bare': !hasHeader && !$slots.header }"
            @pointerdown="onDragStart"
          >
            <div class="v-sheet__titles">
              <slot name="header" :title-id="titleId" :close="() => close('button')">
                <h2 v-if="title" :id="titleId" class="v-sheet__title">{{ title }}</h2>
                <p v-if="description" :id="descId" class="v-sheet__desc">{{ description }}</p>
              </slot>
            </div>
            <VIconButton
              v-if="showClose"
              class="v-sheet__close"
              :label="t('ui.close')"
              :icon="X"
              size="sm"
              tooltip-placement="bottom"
              @click="close('button')"
            />
          </header>
          <div ref="body" class="v-sheet__body">
            <slot :close="() => close('button')" />
          </div>
          <footer v-if="$slots.footer" class="v-sheet__foot">
            <slot name="footer" :close="() => close('button')" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.v-sheet-root {
  position: fixed;
  inset: 0;
  display: flex;
}
.v-sheet-root.is-right { justify-content: flex-end; }
.v-sheet-root.is-left { justify-content: flex-start; }
.v-sheet-root.is-bottom { align-items: flex-end; }
.v-sheet-root.is-center {
  align-items: center;
  justify-content: center;
  padding: var(--s-8) var(--s-4);
  /* Optik markaz geometrik markazdan biroz yuqorida. */
  padding-bottom: calc(var(--s-8) + 4vh);
}

.v-sheet-scrim {
  position: absolute;
  inset: 0;
  background: var(--overlay);
}

.v-sheet {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-width: 100%;
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--e3);
  outline: none;
  overscroll-behavior: contain;
}
.v-sheet:focus-visible {
  outline: none;
}

/* O'ng/chap: ekrandan 8px ichkarida "suzuvchi" panel. */
.is-right .v-sheet,
.is-left .v-sheet {
  height: calc(100% - var(--s-4));
  max-width: calc(100vw - var(--s-4));
  margin: var(--s-2);
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  overflow: hidden;
}
.is-center .v-sheet {
  width: 100%;
  max-height: 100%;
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  overflow: hidden;
}
.is-bottom .v-sheet {
  width: 100%;
  max-height: calc(100vh - var(--s-6));
  max-height: calc(100dvh - var(--s-6));
  border-top: 1px solid var(--line);
  border-radius: var(--r-xl) var(--r-xl) 0 0;
  overflow: hidden;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

.v-sheet__handle {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  height: 20px;
  margin-bottom: calc(var(--s-2) * -1);
  cursor: grab;
  touch-action: none;
}
.v-sheet__handle span {
  width: 36px;
  height: 4px;
  border-radius: var(--r-full);
  background: var(--line-strong);
}

.v-sheet__head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
  flex-shrink: 0;
  padding: var(--s-5) var(--s-5) var(--s-4) var(--s-6);
}
.is-center .v-sheet__head {
  padding: var(--s-6) var(--s-5) var(--s-2) var(--s-6);
}
.is-bottom .v-sheet__head {
  padding: var(--s-4) var(--s-4) var(--s-3) var(--s-5);
  touch-action: none;
}
.v-sheet__head.is-bare {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 1;
  padding: var(--s-4);
}
.is-bottom .v-sheet__head.is-bare {
  padding: var(--s-3);
}
/* Sarlavhasiz: tana × tugmasi ostiga kirib qolmasin. */
.v-sheet__head.is-bare + .v-sheet__body {
  padding-top: var(--s-6);
}
.v-sheet__titles {
  flex: 1;
  min-width: 0;
}
.v-sheet__title {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
  text-wrap: balance;
}
.v-sheet__desc {
  margin-top: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}
.v-sheet__close {
  margin: -4px -4px 0 0;
}

.v-sheet__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--s-2) var(--s-6) var(--s-6);
}
.is-bottom .v-sheet__body {
  padding: var(--s-1) var(--s-5) var(--s-5);
}
/* Markaziy oynada footer chiziqsiz - tana va tugmalar orasi ortiqcha bo'lmasin. */
.is-center .v-sheet__body:not(:last-child) {
  padding-bottom: var(--s-4);
}
.v-sheet--flush .v-sheet__body {
  padding: 0;
}

.v-sheet__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s-2);
  flex-shrink: 0;
  padding: var(--s-4) var(--s-6) var(--s-5);
  border-top: 1px solid var(--line);
}
.is-center .v-sheet__foot {
  border-top: 0;
  padding-top: var(--s-2);
}
.is-bottom .v-sheet__foot {
  padding: var(--s-3) var(--s-5) var(--s-4);
}
/* Telefonda pastki tugmalar teng kenglikda - bosh barmoq uchun katta nishon. */
.is-bottom .v-sheet__foot :slotted(*) {
  flex: 1 1 0;
}

/* ---- animatsiya ---- */
.v-sheet-enter-active .v-sheet-scrim {
  transition: opacity var(--dur-3) var(--ease-out);
}
.v-sheet-leave-active .v-sheet-scrim {
  transition: opacity var(--dur-2) var(--ease-out);
}
.v-sheet-enter-from .v-sheet-scrim,
.v-sheet-leave-to .v-sheet-scrim {
  opacity: 0;
}

.v-sheet-enter-active:not(.is-center) .v-sheet {
  transition: transform var(--dur-3) var(--ease-sheet);
}
.v-sheet-leave-active:not(.is-center) .v-sheet {
  transition: transform var(--dur-2) var(--ease-out);
}
.v-sheet-enter-from.is-right .v-sheet,
.v-sheet-leave-to.is-right .v-sheet {
  transform: translateX(calc(100% + var(--s-2)));
}
.v-sheet-enter-from.is-left .v-sheet,
.v-sheet-leave-to.is-left .v-sheet {
  transform: translateX(calc(-100% - var(--s-2)));
}
.v-sheet-enter-from.is-bottom .v-sheet,
.v-sheet-leave-to.is-bottom .v-sheet {
  transform: translateY(100%);
}

.v-sheet-enter-active.is-center .v-sheet-scrim {
  transition-duration: var(--dur-2);
}
.v-sheet-leave-active.is-center .v-sheet-scrim {
  transition-duration: var(--dur-1);
}
.v-sheet-enter-active.is-center .v-sheet {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.v-sheet-leave-active.is-center .v-sheet {
  transition:
    opacity var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.v-sheet-enter-from.is-center .v-sheet,
.v-sheet-leave-to.is-center .v-sheet {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}
</style>
