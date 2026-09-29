<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUp, Mic, Square } from 'lucide-vue-next'
import type { Phase } from '../types'
import VIconButton from '../ui/VIconButton.vue'
import VTooltip from '../ui/VTooltip.vue'
import { useId } from '../ui/composables/useId'
import { usePro } from '../composables/usePro'
import ComposerMenu from './ComposerMenu.vue'

/**
 * Yozish maydoni (spec §4.3): suzuvchi karta - matn, ostida bitta qator boshqaruv:
 * chapda "+" (ulanishlar, fayl) va "Pro" kaliti, o'ngda mikrofon (ovozli suhbat) va
 * yuborish.
 * Javob yozilayotganda yuborish o'rnini "To'xtatish" egallaydi.
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

// Opening the voice panel is the parent's business — the dock only asks.
const emit = defineEmits<{ (e: 'conversation'): void }>()

const { t } = useI18n({ useScope: 'global' })
const inputId = useId('composer')
const value = ref('')
const taRef = ref<HTMLTextAreaElement | null>(null)

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
function onCardPointerDown(e: PointerEvent) {
  const target = e.target as Element | null
  if (!target || target === taRef.value || target.closest('button, a, [role="button"]')) return
  e.preventDefault()
  taRef.value?.focus()
}

// "Pro" kaliti - SHU xabar uchun. Holat modul darajasida (`usePro`): javob kelganda
// byudjetni ChatView yangilaydi, bu yerda faqat ko'rsatiladi. Qoldiq - tooltip'da
// (kam so'z: panelda faqat "Pro" yozuvi).
const { enabled: proOn, remaining: proLeft, exhausted: proSpent, loadFailed: proUnknown } = usePro()

const proTip = computed(() => {
  if (proSpent.value) return t('pro.exhausted')
  const hint = t('pro.hint')
  return !proUnknown.value && proLeft.value !== null ? `${hint} · ${t('pro.left', { n: proLeft.value })}` : hint
})

// Byudjet tugagan bo'lsa bosilmaydi: yoqiq kalit bilan yuborilgan savol baribir
// standart rejimda javob olardi va odam "Pro so'radim" deb o'ylab qolardi.
// `disabled` emas, `aria-disabled`: o'chiq tugma sichqoncha hodisalarini bermaydi
// va tooltip nega bosilmasligini ayta olmasdi.
function togglePro() {
  if (proSpent.value) return
  proOn.value = !proOn.value
}

// ChatView uchun: fokus yo'qolgan joydan (masalan, taklif tugmasi yo'qolganda) matnga.
defineExpose({ focus: () => taRef.value?.focus({ preventScroll: true }) })
</script>

<template>
  <div class="dock">
    <div class="dock__card" :class="{ 'is-busy': busy }" @pointerdown="onCardPointerDown">
      <label class="sr-only" :for="inputId">{{ t('composer.message') }}</label>
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
      <div class="dock__bar">
        <ComposerMenu />
        <!-- pointerdown.prevent: kalit bosilganda fokus matnda qoladi (yuborish kabi). -->
        <VTooltip :text="proTip">
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
        <VIconButton :label="t('voiceTitle')" :icon="Mic" size="sm" @click="emit('conversation')" />
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
