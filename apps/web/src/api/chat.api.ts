// Chat endpoints.
//
//   streamAsk()  POST /api/v1/chat/stream  — the real answer, streamed
//
// Identity comes from the Bearer token; the body never carries a user id.
//
// `/chat/ask` (bir martalik JSON, pipeline izi) endi brauzerdan chaqirilmaydi:
// uni faqat "dasturchi rejimi" ishlatardi, rejim olib tashlandi - savolning to'liq
// izi admin panelida. Backend yo'li o'z joyida (boshqa klientlar, testlar).
//
// WHY NOT EventSource. It is GET-only and cannot send an Authorization
// header, so the question would have to go in the query string and the
// session token with it — into proxy logs and browser history. fetch() with a
// ReadableStream reads the same kind of stream over POST, with the token in a
// header where it belongs.

import { ApiError, BASE_URL, CLIENT_HEADER, clientChannel, getToken } from './http'
import type { ApiErrorResponse, ChatFrame } from '../types'

/* Kanal sarlavhasi (`X-Venera-Client`) - http.ts dagi `clientChannel()`: web'da
   "web", Telegram Mini App'da "miniapp". Bu fayldagi to'g'ridan-to'g'ri fetch'lar ham
   yubormasa, so'rov admin panelda "API" bo'lib ko'rinardi va dvigatel noto'g'ri
   tanlanardi. */
/** Javob sarlavhasi: backend shu savolga bergan kalit (`turns.id`). */
const TURN_HEADER = 'X-Venera-Turn'

function turnOf(response: Response): string | null {
  return response.headers.get(TURN_HEADER)?.trim() || null
}

/** Xato konverti (JSON) -> ApiError; tana JSON bo'lmasa - holat kodi bilan. */
async function errorOf(response: Response, fallback: string): Promise<ApiError> {
  let body: ApiErrorResponse | undefined
  try {
    body = (await response.json()) as ApiErrorResponse
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(body?.message || `${fallback} (${response.status})`, body)
}


/** Frames arrive in this order: stage… sources, artifact?, token…, done.
 *  On failure an `error` frame comes instead of the tokens, then `done`. */
export interface StreamOptions {
  /** "Pro" - SHU xabar uchun. Default `standard`: u pulga tushadi va
   *  odamning byudjetidan yeydi, shuning uchun hech qachon o'z-o'zidan
   *  yuborilmaydi. Javob `done` kadrida `pro` bloki bilan qaytadi. */
  mode?: 'standard' | 'pro'
  /** True while the voice panel is open, so the backend may send holding
   *  phrases to fill the wait. Left out entirely in text mode. */
  voice?: boolean
  /** UI locale — the holding phrase comes back in this language. */
  locale?: string
  /** Yordamchi versiyasi (`v1` | `v2`) - FAQAT odamga tanlov berilgan bo'lsa
   *  (`GET /chat/engines` -> `selectable`). Server uni ruxsat etilganlar ichida
   *  bo'lsagina qabul qiladi, aks holda jimgina o'z default'ini ishlatadi.
   *  Berilmasa - maydon umuman yuborilmaydi (eski xatti-harakat, Mini App ham shu). */
  engine?: string | null
  /** Conversation key. Turns sharing it share the assistant's server-side
   *  memory, so follow-up questions ("va o'tgan oyda?") work. */
  chatId?: string | null
  signal?: AbortSignal
  /** Sarlavhalar kelishi bilan (birinchi kadrdan OLDIN): backend bergan savol
   *  kaliti. Javob tugamasdan "Xabar berish" ham shu kalitni bilsin. */
  onTurn?: (turnId: string) => void
}

/** `streamAsk` natijasi: backend bergan savol kaliti (sarlavha bo'lmasa null). */
export interface StreamResult {
  turnId: string | null
}

/**
 * Sends a question and calls `onFrame` for every NDJSON line that comes back.
 *
 * Resolves when the stream ends. Rejects on a transport or HTTP error — but
 * NOT on an `error` frame: that is a normal outcome of a completed request
 * (the assistant answered "I cannot"), and the caller decides how to show it.
 */
export async function streamAsk(
  question: string,
  onFrame: (frame: ChatFrame) => void,
  options: StreamOptions = {},
): Promise<StreamResult> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}/api/v1/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'application/x-ndjson',
      [CLIENT_HEADER]: clientChannel(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      question,
      // `standard` YUBORILMAYDI - u serverning o'z default'i.
      mode: options.mode === 'pro' ? 'pro' : undefined,
      chatId: options.chatId ?? undefined,
      // VOICE MODE IS DECLARED BY THE CLIENT, and it has to be: the server
      // cannot know whether anyone is listening. Holding phrases (`hold`
      // frames) are only sent when it is true — in a text chat the wait is
      // already visible, so "One moment, checking" would be pure noise.
      voice: options.voice ?? undefined,
      locale: options.locale ?? undefined,
      engine: options.engine || undefined,
    }),
    signal: options.signal,
  })

  // The error envelope is JSON even here, so the same ApiError the rest of
  // the app throws comes out of this path too and localizeApiError works.
  if (!response.ok) throw await errorOf(response, 'Request failed')
  if (!response.body) throw new ApiError('Streaming unsupported')

  const turnId = turnOf(response)
  if (turnId) options.onTurn?.(turnId)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      // `stream: true` matters: a multi-byte character can straddle two
      // chunks, and decoding each chunk independently would split it.
      if (value) buffer += decoder.decode(value, { stream: true })
      let cut = buffer.indexOf('\n')
      while (cut >= 0) {
        emit(buffer.slice(0, cut), onFrame)
        buffer = buffer.slice(cut + 1)
        cut = buffer.indexOf('\n')
      }
      if (done) break
    }
    // A last frame with no trailing newline is still a frame.
    emit(buffer + decoder.decode(), onFrame)
  } finally {
    // Abort mid-answer: release the connection instead of leaving it to the
    // garbage collector, which would hold a slot on the assistant's queue.
    void reader.cancel().catch(() => {})
  }
  return { turnId }
}

function emit(line: string, onFrame: (frame: ChatFrame) => void): void {
  const text = line.trim()
  if (!text) return
  let frame: ChatFrame
  try {
    frame = JSON.parse(text) as ChatFrame
  } catch {
    // The backend already drops malformed frames; if one still gets here,
    // dropping it beats tearing down an answer that is otherwise fine.
    console.debug('[chat] kadr JSON emas', text.slice(0, 120))
    return
  }
  if (frame && typeof frame.type === 'string') onFrame(frame)
}


/**
 * Fetches a chat file (the generated application, or a cited document) and
 * hands it to the browser as a download.
 *
 * WHY NOT A PLAIN <a href>. Both paths sit behind the session, and a link
 * cannot send an Authorization header — the browser would get a 401 and show
 * the error envelope as a broken page. Putting the token in the query string
 * instead would leak it into proxy logs and browser history, which is the
 * same reason the stream is a POST.
 *
 * WHY A DOWNLOAD AND NOT A VIEWER. Rendering the PDF in place would need a
 * blob: document, and this app runs under `script-src 'self'` with no blob:
 * allowance — the viewer would be blocked silently, in production only. A
 * download works in every browser with nothing to configure.
 */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}${url}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), Accept: '*/*', [CLIENT_HEADER]: clientChannel() },
  })
  if (!response.ok) throw await errorOf(response, 'Download failed')
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filename
    // Firefox needs the element in the document for a programmatic click.
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    // Not immediately: revoking before the browser has started reading the
    // blob cancels the download. One tick is enough and the URL cannot leak
    // for longer than that.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000)
  }
}
