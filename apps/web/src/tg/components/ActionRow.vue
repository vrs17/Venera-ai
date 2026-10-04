<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Copy, Flag, Loader, Sparkles, Square, Volume2 } from 'lucide-vue-next'
import { copyText } from '../../clipboard'
import { proBadge } from '../../components/chat/pro'
import { useReadAloud } from '../../components/chat/readAloud'
import { formatWhen } from '../../time'
import type { ProInfo } from '../../types'
import { toast } from '../../ui/useToast'
import { usePrefs } from '../prefs'
import { haptic } from '../telegram'

/**
 * Javob ostidagi ixcham amallar qatori: nusxa, xabar berish, (sozlamada yoqilgan
 * bo'lsa) ovoz bilan o'qish, "Pro" belgisi va vaqt. Har tugma 44px nishon, ko'rinishi
 * jim (--text-3) - qator javobdan ko'zni tortmasin.
 *
 * Xabar berilgan javob: bayroq TO'LDIRILGAN va brend rangida - faqat to'qroq bo'lsa,
 * odam "yuborildimi?" deb ikkinchi marta bosardi.
 */
const props = defineProps<{
  id: string
  answer: string
  turnId?: string | null
  pro?: ProInfo | null
  at?: number | null
  reported: boolean
}>()
const emit = defineEmits<{ report: [] }>()
const { t, locale } = useI18n({ useScope: 'global' })
const { readAloud } = usePrefs()
const reader = useReadAloud()

const copied = ref(false)
let copiedTimer = 0

async function copy() {
  if (await copyText(props.answer)) {
    haptic.notify('success')
    copied.value = true
    window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => (copied.value = false), 1600)
  } else {
    toast.error(t('chat.copyFailed'))
  }
}

const reading = computed(() => reader.current.value === props.id)
const pending = computed(() => reader.pending.value === props.id)

async function read() {
  haptic.select()
  const ok = await reader.toggleReading(props.id, props.answer, String(locale.value), props.turnId)
  if (!ok) toast.error(t('chat.readFailed'))
}

const badge = computed(() => proBadge(props.pro, (k, n, p) => (p === undefined ? t(k, n ?? {}) : t(k, n ?? {}, p))))
const when = computed(() => {
  const lang = document.documentElement.lang || String(locale.value)
  return props.at ? formatWhen(props.at, lang) : ''
})
</script>

<template>
  <div class="arow">
    <button type="button" class="arow__btn" :aria-label="copied ? t('ui.copied') : t('ui.copy')" @click="copy">
      <Check v-if="copied" :size="18" :stroke-width="2" aria-hidden="true" />
      <Copy v-else :size="18" :stroke-width="1.75" aria-hidden="true" />
    </button>
    <button
      type="button"
      class="arow__btn"
      :class="{ 'is-reported': reported }"
      :aria-label="reported ? t('report.reportedTooltip') : t('report.reportAnswer')"
      @click="emit('report')"
    >
      <Flag :size="18" :stroke-width="1.75" :fill="reported ? 'currentColor' : 'none'" aria-hidden="true" />
    </button>
    <button
      v-if="readAloud && reader.canSpeak(String(locale))"
      type="button"
      class="arow__btn"
      :class="{ 'is-on': reading }"
      :aria-label="reading || pending ? t('chat.stopReading') : t('chat.readAloud')"
      :aria-pressed="reading ? 'true' : 'false'"
      @click="read"
    >
      <Loader v-if="pending" class="arow__spin" :size="18" :stroke-width="1.75" aria-hidden="true" />
      <Square v-else-if="reading" :size="16" :stroke-width="2" aria-hidden="true" />
      <Volume2 v-else :size="18" :stroke-width="1.75" aria-hidden="true" />
    </button>
    <span v-if="badge" class="arow__pro" :class="`is-${badge.state}`" :title="badge.detail">
      <Sparkles :size="12" :stroke-width="2" aria-hidden="true" />
      <span>Pro · {{ badge.text }}</span>
    </span>
    <span v-if="when" class="arow__time">{{ when }}</span>
    <span class="sr-only" aria-live="polite">{{ copied ? t('tg.chat.copied') : '' }}</span>
  </div>
</template>

<style scoped>
.arow {
  display: flex;
  align-items: center;
  gap: 0;
  min-height: var(--tap);
  margin: var(--s-1) 0 0 calc(var(--s-3) * -1);
}
.arow__btn {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--tap);
  height: var(--tap);
  border-radius: var(--r-full);
  color: var(--text-3);
  transition:
    transform var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
.arow__btn:active {
  transform: scale(0.9);
  background: var(--fill);
}
.arow__btn.is-on {
  color: var(--text);
}
.arow__btn.is-reported {
  color: var(--brand);
}
.arow__spin {
  animation: arow-spin 1s linear infinite;
}
@keyframes arow-spin {
  to {
    transform: rotate(360deg);
  }
}
.arow__pro {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  margin-left: var(--s-1);
  padding: 2px var(--s-2);
  border-radius: var(--r-full);
  background: var(--brand-soft);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.arow__pro svg {
  flex-shrink: 0;
  color: var(--brand);
}
.arow__pro.is-denied {
  background: var(--warn-soft);
  color: var(--warn-text);
}
.arow__time {
  margin-left: auto;
  padding-left: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
</style>
