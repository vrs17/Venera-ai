<script setup lang="ts">
import { ref } from 'vue'
import { CircleAlert } from 'lucide-vue-next'

/**
 * Shakl darajasidagi xato: belgi + qizil matn, quti va fon yo'q (spec §4.1 - "jim").
 * Bo'sh xabarda hech narsa chizilmaydi. `role=alert` - ekran o'quvchi darhol o'qiydi;
 * maydonlardagi xatolar alert emas, shuning uchun e'lon bitta bo'ladi.
 * Slot - xabar oxiridagi havola uchun (masalan, "CRM ni ochish").
 */
defineProps<{ message: string }>()
defineSlots<{ default?(): unknown }>()

const el = ref<HTMLElement | null>(null)
// Kerak bo'lsa sahifa fokusni shu yerga ko'chiradi (tabindex=-1 - Tab tartibida emas).
defineExpose({ focus: () => el.value?.focus() })
</script>

<template>
  <div v-if="message" ref="el" class="auth-error" role="alert" tabindex="-1">
    <CircleAlert class="auth-error__icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
    <p class="auth-error__text">
      {{ message }}
      <template v-if="$slots.default">{{ ' ' }}<slot /></template>
    </p>
  </div>
</template>

<style scoped>
.auth-error {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  outline: none;
}
.auth-error__icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.auth-error__text {
  min-width: 0;
  overflow-wrap: anywhere;
}
.auth-error__text :slotted(a) {
  color: var(--text);
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
  white-space: nowrap;
  transition: text-decoration-color var(--dur-1) var(--ease-out);
}
.auth-error__text :slotted(a:hover) {
  text-decoration-color: currentColor;
}
</style>
