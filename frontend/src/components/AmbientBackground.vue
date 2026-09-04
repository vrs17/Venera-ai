<script setup lang="ts">
/**
 * Static ambient glow that pools behind the answer box at the bottom-centre and
 * fans softly upward. No animation — just a calm warm backdrop. Pure radial
 * gradients (colours from theme tokens, so it repaints with the theme switch).
 * Decorative: pointer-events none, aria-hidden.
 */
</script>

<template>
  <div aria-hidden="true" :style="{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }">
    <!-- Wide, cool base — depth at the edges. -->
    <div
      :style="{
        position: 'absolute',
        left: '50%',
        top: '90%',
        width: '1500px',
        height: '1040px',
        transform: 'translate(-50%, -50%)',
        background: 'var(--glow-base)',
      }"
    />
    <!-- Warm brand core — sits right behind the input box. -->
    <div
      :style="{
        position: 'absolute',
        left: '50%',
        top: '93%',
        width: '1120px',
        height: '760px',
        transform: 'translate(-50%, -50%)',
        background: 'var(--glow-core)',
      }"
    />
  </div>
</template>
