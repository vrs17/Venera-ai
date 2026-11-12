<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { streamAsk } from '../api/chat.api'
import { openChat as fetchChat } from '../api/chats.api'
import { localizeApiError } from '../api/errors'
import { ApiError } from '../api/http'
import { copyText } from '../clipboard'
import { useAuth } from '../composables/useAuth'
import { usePro } from '../composables/usePro'
import { hasPro, useEngines } from '../composables/useEngines'
import { provisionalTitle, useChats } from '../composables/useChats'
import { useWakeWord, WAKE_LOCALES, WAKE_STORAGE_KEY } from '../composables/useWakeWord'
import { warmGreeting } from '../api/greeting'
import type { ActionProposal, ActorType, ChatFrame, ChatMessage, Phase, PipelineResponse, ProInfo } from '../types'
import { useTheme } from '../theme'
import type { ThemePreference } from '../theme'
import { isoToMs } from '../time'
import { clearSources, recallSources, rememberSources } from '../sourcesCache'
import type { ReportMessage } from '../features/report/report.api'
import ChatSidebar from '../components/ChatSidebar.vue'
import Welcome from '../components/Welcome.vue'
import Conversation from '../components/Conversation.vue'
import InputDock from '../components/InputDock.vue'
import VoicePanel from '../components/VoicePanel.vue'
import DocViewer from '../components/DocViewer.vue'
import ChatTopBar from '../components/chat/ChatTopBar.vue'
import type { ChatExchange } from '../components/chat/types'
import { useChatActions } from '../components/chat/chatActions'
import { stopReading } from '../components/chat/readAloud'
import { useDocViewer } from '../composables/useDocViewer'
import VButton from '../ui/VButton.vue'
import VDialog from '../ui/VDialog.vue'
import VSheet from '../ui/VSheet.vue'
import VSkeleton from '../ui/VSkeleton.vue'
import { toast } from '../ui/useToast'
import { useIsPhone, useMediaQuery } from '../ui/composables/useMediaQuery'
import { useResizablePanel } from '../ui/composables/useResizablePanel'
import { isEditableTarget, matchesShortcut } from '../ui/useCommandPalette'

// Kamdan-kam ochiladi - alohida bo'lak, chatning birinchi yuklanishiga qo'shilmaydi.
const ReportDialog = defineAsyncComponent(() => import('../features/report/ReportDialog.vue'))
const DesktopDownload = defineAsyncComponent(() => import('../components/DesktopDownload.vue'))
const MemoryDialog = defineAsyncComponent(() => import('../components/MemoryDialog.vue'))

const { t, locale } = useI18n({ useScope: 'global' })
const router = useRouter()
// Identity now comes from the authenticated session (derived from the token by
// the backend); the chat request carries only the question.
const { user, logout } = useAuth()
// "Pro" - HAR XABAR uchun. Kalit kiritish panelida turadi, byudjet esa
// shu yerda yangilanadi: javob bilan kelgan `pro.remaining` qayta
// so'rashdan aniqroq va bepul.
const pro = usePro()
// Yordamchi versiyasi (v1/v2): admin odamga tanlov bergan bo'lsa kompozerda "v2 ▾"
// chiqadi va tanlov har savol bilan ketadi. Tanlov yo'q - hech narsa o'zgarmaydi.
const engines = useEngines()
// Iqtibos qilingan hujjat - chat yonidagi panel. Manba ro'yxati ochadi.
const { doc: viewerDoc, close: closeViewer } = useDocViewer()
// Suhbatlar tarixi (yon panel). Ro'yxat serverdan; bu ekran faqat qaysi
// suhbat ochiq ekanini aytadi va yangi javob kelganda xabar beradi.
const chats = useChats()
const { renameChat, deleteChat } = useChatActions()
const exchanges = ref<ChatExchange[]>([])
const phase = ref<Phase>('idle')
/** Hozir yozilayotgan javob (kursor va "javob tayyor" e'loni uchun). */
const streamingId = ref<string | null>(null)
// Eski suhbat ochilmoqda / ochilmadi. `historyRequest` - ketma-ket
// ochishlar: odam ikkita qatorni tez bossa, birinchisining javobi
// keyin kelib ikkinchisini bosib qo'ymasin.
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
let historyRequest = 0
// Mavzu tanlovi (yorug' / qorong'i / tizim) - theme.ts dagi yagona manba.
const { preference: theme, setPreference } = useTheme()
const voiceOpen = ref(false)
/** The holding phrase the backend sent for the question in flight.
 *
 *  Lives here rather than in the panel because it arrives on the CHAT
 *  stream — the panel only speaks it. Cleared on every new question so a
 *  phrase from the previous turn can never surface late. */
const holdCue = ref<{ text: string; clip?: string; at?: number } | null>(null)

// localStorage xususiy rejimda yoki bloklanganda xato tashlaydi - sahifa yiqilmasin.
function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v === '1'
  } catch {
    return fallback
  }
}
function writeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* saqlanmaydi - faqat shu sessiya uchun */
  }
}

// --- "Salom Venera" ---------------------------------------------------------
// OFF by default (2026-10-09, product owner's decision): an always-open
// microphone was suspected of slowing the page when dictation starts, it sends
// snippets of nearby speech to the STT provider while nobody is talking to
// Venera, and people did not expect to be listened to. The switch stays - anyone
// who wants the wake phrase turns it on, and only an explicit '1' keeps it on
// (`WAKE_STORAGE_KEY` was renamed, so earlier stored "on"s do not carry over).
const wakeEnabled = ref(readFlag(WAKE_STORAGE_KEY, false))
watch(wakeEnabled, (value) => writeFlag(WAKE_STORAGE_KEY, value))
const wakeSupported = computed(() => WAKE_LOCALES.includes(String(locale.value)))

/** Kompozerda ovoz bilan yozilyapti (InputDock xabar beradi). Mikrofon o'shaniki:
 *  "Salom Venera" shu paytda to'xtab turadi - aks holda diktovkani ham eshitib,
 *  uni serverga "uyg'otish so'zi" deb yuborar va yozuv o'rtasida panelni ochardi. */
const dictating = ref(false)

const {
  active: wakeActive,
  blocked: wakeBlocked,
  distorted: wakeDistorted,
} = useWakeWord({
  enabled: wakeEnabled,
  locale: computed(() => String(locale.value)),
  paused: computed(() => voiceOpen.value || dictating.value),
  onWake: () => {
    voiceOpen.value = true
  },
})

function toggleWake() {
  wakeEnabled.value = !wakeEnabled.value
}

// Jonli ovozli suhbat ikki yo'l bilan ochiladi: kompozerdagi "Jonli suhbat"
// tugmasi va "Salom Venera". Kompozerdagi mikrofon esa ovoz bilan YOZADI
// (InputDock), panelni ochmaydi.
function closeVoice() {
  voiceOpen.value = false
}
// Ovozli panel o'z ovozini gapiradi - javobni o'qish ustiga tushmasin.
watch(voiceOpen, (open) => open && stopReading())

// --- Yon panel ----------------------------------------------------------------
// ≥1120 - sahifada (yig'iladi, holati eslab qolinadi; chetidan tortib kengligi
// o'zgartiriladi); undan kichikda - chap tomondan chiquvchi drawer (VSheet: fokus
// tuzog'i, parda, Esc).
const isDesktop = useMediaQuery('(min-width: 1120px)')
const isPhone = useIsPhone()
const sidebarOpen = ref(false)
watch(isDesktop, (desktop) => desktop && (sidebarOpen.value = false))
const collapsed = ref(readFlag('venera_sidebar_collapsed', false))
watch(collapsed, (value) => writeFlag('venera_sidebar_collapsed', value))
// Kenglik: 220-420, standart 272 (tokens.css --sidebar-w), ustun 56 (--rail-w). Yig'iq
// holat baribir shu yerda (`collapsed`) - Esc ham, tortib yig'ish ham uni o'zgartiradi.
const sidebarPanel = useResizablePanel({
  storageKey: 'venera_sidebar_w',
  min: 220,
  max: 420,
  initial: 272,
  rail: 56,
  collapsed: () => collapsed.value,
  setCollapsed: (value) => {
    collapsed.value = value
  },
  enabled: () => isDesktop.value,
})

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
/** Reaktiv nusxa: suhbat almashganini Conversation bilsin (darhol oxiriga). */
const chatKey = ref(chatId)

onBeforeUnmount(() => {
  abortController?.abort()
  stopReading()
  // Ko'ruvchi holati modul darajasida: boshqa tabda chiqilganda ChatView shu yo'l
  // bilan yopiladi va keyingi kirgan odamga oldingisining hujjati ochiq qolmasin.
  closeViewer()
})

function setTheme(value: ThemePreference) {
  setPreference(value)
}

// --- Xabar berish (spec §4.4) -------------------------------------------------
const reportOpen = ref(false)
/** Dialog birinchi ochilganda yuklanadi va keyin DOM'da qoladi (yopilish animatsiyasi uchun). */
const reportMounted = ref(false)
const reportTurnId = ref<string | null>(null)
/** Bitta javob uchun ochilganda uning kaliti (`turnId`, bo'lmasa `ex:<id>`). */
let reportKey: string | null = null
const reportedKeys = ref<ReadonlySet<string>>(new Set())
const chatReported = ref(false)
const topScrolled = ref(false)

/** Suhbatga bog'liq ekran holati - boshqa suhbatga o'tganda tozalanadi. */
function resetChatUi() {
  stopReading()
  reportOpen.value = false
  reportedKeys.value = new Set()
  chatReported.value = false
  topScrolled.value = false
}

function newChat() {
  closeViewer()
  abortController?.abort()
  abortController = null
  historyRequest++
  historyLoading.value = false
  historyError.value = null
  exchanges.value = []
  streamingId.value = null
  phase.value = 'idle'
  chatId = randomId('c')
  chatKey.value = chatId
  chats.select(chatId)
  resetChatUi()
}

// Open a chat from the sidebar. The messages come from the server; the next
// question goes out with the same chatId, so the assistant's memory of the
// thread continues where it left off. `force` - "Qayta urinish": o'sha suhbatni
// qayta so'raydi (aks holda pastdagi qo'riqchi uni "allaqachon ochiq" deb o'tkazib
// yuborardi va odam ko'rinmaydigan suhbatda qolardi).
async function openHistory(id: string, force = false) {
  if (!force && id === chatId && !historyLoading.value && !historyError.value) return
  if (id !== chatId) {
    // Boshqa suhbatning hujjati yangi suhbat yonida ochiq qolmasin.
    closeViewer()
    resetChatUi()
  }
  abortController?.abort()
  abortController = null
  streamingId.value = null
  phase.value = 'idle'
  chatId = id
  chatKey.value = id
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
  void openHistory(chatId, true)
}

// Stored messages -> the exchange shape the conversation view renders. A
// user message opens an exchange, the assistant message that follows fills
// it. A user message with no reply (the answer failed back then) is shown
// as stopped, with Regenerate; a reply with no question (legacy rows) is
// shown on its own.
function exchangesFrom(messages: ChatMessage[], chat: string): ChatExchange[] {
  const out: ChatExchange[] = []
  let current: ChatExchange | null = null
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

// User-initiated cancel. Before the first token the exchange becomes a soft
// "Generation stopped" notice (not a request-failed error); after it, the part
// that arrived stays and is marked "Stopped".
function stop() {
  if (phase.value !== 'sending') return
  abortController?.abort()
  abortController = null
  const inflight = exchanges.value.find((e) => !e.response && !e.error && !e.cancelled)
  if (inflight) patch(inflight.id, { cancelled: true })
  else if (streamingId.value) patch(streamingId.value, { stopped: true })
  streamingId.value = null
  phase.value = 'idle'
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

// Esc: ovozli panel ustida - avval u yopiladi. Aks holda katta ekranda yon panel
// yig'iladi/ochiladi; kichik ekranda ochiq drawer yopiladi (Esc uni OCHMAYDI).
// IME tarkibi va chuqurroq ishlov bergan (preventDefault) hodisa o'tkazib yuboriladi -
// menyu/dialog/qayta nomlash Esc'ni o'zi oladi. Yozuv maydonidagi Esc panelga tegmaydi.
// ⌘⇧O / Ctrl+Shift+O - yangi suhbat.
function onKeydown(e: KeyboardEvent) {
  if (e.isComposing || e.defaultPrevented) return
  if (matchesShortcut(e, 'mod+shift+o')) {
    // Ochiq oyna (xabar berish, ilova) ortida suhbat jimgina almashib qolmasin.
    if (document.querySelector('[aria-modal="true"]:not(.chat-drawer)')) return
    e.preventDefault()
    newChat()
    sidebarOpen.value = false
    return
  }
  if (e.key !== 'Escape') return
  // The voice panel is on top, so ESC closes that first — otherwise the
  // sidebar would toggle behind an open dialog and the microphone stay live.
  if (voiceOpen.value) {
    closeVoice()
    return
  }
  if (isEditableTarget(e.target)) return
  if (isDesktop.value) collapsed.value = !collapsed.value
  else sidebarOpen.value = false
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
// Byudjet bir marta yuklanadi; keyin har javob bilan o'zi yangilanadi
// (`pro.noteAnswer`), ya'ni qayta so'rashning hojati yo'q. Versiya tanlovi bor odamda
// esa tanlov o'zgarganda qayta so'raladi (pastda) - "Pro" kaliti versiyaga ergashadi.
onMounted(() => {
  if (user.value) void pro.load(engines.requestEngine.value)
})

// Versiyalar: sahifa ochilganda va boshqa odam kirganda (shu tabda chiqib-kirish).
// `immediate` - onMounted o'rniga: kirish bilan birinchi so'rov bir joyda.
watch(
  () => user.value?.actorId ?? null,
  (id) => {
    if (id !== null) void engines.load(id)
  },
  { immediate: true },
)
// Tanlov o'zgardi (yoki versiyalar endi keldi) -> "Pro" byudjeti shu versiya bo'yicha.
// Javob kelguncha kalit yashirin (`usePro.available` versiyani tekshiradi): v1 ga
// o'tilganda eski "v2 da Pro bor" holati bir lahza ham qolmasin.
// `choice` - versiyalar yuklangan: chiqishdagi `reset()` (null) eski odamning tokeni
// bilan yana bir byudjet so'rovini yubormasin.
watch(engines.requestEngine, (engine, prev) => {
  if (user.value && engines.choice.value && engine !== prev) void pro.load(engine)
})
// Odam tabga qaytdi: admin shu orada versiya bergan yoki olgan bo'lishi mumkin. Arzon
// GET, lekin daqiqasiga bir martadan ko'p emas - tab almashtirib turish so'rov yog'dirmasin.
let enginesCheckedAt = Date.now()
function onVisible() {
  if (document.visibilityState !== 'visible' || !user.value) return
  if (Date.now() - enginesCheckedAt < 60_000) return
  enginesCheckedAt = Date.now()
  void engines.load(user.value.actorId)
}
onMounted(() => document.addEventListener('visibilitychange', onVisible))
onBeforeUnmount(() => document.removeEventListener('visibilitychange', onVisible))
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

async function onLogout() {
  abortController?.abort()
  stopReading()
  // Keyingi kirgan odam boshqa "Pro" byudjeti va boshqa versiyalar bilan keladi.
  pro.reset()
  engines.reset()
  // Ochiq hujjat (HRM/CRM manbasi bo'lishi mumkin) keyingi kirgan odamga qolmasin.
  closeViewer()
  // The list belongs to this person; the next login must not see it — nor the
  // cited HRM/CRM digests cached in this browser.
  chats.reset()
  clearSources()
  // Oldingi hisobning "Bekor qilish" toast'i keyingi kirgan odamga qolib ketmasin.
  toast.clear()
  await logout()
  router.push({ name: 'welcome' })
}

function patch(id: string, p: Partial<ChatExchange>) {
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
// Xizmatning O'Z matni yutadi - BITTA istisno: HRM yoki CRM tokeni yo'qligi. Xizmat u yerda
// "«+» menyusidan ulang" deydi, lekin 2026-11-12 dan ikkalasi ham odam tomonidan ulanmaydi:
// BRB-Tech ID bilan kirilganda o'zi ulanadi («+» da «Ulanishlar» yo'q). Qaysi tizim - xizmat
// matnidan (Mini App'dagi qoida, `tg/chat/useTgChat.ts`).
function errorText(frame: ChatFrame): string {
  const own = frame.text?.trim()
  const auth = frame.code === 'auth_missing' || frame.code === 'auth_expired'
  if (auth && own && /CRM|HRM/i.test(own)) {
    const crm = /CRM/i.test(own)
    const hrm = /HRM/i.test(own)
    return t('chatSsoNotConnected', { system: crm && hrm ? 'HRM / CRM' : crm ? 'CRM' : 'HRM' })
  }
  if (own) return own
  return auth ? t('chatNotConnected') : t('chatFailed')
}

// Run (or re-run) the question for an existing exchange. Shared by send and
// regenerate so both paths handle abort/error/timing identically.
function runPipeline(id: string, question: string, mode: 'standard' | 'pro' = 'standard') {
  phase.value = 'sending'
  streamingId.value = id
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
        // Audit kaliti - admin izi va shikoyat shu bilan bog'lanadi.
        if (frame.request_id) patch(id, { requestId: frame.request_id })
        break
      case 'done':
        patch(id, {
          route: frame.route ?? null,
          stage: null,
          ...(frame.request_id ? { requestId: frame.request_id } : {}),
          // Qaysi dvigatel (v1/v2) javob berdi - tanlov bor odamga javob ostida.
          ...(frame.engine ? { engine: String(frame.engine) } : {}),
        })
        // "Pro" natijasi: ishlatildimi, nechta qoldi, berilmagan bo'lsa
        // sababi. Blok FAQAT shu rejim so'ralgan turlarda keladi.
        if (frame.pro) {
          patch(id, { pro: frame.pro })
          pro.noteAnswer(frame.pro)
        } else if (mode === 'pro' && !hasPro(frame.engine)) {
          // "Pro" so'raldi, lekin backend uni "Pro"siz dvigatelga YUBORMADI
          // (kanal sozlamasi sahifa ochilgandan keyin o'zgargan) - shartnoma
          // bo'yicha bunda `done` da `pro` bloki umuman yo'q. Jim qolsak odam
          // "Pro ishladi" deb o'ylaydi; admin izida esa shu tur "berilmadi
          // (versiya)" bo'lib yozilgan. Belgi o'sha gapni aytadi va kalit
          // yashirinadi (`noteAnswer` -> `available: false`).
          const denied: ProInfo = { requested: true, used: false, calls: 0, reason: 'engine' }
          patch(id, { pro: denied })
          pro.noteAnswer(denied)
        }
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
    // "Pro" FAQAT shu xabar uchun: kalit yoqiq bo'lsa ham har savol
    // alohida hal qilinadi (u pulga tushadi).
    mode,
    signal: controller.signal,
    // Only the client knows whether anyone is listening.
    voice: voiceOpen.value,
    // Odam tanlagan versiya - faqat tanlov bor bo'lsa (aks holda `null`, maydon
    // yuborilmaydi). Server uni ruxsat etilganlar ichida bo'lsagina oladi.
    engine: engines.requestEngine.value,
    locale: String(locale.value),
    // Sarlavhalar bilan keladi - javob tugamasdan ham "Xabar berish" kalitni bilsin.
    onTurn: (turnId) => {
      if (!controller.signal.aborted) patch(id, { turnId })
    },
  })
    .then(() => {
      const durationMs = performance.now() - t0
      if (streamingId.value === id && !controller.signal.aborted) streamingId.value = null
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
      if (streamingId.value === id) streamingId.value = null
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
  // Rejim SHU YERDA qotiriladi: odam javob kelguncha kalitni bossa ham,
  // bu tur o'zi yuborilgan rejimda qolishi kerak - aks holda javob ostidagi
  // belgi boshqa narsani ko'rsatardi. `active`, `enabled` emas: kalit
  // ko'rinmasa (v1 kanali) yoki byudjet tugagan bo'lsa, eslab qolingan
  // "yoqiq" tanlov savolni "pro" qilib yubormasin.
  const mode = pro.active.value ? 'pro' : 'standard'
  patch(id, { proRequested: mode === 'pro' })
  runPipeline(id, trimmed, mode)
  return true
}

// Taklif tugmasi bosilgach salomlashuv yo'qoladi va fokus <body> ga tushib qolardi -
// klaviatura bilan ishlayotgan odam keyingi savolni yozish joyiga qaytadi. Sensorli
// ekranda emas: u yerda fokus ekran klaviaturasini ochib, javobni yopib qo'yardi.
const dock = ref<InstanceType<typeof InputDock> | null>(null)
function sendChip(text: string) {
  if (!send(text)) return
  void nextTick(() => {
    const active = document.activeElement
    if ((!active || active === document.body) && window.matchMedia('(pointer: fine)').matches) dock.value?.focus()
  })
}

// Re-run the same question in place: clear the existing result, then re-fetch.
function regenerate(id: string) {
  if (phase.value !== 'idle') return
  const ex = exchanges.value.find((e) => e.id === id)
  if (!ex) return
  patch(id, {
    response: null, error: null, cancelled: false, stopped: false, durationMs: null, stage: null,
    sources: [], artifact: null, proposal: null, warning: null, route: null, answeredAt: null,
    turnId: null, requestId: null, pro: null, engine: null,
  })
  // Qayta yaratish O'SHA rejimda: "pro" savolni standart rejimda qayta
  // so'rash boshqa javob berardi, teskarisi esa odam so'ramagan holda
  // byudjetdan yeyardi. Bu - odamning O'Z bosishi (hujjat faqat AVTOMATIK
  // qayta urinishni taqiqlaydi; bunday yo'l chatda yo'q). Lekin "Pro" endi
  // yo'q bo'lsa (dvigatel o'zgargan) - standart: backend baribir yubormasdi.
  runPipeline(id, ex.question, ex.proRequested && pro.available.value ? 'pro' : 'standard')
}

// The newest answer, for the voice panel to read back after a spoken turn.
const lastAnswer = computed(() => {
  const last = exchanges.value[exchanges.value.length - 1]
  return last?.response?.answer ?? null
})
const lastTurn = computed(() => exchanges.value[exchanges.value.length - 1]?.turnId ?? null)
// O'sha javobning manbalari: ovoz paneli `[1]` ni chatdagidek iqtibosga aylantiradi.
const lastSources = computed(() => exchanges.value[exchanges.value.length - 1]?.sources)

// --- Salomlashuv --------------------------------------------------------------
/** "Salom, {ism}". HRM ism-familiyani ko'pincha rasmiy tartibda beradi ("Mamajonov
 *  Yusufjon"): birinchi so'z familiya qo'shimchasi bilan tugasa - ism ikkinchi so'z.
 *  BUTUN KATTA HARF bilan yozilgani odatiy ko'rinishga keltiriladi. */
function firstName(full: string): string {
  const words = full.trim().split(/\s+/u).filter(Boolean)
  if (!words.length) return ''
  let pick = words.length > 1 && /(ov|ova|ev|eva|ов|ова|ев|ева)$/iu.test(words[0]) ? words[1] : words[0]
  if (pick.length > 1 && pick === pick.toLocaleUpperCase()) pick = pick.charAt(0) + pick.slice(1).toLocaleLowerCase()
  return pick
}
const greetName = computed(() => firstName(user.value?.fullName ?? '') || user.value?.email?.split('@')[0] || '')
const actorType = computed<ActorType>(() => (user.value?.actorType as ActorType) ?? 'CUSTOMER')

// --- Rollar -------------------------------------------------------------------
const roles = computed(() => (user.value?.roles ?? []).map((r) => r.toUpperCase()))
const isAdmin = computed(() => roles.value.includes('ADMIN'))
/** Savol izi havolasi: iz admin panelida ochiladi, u esa (marshrut ham, server ham) faqat
 *  ADMIN ga ochiq - RAG_ADMIN ga ko'rsatilsa, havola uni chatga qaytarib yuborardi. */
const canTrace = isAdmin

// --- Yuqori panel -------------------------------------------------------------
const activeSummary = computed(() => chats.chats.value.find((c) => c.chat_id === chats.activeId.value) ?? null)
const topTitle = computed(() => {
  if (activeSummary.value) return activeSummary.value.title
  const first = exchanges.value.find((e) => e.question)?.question
  return first ? provisionalTitle(first) : ''
})
/** Kamida bitta yordamchi javobi bor - muvaffaqiyatli YOKI xato bilan tugagan. "Xabar
 *  berish" shundan keyin yoqiladi: odamlar aynan yiqilgan javob haqida ko'proq xabar
 *  beradi (backend xato bilan tugagan savolni ham `turns` ga yozadi). Hali yozilayotgan
 *  javob hisobga kirmaydi; yarmida to'xtatilgani kiradi (kelgan qism ko'rinib turibdi).
 *  `answeredAt` ga tayanilmaydi: to'xtatishda u qo'yilmaydi, tarixda esa bo'lmasligi mumkin. */
const hasReply = computed(() =>
  exchanges.value.some((e) => !!e.error || (!!e.response && e.id !== streamingId.value)),
)
const welcome = computed(() => !historyLoading.value && !historyError.value && exchanges.value.length === 0)

function onTopRename(title: string) {
  if (activeSummary.value) void renameChat(activeSummary.value.chat_id, title)
}
function onTopDelete() {
  if (activeSummary.value) void deleteChat(activeSummary.value.chat_id, newChat)
}
async function copyChat() {
  const text = exchanges.value
    .map((ex) => {
      const lines: string[] = []
      if (ex.question) lines.push(`${t('chat.you')}: ${ex.question}`)
      const reply = ex.response?.answer?.trim() || ex.error || ''
      if (reply) lines.push(`${t('chat.assistant')}: ${reply}`)
      return lines.join('\n\n')
    })
    .filter(Boolean)
    .join('\n\n')
  if (await copyText(text)) toast.success(t('chat.chatCopied'))
  else toast.error(t('chat.copyFailed'))
}

// --- Xabar berish: dialog va belgilar -------------------------------------------
function isoOf(ms: number | null | undefined): string | null {
  return ms ? new Date(ms).toISOString() : null
}
/** Suhbat nusxasi - brauzer holatidan (server xabar bo'yicha manba saqlamaydi). */
const reportMessages = computed<ReportMessage[]>(() => {
  const out: ReportMessage[] = []
  for (const ex of exchanges.value) {
    if (ex.question) out.push({ role: 'user', content: ex.question, createdAt: isoOf(ex.askedAt) })
    const content =
      ex.response?.answer?.trim() || ex.error || (ex.cancelled ? t('generationStopped') : '') || ex.proposal?.summary || ''
    if (!content) continue
    out.push({
      role: 'assistant',
      content,
      createdAt: isoOf(ex.answeredAt),
      turnId: ex.turnId ?? null,
      sources: ex.sources?.length ? ex.sources : null,
    })
  }
  return out
})

function openReport(exchangeId?: string) {
  const ex = exchangeId ? exchanges.value.find((e) => e.id === exchangeId) : undefined
  reportTurnId.value = ex?.turnId ?? null
  reportKey = ex ? (ex.turnId ?? `ex:${ex.id}`) : null
  reportMounted.value = true
  reportOpen.value = true
}
function onReportSent(payload: { id: string; turnId: string | null }) {
  const key = payload.turnId ?? reportKey
  if (key) reportedKeys.value = new Set([...reportedKeys.value, key])
  else chatReported.value = true
}

// --- Ish stoli ilovasi ----------------------------------------------------------
const desktopOpen = ref(false)

// --- Xotira (Barno nimani eslab qolgan) - hisob menyusidan; kod birinchi ochilganda yuklanadi.
const memoryOpen = ref(false)
const memoryMounted = ref(false)
watch(memoryOpen, (on) => on && (memoryMounted.value = true))

// --- Toast'lar kompozer ustida chiqsin (VToastHost `--toast-offset` ni o'qiydi) --
const composerEl = ref<HTMLElement | null>(null)
let composerRo: ResizeObserver | null = null
function syncToastOffset() {
  const el = composerEl.value
  const root = document.documentElement
  if (!el || welcome.value) root.style.removeProperty('--toast-offset')
  else root.style.setProperty('--toast-offset', `${Math.round(el.offsetHeight) + 12}px`)
}
onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && composerEl.value) {
    composerRo = new ResizeObserver(syncToastOffset)
    composerRo.observe(composerEl.value)
  }
  syncToastOffset()
})
watch(welcome, syncToastOffset, { flush: 'post' })
onBeforeUnmount(() => {
  composerRo?.disconnect()
  document.documentElement.style.removeProperty('--toast-offset')
})
</script>

<template>
  <div class="chat">
    <ChatSidebar
      v-if="isDesktop"
      mode="inline"
      :collapsed="sidebarPanel.folded.value"
      :resize="sidebarPanel"
      :user="user"
      :theme="theme"
      :wake="wakeEnabled"
      :wake-supported="wakeSupported"
      :wake-distorted="wakeDistorted"
      :wake-blocked="wakeBlocked"
      :is-admin="isAdmin"
      @toggle-collapse="toggleCollapse"
      @new-chat="newChat"
      @open-chat="openHistory"
      @set-theme="setTheme"
      @toggle-wake="toggleWake"
      @open-desktop="desktopOpen = true"
      @open-memory="memoryOpen = true"
      @logout="onLogout"
    />
    <!-- <1120: chapdan chiquvchi drawer - fokus tuzog'i, parda, Esc; fon bosilmaydi. -->
    <VSheet
      v-else
      v-model:open="sidebarOpen"
      class="chat-drawer"
      side="left"
      :responsive="false"
      padding="none"
      hide-close
      :width="300"
      :aria-label="t('chat.navigation')"
    >
      <ChatSidebar
        mode="drawer"
        :user="user"
        :theme="theme"
        :wake="wakeEnabled"
        :wake-supported="wakeSupported"
        :wake-distorted="wakeDistorted"
        :wake-blocked="wakeBlocked"
        :is-admin="isAdmin"
        @new-chat="newChat"
        @open-chat="openHistory"
        @close="sidebarOpen = false"
        @set-theme="setTheme"
        @toggle-wake="toggleWake"
        @open-desktop="desktopOpen = true"
        @open-memory="memoryOpen = true"
        @logout="onLogout"
      />
    </VSheet>

    <main class="chat-main">
      <ChatTopBar
        :title="welcome ? '' : topTitle"
        :can-rename="!!activeSummary"
        :show-menu-button="!isDesktop"
        :has-chat="exchanges.length > 0"
        :can-report="hasReply"
        :reported="chatReported"
        :show-more="!isPhone"
        :scrolled="topScrolled"
        :mic-live="wakeSupported && wakeEnabled && wakeActive"
        :mic-distorted="wakeDistorted"
        @open-menu="sidebarOpen = true"
        @rename="onTopRename"
        @report="openReport()"
        @copy-chat="copyChat"
        @delete-chat="onTopDelete"
        @mic-off="wakeEnabled = false"
      />

      <div class="chat-stage" :class="{ 'is-welcome': welcome }">
        <!-- Eski suhbat olinmoqda yoki olinmadi: ikkalasi ham suhbat o'rnida (salomlashuv
             "yangi suhbat" degan bo'lardi). -->
        <div v-if="historyLoading" class="chat-state">
          <div class="chat-state__skeleton" aria-hidden="true">
            <VSkeleton width="46%" :height="40" radius="lg" class="chat-state__bubble" />
            <VSkeleton :lines="3" />
            <VSkeleton width="38%" :height="40" radius="lg" class="chat-state__bubble" />
            <VSkeleton :lines="2" />
          </div>
          <p class="sr-only" role="status">{{ t('historyLoading') }}</p>
        </div>
        <div v-else-if="historyError" class="chat-state is-error" role="alert">
          <p>{{ t('historyOpenFailed') }}</p>
          <p class="chat-state__detail">{{ historyError }}</p>
          <VButton size="sm" @click="retryOpenHistory">{{ t('retry') }}</VButton>
        </div>
        <Welcome v-else-if="exchanges.length === 0" :name="greetName" :actor-type="actorType" @chip="sendChip" />
        <Conversation
          v-else
          :exchanges="exchanges"
          :show-engine="engines.selectable.value"
          :busy="phase !== 'idle'"
          :streaming-id="streamingId"
          :reported-keys="reportedKeys"
          :can-trace="canTrace"
          :chat-key="chatKey"
          @regenerate="regenerate"
          @report="openReport"
          @scrolled="topScrolled = $event"
        />
        <!-- Yozish maydoni DOIM shu joyda (salomlashuvda ham) - yuborilganda qayta
             yaratilmaydi, fokus saqlanadi; salomlashuvda CSS uni markazga qo'yadi. -->
        <div ref="composerEl" class="chat-composer">
          <InputDock ref="dock" :phase="phase" :send="send" :stop="stop" @dictating="dictating = $event" @live="voiceOpen = true" />
        </div>
      </div>

      <VoicePanel
        :hold="holdCue"
        :open="voiceOpen"
        :send="send"
        :busy="phase !== 'idle'"
        :answer="lastAnswer"
        :answer-sources="lastSources"
        :answer-turn="lastTurn"
        :greeting="t('voiceGreeting')"
        @close="closeVoice"
      />
    </main>

    <!-- Iqtibos qilingan hujjat: chatning YONIDA, ustida emas - odam javobni va
         manbani birga ko'rsin (kichik ekranda butun ekran). -->
    <DocViewer v-if="viewerDoc" :doc="viewerDoc" @close="closeViewer" />

    <ReportDialog
      v-if="reportMounted"
      v-model:open="reportOpen"
      :chat-id="exchanges.length ? chatKey : null"
      :turn-id="reportTurnId"
      :messages="reportMessages"
      @sent="onReportSent"
    />

    <MemoryDialog v-if="memoryMounted" v-model:open="memoryOpen" />

    <!-- Sarlavha DesktopDownload'ning o'zida - dialogda takrorlanmaydi. -->
    <VDialog v-model:open="desktopOpen" size="md" :aria-label="t('chat.desktopApp')">
      <DesktopDownload />
    </VDialog>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  height: 100vh;
  height: 100dvh;
  /* viewport-fit=cover: yon "chiqiq" (landshaft iPhone) va ilova rejimidagi yuqori
     panel ostiga kontent kirmasin. Pastki chet - kompozerning o'zida. */
  padding: env(safe-area-inset-top, 0px) env(safe-area-inset-right, 0px) 0 env(safe-area-inset-left, 0px);
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
}
.chat-main {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}
.chat-stage {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}
/* Salomlashuv: uchqun + salom, maydon, takliflar - optik markazda (biroz yuqorida). */
.chat-stage.is-welcome {
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  padding: var(--s-6) 0 max(8vh, var(--s-12));
}
.chat-composer {
  order: 2;
  position: relative;
  flex-shrink: 0;
  width: 100%;
  max-width: calc(var(--chat-col) + 2 * var(--gutter));
  margin: 0 auto;
  padding: 0 var(--gutter) max(var(--s-3), env(safe-area-inset-bottom, 0px));
}
.chat-stage.is-welcome .chat-composer {
  padding-bottom: 0;
}

.chat-state {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  max-width: calc(var(--chat-col) + 2 * var(--gutter));
  margin: 0 auto;
  padding: var(--s-6) var(--gutter);
}
.chat-state__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
}
.chat-state__skeleton :deep(.chat-state__bubble) {
  align-self: flex-end;
}
.chat-state.is-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  text-align: center;
  color: var(--text);
  font-size: var(--fs-body);
}
.chat-state__detail {
  margin-bottom: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}
</style>
