<script setup lang="ts">
// Primary auth CTA: the brand-gradient pill. `btn-gradient` (global) supplies
// the hover-brightness + active-scale; a one-shot glint sweeps when the form
// becomes valid; a spinning ✦ shows while a submit is pending.
defineProps<{ label: string; valid?: boolean; busy?: boolean }>()
</script>

<template>
  <button
    type="submit"
    class="btn-gradient auth-btn"
    :class="{ glint: valid && !busy, 'glint-once': valid && !busy }"
    :disabled="busy"
    :aria-busy="busy"
    :style="{ background: 'var(--accent)', color: 'var(--accent-contrast)' }"
  >
    <span v-if="busy" class="auth-btn__spark" aria-hidden="true">✦</span>
    <span>{{ label }}</span>
  </button>
</template>

<style scoped>
.auth-btn {
  position: relative;
  width: 100%;
  border: none;
  border-radius: 999px;
  padding: 12px 18px;
  font-size: 15px;
  font-weight: 600;
  font-family: 'Figtree', sans-serif;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: filter 0.2s, transform 0.1s;
  overflow: hidden;
}
.auth-btn:disabled {
  cursor: default;
}
.auth-btn__spark {
  display: inline-flex;
  animation: spinSlow 1s linear infinite;
}
@media (prefers-reduced-motion: reduce) {
  .auth-btn__spark {
    animation: none !important;
  }
}
</style>
