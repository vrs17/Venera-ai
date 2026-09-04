// Chat endpoint wrapper. POST /api/v1/chat/ask runs the full pipeline AND
// produces the answer. Identity comes from the Bearer token (attached by
// apiFetch) — the request body carries only the question.

import { apiFetch } from './http'
import type { PipelineResponse, RetrievalStage } from '../types'

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
