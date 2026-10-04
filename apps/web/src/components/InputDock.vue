<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUp, Mic, Square } from 'lucide-vue-next'
import type { Phase } from '../types'
import { ApiError } from '../api/http'
import { localizeApiError } from '../api/errors'
import VIconButton from '../ui/VIconButton.vue'
import VTooltip from '../ui/VTooltip.vue'
import { useId } from '../ui/composables/useId'
import { toast } from '../ui/useToast'
import { usePro } from '../composables/usePro'
import { useDictation } from '../composables/useDictation'
import type { DictationOutcome, DictationStartFailure } from '../composables/useDictation'
import ComposerMenu from './ComposerMenu.vue'
import DictationBar from './chat/DictationBar.vue'

/**
 * Yozish maydoni (spec §4.3): suzuvchi karta - matn, ostida bitta qator boshqaruv:
 * chapda "+" (ulanishlar, fayl) va "Pro" kaliti, o'ngda mikrofon (ovoz bilan yozish)
 * va yuborish.
 * Javob yozilayotganda yuborish o'rnini "To'xtatish" egallaydi.
 *
 * Mikrofon HECH QAYERGA OLIB BORMAYDI: u shu kartaning ichida ovozni yozib oladi
 * (jonli to'lqin bilan) va matnni maydonga qo'yadi - yuborishni odam o'zi qiladi.
 * Jonli ovozli suhbat (VoicePanel) hozircha faqat "Salom Venera" orqali ochiladi.
 *
 * Joylashuv (pastda yopishish, safe-area, salomlashuvda markaz) - ChatView'ning ishi;
 * bu komponent faqat kartani chizadi.
 */
const props = defineProps<{
  phase: Phase
  // Returns true if the send was accepted (so the dock clears its input).
  // Kept as a function prop rather than an emit because emits can't return.
  send: (text: string) => boolean
  // Abort the in-flight request. Required while `phase === 'sending'`.
  stop?: () => void
}>()

// Diktovka paytida mikrofon kompozerniki: ChatView shunga qarab "Salom Venera"
// tinglovchisini to'xtatib turadi (VoicePanel ochiqdagidek), aks holda u
// aytilgan gapni ham eshitib, serverga "uyg'otish so'zi" deb yuborardi.
const emit = defineEmits<{ (e: 'dictating', on: boolean): void }>()

const { t, locale } = useI18n({ useScope: 'global' })
const inputId = useId('composer')
const value = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)
const cardRef = ref<HTMLElement | null>(null)

// 1-8 qator o'sadi, keyin ichida aylanadi. Qator balandligi CSS dagi line-height bilan bir xil.
const LINE_HEIGHT = 24
const MAX_ROWS = 8

const hasText = computed(() => value.value.trim().length > 0)
const busy = computed(() => props.phase !== 'idle')

// Auto-resize to fit content (reset to one line when cleared after send).
// flush:'post' so the textarea's scrollHeight is measured after the new value
// has rendered.
function resize() {
  const ta = taRef.value
  if (!ta) return
  const cs = getComputedStyle(ta)
  const max = LINE_HEIGHT * MAX_ROWS + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)
  ta.style.height = 'auto'
  ta.style.height = `${Math.min(ta.scrollHeight, max)}px`
  ta.style.overflowY = ta.scrollHeight > max ? 'auto' : 'hidden'
}
onMounted(resize)
watch(value, resize, { flush: 'post' })

// Qoralama FAQAT qabul qilinganda tozalanadi: quvur band bo'lsa (send → false)
// yozilgan savol yo'qolmaydi.
function trySend() {
  if (props.send(value.value)) value.value = ''
}

function onPrimaryClick() {
  if (busy.value) props.stop?.()
  else trySend()
}

function onKeyDown(e: KeyboardEvent) {
  // Enter sends; Shift+Enter inserts a newline. Don't send mid-IME-composition.
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    trySend()
  }
}

// Kartaning bo'sh joyiga (tugmalar orasiga) bosilsa ham kursor matnga tushsin.
// Diktovka paytida maydon yashirin - u yerga fokus yuborilmaydi.
function onCardPointerDown(e: PointerEvent) {
  if (dictating.value) return
  const target = e.target as Element | null
  if (!target || target === taRef.value || target.closest('button, a, [role="button"]')) return
  e.preventDefault()
  taRef.value?.focus()
}

// "Pro" kaliti - SHU xabar uchun. Holat modul darajasida (`usePro`): javob kelganda
// byudjetni ChatView yangilaydi, bu yerda faqat ko'rsatiladi. Qoldiq - tooltip'da
// (kam so'z: panelda faqat "Pro" yozuvi).
//
// Kalit FAQAT `available` bo'lsa bor (backend: shu kanal v2 da va byudjet o'qildi).
// v1 kanalida u umuman chizilmaydi - o'chiq tugma "nega bosilmaydi?" degan savol
// tug'dirardi, javobi esa odamga kerak emas (sozlama).
const { enabled: proOn, available: proAvailable, remaining: proLeft, exhausted: proSpent } = usePro()

// Tooltip = ekran o'quvchi tavsifi (VTooltip `aria-describedby` ni o'zi ulaydi).
// Birinchi qator - xizmat jamoasi bergan izoh (`pro.hint`), ikkinchisi - holat.
const proStatus = computed(() => {
  if (proSpent.value) return t('pro.exhausted')
  return proLeft.value !== null ? t('pro.left', { n: proLeft.value }) : ''
})

// Byudjet tugagan bo'lsa bosilmaydi: yoqiq kalit bilan yuborilgan savol baribir
// standart rejimda javob olardi va odam "Pro so'radim" deb o'ylab qolardi.
// `disabled` emas, `aria-disabled`: o'chiq tugma sichqoncha hodisalarini bermaydi
// va tooltip nega bosilmasligini ayta olmasdi.
function togglePro() {
  if (proSpent.value) return
  proOn.value = !proOn.value
}

// --- Ovoz bilan yozish ---------------------------------------------------------
const dictation = useDictation({
  language: () => String(locale.value),
  onOutcome,
})
const dictState = dictation.state
const dictating = computed(() => dictState.value !== 'idle')
const barRef = ref<InstanceType<typeof DictationBar> | null>(null)

// Kartaning balandligi yozuv boshlangan paytdagidek QOTADI: qator almashganda
// karta sakrasa, suhbat ham sakraydi. `sync` - o'lchov DOM hali eski
// (maydon ko'rinib turgan) paytda olinadi; `idle` da qaytarilgan matn bilan
// bitta chizishda bo'shatiladi.
const lockedHeight = ref<number | null>(null)
watch(
  dictState,
  (now, before) => {
    if (before === 'idle' && now !== 'idle') lockedHeight.value = cardRef.value?.offsetHeight ?? null
    else if (now === 'idle') lockedHeight.value = null
  },
  { flush: 'sync' },
)
// `sync`: ota "Salom Venera" ni `useDictation` mikrofonni so'rashidan OLDIN
// to'xtatishi kerak (u bir tik kutadi).
watch(dictating, (on) => emit('dictating', on), { flush: 'sync' })

// Ekran o'quvchi uchun jim e'lonlar. Bo'shatib qayta yoziladi - bir xil gap
// ketma-ket ikki marta aytilsa ham o'qilsin.
const announcement = ref('')
function announce(text: string) {
  announcement.value = ''
  void nextTick(() => {
    announcement.value = text
  })
}

watch(
  dictState,
  (now, before) => {
    if (now === 'starting') barRef.value?.focusDone()
    else if (now === 'recording') announce(t('composer.dictate.started'))
    else if (now === 'transcribing') announce(t('composer.dictate.transcribing'))
    else if (now === 'idle' && before !== 'idle') focusEnd()
  },
  { flush: 'post' },
)

/** Fokus matn oxiriga - aytilgan gapni darhol davom ettirish yoki tuzatish mumkin. */
function focusEnd() {
  const ta = taRef.value
  if (!ta) return
  resize()
  ta.focus({ preventScroll: true })
  const end = ta.value.length
  ta.setSelectionRange(end, end)
  ta.scrollTop = ta.scrollHeight
}

async function onMicClick() {
  if (busy.value || dictating.value) return
  const failure = await dictation.start()
  if (failure) toast.error(startFailureText(failure), { id: 'dictation', duration: 8000 })
}

function startFailureText(failure: DictationStartFailure): string {
  switch (failure) {
    case 'insecure': return `${t('voiceNeedsHttps')} ${t('voiceNeedsHttpsHow')}`
    case 'policy': return `${t('voiceBlockedPolicy')} ${t('voiceBlockedPolicyHow')}`
    case 'denied': return `${t('voiceDenied')} ${t('voiceDeniedHow')}`
    case 'noDevice': return t('voiceNoMic')
    default: return t('voiceError')
  }
}

/** Proksi xatolari (nginx 413/504) xabarsiz keladi - holat bo'yicha. VoicePanel'dagi
 *  bilan bir xil; odam "Request failed (504)" ni ko'rmasin. */
function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    // nginx sahifasida JSON konvert yo'q - `status` bo'sh qoladi, holat faqat
    // `apiFetch` yozgan "Request failed (504)" matnida (authErrorKind ham shunday).
    const status = err.status ?? (err.body ? undefined : Number(/\((\d{3})\)$/.exec(err.message)?.[1]))
    switch (status) {
      case 503: return t('voiceBusy')
      case 504: return t('voiceTooLong')
      case 413: return t('voiceTooLarge')
      case 415: return t('voiceFormat')
    }
  }
  return localizeApiError(err, t)
}

/** Aytilgan matn qoralamaga QO'SHILADI (almashtirmaydi): odam yozib turgan gapni
 *  ovoz bilan davom ettirishi mumkin. Qoralama bo'shliq bilan tugasa - o'sha qoladi
 *  (masalan, yangi qatordan boshlangan bo'lsa). */
function insert(text: string) {
  const draft = value.value
  if (!draft.trim()) value.value = text
  else value.value = /\s$/.test(draft) ? `${draft}${text}` : `${draft} ${text}`
}

function onOutcome(outcome: DictationOutcome) {
  switch (outcome.kind) {
    case 'text':
      insert(outcome.text)
      announce(t('composer.dictate.inserted'))
      if (outcome.truncated) toast.show({ message: t('voiceTruncatedNote'), id: 'dictation' })
      break
    case 'empty':
      toast.show({ message: t('composer.dictate.noSpeech'), id: 'dictation' })
      break
    case 'cancelled':
      if (!outcome.silent) announce(t('composer.dictate.cancelled'))
      break
    case 'error':
      toast.error(errorText(outcome.error), { id: 'dictation' })
      break
  }
}

// ChatView uchun: fokus yo'qolgan joydan (masalan, taklif tugmasi yo'qolganda) matnga.
defineExpose({ focus: () => taRef.value?.focus({ preventScroll: true }) })
</script>

<template>
  <div class="dock">
    <div
      ref="cardRef"
      class="dock__card"
      :class="{ 'is-busy': busy, 'is-dictating': dictating }"
      :style="lockedHeight ? { height: `${lockedHeight}px` } : undefined"
      @pointerdown="onCardPointerDown"
    >
      <label class="sr-only" :for="inputId">{{ t('composer.message') }}</label>
      <!-- Yozuv paytida maydon O'CHIRILMAYDI, faqat yashiriladi (`.is-dictating`):
           qoralama, balandlik va bekor qilish tarixi saqlanadi. v-show emas - u
           `display` ni chizishdan KEYIN qo'yadi va qaytgan matn yashirin maydonda
           o'lchanib, fokus ham unga tushmay qolardi. -->
      <textarea
        :id="inputId"
        ref="taRef"
        v-model="value"
        class="dock__input"
        rows="1"
        enterkeyhint="send"
        :placeholder="t('composer.placeholder')"
        @keydown="onKeyDown"
      />
      <DictationBar
        v-if="dictState !== 'idle'"
        ref="barRef"
        :state="dictState"
        :elapsed="dictation.elapsed.value"
        :levels="dictation.levels"
        @cancel="dictation.cancel"
        @done="dictation.finish"
      />
      <div class="dock__bar">
        <ComposerMenu />
        <!-- pointerdown.prevent: kalit bosilganda fokus matnda qoladi (yuborish kabi). -->
        <VTooltip v-if="proAvailable">
          <template #content>
            <span class="dock__tip">
              <span>{{ t('pro.hint') }}</span>
              <!-- Bo'shliq: ekran o'quvchi ikki gapni qo'shib o'qimasin (flex'da ko'rinmaydi). -->
              {{ ' ' }}<span v-if="proStatus" class="dock__tip-status">{{ proStatus }}</span>
            </span>
          </template>
          <button
            type="button"
            class="dock__pro"
            role="switch"
            :class="{ 'is-on': proOn }"
            :aria-checked="proOn ? 'true' : 'false'"
            :aria-disabled="proSpent ? 'true' : undefined"
            :aria-label="t('pro.toggle')"
            @pointerdown.prevent
            @click="togglePro"
          >
            {{ t('pro.label') }}
          </button>
        </VTooltip>
        <span class="dock__spacer" />
        <!-- Javob yozilayotganda o'chiq (yuborish tugmasi o'shanda "To'xtatish"):
             aytilgan savol baribir javob tugaguncha ketmaydi. Mikrofon ishlamaydigan
             joyda (HTTP) ham KO'RINADI - bosilganda nega ishlamasligini aytadi. -->
        <VIconButton :label="t('composer.dictate.start')" :icon="Mic" size="sm" :disabled="busy" @click="onMicClick" />
        <!-- pointerdown.prevent: sichqoncha bilan bosilganda fokus matnda qoladi -
             keyingi savolni darhol yozish mumkin (telefonda klaviatura ham yopilmaydi). -->
        <VIconButton
          class="dock__send"
          variant="primary"
          size="sm"
          :label="busy ? t('stopAria') : t('send')"
          :disabled="!busy && !hasText"
          @pointerdown.prevent
          @click="onPrimaryClick"
        >
          <Square v-if="busy" :size="12" :stroke-width="0" fill="currentColor" aria-hidden="true" />
          <ArrowUp v-else :size="18" :stroke-width="2" aria-hidden="true" />
        </VIconButton>
      </div>
    </div>
    <p class="dock__note">{{ t('composer.disclaimer') }}</p>
    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>
  </div>
</template>

<style scoped>
.dock {
  width: 100%;
  max-width: var(--chat-col);
  margin: 0 auto;
}

.dock__card {
  /* Halo juda och (6%) va kengroq (4px) - chiziq emas, yumshoq "nur". Oldingi 8%/3px
     line-strong chegara bilan qo'shilib, oq fonda qalin kulrang-qora halqa bo'lib o'qilardi. */
  --dock-ring: color-mix(in srgb, var(--text) 6%, transparent);
  display: flex;
  flex-direction: column;
  padding: var(--s-3) var(--s-3) var(--s-2);
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  background: var(--surface);
  box-shadow: var(--e2);
  cursor: text;
  transition:
    border-color var(--dur-2) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out);
}
@media (hover: hover) {
  .dock__card:hover:not(:focus-within) {
    border-color: var(--line-strong);
  }
}
/* Fokus - jim: line-strong chegara + yumshoq halo + odatdagi e2 soya. Kompozer ekrandagi
   yagona katta maydon va kursor ichida miltillaydi - qayerda yozilayotgani baribir
   ko'rinadi, qora halqa ortiqcha. Klaviatura bilan kartadagi tugmalarga o'tilsa, ularning
   o'z :focus-visible halqasi (base.css) ishlaydi. */
.dock__card:focus-within {
  border-color: var(--line-strong);
  box-shadow:
    var(--e2),
    0 0 0 4px var(--dock-ring);
}
/* Ovoz yozilyapti: bitta qator kartaning o'rtasida. Yuqori/past ichki bo'shliq
   tenglashadi - balandlik qotgan (`lockedHeight`), qator esa optik markazda tursin. */
.dock__card.is-dictating {
  flex-direction: row;
  align-items: center;
  padding: var(--s-2) var(--s-3);
  cursor: default;
}
/* "+" va "Pro" ham, mikrofon va yuborish ham shu qatorda - yozuv paytida ularning
   o'rnini DictationBar'ning ✕ / ✓ tugmalari egallaydi. */
.dock__card.is-dictating > .dock__input,
.dock__card.is-dictating > .dock__bar {
  display: none;
}

.dock__input {
  display: block;
  width: 100%;
  margin: 0;
  padding: var(--s-1) var(--s-2) 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: var(--fs-body);
  line-height: 24px;
  letter-spacing: -0.006em;
  resize: none;
  overflow-y: hidden;
  outline: none;
}
/* Fokus kartaning halqasida ko'rinadi - maydonning o'z chizig'i kerak emas. */
.dock__input:focus-visible {
  outline: none;
}
.dock__input::placeholder {
  color: var(--text-4);
  opacity: 1;
}
/* iOS 16px dan kichik shriftli maydonga fokusda sahifani kattalashtiradi. */
@media (max-width: 767.98px) {
  .dock__input {
    font-size: 16px;
  }
}

.dock__bar {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  margin-top: var(--s-2);
  cursor: default;
}
.dock__spacer {
  flex: 1;
}

/* "Pro" - tabletka kalit (VChoiceChips chipi kabi): o'chiqda jim (faqat matn, hover'da
   --fill), yoqiqda siyoh fon. Balandligi "+" bilan bir xil - qator tekis turadi. */
.dock__pro {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 var(--s-3);
  border-radius: var(--r-full);
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  touch-action: manipulation;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .dock__pro:not([aria-disabled='true']):not(.is-on):hover {
    background: var(--fill);
    color: var(--text);
  }
}
.dock__pro:not([aria-disabled='true']):active {
  transform: scale(0.97);
}
.dock__pro.is-on {
  background: var(--ink);
  color: var(--on-ink);
}
@media (hover: hover) {
  .dock__pro.is-on:hover {
    background: var(--ink-hover);
  }
}
.dock__pro[aria-disabled='true'] {
  color: var(--text-4);
  cursor: not-allowed;
}
/* Tooltip ichi: izoh, ostida holat (qoldiq yoki "limit tugadi") - xira. */
.dock__tip {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dock__tip-status {
  opacity: 0.72;
}
/* Yuborish: 32px dumaloq siyoh tugma; bo'sh maydonda --fill (VIconButton primary disabled). */
.dock__send {
  border-radius: var(--r-full);
}

.dock__note {
  margin-top: var(--s-2);
  color: var(--text-4);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-align: center;
}
</style>
