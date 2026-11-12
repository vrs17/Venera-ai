// Mini App suhbat dvigateli: savol -> oqim -> javob, suhbatlar tarixi.
//
// MANTIQ web ilovaning `views/ChatView.vue` dagisi bilan BIR XIL (u jonli sinalgan):
// kadrlar tartibi, xato kadri tokenlardan keyin kelsa javob saqlanishi, "Pro" rejimi
// shu yerda qotirilishi, manbalar keshi, 404 da yangi suhbat. Farqi - faqat ekran
// qismi yo'q (yon panel, ovozli panel, dasturchi rejimi) va 401 da sessiya Telegram
// orqali jim tiklanadi (useTgSession.expire).
//
// Kanal sarlavhasi (`miniapp`) main.ts da `setClientChannel` bilan qo'yiladi - bu
// yerdagi so'rovlar umumiy `chat.api.ts` / `chats.api.ts` orqali ketadi va uni o'qiydi.

import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { streamAsk } from '../../api/chat.api'
import { openChat as fetchChat } from '../../api/chats.api'
import { localizeApiError } from '../../api/errors'
import { ApiError } from '../../api/http'
import { provisionalTitle, useChats } from '../../composables/useChats'
import { hasPro } from '../../composables/useEngines'
import { usePro } from '../../composables/usePro'
import { recallSources, rememberSources } from '../../sourcesCache'
import { isoToMs } from '../../time'
import type { ActionProposal, ChatFrame, ChatMessage, PipelineResponse, ProInfo } from '../../types'
import type { ChatExchange } from '../../components/chat/types'
import type { ReportMessage } from '../../features/report/report.api'
import { useTgSession } from '../useTgSession'

/** Mini App'ning savol-javobi: umumiy `ChatExchange` + xato KODI. Kod bo'yicha karta
 *  boshqa yo'l taklif qiladi: `auth_missing`/`auth_expired` da "Qayta urinish" foyda
 *  bermaydi (token yo'q) - "Veb ilovani ochish": ulanish o'sha yerda tiklanadi. */
export type TgExchange = ChatExchange & { errorCode?: string | null }

/** HRM/CRM tokeni yo'q yoki eskirgan - ulanishni veb ilovada tiklash kerak. */
export function isAuthCode(code: string | null | undefined): boolean {
  return code === 'auth_missing' || code === 'auth_expired'
}

/** crypto.randomUUID faqat xavfsiz kontekstda (HTTPS) bor - LAN'dagi HTTP da yo'q. */
export function randomId(prefix: string): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** Matnli javobni natija view'i taniydigan shaklga o'raydi (ChatView bilan bir xil). */
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

export function useTgChat() {
  const { t, locale } = useI18n({ useScope: 'global' })
  const chats = useChats()
  const pro = usePro()
  const session = useTgSession()

  const exchanges = ref<TgExchange[]>([])
  const phase = ref<'idle' | 'sending'>('idle')
  const streamingId = ref<string | null>(null)
  const historyLoading = ref(false)
  const historyError = ref<string | null>(null)
  let historyRequest = 0
  let controller: AbortController | null = null

  // Bitta suhbat - bitta kalit: yordamchi xotirasi (user_id, chat_id) bo'yicha, ya'ni
  // "va o'tgan oyda?" kabi davomli savollar shu kalit o'zgarmaguncha ishlaydi.
  let chatId = randomId('c')
  chats.select(chatId)
  const chatKey = ref(chatId)

  function patch(id: string, p: Partial<TgExchange>) {
    exchanges.value = exchanges.value.map((e) => (e.id === id ? { ...e, ...p } : e))
  }

  /** Xizmatning O'Z matni yutadi - BITTA istisno: token yo'qligi. Xizmat u yerda
   *  "«+» menyusidan ulang" deydi, Mini App'da esa «+» yo'q, yo'l ham tizimga qarab har xil:
   *    HRM - veb ilovada qo'lda ulanadi («+» -> Ulanishlar);
   *    CRM - odam ulamaydi: vebda BRB-Tech ID bilan kirilganda o'zi ulanadi (ro'yxatda
   *          CRM qatori yo'q, shuning uchun unga «+» ni ko'rsatish odamni adashtirardi).
   *  Qaysi tizim - xizmat matnidan: faqat CRM tilga olingan bo'lsa CRM, aks holda HRM. */
  function errorText(frame: ChatFrame): string {
    const own = frame.text?.trim() ?? ''
    if (isAuthCode(frame.code)) {
      // So'z chegarasisiz: o'zbekcha qo'shimcha bilan ham topilsin ("CRMga", "CRMni").
      // 2026-11-12 dan HRM ham CRM kabi: BRB-Tech ID bilan kirilganda o'zi ulanadi.
      const crm = /CRM/i.test(own)
      const hrm = /HRM/i.test(own)
      return t('tg.chat.notConnected', { system: crm && hrm ? 'HRM / CRM' : crm ? 'CRM' : 'HRM' })
    }
    return own || t('chatFailed')
  }

  function fail(err: unknown): string {
    // Sessiya serverda bekor qilingan - Telegram orqali jim tiklash yoki kirish ekrani.
    if (err instanceof ApiError && err.status === 401) void session.expire(err)
    return localizeApiError(err, t)
  }

  function newChat() {
    controller?.abort()
    controller = null
    historyRequest++
    historyLoading.value = false
    historyError.value = null
    exchanges.value = []
    streamingId.value = null
    phase.value = 'idle'
    chatId = randomId('c')
    chatKey.value = chatId
    chats.select(chatId)
  }

  /** Tarixdan ochish. Keyingi savol o'sha kalit bilan ketadi - suhbat davom etadi. */
  async function openHistory(id: string, force = false) {
    if (!force && id === chatId && !historyLoading.value && !historyError.value) return
    controller?.abort()
    controller = null
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
        // Boshqa qurilmada o'chirilgan: eski kalit bilan savol berish uni tiriltirardi.
        chats.forget(id)
        newChat()
        return
      }
      historyError.value = fail(err)
    } finally {
      if (request === historyRequest) historyLoading.value = false
    }
  }

  function exchangesFrom(messages: ChatMessage[], chat: string): TgExchange[] {
    const out: TgExchange[] = []
    let current: TgExchange | null = null
    for (const message of messages) {
      const content = message.content ?? ''
      if (message.role === 'assistant') {
        // Server xabar bo'yicha manba saqlamaydi - shu brauzerda eslab qolingan bo'lishi mumkin.
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

  function stop() {
    if (phase.value !== 'sending') return
    controller?.abort()
    controller = null
    const inflight = exchanges.value.find((e) => !e.response && !e.error && !e.cancelled)
    if (inflight) patch(inflight.id, { cancelled: true })
    else if (streamingId.value) patch(streamingId.value, { stopped: true })
    streamingId.value = null
    phase.value = 'idle'
  }

  function run(id: string, question: string, mode: 'standard' | 'pro') {
    phase.value = 'sending'
    streamingId.value = id
    const t0 = performance.now()
    const mine = new AbortController()
    controller = mine
    const turnChat = chatId
    let answer = ''
    let failure: string | null = null
    let failureCode: string | null = null
    let proposed = false

    const onFrame = (frame: ChatFrame) => {
      if (mine.signal.aborted) return
      switch (frame.type) {
        case 'stage':
          patch(id, { stage: frame.text?.trim() || frame.stage || null })
          break
        case 'sources':
          patch(id, { sources: frame.sources ?? frame.items ?? [] })
          break
        case 'artifact': {
          const { type: _type, ...inline } = frame
          patch(id, { artifact: frame.artifact ?? inline })
          break
        }
        case 'proposal': {
          const { type: _type, ...inline } = frame
          const proposal = (frame.proposal ?? inline) as ActionProposal
          if (proposal.token) {
            patch(id, { proposal })
            proposed = true
          }
          break
        }
        case 'token':
          answer += frame.text ?? ''
          patch(id, { response: streamedResponse(answer), stage: null, error: null })
          break
        case 'error':
          failure = errorText(frame)
          failureCode = frame.code ?? null
          if (frame.request_id) patch(id, { requestId: frame.request_id })
          break
        case 'done':
          patch(id, {
            route: frame.route ?? null,
            stage: null,
            ...(frame.request_id ? { requestId: frame.request_id } : {}),
            ...(frame.engine ? { engine: String(frame.engine) } : {}),
          })
          if (frame.pro) {
            patch(id, { pro: frame.pro })
            pro.noteAnswer(frame.pro)
          } else if (mode === 'pro' && !hasPro(frame.engine)) {
            // "Pro" so'raldi, lekin backend uni "Pro"siz dvigatelga yubormadi:
            // jim qolsak odam "Pro ishladi" deb o'ylaydi (ChatView bilan bir xil).
            const denied: ProInfo = { requested: true, used: false, calls: 0, reason: 'engine' }
            patch(id, { pro: denied })
            pro.noteAnswer(denied)
          }
          break
        default:
          break
      }
    }

    streamAsk(question, onFrame, {
      chatId,
      mode,
      signal: mine.signal,
      locale: String(locale.value),
      onTurn: (turnId) => {
        if (!mine.signal.aborted) patch(id, { turnId })
      },
    })
      .then(() => {
        const durationMs = performance.now() - t0
        if (streamingId.value === id && !mine.signal.aborted) streamingId.value = null
        if (failure && !answer) {
          patch(id, { error: failure, errorCode: failureCode, stage: null, durationMs, answeredAt: Date.now() })
        } else {
          // Qisman javobdan keyingi xato - IZOH: kelgan qism baribir o'qishga arziydi.
          patch(id, { response: streamedResponse(answer), warning: failure, error: null, stage: null, durationMs, answeredAt: Date.now() })
          if (answer || proposed) chats.noteTurn(turnChat, question)
          const done = exchanges.value.find((e) => e.id === id)
          if (answer && done) rememberSources(turnChat, answer, done.sources ?? [], done.artifact)
        }
        if (controller === mine) controller = null
        phase.value = 'idle'
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (streamingId.value === id) streamingId.value = null
        patch(id, { error: fail(err), stage: null, durationMs: performance.now() - t0, answeredAt: Date.now() })
        if (controller === mine) controller = null
        phase.value = 'idle'
      })
  }

  function send(text: string): boolean {
    const trimmed = text.trim()
    if (!trimmed || phase.value !== 'idle') return false
    const id = randomId('ex')
    // Rejim SHU YERDA qotiriladi: javob kelguncha Pro bosilsa ham bu tur o'z rejimida.
    const mode = pro.active.value ? 'pro' : 'standard'
    exchanges.value = [
      ...exchanges.value,
      { id, question: trimmed, response: null, error: null, durationMs: null, stage: null, askedAt: Date.now(), proRequested: mode === 'pro' },
    ]
    run(id, trimmed, mode)
    return true
  }

  function regenerate(id: string) {
    if (phase.value !== 'idle') return
    const ex = exchanges.value.find((e) => e.id === id)
    if (!ex) return
    patch(id, {
      response: null, error: null, errorCode: null, cancelled: false, stopped: false, durationMs: null, stage: null,
      sources: [], artifact: null, proposal: null, warning: null, route: null, answeredAt: null,
      turnId: null, requestId: null, pro: null, engine: null,
    })
    run(id, ex.question, ex.proRequested && pro.available.value ? 'pro' : 'standard')
  }

  function abort() {
    controller?.abort()
    controller = null
  }

  const activeSummary = computed(() => chats.chats.value.find((c) => c.chat_id === chats.activeId.value) ?? null)
  const title = computed(() => {
    if (activeSummary.value) return activeSummary.value.title
    const first = exchanges.value.find((e) => e.question)?.question
    return first ? provisionalTitle(first) : ''
  })

  function isoOf(ms: number | null | undefined): string | null {
    return ms ? new Date(ms).toISOString() : null
  }
  /** "Xabar berish" uchun suhbat nusxasi - brauzer holatidan. */
  const reportMessages = computed<ReportMessage[]>(() => {
    const out: ReportMessage[] = []
    for (const ex of exchanges.value) {
      if (ex.question) out.push({ role: 'user', content: ex.question, createdAt: isoOf(ex.askedAt) })
      const content =
        ex.response?.answer?.trim() || ex.error || (ex.cancelled ? t('generationStopped') : '') || ex.proposal?.summary || ''
      if (!content) continue
      out.push({ role: 'assistant', content, createdAt: isoOf(ex.answeredAt), turnId: ex.turnId ?? null, sources: ex.sources?.length ? ex.sources : null })
    }
    return out
  })

  return {
    exchanges,
    phase,
    streamingId,
    historyLoading,
    historyError,
    chatKey,
    title,
    reportMessages,
    currentChatId: () => chatId,
    send,
    stop,
    regenerate,
    newChat,
    openHistory,
    abort,
  }
}
