<script lang="ts">
import { markRaw, shallowRef } from 'vue'
import type { Component } from 'vue'

// Markdown bo'lagi - BITTA, hamma javoblar uchun umumiy (modul darajasida).
const markdown = shallowRef<Component | null>(null)
let loading: Promise<void> | null = null

/** markdown-it + DOMPurify bo'lagini yuklaydi. ChatScreen buni bo'sh paytda oldindan
 *  chaqiradi - birinchi javob kelganda bo'lak tayyor turadi. */
export function loadMarkdown(): Promise<void> {
  loading ??= import('../../components/MarkdownMessage.vue').then(
    (m) => {
      markdown.value = markRaw(m.default)
    },
    () => {
      // Tarmoq uzildi - keyingi javobda qayta urinadi; hozircha oddiy matn.
      loading = null
    },
  )
  return loading
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, KeyRound, RotateCw, TriangleAlert } from 'lucide-vue-next'
import BrandSpark from '../../components/BrandSpark.vue'
import ThinkingLoader from '../../components/ThinkingLoader.vue'
import { longPress } from '../chat/longPress'
import { closeDangling, observeAnswer, trimStreamingTable, uzApostrophes } from '../chat/polish'
import { lookupBadges, sourceItems } from '../chat/sources'
import { isAuthCode } from '../chat/useTgChat'
import type { TgExchange } from '../chat/useTgChat'
import { haptic, openLink } from '../telegram'
import ActionRow from './ActionRow.vue'
import ArtifactCard from './ArtifactCard.vue'
import ProposalCard from './ProposalCard.vue'
import SourcesRow from './SourcesRow.vue'

/**
 * Bitta savol-javob. Savol - o'ngda pufakcha; javob - to'liq kenglikda, pufakchasiz
 * (o'qish uchun eng keng ustun, 16/26). Ostida: manbalar qatori, ariza/taklif kartasi,
 * amallar qatori.
 *
 * MARKDOWN KECH YUKLANADI: markdown-it + DOMPurify ilovaning birinchi ochilishiga
 * kerak emas (salomlashuv ekrani). Bo'lak kelguncha javob oddiy matn bo'lib turadi -
 * bo'sh joy yoki sakrash yo'q. Chizilgan HTML Mini App uchun pardozlanadi
 * (chat/polish.ts): "T1" o'rniga "CRM", chip va nuqta yolg'iz qatorga tushmaydi,
 * o'zbekcha tutuq belgilari bir xil.
 *
 * Iqtibos chipi va havolalar ushlanadi (capture): web'da chip hujjat ko'ruvchisini
 * ochadi (pdf.js) - Mini App'da esa manbalar oynasi; havola - Telegram'ning `openLink`
 * i (Mini App yopilmaydi).
 *
 * XATO KARTASI tinch (qizil faqat belgida - qizil fon xavfli amal uchun saqlanadi).
 * HRM/CRM tokeni yo'q bo'lsa "Qayta urinish" o'rniga "Qayta ulash": takror so'rash
 * tokenni paydo qilmaydi, qayta kirish esa qiladi.
 *
 * `landed` - javob shu sessiyada jonli keldi: manbalar va amallar qatori 4px pastdan
 * "ko'tarilib" chiqadi (tarixdan ochilganda - jim).
 */
const props = defineProps<{
  exchange: TgExchange
  streaming: boolean
  reported: boolean
  landed?: boolean
}>()
const emit = defineEmits<{
  cite: [marker: string | null]
  report: []
  menu: [part: 'question' | 'answer', el: HTMLElement]
  retry: []
  reconnect: []
}>()
const { t, locale } = useI18n({ useScope: 'global' })

const ex = computed(() => props.exchange)
const answer = computed(() => ex.value.response?.answer ?? '')
/** Oqim paytida chala jadval qatori yashiriladi (bo'sh kataklar chiqmasin); oqimda
 *  yoki to'xtatilgan javobda yopilmagan `**` yopiladi. */
const shown = computed(() => {
  // Manbasiz javob (boshqa qurilmada berilgan, tarixdan ochilgan - server manbani
  // saqlamaydi): "[1]" belgisi hech qayerga olib bormaydi, faqat texnik shovqin.
  const text = ex.value.sources?.length ? answer.value : answer.value.replace(/[ \u00a0]?\[T?\d{1,3}\]/g, '')
  if (props.streaming) return closeDangling(trimStreamingTable(text))
  return ex.value.stopped ? closeDangling(text) : text
})
const items = computed(() => sourceItems(ex.value.sources, (k, n) => t(k, n ?? {}), String(locale.value) === 'uz'))
watch(answer, (text) => text && !markdown.value && void loadMarkdown(), { immediate: true })
const pending = computed(() => !ex.value.response && !ex.value.error && !ex.value.cancelled)
const finished = computed(() => !!ex.value.response && !props.streaming)
const needsLogin = computed(() => isAuthCode(ex.value.errorCode))
const uzLatin = computed(() => String(locale.value) === 'uz')
/** Xizmat matni (ogohlantirish, xato) ham interfeys tutuq belgilarida. */
const fix = (text: string | null | undefined) => (text && uzLatin.value ? uzApostrophes(text) : (text ?? ''))
const plain = computed(() => fix(shown.value))

/* ── Pardoz: MarkdownMessage har chizgandan keyin ── */
const answerEl = ref<HTMLElement | null>(null)
let stopObserving: (() => void) | null = null
const badges = computed(() => lookupBadges(ex.value.sources))
watch(
  [answerEl, markdown],
  ([el]) => {
    stopObserving?.()
    stopObserving = null
    if (el && markdown.value) {
      stopObserving = observeAnswer(el, () => ({ lookups: badges.value, uzLatin: uzLatin.value }))
    }
  },
  { flush: 'post' },
)
onBeforeUnmount(() => stopObserving?.())

/** Matndagi chip / havola. Hodisa ildizda capture bosqichida ushlanadi - MarkdownMessage
 *  o'z tinglovchisiga (hujjat ko'ruvchisi) yetib bormaydi. */
function citeOf(chip: HTMLElement): string | null {
  return chip.dataset.marker || chip.textContent?.trim() || null
}
function onAnswerClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  const chip = target?.closest<HTMLElement>('.vmd-cite')
  if (chip) {
    e.preventDefault()
    e.stopPropagation()
    emit('cite', citeOf(chip))
    return
  }
  const link = target?.closest<HTMLAnchorElement>('a[href]')
  if (link) {
    e.preventDefault()
    e.stopPropagation()
    const href = link.href
    if (/^https?:\/\//i.test(href)) openLink(href)
  }
}
function onAnswerKey(e: KeyboardEvent) {
  if (e.key !== 'Enter' && e.key !== ' ') return
  const chip = (e.target as HTMLElement | null)?.closest<HTMLElement>('.vmd-cite')
  if (!chip) return
  e.preventDefault()
  e.stopPropagation()
  emit('cite', citeOf(chip))
}

// Savol va javob - alohida: menyu qaysi biri bosilganini biladi (nusxa aynan o'shani oladi).
function pressFor(part: 'question' | 'answer') {
  return longPress((el) => {
    haptic.impact('medium')
    emit('menu', part, el)
  })
}
const pressQuestion = pressFor('question')
const pressAnswer = pressFor('answer')
</script>

<template>
  <article class="ex">
    <div v-if="ex.question" class="ex__q">
      <p class="ex__bubble" v-bind="pressQuestion">{{ ex.question }}</p>
    </div>

    <div class="ex__a">
      <div v-if="pending" class="ex__thinking">
        <span class="ex__spark" aria-hidden="true"><BrandSpark :size="14" /></span>
        <ThinkingLoader :status="ex.stage ?? undefined" />
      </div>

      <div v-else-if="ex.error" class="ex__error" role="alert">
        <span class="ex__error-icon" aria-hidden="true">
          <KeyRound v-if="needsLogin" :size="18" :stroke-width="2" />
          <CircleAlert v-else :size="18" :stroke-width="2" />
        </span>
        <p class="ex__error-text">{{ fix(ex.error) }}</p>
        <button v-if="needsLogin" type="button" class="ex__retry ex__retry--primary" @click="emit('reconnect')">
          {{ t('tg.chat.reconnect') }}
        </button>
        <button v-else type="button" class="ex__retry" @click="emit('retry')">
          <RotateCw :size="16" :stroke-width="2" aria-hidden="true" />
          {{ t('retry') }}
        </button>
      </div>

      <div v-else-if="ex.cancelled && !ex.response" class="ex__note">
        <span>{{ t('generationStopped') }}</span>
        <button v-if="ex.question" type="button" class="ex__retry ex__retry--ghost" @click="emit('retry')">
          <RotateCw :size="16" :stroke-width="2" aria-hidden="true" />
          {{ t('retry') }}
        </button>
      </div>

      <template v-else-if="ex.response">
        <div
          v-if="answer"
          ref="answerEl"
          class="tg-answer"
          v-bind="pressAnswer"
          @click.capture="onAnswerClick"
          @keydown.capture="onAnswerKey"
        >
          <component :is="markdown" v-if="markdown" :source="shown" :sources="ex.sources" :streaming="streaming" />
          <div v-else class="tg-plain">{{ plain }}</div>
        </div>
        <p v-if="ex.stopped" class="ex__caption">{{ t('chat.stopped') }}</p>
        <p v-if="ex.warning" class="ex__warn">
          <TriangleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
          <span>{{ fix(ex.warning) }}</span>
        </p>
        <ArtifactCard v-if="ex.artifact" :artifact="ex.artifact" />
        <ProposalCard v-if="ex.proposal" :key="ex.proposal.token" :proposal="ex.proposal" />
        <div v-if="finished" class="ex__after" :class="{ 'is-landed': landed }">
          <SourcesRow v-if="items.length" :items="items" @open="emit('cite', $event)" />
          <ActionRow
            v-if="answer"
            :id="ex.id"
            :answer="answer"
            :turn-id="ex.turnId"
            :pro="ex.pro"
            :at="ex.answeredAt"
            :reported="reported"
            @report="emit('report')"
          />
        </div>
      </template>
    </div>
  </article>
</template>

<style scoped>
.ex {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.ex__q {
  display: flex;
  justify-content: flex-end;
  padding-left: 12%;
}
.ex__bubble {
  max-width: 100%;
  padding: 10px 14px;
  border-radius: 20px 20px 6px 20px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  animation: ex-pop var(--dur-3) var(--ease-sheet) backwards;
  transition:
    transform 330ms var(--ease-out),
    background-color 330ms var(--ease-out);
}
@keyframes ex-pop {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
/* Ushlab turilganda (longPress.ts): 450 ms da to'liq bo'ladigan siqilish. */
.ex__bubble.is-pressing {
  transform: scale(0.985);
  background: var(--fill-hover);
}
.tg-answer {
  border-radius: 12px;
  transition:
    transform 330ms var(--ease-out),
    background-color 330ms var(--ease-out),
    box-shadow 330ms var(--ease-out);
}
/* Fon matn qutisidan 8px tashqariga (box-shadow) - joylashuv siljimaydi. */
.tg-answer.is-pressing {
  transform: scale(0.985);
  background: var(--fill);
  box-shadow: 0 0 0 8px var(--fill);
}

.ex__a {
  min-width: 0;
}
.ex__thinking {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-height: var(--lh-body-lg);
}
.ex__spark {
  display: grid;
  place-items: center;
  color: var(--brand);
  /* Aylanish emas - tinch "nafas": to'rt uchli yulduz aylanganda "✕" bo'lib ko'rinadi. */
  animation: ex-breathe 1.6s ease-in-out infinite;
}
@keyframes ex-breathe {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.45;
    transform: scale(0.8);
  }
}

.ex__error {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--s-2);
  padding: var(--s-3);
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--bg-subtle);
}
.ex__error-icon {
  display: grid;
  place-items: center;
  margin-top: 3px;
  color: var(--crit-text);
}
.ex__error-text {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  color: var(--text);
  overflow-wrap: anywhere;
}
.ex__retry {
  grid-column: 2;
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  min-height: var(--tap);
  padding: 0 var(--s-4);
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 600;
  transition: transform var(--dur-1) var(--ease-out);
}
.ex__retry:active {
  transform: scale(0.96);
}
.ex__retry--primary {
  border-color: transparent;
  padding: 0 var(--s-5);
  background: var(--ink);
  color: var(--on-ink);
}
.ex__retry--ghost {
  border-color: transparent;
  background: var(--fill);
}
.ex__note {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}
.ex__caption {
  margin-top: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.ex__warn {
  display: flex;
  gap: var(--s-2);
  margin-top: var(--s-3);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.ex__warn svg {
  flex-shrink: 0;
  margin-top: 2px;
}

/* "Javob tayyor": manbalar va amallar 4px pastdan, 180 ms. */
.ex__after.is-landed {
  animation: ex-land var(--dur-2) var(--ease-out) backwards;
}
@keyframes ex-land {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
}

/* Kech yuklanadigan markdown kelguncha - xuddi o'sha shriftda oddiy matn. */
.tg-answer :deep(.tg-plain) {
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body-lg);
  white-space: pre-wrap;
  overflow-wrap: break-word;
}

/* Sensorli ekranda uzoq bosish - bizning menyu; tizimning matn tanlash lupasi emas.
   Qismini belgilash kerak bo'lsa - menyudagi "Matnni belgilash" (SelectTextSheet). */
@media (pointer: coarse) {
  .ex__bubble,
  .tg-answer {
    -webkit-user-select: none;
    user-select: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ex__bubble,
  .ex__spark,
  .ex__after.is-landed {
    animation: none;
  }
}
</style>
