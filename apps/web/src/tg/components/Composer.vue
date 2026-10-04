<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUp, Mic, Sparkles, Square } from 'lucide-vue-next'
import { localizeApiError } from '../../api/errors'
import { ApiError } from '../../api/http'
import DictationBar from '../../components/chat/DictationBar.vue'
import { useDictation } from '../../composables/useDictation'
import type { DictationOutcome, DictationStartFailure } from '../../composables/useDictation'
import { usePro } from '../../composables/usePro'
import { toast } from '../../ui/useToast'
import { enterSends, haptic, isTelegram } from '../telegram'

/**
 * Kompozer - ekranning pastida, xavfsiz zona ustida, klaviaturaga "minib" chiqadi
 * (ramka balandligi layout.ts da). Telegram'ning o'z yozish qatori kabi: maydon va
 * o'ngda BITTA katta dumaloq tugma (48px) holatga qarab almashadi:
 *
 *   bo'sh      -> mikrofon (ovoz bilan yozish, jonli to'lqin)
 *   matn bor   -> yuborish
 *   javob ketyapti -> to'xtatish
 *
 * Bitta tugma - bitta nishon: bosh barmoq doim bir joyga boradi. Matn bor paytda ham
 * ovoz bilan davom ettirish uchun maydon ichida kichik mikrofon qoladi.
 *
 * Matn 16px (iOS kattalashtirmaydi), 1-5 qator o'sadi; qator balandligi `1.5` (em) -
 * tizimda katta shrift yoqilganda ham glif qatorga sig'adi. Enter: telefonda - yangi
 * qator (adashib bosilgan Enter yarim savolni jo'natmasin), Telegram Desktop'da -
 * yuborish (Shift+Enter - yangi qator). Yuborish/to'xtatish tugmasi fokusni olmaydi
 * (pointerdown.prevent) - klaviatura yopilmaydi, keyingi savolni darhol yozish mumkin.
 *
 * "Pro" - faqat dvigatel ruxsat bersa (`/pro/quota` -> available): maydonning ICHIDA,
 * chapda 32px dumaloq kalit (alohida qator emas - klaviatura ochiq paytda har piksel
 * kerak). Qoldiq faqat 3 va undan kam bo'lganda burchakdagi belgi bilan; to'liq son
 * har doim `aria-label` da.
 */
const props = defineProps<{
  busy: boolean
  send: (text: string) => boolean
}>()
const emit = defineEmits<{ stop: []; dictating: [on: boolean]; focus: [] }>()
const { t, locale } = useI18n({ useScope: 'global' })

const value = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)
const hasText = computed(() => value.value.trim().length > 0)

const MAX_ROWS = 5

function resize() {
  const ta = taRef.value
  if (!ta) return
  const cs = getComputedStyle(ta)
  // `line-height: 1.5` - brauzer ba'zan sonni qaytaradi, ba'zan px: ikkalasi ham.
  const raw = parseFloat(cs.lineHeight)
  const line = cs.lineHeight.endsWith('px') ? raw : (raw || 1.5) * parseFloat(cs.fontSize)
  const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)
  const max = line * MAX_ROWS + pad
  ta.style.height = 'auto'
  ta.style.height = `${Math.min(ta.scrollHeight, max)}px`
  ta.style.overflowY = ta.scrollHeight > max + 1 ? 'auto' : 'hidden'
}
onMounted(resize)
watch(value, resize, { flush: 'post' })

function trySend() {
  if (!hasText.value) return
  if (props.send(value.value)) {
    haptic.impact('light')
    value.value = ''
  }
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.isComposing || !enterSends || e.shiftKey) return
  e.preventDefault()
  trySend()
}

// --- "Pro" --------------------------------------------------------------------
const { enabled: proOn, available: proAvailable, remaining: proLeft, exhausted: proSpent } = usePro()
const proActive = computed(() => proOn.value && !proSpent.value)
/** Burchakdagi son - faqat oz qolganda (ogohlantirish); ko'p bo'lsa shovqin. */
const proBadge = computed(() => (proLeft.value !== null && proLeft.value <= 3 ? Math.max(0, proLeft.value) : null))
const proLabel = computed(() => `${t('pro.toggle')}${proLeft.value !== null ? ' · ' + t('pro.left', { n: proLeft.value }) : ''}`)
function togglePro() {
  if (proSpent.value) {
    toast.show({ message: t('pro.exhausted'), id: 'pro' })
    return
  }
  haptic.select()
  proOn.value = !proOn.value
}

// --- Ovoz bilan yozish ---------------------------------------------------------
const dictation = useDictation({ language: () => String(locale.value), onOutcome })
const dictState = dictation.state
const dictating = computed(() => dictState.value !== 'idle')
watch(dictating, (on) => emit('dictating', on), { flush: 'sync' })

async function startDictation() {
  if (props.busy || dictating.value) return
  haptic.impact('light')
  const failure = await dictation.start()
  if (failure) {
    haptic.notify('error')
    toast.error(startFailureText(failure), { id: 'dictation', duration: 8000 })
  }
}

function finishDictation() {
  dictation.finish()
}

function startFailureText(failure: DictationStartFailure): string {
  switch (failure) {
    case 'insecure':
      return `${t('voiceNeedsHttps')} ${t('voiceNeedsHttpsHow')}`
    case 'policy':
      return `${t('voiceBlockedPolicy')} ${t('voiceBlockedPolicyHow')}`
    // Telegram ichida "manzil satridagi qulf" yo'q - ruxsat telefon sozlamalarida.
    case 'denied':
      return isTelegram ? t('tg.mic.denied') : `${t('voiceDenied')} ${t('voiceDeniedHow')}`
    case 'noDevice':
      return t('voiceNoMic')
    default:
      return t('voiceError')
  }
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const status = err.status ?? (err.body ? undefined : Number(/\((\d{3})\)$/.exec(err.message)?.[1]))
    switch (status) {
      case 503:
        return t('voiceBusy')
      case 504:
        return t('voiceTooLong')
      case 413:
        return t('voiceTooLarge')
      case 415:
        return t('voiceFormat')
    }
  }
  return localizeApiError(err, t)
}

/** Aytilgan matn qoralamaga QO'SHILADI - yozilgan gapni ovoz bilan davom ettirish mumkin. */
function insert(text: string) {
  const draft = value.value
  if (!draft.trim()) value.value = text
  else value.value = /\s$/.test(draft) ? `${draft}${text}` : `${draft} ${text}`
}

const announcement = ref('')
function announce(text: string) {
  announcement.value = ''
  void nextTick(() => (announcement.value = text))
}

function onOutcome(outcome: DictationOutcome) {
  switch (outcome.kind) {
    case 'text':
      insert(outcome.text)
      haptic.notify('success')
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
      haptic.notify('error')
      toast.error(errorText(outcome.error), { id: 'dictation' })
      break
  }
}

// Kartaning bo'sh joyiga bosilsa ham kursor matnga tushsin.
function onCardPointerDown(e: PointerEvent) {
  if (dictating.value) return
  const target = e.target as Element | null
  if (!target || target === taRef.value || target.closest('button, a, [role="button"]')) return
  e.preventDefault()
  taRef.value?.focus()
}

type Primary = 'stop' | 'send' | 'mic'
const primary = computed<Primary>(() => (props.busy ? 'stop' : hasText.value ? 'send' : 'mic'))
const primaryLabel = computed(() =>
  primary.value === 'stop' ? t('stopAria') : primary.value === 'send' ? t('send') : t('composer.dictate.start'),
)

function onPrimary() {
  if (primary.value === 'stop') {
    haptic.impact('light')
    emit('stop')
  } else if (primary.value === 'send') trySend()
  else void startDictation()
}

/** Yuborish/to'xtatish matn maydonidan fokusni olmasin: klaviatura ochiq qolsin
 *  (Telegram'ning o'zidagi kabi). Mikrofon esa olsin - u klaviaturani yopadi. */
function keepFocus(e: PointerEvent) {
  if (primary.value !== 'mic' && document.activeElement === taRef.value) e.preventDefault()
}

/** Tashqaridan (taklif kartasidan keyin) - matn maydoniga. */
defineExpose({
  focus: () => taRef.value?.focus({ preventScroll: true }),
  setText: (text: string) => (value.value = text),
})
</script>

<template>
  <div class="composer">
    <div class="composer__row">
      <div
        class="composer__field"
        :class="{ 'is-dictating': dictating, 'has-pro': proAvailable && !dictating, 'is-pro': proActive && proAvailable }"
        @pointerdown="onCardPointerDown"
      >
        <DictationBar
          v-if="dictating"
          class="composer__dict"
          :state="dictState as 'starting' | 'recording' | 'transcribing'"
          :elapsed="dictation.elapsed.value"
          :levels="dictation.levels"
          @cancel="dictation.cancel"
          @done="finishDictation"
        />
        <template v-else>
          <Transition name="pro-in">
            <button
              v-if="proAvailable"
              type="button"
              class="pro"
              :class="{ 'is-on': proActive, 'is-spent': proSpent }"
              :aria-pressed="proActive ? 'true' : 'false'"
              :aria-label="proLabel"
              @click="togglePro"
            >
              <Sparkles :size="16" :stroke-width="2" aria-hidden="true" />
              <span v-if="proBadge !== null" class="pro__badge" aria-hidden="true">{{ proBadge }}</span>
            </button>
          </Transition>
          <textarea
            ref="taRef"
            v-model="value"
            class="composer__input"
            rows="1"
            :placeholder="t('composer.placeholder')"
            :aria-label="t('composer.message')"
            :enterkeyhint="enterSends ? 'send' : 'enter'"
            autocomplete="off"
            autocapitalize="sentences"
            @keydown="onKeyDown"
            @focus="emit('focus')"
          />
          <button
            v-if="hasText && !busy"
            type="button"
            class="composer__mic"
            :aria-label="t('composer.dictate.start')"
            @click="startDictation"
          >
            <Mic :size="20" :stroke-width="1.75" aria-hidden="true" />
          </button>
        </template>
      </div>

      <button
        v-if="!dictating"
        type="button"
        class="composer__primary"
        :class="`is-${primary}`"
        :aria-label="primaryLabel"
        @pointerdown="keepFocus"
        @click="onPrimary"
      >
        <Transition name="swap" mode="out-in">
          <Square v-if="primary === 'stop'" key="stop" :size="16" :stroke-width="2.5" fill="currentColor" aria-hidden="true" />
          <ArrowUp v-else-if="primary === 'send'" key="send" :size="22" :stroke-width="2.25" aria-hidden="true" />
          <Mic v-else key="mic" :size="22" :stroke-width="1.75" aria-hidden="true" />
        </Transition>
      </button>
    </div>
    <span class="sr-only" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
}

.composer__row {
  display: flex;
  align-items: flex-end;
  gap: var(--s-2);
}
.composer__field {
  /* `em` - kiritish matnining o'lchami: katta shriftda maydon ham o'sadi. */
  font-size: max(16px, 1rem);
  display: flex;
  flex: 1;
  align-items: flex-end;
  min-width: 0;
  min-height: max(48px, calc(1.5em + 24px));
  padding: 0 4px 0 var(--s-4);
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--surface);
  box-shadow: var(--e1);
  cursor: text;
  transition:
    border-color var(--dur-2) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out);
}
.composer__field.has-pro {
  padding-left: 7px;
}
.composer__field:focus-within {
  border-color: var(--line-strong);
  box-shadow: var(--e2);
}
/* Pro yoqiq - maydon chegarasi brend rangiga moyil: keyingi savol "Pro" bilan ketishi
   ko'rinib turadi. */
.composer__field.is-pro {
  border-color: color-mix(in srgb, var(--brand) 45%, var(--line));
}
.composer__field.is-dictating {
  align-items: center;
  padding: 0 4px;
  cursor: default;
}
.composer__input {
  flex: 1;
  min-width: 0;
  min-height: calc(1.5em + 22px);
  margin: 0;
  padding: 11px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 16px;
  line-height: 1.5;
  resize: none;
  outline: none;
  overflow-y: hidden;
  overscroll-behavior: contain;
}
.has-pro .composer__input {
  padding-left: var(--s-2);
}
.composer__input::placeholder {
  color: var(--text-3);
}
.composer__mic {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--tap);
  height: var(--tap);
  margin-bottom: max(1px, calc((1.5em + 22px - 44px) / 2));
  border-radius: var(--r-full);
  color: var(--text-3);
}
.composer__mic:active {
  background: var(--fill);
}

/* Pro kaliti: 32px doira maydon ichida (bosish maydoni ::after bilan 44px). Maydon
   pastki chetiga tekislangan - ko'p qatorli matnda ham yuborish tugmasi bilan bir
   chiziqda. */
.pro {
  position: relative;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  margin-bottom: calc((1.5em + 22px - 32px) / 2);
  border-radius: var(--r-full);
  color: var(--brand);
  transition:
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.pro::after {
  content: '';
  position: absolute;
  inset: -6px;
  border-radius: var(--r-full);
}
.pro:active {
  transform: scale(0.9);
}
.pro.is-on {
  background: var(--ink);
  color: var(--on-ink);
}
.pro.is-spent {
  color: var(--text-4);
}
.pro__badge {
  position: absolute;
  /* Belgi burchakdan tashqariroq - uchqun ustini yopmasin. */
  top: -6px;
  right: -9px;
  display: grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border: 1.5px solid var(--surface);
  border-radius: 8px;
  background: var(--brand);
  color: #fff;
  font-size: 10px;
  line-height: 1;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  box-sizing: content-box;
}
.pro.is-spent .pro__badge {
  background: var(--text-4);
}
.pro-in-enter-active,
.pro-in-leave-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.pro-in-enter-from,
.pro-in-leave-to {
  opacity: 0;
  transform: scale(0.6);
}

/* DictationBar'ning tugmalari (32px) telefonda kichik - 44px nishon. */
.composer__dict {
  min-height: 46px;
}
.composer__dict :deep(.v-icon-btn) {
  --ib-size: 44px;
  border-radius: var(--r-full);
}
.composer__dict :deep(.dict__wave) {
  height: 28px;
}

.composer__primary {
  /* `em` maydon bilan bir xil bo'lsin - katta shriftda ham bir qatorda markazda. */
  font-size: max(16px, 1rem);
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  margin-bottom: max(0px, calc((1.5em + 24px - 48px) / 2));
  border-radius: var(--r-full);
  background: var(--ink);
  color: var(--on-ink);
  box-shadow: var(--e2);
  transition:
    transform var(--dur-1) var(--ease-out),
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out);
}
.composer__primary:active {
  transform: scale(0.9);
}
.composer__primary.is-mic {
  background: var(--fill);
  color: var(--text);
  box-shadow: none;
}
.swap-enter-active,
.swap-leave-active {
  transition:
    opacity var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.swap-enter-from {
  opacity: 0;
  transform: scale(0.6) rotate(-45deg);
}
.swap-leave-to {
  opacity: 0;
  transform: scale(0.6);
}
</style>
