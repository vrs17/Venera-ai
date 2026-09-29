<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Paperclip, Plug, Plus } from 'lucide-vue-next'
import { useConnectors } from '../composables/useConnectors'
import VIconButton from '../ui/VIconButton.vue'
import VMenu from '../ui/VMenu.vue'
import VMenuItem from '../ui/VMenuItem.vue'
import ConnectorDialog from './ConnectorDialog.vue'

/**
 * Yozish maydonidagi "+" va uning menyusi: ulanishlar, fayl biriktirish (hali yo'q).
 *
 * VMenu (qatlam steki) hamma nozik joyni o'zi hal qiladi: "+" ni bosish menyuni yopib
 * qayta ochmaydi (trigger qatlamning bir qismi), Esc faqat eng ustidagi qatlamni yopadi
 * va `preventDefault` qiladi (ChatView yon panelni yig'ib yubormaydi), fokus menyuga
 * kiradi va "+" ga qaytadi. Menyu <body> ga teleport - hech qanday `overflow` uni kesmaydi.
 *
 * Ulanishlar oynasi menyudan TASHQARIDA yashaydi: menyu band tanlanganda yopiladi,
 * oyna esa ochiq qoladi; yopilganda fokus yana "+" ga qaytadi.
 */
const { t } = useI18n({ useScope: 'global' })
const menuOpen = ref(false)
const connectorsOpen = ref(false)

// Har ochilishda holat serverdan yangilanadi: HRM sessiyasi 10 soatda tugaydi, CRM
// refresh rad etilishi mumkin - oynadagi ro'yxat buni ko'rsatishi kerak.
const { load } = useConnectors()
watch(menuOpen, (open) => open && void load())
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
    <VMenuItem :icon="Plug" @select="connectorsOpen = true">{{ t('connectors') }}</VMenuItem>
    <!-- Yuklash hali yo'q: band ko'rinadi (kelishini bilishsin), lekin bosilmaydi. -->
    <VMenuItem :icon="Paperclip" :hint="t('composer.soon')" disabled>{{ t('composer.attach') }}</VMenuItem>
  </VMenu>
  <ConnectorDialog v-model:open="connectorsOpen" />
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
