<script setup lang="ts">
import type { Component } from 'vue'

/**
 * Bo'sh holat: belgi (40px doira ichida), qisqa sarlavha, bitta qator izoh va ko'pi
 * bilan bitta harakat. Ko'p so'z yozilmaydi - UI o'zi ko'rsatib turgan narsa
 * tushuntirilmaydi (spec §0.2).
 */
withDefaults(
  defineProps<{
    icon?: Component
    title?: string
    description?: string
    compact?: boolean
  }>(),
  {},
)
</script>

<template>
  <div class="v-empty" :class="{ 'v-empty--compact': compact }">
    <span v-if="icon || $slots.icon" class="v-empty__icon" aria-hidden="true">
      <slot name="icon"><component :is="icon" :size="18" :stroke-width="1.75" /></slot>
    </span>
    <p v-if="title" class="v-empty__title">{{ title }}</p>
    <p v-if="description" class="v-empty__desc">{{ description }}</p>
    <div v-if="$slots.default" class="v-empty__action"><slot /></div>
  </div>
</template>

<style scoped>
.v-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--s-12) var(--s-6);
  text-align: center;
}
.v-empty--compact {
  padding: var(--s-8) var(--s-4);
}
.v-empty__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin-bottom: var(--s-4);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-3);
}
.v-empty__title {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.006em;
}
.v-empty__desc {
  max-width: 36ch;
  margin-top: var(--s-0_5);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}
.v-empty__action {
  margin-top: var(--s-5);
}
</style>
