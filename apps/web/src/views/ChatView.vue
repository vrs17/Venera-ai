<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { streamAsk } from '../api/chat.api'
import { openChat as fetchChat } from '../api/chats.api'
import { localizeApiError } from '../api/errors'
import { ApiError } from '../api/http'
import { useAuth } from '../composables/useAuth'
import { useChats } from '../composables/useChats'
import { useWakeWord, WAKE_LOCALES, WAKE_STORAGE_KEY } from '../composables/useWakeWord'
import { warmGreeting } from '../api/greeting'
import type { ActionProposal, ActorType, ChatFrame, ChatMessage, Phase, PipelineResponse, UIExchange } from '../types'
import { applyTheme, getInitialTheme } from '../theme'
import { isoToMs } from '../time'
import { recallSources, rememberSources } from '../sourcesCache'
import type { Theme } from '../theme'
import AmbientBackground from '../components/AmbientBackground.vue'
import ChatSidebar from '../components/ChatSidebar.vue'
import Welcome from '../components/Welcome.vue'
import Conversation from '../components/Conversation.vue'
import InputDock from '../components/InputDock.vue'
import VoicePanel from '../components/VoicePanel.vue'
import AnswerGlow from '../components/AnswerGlow.vue'
import DocViewer from '../components/DocViewer.vue'
import { useDocViewer } from '../composables/useDocViewer'
import { MenuIcon } from '../icons'

const { t, locale } = useI18n({ useScope: 'global' })
const router = useRouter()
// Identity now comes from the authenticated session (derived from the token by
// the backend); the chat request carries only the question.
const { user, logout } = useAuth()
// Iqtibos qilingan hujjat - chat yonidagi panel. Manba ro'yxati ochadi.
const { doc: viewerDoc, close: closeViewer } = useDocViewer()
// Suhbatlar tarixi (yon panel). Ro'yxat serverdan; bu ekran faqat qaysi
// suhbat ochiq ekanini aytadi va yangi javob kelganda xabar beradi.
const chats = useChats()
const exchanges = ref<UIExchange[]>([])
const phase = ref<Phase>('idle')
// Eski suhbat ochilmoqda / ochilmadi. `historyRequest` - ketma-ket
// ochishlar: odam ikkita qatorni tez bossa, birinchisining javobi
// keyin kelib ikkinchisini bosib qo'ymasin.
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
let historyRequest = 0
const theme = ref<Theme>(getInitialTheme())
const sidebarOpen = ref(false)
const voiceOpen = ref(false)
/** The holding phrase the backend sent for the question in flight.
 *
 *  Lives here rather than in the panel because it arrives on the CHAT
 *  stream — the panel only speaks it. Cleared on every new question so a
 *  phrase from the previous turn can never surface late. */
const holdCue = ref<{ text: string; clip?: string; at?: number } | null>(null)

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

// crypto.randomUUID() exists only in secure contexts (HTTPS / localhost);
// over plain HTTP on the LAN it's undefined, so fall back to a non-crypto id.
// Both shapes are path-safe: the history routes put the chat id in a URL.
function randomId(prefix: string): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

// One conversation, one key. The assistant keeps its memory per
// (user_id, chat_id), so follow-up questions ("va o'tgan oyda?") only work
// while this stays the same — and "New chat" MUST change it, or the previous
// conversation would bleed into the new one. The same key names the chat in
// the history list once its first answer has been stored.
let chatId = randomId('c')
chats.select(chatId)

watch(theme, (value) => applyTheme(value), { immediate: true })
onBeforeUnmount(() => abortController?.abort())

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

function newChat() {
  closeViewer()
  abortController?.abort()
  abortController = null
  historyRequest++
  historyLoading.value = false
  historyError.value = null
  exchanges.value = []
  phase.value = 'idle'
  chatId = randomId('c')
  chats.select(chatId)
}

// Open a chat from the sidebar. The messages come from the server; the next
// question goes out with the same chatId, so the assistant's memory of the
// thread continues where it left off.
async function openHistory(id: string) {
  if (id === chatId && !historyLoading.value && !historyError.value) return
  abortController?.abort()
  abortController = null
  phase.value = 'idle'
  chatId = id
  chats.select(id)
  const request = ++historyRequest
  historyLoading.value = true
  historyError.value = null
  exchanges.value = []
  try {
    const detail = await fetchChat(id)
    if (request !== historyRequest) return
    exchanges.value = exchangesFrom(detail.messages, id)
  } catch (err) {
    if (request !== historyRequest) return
    if (err instanceof ApiError && err.status === 404) {
      // Deleted from another device, or not this person's chat: it has no
      // place in the sidebar, and there is nothing to show — start fresh.
      chats.forget(id)
      newChat()
      return
    }
    historyError.value = localizeApiError(err, t)
  } finally {
    if (request === historyRequest) historyLoading.value = false
  }
}

function retryOpenHistory() {
  const id = chatId
  historyError.value = null
  void openHistory(id)
}

// Stored messages -> the exchange shape the conversation view renders. A
// user message opens an exchange, the assistant message that follows fills
// it. A user message with no reply (the answer failed back then) is shown
// as stopped, with Regenerate; a reply with no question (legacy rows) is
// shown on its own.
function exchangesFrom(messages: ChatMessage[], chat: string): UIExchange[] {
  const out: UIExchange[] = []
  let current: UIExchange | null = null
  for (const message of messages) {
    const content = message.content ?? ''
    if (message.role === 'assistant') {
      // The server keeps no citations per message; this browser may have
      // them from when the answer was streamed (sourcesCache.ts).
      const cached = recallSources(chat, content)
      if (current && !current.response) {
        current.response = streamedResponse(content)
        current.cancelled = false
        current.answeredAt = isoToMs(message.created_at)
        current.sources = cached?.sources ?? []
        current.artifact = cached?.artifact ?? null
      } else if (current?.response) {
        current.response = streamedResponse(`${current.response.answer ?? ''}\n\n${content}`)
      } else {
        current = {
          id: randomId('ex'), question: '', response: streamedResponse(content), error: null,
          durationMs: null, stage: null, answeredAt: isoToMs(message.created_at),
          sources: cached?.sources ?? [], artifact: cached?.artifact ?? null,
        }
        out.push(current)
      }
      continue
    }
    current = {
      id: randomId('ex'), question: content, response: null, error: null, durationMs: null,
      stage: null, cancelled: true, askedAt: isoToMs(message.created_at),
    }
    out.push(current)
  }
  return out
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
// The sidebar list, keyed by the signed-in person so another account in the
// same tab never sees a stale list (the route guard guarantees `user`).
onMounted(() => {
  const owner = user.value ? String(user.value.actorId) : null
  if (owner) void chats.load(owner)
})
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function toggleDevMode() {
  devMode.value = !devMode.value
}

async function onLogout() {
  abortController?.abort()
  // The list belongs to this person; the next login must not see it.
  chats.reset()
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

// The assistant's OWN text wins, for every code including auth_missing.
//
// It used to be overridden for `auth_missing` with our own HRM-specific
// sentence. That became WRONG when CRM was added on 2026-09-14: a CRM
// question with no CRM token returned "CRM tizimiga kiring" from the
// service, and we replaced it with "your HRM account is not connected" —
// pointing the person at the wrong system. The service knows which
// platform the question needed; we do not.
//
// The service's text is documented as user-safe and written in the
// language of the QUESTION. Our own string stays as the fallback for when
// no text arrives at all.
function errorText(frame: ChatFrame): string {
  const own = frame.text?.trim()
  if (own) return own
  if (frame.code === 'auth_missing' || frame.code === 'auth_expired') {
    return t('chatNotConnected')
  }
  return t('chatFailed')
}

// Run (or re-run) the question for an existing exchange. Shared by send and
// regenerate so both paths handle abort/error/timing identically.
function runPipeline(id: string, question: string) {
  phase.value = 'sending'
  const t0 = performance.now()
  const controller = new AbortController()
  abortController = controller
  // The chat this turn belongs to. Opening another chat or "New chat" aborts
  // the stream, so `chatId` cannot have moved by the time the answer lands —
  // but the list update below must not depend on that.
  const turnChat = chatId
  let answer = ''
  let failure: string | null = null
  let proposed = false

  const onFrame = (frame: ChatFrame) => {
    // A frame that arrives after Stop must not resurrect the exchange the
    // user just cancelled.
    if (controller.signal.aborted) return
    switch (frame.type) {
      case 'stage':
        patch(id, { stage: frame.text?.trim() || frame.stage || null })
        break
      case 'sources':
        patch(id, { sources: frame.sources ?? frame.items ?? [] })
        break
      case 'artifact': {
        // The fields come either nested under `artifact` or inline.
        const { type: _type, ...inline } = frame
        patch(id, { artifact: frame.artifact ?? inline })
        break
      }
      case 'proposal': {
        // A write action the assistant wants to make. NOTHING has changed:
        // the card under the answer asks the person to confirm or reject.
        // Nested under `proposal` or inline, like the artifact frame.
        const { type: _type, ...inline } = frame
        const proposal = (frame.proposal ?? inline) as ActionProposal
        if (proposal.token) {
          patch(id, { proposal })
          proposed = true
        }
        break
      }
      case 'hold':
        // A ready-made holding clip while HRM/CRM works. Voice only: the
        // panel plays it, and nothing is written into the exchange. In text
        // mode the backend does not send these at all.
        if (frame.clip) holdCue.value = { text: frame.text ?? '', clip: frame.clip, at: frame.at }
        break
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

  // A new question retires the previous holding phrase, so a phrase from
  // the last turn can never be spoken over this one's answer.
  holdCue.value = null
  streamAsk(question, onFrame, {
    chatId,
    signal: controller.signal,
    // Only the client knows whether anyone is listening.
    voice: voiceOpen.value,
    locale: String(locale.value),
  })
    .then(() => {
      const durationMs = performance.now() - t0
      if (failure && !answer) {
        // Nothing useful arrived: the error shell with Regenerate is the
        // honest view.
        patch(id, { error: failure, stage: null, durationMs, answeredAt: Date.now() })
      } else {
        patch(id, {
          response: streamedResponse(answer),
          // An error after a partial answer is a NOTE, not a failure: the
          // part that arrived is still worth reading.
          warning: failure,
          error: null,
          stage: null,
          durationMs,
          answeredAt: Date.now(),
        })
        // An answer was stored, so the chat now exists on the server: it
        // enters the sidebar (first turn) or moves to the top (later turns).
        // Not before — the service creates the chat with its first answer.
        if (answer || proposed) chats.noteTurn(turnChat, question)
        // The server will not hand the citations back with the history, so
        // keep them here for when this chat is reopened in this browser.
        const done = exchanges.value.find((e) => e.id === id)
        if (answer && done) rememberSources(turnChat, answer, done.sources ?? [], done.artifact)
      }
      phase.value = 'idle'
    })
    .catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return
      patch(id, { error: localizeApiError(err, t), stage: null, durationMs: performance.now() - t0, answeredAt: Date.now() })
      phase.value = 'idle'
    })
}

function send(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed || phase.value !== 'idle') return false
  const id = randomId('ex')
  exchanges.value = [
    ...exchanges.value,
    { id, question: trimmed, response: null, error: null, durationMs: null, stage: null, askedAt: Date.now() },
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
    stage: null, sources: [], artifact: null, proposal: null, warning: null, route: null, answeredAt: null,
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
        @open-chat="openHistory"
        @close="sidebarOpen = false"
        @toggle-collapse="toggleCollapse"
        @logout="onLogout"
      />

      <div v-if="sidebarOpen" class="chat-backdrop" @click="sidebarOpen = false" />

      <div class="chat-main">
        <button class="chat-menu-btn glass glass-hover" :aria-label="t('menu')" @click="sidebarOpen = true">
          <MenuIcon :size="18" />
        </button>

        <!-- An old chat is being fetched, or could not be. Both replace the
             conversation area: the welcome screen would say "new chat". -->
        <div v-if="historyLoading" class="chat-history-state" role="status">{{ t('historyLoading') }}</div>
        <div v-else-if="historyError" class="chat-history-state" role="alert">
          <span>{{ historyError }}</span>
          <button class="chat-history-retry" type="button" @click="retryOpenHistory">{{ t('retry') }}</button>
        </div>
        <Welcome v-else-if="exchanges.length === 0" :name="displayName" :actor-type="actorType" @chip="send" />
        <Conversation v-else :exchanges="exchanges" :dev-mode="devMode" :busy="phase !== 'idle'" @regenerate="regenerate" />
        <InputDock :phase="phase" :send="send" :stop="stop" @conversation="openVoice" />
        <AnswerGlow :phase="phase" />

        <VoicePanel
          :hold="holdCue"
          :open="voiceOpen"
          :send="send"
          :busy="phase !== 'idle'"
          :answer="lastAnswer"
          :greeting="t('voiceGreeting')"
          @close="closeVoice"
        />
      </div>

      <!-- Iqtibos qilingan hujjat: chatning YONIDA, ustida emas - odam
           javobni va manbani birga ko'rsin (mobilda butun ekran). -->
      <DocViewer v-if="viewerDoc" :doc="viewerDoc" @close="closeViewer" />
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
.chat-history-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 0 24px 120px;
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
}
.chat-history-retry {
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  font-family: 'Figtree', sans-serif;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.chat-history-retry:hover {
  background: var(--surface-hover);
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
