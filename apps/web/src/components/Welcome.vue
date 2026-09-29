<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Briefcase, CalendarDays, FileText, Headset, Info, Lightbulb, ReceiptText, Wallet } from 'lucide-vue-next'
import type { ActorType } from '../types'
import type { Locale } from '../i18n'
import { chipsFor } from '../i18n'
import BrandSpark from './BrandSpark.vue'

/**
 * Yangi suhbat: markazda uchqun, salomlashuv, yozish maydoni va 3-4 taklif.
 *
 * Ildiz `display: contents` - salomlashuv (order 1) va takliflar (order 3) ota
 * ustunning bevosita bolalari bo'ladi, yozish maydoni (ChatView, order 2) esa ular
 * ORASIGA tushadi. Maydon ChatView'da qoladi: birinchi savol yuborilganda u qayta
 * yaratilmaydi (fokus va holat saqlanadi) - faqat joyi o'zgaradi.
 *
 * Taklif bosilsa - o'sha aniq matn darhol savol bo'lib ketadi (til va aktor turiga
 * qarab). Belgilar mazmunga mos: tartib CHIPS ro'yxati bilan bir xil.
 */
const props = defineProps<{ name: string; actorType: ActorType }>()
const emit = defineEmits<{ chip: [text: string] }>()

const { t, locale } = useI18n({ useScope: 'global' })
const chips = computed(() => chipsFor(locale.value as Locale, props.actorType))

const ICONS: Record<ActorType, Component[]> = {
  // ta'til, ish haqi, xizmat safari, shartnoma namunasi
  EMPLOYEE: [CalendarDays, Wallet, Briefcase, FileText],
  // imkoniyatlar, pul qaytarish, qo'llab-quvvatlash, Venera haqida
  CUSTOMER: [Lightbulb, ReceiptText, Headset, Info],
}
const icons = computed(() => ICONS[props.actorType] ?? ICONS.CUSTOMER)
const greeting = computed(() => (props.name ? t('hello', { name: props.name }) : t('chat.greetingAnon')))
</script>

<template>
  <div class="welcome">
    <div class="welcome__head">
      <span class="welcome__spark" aria-hidden="true"><BrandSpark :size="24" /></span>
      <h1 class="welcome__title">{{ greeting }}</h1>
    </div>
    <ul class="welcome__chips">
      <li v-for="(label, i) in chips" :key="label">
        <button type="button" class="welcome__chip" :title="label" @click="emit('chip', label)">
          <component :is="icons[i % icons.length]" :size="16" :stroke-width="1.75" aria-hidden="true" />
          <span class="welcome__chip-text">{{ label }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.welcome {
  display: contents;
}
.welcome__head {
  order: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-4);
  margin-bottom: var(--s-8);
  padding: 0 var(--gutter);
  text-align: center;
}
.welcome__spark {
  display: inline-flex;
  color: var(--brand);
  user-select: none;
}
.welcome__title {
  font-size: var(--fs-display);
  line-height: var(--lh-display);
  font-weight: 600;
  letter-spacing: -0.028em;
  color: var(--text);
  text-wrap: balance;
  overflow-wrap: anywhere;
}
.welcome__chips {
  order: 3;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--s-2);
  width: 100%;
  max-width: calc(var(--chat-col) + 2 * var(--gutter));
  margin: var(--s-5) 0 0;
  padding: 0 var(--gutter);
  list-style: none;
}
.welcome__chips li {
  display: flex;
  min-width: 0;
  max-width: 100%;
}
.welcome__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  max-width: 100%;
  height: 36px;
  padding: 0 var(--s-4) 0 var(--s-3);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
.welcome__chip svg {
  flex-shrink: 0;
  color: var(--text-3);
}
@media (hover: hover) {
  .welcome__chip:hover {
    background: var(--fill-hover);
    color: var(--text);
  }
}
.welcome__chip:active {
  transform: scale(0.98);
}
.welcome__chip-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 767.98px) {
  .welcome__head {
    margin-bottom: var(--s-6);
  }
  .welcome__title {
    font-size: var(--fs-title-1);
    line-height: var(--lh-title-1);
    letter-spacing: -0.022em;
  }
  /* Telefonda takliflar ustun: uzun o'zbekcha savollar kesilmasin. */
  .welcome__chips {
    flex-direction: column;
    align-items: stretch;
  }
  .welcome__chip {
    width: 100%;
    height: auto;
    min-height: 44px;
    padding-block: var(--s-2);
    border-radius: var(--r-md);
    text-align: left;
  }
  .welcome__chip-text {
    white-space: normal;
  }
}
</style>
