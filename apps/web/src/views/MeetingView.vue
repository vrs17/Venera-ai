<script setup lang="ts">
/**
 * Yig'ilish sahifasi - llm.brb-tech.uz/meeting/<id> (2026-11-26). FAQAT KO'RISH: xulosa, vazifalar,
 * transkript, bayonnoma. Barno konnektori (Claude / ChatGPT) natijalaridagi havolalar va mobil ilova
 * yo'li (`/meeting/[id]`) shu yerga ochiladi; tahrirlash - mobil ilovada.
 *
 * Kirish shart (router `requiresAuth`): kirmagan odam kirish sahifasidan keyin shu yerga qaytadi.
 * Server faqat odamning O'Z yig'ilishini beradi (begonasi ham, yo'g'i ham bir xil 404).
 * Xulosa va bayonnoma - serverning Markdown eksporti, ya'ni konnektor ko'rsatadigan matn bilan bir xil;
 * ismsiz spiker yorlig'i ham eksportdagi qoida bilan (`services/meetings/export.py` `speaker_name`).
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BrandSpark from '../components/BrandSpark.vue'
import MarkdownMessage from '../components/MarkdownMessage.vue'
import VBadge from '../ui/VBadge.vue'
import VButton from '../ui/VButton.vue'
import VEmpty from '../ui/VEmpty.vue'
import VTabs, { type TabItem } from '../ui/VTabs.vue'
import { fmtDate, fmtDateTime } from '../ui/format'
import { ApiError } from '../api/http'
import {
  getMeeting,
  getTranscript,
  listActionItems,
  listMinutes,
  listSummaries,
  minutesMarkdown,
  summaryMarkdown,
  type ActionItem,
  type Meeting,
  type MeetingSpeaker,
  type Transcript,
} from '../api/meetings.api'

const props = defineProps<{ id: string }>()
const { t, locale } = useI18n({ useScope: 'global' })

type Tab = 'summary' | 'actions' | 'transcript' | 'minutes'
type State = 'idle' | 'loading' | 'ready' | 'error'

const phase = ref<'loading' | 'ready' | 'notFound' | 'error'>('loading')
const meeting = ref<Meeting | null>(null)
const tab = ref<Tab>('summary')

/** Har bo'lim birinchi ochilganda bir marta yuklanadi. */
const parts = reactive({
  summary: { state: 'idle' as State, data: null as string | null },
  actions: { state: 'idle' as State, data: null as ActionItem[] | null },
  transcript: { state: 'idle' as State, data: null as Transcript | null },
  minutes: { state: 'idle' as State, data: null as string | null },
})

const LOADERS: Record<Tab, (m: Meeting) => Promise<unknown>> = {
  async summary(m) {
    let chosen = m.primarySummaryId
    if (!chosen) {
      const ready = (await listSummaries(m.id)).filter((s) => s.status === 'ready')
      chosen = (ready.find((s) => s.primary) ?? ready[0])?.id ?? null
    }
    return chosen ? summaryMarkdown(m.id, chosen) : null
  },
  async actions(m) {
    const order = { open: 0, done: 1, dismissed: 2 }
    return (await listActionItems(m.id)).sort((a, b) => order[a.status] - order[b.status])
  },
  async transcript(m) {
    return m.transcript.available ? getTranscript(m.id) : null
  },
  async minutes(m) {
    const ready = (await listMinutes(m.id)).filter((x) => x.status === 'ready')
    ready.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    return ready[0] ? minutesMarkdown(m.id, ready[0].id) : null
  },
}

async function loadPart(name: Tab): Promise<void> {
  const m = meeting.value
  if (!m || parts[name].state === 'loading' || parts[name].state === 'ready') return
  parts[name].state = 'loading'
  try {
    ;(parts[name] as { data: unknown }).data = await LOADERS[name](m)
    parts[name].state = 'ready'
  } catch {
    parts[name].state = 'error'
  }
}

async function load(): Promise<void> {
  phase.value = 'loading'
  meeting.value = null
  for (const p of Object.values(parts)) {
    p.state = 'idle'
    p.data = null
  }
  try {
    meeting.value = await getMeeting(props.id)
    phase.value = 'ready'
    document.title = t('meeting.docTitle', { title: meeting.value.title })
    void loadPart(tab.value)
  } catch (err) {
    phase.value = err instanceof ApiError && err.status === 404 ? 'notFound' : 'error'
  }
}

onMounted(load)
watch(() => props.id, load)
watch(tab, (name) => void loadPart(name))

// --- ko'rinish ---------------------------------------------------------------------------------

const tabs = computed<TabItem<Tab>[]>(() => [
  { value: 'summary', label: t('meeting.tabs.summary') },
  { value: 'actions', label: t('meeting.tabs.actions'), count: meeting.value?.openActionItems || undefined },
  { value: 'transcript', label: t('meeting.tabs.transcript') },
  { value: 'minutes', label: t('meeting.tabs.minutes') },
])

const when = computed(() => (meeting.value ? fmtDateTime(meeting.value.recordedAt, locale.value, 'medium') : ''))
const duration = computed(() => {
  const sec = meeting.value?.durationSec
  if (sec == null) return ''
  return sec < 60 ? t('meeting.durationShort') : t('meeting.duration', { min: Math.round(sec / 60) })
})
const speakerCount = computed(() => meeting.value?.speakers.filter((s) => !s.mergedInto).length ?? 0)
const processing = computed(() => !!meeting.value && !['ready', 'failed'].includes(meeting.value.status))
const statusTone = computed(() =>
  meeting.value?.status === 'ready' ? 'good' : meeting.value?.status === 'failed' ? 'crit' : 'info',
)

const FALLBACK = { uz: '{n}-ishtirokchi', ru: 'Участник {n}', en: 'Speaker {n}' } as const
const UNKNOWN = { uz: "Noma'lum #{n}", ru: 'Неизвестный #{n}', en: 'Unknown #{n}' } as const

/** Spiker yorlig'i - eksportdagi bilan aynan bir xil: ism; ismsiz, lekin ovozi tanilgan - "Noma'lum #N";
 *  aks holda id raqami bilan "N-ishtirokchi" (yig'ilish tilida). Birlashtirilgan spiker - nishoniga. */
function speakerLabel(id: string | null, speakers: MeetingSpeaker[]): string {
  const byId = new Map(speakers.map((s) => [s.id, s]))
  let sid = id
  for (let seen = 0; sid && byId.get(sid)?.mergedInto && seen < 8; seen += 1) sid = byId.get(sid)!.mergedInto
  if (!sid) return '?'
  const sp = byId.get(sid)
  const name = (sp?.name ?? '').replace(/[\s\p{Cc}]+/gu, ' ').trim()
  if (name) return name
  const lang = meeting.value?.language ?? 'uz'
  if (sp?.personId) return UNKNOWN[lang].replace('{n}', String(sp.personId))
  return FALLBACK[lang].replace('{n}', sid.replace(/\D/g, '') || '?')
}

function clock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const hh = Math.floor(s / 3600)
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return hh ? `${hh}:${mm}:${ss}` : `${mm}:${ss}`
}

/** Ketma-ket bir spikerning segmentlari - bitta blok. */
const blocks = computed(() => {
  const tr = parts.transcript.data
  if (!tr) return []
  const out: { key: number; speaker: string; start: number; lines: string[] }[] = []
  for (const seg of tr.segments) {
    const speaker = speakerLabel(seg.speaker, tr.speakers)
    const last = out[out.length - 1]
    if (last && last.speaker === speaker) last.lines.push(seg.text)
    else out.push({ key: seg.id, speaker, start: seg.start, lines: [seg.text] })
  }
  return out
})

function ownerOf(item: ActionItem): string {
  if (item.owner.name) return item.owner.name
  if (item.owner.speaker && meeting.value) return speakerLabel(item.owner.speaker, meeting.value.speakers)
  return t('meeting.noOwner')
}

function dueOf(item: ActionItem): string {
  const { date, time, raw } = item.due
  if (date) return t('meeting.due', { date: `${fmtDate(date, locale.value)}${time ? `, ${time}` : ''}` })
  return raw ? t('meeting.due', { date: raw }) : ''
}
</script>

<template>
  <main class="meeting">
    <header class="meeting__head">
      <RouterLink to="/" class="meeting__brand"><BrandSpark :size="22" /> Barno AI</RouterLink>
      <RouterLink to="/" class="meeting__back">{{ t('meeting.back') }}</RouterLink>
    </header>

    <div class="meeting__body">
      <p v-if="phase === 'loading'" class="meeting__muted" role="status">{{ t('meeting.loading') }}</p>
      <VEmpty v-else-if="phase === 'notFound'" :title="t('meeting.notFound')" />
      <div v-else-if="phase === 'error'" class="meeting__retry" role="alert">
        <p>{{ t('meeting.failedLoad') }}</p>
        <VButton variant="ghost" size="sm" @click="load">{{ t('meeting.retry') }}</VButton>
      </div>

      <template v-else-if="meeting">
        <h1 class="meeting__title">{{ meeting.title }}</h1>
        <p class="meeting__meta">
          <span>{{ when }}</span>
          <span v-if="duration">· {{ duration }}</span>
          <span v-if="speakerCount">· {{ t('meeting.speakers', { n: speakerCount }) }}</span>
          <VBadge :tone="statusTone" size="sm">{{ t(`meeting.status.${meeting.status}`) }}</VBadge>
        </p>
        <p v-if="processing" class="meeting__muted">{{ t('meeting.processing') }}</p>

        <VTabs v-model="tab" :tabs="tabs" :aria-label="meeting.title">
          <template #default="{ value }">
            <div class="meeting__panel">
              <p v-if="parts[value].state === 'loading' || parts[value].state === 'idle'" class="meeting__muted" role="status">
                {{ t('meeting.loading') }}
              </p>
              <div v-else-if="parts[value].state === 'error'" class="meeting__retry" role="alert">
                <p>{{ t('meeting.failedLoad') }}</p>
                <VButton variant="ghost" size="sm" @click="loadPart(value)">{{ t('meeting.retry') }}</VButton>
              </div>

              <template v-else-if="value === 'summary'">
                <MarkdownMessage v-if="parts.summary.data" :source="parts.summary.data" />
                <p v-else class="meeting__muted">{{ t('meeting.noSummary') }}</p>
              </template>

              <template v-else-if="value === 'actions'">
                <ul v-if="parts.actions.data?.length" class="meeting__items">
                  <li v-for="item in parts.actions.data" :key="item.id" class="meeting__item" :class="`is-${item.status}`">
                    <p class="meeting__task">{{ item.task }}</p>
                    <p class="meeting__item-meta">
                      <span>{{ ownerOf(item) }}</span>
                      <span v-if="dueOf(item)">· {{ dueOf(item) }}</span>
                      <VBadge v-if="item.priority === 'high'" tone="warn" size="sm">{{ t('meeting.priority.high') }}</VBadge>
                      <VBadge :tone="item.status === 'done' ? 'good' : 'neutral'" size="sm">
                        {{ t(`meeting.itemStatus.${item.status}`) }}
                      </VBadge>
                    </p>
                  </li>
                </ul>
                <p v-else class="meeting__muted">{{ t('meeting.noActions') }}</p>
              </template>

              <template v-else-if="value === 'transcript'">
                <div v-if="blocks.length" class="meeting__transcript">
                  <section v-for="b in blocks" :key="b.key" class="meeting__turn">
                    <p class="meeting__speaker">
                      <strong>{{ b.speaker }}</strong> <time class="meeting__time">{{ clock(b.start) }}</time>
                    </p>
                    <p v-for="(line, i) in b.lines" :key="i" class="meeting__line">{{ line }}</p>
                  </section>
                </div>
                <p v-else class="meeting__muted">{{ t('meeting.noTranscript') }}</p>
              </template>

              <template v-else>
                <MarkdownMessage v-if="parts.minutes.data" :source="parts.minutes.data" />
                <p v-else class="meeting__muted">{{ t('meeting.noMinutes') }}</p>
              </template>
            </div>
          </template>
        </VTabs>

        <p class="meeting__muted meeting__foot">{{ t('meeting.readOnly') }}</p>
      </template>
    </div>
  </main>
</template>

<style scoped>
.meeting {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  padding: 24px 16px 64px;
}
.meeting__head,
.meeting__body {
  max-width: 820px;
  margin: 0 auto;
}
.meeting__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 24px;
}
.meeting__brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 18px;
  color: var(--text);
  text-decoration: none;
}
.meeting__brand :deep(svg) {
  color: var(--brand);
}
.meeting__back {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
}
.meeting__title {
  font-size: 26px;
  line-height: 1.25;
  margin: 0 0 8px;
  overflow-wrap: anywhere;
}
.meeting__meta,
.meeting__item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0 0 16px;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
}
.meeting__muted {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}
.meeting__retry {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.meeting__panel {
  padding-top: 16px;
  line-height: 1.6;
}
.meeting__items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.meeting__item {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--surface);
}
.meeting__item.is-done .meeting__task,
.meeting__item.is-dismissed .meeting__task {
  color: var(--text-3);
  text-decoration: line-through;
}
.meeting__task {
  margin: 0 0 6px;
  overflow-wrap: anywhere;
}
.meeting__item-meta {
  margin: 0;
}
.meeting__transcript {
  display: grid;
  gap: 14px;
}
.meeting__speaker {
  margin: 0 0 2px;
  font-size: var(--fs-body-sm);
}
.meeting__time {
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  margin-left: 6px;
}
.meeting__line {
  margin: 0;
  overflow-wrap: anywhere;
}
.meeting__foot {
  margin-top: 32px;
}
</style>
