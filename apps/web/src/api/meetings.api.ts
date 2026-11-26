// Yig'ilish sahifasi (`/meeting/:id`, `views/MeetingView.vue`) - faqat O'QISH so'rovlari.
// Server: `apps/api/app/api/v1/meetings.py` (odamning O'Z yig'ilishi; begonasi ham, yo'g'i ham bir xil 404).
// Turlar - `app/schemas/meetings.py` ning sahifa ishlatadigan qismi. Xulosa va bayonnoma Markdown
// eksportidan olinadi - Barno konnektori (Claude / ChatGPT) ko'rsatadigan matn bilan bir xil.

import { apiFetch, apiText } from './http'

export type MeetingStatus =
  | 'uploading'
  | 'uploaded'
  | 'transcribing'
  | 'summarizing'
  | 'ready'
  | 'failed'
  | 'waiting_quota'

export interface MeetingSpeaker {
  id: string
  name: string | null
  suggestedName: string | null
  talkSec: number
  mergedInto: string | null
  personId: number | null
}

export interface Meeting {
  id: string
  title: string
  status: MeetingStatus
  /** Yig'ilish tili - ismsiz spiker yorlig'i shu tilda (xulosa eksporti bilan bir xil). */
  language: 'uz' | 'ru' | 'en'
  recordedAt: string
  durationSec: number | null
  transcript: { available: boolean; segmentCount: number }
  speakers: MeetingSpeaker[]
  summaryStatus: 'none' | 'queued' | 'running' | 'ready' | 'failed' | 'skipped'
  primarySummaryId: string | null
  openActionItems: number
}

export interface SummaryCard {
  id: string
  status: 'none' | 'queued' | 'running' | 'ready' | 'failed' | 'skipped'
  primary: boolean
  createdAt: string
}

export interface TranscriptSegment {
  id: number
  speaker: string | null
  start: number
  end: number
  text: string
}

export interface Transcript {
  speakers: MeetingSpeaker[]
  segments: TranscriptSegment[]
}

export interface ActionItem {
  id: string
  task: string
  owner: { speaker: string | null; name: string | null; kind: 'person' | 'team' | 'role' | 'unknown' }
  due: { date: string | null; time: string | null; raw: string | null }
  priority: 'high' | 'normal' | 'low' | null
  status: 'open' | 'done' | 'dismissed'
}

export interface MinutesCard {
  id: string
  status: 'running' | 'ready' | 'failed'
  createdAt: string
}

const base = (id: string) => `/api/v1/meetings/${encodeURIComponent(id)}`

export function getMeeting(id: string): Promise<Meeting> {
  return apiFetch<Meeting>(base(id))
}

export function getTranscript(id: string): Promise<Transcript> {
  return apiFetch<Transcript>(`${base(id)}/transcript`)
}

export async function listSummaries(id: string): Promise<SummaryCard[]> {
  return (await apiFetch<{ items: SummaryCard[] }>(`${base(id)}/summaries`)).items
}

export function summaryMarkdown(id: string, summaryId: string): Promise<string> {
  return apiText(`${base(id)}/summaries/${encodeURIComponent(summaryId)}/export?format=md`)
}

export async function listActionItems(id: string): Promise<ActionItem[]> {
  return (await apiFetch<{ items: ActionItem[] }>(`${base(id)}/action-items`)).items
}

export async function listMinutes(id: string): Promise<MinutesCard[]> {
  return (await apiFetch<{ items: MinutesCard[] }>(`${base(id)}/minutes`)).items
}

export function minutesMarkdown(id: string, minutesId: string): Promise<string> {
  return apiText(`${base(id)}/minutes/${encodeURIComponent(minutesId)}/export?format=md`)
}
