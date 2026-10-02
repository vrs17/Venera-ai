// Admin tomonidagi manbalar -> chatdagi `AnswerSource` shakli.
//
// Javob matnini chat bilan AYNAN bir xil chizish uchun (`MarkdownMessage`: `[1]` va `[T1]`
// chiplari) manbalar chat kutgan shaklda bo'lishi kerak. Admin API esa ularni o'z
// shaklida beradi: savol izida `TurnSource` (`ref`, `citation`), xabar nusxasida -
// jurnaldan (`ref`, `citation`) yoki brauzerdan (`doc_id`, `citation_index`, `marker`)
// kelgan aralash lug'at. Shu yerda bittaga keltiriladi.
//
// `docUrl` - backend chatda qo'shadigan yo'lning o'zi (`/api/v1/chat/doc/<id>#page=n`):
// chip bosilganda hujjat ko'ruvchisi aynan shu yo'l bilan ochiladi.
//
// QONUN MODDASI (`kind: "law"`, v2): hujjat emas - `docUrl` YO'Q, chip LEX.UZ ga havola.
// Jurnal unda `doc_id` va `tool` bo'lmagani uchun manzilni `ref` ga yozadi; brauzer
// nusxasida esa `url` maydoni bor. Ikkalasi ham faqat `https://` bo'lsa havola bo'ladi.

import { safeHttps } from '../../components/chat/sources'
import type { AnswerSource } from '../../types'
import type { TurnSource } from '../types'

export function isLawSource(kind: string | null | undefined): boolean {
  return String(kind ?? '').toLowerCase() === 'law'
}

/** Savol izidagi qonun manbasining havolasi (faqat https) yoki `null`. */
export function turnLawUrl(s: TurnSource): string | null {
  return safeHttps(s.ref)
}

/** Hujjat emas, platforma chaqiruvi (HRM/CRM/boshqa vosita). */
const TOOL_KINDS = new Set(['hrm', 'crm', 'tool'])

export function isToolSource(kind: string | null | undefined): boolean {
  return TOOL_KINDS.has(String(kind ?? '').toLowerCase())
}

export function docUrl(docId: string | null | undefined, page?: number | null): string | null {
  if (!docId) return null
  const base = `/api/v1/chat/doc/${encodeURIComponent(docId)}`
  return page && page > 0 ? `${base}#page=${page}` : base
}

/** Vosita nomidan platforma (`hrm_today_late` -> `hrm`) - chip turi shunga qarab. */
function toolKind(kind: string | null | undefined, tool: string | null | undefined): 'hrm' | 'crm' {
  const k = String(kind ?? '').toLowerCase()
  if (k === 'hrm' || k === 'crm') return k
  return String(tool ?? '').toLowerCase().startsWith('crm') ? 'crm' : 'hrm'
}

export function fromTurnSource(s: TurnSource): AnswerSource {
  if (isLawSource(s.kind)) {
    return {
      kind: 'law',
      title: s.title ?? undefined,
      citation_index: s.citation ?? undefined,
      url: turnLawUrl(s),
      doc_id: null,
      page: null,
    }
  }
  if (isToolSource(s.kind)) {
    return {
      kind: toolKind(s.kind, s.ref),
      tool: s.ref ?? undefined,
      status: s.status ?? undefined,
      digest: s.digest ?? undefined,
      marker: s.citation != null ? `T${s.citation}` : undefined,
    }
  }
  return {
    kind: 'doc',
    doc_id: s.ref ?? undefined,
    title: s.title ?? undefined,
    page: s.page ?? undefined,
    citation_index: s.citation ?? undefined,
    docUrl: docUrl(s.ref, s.page),
  }
}

const str = (v: unknown): string | undefined => (typeof v === 'string' && v.trim() ? v : undefined)
const int = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)

/** Nusxadagi bitta manba (jurnaldan yoki brauzerdan) - noma'lum shakl jim tashlanadi. */
export function fromSnapshotSource(raw: unknown): AnswerSource | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const kind = str(o.kind)
  if (isLawSource(kind)) {
    return {
      kind: 'law',
      title: str(o.title),
      citation_index: int(o.citation_index) ?? int(o.citation),
      url: safeHttps(o.url) ?? safeHttps(o.ref),
      doc_id: null,
      page: null,
    }
  }
  const tool = str(o.tool) ?? (isToolSource(kind) ? str(o.ref) : undefined)
  if (tool || isToolSource(kind)) {
    const n = int(o.citation)
    return {
      kind: toolKind(kind, tool),
      tool,
      status: str(o.status),
      digest: str(o.digest),
      marker: str(o.marker) ?? (n != null ? `T${n}` : undefined),
    }
  }
  const docId = str(o.doc_id) ?? str(o.documentId) ?? str(o.ref)
  const page = int(o.page)
  return {
    kind: 'doc',
    doc_id: docId,
    title: str(o.title) ?? str(o.documentTitle),
    page,
    citation_index: int(o.citation_index) ?? int(o.citation),
    docUrl: docUrl(docId, page),
  }
}

export function fromSnapshotSources(list: unknown[] | null | undefined): AnswerSource[] {
  return (list ?? []).map(fromSnapshotSource).filter((s): s is AnswerSource => s !== null)
}
