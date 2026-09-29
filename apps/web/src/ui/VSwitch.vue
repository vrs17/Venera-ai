<script setup lang="ts">
import { useId } from './composables/useId'

/**
 * Yoqish/o'chirish. Yoqilganda siyoh (spec §1.1: "switches on").
 *
 * <button role="switch"> + <label for>: yozuvga bosish ham tugmani bosadi (button
 * "labelable" element), ekran o'quvchi esa "Bloklash, switch, off" deb o'qiydi.
 * `description` - yozuv ostida kulrang bir qator (aria-describedby).
 */
const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    label?: string
    description?: string
    disabled?: boolean
    size?: 'sm' | 'md'
    /** Yozuv chapda, tugma o'ngda (sozlamalar ro'yxati uchun). */
    labelFirst?: boolean
    ariaLabel?: string
  }>(),
  { modelValue: false, size: 'md' },
)

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const id = useId('v-switch')

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <div
    class="v-switch"
    :class="[`v-switch--${size}`, { 'is-disabled': disabled, 'is-reversed': labelFirst, 'has-text': !!(label || description) }]"
  >
    <button
      :id="id"
      type="button"
      role="switch"
      class="v-switch__track"
      :class="{ 'is-on': modelValue }"
      :aria-checked="modelValue ? 'true' : 'false'"
      :aria-label="label ? undefined : ariaLabel"
      :aria-describedby="description ? `${id}-desc` : undefined"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="v-switch__thumb" aria-hidden="true" />
    </button>
    <span v-if="label || description" class="v-switch__text">
      <label v-if="label" :for="id" class="v-switch__label">{{ label }}</label>
      <span v-if="description" :id="`${id}-desc`" class="v-switch__desc">{{ description }}</span>
    </span>
  </div>
</template>

<style scoped>
.v-switch {
  --sw-w: 36px;
  --sw-h: 20px;
  --sw-pad: 2px;
  display: inline-flex;
  align-items: flex-start;
  gap: var(--s-3);
  min-width: 0;
}
.v-switch--sm {
  --sw-w: 28px;
  --sw-h: 16px;
}
.v-switch.is-reversed {
  flex-direction: row-reverse;
  justify-content: space-between;
  width: 100%;
}

.v-switch__track {
  position: relative;
  flex-shrink: 0;
  width: var(--sw-w);
  height: var(--sw-h);
  padding: 0;
  border-radius: var(--r-full);
  /* O'chiq yo'lak --line-strong (1.3:1) bilan fonda "erib" ketardi - holat ko'rinishi
     uchun to'qroq kulrang (WCAG 1.4.11 ga yaqin, tinch ko'rinish saqlanadi). */
  background: var(--text-4);
  cursor: pointer;
  transition: background-color var(--dur-2) var(--ease-out);
}
/* Yozuvning birinchi qatori (20px) bilan markazlashsin; yozuvsiz - tekis turadi. */
.v-switch.has-text .v-switch__track {
  margin-top: calc((var(--lh-body-sm) - var(--sw-h)) / 2);
}
@media (hover: hover) {
  .v-switch__track:not(:disabled):not(.is-on):hover {
    background: var(--text-3);
  }
  .v-switch__track.is-on:not(:disabled):hover {
    background: var(--ink-hover);
  }
}
.v-switch__track.is-on {
  background: var(--ink);
}
.v-switch__track:focus-visible {
  border-radius: var(--r-full);
}
.v-switch__thumb {
  position: absolute;
  top: var(--sw-pad);
  left: var(--sw-pad);
  width: calc(var(--sw-h) - var(--sw-pad) * 2);
  height: calc(var(--sw-h) - var(--sw-pad) * 2);
  border-radius: var(--r-full);
  background: var(--surface);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--overlay) 50%, transparent);
  transition:
    transform var(--dur-2) var(--ease-out),
    width var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
.is-on .v-switch__thumb {
  transform: translateX(calc(var(--sw-w) - var(--sw-h)));
  background: var(--on-ink);
}
/* Qorong'i mavzuda --surface yo'lakdan to'q - o'chiq holatdagi tugmacha ko'rinmay
   qolardi; och qilamiz. */
:root[data-theme='dark'] .v-switch__track:not(.is-on) .v-switch__thumb {
  background: var(--text);
}
.v-switch__track:active:not(:disabled) .v-switch__thumb {
  width: calc(var(--sw-h) - var(--sw-pad) * 2 + 3px);
}
.is-on:active:not(:disabled) .v-switch__thumb {
  transform: translateX(calc(var(--sw-w) - var(--sw-h) - 3px));
}

.v-switch.is-disabled {
  opacity: 0.5;
}
.v-switch.is-disabled .v-switch__track,
.v-switch.is-disabled .v-switch__label {
  cursor: default;
}

.v-switch__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.v-switch__label {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  cursor: pointer;
}
.v-switch__desc {
  color: var(--text-3);
  font-size: 13px;
  line-height: 18px;
  text-wrap: pretty;
}
</style>
