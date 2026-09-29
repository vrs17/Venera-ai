<script lang="ts">
import type { Component } from 'vue'

export interface TabItem<T extends string | number = string> {
  value: T
  label: string
  icon?: Component
  /** Yorliq yonidagi son (masalan, "Yangi 3"). */
  count?: number
  disabled?: boolean
}
</script>

<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useId } from './composables/useId'
import { usePrefersReducedMotion } from './composables/useMediaQuery'

/**
 * Matnli tablar, ostida 2px siyoh chiziq suzib o'tadi (spec §3).
 *
 * WAI tabs naqshi: tablist / tab / tabpanel, avtomatik faollashtirish (strelka bilan
 * o'tish - darhol tanlash), Home/End. Default slot berilsa panelni ham shu komponent
 * chizadi (`role=tabpanel`, to'g'ri aria bog'lanishlari bilan): slot `{ value }` oladi.
 * Tor ekranda tablar gorizontal aylanadi, faol tab ko'rinishga suriladi.
 */
const props = withDefaults(
  defineProps<{
    tabs: TabItem<T>[]
    modelValue: T
    size?: 'sm' | 'md'
    ariaLabel?: string
  }>(),
  { size: 'md' },
)

const emit = defineEmits<{ 'update:modelValue': [value: T] }>()

defineSlots<{
  default?(props: { value: T }): unknown
}>()

const base = useId('v-tabs')
const tabId = (v: T) => `${base}-tab-${String(v).replace(/[^A-Za-z0-9_-]/g, '_')}`
const panelId = (v: T) => `${base}-panel-${String(v).replace(/[^A-Za-z0-9_-]/g, '_')}`

const list = ref<HTMLElement | null>(null)
const refs: (HTMLButtonElement | null)[] = []
function setRef(el: unknown, i: number) {
  refs[i] = el instanceof HTMLButtonElement ? el : null
}

const activeIndex = computed(() => props.tabs.findIndex((t) => t.value === props.modelValue))
const bar = ref<{ x: number; w: number } | null>(null)
const animate = ref(false)

function measure() {
  const el = refs[activeIndex.value]
  bar.value = el ? { x: el.offsetLeft, w: el.offsetWidth } : null
}

const reduced = usePrefersReducedMotion()

function reveal() {
  const el = refs[activeIndex.value]
  const box = list.value
  if (!el || !box || box.scrollWidth <= box.clientWidth) return
  const left = el.offsetLeft - 16
  const right = el.offsetLeft + el.offsetWidth + 16
  // JS `smooth` CSS'dagi reduced-motion qoidasiga bo'ysunmaydi - o'zimiz tekshiramiz.
  const behavior: ScrollBehavior = animate.value && !reduced.value ? 'smooth' : 'auto'
  if (left < box.scrollLeft) box.scrollTo({ left, behavior })
  else if (right > box.scrollLeft + box.clientWidth) box.scrollTo({ left: right - box.clientWidth, behavior })
}

watch(
  () => [activeIndex.value, props.tabs.length, props.tabs.map((t) => `${t.label}${t.count ?? ''}`).join('|')],
  async () => {
    await nextTick()
    measure()
    reveal()
  },
)

let ro: ResizeObserver | null = null
// `await` dan keyin komponent allaqachon yo'q bo'lishi mumkin - kuzatuvchi "yetim" qolmasin.
let alive = true
onMounted(async () => {
  measure()
  reveal()
  try {
    await document.fonts?.ready
  } catch {
    /* fonts API yo'q */
  }
  if (!alive) return
  measure()
  requestAnimationFrame(() => (animate.value = true))
  if (typeof ResizeObserver !== 'undefined' && list.value) {
    ro = new ResizeObserver(() => measure())
    ro.observe(list.value)
  }
})
onBeforeUnmount(() => {
  alive = false
  ro?.disconnect()
})

function select(i: number) {
  const tab = props.tabs[i]
  if (!tab || tab.disabled) return
  if (tab.value !== props.modelValue) emit('update:modelValue', tab.value)
}

function move(from: number, dir: 1 | -1): number {
  const n = props.tabs.length
  for (let step = 1; step <= n; step++) {
    const i = (from + dir * step + n) % n
    if (!props.tabs[i].disabled) return i
  }
  return from
}

function onKeyDown(e: KeyboardEvent, index: number) {
  let next = -1
  if (e.key === 'ArrowRight') next = move(index, 1)
  else if (e.key === 'ArrowLeft') next = move(index, -1)
  else if (e.key === 'Home') next = move(-1, 1)
  else if (e.key === 'End') next = move(props.tabs.length, -1)
  if (next < 0) return
  e.preventDefault()
  select(next)
  refs[next]?.focus()
}
</script>

<template>
  <div class="v-tabs" :class="`v-tabs--${size}`">
    <div class="v-tabs__rail">
      <div ref="list" class="v-tabs__list" role="tablist" :aria-label="ariaLabel">
        <button
          v-for="(tab, i) in tabs"
          :id="tabId(tab.value)"
          :key="String(tab.value)"
          :ref="(el) => setRef(el, i)"
          type="button"
          role="tab"
          class="v-tabs__tab"
          :class="{ 'is-on': i === activeIndex }"
          :aria-selected="i === activeIndex ? 'true' : 'false'"
          :aria-controls="$slots.default ? panelId(tab.value) : undefined"
          :tabindex="i === activeIndex || (activeIndex < 0 && i === 0) ? 0 : -1"
          :disabled="tab.disabled"
          @click="select(i)"
          @keydown="onKeyDown($event, i)"
        >
          <component :is="tab.icon" v-if="tab.icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
          <span>{{ tab.label }}</span>
          <span v-if="tab.count !== undefined" class="v-tabs__count">{{ tab.count }}</span>
        </button>
        <span
          v-if="bar"
          class="v-tabs__bar"
          :class="{ 'is-animated': animate }"
          :style="{ width: `${bar.w}px`, transform: `translateX(${bar.x}px)` }"
          aria-hidden="true"
        />
      </div>
    </div>
    <div
      v-if="$slots.default"
      :id="panelId(modelValue)"
      class="v-tabs__panel"
      role="tabpanel"
      :aria-labelledby="tabId(modelValue)"
      tabindex="0"
    >
      <slot :value="modelValue" />
    </div>
  </div>
</template>

<style scoped>
.v-tabs {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
/* Soch tolasi chiziq aylanmaydigan o'ramada (kontent chetiga tekis). Ro'yxat esa
   har tomonga 6px chiqadi: shu zaxirada fokus halqasi aylanish chegarasida kesilmaydi. */
.v-tabs__rail {
  min-width: 0;
  box-shadow: inset 0 -1px 0 var(--line);
}
.v-tabs__list {
  position: relative;
  display: flex;
  gap: var(--s-6);
  margin-inline: calc(var(--s-1_5) * -1);
  padding-inline: var(--s-1_5);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}
.v-tabs__list::-webkit-scrollbar {
  display: none;
}
.v-tabs--sm .v-tabs__list {
  gap: var(--s-5);
}
.v-tabs__tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  flex-shrink: 0;
  height: 40px;
  padding: 0;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  white-space: nowrap;
  transition: color var(--dur-1) var(--ease-out);
}
.v-tabs--sm .v-tabs__tab {
  height: 36px;
  font-size: 13px;
}
@media (hover: hover) {
  .v-tabs__tab:not(:disabled):not(.is-on):hover {
    color: var(--text-2);
  }
}
.v-tabs__tab.is-on {
  color: var(--text);
}
.v-tabs__tab:disabled {
  color: var(--text-4);
  cursor: default;
}
/* Tabda ichki bo'shliq yo'q (chiziq matn kengligida) - oddiy outline matnga
   yopishib qolardi. Halqa yozuv atrofida, chiziqdan yuqorida chiziladi. */
.v-tabs__tab:focus-visible {
  outline: none;
}
.v-tabs__tab:focus-visible::before {
  content: '';
  position: absolute;
  inset: var(--s-1_5) calc(var(--s-1_5) * -1);
  border-radius: var(--r-xs);
  box-shadow: 0 0 0 2px var(--focus);
  pointer-events: none;
}
.v-tabs__count {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--r-full);
  background: var(--fill);
  /* --text-3 --fill ustida 4.2:1 - 11px raqam uchun AA yetmaydi. */
  color: var(--text-2);
  font-size: 11px;
  line-height: 1;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.v-tabs__tab.is-on .v-tabs__count {
  background: var(--fill-hover);
  color: var(--text);
}
.v-tabs__bar {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--ink);
  pointer-events: none;
}
.v-tabs__bar.is-animated {
  transition:
    transform var(--dur-2) var(--ease-out),
    width var(--dur-2) var(--ease-out);
}
.v-tabs__panel {
  min-width: 0;
  padding-top: var(--s-4);
}
.v-tabs__panel:focus-visible {
  outline-offset: 4px;
}
</style>
