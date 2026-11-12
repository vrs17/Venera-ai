<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Paperclip, Plus } from 'lucide-vue-next'
import VIconButton from '../ui/VIconButton.vue'
import VMenu from '../ui/VMenu.vue'
import VMenuItem from '../ui/VMenuItem.vue'

/**
 * Yozish maydonidagi "+" va uning menyusi: fayl biriktirish (hali yo'q).
 *
 * «Ulanishlar» bandi 2026-11-12 da olib tashlandi (ega so'rovi): HRM va CRM BRB-Tech ID
 * bilan kirganda o'zi ulanadi - odam hech narsani qo'lda ulamaydi.
 *
 * VMenu (qatlam steki) hamma nozik joyni o'zi hal qiladi: "+" ni bosish menyuni yopib
 * qayta ochmaydi (trigger qatlamning bir qismi), Esc faqat eng ustidagi qatlamni yopadi
 * va `preventDefault` qiladi (ChatView yon panelni yig'ib yubormaydi), fokus menyuga
 * kiradi va "+" ga qaytadi. Menyu <body> ga teleport - hech qanday `overflow` uni kesmaydi.
 */
const { t } = useI18n({ useScope: 'global' })
const menuOpen = ref(false)
</script>

<template>
  <VMenu v-model:open="menuOpen" placement="top-start" :offset="8" :min-width="224" :aria-label="t('composer.add')">
    <template #trigger>
      <VIconButton
        class="cmenu__plus"
        :class="{ 'is-open': menuOpen }"
        :label="t('composer.add')"
        :icon="Plus"
        size="sm"
        :active="menuOpen"
        :tooltip="!menuOpen"
      />
    </template>
    <!-- Yuklash hali yo'q: band ko'rinadi (kelishini bilishsin), lekin bosilmaydi. -->
    <VMenuItem :icon="Paperclip" :hint="t('composer.soon')" disabled>{{ t('composer.attach') }}</VMenuItem>
  </VMenu>
</template>

<style scoped>
.cmenu__plus :deep(svg) {
  transition: transform var(--dur-2) var(--ease-out);
}
/* Ochiq menyuda "+" 45° buriladi - "yopish" ma'nosi. */
.cmenu__plus.is-open :deep(svg) {
  transform: rotate(45deg);
}
</style>
