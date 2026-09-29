<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { Check, Minus } from 'lucide-vue-next'
import { useId } from './composables/useId'

/**
 * Belgilash katakchasi. Ichida HAQIQIY <input type="checkbox"> (ko'rinmas, lekin
 * fokus, Space, forma va ekran o'quvchi - hammasi brauzerniki); ko'rinadigan qism -
 * uning ustidagi siyoh katakcha.
 *
 * Ikki rejim:
 * - `v-model` boolean;
 * - `v-model` massiv + `value`: belgilanganda qiymat massivga qo'shiladi (filtr ro'yxati).
 * `indeterminate` - "qisman" holat (jadvalda hammasini tanlash).
 */
type Val = string | number

const props = withDefaults(
  defineProps<{
    modelValue?: boolean | Val[]
    value?: Val
    label?: string
    description?: string
    indeterminate?: boolean
    disabled?: boolean
    ariaLabel?: string
  }>(),
  { modelValue: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: boolean | Val[]] }>()

const id = useId('v-checkbox')
const input = ref<HTMLInputElement | null>(null)

const checked = computed(() =>
  Array.isArray(props.modelValue) ? props.value !== undefined && props.modelValue.includes(props.value) : !!props.modelValue,
)

// `indeterminate` faqat JS xossasi (HTML atributi yo'q).
watchEffect(() => {
  if (input.value) input.value.indeterminate = !!props.indeterminate
})

function onChange(e: Event) {
  const on = (e.target as HTMLInputElement).checked
  if (Array.isArray(props.modelValue)) {
    if (props.value === undefined) return
    const rest = props.modelValue.filter((v) => v !== props.value)
    emit('update:modelValue', on ? [...rest, props.value] : rest)
  } else emit('update:modelValue', on)
}
</script>

<template>
  <label
    class="v-checkbox"
    :class="{ 'is-disabled': disabled, 'has-text': !!(label || description || $slots.default) }"
    :for="id"
  >
    <span class="v-checkbox__box-wrap">
      <input
        :id="id"
        ref="input"
        type="checkbox"
        class="v-checkbox__input"
        :checked="checked"
        :value="value"
        :disabled="disabled"
        :aria-label="label ? undefined : ariaLabel"
        :aria-describedby="description ? `${id}-desc` : undefined"
        @change="onChange"
      />
      <span class="v-checkbox__box" :class="{ 'is-on': checked || indeterminate }" aria-hidden="true">
        <Minus v-if="indeterminate" :size="12" :stroke-width="3" />
        <Check v-else-if="checked" :size="12" :stroke-width="3" />
      </span>
    </span>
    <span v-if="label || description || $slots.default" class="v-checkbox__text">
      <span class="v-checkbox__label"><slot>{{ label }}</slot></span>
      <span v-if="description" :id="`${id}-desc`" class="v-checkbox__desc">{{ description }}</span>
    </span>
  </label>
</template>

<style scoped>
.v-checkbox {
  display: inline-flex;
  align-items: flex-start;
  gap: var(--s-2);
  min-width: 0;
  cursor: pointer;
  -webkit-user-select: none;
  user-select: none;
}
.v-checkbox.is-disabled {
  cursor: default;
  opacity: 0.5;
}
.v-checkbox__box-wrap {
  position: relative;
  display: inline-grid;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
}
/* Yozuvning birinchi qatori (20px) bilan markazlashsin; yozuvsiz (jadval) - tekis. */
.has-text .v-checkbox__box-wrap {
  margin-top: 2px;
}
.v-checkbox__input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: inherit;
}
.v-checkbox__box {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  /* --line-strong oq fonda 1.3:1 - katak "ko'rinmas" edi; --text-4 aniq, lekin jim. */
  border: 1.5px solid var(--text-4);
  border-radius: calc(var(--r-xs) - 1px);
  background: var(--surface);
  color: var(--on-ink);
  pointer-events: none;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-checkbox:not(.is-disabled):hover .v-checkbox__box:not(.is-on) {
    border-color: var(--text-3);
  }
}
.v-checkbox__box.is-on {
  background: var(--ink);
  border-color: var(--ink);
}
.v-checkbox__box svg {
  animation: v-check-in var(--dur-2) var(--ease-out);
}
@keyframes v-check-in {
  from {
    transform: scale(0.5);
    opacity: 0;
  }
}
.v-checkbox__input:focus-visible + .v-checkbox__box {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.v-checkbox__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.v-checkbox__label {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.v-checkbox__desc {
  color: var(--text-3);
  font-size: 13px;
  line-height: 18px;
}
</style>
