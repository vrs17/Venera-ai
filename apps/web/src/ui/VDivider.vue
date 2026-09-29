<script setup lang="ts">
/**
 * Soch tolasidek chiziq. `label` berilsa - o'rtasida qisqa yozuv ("yoki").
 * `spacing` - chiziq atrofidagi bo'shliq (gorizontalda yuqori/past, vertikalda chap/o'ng).
 */
withDefaults(
  defineProps<{
    orientation?: 'horizontal' | 'vertical'
    spacing?: 'none' | 'xs' | 'sm' | 'md' | 'lg'
    label?: string
  }>(),
  { orientation: 'horizontal', spacing: 'none' },
)
</script>

<template>
  <div
    v-if="label && orientation === 'horizontal'"
    class="v-divider v-divider--label"
    :class="`v-divider--${spacing}`"
    role="separator"
  >
    <span class="v-divider__text">{{ label }}</span>
  </div>
  <div
    v-else
    class="v-divider"
    :class="[`v-divider--${orientation}`, `v-divider--${spacing}`]"
    role="separator"
    :aria-orientation="orientation"
  />
</template>

<style scoped>
.v-divider {
  flex-shrink: 0;
  border: 0;
}
.v-divider--horizontal {
  height: 1px;
  width: 100%;
  background: var(--line);
}
.v-divider--vertical {
  width: 1px;
  align-self: stretch;
  min-height: 1em;
  background: var(--line);
}

.v-divider--horizontal.v-divider--xs,
.v-divider--label.v-divider--xs { margin-block: var(--s-1); }
.v-divider--horizontal.v-divider--sm,
.v-divider--label.v-divider--sm { margin-block: var(--s-2); }
.v-divider--horizontal.v-divider--md,
.v-divider--label.v-divider--md { margin-block: var(--s-4); }
.v-divider--horizontal.v-divider--lg,
.v-divider--label.v-divider--lg { margin-block: var(--s-6); }
.v-divider--vertical.v-divider--xs { margin-inline: var(--s-1); }
.v-divider--vertical.v-divider--sm { margin-inline: var(--s-2); }
.v-divider--vertical.v-divider--md { margin-inline: var(--s-4); }
.v-divider--vertical.v-divider--lg { margin-inline: var(--s-6); }

.v-divider--label {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.v-divider--label::before,
.v-divider--label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line);
}
.v-divider__text {
  flex-shrink: 0;
}
</style>
