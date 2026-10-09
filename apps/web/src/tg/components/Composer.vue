<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
 * (ramka balandligi layout.ts da). Claude ilovasidagi kabi BITTA karta: tepada matn
 * (butun kenglikda - chapdagi belgi matnni siqib qo'ymaydi), ostida boshqaruv qatori:
 *
 *   chapda  "Pro" (faqat dvigatel ruxsat bersa)
 *   o'ngda  mikrofon va yuborish (javob ketayotganda - to'xtatish)
 *
 * Yuborish tugmasi doim joyida: matn bo'lmasa xira (bosilmaydi), bor bo'lsa brend
 * rangida - bosh barmoq har safar bir joyga boradi. Ovoz yozilayotganda karta bitta
 * qatorga aylanadi: ✕ bekor, to'lqin, ■ to'xtatib tahrirlash, ↑ darhol yuborish.
 *
 * Matn 16px (iOS kattalashtirmaydi), qator balandligi `1.5` (em) - tizimda katta shrift
 * yoqilganda ham glif qatorga sig'adi. Karta 8 qatorgacha o'sadi, lekin ekranning ~30%
 * dan oshmaydi (klaviatura ochiq paytda suhbat ko'rinib tursin). Enter: telefonda -
 * yangi qator (adashib bosilgan Enter yarim savolni jo'natmasin), Telegram Desktop'da -
 * yuborish (Shift+Enter - yangi qator). Yuborish/to'xtatish/Pro fokusni olmaydi
 * (pointerdown.prevent) - klaviatura yopilmaydi.
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

const MAX_ROWS = 8
/** Karta ekranning shuncha qismidan oshmaydi: klaviatura ochiq paytda ham suhbat
 *  ko'rinib tursin (aytilgan uzun gap 8 qatorni bemalol to'ldiradi). */
const MAX_SHARE = 0.3

function resize() {
  const ta = taRef.value
  if (!ta) return
  const cs = getComputedStyle(ta)
  // `line-height: 1.5` - brauzer ba'zan sonni qaytaradi, ba'zan px: ikkalasi ham.
  const raw = parseFloat(cs.lineHeight)
  const line = cs.lineHeight.endsWith('px') ? raw : (raw || 1.5) * parseFloat(cs.fontSize)
  const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)
  const viewport = window.visualViewport?.height ?? window.innerHeight
  const max = Math.min(line * MAX_ROWS, Math.max(line * 3, viewport * MAX_SHARE)) + pad
  ta.style.height = 'auto'
  ta.style.height = `${Math.min(ta.scrollHeight, max)}px`
  ta.style.overflowY = ta.scrollHeight > max + 1 ? 'auto' : 'hidden'
}
onMounted(() => {
  resize()
  window.visualViewport?.addEventListener('resize', resize)
})
onBeforeUnmount(() => window.visualViewport?.removeEventListener('resize', resize))
watch(value, resize, { flush: 'post' })
// Diktovka paytida textarea O'RNIDA to'lqin turadi (v-if), ya'ni yozuv tugaganda u
// QAYTA yaratiladi - aytilgan matn bilan bir tikda. v-model qiymatni yangi elementga
// o'zining `mounted` ilgagida qo'yadi, yuqoridagi post-watcher'dan KEYIN: o'lchov bo'sh
// maydonni o'lchab, uzun gap bir qatorda yashirinib qolardi. Element almashganda
// o'lchov flush tugagunicha (qiymat joyiga tushgunicha) kechiktiriladi.
watch(taRef, (el) => {
  if (el) void nextTick(resize)
})

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
const proText = computed(() => (proBadge.value !== null ? `${t('pro.label')} · ${proBadge.value}` : t('pro.label')))
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

/** Yozuv qanday tugadi: ■ - matn maydonga, ↑ - maydonga tushib, darhol yuboriladi. */
const dictPending = ref<'done' | 'send' | null>(null)

async function startDictation() {
  if (props.busy || dictating.value) return
  dictPending.value = null
  haptic.impact('light')
  const failure = await dictation.start()
  if (failure) {
    haptic.notify('error')
    toast.error(startFailureText(failure), { id: 'dictation', duration: 8000 })
  }
}

function finishDictation(intent: 'done' | 'send') {
  if (dictState.value !== 'recording') return
  dictPending.value = intent
  haptic.impact('light')
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
    case 'busy':
      return t('voiceMicBusy')
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

/** Aytilgan matn maydondagi matnning O'RNIGA yoziladi. Odatiy holat: diktovka yomon
 *  eshitildi - odam qayta aytadi va eski noto'g'ri matn yangisi bilan almashishi kerak
 *  (qo'shilib ketsa, uni qo'lda o'chirish telefonda noqulay). Almashtirish FAQAT yangi
 *  matn kelganda: ✕ (bekor), "ovoz eshitilmadi" yoki xato bo'lsa eski matn joyida qoladi. */
function place(text: string) {
  value.value = text
}

const announcement = ref('')
function announce(text: string) {
  announcement.value = ''
  void nextTick(() => (announcement.value = text))
}

function onOutcome(outcome: DictationOutcome) {
  const intent = dictPending.value
  dictPending.value = null
  switch (outcome.kind) {
    case 'text':
      place(outcome.text)
      if (outcome.truncated) toast.show({ message: t('voiceTruncatedNote'), id: 'dictation' })
      // "Darhol yuborish": matn avval maydonga tushadi - yuborish qabul qilinmasa
      // (javob hali ketyapti) u yo'qolmaydi, odam o'zi yuboradi.
      if (intent === 'send' && !props.busy) {
        void nextTick(trySend)
        break
      }
      haptic.notify('success')
      announce(t('composer.dictate.inserted'))
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

function onPrimary() {
  if (props.busy) {
    haptic.impact('light')
    emit('stop')
  } else trySend()
}

/** Yuborish/to'xtatish/Pro matn maydonidan fokusni olmasin: klaviatura ochiq qolsin
 *  (Telegram'ning o'zidagi kabi). Mikrofon esa olsin - u klaviaturani yopadi. */
function keepFocus(e: PointerEvent) {
  if (document.activeElement === taRef.value) e.preventDefault()
}

/** Tashqaridan (taklif kartasidan keyin) - matn maydoniga. */
defineExpose({
  focus: () => taRef.value?.focus({ preventScroll: true }),
  setText: (text: string) => (value.value = text),
})
</script>

<template>
  <div class="composer">
    <div
      class="composer__card"
      :class="{ 'is-dictating': dictating, 'is-pro': proActive && proAvailable && !dictating }"
      @pointerdown="onCardPointerDown"
    >
      <DictationBar
        v-if="dictating"
        class="composer__dict"
        sendable
        :pending="dictPending"
        :state="dictState as 'starting' | 'recording' | 'transcribing'"
        :elapsed="dictation.elapsed.value"
        :levels="dictation.levels"
        @cancel="dictation.cancel"
        @done="finishDictation('done')"
        @send="finishDictation('send')"
      />
      <template v-else>
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
        <div class="composer__bar">
          <Transition name="pro-in">
            <button
              v-if="proAvailable"
              type="button"
              class="pro"
              :class="{ 'is-on': proActive, 'is-spent': proSpent }"
              :aria-pressed="proActive ? 'true' : 'false'"
              :aria-label="proLabel"
              @pointerdown="keepFocus"
              @click="togglePro"
            >
              <Sparkles :size="16" :stroke-width="2" aria-hidden="true" />
              <span class="pro__text" aria-hidden="true">{{ proText }}</span>
            </button>
          </Transition>
          <span class="composer__spacer" />
          <button
            type="button"
            class="composer__btn composer__mic"
            :aria-label="t('composer.dictate.start')"
            :disabled="busy"
            @click="startDictation"
          >
            <Mic :size="20" :stroke-width="1.75" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="composer__btn composer__send"
            :class="{ 'is-stop': busy, 'is-ready': hasText }"
            :aria-label="busy ? t('stopAria') : t('send')"
            :aria-disabled="!busy && !hasText ? 'true' : undefined"
            @pointerdown="keepFocus"
            @click="onPrimary"
          >
            <Transition name="swap" mode="out-in">
              <Square v-if="busy" key="stop" :size="13" :stroke-width="0" fill="currentColor" aria-hidden="true" />
              <ArrowUp v-else key="send" :size="20" :stroke-width="2.25" aria-hidden="true" />
            </Transition>
          </button>
        </div>
      </template>
    </div>
    <span class="sr-only" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
}

/* Karta ranglari: yorug'da - oq karta, aniq chegara va soya (fon ham oq); qorong'ida -
   fondan bir pog'ona yorug' karta, tugmalar undan ham bir pog'ona (Claude ilovasidagi
   #151515 -> #20201e -> #313131 zinasi). */
.composer__card {
  --cmp-bg: var(--surface);
  --cmp-line: var(--line-strong);
  --cmp-btn: var(--fill);
  --cmp-btn-text: var(--text-2);

  /* `em` - kiritish matnining o'lchami: katta shriftda karta ham o'sadi. */
  font-size: max(16px, 1rem);
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--cmp-line);
  border-radius: 24px;
  background: var(--cmp-bg);
  box-shadow: var(--e2);
  cursor: text;
  transition:
    border-color var(--dur-2) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out);
}
:global(:root[data-theme='dark']) .composer__card {
  --cmp-bg: var(--fill);
  --cmp-line: color-mix(in srgb, var(--text) 7%, transparent);
  --cmp-btn: color-mix(in srgb, var(--text) 9%, var(--fill));
  box-shadow: none;
}
.composer__card:focus-within {
  border-color: color-mix(in srgb, var(--text) 22%, transparent);
}
/* Pro yoqiq - chegara brend rangiga moyil: keyingi savol "Pro" bilan ketishi ko'rinadi. */
.composer__card.is-pro {
  border-color: color-mix(in srgb, var(--brand) 45%, var(--cmp-line));
}
.composer__card.is-dictating {
  flex-direction: row;
  align-items: center;
  padding: 10px 8px;
  cursor: default;
}

.composer__input {
  display: block;
  width: 100%;
  min-height: calc(1.5em + 18px);
  margin: 0;
  padding: 13px 16px 5px;
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
.composer__input::placeholder {
  color: var(--text-3);
}

.composer__bar {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  padding: 4px 8px 8px;
}
.composer__spacer {
  flex: 1;
}

/* 36px doiralar; sensorli ekranda bosish maydoni ::after bilan 44px. */
.composer__btn {
  position: relative;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--r-full);
  transition:
    transform var(--dur-1) var(--ease-out),
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    opacity var(--dur-2) var(--ease-out);
}
.composer__btn::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: var(--r-full);
}
.composer__btn:not(:disabled):not([aria-disabled='true']):active {
  transform: scale(0.9);
}
.composer__mic {
  background: var(--cmp-btn);
  color: var(--cmp-btn-text);
}
.composer__mic:disabled {
  opacity: 0.4;
}
/* Yuborish: doim joyida. Matn yo'q - xira brend (bosilmaydi), bor - to'liq brend. */
.composer__send {
  background: color-mix(in srgb, var(--brand) 38%, var(--cmp-bg));
  color: color-mix(in srgb, #fff 60%, var(--cmp-bg));
}
.composer__send.is-ready {
  background: var(--brand);
  color: #fff;
}
.composer__send[aria-disabled='true'] {
  cursor: default;
}
.composer__send.is-stop {
  background: var(--ink);
  color: var(--on-ink);
}

/* "Pro" - Claude'dagi model tanlovi o'rnida: belgi + yozuv, 36px tabletka. */
.pro {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  height: 36px;
  padding: 0 14px 0 11px;
  border: 1px solid transparent;
  border-radius: var(--r-full);
  background: var(--cmp-btn);
  color: var(--cmp-btn-text);
  font-size: 14px;
  line-height: 1;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  transition:
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.pro:active {
  transform: scale(0.95);
}
.pro.is-on {
  border-color: color-mix(in srgb, var(--brand) 40%, transparent);
  background: var(--brand-soft);
  color: var(--brand);
}
.pro.is-spent {
  color: var(--text-4);
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
  transform: scale(0.8);
}

/* Yozuv qatori: tugmalar 36px doira (bosish maydoni 44px), ✕ va ■ - karta tugmasi
   rangida, ↑ - brend. To'lqin ustidagi holat yozuvi karta rangida so'nadi. */
.composer__dict {
  min-height: 36px;
}
.composer__dict :deep(.v-icon-btn) {
  --ib-size: 36px;
  border-radius: var(--r-full);
}
.composer__dict :deep(.v-icon-btn::after) {
  inset: -4px;
}
.composer__dict :deep(.dict__cancel),
.composer__dict :deep(.dict__stop) {
  background: var(--cmp-btn);
  color: var(--text);
}
.composer__dict :deep(.dict__send) {
  background: var(--brand);
  color: #fff;
}
.composer__dict :deep(.v-icon-btn[aria-disabled='true']:not(.is-loading)) {
  opacity: 0.45;
}
.composer__dict :deep(.dict__wave) {
  height: 28px;
}
/* Matnga aylantirilayotganda soat to'xtagan - joyini holat yozuviga beradi (telefonda
   "Matnga aylantirilmoqda…" aks holda qisqarib qolardi). */
.composer__dict.is-transcribing :deep(.dict__time) {
  display: none;
}
.composer__dict :deep(.dict__status) {
  padding: 0 var(--s-2);
  background: linear-gradient(
    90deg,
    transparent,
    var(--cmp-bg) var(--s-4),
    var(--cmp-bg) calc(100% - var(--s-4)),
    transparent
  );
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
