<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { History, SquarePen } from 'lucide-vue-next'
import BrandSpark from '../../components/BrandSpark.vue'
import VAvatar from '../../ui/VAvatar.vue'
import VIconButton from '../../ui/VIconButton.vue'

/**
 * Ixcham yuqori panel (48px): chapda tarix, o'rtada suhbat nomi (bir qator), o'ngda
 * yangi suhbat va avatar (sozlamalar). Yon ustunlar teng kenglikda - nom ekranning
 * aynan o'rtasida turadi, tugmalar soni har xil bo'lsa ham.
 *
 * Pastki chiziq faqat suhbat ostiga aylantirilganda chiqadi: tinch holatda panel
 * fon bilan bir, "xrom" ko'rinmaydi.
 *
 * Yangi suhbatda (boshlash uchun hech narsa yo'q) qalam tugmasi YASHIRIN, o'chirilgan
 * emas: kulrang "ishlamaydigan" tugma shovqin. `visibility` - joyi saqlanadi, nom
 * o'rtada qoladi.
 *
 * Nom katta matnda (200%) ham 19px dan oshmaydi - iOS navigatsiya sarlavhasi kabi:
 * tor panelda u tugmalarni siqib chiqarmasin (to'liq nom tarix ro'yxatida).
 */
defineProps<{ title: string; userName: string; scrolled: boolean; canStartNew: boolean }>()
const emit = defineEmits<{ history: []; newChat: []; settings: [] }>()
const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <header class="top" :class="{ 'is-scrolled': scrolled }">
    <div class="top__side">
      <VIconButton class="tg-ib" :icon="History" :label="t('tg.top.history')" :tooltip="false" @click="emit('history')" />
    </div>
    <h1 class="top__title">
      <template v-if="title">{{ title }}</template>
      <span v-else class="top__brand"><BrandSpark :size="14" />Venera</span>
    </h1>
    <div class="top__side top__side--end">
      <VIconButton
        class="tg-ib"
        :icon="SquarePen"
        :label="t('tg.top.newChat')"
        :class="{ 'is-hidden': !canStartNew }"
        :disabled="!canStartNew"
        :tooltip="false"
        @click="emit('newChat')"
      />
      <button type="button" class="top__avatar" :aria-label="t('tg.top.settings')" @click="emit('settings')">
        <VAvatar :name="userName" :size="32" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.top {
  position: relative;
  z-index: var(--z-sticky);
  display: grid;
  /* Yon ustunlar QAT'IY va teng (2 tugma kengligi): nom aynan o'rtada, uzun nom esa
     tugmalar ustiga chiqmasdan "…" bilan qisqaradi. */
  grid-template-columns: calc(var(--tap) * 2) minmax(0, 1fr) calc(var(--tap) * 2);
  align-items: center;
  gap: var(--s-1);
  flex-shrink: 0;
  min-height: 52px;
  /* Xrom chekkasi kompozer bilan BIR XIL (12px): 44px tugma ichidagi 32px avatar
     doirasi 6px ichkarida - ya'ni 6 + 6 = 12. */
  padding: calc(var(--tg-safe-top) + 4px) calc(var(--tg-chrome) - 6px + var(--tg-safe-right)) 4px
    calc(var(--tg-chrome) - 6px + var(--tg-safe-left));
  background: var(--bg);
}
.top::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: var(--line);
  opacity: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.top.is-scrolled::after {
  opacity: 1;
}
.top__side {
  display: flex;
  align-items: center;
}
.top__side--end {
  justify-content: flex-end;
}
.top__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  font-size: min(0.9375rem, 19px);
  line-height: 1.5;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.top__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
}
.top__brand :deep(svg) {
  color: var(--brand);
}
.is-hidden {
  visibility: hidden;
}
.top__avatar {
  display: grid;
  place-items: center;
  width: var(--tap);
  height: var(--tap);
  border-radius: var(--r-full);
  transition: transform var(--dur-1) var(--ease-out);
}
.top__avatar:active {
  transform: scale(0.92);
}
</style>
