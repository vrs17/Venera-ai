<script lang="ts">
import type { Component } from 'vue'

export interface ChoiceOption<T extends string | number = string> {
  value: T
  label: string
  icon?: Component
  disabled?: boolean
}
</script>

<script setup lang="ts" generic="T extends string | number">
import { computed, ref, watch } from 'vue'

/**
 * Tabletka tugmalar to'plami: bitta (`multiple` yo'q) yoki bir nechta tanlov.
 * Tanlangan - siyoh fon (spec §3).
 *
 * Semantika: har bir chip - toggle tugma (`aria-pressed`), guruh - `role="group"`.
 * Radio emas: bitta tanlovda ham tanlovni bekor qilish mumkin (`deselectable`) -
 * masalan, "Xabar berish" sababi ixtiyoriy. Klaviatura: guruh bitta Tab to'xtashi,
 * ichida ← → / Home End, Space/Enter - tanlash.
 */
const props = withDefaults(
  defineProps<{
    options: ChoiceOption<T>[]
    modelValue?: T | T[] | null
    multiple?: boolean
    deselectable?: boolean
    size?: 'sm' | 'md'
    disabled?: boolean
    ariaLabel?: string
  }>(),
  { modelValue: null, deselectable: true, size: 'md' },
)

const emit = defineEmits<{ 'update:modelValue': [value: T | T[] | null] }>()

// v-for ichidagi `ref="..."` massiv tartibini kafolatlamaydi - indeks bo'yicha yozamiz.
const refs: (HTMLButtonElement | null)[] = []
function setRef(el: unknown, i: number) {
  refs[i] = el instanceof HTMLButtonElement ? el : null
}

function isOn(v: T): boolean {
  const m = props.modelValue
  return Array.isArray(m) ? m.includes(v) : m === v
}

// Roving tabindex: guruhga Tab bilan kirganda tanlangan chip'ga (yo'q bo'lsa birinchisiga).
const focusIndex = ref(0)
const firstSelected = computed(() => Math.max(0, props.options.findIndex((o) => isOn(o.value))))
watch(firstSelected, (i) => (focusIndex.value = i), { immediate: true })

function toggle(opt: ChoiceOption<T>, index: number) {
  if (props.disabled || opt.disabled) return
  focusIndex.value = index
  if (props.multiple) {
    const cur = Array.isArray(props.modelValue) ? props.modelValue : []
    emit('update:modelValue', isOn(opt.value) ? cur.filter((v) => v !== opt.value) : [...cur, opt.value])
    return
  }
  if (isOn(opt.value)) {
    if (props.deselectable) emit('update:modelValue', null)
    return
  }
  emit('update:modelValue', opt.value)
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
  focusIndex.value = next
  refs[next]?.focus()
}
</script>

<template>
  <div class="v-chips" :class="`v-chips--${size}`" role="group" :aria-label="ariaLabel">
    <button
      v-for="(opt, i) in options"
      :key="String(opt.value)"
      :ref="(el) => setRef(el, i)"
      type="button"
      class="v-chip"
      :class="{ 'is-on': isOn(opt.value) }"
      :aria-pressed="isOn(opt.value) ? 'true' : 'false'"
      :disabled="disabled || opt.disabled"
      :tabindex="i === focusIndex ? 0 : -1"
      @click="toggle(opt, i)"
      @keydown="onKeyDown($event, i)"
      @focus="focusIndex = i"
    >
      <component :is="opt.icon" v-if="opt.icon" :size="size === 'sm' ? 14 : 16" :stroke-width="1.75" aria-hidden="true" />
      <span>{{ opt.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.v-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
}
.v-chips--sm {
  gap: var(--s-1_5);
}
.v-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  height: 32px;
  padding: 0 var(--s-3);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  touch-action: manipulation;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.v-chips--sm .v-chip {
  height: 28px;
  padding: 0 10px;
  font-size: var(--fs-caption);
}
/* Barmoq uchun kattaroq nishon. */
@media (pointer: coarse) {
  .v-chip {
    height: 36px;
  }
  .v-chips--sm .v-chip {
    height: 32px;
  }
}
.v-chip:has(svg) {
  padding-left: 10px;
}
@media (hover: hover) {
  .v-chip:not(:disabled):not(.is-on):hover {
    background: var(--fill-hover);
    color: var(--text);
  }
}
.v-chip:not(:disabled):active {
  transform: scale(0.97);
}
.v-chip.is-on {
  background: var(--ink);
  color: var(--on-ink);
}
.v-chip:focus-visible {
  border-radius: var(--r-full);
}
.v-chip:disabled {
  color: var(--text-4);
  cursor: default;
}
</style>
