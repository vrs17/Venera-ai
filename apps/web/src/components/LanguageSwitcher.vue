<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Globe } from 'lucide-vue-next'
import { LOCALES, setLocale } from '../i18n'
import type { Locale } from '../i18n'
import VButton from '../ui/VButton.vue'
import VMenu from '../ui/VMenu.vue'
import VMenuItem from '../ui/VMenuItem.vue'
import VTooltip from '../ui/VTooltip.vue'

/**
 * Til tanlash: yuqori paneldagi kichik tugma (globus + qisqa kod) va menyu.
 * Menyu VMenu'da - Esc, strelkalar, harf bilan qidirish va fokusni qaytarish tayyor;
 * joriy til `menuitemradio` + `aria-checked` bilan e'lon qilinadi.
 * Tanlash butun ilovani o'giradi (setLocale: i18n + <html lang> + localStorage).
 */
const { locale, t } = useI18n({ useScope: 'global' })

// Qisqa kodlar tarjima qilinmaydi - har til o'z yozuvida.
const SHORT: Record<Locale, string> = { uz: 'UZ', 'uz-Cyrl': 'ЎЗ', ru: 'RU', en: 'EN' }

const current = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale)) ?? LOCALES[0])

function choose(code: Locale) {
  if (code !== locale.value) setLocale(code)
}
</script>

<template>
  <VMenu placement="bottom-end" :min-width="168" :aria-label="t('language')">
    <template #trigger>
      <VTooltip :text="t('language')" placement="bottom" :describe="false">
        <VButton
          variant="ghost"
          :icon="Globe"
          class="lang-btn"
          :aria-label="`${t('language')}: ${current.label}`"
        >
          <span :lang="current.htmlLang">{{ SHORT[current.code] }}</span>
        </VButton>
      </VTooltip>
    </template>
    <VMenuItem
      v-for="l in LOCALES"
      :key="l.code"
      kind="radio"
      :checked="l.code === current.code"
      :text-value="l.label"
      @select="choose(l.code)"
    >
      <span :lang="l.htmlLang">{{ l.label }}</span>
    </VMenuItem>
  </VMenu>
</template>

<style scoped>
/* Sinf ikki marta: VButton'ning o'z o'lcham/variant o'zgaruvchilaridan ustun tursin. */
.lang-btn.lang-btn {
  --btn-px: 10px;
  --btn-fg: var(--text-2);
  letter-spacing: 0.02em;
}
.lang-btn.lang-btn[aria-expanded='true'] {
  --btn-fg: var(--text);
  background: var(--fill);
}
@media (hover: hover) {
  .lang-btn.lang-btn:hover {
    --btn-fg: var(--text);
  }
}
</style>
