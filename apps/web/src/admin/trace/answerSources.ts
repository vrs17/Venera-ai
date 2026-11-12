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
import { PLATFORM_IDS } from '../../components/chat/platforms'
import type { AnswerSource } from '../../types'
import type { TurnSource } from '../types'

// ESKI IZLAR (2026-11-12). Namoyish manbalari mahsulotdan olib tashlandi va umumiy
// ro'yxatda (`chat/platforms.ts`) endi yo'q, lekin jurnalda ularning savollari qoldi.
// Admin o'sha izlarni avvalgidek o'qishi uchun turlari FAQAT shu yerda: jonlilari - vosita
// chaqiruvi, qo'llanmalari - tashqi sahifa. Yangi izlarda bu turlar uchramaydi.
const RETIRED_LIVE_KINDS = ['dwh', 'biznes247', 'superapp']
const RETIRED_GUIDE_KINDS = ['biznes247_kb', 'biznes247_help']
const GUIDE_KINDS: ReadonlySet<string> = new Set(RETIRED_GUIDE_KINDS)
/** Chip turi bo'la oladigan platformalar (hozirgi va eski). */
const TOOL_PLATFORMS: readonly string[] = [...PLATFORM_IDS, ...RETIRED_LIVE_KINDS, ...RETIRED_GUIDE_KINDS]

export function isLawSource(kind: string | null | undefined): boolean {
  return String(kind ?? '').toLowerCase() === 'law'
}

/** Qo'llanma maqolasi (eski izlarda) - qonun kabi tashqi sahifa: `docUrl` yo'q, "Hujjatni
 *  ochish" emas - havola (faqat https). */
export function isGuideKind(kind: string | null | undefined): boolean {
  return GUIDE_KINDS.has(String(kind ?? '').toLowerCase())
}

/** Tashqi sahifa (qonun yoki qo'llanma) - ko'ruvchida ochilmaydi. */
export function isExternalSource(kind: string | null | undefined): boolean {
  return isLawSource(kind) || isGuideKind(kind)
}

/** Savol izidagi qonun manbasining havolasi (faqat https) yoki `null`. */
export function turnLawUrl(s: TurnSource): string | null {
  return safeHttps(s.ref)
}

/** Hujjat emas, platforma chaqiruvi (HRM/CRM/boshqa vosita). Eski izlardagi jonli manbalar
 *  ham - aks holda ular hujjat bo'lib, mavjud bo'lmagan faylga "Hujjatni ochish" tugmasi
 *  chiqardi. */
const TOOL_KINDS = new Set<string>([...PLATFORM_IDS, ...RETIRED_LIVE_KINDS, 'tool'])

export function isToolSource(kind: string | null | undefined): boolean {
  return TOOL_KINDS.has(String(kind ?? '').toLowerCase())
}

export function docUrl(docId: string | null | undefined, page?: number | null): string | null {
  if (!docId) return null
  const base = `/api/v1/chat/doc/${encodeURIComponent(docId)}`
  return page && page > 0 ? `${base}#page=${page}` : base
}

/** Vosita nomidan platforma (`hrm_today_late` -> `hrm`) - chip turi va belgisi shunga
 *  qarab. Eng uzun mos prefiks; topilmasa - `hrm` (avvalgidek). */
function toolKind(kind: string | null | undefined, tool: string | null | undefined): string {
  const k = String(kind ?? '').toLowerCase()
  if (TOOL_PLATFORMS.includes(k)) return k
  const name = String(tool ?? '').toLowerCase()
  let best = ''
  for (const id of TOOL_PLATFORMS) if (name.startsWith(id) && id.length > best.length) best = id
  return best || 'hrm'
}

export function fromTurnSource(s: TurnSource): AnswerSource {
  if (isGuideKind(s.kind) && s.citation != null) {
    return {
      kind: String(s.kind).toLowerCase(),
      title: s.title ?? undefined,
      citation_index: s.citation,
      url: turnLawUrl(s),
      doc_id: null,
      page: null,
    }
  }
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
  const cite = int(o.citation_index) ?? int(o.citation)
  if (isGuideKind(kind) && cite != null) {
    return {
      kind: String(kind).toLowerCase(),
      title: str(o.title),
      citation_index: cite,
      url: safeHttps(o.url) ?? safeHttps(o.ref),
      doc_id: null,
      page: null,
    }
  }
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
