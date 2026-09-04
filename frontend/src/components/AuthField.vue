<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { EyeIcon, EyeOffIcon } from '../icons'
import Field from './Field.vue'

const props = withDefaults(
  defineProps<{
    label: string
    modelValue: string
    type?: 'text' | 'email' | 'password'
    placeholder?: string
    autocomplete?: string
    error?: string
    icon?: Component
    revealDelay?: string
  }>(),
  { type: 'text', revealDelay: '0s' },
)
defineEmits<{ 'update:modelValue': [value: string] }>()

const { t } = useI18n({ useScope: 'global' })
const revealed = ref(false)
const errorId = useId()
const actualType = computed(() => (props.type === 'password' && revealed.value ? 'text' : props.type))
</script>

<template>
  <Field :label="label" class="field-enter" :style="{ animationDelay: revealDelay }">
    <div class="auth-field" :class="{ 'has-icon': !!icon, 'is-password': type === 'password', 'has-error': !!error }">
      <span v-if="icon" class="auth-field__icon"><component :is="icon" :size="16" /></span>
      <input
        :type="actualType"
        :value="modelValue"
        :placeholder="placeholder"
        :autocomplete="autocomplete"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="error ? errorId : undefined"
        class="input-focus auth-field__input"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
      <button
        v-if="type === 'password'"
        type="button"
        class="auth-field__toggle"
        :title="revealed ? t('hidePassword') : t('showPassword')"
        :aria-label="revealed ? t('hidePassword') : t('showPassword')"
        @click="revealed = !revealed"
      >
        <EyeOffIcon v-if="revealed" :size="16" />
        <EyeIcon v-else :size="16" />
      </button>
    </div>
    <div v-if="error" :id="errorId" role="alert" class="auth-field__error">{{ error }}</div>
  </Field>
</template>

<style scoped>
.auth-field {
  position: relative;
}
.auth-field__input {
  width: 100%;
  font-size: 14.5px;
  font-family: 'Figtree', sans-serif;
  color: var(--text);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 11px 12px;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.auth-field.has-icon .auth-field__input {
  padding-left: 40px;
}
.auth-field.is-password .auth-field__input {
  padding-right: 42px;
}
.auth-field.has-error .auth-field__input {
  border-color: var(--bad-bd);
}
.auth-field__icon {
  position: absolute;
  left: 13px;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  color: var(--icon-muted);
  pointer-events: none;
}
.auth-field__toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--icon-muted);
  cursor: pointer;
  border-radius: 8px;
  transition: color 0.15s, background 0.15s;
}
.auth-field__toggle:hover {
  color: var(--text-secondary);
  background: var(--surface-hover);
}
.auth-field__error {
  margin-top: 5px;
  font-size: 12px;
  color: var(--bad-fg);
}
/* Non-clip-path entrance so the input's focus ring is never sheared (clip-path
   reveals leave a persistent clip box that would crop the 3px brand halo). */
.field-enter {
  animation: fadeUp 0.45s var(--spring) both;
}
@media (prefers-reduced-motion: reduce) {
  .field-enter {
    animation: none !important;
  }
}
</style>
