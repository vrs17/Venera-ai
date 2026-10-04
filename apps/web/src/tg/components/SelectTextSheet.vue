<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import VSheet from '../../ui/VSheet.vue'
import { useTgSheet } from '../sheet'

/**
 * "Matnni belgilash" - Telegram'dagi "Select text" kabi. Chatda javob uzoq bosilganda
 * tizimning belgilash lupasi o'chiq (u yerda bizning menyu), shuning uchun "butunini
 * nusxalash" bor, lekin "faqat sanani / summani / vazifa raqamini" olib bo'lmasdi - HR
 * yordamchisida esa aynan shu eng ko'p kerak. Bu oynada javob ODDIY matn bo'lib turadi
 * va tizimning o'z belgilash vositasi (tutqichlar, "Nusxa olish") ishlaydi.
 */
defineProps<{ text: string }>()
const open = defineModel<boolean>('open', { default: false })
const { t } = useI18n({ useScope: 'global' })

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
useTgSheet(open, sheet)
</script>

<template>
  <VSheet ref="sheet" v-model:open="open" class="tg-sheet tg-sheet--full" side="bottom" :title="t('tg.chat.selectText')">
    <div class="sel" tabindex="0">{{ text }}</div>
  </VSheet>
</template>

<style scoped>
/* Belgilash shu yerda YOQIQ (ilova bo'ylab o'chiq - styles.css, Exchange.vue). */
.sel {
  padding-bottom: calc(var(--s-4) + var(--tg-safe-bottom));
  color: var(--text);
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body-lg);
  white-space: pre-wrap;
  overflow-wrap: break-word;
  -webkit-user-select: text;
  user-select: text;
  -webkit-touch-callout: default;
  outline: none;
}
</style>
