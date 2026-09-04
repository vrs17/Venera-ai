<script setup lang="ts">
defineProps<{ label: string }>()
</script>

<template>
  <label :style="{ display: 'block', marginBottom: '10px' }">
    <div :style="{ fontSize: '11.5px', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '4px' }">
      {{ label }}
    </div>
    <slot />
  </label>
</template>
