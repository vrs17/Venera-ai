<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Flag, RotateCcw, Square, Volume2, Workflow } from 'lucide-vue-next'
import { LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { formatFull, formatWhen } from '../time'
import VIconButton from '../ui/VIconButton.vue'
import VTooltip from '../ui/VTooltip.vue'
import { toast } from '../ui/useToast'
import CopyButton from './CopyButton.vue'
import { useReadAloud } from './chat/readAloud'

/**
 * Javob ostidagi amallar: nusxa, qayta yaratish, ovoz chiqarib o'qish, xabar berish
 * va (ADMIN uchun) savol izi. Sichqonchali qurilmada javob ustiga kelganda
 * ko'rinadi, sensorli ekranda doim turadi (qoida - ota komponentda).
 *
 * - Nusxa - faqat matn bo'lsa.
 * - Qayta yaratish - DOIM (xato va to'xtatilgan javobda ham - "qayta urinish"),
 *   boshqa so'rov ketayotganda o'chiq.
 * - Vaqt - javob TUGAGAN payt, qator oxirida; to'liq sana tooltip'da.
 */
const props = withDefaults(
  defineProps<{
    copyText?: string | null
    busy?: boolean
    at?: number | null
    /** O'qish uchun kalit (exchange id) va matn. Matn yo'q - tugma yo'q. */
    speakKey?: string
    speakText?: string | null
    /** O'qilayotgan javobning savol kaliti (`X-Venera-Turn`). */
    speakTurn?: string | null
    /** "Xabar berish" ko'rsatilsinmi: tugagan javoblarda VA xato bilan tugaganlarida -
     *  odamlar aynan yiqilgan javob haqida xabar bermoqchi bo'ladi (`X-Venera-Turn` xatoda
     *  ham keladi, backend yiqilgan savolni ham yozadi). */
    canReport?: boolean
    reported?: boolean
    /** Savol izi havolasi uchun (ADMIN va kalit ma'lum bo'lsa). */
    traceId?: string | null
  }>(),
  { copyText: null, at: null, speakKey: '', speakText: null, speakTurn: null, canReport: false, reported: false, traceId: null },
)
const emit = defineEmits<{ regenerate: []; report: [] }>()

const { t, locale } = useI18n({ useScope: 'global' })
const lang = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale))?.htmlLang ?? 'uz-Latn')
const when = computed(() => (props.at ? formatWhen(props.at, lang.value) : ''))
const full = computed(() => (props.at ? formatFull(props.at, lang.value) : ''))

const reader = useReadAloud()
const canRead = computed(() => !!props.speakKey && !!props.speakText && reader.canSpeak(String(locale.value)))
const reading = computed(() => reader.current.value === props.speakKey)
const readingPending = computed(() => reader.pending.value === props.speakKey)

async function onRead() {
  if (!props.speakText) return
  const ok = await reader.toggleReading(props.speakKey, props.speakText, String(locale.value), props.speakTurn)
  if (!ok) toast.error(t('chat.readFailed'))
}
</script>

<template>
  <div class="acts">
    <CopyButton v-if="copyText" :text="copyText" />
    <VIconButton size="sm" :icon="RotateCcw" :label="t('regenerate')" :disabled="busy" @click="emit('regenerate')" />
    <VIconButton
      v-if="canRead"
      size="sm"
      :icon="reading || readingPending ? Square : Volume2"
      :label="reading || readingPending ? t('chat.stopReading') : t('chat.readAloud')"
      :pressed="reading"
      :loading="readingPending"
      @click="onRead"
    />
    <VIconButton
      v-if="canReport"
      size="sm"
      class="acts__flag"
      :class="{ 'is-reported': reported }"
      :label="reported ? t('report.reportedTooltip') : t('report.reportAnswer')"
      @click="emit('report')"
    >
      <Flag :size="16" :stroke-width="1.75" :fill="reported ? 'currentColor' : 'none'" aria-hidden="true" />
    </VIconButton>
    <VIconButton
      v-if="traceId"
      size="sm"
      :icon="Workflow"
      :label="t('chat.trace')"
      :to="{ name: 'admin-turn', params: { id: traceId } }"
      target="_blank"
    />
    <!-- Javobga oid kichik belgilar - vaqtdan oldin. ("Pro" belgisi bu yerdan javob
         ostiga ko'chdi: eski javoblarda amallar faqat hover'da ko'rinadi.) -->
    <slot />
    <VTooltip v-if="at" :text="full">
      <time class="acts__time" :datetime="new Date(at).toISOString()">{{ when }}</time>
    </VTooltip>
  </div>
</template>

<style scoped>
.acts {
  display: flex;
  align-items: center;
  gap: var(--s-0_5);
  /* Birinchi belgining optik cheti matn chetiga to'g'ri kelsin. */
  margin-left: calc(var(--s-2) * -1);
}
.acts__flag.is-reported {
  background: var(--brand-soft);
  color: var(--brand);
}
.acts__time {
  margin-left: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  cursor: default;
}
</style>
