<script setup lang="ts">
import type { Component } from 'vue'

/**
 * Holat yoki teg. Rang hech qachon yolg'iz kelmaydi - har doim matn bilan.
 *
 * - odatiy: yumshoq fon + to'q matn (rollar, yo'nalish, sabab);
 * - `dot`: fonsiz, rangli nuqta + oddiy matn (jadvaldagi jim holat ustuni).
 */
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'good' | 'warn' | 'crit' | 'brand' | 'info'
    dot?: boolean
    size?: 'sm' | 'md'
    icon?: Component
  }>(),
  { tone: 'neutral', size: 'md' },
)
</script>

<template>
  <span class="v-badge" :class="[`v-badge--${tone}`, `v-badge--${size}`, { 'v-badge--dot': dot }]">
    <span v-if="dot" class="v-badge__dot" aria-hidden="true" />
    <component :is="icon" v-else-if="icon" class="v-badge__icon" :size="12" :stroke-width="2" aria-hidden="true" />
    <slot />
  </span>
</template>

<style scoped>
.v-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  height: 20px;
  padding: 0 var(--s-2);
  border-radius: var(--r-xs);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  letter-spacing: 0;
  white-space: nowrap;
  vertical-align: middle;
  font-variant-numeric: tabular-nums;
  --badge-fg: var(--text-2);
  --badge-bg: var(--fill);
  --badge-dot: var(--text-4);
  background: var(--badge-bg);
  color: var(--badge-fg);
}
.v-badge--sm {
  height: 18px;
  padding: 0 var(--s-1_5);
  font-size: 11.5px;
  gap: var(--s-1);
}

.v-badge--good { --badge-fg: var(--good-text); --badge-bg: var(--good-soft); --badge-dot: var(--good); }
.v-badge--warn { --badge-fg: var(--warn-text); --badge-bg: var(--warn-soft); --badge-dot: var(--warn); }
.v-badge--crit { --badge-fg: var(--crit-text); --badge-bg: var(--crit-soft); --badge-dot: var(--crit); }
/* Nuqta ham holat/matn tokenidan - --viz-* faqat grafiklar uchun. */
.v-badge--info { --badge-fg: var(--info-text); --badge-bg: var(--info-soft); --badge-dot: var(--info-text); }
/* Brend to'q sarig'i yumshoq fonda kichik matn uchun kontrasti yetmaydi - matn rangiga
   aralashtirib quyuqlashtiramiz (qorong'i mavzuda aksincha och bo'ladi): AA saqlanadi. */
.v-badge--brand {
  --badge-fg: color-mix(in srgb, var(--brand) 72%, var(--text));
  --badge-bg: var(--brand-soft);
  --badge-dot: var(--brand);
}

.v-badge--dot {
  background: transparent;
  padding: 0;
  gap: var(--s-1_5);
  color: var(--text-2);
}
.v-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--r-full);
  background: var(--badge-dot);
  flex-shrink: 0;
}
.v-badge__icon {
  flex-shrink: 0;
  margin-left: -2px;
}
</style>
