<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CSSProperties } from 'vue'
import type { Phase } from '../types'
import { AttachIcon, ConversationIcon, MicIcon, SendIcon, StopIcon } from '../icons'
import BottomCurrent from './BottomCurrent.vue'

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

const disabledRoundButton: CSSProperties = {
  width: '34px',
  height: '34px',
  border: 'none',
  background: 'transparent',
  borderRadius: '50%',
  cursor: 'not-allowed',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
  color: 'var(--icon-muted)',
}
const attachButtonStyle: CSSProperties = { ...disabledRoundButton, position: 'relative' }

// A pill, not another round icon: this one opens a whole mode, and the three
// circular buttons to its left are all single actions. The label carries that
// difference; it collapses to the icon alone when the dock gets narrow.
const conversationBtnStyle = computed<CSSProperties>(() => ({
  display: 'flex',
  alignItems: 'center',
  gap: '6px',
  height: '38px',
  padding: '0 14px',
  border: 'none',
  borderRadius: '19px',
  cursor: 'pointer',
  flexShrink: 0,
  whiteSpace: 'nowrap',
  fontFamily: 'Figtree, sans-serif',
  fontSize: '13.5px',
  fontWeight: 500,
  background: convHover.value ? 'var(--accent)' : 'var(--surface-hover)',
  color: convHover.value ? 'var(--accent-contrast)' : 'var(--text-muted)',
  transition: 'background 0.25s, color 0.25s',
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
  maxWidth: '740px',
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
    <div class="glass" :style="dockStyle">
      <!-- A light wanders randomly along the bottom edge while answering. -->
      <BottomCurrent v-if="busy" />

      <!-- Plus with a small brand spark, à la Gemini -->
      <button :title="t('comingSoon')" aria-disabled="true" :style="attachButtonStyle">
        <AttachIcon />
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
        <ConversationIcon :size="16" />
        <span class="conv-label">{{ t('conversation') }}</span>
      </button>
    </div>
    <div :style="{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '12px' }">{{ t('disclaimer') }}</div>
  </div>
</template>

<style scoped>
/* Below ~560px the dock cannot hold the label and the textarea at once; the
   icon alone still reads as "voice mode" next to the tooltip. */
@media (max-width: 560px) {
  .conv-label {
    display: none;
  }
  .conv-btn {
    padding: 0 11px !important;
  }
}
</style>
