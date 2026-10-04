<script lang="ts">
import type { Component } from 'vue'

export interface SegmentedOption<T extends string | number = string> {
  value: T
  label: string
  icon?: Component
  disabled?: boolean
}
</script>

<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import VTooltip from './VTooltip.vue'

/**
 * Segmentli tanlov (Hammasi · Web · Mini App · Bot; Yorug' · Qorong'i · Tizim).
 * Tanlangan segment ostida siyoh "slayder" suzib o'tadi.
 *
 * Slayder o'lchami JS'da o'lchanadi (segmentlar kengligi matnga bog'liq, 4 tilda har
 * xil). Birinchi o'lchashda animatsiya YO'Q - sahifa ochilganda slayder 0 dan "uchib
 * kelmasin". Keyingi o'zgarishlarda transform + width silliq o'tadi.
 *
 * ARIA: radiogroup / radio, strelkalar tanlovni ham o'zgartiradi (WAI radio naqshi).
 * `iconOnly` - faqat belgi, yozuv aria-label + tooltip bo'ladi.
 */
const props = withDefaults(
  defineProps<{
    options: SegmentedOption<T>[]
    modelValue?: T | null
    size?: 'sm' | 'md'
    block?: boolean
    iconOnly?: boolean
    disabled?: boolean
    ariaLabel?: string
  }>(),
  { modelValue: null, size: 'md' },
)

const emit = defineEmits<{ 'update:modelValue': [value: T] }>()

const root = ref<HTMLElement | null>(null)
const refs: (HTMLButtonElement | null)[] = []
function setRef(el: unknown, i: number) {
  refs[i] = el instanceof HTMLButtonElement ? el : null
}

const activeIndex = computed(() => props.options.findIndex((o) => o.value === props.modelValue))
const thumb = ref<{ x: number; w: number } | null>(null)
const animate = ref(false)

function measure() {
  const el = refs[activeIndex.value]
  if (!el || !root.value) {
    thumb.value = null
    return
  }
  thumb.value = { x: el.offsetLeft, w: el.offsetWidth }
}

watch(
  () => [activeIndex.value, props.options.length, props.size],
  async () => {
    await nextTick()
    measure()
  },
)

let ro: ResizeObserver | null = null
// `await` dan keyin komponent allaqachon yo'q bo'lishi mumkin - kuzatuvchi "yetim" qolmasin.
let alive = true
onMounted(async () => {
  measure()
  // Shrift yuklangach kengliklar o'zgaradi - qayta o'lchaymiz, keyin animatsiyani yoqamiz.
  try {
    await document.fonts?.ready
  } catch {
    /* fonts API yo'q */
  }
  if (!alive) return
  measure()
  requestAnimationFrame(() => (animate.value = true))
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    ro = new ResizeObserver(() => measure())
    ro.observe(root.value)
  }
})
onBeforeUnmount(() => {
  alive = false
  ro?.disconnect()
})

function select(i: number) {
  const opt = props.options[i]
  if (!opt || opt.disabled || props.disabled) return
  if (opt.value !== props.modelValue) emit('update:modelValue', opt.value)
}

function move(from: number, dir: 1 | -1): number {
  const n = props.options.length
  for (let step = 1; step <= n; step++) {
    const i = (from + dir * step + n) % n
    if (!props.options[i].disabled) return i
  }
  return from
}

function onKeyDown(e: KeyboardEvent, index: number) {
  let next = -1
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = move(index, 1)
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = move(index, -1)
  else if (e.key === 'Home') next = move(-1, 1)
  else if (e.key === 'End') next = move(props.options.length, -1)
  if (next < 0) return
  e.preventDefault()
  select(next)
  refs[next]?.focus()
}

// Tanlov bo'lmasa birinchi yoqilgan segment Tab to'xtashi bo'ladi.
const tabStop = computed(() => (activeIndex.value >= 0 ? activeIndex.value : props.options.findIndex((o) => !o.disabled)))
</script>

<template>
  <div
    ref="root"
    class="v-seg"
    :class="[`v-seg--${size}`, { 'v-seg--block': block, 'v-seg--icon': iconOnly, 'is-disabled': disabled }]"
    role="radiogroup"
    :aria-label="ariaLabel"
    :aria-disabled="disabled ? 'true' : undefined"
  >
    <span
      v-if="thumb"
      class="v-seg__thumb"
      :class="{ 'is-animated': animate }"
      :style="{ width: `${thumb.w}px`, transform: `translateX(${thumb.x}px)` }"
      aria-hidden="true"
    />
    <template v-for="(opt, i) in options" :key="String(opt.value)">
      <VTooltip :text="opt.label" :disabled="!iconOnly" :describe="false">
        <button
          :ref="(el) => setRef(el, i)"
          type="button"
          role="radio"
          class="v-seg__item"
          :class="{ 'is-on': i === activeIndex }"
          :aria-checked="i === activeIndex ? 'true' : 'false'"
          :aria-label="iconOnly ? opt.label : undefined"
          :disabled="disabled || opt.disabled"
          :tabindex="i === tabStop ? 0 : -1"
          @click="select(i)"
          @keydown="onKeyDown($event, i)"
        >
          <component
            :is="opt.icon"
            v-if="opt.icon"
            :size="size === 'sm' ? 14 : 16"
            :stroke-width="1.75"
            aria-hidden="true"
          />
          <span v-if="!iconOnly" class="v-seg__label">{{ opt.label }}</span>
        </button>
      </VTooltip>
    </template>
  </div>
</template>

<style scoped>
.v-seg {
  --seg-h: 32px;
  --seg-pad: 2px;
  position: relative;
  display: inline-flex;
  align-items: stretch;
  height: var(--seg-h);
  padding: var(--seg-pad);
  border-radius: var(--r-sm);
  background: var(--fill);
  isolation: isolate;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}
.v-seg::-webkit-scrollbar {
  display: none;
}
.v-seg--sm {
  --seg-h: 28px;
}
/* Barmoq uchun kattaroq nishon (filtr chip'lari bilan bir balandlikda). */
@media (pointer: coarse) {
  .v-seg {
    --seg-h: 36px;
  }
  .v-seg--sm {
    --seg-h: 32px;
  }
}
.v-seg--block {
  display: flex;
  width: 100%;
}
.v-seg--block .v-seg__item {
  flex: 1 1 0;
  /* Teng bo'laklar tor ekranda (360px, 4 segment) "Hammasi" ni kesib qo'ymasin. */
  padding: 0 var(--s-2);
}
.v-seg.is-disabled {
  opacity: 0.5;
}

.v-seg__thumb {
  position: absolute;
  top: var(--seg-pad);
  bottom: var(--seg-pad);
  left: 0;
  z-index: -1;
  border-radius: var(--r-xs);
  background: var(--ink);
  box-shadow: var(--e1);
  will-change: transform;
}
.v-seg__thumb.is-animated {
  transition:
    transform var(--dur-2) var(--ease-out),
    width var(--dur-2) var(--ease-out);
}

.v-seg__item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-1_5);
  min-width: 0;
  padding: 0 var(--s-3);
  border-radius: var(--r-xs);
  color: var(--text-2);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  touch-action: manipulation;
  transition: color var(--dur-2) var(--ease-out);
}
.v-seg--sm .v-seg__item {
  padding: 0 10px;
  font-size: var(--fs-caption);
}
.v-seg--icon .v-seg__item {
  width: calc(var(--seg-h) + 4px);
  padding: 0;
}
@media (hover: hover) {
  .v-seg__item:not(:disabled):not(.is-on):hover {
    color: var(--text);
  }
}
.v-seg__item.is-on {
  color: var(--on-ink);
}
.v-seg__item:disabled {
  color: var(--text-4);
  cursor: default;
}
/* Halqa ICHKARIDA: ildiz `overflow-x: auto` - tashqi halqa kesilib qolardi.
   Tanlangan segmentda fon siyoh, siyoh halqa ko'rinmaydi - teskari rangli ichki
   halqa (siyoh chegara + --on-ink chiziq) ishlatamiz. */
.v-seg__item:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
  border-radius: var(--r-xs);
}
.v-seg__item.is-on:focus-visible {
  outline-color: var(--on-ink);
  outline-offset: -4px;
  border-radius: calc(var(--r-xs) - 2px);
}
.v-seg__label {
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
