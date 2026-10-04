<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import VTooltip from './VTooltip.vue'
import type { ResizablePanel } from './composables/useResizablePanel'

/**
 * Panel chetidagi tortish tutqichi (`useResizablePanel` bilan juft).
 *
 * Joylashuvi: ota elementning O'NG chetida, chegaraning ustida markazlashgan
 * (8px bosish maydoni, ko'rinadigan chiziq 2px). Ota `position: relative` (yoki
 * sticky) bo'lishi va tutqichni KESMASLIGI kerak - shuning uchun panellarda kesish
 * (overflow) ichki o'ramada, tutqich esa undan tashqarida turadi.
 *
 * Klaviatura - WAI-ARIA "window splitter": ← / → 16px (Shift bilan 48px), Home - eng
 * tor, End - eng keng, Enter - yig'ish/ochish. Ikki marta bosish - standart kenglik.
 */
const props = defineProps<{
  panel: ResizablePanel
  /** Boshqariladigan panelning id si (aria-controls). */
  controls?: string
  label?: string
}>()

const { t } = useI18n({ useScope: 'global' })
const el = ref<HTMLElement | null>(null)

const collapsed = computed(() => props.panel.collapsed.value)
// Yig'iq panelda qiymat "eng tor" deb aytiladi, ekran o'quvchi esa matnni o'qiydi.
const valueNow = computed(() => (collapsed.value ? props.panel.min : props.panel.width.value))
</script>

<template>
  <div
    ref="el"
    class="v-resize"
    :class="{ 'is-dragging': panel.dragging.value }"
    role="separator"
    tabindex="0"
    aria-orientation="vertical"
    :aria-label="label ?? t('ui.panelWidth')"
    :aria-controls="controls"
    :aria-valuemin="panel.min"
    :aria-valuemax="panel.max"
    :aria-valuenow="valueNow"
    :aria-valuetext="collapsed ? t('ui.panelCollapsed') : undefined"
    @pointerdown="panel.onPointerDown"
    @keydown="panel.onKeyDown"
    @dblclick="panel.onDoubleClick"
  >
    <VTooltip
      :target="el"
      :text="t('ui.panelResizeHint')"
      placement="right"
      :disabled="panel.dragging.value"
      :describe="false"
    />
  </div>
</template>

<style scoped>
.v-resize {
  position: absolute;
  top: 0;
  bottom: 0;
  /* 8px maydon chegaraning ustida: yarmi panel ichida, yarmi tashqarida. */
  right: calc(var(--s-1) * -1);
  z-index: var(--z-sidebar);
  width: var(--s-2);
  cursor: col-resize;
  /* Barmoq bilan tortganda sahifa aylanmasin. */
  touch-action: none;
  outline: none;
}
.v-resize::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  translate: -50% 0;
  background: var(--line-strong);
  opacity: 0;
  transition:
    opacity var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out);
}
/* Chiziq kechikib chiqadi: sichqoncha chetdan shunchaki o'tib ketganda miltillamasin. */
@media (hover: hover) {
  .v-resize:hover::before {
    opacity: 1;
    transition-delay: var(--delay-hover);
  }
}
.v-resize:focus-visible::before {
  opacity: 1;
  background: var(--focus);
}
.v-resize.is-dragging::before {
  opacity: 1;
  background: var(--ink);
  transition-delay: 0s;
}
</style>
