<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CSSProperties } from 'vue'
import type { Phase } from '../types'
import { AttachIcon, ConversationIcon, MicIcon, SendIcon, StopIcon } from '../icons'
import BottomCurrent from './BottomCurrent.vue'
import ComposerMenu from './ComposerMenu.vue'
import { usePro } from '../composables/usePro'

// Grow the textarea up to ~7 lines, then scroll internally.
const MAX_HEIGHT = 168

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
const value = ref('')
const focused = ref(false)
const hovering = ref(false)
const convHover = ref(false)
const taRef = ref<HTMLTextAreaElement | null>(null)
// "+" menyusi (rasm, ulanishlar). Tugma dockning ichida, menyu esa tashqarida
// (qarang ComposerMenu) - shuning uchun tugmaga ref kerak: menyu uni "o'zimniki"
// deb biladi va unga bosilganda yopilmaydi.
const menuOpen = ref(false)
const plusRef = ref<HTMLButtonElement | null>(null)
const plusHover = ref(false)

const hasText = computed(() => value.value.trim().length > 0)
const busy = computed(() => props.phase !== 'idle')
const active = computed(() => focused.value || hasText.value)

// Auto-resize to fit content (reset to one line when cleared after send).
// flush:'post' so the textarea's scrollHeight is measured after the new value
// has rendered.
function resize() {
  const ta = taRef.value
  if (!ta) return
  ta.style.height = 'auto'
  ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`
}
onMounted(resize)
watch(value, resize, { flush: 'post' })

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

// "Pro" kaliti. Holat modul darajasida (`usePro`): javob kelganda
// byudjetni `ChatView` yangilaydi, bu yerda faqat ko'rsatiladi.
const { enabled: proOn, remaining: proLeft, exhausted: proSpent, loadFailed: proUnknown } = usePro()

function togglePro() {
  if (proSpent.value) return
  proOn.value = !proOn.value
}

const roundButton: CSSProperties = {
  width: '34px',
  height: '34px',
  border: 'none',
  background: 'transparent',
  borderRadius: '50%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
  color: 'var(--icon-muted)',
}
const disabledRoundButton: CSSProperties = { ...roundButton, cursor: 'not-allowed' }

// "+" jonli: menyuni ochadi. Ochiq yoki sichqoncha ustida bo'lsa fon chiqadi,
// tugma menyuga tegishli ekani ko'rinsin.
const attachButtonStyle = computed<CSSProperties>(() => {
  const lit = menuOpen.value || plusHover.value
  return {
    ...roundButton,
    position: 'relative',
    cursor: 'pointer',
    background: lit ? 'var(--surface-hover)' : 'transparent',
    color: lit ? 'var(--text)' : 'var(--icon-muted)',
    transition: 'background 0.15s, color 0.15s',
  }
})

// A filled square-ish button, not another outlined circle: the three buttons to
// its left are all single actions on the current message, this one switches the
// whole interaction to voice. Solid fill is what separates the two groups, so
// the label is no longer needed to carry that difference.
const conversationBtnStyle = computed<CSSProperties>(() => ({
  display: 'grid',
  placeItems: 'center',
  width: '38px',
  height: '38px',
  border: 'none',
  borderRadius: '12px',
  cursor: 'pointer',
  flexShrink: 0,
  background: convHover.value ? 'var(--voice)' : 'var(--voice-soft)',
  color: convHover.value ? '#FFFFFF' : 'var(--voice)',
  transition: 'background 0.22s, color 0.22s, transform 0.1s',
  transform: convHover.value ? 'scale(1.05)' : 'none',
}))

const textareaStyle: CSSProperties = {
  flex: 1,
  border: 'none',
  outline: 'none',
  resize: 'none',
  fontFamily: 'Figtree, sans-serif',
  fontSize: '15.5px',
  lineHeight: 1.45,
  color: 'var(--text)',
  background: 'transparent',
  minWidth: 0,
  padding: '7px 0',
  margin: 0,
  maxHeight: `${MAX_HEIGHT}px`,
  overflowY: 'auto',
  display: 'block',
  boxSizing: 'border-box',
}

const dockStyle = computed<CSSProperties>(() => ({
  position: 'relative',
  width: '100%',
  borderRadius: '26px',
  background: 'var(--glass-bg)',
  // No solid border line at all — the gradient light ring (.dock::before) is the
  // only edge. The glow strengthens when active (focused / typing).
  border: 'none',
  display: 'flex',
  alignItems: 'flex-end',
  gap: '8px',
  padding: '7px 10px 7px 14px',
  pointerEvents: 'auto',
  boxSizing: 'border-box',
  transition: 'box-shadow 0.5s ease, background 0.3s',
  // No border line — a ~5px accent glow that fades solid -> transparent, only
  // when active (focused / typing), keeping the accent reserved for focus.
  boxShadow: active.value
    ? '0 0 5px var(--accent), 0 0 10px rgba(232, 51, 26, 0.3), var(--glass-shadow)'
    : 'var(--glass-shadow)',
}))

// While busy the same slot becomes a Stop button: gray at rest, red on hover — the
// destructive "stop" reveals its intent on hover instead of always shouting red.
const sendBtnStyle = computed<CSSProperties>(() => {
  let background: string
  let color: string
  if (busy.value) {
    background = hovering.value ? 'var(--accent)' : 'color-mix(in srgb, var(--surface-hover) 82%, var(--ink))'
    color = hovering.value ? 'var(--accent-contrast)' : 'var(--text-secondary)'
  } else if (hasText.value) {
    background = 'var(--accent)'
    color = 'var(--accent-contrast)'
  } else {
    background = 'var(--surface-hover)'
    color = 'var(--icon-muted)'
  }
  return {
    width: '38px',
    height: '38px',
    border: 'none',
    borderRadius: '50%',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    background,
    color,
    transition: 'background 0.25s, color 0.25s, transform 0.1s',
  }
})
</script>

<template>
  <div
    :style="{
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '0 24px 22px',
      background: 'linear-gradient(to top, var(--bg) 58%, transparent)',
      pointerEvents: 'none',
    }"
  >
    <!-- O'ram: menyu dockning tashqarisida, lekin unga nisbatan joylashadi -
         dock `.glass` (contain: paint) bo'lgani uchun ichida kesilib qolardi. -->
    <div :style="{ position: 'relative', width: '100%', maxWidth: '740px', pointerEvents: 'auto' }">
    <ComposerMenu v-if="menuOpen" :anchor="plusRef" @close="menuOpen = false" />
    <div class="glass" :style="dockStyle">
      <!-- A light wanders randomly along the bottom edge while answering. -->
      <BottomCurrent v-if="busy" />

      <!-- Plus with a small brand spark, à la Gemini. Ochiq holatda 45° buriladi:
           × - ya'ni "yopish". -->
      <button
        ref="plusRef"
        type="button"
        :title="t('attach')"
        :aria-label="t('attach')"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        :style="attachButtonStyle"
        @click="menuOpen = !menuOpen"
        @mouseenter="plusHover = true"
        @mouseleave="plusHover = false"
      >
        <span
          :style="{
            display: 'inline-flex',
            transform: menuOpen ? 'rotate(45deg)' : 'none',
            transition: 'transform 0.2s',
          }"
        >
          <AttachIcon />
        </span>
        <span
          :style="{
            position: 'absolute',
            top: '5px',
            right: '5px',
            fontSize: '7px',
            lineHeight: 1,
            color: 'var(--accent)',
          }"
          >✦</span
        >
      </button>
      <textarea
        ref="taRef"
        v-model="value"
        :rows="1"
        :placeholder="t('askPlaceholder')"
        :style="textareaStyle"
        @keydown="onKeyDown"
        @focus="focused = true"
        @blur="focused = false"
      />
      <!-- "Pro": SHU xabar uchun. Byudjet tugagan bo'lsa bosilmaydi -
           yoqiq kalit bilan yuborilgan savol baribir standart rejimda
           javob olardi va odam "pro so'radim" deb o'ylab qolardi. -->
      <button
        class="pro-toggle"
        type="button"
        role="switch"
        :aria-checked="proOn"
        :aria-label="t('proLabel')"
        :title="proSpent ? t('proExhausted') : t('proHint')"
        :class="{ 'is-on': proOn }"
        :disabled="proSpent"
        @click="togglePro"
      >
        <span>{{ t('proLabel') }}</span>
        <span v-if="!proUnknown && proLeft !== null" class="pro-toggle__left">{{ proLeft }}</span>
      </button>
      <button :title="t('comingSoon')" aria-disabled="true" :style="disabledRoundButton">
        <MicIcon />
      </button>
      <button
        class="send-btn"
        :title="busy ? t('stop') : t('send')"
        :aria-label="busy ? t('stopAria') : t('send')"
        :style="sendBtnStyle"
        @click="onPrimaryClick"
        @mouseenter="hovering = true"
        @mouseleave="hovering = false"
      >
        <StopIcon v-if="busy" :size="24" />
        <SendIcon v-else stroke="currentColor" />
      </button>
      <button
        class="conv-btn"
        :title="t('voiceTitle')"
        :aria-label="t('voiceTitle')"
        :style="conversationBtnStyle"
        @click="emit('conversation')"
        @mouseenter="convHover = true"
        @mouseleave="convHover = false"
      >
        <ConversationIcon :size="18" />
      </button>
    </div>
    </div>
    <div :style="{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '12px' }">{{ t('disclaimer') }}</div>
  </div>
</template>

<style scoped>
/* "Pro" kaliti - matn bilan, ikonkasiz: u REJIM, amal emas, va yoniq
   holati bir qarashda ko'rinishi kerak. */
.pro-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border-hover);
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-family: 'Figtree', sans-serif;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.pro-toggle:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text);
}
.pro-toggle.is-on {
  background: var(--ink);
  border-color: transparent;
  color: var(--ink-contrast);
}
.pro-toggle:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.pro-toggle__left {
  font-variant-numeric: tabular-nums;
  opacity: 0.75;
}
/* Eng tor telefonda qoldiq raqami joy yeydi - kalitning o'zi qoladi. */
@media (max-width: 380px) {
  .pro-toggle__left {
    display: none;
  }
}
</style>
