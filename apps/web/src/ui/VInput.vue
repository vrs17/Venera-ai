<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'
import { useId } from './composables/useId'

/**
 * Matn maydoni. Tinch holatda --fill fon; hover'da chegara; fokusda sirt foni + yarim
 * siyoh (55%) chegara + 3px yumshoq halqa (spec §3).
 *
 * Atributlar: `class`/`style` tashqi o'ramaga (joylashuv uchun), qolgan hammasi
 * (`name`, `autocomplete`, `inputmode`, `maxlength`, `@keydown`...) to'g'ridan-to'g'ri
 * <input> ga tushadi - maydon oddiy input kabi ishlatiladi.
 *
 * `clearable`: qiymat bo'lsa × chiqadi; Esc ham tozalaydi (va shu Esc dialogni
 * yopmaydi - preventDefault, qatlam uni o'tkazib yuboradi).
 */
defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    type?: string
    label?: string
    hint?: string
    error?: string | null
    placeholder?: string
    size?: 'sm' | 'md' | 'lg'
    icon?: Component
    clearable?: boolean
    disabled?: boolean
    readonly?: boolean
    id?: string
  }>(),
  { modelValue: '', type: 'text', size: 'md' },
)

const emit = defineEmits<{
  'update:modelValue': [value: string | number | null]
  clear: []
}>()

defineSlots<{
  leading?(): unknown
  trailing?(): unknown
}>()

const attrs = useAttrs()
const { t } = useI18n({ useScope: 'global' })

const autoId = useId('v-input')
const inputId = computed(() => props.id ?? autoId)
const hintId = `${autoId}-hint`
const errorId = `${autoId}-error`
const el = ref<HTMLInputElement | null>(null)

const rootAttrs = computed(() => ({ class: attrs.class, style: attrs.style }))
const inputAttrs = computed(() =>
  Object.fromEntries(Object.entries(attrs).filter(([k]) => k !== 'class' && k !== 'style')),
)

const hasValue = computed(() => props.modelValue !== null && props.modelValue !== undefined && props.modelValue !== '')
const showClear = computed(() => props.clearable && hasValue.value && !props.disabled && !props.readonly)
const describedBy = computed(() => {
  const own = props.error ? errorId : props.hint ? hintId : ''
  const extra = typeof attrs['aria-describedby'] === 'string' ? attrs['aria-describedby'] : ''
  return [own, extra].filter(Boolean).join(' ') || undefined
})

function onInput(e: Event) {
  const raw = (e.target as HTMLInputElement).value
  if (props.type === 'number') {
    const n = raw === '' ? null : Number(raw)
    emit('update:modelValue', n === null || Number.isNaN(n) ? null : n)
  } else emit('update:modelValue', raw)
}

function clear() {
  emit('update:modelValue', props.type === 'number' ? null : '')
  emit('clear')
  el.value?.focus()
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && showClear.value && !e.isComposing) {
    e.preventDefault()
    clear()
  }
}

// Maydon ichidagi bo'sh joyga (belgi, padding) bosilsa ham input fokus olsin.
function onBoxPointerDown(e: PointerEvent) {
  if (e.target === el.value || props.disabled) return
  if ((e.target as Element).closest('button, a, [role="button"]')) return
  e.preventDefault()
  el.value?.focus()
}

defineExpose({
  el,
  focus: () => el.value?.focus(),
  blur: () => el.value?.blur(),
  select: () => el.value?.select(),
})
</script>

<template>
  <div class="v-field" v-bind="rootAttrs">
    <label v-if="label" :for="inputId" class="v-field__label">{{ label }}</label>
    <div
      class="v-input"
      :class="[`v-input--${size}`, { 'is-invalid': !!error, 'is-disabled': disabled, 'is-readonly': readonly }]"
      @pointerdown="onBoxPointerDown"
    >
      <span v-if="icon || $slots.leading" class="v-input__lead">
        <slot name="leading"><component :is="icon" :size="16" :stroke-width="1.75" aria-hidden="true" /></slot>
      </span>
      <input
        :id="inputId"
        ref="el"
        v-bind="inputAttrs"
        class="v-input__control"
        :type="type"
        :value="modelValue ?? ''"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="describedBy"
        @input="onInput"
        @keydown="onKeyDown"
      />
      <button
        v-if="showClear"
        type="button"
        class="v-input__clear"
        tabindex="-1"
        :aria-label="t('ui.clear')"
        @click="clear"
      >
        <X :size="14" :stroke-width="2" aria-hidden="true" />
      </button>
      <span v-if="$slots.trailing" class="v-input__trail"><slot name="trailing" /></span>
    </div>
    <p v-if="error" :id="errorId" class="v-field__error">{{ error }}</p>
    <p v-else-if="hint" :id="hintId" class="v-field__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.v-field {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.v-field__label {
  margin-bottom: var(--s-1_5);
  color: var(--text-2);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
}
.v-field__hint,
.v-field__error {
  margin-top: var(--s-1_5);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.v-field__hint {
  color: var(--text-3);
}
.v-field__error {
  color: var(--crit-text);
  font-weight: 500;
}

.v-input {
  --in-h: 36px;
  --in-px: 12px;
  /* Fokus: 1px chegara siyohning 55% i + 3px 8% halo. To'liq siyoh (--ink) chegara
     halo bilan qo'shilib 2px qora chiziq bo'lib o'qilardi. 55% - WCAG 1.4.11/2.4.7
     chegarasidan yuqori: sirt/fon/fill ga nisbatan yorug'da >= 3.8:1, qorong'ida
     >= 5.2:1 (chegara fokusdagi --surface ustida aralashadi). */
  --in-focus: color-mix(in srgb, var(--text) 55%, transparent);
  --in-ring: color-mix(in srgb, var(--text) 8%, transparent);
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s-2);
  height: var(--in-h);
  padding: 0 var(--in-px);
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: var(--fill);
  color: var(--text);
  cursor: text;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    box-shadow var(--dur-1) var(--ease-out);
}
.v-input--sm {
  --in-h: 32px;
  --in-px: 10px;
  border-radius: var(--r-sm);
}
.v-input--lg {
  --in-h: 44px;
  --in-px: 14px;
}
/* Sensorli ekranda sm maydon filtr chip'lari (36px) bilan bir balandlikda. */
@media (pointer: coarse) {
  .v-input--sm {
    --in-h: 36px;
  }
}
@media (hover: hover) {
  .v-input:hover:not(.is-disabled):not(:focus-within) {
    border-color: var(--line-strong);
  }
}
.v-input:focus-within {
  background: var(--surface);
  border-color: var(--in-focus);
  box-shadow: 0 0 0 3px var(--in-ring);
}
.v-input.is-invalid {
  --in-ring: color-mix(in srgb, var(--crit) 14%, transparent);
  border-color: var(--crit);
}
.v-input.is-disabled {
  cursor: default;
  opacity: 0.5;
}
.v-input.is-readonly {
  background: transparent;
  border-color: var(--line);
}

.v-input__control {
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  outline: none;
}
.v-input--lg .v-input__control {
  font-size: var(--fs-body);
}
.v-input__control:focus-visible {
  outline: none;
}
.v-input__control::placeholder {
  color: var(--text-4);
  opacity: 1;
}
.v-input__control:disabled {
  cursor: default;
}
/* Brauzer avto-to'ldirish fonini "cheksiz kechiktiramiz" - maydon o'z rangida qoladi. */
.v-input__control:-webkit-autofill,
.v-input__control:-webkit-autofill:hover,
.v-input__control:-webkit-autofill:focus {
  -webkit-text-fill-color: var(--text);
  caret-color: var(--text);
  transition: background-color 600000s 0s, color 600000s 0s;
}
.v-input__control[type='search']::-webkit-search-cancel-button {
  display: none;
}
/* iOS 16px dan kichik shriftli maydonga fokusda sahifani kattalashtiradi. */
@media (max-width: 767.98px) {
  .v-input__control {
    font-size: 16px;
  }
}

.v-input__lead,
.v-input__trail {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  color: var(--text-3);
}
.v-input__lead {
  margin-left: -2px;
}
.v-input__trail {
  margin-right: -4px;
  gap: var(--s-1);
}
.v-input__clear {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  margin-right: -4px;
  border-radius: var(--r-full);
  color: var(--text-3);
  background: var(--fill-hover);
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-input__clear:hover {
    color: var(--text);
    background: var(--line-strong);
  }
}
</style>
