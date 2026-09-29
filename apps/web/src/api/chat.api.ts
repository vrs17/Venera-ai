// Chat endpoints.
//
//   streamAsk()  POST /api/v1/chat/stream  — the real answer, streamed
//   askAi()      POST /api/v1/chat/ask     — the pipeline skeleton, one JSON
//
// Identity comes from the Bearer token in both cases; the body never carries
// a user id. The streaming route is the one people use — the skeleton stays
// so the trace view still works where the assistant is not configured.
//
// WHY NOT EventSource. It is GET-only and cannot send an Authorization
// header, so the question would have to go in the query string and the
// session token with it — into proxy logs and browser history. fetch() with a
// ReadableStream reads the same kind of stream over POST, with the token in a
// header where it belongs.

import { ApiError, apiFetch, BASE_URL, getToken } from './http'
import type { ApiErrorResponse, ChatFrame, PipelineResponse, RetrievalStage } from '../types'

// `/ask` nests the router trace under `pipeline.*` and ships `chunks` instead of
// `results`. Flatten + rename into the UI's PipelineResponse shape so the trace
// view keeps working, and surface the top-level domain/answer.
function normalizeAskResponse(raw: Record<string, unknown>): PipelineResponse {
  const wrapper = (raw.pipeline ?? raw) as Record<string, unknown>
  const rawRetrieval = wrapper.retrieval as Record<string, unknown> | null | undefined
  let retrieval: RetrievalStage | null = null
  if (rawRetrieval) {
    const chunks = (rawRetrieval.chunks ?? rawRetrieval.results ?? []) as RetrievalStage['results']
    const status = rawRetrieval.retrievalStatus as string | undefined
    const message = rawRetrieval.message as string | undefined
    retrieval = {
      status,
      collection: rawRetrieval.collection as string | undefined,
      results: chunks,
      seconds: rawRetrieval.seconds as number | undefined,
      error: status && status !== 'OK' ? message || status : ((rawRetrieval.error as string | null | undefined) ?? null),
    }
  }
  return {
    finalStatus: (raw.finalStatus ?? wrapper.finalStatus) as PipelineResponse['finalStatus'],
    domain: (raw.domain ?? null) as PipelineResponse['domain'],
    domainReason: (raw.domainReason ?? null) as PipelineResponse['domainReason'],
    guard: (wrapper.guard ?? null) as PipelineResponse['guard'],
    intent: (wrapper.intent ?? null) as PipelineResponse['intent'],
    orchestrator: (wrapper.orchestrator ?? null) as PipelineResponse['orchestrator'],
    access: (wrapper.access ?? null) as PipelineResponse['access'],
    retrieval,
    answer: (raw.answer ?? null) as string | null,
  }
}

export async function askAi(question: string, signal?: AbortSignal): Promise<PipelineResponse> {
  const raw = await apiFetch<Record<string, unknown>>('/api/v1/chat/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
    signal,
  })
  return normalizeAskResponse(raw)
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
  /** Conversation key. Turns sharing it share the assistant's server-side
   *  memory, so follow-up questions ("va o'tgan oyda?") work. */
  chatId?: string | null
  signal?: AbortSignal
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
): Promise<void> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}/api/v1/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'application/x-ndjson',
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
    }),
    signal: options.signal,
  })

  if (!response.ok) {
    // The error envelope is JSON even here, so the same ApiError the rest of
    // the app throws comes out of this path too and localizeApiError works.
    let body: ApiErrorResponse | undefined
    try {
      body = (await response.json()) as ApiErrorResponse
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(body?.message || `Request failed (${response.status})`, body)
  }
  if (!response.body) throw new ApiError('Streaming unsupported')

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
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), Accept: '*/*' },
  })
  if (!response.ok) {
    let body: ApiErrorResponse | undefined
    try {
      body = (await response.json()) as ApiErrorResponse
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(body?.message || `Download failed (${response.status})`, body)
  }
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
