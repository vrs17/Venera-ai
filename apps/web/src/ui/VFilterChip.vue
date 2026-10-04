<script lang="ts">
import type { Component } from 'vue'

export interface FilterOption<T extends string | number | boolean = string> {
  value: T
  label: string
  icon?: Component
  /** Kichik rangli nuqta - CSS qiymati, masalan `'var(--ch-web)'` (kanal ranglari). */
  dot?: string
  /** O'ng chetda kulrang izoh (odatda soni). */
  hint?: string
  disabled?: boolean
}
</script>

<script setup lang="ts" generic="T extends string | number | boolean">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Search, X } from 'lucide-vue-next'
import VPopover from './VPopover.vue'
import VSpinner from './VSpinner.vue'
import VTooltip from './VTooltip.vue'
import { FILTER_BAR_KEY } from './VFilterBar.vue'
import type { Placement } from './composables/useFloating'
import { useId } from './composables/useId'
import { normalizeSearch } from './useCommandPalette'

/**
 * Filtr "tabletkasi" (spec §3, VFilterBar ichida).
 *
 * - Faol emas: soch tolasi chegarali tabletka, yorliq --text-2 va kichik ▾.
 * - Faol: --fill fon, "Yorliq: Qiymat" siyoh rangida va o'ng tomonda × (tozalash).
 *   Bir nechta tanlovda: "Web, Bot" yoki "Web +2".
 * - Bosilganda ro'yxat (listbox) ochiladi: bitta tanlov - tanlagach yopiladi (tanlangan
 *   qatorni qayta bosish - bekor qiladi); `multiple` - ochiq qoladi, chapda belgi katak.
 *   Variant ko'p bo'lsa (> 7) tepada qidiruv maydoni chiqadi; `remote` bilan filtrlash
 *   ota komponentga (`@search`) topshiriladi.
 * - `toggle`: ro'yxatsiz, yoqish/o'chirish tugmasi ("Faqat xabar berilganlar").
 *
 * Klaviatura: ro'yxatda fokus bitta joyda (qidiruv maydoni yoki ro'yxatning o'zi),
 * faol qator `aria-activedescendant` bilan; ↑ ↓ Home End PageUp PageDown, harf terish,
 * Enter (va qidiruvsiz rejimda Space) - tanlash, Esc - yopish, Tab - chiqish.
 */
const props = withDefaults(
  defineProps<{
    label: string
    options?: FilterOption<T>[]
    modelValue?: T | T[] | null
    multiple?: boolean
    toggle?: boolean
    icon?: Component
    /** Qidiruv maydoni; berilmasa - variantlar 7 tadan ko'p bo'lsa. */
    searchable?: boolean
    /** Variantlar serverdan: mahalliy filtrlash yo'q, `search` hodisasi chiqadi. */
    remote?: boolean
    loading?: boolean
    searchPlaceholder?: string
    /** Faol qiymat matnini o'zingiz yasash (masalan, "≥ 3 s"). */
    formatValue?: (selected: FilterOption<T>[], values: T[]) => string
    disabled?: boolean
    placement?: Placement
  }>(),
  { options: () => [], modelValue: null, searchable: undefined, placement: 'bottom-start' },
)

const emit = defineEmits<{
  'update:modelValue': [value: T | T[] | null]
  change: [value: T | T[] | null]
  clear: []
  search: [query: string]
}>()

const { t } = useI18n({ useScope: 'global' })
const bar = inject(FILTER_BAR_KEY, null)

const id = useId('v-fchip')
const listId = `${id}-list`
const optionId = (i: number) => `${id}-opt-${i}`

const mainBtn = ref<HTMLButtonElement | null>(null)
const pop = ref<InstanceType<typeof VPopover> | null>(null)
const listEl = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)
const open = ref(false)
const query = ref('')
const active = ref(-1)

/* ---- qiymatlar ---- */
const values = computed<T[]>(() => {
  const v = props.modelValue
  if (Array.isArray(v)) return v
  return v === null || v === undefined ? [] : [v]
})
const isSelected = (v: T) => values.value.includes(v)

const isActive = computed(() => (props.toggle ? props.modelValue === true : values.value.length > 0))

const selectedOptions = computed(() =>
  values.value.map(
    (v) => props.options.find((o) => o.value === v) ?? ({ value: v, label: String(v) } as FilterOption<T>),
  ),
)

const valueText = computed(() => {
  if (props.toggle || !isActive.value) return ''
  if (props.formatValue) return props.formatValue(selectedOptions.value, values.value)
  const labels = selectedOptions.value.map((o) => o.label)
  if (labels.length === 1) return labels[0]
  // Ikkitasi qisqa bo'lsa - to'liq; aks holda birinchisi va qolganlar soni.
  if (labels.length === 2 && labels[0].length + labels[1].length <= 18) return `${labels[0]}, ${labels[1]}`
  return `${labels[0]} +${labels.length - 1}`
})

// Bitta qiymat tanlanganda uning nuqtasi/belgisi chip'da ham ko'rinadi (kanal rangi).
const lead = computed(() => (values.value.length === 1 && !props.toggle ? selectedOptions.value[0] : null))

/* ---- VFilterBar bilan bog'lanish ---- */
function emitValue(v: T | T[] | null) {
  emit('update:modelValue', v)
  emit('change', v)
}

function emptyValue(): T | T[] | null {
  if (props.toggle) return false as T
  return props.multiple ? [] : null
}

function clear(refocus = false) {
  if (!isActive.value) return
  emitValue(emptyValue())
  emit('clear')
  if (refocus) void nextTick(() => mainBtn.value?.focus())
}

const unregister = bar?.register({ active: () => isActive.value, clear: () => clear(false) })
onBeforeUnmount(() => unregister?.())

/* ---- ro'yxat ---- */
const isSearchable = computed(() => !props.toggle && (props.searchable ?? props.options.length > 7))

const visible = computed(() => {
  const q = normalizeSearch(query.value.trim())
  if (!q || props.remote) return props.options
  return props.options.filter((o) => normalizeSearch(o.label).includes(q))
})

function enabledFrom(from: number, dir: 1 | -1): number {
  const list = visible.value
  for (let i = from; i >= 0 && i < list.length; i += dir) if (!list[i].disabled) return i
  return -1
}

function resetActive() {
  const list = visible.value
  const sel = list.findIndex((o) => isSelected(o.value) && !o.disabled)
  active.value = sel >= 0 ? sel : enabledFrom(0, 1)
}

function choose(i: number) {
  const opt = visible.value[i]
  if (!opt || opt.disabled) return
  active.value = i
  if (props.multiple) {
    const cur = values.value
    emitValue(isSelected(opt.value) ? cur.filter((v) => v !== opt.value) : [...cur, opt.value])
    return
  }
  emitValue(isSelected(opt.value) ? null : opt.value)
  open.value = false
}

function step(dir: 1 | -1, by = 1) {
  const list = visible.value
  let i = active.value
  for (let moved = 0; moved < by; ) {
    const next = i + dir
    if (next < 0 || next >= list.length) break
    i = next
    if (!list[i].disabled) {
      moved++
      active.value = i
    }
  }
}

/* harf bilan qidirish (qidiruv maydoni yo'q rejimda) */
let buffer = ''
let bufferTimer: ReturnType<typeof setTimeout> | undefined
function typeahead(ch: string) {
  clearTimeout(bufferTimer)
  buffer += ch.toLocaleLowerCase()
  bufferTimer = setTimeout(() => (buffer = ''), 500)
  const list = visible.value
  const n = list.length
  const same = [...buffer].every((c) => c === buffer[0])
  const q = same ? buffer[0] : buffer
  const start = same ? active.value + 1 : Math.max(active.value, 0)
  for (let k = 0; k < n; k++) {
    const i = (((start + k) % n) + n) % n
    if (!list[i].disabled && normalizeSearch(list[i].label).startsWith(q)) {
      active.value = i
      return
    }
  }
}

// Klaviatura panel darajasida tinglanadi (VPopover @keydown): fokus qidiruv
// maydonida, ro'yxatda yoki (bo'sh joy bosilganda) panelning o'zida bo'lsa ham ishlaydi.
function onListKeyDown(e: KeyboardEvent) {
  if (e.isComposing || e.defaultPrevented) return
  const inInput = e.target === searchEl.value
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      if (active.value < 0) active.value = enabledFrom(0, 1)
      else step(1)
      return
    case 'ArrowUp':
      e.preventDefault()
      if (active.value < 0) active.value = enabledFrom(visible.value.length - 1, -1)
      else step(-1)
      return
    case 'PageDown':
      e.preventDefault()
      step(1, 8)
      return
    case 'PageUp':
      e.preventDefault()
      step(-1, 8)
      return
    case 'Home':
    case 'End':
      // Qidiruv maydonida Home/End kursorni suradi - tegmaymiz.
      if (inInput) return
      e.preventDefault()
      active.value = e.key === 'Home' ? enabledFrom(0, 1) : enabledFrom(visible.value.length - 1, -1)
      return
    case 'Enter':
      e.preventDefault()
      if (active.value >= 0) choose(active.value)
      return
    case ' ':
      if (inInput) return
      e.preventDefault()
      if (buffer) typeahead(' ')
      else if (active.value >= 0) choose(active.value)
      return
  }
  if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey || inInput) return
  if (isSearchable.value) {
    // Fokus qidiruv maydonidan tashqarida - harfni o'sha maydonga yo'naltiramiz
    // (keydown paytida fokus o'tsa, belgi yangi maydonga tushadi).
    searchEl.value?.focus()
    return
  }
  e.preventDefault()
  typeahead(e.key)
}

/* sichqoncha: faqat haqiqiy harakatda ta'kidlaymiz (klaviatura bilan aylantirilganda
   kursor ostidagi qator ta'kidni "o'g'irlamasin") */
let lastPointer = { x: -1, y: -1 }
let fromPointer = false
function onPointerMove(i: number, e: PointerEvent) {
  if (e.clientX === lastPointer.x && e.clientY === lastPointer.y) return
  lastPointer = { x: e.clientX, y: e.clientY }
  if (!visible.value[i]?.disabled && active.value !== i) {
    fromPointer = true
    active.value = i
  }
}

watch(active, (i) => {
  if (fromPointer) {
    fromPointer = false
    return
  }
  if (i < 0) return
  void nextTick(() => document.getElementById(optionId(i))?.scrollIntoView({ block: 'nearest' }))
})

/* qidiruv matni */
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(query, (q) => {
  resetActive()
  if (!props.remote) return
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => emit('search', q.trim()), 200)
})
// Server yangi variantlar bersa - faol qator chegaradan chiqib ketmasin.
watch(
  () => props.options,
  () => {
    if (open.value && active.value >= visible.value.length) resetActive()
  },
)

watch(open, (on) => {
  if (on) {
    resetActive()
    lastPointer = { x: -1, y: -1 }
  } else {
    clearTimeout(searchTimer)
    if (query.value) {
      query.value = ''
      if (props.remote) emit('search', '')
    }
  }
})

onBeforeUnmount(() => {
  clearTimeout(bufferTimer)
  clearTimeout(searchTimer)
})

// Yopiq chip'da ↓ / ↑ - ro'yxatni klaviatura rejimida ochadi (WAI listbox tugmasi).
function onTriggerKeyDown(e: KeyboardEvent) {
  if (open.value || props.disabled || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return
  e.preventDefault()
  pop.value?.show(true)
}

function focusOnOpen(): HTMLElement | null {
  return isSearchable.value ? searchEl.value : listEl.value
}

const activeId = computed(() => (open.value && active.value >= 0 ? optionId(active.value) : undefined))

/* ---- toggle rejimi ---- */
function onToggleClick() {
  if (props.disabled) return
  emitValue((props.modelValue !== true) as T)
}

const clearLabel = computed(() => t('ui.clearFilter', { label: props.label }))
</script>

<template>
  <span
    class="v-fchip"
    :class="{ 'is-active': isActive, 'is-open': open, 'is-disabled': disabled }"
  >
    <!-- toggle: ro'yxatsiz -->
    <button
      v-if="toggle"
      ref="mainBtn"
      type="button"
      class="v-fchip__main"
      :aria-pressed="isActive ? 'true' : 'false'"
      :disabled="disabled"
      @click="onToggleClick"
    >
      <Check v-if="isActive" class="v-fchip__lead" :size="14" :stroke-width="2.25" aria-hidden="true" />
      <component :is="icon" v-else-if="icon" class="v-fchip__lead" :size="14" :stroke-width="1.75" aria-hidden="true" />
      <span class="v-fchip__label">{{ label }}</span>
    </button>

    <VPopover
      v-else
      ref="pop"
      v-model:open="open"
      :role="isSearchable ? 'dialog' : 'presentation'"
      :haspopup="isSearchable ? 'dialog' : 'listbox'"
      :aria-label="isSearchable ? label : undefined"
      :placement="placement"
      :offset="6"
      padding="none"
      :disabled="disabled"
      :auto-focus="focusOnOpen"
      @keydown="onListKeyDown"
      @trigger-keydown="onTriggerKeyDown"
    >
      <template #trigger>
        <button ref="mainBtn" type="button" class="v-fchip__main" :disabled="disabled">
          <component :is="icon" v-if="icon" class="v-fchip__lead" :size="14" :stroke-width="1.75" aria-hidden="true" />
          <template v-if="isActive">
            <span class="v-fchip__key">{{ label }}:</span>
            <span v-if="lead?.dot" class="v-fchip__dot v-fchip__dot--value" :style="{ background: lead.dot }" aria-hidden="true" />
            <component
              :is="lead.icon"
              v-else-if="lead?.icon"
              class="v-fchip__vicon"
              :size="14"
              :stroke-width="1.75"
              aria-hidden="true"
            />
            <span class="v-fchip__value">{{ valueText }}</span>
          </template>
          <template v-else>
            <span class="v-fchip__label">{{ label }}</span>
            <ChevronDown class="v-fchip__chev" :size="14" :stroke-width="1.75" aria-hidden="true" />
          </template>
        </button>
      </template>

      <div class="v-fchip__panel">
        <div v-if="isSearchable" class="v-fchip__search">
          <VSpinner v-if="loading" :size="14" />
          <Search v-else :size="14" :stroke-width="1.75" aria-hidden="true" />
          <input
            ref="searchEl"
            v-model="query"
            class="v-fchip__input"
            type="text"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded="true"
            :aria-controls="listId"
            :aria-activedescendant="activeId"
            :aria-label="label"
            :placeholder="searchPlaceholder ?? t('ui.search')"
            autocomplete="off"
            autocorrect="off"
            autocapitalize="off"
            spellcheck="false"
          />
        </div>
        <ul
          :id="listId"
          ref="listEl"
          class="v-fchip__list"
          role="listbox"
          :aria-label="label"
          :aria-multiselectable="multiple ? 'true' : undefined"
          :aria-busy="loading ? 'true' : undefined"
          :aria-activedescendant="isSearchable ? undefined : activeId"
          :tabindex="isSearchable ? undefined : 0"
        >
          <li
            v-for="(opt, i) in visible"
            :id="optionId(i)"
            :key="String(opt.value)"
            class="v-fchip__opt"
            :class="{ 'is-active': i === active, 'is-selected': isSelected(opt.value), 'is-disabled': opt.disabled }"
            role="option"
            :aria-selected="isSelected(opt.value) ? 'true' : 'false'"
            :aria-disabled="opt.disabled ? 'true' : undefined"
            @pointermove="onPointerMove(i, $event)"
            @pointerdown.prevent
            @click="choose(i)"
          >
            <span v-if="multiple" class="v-fchip__box" aria-hidden="true">
              <Check v-if="isSelected(opt.value)" :size="12" :stroke-width="3" />
            </span>
            <span v-if="opt.dot" class="v-fchip__dot" :style="{ background: opt.dot }" aria-hidden="true" />
            <component :is="opt.icon" v-else-if="opt.icon" class="v-fchip__opt-icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
            <span class="v-fchip__opt-label">{{ opt.label }}</span>
            <span v-if="opt.hint" class="v-fchip__opt-hint">{{ opt.hint }}</span>
            <span v-if="!multiple" class="v-fchip__check" aria-hidden="true">
              <Check v-if="isSelected(opt.value)" :size="16" :stroke-width="2.25" />
            </span>
          </li>
          <li v-if="!visible.length" class="v-fchip__none" role="presentation">
            <VSpinner v-if="loading" :size="16" />
            <template v-else>{{ t('ui.noResults') }}</template>
          </li>
        </ul>
      </div>
    </VPopover>

    <VTooltip v-if="isActive" :text="clearLabel" :describe="false" placement="top">
      <button type="button" class="v-fchip__clear" :aria-label="clearLabel" :disabled="disabled" @click="clear(true)">
        <X :size="14" :stroke-width="2" aria-hidden="true" />
      </button>
    </VTooltip>
  </span>
</template>

<style scoped>
/* ---- tabletka ---- */
.v-fchip {
  --chip-h: 32px;
  display: inline-flex;
  align-items: stretch;
  max-width: 100%;
  height: var(--chip-h);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-full);
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
/* Barmoq uchun kattaroq nishon. */
@media (pointer: coarse) {
  .v-fchip {
    --chip-h: 36px;
  }
}
.v-fchip.is-active {
  border-color: transparent;
  background: var(--fill);
  color: var(--text);
}
.v-fchip.is-disabled {
  opacity: 0.5;
}

.v-fchip__main,
.v-fchip__clear {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  color: inherit;
  touch-action: manipulation;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
.v-fchip__main {
  gap: var(--s-1_5);
  padding: 0 10px 0 12px;
  border-radius: var(--r-full);
}
.v-fchip__main:has(> .v-fchip__lead) {
  padding-left: 10px;
}
.is-active .v-fchip__main {
  gap: var(--s-1);
  padding-right: var(--s-1);
  border-radius: var(--r-full) 0 0 var(--r-full);
}
.is-active .v-fchip__lead {
  margin-right: 2px;
}
/* Qiymat belgisi (kanal nuqtasi) qiymatga yopishgan, kalitdan esa biroz uzoqroq. */
.v-fchip__dot--value,
.v-fchip__vicon {
  flex-shrink: 0;
  margin-left: 2px;
}
.v-fchip__vicon {
  color: var(--text-2);
}
.v-fchip__main:focus-visible {
  border-radius: var(--r-full);
  outline-offset: 1px;
}
.is-active .v-fchip__main:focus-visible {
  border-radius: var(--r-full) 0 0 var(--r-full);
}

.v-fchip__clear {
  justify-content: center;
  width: 28px;
  padding-right: 2px;
  border-radius: 0 var(--r-full) var(--r-full) 0;
  color: var(--text-3);
}
.v-fchip__clear:focus-visible {
  border-radius: 0 var(--r-full) var(--r-full) 0;
  outline-offset: 1px;
}

@media (hover: hover) {
  .v-fchip:not(.is-active):not(.is-disabled):hover {
    background: var(--fill);
    color: var(--text);
  }
  .is-active .v-fchip__main:not(:disabled):hover,
  .v-fchip__clear:not(:disabled):hover {
    background: var(--fill-hover);
  }
  .v-fchip__clear:not(:disabled):hover {
    color: var(--text);
  }
}
.v-fchip.is-open:not(.is-active) {
  background: var(--fill);
  color: var(--text);
}
.is-active.is-open .v-fchip__main {
  background: var(--fill-hover);
}

.v-fchip__lead {
  flex-shrink: 0;
  color: var(--text-2);
}
.is-active .v-fchip__lead {
  color: var(--text);
}
.v-fchip__dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
}
.v-fchip__label,
.v-fchip__value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.v-fchip__key {
  flex-shrink: 0;
  color: var(--text-2);
}
.v-fchip__value {
  max-width: 180px;
  color: var(--text);
}
.v-fchip__chev {
  flex-shrink: 0;
  margin-right: -2px;
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.is-open .v-fchip__chev {
  transform: rotate(180deg);
}

/* ---- ro'yxat paneli ---- */
.v-fchip__panel {
  display: flex;
  flex-direction: column;
  min-width: 200px;
  max-width: min(320px, calc(100vw - 16px));
  max-height: inherit;
}
.v-fchip__search {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  flex-shrink: 0;
  height: 40px;
  padding: 0 var(--s-3);
  border-bottom: 1px solid var(--line);
  color: var(--text-3);
}
.v-fchip__input {
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: var(--fs-body-sm);
  outline: none;
}
.v-fchip__input:focus-visible {
  outline: none;
}
.v-fchip__input::placeholder {
  color: var(--text-4);
  opacity: 1;
}
@media (max-width: 767.98px) {
  .v-fchip__input {
    font-size: 16px;
  }
}

.v-fchip__list {
  flex: 1 1 auto;
  min-height: 0;
  max-height: 320px;
  margin: 0;
  padding: var(--s-1_5);
  overflow-y: auto;
  overscroll-behavior: contain;
  list-style: none;
  outline: none;
}
.v-fchip__list:focus-visible {
  outline: none;
}
.v-fchip__opt {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-height: 32px;
  padding: 0 var(--s-2);
  border-radius: var(--r-xs);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  scroll-margin: var(--s-1_5);
}
.v-fchip__opt.is-active {
  background: var(--fill);
}
@media (pointer: coarse) {
  .v-fchip__opt {
    min-height: 40px;
  }
}
.v-fchip__opt.is-disabled {
  color: var(--text-4);
  cursor: default;
}
.v-fchip__opt-icon {
  flex-shrink: 0;
  color: var(--text-2);
}
.v-fchip__opt-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.v-fchip__opt-hint {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  font-variant-numeric: tabular-nums;
}
.v-fchip__check {
  display: inline-flex;
  flex-shrink: 0;
  width: 16px;
  color: var(--text);
}
.v-fchip__box {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  /* VCheckbox bilan bir xil katak. */
  border: 1.5px solid var(--text-4);
  border-radius: calc(var(--r-xs) - 1px);
  background: var(--surface);
  color: var(--on-ink);
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out);
}
.is-selected .v-fchip__box {
  border-color: var(--ink);
  background: var(--ink);
}
.v-fchip__none {
  display: flex;
  justify-content: center;
  padding: var(--s-4) var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
</style>
