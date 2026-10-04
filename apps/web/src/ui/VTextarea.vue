<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useAttrs, watch } from 'vue'
import { useId } from './composables/useId'

/**
 * Ko'p qatorli maydon, VInput bilan bir xil ko'rinish. `autosize`: `rows` dan `maxRows`
 * gacha o'sadi, keyin ichida aylanadi.
 *
 * Hisoblagich (`maxlength` bo'lsa) faqat chegaraga yaqinlashganda chiqadi (standart:
 * 90%) - bo'sh maydon ostida "0 / 2000" shovqini bo'lmasin (spec §4.4).
 */
defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string | null
    label?: string
    hint?: string
    error?: string | null
    placeholder?: string
    rows?: number
    maxRows?: number
    autosize?: boolean
    maxlength?: number
    /** Hisoblagich shu uzunlikdan boshlab ko'rinadi. */
    counterFrom?: number
    disabled?: boolean
    readonly?: boolean
    id?: string
  }>(),
  { modelValue: '', rows: 3, maxRows: 8, autosize: true },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const attrs = useAttrs()
const autoId = useId('v-textarea')
const inputId = computed(() => props.id ?? autoId)
const hintId = `${autoId}-hint`
const errorId = `${autoId}-error`
const counterId = `${autoId}-count`
const el = ref<HTMLTextAreaElement | null>(null)

const rootAttrs = computed(() => ({ class: attrs.class, style: attrs.style }))
const inputAttrs = computed(() =>
  Object.fromEntries(Object.entries(attrs).filter(([k]) => k !== 'class' && k !== 'style')),
)

const length = computed(() => (props.modelValue ?? '').length)
const showCounter = computed(() => {
  if (!props.maxlength) return false
  const from = props.counterFrom ?? Math.floor(props.maxlength * 0.9)
  return length.value >= from
})
const describedBy = computed(
  () =>
    [props.error ? errorId : props.hint ? hintId : '', showCounter.value ? counterId : '']
      .filter(Boolean)
      .join(' ') || undefined,
)

function resize() {
  const ta = el.value
  if (!ta || !props.autosize) return
  const cs = getComputedStyle(ta)
  const lh = parseFloat(cs.lineHeight) || 24
  const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)
  const min = props.rows * lh + padY
  const max = Math.max(props.rows, props.maxRows) * lh + padY
  // `auto` o'rniga minimal balandlik: vaqtincha 0 ga qisqarish ota-elementning
  // aylantirish holatini "sakratib" yuborishi mumkin edi.
  ta.style.height = `${min}px`
  const next = Math.min(max, Math.max(min, ta.scrollHeight))
  ta.style.height = `${next}px`
  ta.style.overflowY = ta.scrollHeight > max + 1 ? 'auto' : 'hidden'
}

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
  resize()
}

watch(
  () => [props.modelValue, props.rows, props.maxRows, props.autosize],
  () => nextTick(resize),
)

// Kenglik o'zgarsa (dialog ochilishi, oyna o'lchami) qatorlar qayta o'raladi.
let ro: ResizeObserver | null = null
let lastWidth = 0
onMounted(() => {
  resize()
  if (typeof ResizeObserver === 'undefined' || !el.value) return
  ro = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect.width ?? 0
    if (Math.abs(w - lastWidth) < 0.5) return
    lastWidth = w
    resize()
  })
  ro.observe(el.value)
})
onBeforeUnmount(() => ro?.disconnect())

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
    <div class="v-textarea" :class="{ 'is-invalid': !!error, 'is-disabled': disabled, 'is-readonly': readonly }">
      <textarea
        :id="inputId"
        ref="el"
        v-bind="inputAttrs"
        class="v-textarea__control"
        :value="modelValue ?? ''"
        :rows="rows"
        :placeholder="placeholder"
        :maxlength="maxlength"
        :disabled="disabled"
        :readonly="readonly"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="describedBy"
        @input="onInput"
      />
    </div>
    <div v-if="error || hint || showCounter" class="v-field__below">
      <p v-if="error" :id="errorId" class="v-field__error">{{ error }}</p>
      <p v-else-if="hint" :id="hintId" class="v-field__hint">{{ hint }}</p>
      <span
        v-if="showCounter"
        :id="counterId"
        class="v-field__count"
        :class="{ 'is-max': maxlength && length >= maxlength }"
      >
        {{ length }} / {{ maxlength }}
      </span>
    </div>
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
.v-field__below {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
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
.v-field__count {
  margin-left: auto;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.v-field__count.is-max {
  color: var(--crit-text);
}

.v-textarea {
  /* Fokus: 1px chegara siyohning 55% i + 3px 8% halo. To'liq siyoh (--ink) chegara
     halo bilan qo'shilib 2px qora chiziq bo'lib o'qilardi. 55% - WCAG 1.4.11/2.4.7
     chegarasidan yuqori: sirt/fon/fill ga nisbatan yorug'da >= 3.8:1, qorong'ida
     >= 5.2:1 (chegara fokusdagi --surface ustida aralashadi). */
  --in-focus: color-mix(in srgb, var(--text) 55%, transparent);
  --in-ring: color-mix(in srgb, var(--text) 8%, transparent);
  display: flex;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: var(--fill);
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    box-shadow var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-textarea:hover:not(.is-disabled):not(:focus-within) {
    border-color: var(--line-strong);
  }
}
.v-textarea:focus-within {
  background: var(--surface);
  border-color: var(--in-focus);
  box-shadow: 0 0 0 3px var(--in-ring);
}
.v-textarea.is-invalid {
  --in-ring: color-mix(in srgb, var(--crit) 14%, transparent);
  border-color: var(--crit);
}
.v-textarea.is-disabled {
  opacity: 0.5;
}
.v-textarea.is-readonly {
  background: transparent;
  border-color: var(--line);
}

.v-textarea__control {
  display: block;
  flex: 1;
  width: 100%;
  min-width: 0;
  margin: 0;
  padding: var(--s-2) var(--s-3);
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  resize: none;
  outline: none;
  /* autosize yoqilganda resize() buni inline boshqaradi. */
  overflow-y: auto;
}
.v-textarea__control:focus-visible {
  outline: none;
}
.v-textarea__control::placeholder {
  color: var(--text-4);
  opacity: 1;
}
@media (max-width: 767.98px) {
  .v-textarea__control {
    font-size: 16px;
  }
}
</style>
