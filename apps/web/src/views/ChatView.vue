<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { streamAsk } from '../api/chat.api'
import { localizeApiError } from '../api/errors'
import { useAuth } from '../composables/useAuth'
import { useWakeWord, WAKE_LOCALES, WAKE_STORAGE_KEY } from '../composables/useWakeWord'
import { warmGreeting } from '../api/greeting'
import type { ActorType, ChatFrame, Phase, PipelineResponse, UIExchange } from '../types'
import { applyTheme, getInitialTheme } from '../theme'
import type { Theme } from '../theme'
import AmbientBackground from '../components/AmbientBackground.vue'
import ChatSidebar from '../components/ChatSidebar.vue'
import Welcome from '../components/Welcome.vue'
import Conversation from '../components/Conversation.vue'
import InputDock from '../components/InputDock.vue'
import VoicePanel from '../components/VoicePanel.vue'
import AnswerGlow from '../components/AnswerGlow.vue'
import { MenuIcon } from '../icons'

const { t, locale } = useI18n({ useScope: 'global' })
const router = useRouter()
// Identity now comes from the authenticated session (derived from the token by
// the backend); the chat request carries only the question.
const { user, logout } = useAuth()
const exchanges = ref<UIExchange[]>([])
const phase = ref<Phase>('idle')
const theme = ref<Theme>(getInitialTheme())
const sidebarOpen = ref(false)
const voiceOpen = ref(false)

// --- "Salom Venera" ---------------------------------------------------------
// ON by default: the assistant should answer when spoken to, without anyone
// having to find a switch first. The switch stays, because the microphone
// must always have an off — but only an explicit '0' turns it off, so a fresh
// login, a new browser, or cleared storage all come up listening.
const wakeEnabled = ref(localStorage.getItem(WAKE_STORAGE_KEY) !== '0')
watch(wakeEnabled, (value) => localStorage.setItem(WAKE_STORAGE_KEY, value ? '1' : '0'))
const wakeSupported = computed(() => WAKE_LOCALES.includes(String(locale.value)))

const { active: wakeActive, distorted: wakeDistorted } = useWakeWord({
  enabled: wakeEnabled,
  locale: computed(() => String(locale.value)),
  paused: voiceOpen,
  onWake: () => { voiceOpen.value = true },
})

function toggleWake() {
  wakeEnabled.value = !wakeEnabled.value
}

function openVoice() {
  voiceOpen.value = true
}

function closeVoice() {
  voiceOpen.value = false
}
const collapsed = ref(localStorage.getItem('venera_sidebar_collapsed') === '1')
watch(collapsed, (value) => localStorage.setItem('venera_sidebar_collapsed', value ? '1' : '0'))
// User vs developer chat UI. User mode (default) hides the pipeline trace and
// shows a "Thinking" loader; developer mode shows the full Guard/Intent/
// Orchestrator/Access trace. A sidebar toggle drives it for now — later this
// will be derived from the signed-in user's email.
const devMode = ref(localStorage.getItem('venera_dev_mode') === '1')
watch(devMode, (value) => localStorage.setItem('venera_dev_mode', value ? '1' : '0'))
// Imperative, non-reactive (the React useRef equivalent) — a plain let, not a ref.
let abortController: AbortController | null = null

// One conversation, one key. The assistant keeps its memory per
// (user_id, chat_id), so follow-up questions ("va o'tgan oyda?") only work
// while this stays the same — and "New chat" MUST change it, or the previous
// conversation would bleed into the new one.
function freshChatId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
let chatId = freshChatId()

watch(theme, (value) => applyTheme(value), { immediate: true })
onBeforeUnmount(() => abortController?.abort())

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

function newChat() {
  abortController?.abort()
  abortController = null
  exchanges.value = []
  phase.value = 'idle'
  chatId = freshChatId()
}

// User-initiated cancel. Mark the in-flight exchange so PipelineResult can
// render a soft "Generation stopped" notice instead of a request-failed error.
function stop() {
  if (phase.value !== 'sending') return
  abortController?.abort()
  abortController = null
  const inflight = exchanges.value.find((e) => !e.response && !e.error && !e.cancelled)
  if (inflight) patch(inflight.id, { cancelled: true })
  phase.value = 'idle'
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

// ESC toggles the sidebar. On mobile that's the off-canvas drawer; on desktop
// it's the collapsed rail. Skip during IME composition and if a deeper handler
// (e.g. a future modal) already claimed the key.
function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.isComposing || e.defaultPrevented) return
  // The voice panel is on top, so ESC closes that first — otherwise the
  // sidebar would toggle behind an open dialog and the microphone stay live.
  if (voiceOpen.value) {
    closeVoice()
    return
  }
  if (window.matchMedia('(max-width: 768px)').matches) {
    sidebarOpen.value = !sidebarOpen.value
  } else {
    collapsed.value = !collapsed.value
  }
}
// Fetch the greeting now, while nobody is waiting: the first wake word should
// play instantly, not after a round trip.
onMounted(() => warmGreeting(String(locale.value)))
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function toggleDevMode() {
  devMode.value = !devMode.value
}

async function onLogout() {
  abortController?.abort()
  await logout()
  router.push({ name: 'welcome' })
}

function patch(id: string, p: Partial<UIExchange>) {
  exchanges.value = exchanges.value.map((e) => (e.id === id ? { ...e, ...p } : e))
}

// The answer arrives as text, not as a pipeline trace, so it is wrapped in
// the shape the result view already knows. Everything the streamed route does
// not have stays null and the view shows the assistant's own route instead.
function streamedResponse(answer: string): PipelineResponse {
  return {
    finalStatus: 'READY_FOR_HR_RAG',
    domain: 'HR',
    domainReason: null,
    guard: null,
    intent: null,
    orchestrator: null,
    access: null,
    retrieval: null,
    answer,
  }
}

// `auth_missing` is the one code worth translating: it means the question
// needed live HRM data and this person has no HRM session here, which is a
// setup fact the assistant cannot phrase for us. For every other code the
// assistant's own text is user-safe and more specific than anything we could
// invent, so it is shown as-is.
function errorText(frame: ChatFrame): string {
  if (frame.code === 'auth_missing') return t('chatHrmNotConnected')
  return frame.text?.trim() || t('chatFailed')
}

// Run (or re-run) the question for an existing exchange. Shared by send and
// regenerate so both paths handle abort/error/timing identically.
function runPipeline(id: string, question: string) {
  phase.value = 'sending'
  const t0 = performance.now()
  const controller = new AbortController()
  abortController = controller
  let answer = ''
  let failure: string | null = null

  const onFrame = (frame: ChatFrame) => {
    // A frame that arrives after Stop must not resurrect the exchange the
    // user just cancelled.
    if (controller.signal.aborted) return
    switch (frame.type) {
      case 'stage':
        patch(id, { stage: frame.text?.trim() || frame.stage || null })
        break
      case 'sources':
        patch(id, { sources: frame.sources ?? [] })
        break
      case 'artifact': {
        // The fields come either nested under `artifact` or inline.
        const { type: _type, ...inline } = frame
        patch(id, { artifact: frame.artifact ?? inline })
        break
      }
      case 'token':
        answer += frame.text ?? ''
        // The response object appears with the FIRST token, which is what
        // swaps the "Thinking" loader for the answer being written.
        patch(id, { response: streamedResponse(answer), stage: null, error: null })
        break
      case 'error':
        failure = errorText(frame)
        break
      case 'done':
        patch(id, { route: frame.route ?? null, stage: null })
        break
      default:
        break
    }
  }

  streamAsk(question, onFrame, { chatId, signal: controller.signal })
    .then(() => {
      const durationMs = performance.now() - t0
      if (failure && !answer) {
        // Nothing useful arrived: the error shell with Regenerate is the
        // honest view.
        patch(id, { error: failure, stage: null, durationMs })
      } else {
        patch(id, {
          response: streamedResponse(answer),
          // An error after a partial answer is a NOTE, not a failure: the
          // part that arrived is still worth reading.
          warning: failure,
          error: null,
          stage: null,
          durationMs,
        })
      }
      phase.value = 'idle'
    })
    .catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return
      patch(id, { error: localizeApiError(err, t), stage: null, durationMs: performance.now() - t0 })
      phase.value = 'idle'
    })
}

function send(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed || phase.value !== 'idle') return false
  // crypto.randomUUID() exists only in secure contexts (HTTPS / localhost);
  // over plain HTTP on the LAN it's undefined, so fall back to a non-crypto id.
  const id =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `ex-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  exchanges.value = [
    ...exchanges.value,
    { id, question: trimmed, response: null, error: null, durationMs: null, stage: null },
  ]
  runPipeline(id, trimmed)
  return true
}

// Re-run the same question in place: clear the existing result, then re-fetch.
function regenerate(id: string) {
  if (phase.value !== 'idle') return
  const ex = exchanges.value.find((e) => e.id === id)
  if (!ex) return
  patch(id, {
    response: null, error: null, cancelled: false, durationMs: null,
    stage: null, sources: [], artifact: null, warning: null, route: null,
  })
  runPipeline(id, ex.question)
}

// The newest answer, for the voice panel to read back after a spoken turn.
const lastAnswer = computed(() => {
  const last = exchanges.value[exchanges.value.length - 1]
  return last?.response?.answer ?? null
})

const displayName = computed(
  () => user.value?.fullName?.trim() || user.value?.email?.split('@')[0] || t('defaultName'),
)
const actorType = computed<ActorType>(() => (user.value?.actorType as ActorType) ?? 'CUSTOMER')
</script>

<template>
  <div
    :style="{
      fontFamily: 'Figtree, sans-serif',
      color: 'var(--text)',
      height: '100vh',
      overflow: 'hidden',
      background: 'var(--bg)',
      position: 'relative',
    }"
  >
    <div
      data-screen-label="App shell"
      :style="{ position: 'absolute', inset: 0, display: 'flex', animation: 'fadeUp 0.5s ease both' }"
    >
      <AmbientBackground />

      <ChatSidebar
        :user="user"
        :theme="theme"
        :open="sidebarOpen"
        :collapsed="collapsed"
        :dev-mode="devMode"
        :wake="wakeEnabled"
        :wake-active="wakeActive"
        :wake-supported="wakeSupported"
        :wake-distorted="wakeDistorted"
        @toggle-theme="toggleTheme"
        @toggle-dev-mode="toggleDevMode"
        @toggle-wake="toggleWake"
        @new-chat="newChat"
        @close="sidebarOpen = false"
        @toggle-collapse="toggleCollapse"
        @logout="onLogout"
      />

      <div v-if="sidebarOpen" class="chat-backdrop" @click="sidebarOpen = false" />

      <div class="chat-main">
        <button class="chat-menu-btn glass glass-hover" :aria-label="t('menu')" @click="sidebarOpen = true">
          <MenuIcon :size="18" />
        </button>

        <Welcome v-if="exchanges.length === 0" :name="displayName" :actor-type="actorType" @chip="send" />
        <Conversation v-else :exchanges="exchanges" :dev-mode="devMode" :busy="phase !== 'idle'" @regenerate="regenerate" />
        <InputDock :phase="phase" :send="send" :stop="stop" @conversation="openVoice" />
        <AnswerGlow :phase="phase" />

        <VoicePanel
          :open="voiceOpen"
          :send="send"
          :busy="phase !== 'idle'"
          :answer="lastAnswer"
          :greeting="t('voiceGreeting')"
          @close="closeVoice"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-main {
  flex: 1;
  position: relative;
  min-width: 0;
  min-height: 0;
}
.chat-menu-btn {
  display: none;
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 15;
  width: 38px;
  height: 38px;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  cursor: pointer;
  box-shadow: var(--glass-shadow);
}
.chat-backdrop {
  display: none;
}
@media (max-width: 768px) {
  .chat-menu-btn {
    display: flex;
  }
  .chat-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 19;
    background: rgba(0, 0, 0, 0.4);
  }
}
</style>
