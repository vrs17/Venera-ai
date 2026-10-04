<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { CircleAlert, Clock, Lock, ShieldAlert } from 'lucide-vue-next'
import type { ChatExchange } from './chat/types'
import ResultShell from './ResultShell.vue'
import ThinkingLoader from './ThinkingLoader.vue'
import MessageActions from './MessageActions.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import AnswerSources from './AnswerSources.vue'
import ActionCard from './ActionCard.vue'
import { proBadge as proOutcome } from './chat/pro'
import VBadge from '../ui/VBadge.vue'
import VTooltip from '../ui/VTooltip.vue'

/**
 * Bitta yordamchi javobi - barcha holatlarda. Ustuvorlik o'zgarmaydi:
 * xato > to'xtatilgan > kutilmoqda > tayyor.
 *
 * Tayyor javob tartibi: (kerak bo'lsa) holat qatori, matn, "to'xtatildi" belgisi,
 * ogohlantirish, tasdiq kartasi, fayl va manbalar, "Pro" natijasi, amallar.
 *
 * Dasturchi rejimi (pipeline izi, mono qator) olib tashlandi: savolning to'liq izi
 * admin panelida ("Savol izi"), oddiy odamga esa texnik qator faqat shovqin edi.
 */
const props = withDefaults(
  defineProps<{
    exchange: ChatExchange
    /** Odam versiyani o'zi tanlay oladi: qaysi versiya javob berganini amallar qatorida
     *  kichik yozuv bilan ko'rsatamiz - ikki versiyani solishtirayotgan odam adashmasin. */
    showEngine?: boolean
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
  { showEngine: false, busy: false, streaming: false, latest: false, reported: false, canTrace: false },
)
const emit = defineEmits<{ regenerate: []; report: [] }>()

const { t } = useI18n({ useScope: 'global' })

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

// "Pro" belgisi: javob OSTIDA, doim ko'rinib turadi ("Pro · ishlatildi (1 ta
// murojaat)"), to'liq gap - tooltip'da. Amallar qatorida emas: u eski javoblarda
// faqat sichqoncha ustiga kelganda chiqadi, pulga tushgan narsa esa yashirinmasin.
// HOLATLAR farqi MUHIM: "ishlatildi" byudjetdan yegan, "kerak bo'lmadi" va
// "berilmadi" esa yemagan (oxirgisida javob standart rejimda va SABABI aytiladi:
// limit, foydalanuvchi yo'q, dvigatel). Blok faqat yordamchi javobida keladi:
// xodimlar ma'lumotnomasi javob bergan bo'lsa belgi yo'q - byudjet ham yeyilmagan.
const proBadge = computed(() => proOutcome(props.exchange.pro, t))

const finished = computed(() => !!props.exchange.response && !props.streaming)
const canReport = computed(() => finished.value && !!(answer.value || props.exchange.proposal))
const traceId = computed(() => (props.canTrace ? (props.exchange.turnId ?? null) : null))

// Javob bergan versiya (`done.engine`). Faqat tanlov bor odamga - qolganlarga bitta
// versiya bor, yozuv hech narsa aytmaydi. Tarixdan ochilgan javobda yo'q (server
// xabar bo'yicha versiyani saqlamaydi) - u holda yozuv ham yo'q, taxmin qilinmaydi.
const engineTag = computed(() => (props.showEngine ? (props.exchange.engine?.trim() || null) : null))
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

      <!-- tabindex: klaviatura bilan ham to'liq gap (tooltip) o'qilsin. -->
      <VTooltip v-if="proBadge && !streaming" :text="proBadge.detail" placement="bottom">
        <div class="res__pro" :class="`is-${proBadge.state}`" tabindex="0">
          <VBadge class="res__pro-badge" size="sm" :tone="proBadge.tone">{{ t('pro.label') }}</VBadge>
          <span class="res__pro-text">{{ proBadge.text }}</span>
        </div>
      </VTooltip>

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
        <VTooltip v-if="engineTag" :text="t('chat.engines.answeredBy', { v: engineTag })">
          <span class="res__engine" tabindex="0">{{ engineTag }}</span>
        </VTooltip>
      </MessageActions>
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
.res__pro {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  max-width: 100%;
  margin-top: var(--s-3);
  border-radius: var(--r-xs);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  cursor: default;
}
.res__pro-text {
  min-width: 0;
  overflow-wrap: anywhere;
}
/* "Berilmadi" - sababi ham sariq matnda: javob standart rejimda, odam buni bilsin. */
.res__pro.is-denied .res__pro-text {
  color: var(--warn-text);
}
/* "Kerak bo'lmadi" - eng jim holat: byudjet yeyilmagan, e'tibor talab qilmaydi. */
.res__pro.is-idle .res__pro-badge {
  --badge-fg: var(--text-3);
  --badge-bg: transparent;
  box-shadow: inset 0 0 0 1px var(--line);
}
/* Versiya yozuvi: vaqt yonida, eng jim rangda - e'tibor talab qilmaydi, faqat
   kerak bo'lganda o'qiladi. Mono shrift: "v1"/"v2" bir xil kenglikda. */
.res__engine {
  padding: 0 var(--s-1);
  border-radius: var(--r-xs);
  color: var(--text-4);
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  cursor: default;
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
