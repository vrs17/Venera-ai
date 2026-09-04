<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  /** Null/omitted hides the status pill (user mode shows just the answer). */
  badge?: { label: string; color: string; bg: string; border: string; icon: Component } | null
}>()
</script>

<template>
  <div :style="{ display: 'flex', gap: '12px', margin: '14px 0' }">
    <div
      :style="{
        width: '28px',
        height: '28px',
        borderRadius: '50%',
        background: 'var(--ink)',
        color: 'var(--ink-contrast)',
        fontSize: '13px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        marginTop: '2px',
      }"
    >
      ✦
    </div>
    <div :style="{ flex: 1, minWidth: 0 }">
      <div
        v-if="badge"
        class="glint glint-once"
        :style="{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '12px',
          fontWeight: 600,
          color: badge.color,
          background: badge.bg,
          border: `1px solid ${badge.border}`,
          borderRadius: '999px',
          padding: '4px 10px 4px 8px',
          marginBottom: '10px',
        }"
      >
        <component :is="badge.icon" stroke="currentColor" />
        {{ badge.label }}
      </div>
      <slot />
    </div>
  </div>
</template>
