<script setup lang="ts">
import type { Component } from 'vue'
import BrandSpark from './BrandSpark.vue'

/**
 * Yordamchi javobining ramkasi: kichik brend uchquni (faqat keng ekranda, ustun
 * chetidan tashqarida - matn to'liq kenglikda qoladi) va ixtiyoriy holat qatori.
 *
 * Holat qatori - pufak/pill emas, belgi + bitta gap: "bloklandi", "ruxsat yo'q",
 * "modul tayyor emas". Oddiy javobda umuman yo'q.
 */
defineProps<{
  notice?: { text: string; tone: 'neutral' | 'warn' | 'crit'; icon: Component } | null
}>()
</script>

<template>
  <div class="shell">
    <span class="shell__spark" aria-hidden="true"><BrandSpark :size="14" /></span>
    <div class="shell__body">
      <p v-if="notice" class="shell__notice" :class="`is-${notice.tone}`">
        <component :is="notice.icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
        <span>{{ notice.text }}</span>
      </p>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.shell {
  position: relative;
}
.shell__spark {
  display: none;
  position: absolute;
  top: 4px;
  left: -36px;
  width: 20px;
  height: 20px;
  place-items: center;
  color: var(--brand);
  user-select: none;
}
@media (min-width: 1120px) {
  .shell__spark {
    display: grid;
  }
}
.shell__body {
  min-width: 0;
}
.shell__notice {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  margin-bottom: var(--s-2);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.shell__notice svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.shell__notice.is-warn svg {
  color: var(--warn-text);
}
.shell__notice.is-crit svg {
  color: var(--crit-text);
}
</style>
