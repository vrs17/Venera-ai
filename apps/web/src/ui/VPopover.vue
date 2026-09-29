<script lang="ts">
export interface PopoverFocusContext {
  /** Ochilish klaviatura bilan bo'ldimi (Enter/Space/strelka). */
  keyboard: boolean
}
export type PopoverAutoFocus =
  | 'first'
  | 'panel'
  | 'none'
  | ((ctx: PopoverFocusContext) => HTMLElement | null | undefined)
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useFloating } from './composables/useFloating'
import type { FloatingAnchor, Placement } from './composables/useFloating'
import { useLayer } from './composables/useClickOutside'
import { focusElement, getTabbables } from './composables/useFocusTrap'
import { useId } from './composables/useId'

/**
 * Suzuvchi panel: sirt, e2 soya, 12px burchak. VMenu va VSelect shu ustiga qurilgan.
 *
 * Ikki xil ulanish:
 * 1. `#trigger` slot - ichidagi element bosilganda ochiladi/yopiladi; unga
 *    aria-expanded / aria-haspopup / aria-controls avtomatik qo'yiladi.
 * 2. `anchor` prop - tashqi element (yoki virtual nuqta); ochish/yopish `v-model:open`
 *    orqali, ARIA'ni chaqiruvchi o'zi boshqaradi (VSelect shunday).
 *
 * Yopilish: Esc, tashqariga bosish (qatlam steki bo'yicha - ichma-ich overlay'lar
 * to'g'ri ishlaydi), fokus paneldan tashqariga chiqsa. Esc'dan keyin fokus trigger'ga
 * qaytadi; tashqariga bosilganda esa foydalanuvchi bosgan joyda qoladi.
 *
 * Qo'shimcha atributlar (class, style, @keydown) PANELga tushadi.
 */
defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    anchor?: FloatingAnchor | null
    placement?: Placement
    offset?: number
    matchWidth?: boolean
    width?: number | string
    role?: string
    ariaLabel?: string
    ariaLabelledby?: string
    haspopup?: 'dialog' | 'menu' | 'listbox' | 'true'
    padding?: 'none' | 'sm' | 'md'
    autoFocus?: PopoverAutoFocus
    returnFocus?: boolean
    closeOnEscape?: boolean
    closeOnOutside?: boolean
    closeOnFocusOut?: boolean
    disabled?: boolean
  }>(),
  {
    anchor: null,
    placement: 'bottom-start',
    offset: 6,
    role: 'dialog',
    padding: 'sm',
    autoFocus: 'first',
    returnFocus: true,
    closeOnEscape: true,
    closeOnOutside: true,
    closeOnFocusOut: true,
  },
)

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{
  'trigger-keydown': [e: KeyboardEvent]
  'after-leave': []
}>()

defineSlots<{
  trigger?(props: { open: boolean; toggle: () => void }): unknown
  default?(props: { close: () => void }): unknown
}>()

const panelId = useId('v-popover')
const wrapper = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLElement | null>(null)
let viaKeyboard = false
// Tashqariga bosib yopilganda fokus foydalanuvchi bosgan joyda qolsin.
let skipReturn = false

function resolveTrigger(): HTMLElement | null {
  let el = wrapper.value?.firstElementChild as HTMLElement | null
  while (el && el.hasAttribute('data-v-contents')) el = el.firstElementChild as HTMLElement | null
  return el
}

const anchorEl = computed<FloatingAnchor | null>(() => props.anchor ?? triggerEl.value)

const { style: floatingStyle, side } = useFloating(anchorEl, panel, {
  open,
  placement: () => props.placement,
  offset: () => props.offset,
  matchWidth: () => props.matchWidth,
})

const layer = useLayer(open, {
  kind: 'popover',
  elements: () => [panel.value, anchorEl.value instanceof Element ? anchorEl.value : null],
  onDismiss: (reason) => hide(reason === 'escape'),
  closeOnEscape: () => props.closeOnEscape,
  closeOnOutside: () => props.closeOnOutside,
})

const haspopupValue = computed(() => {
  if (props.haspopup) return props.haspopup
  return props.role === 'menu' || props.role === 'listbox' ? props.role : 'dialog'
})

function syncTriggerAria() {
  const el = triggerEl.value
  if (!el || props.anchor) return
  el.setAttribute('aria-haspopup', haspopupValue.value)
  el.setAttribute('aria-expanded', open.value ? 'true' : 'false')
  if (open.value) el.setAttribute('aria-controls', panelId)
  else el.removeAttribute('aria-controls')
}

function show(keyboard = false) {
  if (props.disabled) return
  viaKeyboard = keyboard
  triggerEl.value = resolveTrigger() ?? triggerEl.value
  open.value = true
}

function hide(restoreFocus = true) {
  if (!open.value) return
  skipReturn = !restoreFocus
  open.value = false
}

function toggle() {
  if (open.value) hide()
  else show(false)
}

function onTriggerClick(e: MouseEvent) {
  if (props.disabled || e.defaultPrevented) return
  // Klaviaturadan kelgan "click" (Enter/Space) da `detail` 0 bo'ladi.
  if (open.value) hide()
  else show(e.detail === 0)
}

function onTriggerKeyDown(e: KeyboardEvent) {
  emit('trigger-keydown', e)
}

function onFocusOut(e: FocusEvent) {
  if (!props.closeOnFocusOut || !open.value) return
  const to = e.relatedTarget
  // relatedTarget yo'q - oyna fokusni yo'qotdi yoki Safari tugmaga fokus bermadi:
  // yopmaymiz (aks holda trigger bosilganda yopilib-qayta ochilardi).
  if (!(to instanceof Node)) return
  if (panel.value?.contains(to) || triggerEl.value?.contains(to) || layer.contains(to)) return
  hide(false)
}

async function applyAutoFocus() {
  await nextTick()
  const box = panel.value
  if (!box || !open.value) return
  const mode = props.autoFocus
  if (typeof mode === 'function') {
    const el = mode({ keyboard: viaKeyboard })
    if (!focusElement(el)) focusElement(box)
  } else if (mode === 'first') {
    if (!focusElement(getTabbables(box)[0])) focusElement(box)
  } else if (mode === 'panel') {
    focusElement(box)
  }
}

// Fokusni qaytarish shu yerda (hide() da emas): chaqiruvchi `v-model:open` ni o'zi
// false qilsa ham ishlasin. `pre` watcher - panel hali DOM'da, fokus uning ichida.
function restoreFocus() {
  const active = document.activeElement
  const inside = !!panel.value && !!active && panel.value.contains(active)
  const target = (anchorEl.value instanceof HTMLElement ? anchorEl.value : null) ?? triggerEl.value
  if (!skipReturn && props.returnFocus && (inside || active === document.body)) focusElement(target)
  skipReturn = false
}

watch(open, (on) => {
  syncTriggerAria()
  if (on) {
    if (!triggerEl.value) triggerEl.value = resolveTrigger()
    void applyAutoFocus()
  } else {
    restoreFocus()
    viaKeyboard = false
  }
})

onMounted(() => {
  triggerEl.value = resolveTrigger()
  syncTriggerAria()
})
onBeforeUnmount(() => {
  triggerEl.value?.removeAttribute('aria-expanded')
  triggerEl.value?.removeAttribute('aria-controls')
})

const panelStyle = computed(() => [
  floatingStyle.value,
  { zIndex: layer.zIndex.value },
  props.width !== undefined ? { width: typeof props.width === 'number' ? `${props.width}px` : props.width } : null,
])

defineExpose({ panel, triggerEl, show, hide, toggle })
</script>

<template>
  <span
    v-if="$slots.trigger"
    ref="wrapper"
    class="v-popover-trigger"
    data-v-contents
    @click="onTriggerClick"
    @keydown="onTriggerKeyDown"
  >
    <slot name="trigger" :open="open" :toggle="toggle" />
  </span>
  <Teleport to="body">
    <Transition name="v-pop" @after-leave="emit('after-leave')">
      <div
        v-if="open"
        :id="panelId"
        ref="panel"
        v-bind="$attrs"
        class="v-popover"
        :class="`v-popover--pad-${padding}`"
        :role="role"
        :aria-label="ariaLabel"
        :aria-labelledby="ariaLabelledby"
        :data-side="side"
        tabindex="-1"
        :style="panelStyle"
        @focusout="onFocusOut"
      >
        <slot :close="hide" />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.v-popover-trigger {
  display: contents;
}
.v-popover {
  box-sizing: border-box;
  max-width: calc(100vw - 16px);
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  box-shadow: var(--e2);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  outline: none;
}
.v-popover:focus-visible {
  outline: none;
}
.v-popover--pad-none { padding: 0; }
.v-popover--pad-sm { padding: var(--s-1_5); }
.v-popover--pad-md { padding: var(--s-4); }

.v-pop-enter-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.v-pop-leave-active {
  transition:
    opacity var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.v-pop-enter-from,
.v-pop-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
.v-pop-enter-from[data-side='bottom'] { transform: translateY(-4px) scale(0.98); }
.v-pop-enter-from[data-side='top'] { transform: translateY(4px) scale(0.98); }
.v-pop-enter-from[data-side='left'] { transform: translateX(4px) scale(0.98); }
.v-pop-enter-from[data-side='right'] { transform: translateX(-4px) scale(0.98); }
</style>
