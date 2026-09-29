<script setup lang="ts">
/**
 * Aylanma yuklanish belgisi. Rangi `currentColor` - tugma ichida tugma matni rangini oladi.
 *
 * `label` berilsa - ekran o'quvchiga "status" sifatida e'lon qilinadi. Berilmasa
 * bezak hisoblanadi (masalan, tugma ichida - u yerda tugmaning `aria-busy` si yetarli).
 */
withDefaults(defineProps<{ size?: number; label?: string }>(), { size: 16 })
</script>

<template>
  <span
    class="v-spinner"
    :style="{ width: `${size}px`, height: `${size}px` }"
    :role="label ? 'status' : undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <svg :width="size" :height="size" viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="2" opacity="0.18" />
      <path d="M10 2a8 8 0 0 1 8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
    </svg>
    <span v-if="label" class="sr-only">{{ label }}</span>
  </span>
</template>

<style scoped>
.v-spinner {
  display: inline-flex;
  flex-shrink: 0;
  color: inherit;
}
.v-spinner svg {
  animation: v-spin 0.7s linear infinite;
}
@keyframes v-spin {
  to {
    transform: rotate(360deg);
  }
}
/* Harakat kamaytirilganda aylanish to'xtaydi; yarim halqa baribir "kutilmoqda" deydi. */
@media (prefers-reduced-motion: reduce) {
  .v-spinner svg {
    animation: none;
    opacity: 0.7;
  }
}
</style>
