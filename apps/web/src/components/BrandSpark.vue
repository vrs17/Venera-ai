<script setup lang="ts">
/**
 * Venera uchquni (✦) - SVG. Matn belgisi ✦ (U+2726) shriftda yo'q va har OS da
 * boshqacha chiziladi; bu shakl favicon va index.html dagi yuklanish belgisi bilan
 * bir xil. Rangi `currentColor` - odatda ota `color: var(--brand)` beradi.
 */
withDefaults(defineProps<{ size?: number }>(), { size: 16 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true" focusable="false">
    <path
      d="M16 1.5c1.2 8.1 6.4 13.3 14.5 14.5-8.1 1.2-13.3 6.4-14.5 14.5C14.8 22.4 9.6 17.2 1.5 16 9.6 14.8 14.8 9.6 16 1.5Z"
    />
  </svg>
</template>
