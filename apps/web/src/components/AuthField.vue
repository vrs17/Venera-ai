<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Eye, EyeOff } from 'lucide-vue-next'
import VInput from '../ui/VInput.vue'
import VIconButton from '../ui/VIconButton.vue'

/**
 * Kirish shakllari maydoni: VInput (lg, 44px) + parol uchun ko'rsatish/yashirish.
 * Prop'lar eskisi bilan bir xil (label, v-model, type, autocomplete, error, icon) -
 * chaqiruvchilarni buzmaslik uchun. Qolgan atributlar (`name`, `autocapitalize`,
 * `spellcheck`, `aria-describedby`...) VInput orqali to'g'ridan-to'g'ri <input> ga
 * tushadi.
 *
 * Xato matni oddiy <p> (role=alert EMAS): yuborishda bir nechta maydon birdan
 * "baqirmasin" - e'lonni shakl darajasidagi AuthError qiladi.
 */
defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    label: string
    modelValue: string
    type?: 'text' | 'email' | 'password'
    placeholder?: string
    autocomplete?: string
    error?: string
    icon?: Component
    /** @deprecated Eski kirish animatsiyasi kechikishi - endi e'tiborsiz. */
    revealDelay?: string
  }>(),
  { type: 'text' },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const { t } = useI18n({ useScope: 'global' })
const revealed = ref(false)
const input = ref<InstanceType<typeof VInput> | null>(null)
const actualType = computed(() => (props.type === 'password' && revealed.value ? 'text' : props.type))

function onUpdate(v: string | number | null) {
  emit('update:modelValue', v == null ? '' : String(v))
}

defineExpose({ focus: () => input.value?.focus() })
</script>

<template>
  <VInput
    ref="input"
    v-bind="$attrs"
    :model-value="modelValue"
    :label="label"
    :type="actualType"
    :placeholder="placeholder"
    :autocomplete="autocomplete"
    :error="error || undefined"
    :icon="icon"
    size="lg"
    @update:model-value="onUpdate"
  >
    <template v-if="type === 'password'" #trailing>
      <!-- type=button (VIconButton standarti) - shaklni hech qachon yubormaydi. -->
      <VIconButton
        size="sm"
        :icon="revealed ? EyeOff : Eye"
        :label="revealed ? t('hidePassword') : t('showPassword')"
        @click="revealed = !revealed"
      />
    </template>
  </VInput>
</template>
