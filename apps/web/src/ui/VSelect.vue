<script lang="ts">
import type { Component } from 'vue'

export interface SelectOption<T extends string | number = string> {
  value: T
  label: string
  icon?: Component
  /** O'ng tomonda kulrang qisqa izoh (masalan, soni). */
  hint?: string
  disabled?: boolean
}
</script>

<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown } from 'lucide-vue-next'
import VPopover from './VPopover.vue'
import { useId } from './composables/useId'

/**
 * Ro'yxatdan tanlash: tugma + listbox popover (WAI "select-only combobox" naqshi).
 *
 * Fokus DOIM tugmada qoladi, ro'yxatdagi faol qator `aria-activedescendant` bilan
 * ko'rsatiladi. Shuning uchun dialog ichida ham fokus tuzog'i bilan to'qnashuv yo'q.
 * Klaviatura: ↓ ↑ Enter Space - ochish; ichida ↑ ↓ Home End PageUp PageDown, harf
 * terish, Enter/Space - tanlash, Esc - yopish, Tab - tanlab chiqish.
 */
const props = withDefaults(
  defineProps<{
    options: SelectOption<T>[]
    modelValue?: T | null
    placeholder?: string
    label?: string
    hint?: string
    error?: string | null
    size?: 'sm' | 'md' | 'lg'
    variant?: 'field' | 'ghost'
    disabled?: boolean
    id?: string
    ariaLabel?: string
    /** Ro'yxat eni (standart: tugmadan tor emas). */
    menuWidth?: number
  }>(),
  { modelValue: null, size: 'md', variant: 'field' },
)

const emit = defineEmits<{
  'update:modelValue': [value: T]
  change: [value: T]
}>()

const { t } = useI18n({ useScope: 'global' })
const autoId = useId('v-select')
const buttonId = computed(() => props.id ?? autoId)
const labelId = `${autoId}-label`
const listId = `${autoId}-list`
const hintId = `${autoId}-hint`
const errorId = `${autoId}-error`
const optionId = (i: number) => `${autoId}-opt-${i}`

const button = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const active = ref(-1)

const selectedIndex = computed(() => props.options.findIndex((o) => o.value === props.modelValue))
const selected = computed(() => props.options[selectedIndex.value] ?? null)

function firstEnabled(from: number, dir: 1 | -1): number {
  const n = props.options.length
  for (let i = from; i >= 0 && i < n; i += dir) if (!props.options[i].disabled) return i
  return -1
}

function openList(at?: 'selected' | 'first' | 'last') {
  if (props.disabled || !props.options.length) return
  if (at === 'first') active.value = firstEnabled(0, 1)
  else if (at === 'last') active.value = firstEnabled(props.options.length - 1, -1)
  else active.value = selectedIndex.value >= 0 ? selectedIndex.value : firstEnabled(0, 1)
  open.value = true
}

function commit(i: number) {
  const opt = props.options[i]
  if (!opt || opt.disabled) return
  if (opt.value !== props.modelValue) {
    emit('update:modelValue', opt.value)
    emit('change', opt.value)
  }
  open.value = false
}

function scrollActive() {
  if (active.value < 0) return
  document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' })
}
// Faqat klaviatura bilan o'zgarganda aylantiramiz: sichqoncha chetdagi qatorga
// kelganda ro'yxat uning ostidan "qochib" ketmasin.
let fromPointer = false
function hover(i: number) {
  if (props.options[i]?.disabled || active.value === i) return
  fromPointer = true
  active.value = i
}
watch(active, () => {
  if (fromPointer) fromPointer = false
  else void nextTick(scrollActive)
})
watch(open, (on) => on && nextTick(scrollActive))

/* ---- harf bilan qidirish (yopiq holatda ham ishlaydi) ---- */
let buffer = ''
let bufferTimer: ReturnType<typeof setTimeout> | undefined
function typeahead(ch: string) {
  clearTimeout(bufferTimer)
  buffer += ch.toLocaleLowerCase()
  bufferTimer = setTimeout(() => (buffer = ''), 500)
  const n = props.options.length
  const same = [...buffer].every((c) => c === buffer[0])
  const query = same ? buffer[0] : buffer
  const from = open.value ? active.value : selectedIndex.value
  const start = same ? from + 1 : Math.max(from, 0)
  for (let k = 0; k < n; k++) {
    const i = (((start + k) % n) + n) % n
    const o = props.options[i]
    if (!o.disabled && o.label.toLocaleLowerCase().startsWith(query)) {
      if (!open.value) openList()
      active.value = i
      return
    }
  }
}
onBeforeUnmount(() => clearTimeout(bufferTimer))

function step(dir: 1 | -1, by = 1) {
  const n = props.options.length
  let i = active.value
  for (let moved = 0; moved < by; ) {
    const next = i + dir
    if (next < 0 || next >= n) break
    i = next
    if (!props.options[i].disabled) {
      moved++
      active.value = i
    }
  }
}

function onKeyDown(e: KeyboardEvent) {
  if (props.disabled || e.isComposing) return
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
      e.preventDefault()
      openList(e.key === 'ArrowUp' ? 'selected' : undefined)
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault()
      openList(e.key === 'Home' ? 'first' : 'last')
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault()
      typeahead(e.key)
    }
    return
  }
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      if (e.altKey) commit(active.value)
      else step(1)
      return
    case 'ArrowUp':
      e.preventDefault()
      if (e.altKey) commit(active.value)
      else step(-1)
      return
    case 'PageDown':
      e.preventDefault()
      step(1, 10)
      return
    case 'PageUp':
      e.preventDefault()
      step(-1, 10)
      return
    case 'Home':
      e.preventDefault()
      active.value = firstEnabled(0, 1)
      return
    case 'End':
      e.preventDefault()
      active.value = firstEnabled(props.options.length - 1, -1)
      return
    case 'Enter':
      e.preventDefault()
      commit(active.value)
      return
    case ' ':
      e.preventDefault()
      if (buffer) typeahead(' ')
      else commit(active.value)
      return
    case 'Tab':
      // WAI: Tab joriy qatorni tanlab, fokusni keyingi elementga o'tkazadi.
      if (active.value >= 0) commit(active.value)
      else open.value = false
      return
  }
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    typeahead(e.key)
  }
}

function onButtonClick() {
  if (props.disabled) return
  if (open.value) open.value = false
  else openList()
}

const describedBy = computed(() => (props.error ? errorId : props.hint ? hintId : undefined))

defineExpose({ focus: () => button.value?.focus(), open: () => openList(), close: () => (open.value = false) })
</script>

<template>
  <div class="v-select" :class="[`v-select--${variant}`, { 'is-block': variant === 'field' }]">
    <label v-if="label" :id="labelId" :for="buttonId" class="v-select__label">{{ label }}</label>
    <button
      :id="buttonId"
      ref="button"
      type="button"
      role="combobox"
      class="v-select__button"
      :class="[`v-select__button--${size}`, { 'is-open': open, 'is-invalid': !!error, 'is-empty': !selected }]"
      :disabled="disabled"
      :aria-label="label ? undefined : ariaLabel"
      :aria-labelledby="label ? labelId : undefined"
      aria-haspopup="listbox"
      :aria-expanded="open ? 'true' : 'false'"
      :aria-controls="open ? listId : undefined"
      :aria-activedescendant="open && active >= 0 ? optionId(active) : undefined"
      :aria-invalid="error ? 'true' : undefined"
      :aria-describedby="describedBy"
      @click="onButtonClick"
      @keydown="onKeyDown"
    >
      <component
        :is="selected.icon"
        v-if="selected?.icon"
        class="v-select__icon"
        :size="16"
        :stroke-width="1.75"
        aria-hidden="true"
      />
      <span class="v-select__value">{{ selected ? selected.label : (placeholder ?? t('ui.select')) }}</span>
      <ChevronDown class="v-select__chev" :size="16" :stroke-width="1.75" aria-hidden="true" />
    </button>
    <p v-if="error" :id="errorId" class="v-select__error">{{ error }}</p>
    <p v-else-if="hint" :id="hintId" class="v-select__hint">{{ hint }}</p>

    <VPopover
      v-model:open="open"
      :anchor="button"
      role="presentation"
      haspopup="listbox"
      placement="bottom-start"
      :offset="4"
      match-width
      :width="menuWidth"
      padding="sm"
      auto-focus="none"
      :close-on-focus-out="false"
    >
      <ul :id="listId" class="v-select__list" role="listbox" :aria-labelledby="label ? labelId : undefined" :aria-label="label ? undefined : ariaLabel" tabindex="-1">
        <li
          v-for="(opt, i) in options"
          :id="optionId(i)"
          :key="String(opt.value)"
          class="v-select__option"
          :class="{ 'is-active': i === active, 'is-disabled': opt.disabled }"
          role="option"
          :aria-selected="i === selectedIndex ? 'true' : 'false'"
          :aria-disabled="opt.disabled ? 'true' : undefined"
          @pointermove="hover(i)"
          @pointerdown.prevent
          @click="commit(i)"
        >
          <component :is="opt.icon" v-if="opt.icon" class="v-select__opt-icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
          <span class="v-select__opt-label">{{ opt.label }}</span>
          <span v-if="opt.hint" class="v-select__opt-hint">{{ opt.hint }}</span>
          <span class="v-select__check" aria-hidden="true">
            <Check v-if="i === selectedIndex" :size="16" :stroke-width="2" />
          </span>
        </li>
        <li v-if="!options.length" class="v-select__none" role="presentation">{{ t('ui.noResults') }}</li>
      </ul>
    </VPopover>
  </div>
</template>

<style scoped>
.v-select {
  display: inline-flex;
  flex-direction: column;
  min-width: 0;
}
.v-select.is-block {
  display: flex;
}
.v-select__label {
  margin-bottom: var(--s-1_5);
  color: var(--text-2);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
}
.v-select__hint,
.v-select__error {
  margin-top: var(--s-1_5);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.v-select__hint {
  color: var(--text-3);
}
.v-select__error {
  color: var(--crit-text);
  font-weight: 500;
}

.v-select__button {
  --sel-h: 36px;
  --sel-ring: color-mix(in srgb, var(--text) 10%, transparent);
  display: flex;
  align-items: center;
  gap: var(--s-2);
  width: 100%;
  height: var(--sel-h);
  padding: 0 10px 0 12px;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: left;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    box-shadow var(--dur-1) var(--ease-out);
}
.v-select__button--sm {
  --sel-h: 32px;
  border-radius: var(--r-sm);
  font-size: 13px;
}
@media (pointer: coarse) {
  .v-select__button--sm {
    --sel-h: 36px;
  }
}
.v-select__button--lg {
  --sel-h: 44px;
  padding: 0 12px 0 14px;
  font-size: var(--fs-body);
}
@media (hover: hover) {
  .v-select__button:not(:disabled):not(.is-open):hover {
    border-color: var(--line-strong);
  }
}
.v-select__button:focus-visible,
.v-select__button.is-open {
  outline: none;
  background: var(--surface);
  border-color: var(--ink);
  box-shadow: 0 0 0 3px var(--sel-ring);
}
.v-select__button.is-invalid {
  --sel-ring: color-mix(in srgb, var(--crit) 14%, transparent);
  border-color: var(--crit);
}
.v-select__button:disabled {
  opacity: 0.5;
  cursor: default;
}

/* Jim variant: filtr qatorida, sarlavha yonida - fonsiz, faqat hover'da. */
.v-select--ghost .v-select__button {
  width: auto;
  background: transparent;
  padding: 0 var(--s-2) 0 10px;
}
@media (hover: hover) {
  .v-select--ghost .v-select__button:not(:disabled):hover {
    background: var(--fill);
    border-color: transparent;
  }
}
.v-select--ghost .v-select__button.is-open {
  background: var(--fill);
  border-color: transparent;
  box-shadow: none;
}
.v-select--ghost .v-select__button:focus-visible {
  background: var(--fill);
  border-color: transparent;
  box-shadow: none;
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.v-select__icon {
  flex-shrink: 0;
  color: var(--text-2);
}
.v-select__value {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.is-empty .v-select__value {
  color: var(--text-4);
}
.v-select__chev {
  flex-shrink: 0;
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.is-open .v-select__chev {
  transform: rotate(180deg);
}

.v-select__list {
  margin: 0;
  padding: 0;
  list-style: none;
  outline: none;
}
.v-select__option {
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
.v-select__option.is-active {
  background: var(--fill);
}
/* Barmoq uchun kattaroq qator. */
@media (pointer: coarse) {
  .v-select__option {
    min-height: 40px;
  }
}
.v-select__option.is-disabled {
  color: var(--text-4);
  cursor: default;
}
.v-select__opt-icon {
  flex-shrink: 0;
  color: var(--text-2);
}
.v-select__opt-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.v-select__opt-hint {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  font-variant-numeric: tabular-nums;
}
.v-select__check {
  display: inline-flex;
  flex-shrink: 0;
  width: 16px;
  color: var(--text);
}
.v-select__none {
  padding: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}
</style>
