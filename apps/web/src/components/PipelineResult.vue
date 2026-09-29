<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { CircleAlert, Clock, Lock, ShieldAlert } from 'lucide-vue-next'
import type { MsgKey } from '../i18n'
import type { ChatExchange } from './chat/types'
import ResultShell from './ResultShell.vue'
import TraceStages from './TraceStages.vue'
import ThinkingLoader from './ThinkingLoader.vue'
import MessageActions from './MessageActions.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import AnswerSources from './AnswerSources.vue'
import ActionCard from './ActionCard.vue'
import VBadge from '../ui/VBadge.vue'
import VTooltip from '../ui/VTooltip.vue'

/**
 * Bitta yordamchi javobi - barcha holatlarda. Ustuvorlik o'zgarmaydi:
 * xato > to'xtatilgan > kutilmoqda > tayyor.
 *
 * Tayyor javob tartibi: (kerak bo'lsa) holat qatori, matn, "to'xtatildi" belgisi,
 * ogohlantirish, tasdiq kartasi, fayl va manbalar, amallar. Dasturchi rejimida
 * oxirida bitta mono qator: yo'nalish, vaqt, audit kaliti.
 */
const props = withDefaults(
  defineProps<{
    exchange: ChatExchange
    devMode: boolean
    /** Istalgan so'rov ketmoqda - "Qayta yaratish" o'chiq. */
    busy?: boolean
    /** Aynan SHU javob hozir yozilmoqda: kursor, amallar hali yo'q. */
    streaming?: boolean
    /** Oxirgi javob: amallar sichqonchasiz ham ko'rinib turadi. */
    latest?: boolean
    reported?: boolean
    /** ADMIN: amallarda savol izi havolasi. */
    canTrace?: boolean
  }>(),
  { busy: false, streaming: false, latest: false, reported: false, canTrace: false },
)
const emit = defineEmits<{ regenerate: []; report: [] }>()

const { t } = useI18n({ useScope: 'global' })

/** Dasturchi qatoridagi holat nomi. Noma'lum `READY_*` - "Tayyor" (yiqilmaydi). */
const STATUS_LABEL: Record<string, MsgKey> = {
  READY_FOR_HR_RAG: 'statusReady',
  READY_FOR_PUBLIC_RAG: 'statusReady',
  READY_FOR_OPENAI: 'statusReady',
  PUBLIC_RAG_NO_RELEVANT_CONTEXT: 'statusNoContext',
  RAG_DOMAIN_NOT_READY: 'statusModuleNotReady',
  STOP_ACCESS_DENIED: 'statusAccessDenied',
  STOP_UNSAFE: 'statusBlocked',
}

const DOMAIN_LABEL: Record<string, MsgKey> = {
  HR: 'domainHR',
  PUBLIC_DOMAIN: 'domainPublic',
  PUBLIC_GENERAL: 'domainGeneral',
  FUTURE_DOMAIN: 'domainFuture',
}

// Guard/access `reason` matnlari backenddan keladi (u yerda allaqachon tarjima
// qilingan); bu yerdagi matnlar - faqat backend sabab bermasa.
const headline = computed<string | null>(() => {
  const r = props.exchange.response
  if (!r) return null
  if (r.finalStatus === 'STOP_UNSAFE') return r.guard?.reason || t('headlineUnsafe')
  if (r.finalStatus === 'STOP_ACCESS_DENIED') return r.access?.reason || t('headlineAccessDenied')
  // Matnsiz tasdiq kartasi ham to'liq javob - "javob kelmadi" deyish noto'g'ri.
  if (r.answer || props.exchange.proposal) return null
  if (r.finalStatus === 'RAG_DOMAIN_NOT_READY') return t('headlineModuleNotReady')
  // Oqim hali davom etsa, bo'sh javob - "hali yozilmagan", xato emas.
  if (props.streaming) return null
  return t('headlinePending')
})

/** Foydalanuvchi ko'radigan holat: faqat bloklangan / ruxsat yo'q / modul tayyor emas. */
const notice = computed<{ text: string; tone: 'neutral' | 'warn' | 'crit'; icon: Component } | null>(() => {
  const r = props.exchange.response
  if (!r || !headline.value) return null
  if (r.finalStatus === 'STOP_UNSAFE') return { text: headline.value, tone: 'crit', icon: ShieldAlert }
  if (r.finalStatus === 'STOP_ACCESS_DENIED') return { text: headline.value, tone: 'warn', icon: Lock }
  if (r.finalStatus === 'RAG_DOMAIN_NOT_READY') return { text: headline.value, tone: 'warn', icon: Clock }
  return null
})

const answer = computed(() => props.exchange.response?.answer ?? '')

// Nusxa: javob matni, bo'lmasa - holat jumlasi.
const copyText = computed(() => answer.value || headline.value || null)

// "Pro" belgisi: rejim so'ralgan turlarda amallar qatorida kichik "Pro", tafsiloti
// tooltip'da. UCH HOLAT, farqi MUHIM: "ishlatildi" byudjetdan yegan, "kerak
// bo'lmadi" va "berilmadi" esa yemagan (ikkinchisida javob standart rejimda va
// SABABI aytiladi). Blok faqat yordamchi javobida keladi: xodimlar ma'lumotnomasi
// javob bergan bo'lsa belgi yo'q - byudjet ham yeyilmagan.
const proBadge = computed<{ text: string; tone: 'neutral' | 'warn'; idle: boolean } | null>(() => {
  const info = props.exchange.pro
  if (!info) return null
  if (info.used) return { text: t('pro.used'), tone: 'neutral', idle: false }
  if (info.reason) {
    const why = info.reason === 'limit' ? t('pro.reasonLimit')
      : info.reason === 'no user' ? t('pro.reasonNoUser')
      : info.reason
    return { text: t('pro.denied', { why }), tone: 'warn', idle: false }
  }
  return { text: t('pro.notNeeded'), tone: 'neutral', idle: true }
})

const finished = computed(() => !!props.exchange.response && !props.streaming)
const canReport = computed(() => finished.value && !!(answer.value || props.exchange.proposal))
const traceId = computed(() => (props.canTrace ? (props.exchange.turnId ?? null) : null))

const devMeta = computed(() => {
  if (!props.devMode) return []
  const ex = props.exchange
  const r = ex.response
  const parts: string[] = []
  if (r) {
    const status = STATUS_LABEL[r.finalStatus]
    parts.push(status ? t(status) : String(r.finalStatus))
    const domain = r.domain ? DOMAIN_LABEL[r.domain] : undefined
    if (r.domain) parts.push(domain ? t(domain) : String(r.domain))
  }
  if (ex.route) parts.push(t('answerRoute', { route: ex.route }))
  if (ex.durationMs != null) parts.push(t('roundTrip', { n: (ex.durationMs / 1000).toFixed(2) }))
  if (ex.requestId) parts.push(ex.requestId)
  return parts
})
</script>

<template>
  <div class="res" :class="{ 'is-latest': latest }">
    <ResultShell v-if="exchange.error">
      <p class="res__error">
        <CircleAlert :size="18" :stroke-width="1.75" aria-hidden="true" />
        <span>{{ exchange.error }}</span>
      </p>
      <!-- Xato ham "Xabar berish"ga loyiq - odamlar aynan yiqilgan javob haqida xabar beradi;
           `turnId` (X-Venera-Turn) xatoda ham keladi, backend yiqilgan savolni ham yozadi. -->
      <MessageActions
        class="res__acts"
        :busy="busy"
        :at="exchange.answeredAt"
        :can-report="true"
        :reported="reported"
        :trace-id="traceId"
        @regenerate="emit('regenerate')"
        @report="emit('report')"
      />
    </ResultShell>

    <ResultShell v-else-if="exchange.cancelled">
      <p class="res__muted">{{ t('generationStopped') }}</p>
      <MessageActions class="res__acts" :busy="busy" :at="exchange.answeredAt" @regenerate="emit('regenerate')" />
    </ResultShell>

    <!-- Yordamchi nima qilayotganini aytadi ("hujjatlar qidirilmoqda") - kutishning
         sababi bor. Birinchi bosqich kelguncha - "O'ylayapman". -->
    <ResultShell v-else-if="!exchange.response">
      <ThinkingLoader :status="exchange.stage || undefined" />
    </ResultShell>

    <ResultShell v-else :notice="notice">
      <p v-if="headline && !notice" class="res__muted">{{ headline }}</p>

      <MarkdownMessage v-if="answer" :source="answer" :sources="exchange.sources" :streaming="streaming" />
      <p v-if="exchange.stopped" class="res__stopped">{{ t('chat.stopped') }}</p>

      <!-- Javobning bir qismi kelgandan KEYIN nimadir yiqildi: kelgan qism qoladi,
           bu qator nima yetishmayotganini aytadi. -->
      <p v-if="exchange.warning" class="res__warning" role="status">{{ exchange.warning }}</p>

      <!-- Yordamchi o'zgartirish taklif qildi: "Tasdiqlash" bosilmaguncha hech narsa
           o'zgarmaydi. -->
      <ActionCard v-if="exchange.proposal" :key="exchange.proposal.token" :proposal="exchange.proposal" />

      <AnswerSources v-if="!streaming" :sources="exchange.sources" :artifact="exchange.artifact" />

      <MessageActions
        v-if="!streaming"
        class="res__acts"
        :copy-text="copyText"
        :busy="busy"
        :at="exchange.answeredAt"
        :speak-key="exchange.id"
        :speak-text="answer || null"
        :speak-turn="exchange.turnId ?? null"
        :can-report="canReport"
        :reported="reported"
        :trace-id="traceId"
        @regenerate="emit('regenerate')"
        @report="emit('report')"
      >
        <!-- tabindex: klaviatura bilan ham tafsilot (tooltip) ko'rinsin. -->
        <VTooltip v-if="proBadge" :text="proBadge.text">
          <VBadge class="res__pro" :class="{ 'is-idle': proBadge.idle }" size="sm" :tone="proBadge.tone" tabindex="0">
            {{ t('pro.label') }}
          </VBadge>
        </VTooltip>
      </MessageActions>

      <!-- Dasturchi rejimi: to'liq iz (faqat /ask yo'lida bor) yoki bitta mono qator. -->
      <div v-if="devMode && exchange.response.guard" class="res__trace">
        <TraceStages :response="exchange.response" :default-open="true" />
      </div>
      <p v-if="devMeta.length" class="res__dev">
        <span v-for="(part, i) in devMeta" :key="i">{{ part }}</span>
      </p>
    </ResultShell>
  </div>
</template>

<style scoped>
.res__error {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.res__error svg {
  flex-shrink: 0;
  margin-top: 3px;
  color: var(--crit-text);
}
.res__muted {
  color: var(--text-3);
  font-size: var(--fs-body);
  line-height: var(--lh-body-lg);
}
.res__stopped {
  margin-top: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.res__warning {
  margin-top: var(--s-3);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.res :deep(.res__acts) {
  margin-top: var(--s-2);
}
.res__trace {
  margin-top: var(--s-4);
}
.res__pro {
  margin-left: var(--s-1);
  cursor: default;
}
/* "Kerak bo'lmadi" - eng jim holat: byudjet yeyilmagan, e'tibor talab qilmaydi. */
.res__pro.is-idle {
  --badge-fg: var(--text-3);
  --badge-bg: transparent;
  box-shadow: inset 0 0 0 1px var(--line);
}
.res__pro:focus-visible {
  border-radius: var(--r-xs);
}
.res__dev {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-1) var(--s-3);
  margin-top: var(--s-2);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
}

/* Amallar: sichqonchali qurilmada javob ustida (yoki fokus ichida) ko'rinadi, oxirgi
   javobda - doim. Sensorli ekranda doim: aks holda ularga yetib bo'lmasdi. */
@media (hover: hover) {
  .res:not(.is-latest) :deep(.res__acts) {
    opacity: 0;
    transition: opacity var(--dur-2) var(--ease-out);
  }
  .res:hover :deep(.res__acts),
  .res:focus-within :deep(.res__acts) {
    opacity: 1;
  }
}
</style>
