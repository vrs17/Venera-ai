<script setup lang="ts">
// Dizayn kutubxonasi galereyasi (`/_kit`, faqat `vite dev`). Bosh dizayner src/ui dagi
// HAR BIR komponentni barcha variant va holatlarda, ikkala mavzuda va to'rt tilda shu
// yerda ko'radi. Ma'lumotlar soxta, lekin real shaklda (30 kun × 3 kanal, haqiqiy
// trace vaqtlari) - bo'sh "Lorem ipsum" dizayn xatolarini yashiradi.

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Activity,
  ArrowRight,
  Bot,
  Copy,
  Download,
  FileText,
  Flag,
  Globe,
  Inbox,
  LayoutDashboard,
  Link2,
  LogOut,
  MessagesSquare,
  Mic,
  Monitor,
  Moon,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Search,
  Send,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Smartphone,
  Sun,
  Trash2,
  User,
  Users,
} from 'lucide-vue-next'
import { LOCALES, setLocale } from '../../i18n'
import type { Locale } from '../../i18n'
import { useTheme } from '../../theme'
import type { ThemePreference } from '../../theme'
import BrandSpark from '../../components/BrandSpark.vue'
import {
  VAreaChart,
  VAvatar,
  VBadge,
  VBarChart,
  VButton,
  VCard,
  VChartLegend,
  VChartTable,
  VChartTooltip,
  VCheckbox,
  VChoiceChips,
  VCommandPalette,
  VCopy,
  VDataTable,
  VDateRange,
  VDialog,
  VDivider,
  VEmpty,
  VFilterBar,
  VFilterChip,
  VIconButton,
  VInput,
  VJson,
  VKbd,
  VLineChart,
  VMenu,
  VMenuItem,
  VMeter,
  VPopover,
  VSearchField,
  VSegmented,
  VSelect,
  VSheet,
  VSkeleton,
  VSparkline,
  VSpinner,
  VStackedBar,
  VStat,
  VSwitch,
  VTabs,
  VTextarea,
  VTooltip,
  VWaterfall,
  addDays,
  fmtCompact,
  fmtDate,
  fmtMs,
  fmtNumber,
  fmtPercent,
  fmtRelative,
  startOfDay,
  toISODate,
  useCommandPalette,
  useToast,
} from '../../ui'
import type {
  BarDatum,
  ChartSeries,
  ChartTableColumn,
  ChoiceOption,
  CommandItem,
  DataTableColumn,
  FilterOption,
  LegendItem,
  MenuEntry,
  SegmentedOption,
  SelectOption,
  StackPart,
  TabItem,
  TooltipRow,
  WaterfallRow,
} from '../../ui'
import { useAdminFilters } from '../../admin/useAdminFilters'
import type { Channel, ChannelFilter, ReportStatus, Route, TurnStatus } from '../../admin/types'
import { REPORT_COMMENT_MAX, REPORT_REASONS } from '../../features/report/report.api'
import type { ReportReason } from '../../features/report/report.api'

const { t, locale } = useI18n({ useScope: 'global' })
const toast = useToast()
const loc = computed(() => locale.value)

/* ================================================================ mavzu va til */

const { preference, setPreference } = useTheme()
const theme = computed<ThemePreference>({ get: () => preference.value, set: setPreference })

const themeOptions = computed<SegmentedOption<ThemePreference>[]>(() => [
  { value: 'light', label: t('ui.light'), icon: Sun },
  { value: 'dark', label: t('ui.dark'), icon: Moon },
  { value: 'system', label: t('ui.system'), icon: Monitor },
])

const localeModel = computed<Locale>({
  get: () => locale.value as Locale,
  set: (v) => setLocale(v),
})
const localeOptions: SelectOption<Locale>[] = LOCALES.map((l) => ({ value: l.code, label: l.label }))

/* ================================================================ mundarija */

const SECTIONS = [
  { id: 'foundations', label: 'Foundations' },
  { id: 'buttons', label: 'Buttons' },
  { id: 'fields', label: 'Fields' },
  { id: 'choices', label: 'Choices' },
  { id: 'display', label: 'Display' },
  { id: 'cards', label: 'Cards & empty' },
  { id: 'overlays', label: 'Overlays' },
  { id: 'feedback', label: 'Feedback' },
  { id: 'filters', label: 'Filters' },
  { id: 'table', label: 'Data table' },
  { id: 'stats', label: 'Stats' },
  { id: 'charts', label: 'Charts' },
  { id: 'trace', label: 'Trace' },
] as const

const activeSection = ref<string>(SECTIONS[0].id)
let io: IntersectionObserver | null = null
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') return
  // Ekranning yuqori uchdan birini kesib o'tgan bo'lim - "joriy".
  io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) if (e.isIntersecting) activeSection.value = e.target.id
    },
    { rootMargin: '-72px 0px -66% 0px' },
  )
  for (const s of SECTIONS) {
    const el = document.getElementById(s.id)
    if (el) io.observe(el)
  }
})
onBeforeUnmount(() => io?.disconnect())

const reducedMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
function jump(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
  // Klaviatura foydalanuvchisi uchun fokus ham bo'limga o'tsin.
  el.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
}

/* ================================================================ soxta ma'lumot */

// Deterministik tasodif: har qayta yuklashda bir xil rasm (skrinshotlarni solishtirish oson).
function mulberry32(seed: number) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let x = Math.imul(a ^ (a >>> 15), 1 | a)
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296
  }
}
const rand = mulberry32(20260929)
const pick = <T,>(list: readonly T[]): T => list[Math.floor(rand() * list.length)]

const today = startOfDay(new Date())
const days: Date[] = Array.from({ length: 30 }, (_, i) => addDays(today, i - 29))

function series(base: number, weekendDip: number, trend: number): number[] {
  return days.map((d, i) => {
    const weekend = d.getDay() === 0 || d.getDay() === 6
    const noise = 0.86 + rand() * 0.28
    return Math.round(base * (weekend ? weekendDip : 1) * (1 + i * trend) * noise)
  })
}
const webSeries = series(236, 0.38, 0.011)
const miniSeries = series(104, 0.62, 0.016)
const botSeries = series(82, 0.74, 0.006)
const totalSeries = days.map((_, i) => webSeries[i] + miniSeries[i] + botSeries[i])
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)

const activitySeries = computed<ChartSeries[]>(() => [
  { key: 'web', label: t('admin.channel.web'), color: '--ch-web', values: webSeries },
  { key: 'miniapp', label: t('admin.channel.miniapp'), color: '--ch-miniapp', values: miniSeries },
  { key: 'bot', label: t('admin.channel.bot'), color: '--ch-bot', values: botSeries },
])

const p50 = days.map((_, i) => Math.round(1750 + rand() * 520 + (i === 21 ? 900 : 0)))
const p95 = p50.map((v, i) => Math.round(v * (2.4 + rand() * 0.7) + (i === 21 ? 2600 : 0)))
const latencySeries = computed<ChartSeries[]>(() => [
  { key: 'p50', label: t('admin.overview.p50'), color: '--viz-1', values: p50 },
  { key: 'p95', label: t('admin.overview.p95'), color: '--viz-2', values: p95 },
  { key: 'slo', label: 'SLO', color: '--text-4', values: days.map(() => 6000), reference: true },
])
const msFormat = (v: number) => fmtMs(v, loc.value)
const numFormat = (v: number) => fmtNumber(v, loc.value)

const ROUTE_MIX: [Route | 'none', number][] = [
  ['rules', 0.58],
  ['hrm', 0.18],
  ['crm', 0.09],
  ['live', 0.06],
  ['clarify', 0.04],
  ['both', 0.03],
  ['none', 0.02],
]
const allTurns = sum(totalSeries)
const routeBars = computed<BarDatum[]>(() =>
  ROUTE_MIX.map(([route, share]) => ({
    key: route,
    label: t(`admin.route.${route}`),
    value: Math.round(allTurns * share),
    sub: fmtPercent(share, 0, loc.value),
    color: route === 'none' ? '--crit' : undefined,
  })),
)

const SERVICE_P95: [string, number][] = [
  ['assistant', 6240],
  ['stt_gapi', 1420],
  ['stt_router', 910],
  ['tts', 820],
  ['crm', 480],
  ['ollama', 420],
  ['hrm', 350],
  ['telegram', 230],
  ['keycloak', 160],
]
// Har bir xizmatning kunlik so'rovlari (kichik ko'plik grafiklari uchun).
const SERVICE_REQ: Record<string, number[]> = {
  assistant: series(410, 0.5, 0.012),
  ollama: series(395, 0.5, 0.012),
  stt_router: series(138, 0.55, 0.02),
  tts: series(176, 0.6, 0.018),
  hrm: series(122, 0.3, 0.008),
  crm: series(88, 0.3, 0.004),
  stt_gapi: series(58, 0.6, 0.03),
  telegram: series(164, 0.8, 0.006),
  keycloak: series(71, 0.4, 0.002),
}
const serviceBars = computed<BarDatum[]>(() =>
  SERVICE_P95.map(([service, ms]) => ({ key: service, label: t(`admin.usage.service.${service}`), value: ms })),
)

const channelParts = computed<StackPart[]>(() => [
  { key: 'web', label: t('admin.channel.web'), value: sum(webSeries), color: '--ch-web' },
  { key: 'miniapp', label: t('admin.channel.miniapp'), value: sum(miniSeries), color: '--ch-miniapp' },
  { key: 'bot', label: t('admin.channel.bot'), value: sum(botSeries), color: '--ch-bot' },
])

/** 30 kunlik qatorni 14 nuqtaga siqish (KPI trendi backend ham 14 nuqta beradi). */
function spark14(xs: number[]): number[] {
  const out: number[] = []
  for (let i = 0; i < 14; i++) {
    const a = Math.floor((i * xs.length) / 14)
    const b = Math.floor(((i + 1) * xs.length) / 14)
    out.push(sum(xs.slice(a, b)) / Math.max(1, b - a))
  }
  return out
}
const kpiLoading = ref(false)
const errorSpark = spark14(days.map(() => 0.012 + rand() * 0.018))

/* ---- soxta savollar jadvali ---- */

const PEOPLE = [
  { id: 101, name: 'Aziza Karimova', login: 'a.karimova', dept: 'HR' },
  { id: 102, name: 'Jasur Toshmatov', login: 'j.toshmatov', dept: 'Savdo' },
  { id: 103, name: 'Dilnoza Rahimova', login: 'd.rahimova', dept: 'Moliya' },
  { id: 104, name: 'Otabek Yusupov', login: 'o.yusupov', dept: 'IT' },
  { id: 105, name: 'Nodira Saidova', login: 'n.saidova', dept: 'HR' },
  { id: 106, name: 'Sherzod Aliyev', login: 's.aliyev', dept: 'Logistika' },
  { id: 107, name: 'Малика Эргашева', login: 'm.ergasheva', dept: 'Marketing' },
  { id: 108, name: 'Bekzod Nurmatov', login: 'b.nurmatov', dept: 'IT' },
  { id: 109, name: 'Gulnora Xolmatova', login: 'g.xolmatova', dept: 'Yuridik' },
  { id: 110, name: 'Рустам Кадыров', login: 'r.qodirov', dept: 'Savdo' },
] as const

const QUESTIONS: [string, Route][] = [
  ['Yillik taʼtil necha kun?', 'rules'],
  ['Bugun kim ishga kechikdi?', 'hrm'],
  ['Xizmat safari xarajatlari qanday qoplanadi?', 'rules'],
  ['Mening sprintimdagi ochiq vazifalar', 'crm'],
  ['Kasallik varaqasini qanday topshiraman?', 'rules'],
  ['Сколько дней отпуска положено за год?', 'rules'],
  ['Oʻtgan haftadagi davomat hisobotini koʻrsat', 'live'],
  ['Yangi xodimlar uchun onboarding tartibi qanday?', 'rules'],
  ['Как оформить командировку в Ташкент?', 'both'],
  ['CRM dagi ochiq lidlar nechta?', 'crm'],
  ['Masofadan ishlash siyosati qanday?', 'rules'],
  ['Hisobot tayyorlab ber', 'clarify'],
]

interface TurnRow {
  id: string
  startedAt: Date
  user: string
  login: string
  channel: Channel
  question: string
  route: Route | null
  sources: number
  ttftMs: number | null
  totalMs: number | null
  status: TurnStatus
}

const CH_WEIGHTED: Channel[] = ['web', 'web', 'web', 'web', 'web', 'miniapp', 'miniapp', 'bot', 'bot', 'desktop']

function makeRows(n: number, offset = 0): TurnRow[] {
  const now = Date.now()
  return Array.from({ length: n }, (_, k) => {
    const i = k + offset
    const who = pick(PEOPLE)
    const [question, route] = pick(QUESTIONS)
    const r = rand()
    const status: TurnStatus = r < 0.06 ? 'error' : r < 0.1 ? 'cancelled' : i === 0 ? 'running' : 'ok'
    const ttft = status === 'error' ? null : Math.round(1300 + rand() * 1800 + (rand() < 0.1 ? 3800 : 0))
    const total =
      status === 'running' ? null : status === 'error' ? Math.round(400 + rand() * 900) : (ttft ?? 0) + Math.round(2200 + rand() * 5200)
    return {
      id: `t_${(0x8f2c41d0 + i * 7919).toString(16)}`,
      startedAt: new Date(now - i * 23 * 60_000 - Math.round(rand() * 20 * 60_000)),
      user: who.name,
      login: who.login,
      channel: pick(CH_WEIGHTED),
      question,
      route: status === 'error' ? null : route,
      sources: route === 'rules' || route === 'both' ? 2 + Math.floor(rand() * 5) : 0,
      ttftMs: ttft,
      totalMs: total,
      status,
    }
  })
}

const tableRows = ref<TurnRow[]>(makeRows(30))
const tableLoading = ref(false)
const tableDense = ref(false)
const tableEmpty = ref(false)
const tableSelected = ref<string | null>(null)
const loadingMore = ref(false)
const shownRows = computed(() => (tableEmpty.value ? [] : tableRows.value))

const tableColumns = computed<DataTableColumn<TurnRow>[]>(() => [
  {
    key: 'startedAt',
    label: t('admin.col.time'),
    width: 112,
    sortable: true,
    format: (r) => fmtRelative(r.startedAt, loc.value),
    sortValue: (r) => r.startedAt.getTime(),
  },
  { key: 'user', label: t('admin.col.user'), width: '20%' },
  { key: 'channel', label: t('admin.col.channel'), width: 120 },
  { key: 'question', label: t('admin.col.question') },
  { key: 'route', label: t('admin.col.route'), width: 132 },
  { key: 'sources', label: t('admin.col.sources'), width: 96, align: 'end', sortable: true },
  {
    key: 'latency',
    label: t('admin.col.latency'),
    width: 136,
    align: 'end',
    mono: true,
    sortable: true,
    value: (r) => r.totalMs,
    format: (r) => `${r.ttftMs === null ? '—' : fmtMs(r.ttftMs, loc.value)} / ${r.totalMs === null ? '—' : fmtMs(r.totalMs, loc.value)}`,
  },
  { key: 'status', label: t('admin.col.status'), width: 132 },
])

const CHANNEL_ICON: Record<string, typeof Globe> = {
  web: Globe,
  miniapp: Smartphone,
  bot: Bot,
  desktop: Monitor,
  api: Server,
}

const ROUTE_TONE: Record<string, 'neutral' | 'info' | 'brand' | 'warn' | 'good'> = {
  rules: 'info',
  hrm: 'good',
  crm: 'brand',
  live: 'good',
  both: 'neutral',
  clarify: 'warn',
}

const STATUS_TONE: Record<TurnStatus, 'good' | 'crit' | 'warn' | 'neutral'> = {
  ok: 'good',
  error: 'crit',
  running: 'warn',
  cancelled: 'neutral',
}

function onRowClick(row: TurnRow) {
  tableSelected.value = row.id
  toast.show({ message: `${t('admin.trace.openTrace')} · ${row.id}` })
}

function loadMore() {
  loadingMore.value = true
  tableLoading.value = true
  setTimeout(() => {
    tableRows.value = [...tableRows.value, ...makeRows(10, tableRows.value.length)]
    loadingMore.value = false
    tableLoading.value = false
  }, 900)
}

/* ---- trace ---- */

const kindColors: Record<string, string> = {
  venera: '--viz-7',
  model: '--viz-4',
  assistant: '--viz-1',
  stage: '--viz-1',
  sources: '--viz-3',
  token: '--viz-2',
  // Holat ranglari (--good/--crit) faqat holat uchun - "tugadi" hodisasi toifa rangida.
  done: '--viz-6',
  tts: '--viz-5',
}

const traceError = ref(false)
const traceRows = computed<WaterfallRow[]>(() => {
  const s = (k: string) => t(`admin.trace.span.${k}`)
  const rows: WaterfallRow[] = [
    { id: 'request', label: s('request'), sub: 'POST /chat/stream', startMs: 0, durMs: 7700, kind: 'request' },
    { id: 'auth', label: s('auth'), startMs: 0, durMs: 3, kind: 'venera', depth: 1 },
    { id: 'classify', label: s('hold.classify'), sub: 'qwen2.5:3b · taʼtil', startMs: 3, durMs: 420, kind: 'model', depth: 1 },
    { id: 'open', label: s('assistant.open'), sub: 'HR Assistant', startMs: 4, durMs: 180, kind: 'assistant', depth: 1 },
    { id: 'stream', label: s('assistant.stream'), startMs: 184, durMs: 6616, kind: 'assistant', depth: 1 },
    { id: 'st1', label: s('stage'), sub: 'Savol tahlil qilinmoqda…', startMs: 260, kind: 'stage', depth: 2 },
    { id: 'st2', label: s('stage'), sub: 'Hujjatlar qidirilmoqda…', startMs: 640, kind: 'stage', depth: 2 },
    { id: 'sources', label: s('sources'), sub: '4 × HR-POL', startMs: 1900, kind: 'sources', depth: 2 },
    { id: 'first', label: s('first_token'), startMs: 2300, kind: 'token', depth: 2 },
    { id: 'done', label: s('done'), sub: 'route: rules', startMs: 6800, kind: 'done', depth: 2 },
    { id: 'tts', label: s('tts'), sub: '612 chars', startMs: 6800, durMs: 900, kind: 'tts', depth: 1 },
  ]
  if (!traceError.value) return rows
  // Xato varianti: yordamchi oqimi 3.1 s da uzildi, javob va ovoz yo'q.
  return rows
    .filter((r) => r.id !== 'done' && r.id !== 'tts' && r.id !== 'first')
    .map((r) =>
      r.id === 'stream'
        ? { ...r, durMs: 2916, status: 'error' as const }
        : r.id === 'request'
          ? { ...r, durMs: 3100, status: 'error' as const }
          : r,
    )
    .concat({ id: 'error', label: s('error'), sub: 'upstream_timeout', startMs: 3100, kind: 'error', depth: 2, status: 'error' })
})
const traceSelected = ref<string | null>('sources')
const traceSelectedRow = computed(() => traceRows.value.find((r) => r.id === traceSelected.value) ?? null)

const rawFrames = [
  { type: 'stage', text: 'Hujjatlar qidirilmoqda…', t_ms: 640 },
  {
    type: 'sources',
    t_ms: 1900,
    items: [
      {
        doc_id: 'HR-POL-014',
        title: 'Mehnat taʼtillari toʻgʻrisidagi nizom',
        page: 3,
        score: 0.872,
        snippet:
          'Xodimga har yili kamida 21 kalendar kunidan iborat asosiy haq toʻlanadigan taʼtil beriladi. Nogironligi boʻlgan xodimlar va 18 yoshga toʻlmaganlar uchun taʼtil 30 kalendar kunidan kam boʻlmasligi kerak.',
        citation_index: 1,
      },
      { doc_id: 'HR-POL-021', title: 'Ichki mehnat tartibi qoidalari', page: 12, score: 0.641, citation_index: 2 },
    ],
  },
  {
    type: 'done',
    route: 'rules',
    request_id: 'req_8f2c41d0',
    usage: { prompt_tokens: 1832, completion_tokens: 412, total_tokens: 2244 },
    cached: false,
    warning: null,
  },
  {
    request: {
      headers: { Authorization: 'Bearer eyJhbGciOiJIUzI1NiJ9.demo', 'X-Venera-Client': 'web' },
      access_token: 'sk-live-should-never-show',
      locale: 'uz',
    },
  },
]

/* ================================================================ holatlar */

// tugmalar
const btnLoading = ref(false)
function fakeWork() {
  btnLoading.value = true
  setTimeout(() => (btnLoading.value = false), 1400)
}
const pressed = ref(false)

// maydonlar
const login = ref('')
const search = ref('taʼtil')
const badLogin = ref('y.mamajonov')
const note = ref('')
const nearLimit = ref('Javobda eski nizom keltirilgan: 2024-yilgi tahrir. Yangi tahrirda taʼtil 24 kun deb yozilgan.')
const routeValue = ref<string | null>('rules')
const routeGhost = ref<string | null>('hrm')
const routeOptions = computed<SelectOption<string>[]>(() =>
  ROUTE_MIX.map(([r, share]) => ({ value: r, label: t(`admin.route.${r}`), hint: fmtPercent(share, 0, loc.value) })),
)
const searchField = ref('')
const lastSearch = ref('')

// tanlovlar
const blocked = ref(false)
const notify = ref(true)
const agree = ref(true)
const channelsChecked = ref<(string | number)[]>(['web', 'bot'])
const allChannels = ['web', 'miniapp', 'bot'] as const
const allChecked = computed(() => channelsChecked.value.length === allChannels.length)
const someChecked = computed(() => channelsChecked.value.length > 0 && !allChecked.value)
function toggleAll(on: boolean | (string | number)[]) {
  channelsChecked.value = on === true ? [...allChannels] : []
}

const reason = ref<ReportReason | null>(null)
const reasonOptions = computed<ChoiceOption<ReportReason>[]>(() =>
  REPORT_REASONS.map((r) => ({ value: r, label: t(`report.reason.${r}`) })),
)
const multiChannels = ref<Channel[]>(['web'])
const channelChoice = computed<ChoiceOption<Channel>[]>(() =>
  (['web', 'miniapp', 'bot', 'desktop'] as Channel[]).map((c) => ({ value: c, label: t(`admin.channel.${c}`), icon: CHANNEL_ICON[c] })),
)

const localChannel = ref<ChannelFilter>('all')
const channelSegments = computed<SegmentedOption<ChannelFilter>[]>(() =>
  (['all', 'web', 'miniapp', 'bot'] as ChannelFilter[]).map((c) => ({ value: c, label: t(`admin.channel.${c}`) })),
)
const viewMode = ref<'turns' | 'chats'>('turns')
const viewSegments = computed<SegmentedOption<'turns' | 'chats'>[]>(() => [
  { value: 'turns', label: t('admin.conversations.viewTurns'), icon: MessagesSquare },
  { value: 'chats', label: t('admin.conversations.viewChats'), icon: Inbox },
])

const reportTab = ref<ReportStatus>('new')
const reportTabs = computed<TabItem<ReportStatus>[]>(() => [
  { value: 'new', label: t('admin.reportTab.new'), count: 7 },
  { value: 'reviewing', label: t('admin.reportTab.reviewing'), count: 2 },
  { value: 'resolved', label: t('admin.reportTab.resolved'), count: 41 },
  { value: 'dismissed', label: t('admin.reportTab.dismissed'), count: 5 },
])
const traceTab = ref<'sources' | 'api' | 'raw' | 'chat'>('sources')
const traceTabs = computed<TabItem<'sources' | 'api' | 'raw' | 'chat'>[]>(() => [
  { value: 'sources', label: t('admin.trace.sources'), count: 4 },
  { value: 'api', label: t('admin.trace.apiCalls') },
  { value: 'raw', label: t('admin.trace.raw') },
  { value: 'chat', label: t('admin.trace.chat') },
])

// menyu
const menuDense = ref(false)
const menuSort = ref<'new' | 'old'>('new')
const menuItems = computed<MenuEntry[]>(() => [
  { label: t('ui.edit'), icon: Pencil, shortcut: 'mod+e', onSelect: () => toast.show(t('ui.edit')) },
  { label: t('admin.common.copyLink'), icon: Link2, onSelect: () => toast.show(t('ui.copied')) },
  { label: t('admin.trace.openTrace'), icon: ArrowRight, hint: 'turn' },
  { kind: 'separator' },
  { kind: 'label', label: t('ui.filters') },
  { kind: 'checkbox', label: t('admin.conversations.reported'), checked: menuDense.value, onSelect: () => (menuDense.value = !menuDense.value) },
  { label: t('ui.delete'), icon: Trash2, danger: true, onSelect: () => toast.error(t('ui.delete')) },
  { label: t('admin.nav.signOut'), icon: LogOut, disabled: true },
])

// dialog va sheet
const reportOpen = ref(false)
const reportComment = ref('')
const reportReason = ref<ReportReason | null>(null)
const reportSending = ref(false)
const reportError = ref<string | null>(null)
let reportFail = true
function sendReport() {
  reportSending.value = true
  reportError.value = null
  setTimeout(() => {
    reportSending.value = false
    // Birinchi urinish ataylab xato: xato holatini ham ko'rish kerak.
    if (reportFail) {
      reportFail = false
      reportError.value = t('report.error')
      return
    }
    reportOpen.value = false
    reportFail = true
    reportComment.value = ''
    reportReason.value = null
    toast.success(t('report.sent'))
  }, 1100)
}

const confirmOpen = ref(false)
const largeOpen = ref(false)
const sheetOpen = ref(false)
const bottomOpen = ref(false)
const sheetBlocked = ref(false)
const sheetRoles = ref<string[]>(['ADMIN', 'USER'])
const roleChoice = computed<ChoiceOption<string>[]>(() =>
  ['ADMIN', 'RAG_ADMIN', 'USER'].map((r) => ({ value: r, label: t(`admin.user.role.${r}`) })),
)

// popover
const popChannels = ref<(string | number)[]>(['web'])

// toast
function toastNeutral() {
  toast.show(t('admin.toast.saved'))
}
function toastGood() {
  toast.success(t('report.sent'))
}
function toastCrit() {
  toast.error(t('admin.toast.failed'))
}
function toastAction() {
  toast.show({
    message: t('admin.toast.blocked'),
    action: { label: t('ui.cancel'), onClick: () => toast.show(t('admin.toast.unblocked')) },
  })
}
function toastSticky() {
  toast.show({ message: t('admin.error.storage'), tone: 'crit', duration: 0, id: 'sticky' })
}

/* ---- filtrlar ---- */

// Global admin filtri - shu sahifaning URL'iga yoziladi (`/_kit?preset=7d&channel=bot`).
const { range, channel: filterChannel, params, filterQuery, isDefault, reset: resetFilters } = useAdminFilters()

const fbSearch = ref('')
const fbChannels = ref<Channel[]>([])
const fbRoute = ref<string | null>(null)
const fbStatus = ref<TurnStatus | null>(null)
const fbReported = ref(false)
const fbUser = ref<number | null>(null)
const fbUserQuery = ref('')
const fbUserLoading = ref(false)

const channelFilterOptions = computed<FilterOption<Channel>[]>(() =>
  (['web', 'miniapp', 'bot', 'desktop', 'api'] as Channel[]).map((c) => ({
    value: c,
    label: t(`admin.channel.${c}`),
    dot: `var(--ch-${c})`,
  })),
)
const routeFilterOptions = computed<FilterOption<string>[]>(() =>
  ROUTE_MIX.map(([r]) => ({ value: r, label: t(`admin.route.${r}`) })),
)
const statusFilterOptions = computed<FilterOption<TurnStatus>[]>(() =>
  (['ok', 'error', 'running', 'cancelled'] as TurnStatus[]).map((s) => ({ value: s, label: t(`admin.status.${s}`) })),
)
const userFilterOptions = computed<FilterOption<number>[]>(() =>
  PEOPLE.filter((p) => !fbUserQuery.value || p.name.toLowerCase().includes(fbUserQuery.value.toLowerCase())).map(
    (p) => ({ value: p.id, label: p.name, hint: p.login }),
  ),
)
let userTimer: ReturnType<typeof setTimeout> | undefined
function onUserSearch(q: string) {
  fbUserLoading.value = true
  clearTimeout(userTimer)
  userTimer = setTimeout(() => {
    fbUserQuery.value = q
    fbUserLoading.value = false
  }, 350)
}
onBeforeUnmount(() => clearTimeout(userTimer))

const fbMatches = computed(() => {
  let rows = tableRows.value
  if (fbChannels.value.length) rows = rows.filter((r) => fbChannels.value.includes(r.channel))
  if (fbRoute.value) rows = rows.filter((r) => (r.route ?? 'none') === fbRoute.value)
  if (fbStatus.value) rows = rows.filter((r) => r.status === fbStatus.value)
  if (fbUser.value) {
    const who = PEOPLE.find((p) => p.id === fbUser.value)
    rows = rows.filter((r) => r.login === who?.login)
  }
  const q = fbSearch.value.trim().toLowerCase()
  if (q) rows = rows.filter((r) => r.question.toLowerCase().includes(q) || r.user.toLowerCase().includes(q))
  return rows.length
})

/* ---- buyruqlar palitrasi ---- */

const palette = useCommandPalette()
palette.registerCommands(
  () => t('admin.palette.pages'),
  () => [
    { id: 'kit-overview', label: t('admin.nav.overview'), icon: LayoutDashboard, to: '/admin', hint: t('admin.title') },
    { id: 'kit-conversations', label: t('admin.nav.conversations'), icon: MessagesSquare, to: '/admin/conversations' },
    { id: 'kit-reports', label: t('admin.nav.reports'), icon: Flag, to: '/admin/reports' },
    { id: 'kit-users', label: t('admin.nav.users'), icon: Users, to: '/admin/users' },
    { id: 'kit-usage', label: t('admin.nav.usage'), icon: Activity, to: '/admin/usage' },
    { id: 'kit-system', label: t('admin.nav.system'), icon: Server, to: '/admin/system' },
  ],
  { id: 'kit-pages' },
)
palette.register(
  async (q, signal) => {
    const query = q.trim().toLowerCase()
    if (!query) return null
    // Tarmoq so'rovini taqlid qilamiz: palitraning "sekin manba" xulqi ko'rinsin.
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, 280)
      signal.addEventListener(
        'abort',
        () => {
          clearTimeout(timer)
          reject(new DOMException('aborted', 'AbortError'))
        },
        { once: true },
      )
    })
    const items: CommandItem[] = PEOPLE.filter(
      (p) => p.name.toLowerCase().includes(query) || p.login.includes(query),
    ).map((p) => ({
      id: `kit-user-${p.id}`,
      label: p.name,
      sub: `${p.login} · ${p.dept}`,
      icon: User,
      run: () => {
        toast.show(p.name)
      },
    }))
    return items.length ? { group: t('admin.palette.users'), items } : null
  },
  { id: 'kit-people' },
)

/* ---- grafik yordamchilari (alohida namoyish) ---- */

const legendItems = computed<LegendItem[]>(() => [
  { key: 'web', label: t('admin.channel.web'), color: '--ch-web', mark: 'rect' },
  { key: 'miniapp', label: t('admin.channel.miniapp'), color: '--ch-miniapp', mark: 'rect' },
  { key: 'bot', label: t('admin.channel.bot'), color: '--ch-bot', mark: 'rect' },
  { key: 'p95', label: t('admin.overview.p95'), color: '--viz-2', mark: 'line' },
  { key: 'slo', label: 'SLO', color: '--text-4', mark: 'dashed' },
])
const hiddenLegend = ref<Set<string>>(new Set())
const legendView = computed(() => legendItems.value.map((i) => ({ ...i, hidden: hiddenLegend.value.has(i.key) })))
function toggleLegend(key: string) {
  const next = new Set(hiddenLegend.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  hiddenLegend.value = next
}
const legendList = computed<LegendItem[]>(() => {
  const total = sum(channelParts.value.map((p) => p.value))
  return channelParts.value.map((p) => ({
    key: p.key,
    label: p.label,
    color: p.color,
    mark: 'rect' as const,
    value: numFormat(p.value),
    share: fmtPercent(p.value / total, 0, loc.value),
  }))
})
const tooltipRows = computed<TooltipRow[]>(() => [
  { key: 'web', label: t('admin.channel.web'), value: numFormat(webSeries[29]), color: '--ch-web', mark: 'rect' },
  { key: 'miniapp', label: t('admin.channel.miniapp'), value: numFormat(miniSeries[29]), color: '--ch-miniapp', mark: 'rect' },
  { key: 'bot', label: t('admin.channel.bot'), value: numFormat(botSeries[29]), color: '--ch-bot', mark: 'rect' },
  { key: 'total', label: t('ui.total'), value: numFormat(totalSeries[29]), mark: 'none' },
])
const tableColumnsChart = computed<ChartTableColumn[]>(() => [
  { key: 'service', label: t('admin.col.service') },
  { key: 'p95', label: t('admin.usage.p95'), align: 'end' },
])
const tableRowsChart = computed(() =>
  SERVICE_P95.slice(0, 5).map(([s, ms]) => ({ service: t(`admin.usage.service.${s}`), p95: fmtMs(ms, loc.value) })),
)
const chartLoading = ref(false)

/* ---- foundations ---- */

const SWATCHES: { group: string; tokens: string[] }[] = [
  { group: 'Surfaces', tokens: ['--bg', '--bg-subtle', '--surface', '--fill', '--fill-hover', '--line', '--line-strong'] },
  { group: 'Text', tokens: ['--text', '--text-2', '--text-3', '--text-4'] },
  { group: 'Accent', tokens: ['--ink', '--ink-hover', '--brand', '--brand-soft', '--focus', '--selection'] },
  {
    group: 'Status',
    tokens: ['--good', '--good-soft', '--warn', '--warn-soft', '--serious', '--crit', '--crit-soft', '--info-soft'],
  },
  { group: 'Data viz', tokens: ['--viz-1', '--viz-2', '--viz-3', '--viz-4', '--viz-5', '--viz-6', '--viz-7', '--viz-8'] },
  { group: 'Channels', tokens: ['--ch-web', '--ch-miniapp', '--ch-bot', '--ch-desktop', '--ch-api'] },
]
const TYPE_SCALE = [
  { cls: 't-display', name: 'display 40/44' },
  { cls: 't-title-1', name: 'title-1 28/34' },
  { cls: 't-title-2', name: 'title-2 20/28' },
  { cls: 't-title-3', name: 'title-3 16/24' },
  { cls: 't-body-lg', name: 'body-lg 16/28' },
  { cls: 't-body', name: 'body 15/24' },
  { cls: 't-body-sm', name: 'body-sm 14/20' },
  { cls: 't-caption', name: 'caption 12/16' },
  { cls: 't-mono', name: 'mono 12.5/18' },
]
const RADII = ['--r-xs', '--r-sm', '--r-md', '--r-lg', '--r-xl', '--r-full']
const ELEVATIONS = ['--e1', '--e2', '--e3']

// Sahifadan chiqqanda ochiq palitra/toast'lar qolib ketmasin.
onBeforeUnmount(() => {
  palette.close()
  toast.clear()
})

// Sahifa ochilganda URL'dagi #bo'limga o'tish (yangilanganda joy saqlansin).
onMounted(async () => {
  const id = location.hash.slice(1)
  if (!id) return
  await nextTick()
  document.getElementById(id)?.scrollIntoView({ block: 'start' })
})

const isoToday = toISODate(today)
</script>

<template>
  <div class="kit">
    <!-- ========================================================== tepa panel -->
    <header class="kit-top">
      <a class="kit-brand" href="#foundations" @click.prevent="jump('foundations')">
        <span class="kit-spark" aria-hidden="true"><BrandSpark :size="16" /></span>
        <span class="kit-word">Venera</span>
        <span class="kit-tag t-caption">UI kit</span>
      </a>
      <div class="kit-top__end">
        <VSegmented v-model="theme" :options="themeOptions" icon-only size="sm" :aria-label="t('ui.theme')" />
        <VSelect
          v-model="localeModel"
          :options="localeOptions"
          size="sm"
          variant="ghost"
          :aria-label="t('ui.language')"
          :menu-width="160"
        />
      </div>
    </header>

    <div class="kit-body">
      <!-- ========================================================== mundarija -->
      <nav class="kit-toc" aria-label="Sections">
        <ul>
          <li v-for="s in SECTIONS" :key="s.id">
            <a
              :href="`#${s.id}`"
              :class="{ 'is-active': activeSection === s.id }"
              :aria-current="activeSection === s.id ? 'true' : undefined"
              @click.prevent="jump(s.id)"
            >
              {{ s.label }}
            </a>
          </li>
        </ul>
      </nav>

      <main class="kit-main">
        <div class="kit-hero">
          <h1 class="t-display">Venera 2026</h1>
          <p class="t-body-lg t-3">
            src/ui — every component, every state. Light / dark, uz · uz-Cyrl · ru · en, 360 px → wide.
          </p>
        </div>

        <!-- ====================================================== foundations -->
        <section id="foundations" class="kit-sec" aria-labelledby="h-foundations">
          <header class="kit-sec__head">
            <h2 id="h-foundations" class="t-title-2" tabindex="-1">Foundations</h2>
            <p class="t-body-sm t-3">tokens.css · base.css</p>
          </header>

          <div v-for="g in SWATCHES" :key="g.group" class="kit-spec">
            <p class="kit-spec__label">{{ g.group }}</p>
            <div class="kit-swatches">
              <div v-for="tk in g.tokens" :key="tk" class="kit-swatch">
                <span class="kit-swatch__chip" :style="{ background: `var(${tk})` }" />
                <code class="kit-code">{{ tk }}</code>
              </div>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">Type</p>
            <div class="kit-type">
              <div v-for="ty in TYPE_SCALE" :key="ty.cls" class="kit-type__row">
                <code class="kit-code">{{ ty.name }}</code>
                <span :class="ty.cls" class="truncate">{{ t('admin.page.overview.subtitle') }} — {{ t('report.subtitle') }}</span>
              </div>
            </div>
          </div>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">Radius</p>
              <div class="kit-row">
                <div v-for="r in RADII" :key="r" class="kit-radius">
                  <span :style="{ borderRadius: `var(${r})` }" />
                  <code class="kit-code">{{ r }}</code>
                </div>
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">Elevation</p>
              <div class="kit-row">
                <div v-for="e in ELEVATIONS" :key="e" class="kit-elev">
                  <span :style="{ boxShadow: `var(${e})` }" />
                  <code class="kit-code">{{ e }}</code>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ====================================================== buttons -->
        <section id="buttons" class="kit-sec" aria-labelledby="h-buttons">
          <header class="kit-sec__head">
            <h2 id="h-buttons" class="t-title-2" tabindex="-1">Buttons</h2>
            <p class="t-body-sm t-3">VButton · VIconButton</p>
          </header>

          <div class="kit-spec">
            <p class="kit-spec__label">Variants — primary · secondary · ghost · outline · danger</p>
            <div class="kit-row">
              <VButton variant="primary" :icon="Send">{{ t('report.send') }}</VButton>
              <VButton variant="secondary">{{ t('admin.overview.viewAll') }}</VButton>
              <VButton variant="ghost">{{ t('ui.cancel') }}</VButton>
              <VButton variant="outline" :icon="RefreshCw">{{ t('admin.common.refresh') }}</VButton>
              <VButton variant="danger">{{ t('admin.user.block') }}</VButton>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">Sizes — sm 32 · md 36 · lg 44 · lg pill</p>
            <div class="kit-row kit-row--end">
              <VButton variant="primary" size="sm">{{ t('ui.apply') }}</VButton>
              <VButton variant="primary" size="md">{{ t('ui.apply') }}</VButton>
              <VButton variant="primary" size="lg">{{ t('ui.apply') }}</VButton>
              <VButton variant="primary" size="lg" pill :icon-end="ArrowRight">{{ t('ui.next') }}</VButton>
              <VButton size="sm" :icon="Download">PDF</VButton>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">States — loading keeps width · disabled · link · block</p>
            <div class="kit-row">
              <VButton variant="primary" :loading="btnLoading" @click="fakeWork">{{ t('report.send') }}</VButton>
              <VButton :loading="btnLoading" :icon="RefreshCw" @click="fakeWork">{{ t('admin.common.refresh') }}</VButton>
              <VButton variant="primary" disabled>{{ t('report.send') }}</VButton>
              <VButton variant="outline" disabled>{{ t('ui.delete') }}</VButton>
              <VButton variant="ghost" href="#buttons" :icon-end="ArrowRight">{{ t('admin.trace.openTrace') }}</VButton>
            </div>
            <div class="kit-narrow">
              <VButton variant="primary" size="lg" block>{{ t('signIn') }}</VButton>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VIconButton — ghost · secondary · outline · primary · sizes · active · pressed · dot · disabled · loading</p>
            <div class="kit-row kit-row--end">
              <VIconButton :icon="Copy" :label="t('ui.copy')" />
              <VIconButton :icon="Flag" :label="t('report.reportAnswer')" variant="secondary" />
              <VIconButton :icon="MoreHorizontal" :label="t('ui.moreActions')" variant="outline" />
              <VIconButton :icon="Send" :label="t('report.send')" variant="primary" />
              <VDivider orientation="vertical" spacing="sm" />
              <VIconButton :icon="Search" :label="t('ui.search')" size="sm" shortcut="mod+k" />
              <VIconButton :icon="Search" :label="t('ui.search')" size="md" />
              <VIconButton :icon="Search" :label="t('ui.search')" size="lg" />
              <VDivider orientation="vertical" spacing="sm" />
              <VIconButton :icon="Flag" :label="t('report.reportedTooltip')" active />
              <VIconButton :icon="Mic" :label="t('admin.conversations.voice')" :pressed="pressed" @click="pressed = !pressed" />
              <VIconButton :icon="Inbox" :label="t('admin.nav.reports')" dot />
              <VIconButton :icon="Flag" :label="t('report.unavailable')" disabled />
              <VIconButton :icon="RefreshCw" :label="t('admin.common.refresh')" :loading="btnLoading" @click="fakeWork" />
            </div>
          </div>
        </section>

        <!-- ====================================================== fields -->
        <section id="fields" class="kit-sec" aria-labelledby="h-fields">
          <header class="kit-sec__head">
            <h2 id="h-fields" class="t-title-2" tabindex="-1">Fields</h2>
            <p class="t-body-sm t-3">VInput · VTextarea · VSelect · VSearchField</p>
          </header>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VInput — label · hint · icon + clearable · error · disabled</p>
              <div class="kit-stack">
                <VInput v-model="login" :label="t('admin.user.login')" placeholder="y.mamajonov" :hint="t('authLoginSub')" autocomplete="off" />
                <VInput v-model="search" :icon="Search" clearable :placeholder="t('ui.search')" :aria-label="t('ui.search')" />
                <VInput v-model="badLogin" :label="t('admin.user.login')" :error="t('connectFailed')" />
                <VInput model-value="a.karimova" :label="t('admin.user.email')" disabled />
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">Sizes — sm · md · lg</p>
              <div class="kit-stack">
                <VInput size="sm" :placeholder="t('admin.conversations.searchPlaceholder')" :aria-label="t('ui.search')" :icon="Search" />
                <VInput size="md" :placeholder="t('admin.conversations.searchPlaceholder')" :aria-label="t('ui.search')" :icon="Search" />
                <VInput size="lg" :placeholder="t('admin.conversations.searchPlaceholder')" :aria-label="t('ui.search')" :icon="Search" />
              </div>
            </div>
          </div>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VTextarea — autosize · counter near limit · error</p>
              <div class="kit-stack">
                <VTextarea
                  v-model="note"
                  :label="t('report.commentLabel')"
                  :placeholder="t('report.placeholder')"
                  :rows="4"
                  :maxlength="REPORT_COMMENT_MAX"
                  :counter-from="1800"
                />
                <VTextarea v-model="nearLimit" :label="t('admin.reports.adminNote')" :rows="2" :maxlength="120" />
                <VTextarea model-value="" :label="t('report.commentLabel')" :rows="2" :error="t('report.error')" />
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VSelect — field · ghost · error · disabled · VSearchField ( / )</p>
              <div class="kit-stack">
                <VSelect v-model="routeValue" :options="routeOptions" :label="t('admin.filter.route')" />
                <div class="kit-row">
                  <VSelect v-model="routeGhost" :options="routeOptions" variant="ghost" size="sm" :aria-label="t('admin.filter.route')" />
                  <VSelect :model-value="null" :options="routeOptions" size="sm" :aria-label="t('admin.filter.route')" disabled />
                </div>
                <VSelect :model-value="null" :options="routeOptions" :label="t('admin.filter.route')" :error="t('ui.rangeInvalid')" />
                <VSearchField
                  v-model="searchField"
                  :placeholder="t('admin.conversations.searchPlaceholder')"
                  shortcut="/"
                  @search="lastSearch = $event"
                />
                <p class="t-caption t-3">search → “{{ lastSearch }}”</p>
              </div>
            </div>
          </div>
        </section>

        <!-- ====================================================== choices -->
        <section id="choices" class="kit-sec" aria-labelledby="h-choices">
          <header class="kit-sec__head">
            <h2 id="h-choices" class="t-title-2" tabindex="-1">Choices</h2>
            <p class="t-body-sm t-3">VSwitch · VCheckbox · VChoiceChips · VSegmented · VTabs</p>
          </header>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VSwitch — description · label first · sm · disabled</p>
              <div class="kit-stack">
                <VSwitch v-model="blocked" :label="t('admin.user.block')" :description="t('admin.user.blockHint')" />
                <VSwitch v-model="notify" :label="t('admin.system.telegramBot')" label-first />
                <div class="kit-row">
                  <VSwitch v-model="agree" size="sm" :label="t('admin.system.analytics')" />
                  <VSwitch :model-value="true" disabled :label="t('admin.user.rolesLocked')" />
                </div>
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VCheckbox — boolean · group · indeterminate · disabled</p>
              <div class="kit-stack">
                <VCheckbox
                  :model-value="allChecked"
                  :indeterminate="someChecked"
                  :label="t('admin.channel.all')"
                  @update:model-value="toggleAll"
                />
                <div class="kit-indent kit-stack kit-stack--tight">
                  <VCheckbox v-for="c in allChannels" :key="c" v-model="channelsChecked" :value="c" :label="t(`admin.channel.${c}`)" />
                </div>
                <VCheckbox :model-value="true" disabled :label="t('admin.channel.desktop')" :description="t('comingSoon')" />
              </div>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VChoiceChips — single, deselectable (report reason) · multiple with icons · sm</p>
            <div class="kit-stack">
              <VChoiceChips v-model="reason" :options="reasonOptions" :aria-label="t('report.reasonLabel')" />
              <VChoiceChips v-model="multiChannels" :options="channelChoice" multiple :aria-label="t('admin.filter.channel')" />
              <VChoiceChips v-model="reason" :options="reasonOptions" size="sm" :aria-label="t('report.reasonLabel')" />
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VSegmented — channel filter · with icons · icon only · sm · block</p>
            <div class="kit-stack">
              <div class="kit-row">
                <VSegmented v-model="localChannel" :options="channelSegments" :aria-label="t('admin.filter.channel')" />
                <VSegmented v-model="viewMode" :options="viewSegments" size="sm" :aria-label="t('admin.nav.conversations')" />
                <VSegmented v-model="theme" :options="themeOptions" icon-only :aria-label="t('ui.theme')" />
              </div>
              <div class="kit-narrow">
                <VSegmented v-model="localChannel" :options="channelSegments" block size="sm" :aria-label="t('admin.filter.channel')" />
              </div>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VTabs — counts · panel slot · sm</p>
            <VTabs v-model="reportTab" :tabs="reportTabs" :aria-label="t('admin.nav.reports')">
              <template #default="{ value }">
                <p class="kit-tabpanel t-body-sm t-3">{{ t(`admin.reportStatus.${value}`) }} — {{ t('admin.empty.reportsNew') }}</p>
              </template>
            </VTabs>
            <VTabs v-model="traceTab" :tabs="traceTabs" size="sm" :aria-label="t('admin.page.turn.title')" />
          </div>
        </section>

        <!-- ====================================================== display -->
        <section id="display" class="kit-sec" aria-labelledby="h-display">
          <header class="kit-sec__head">
            <h2 id="h-display" class="t-title-2" tabindex="-1">Display</h2>
            <p class="t-body-sm t-3">VBadge · VAvatar · VKbd · VDivider · VCopy</p>
          </header>

          <div class="kit-spec">
            <p class="kit-spec__label">VBadge — neutral · good · warn · crit · brand · info · dot · sm · icon</p>
            <div class="kit-stack">
              <div class="kit-row">
                <VBadge>{{ t('admin.route.rules') }}</VBadge>
                <VBadge tone="good">{{ t('admin.reportStatus.resolved') }}</VBadge>
                <VBadge tone="warn">{{ t('admin.reportStatus.reviewing') }}</VBadge>
                <VBadge tone="crit">{{ t('admin.reason.unsafe') }}</VBadge>
                <VBadge tone="brand">{{ t('admin.reportStatus.new') }}</VBadge>
                <VBadge tone="info">RAG_ADMIN</VBadge>
                <VBadge tone="neutral" :icon="ShieldCheck">ADMIN</VBadge>
              </div>
              <div class="kit-row">
                <VBadge dot tone="good">{{ t('admin.status.ok') }}</VBadge>
                <VBadge dot tone="crit">{{ t('admin.status.error') }}</VBadge>
                <VBadge dot tone="warn">{{ t('admin.status.running') }}</VBadge>
                <VBadge dot>{{ t('admin.status.cancelled') }}</VBadge>
                <VBadge size="sm">{{ t('admin.title') }}</VBadge>
                <VBadge size="sm" tone="brand">3</VBadge>
              </div>
            </div>
          </div>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VAvatar — 24 · 28 · 32 · 40 · Cyrillic · broken photo → initials</p>
              <div class="kit-row kit-row--end">
                <VAvatar name="Aziza Karimova" :size="24" />
                <VAvatar name="Jasur Toshmatov" :size="28" />
                <VAvatar name="Oʻlmas Gʻaniyev" :size="32" />
                <VAvatar name="Малика Эргашева" :size="40" />
                <VAvatar name="y.mamajonov" :size="32" />
                <VAvatar name="Dilnoza Rahimova" src="/does-not-exist.png" :size="40" alt="Dilnoza Rahimova" />
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VKbd — default · inverse · sm</p>
              <div class="kit-row">
                <VKbd keys="mod+k" />
                <VKbd keys="mod+shift+o" />
                <VKbd keys="shift+enter" size="sm" />
                <VKbd :keys="['up', 'down']" size="sm" />
                <span class="kit-ink-chip"><VKbd keys="esc" tone="inverse" size="sm" /> {{ t('ui.close') }}</span>
              </div>
            </div>
          </div>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VDivider — plain · labelled · vertical</p>
              <div class="kit-stack">
                <VDivider />
                <VDivider :label="t('ui.last30')" spacing="sm" />
                <div class="kit-row">
                  <span class="t-body-sm">{{ t('admin.channel.web') }}</span>
                  <VDivider orientation="vertical" />
                  <span class="t-body-sm">{{ t('admin.channel.miniapp') }}</span>
                  <VDivider orientation="vertical" />
                  <span class="t-body-sm">{{ t('admin.channel.bot') }}</span>
                </div>
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VCopy — icon · labelled</p>
              <div class="kit-row">
                <code class="kit-code">req_8f2c41d0</code>
                <VCopy text="req_8f2c41d0" />
                <VCopy :text="() => JSON.stringify(rawFrames, null, 2)" :label="t('ui.copy')" size="md" />
              </div>
            </div>
          </div>
        </section>

        <!-- ====================================================== cards -->
        <section id="cards" class="kit-sec" aria-labelledby="h-cards">
          <header class="kit-sec__head">
            <h2 id="h-cards" class="t-title-2" tabindex="-1">Cards &amp; empty</h2>
            <p class="t-body-sm t-3">VCard · VEmpty · VSkeleton</p>
          </header>

          <div class="kit-grid kit-grid--3">
            <VCard :title="t('admin.overview.recentReports')" :description="t('admin.page.reports.subtitle')">
              <template #actions>
                <VIconButton :icon="MoreHorizontal" :label="t('ui.moreActions')" size="sm" />
              </template>
              <ul class="kit-mini-list">
                <li v-for="p in PEOPLE.slice(0, 3)" :key="p.id">
                  <VAvatar :name="p.name" :size="24" />
                  <span class="truncate">{{ p.name }}</span>
                  <VBadge size="sm" tone="crit">{{ t('admin.reason.wrong') }}</VBadge>
                </li>
              </ul>
              <template #footer>
                <VButton variant="ghost" size="sm" :icon-end="ArrowRight">{{ t('admin.overview.viewAll') }}</VButton>
              </template>
            </VCard>
            <VCard interactive :title="t('admin.usage.service.assistant')" :description="t('admin.usage.p95ByService')">
              <p class="kit-big">{{ fmtMs(6240, loc) }}</p>
              <VSparkline :values="p95.slice(-14)" color="--viz-2" fluid :height="32" area decorative />
            </VCard>
            <VCard href="#cards" padding="lg" :title="t('admin.nav.system')" :description="t('admin.page.system.subtitle')">
              <VBadge dot tone="good">{{ t('admin.system.healthy') }}</VBadge>
            </VCard>
          </div>

          <div class="kit-grid kit-grid--3">
            <VCard padding="none">
              <VEmpty :icon="Inbox" :title="t('admin.empty.reportsNew')" :description="t('admin.page.reports.subtitle')">
                <VButton size="sm" variant="secondary">{{ t('admin.common.refresh') }}</VButton>
              </VEmpty>
            </VCard>
            <VCard padding="none">
              <VEmpty compact :icon="Search" :title="t('admin.empty.filtered')" />
            </VCard>
            <VCard>
              <div class="kit-stack">
                <div class="kit-row">
                  <VSkeleton circle :width="32" />
                  <div class="kit-grow kit-stack kit-stack--tight">
                    <VSkeleton width="60%" />
                    <VSkeleton width="35%" />
                  </div>
                </div>
                <VSkeleton :lines="3" />
                <VSkeleton :height="96" radius="md" width="100%" />
              </div>
            </VCard>
          </div>
        </section>

        <!-- ====================================================== overlays -->
        <section id="overlays" class="kit-sec" aria-labelledby="h-overlays">
          <header class="kit-sec__head">
            <h2 id="h-overlays" class="t-title-2" tabindex="-1">Overlays</h2>
            <p class="t-body-sm t-3">VTooltip · VPopover · VMenu · VDialog · VSheet</p>
          </header>

          <div class="kit-spec">
            <p class="kit-spec__label">VTooltip — placements · shortcut · group hover (instant between siblings)</p>
            <div class="kit-row">
              <VTooltip :text="t('report.reportConversation')" placement="top">
                <VButton variant="outline" size="sm">top</VButton>
              </VTooltip>
              <VTooltip :text="t('admin.trace.openTrace')" placement="right">
                <VButton variant="outline" size="sm">right</VButton>
              </VTooltip>
              <VTooltip :text="t('ui.copy')" placement="bottom">
                <VButton variant="outline" size="sm">bottom</VButton>
              </VTooltip>
              <VTooltip :text="t('admin.nav.search')" shortcut="mod+k" placement="left">
                <VButton variant="outline" size="sm">left + ⌘K</VButton>
              </VTooltip>
              <div class="kit-toolbar">
                <VIconButton :icon="Copy" :label="t('ui.copy')" size="sm" />
                <VIconButton :icon="Flag" :label="t('report.reportAnswer')" size="sm" />
                <VIconButton :icon="Link2" :label="t('admin.common.copyLink')" size="sm" />
                <VIconButton :icon="MoreHorizontal" :label="t('ui.moreActions')" size="sm" />
              </div>
            </div>
          </div>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VPopover — trigger slot · focus returns</p>
              <VPopover :aria-label="t('ui.filters')" padding="md" :width="260">
                <template #trigger>
                  <VButton variant="outline" size="sm" :icon="SlidersHorizontal">{{ t('ui.filters') }}</VButton>
                </template>
                <template #default="{ close }">
                  <div class="kit-stack">
                    <p class="t-title-3">{{ t('admin.filter.channel') }}</p>
                    <VCheckbox v-for="c in allChannels" :key="c" v-model="popChannels" :value="c" :label="t(`admin.channel.${c}`)" />
                    <div class="kit-row kit-row--right">
                      <VButton variant="ghost" size="sm" @click="close()">{{ t('ui.cancel') }}</VButton>
                      <VButton variant="primary" size="sm" @click="close()">{{ t('ui.apply') }}</VButton>
                    </div>
                  </div>
                </template>
              </VPopover>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VMenu — items array (shortcut · hint · checkbox · danger · disabled) · slot items</p>
              <div class="kit-row">
                <VMenu :items="menuItems" :aria-label="t('ui.moreActions')">
                  <template #trigger>
                    <VIconButton :icon="MoreHorizontal" :label="t('ui.moreActions')" variant="outline" />
                  </template>
                </VMenu>
                <VMenu :aria-label="t('ui.filters')" :min-width="220">
                  <template #trigger>
                    <VButton variant="ghost" size="sm" :icon="SlidersHorizontal">{{ t('ui.filters') }}</VButton>
                  </template>
                  <VMenuItem kind="label">{{ t('ui.dateRange') }}</VMenuItem>
                  <VMenuItem kind="radio" :checked="menuSort === 'new'" @select="menuSort = 'new'">{{ t('ui.sortDesc') }}</VMenuItem>
                  <VMenuItem kind="radio" :checked="menuSort === 'old'" @select="menuSort = 'old'">{{ t('ui.sortAsc') }}</VMenuItem>
                  <VMenuItem kind="separator" />
                  <VMenuItem :icon="FileText" shortcut="mod+shift+e">{{ t('admin.trace.openDoc') }}</VMenuItem>
                  <VMenuItem :icon="Trash2" danger>{{ t('ui.delete') }}</VMenuItem>
                </VMenu>
              </div>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VDialog — report (sm, error then success) · confirm (alert) · lg · VSheet — right · bottom</p>
            <div class="kit-row">
              <VButton :icon="Flag" @click="reportOpen = true">{{ t('report.title') }}</VButton>
              <VButton variant="danger" @click="confirmOpen = true">{{ t('admin.user.block') }}</VButton>
              <VButton variant="outline" @click="largeOpen = true">{{ t('admin.trace.raw') }}</VButton>
              <VButton variant="outline" :icon="User" @click="sheetOpen = true">{{ t('admin.nav.users') }}</VButton>
              <VButton variant="ghost" @click="bottomOpen = true">Bottom sheet</VButton>
            </div>
          </div>

          <!-- Xabar berish oynasi (spec §4.4) -->
          <VDialog v-model:open="reportOpen" :title="t('report.title')" :description="t('report.subtitle')" :dismissible="!reportSending">
            <div class="kit-stack">
              <VChoiceChips v-model="reportReason" :options="reasonOptions" size="sm" :aria-label="t('report.reasonLabel')" />
              <VTextarea
                v-model="reportComment"
                :placeholder="t('report.placeholder')"
                :aria-label="t('report.commentLabel')"
                :rows="4"
                :maxlength="REPORT_COMMENT_MAX"
                :counter-from="1800"
                data-autofocus
              />
              <p v-if="reportError" class="kit-error" role="alert">{{ reportError }}</p>
            </div>
            <template #footer="{ close }">
              <VButton variant="ghost" :disabled="reportSending" @click="close()">{{ t('report.cancel') }}</VButton>
              <VButton variant="primary" :loading="reportSending" @click="sendReport">{{ t('report.send') }}</VButton>
            </template>
          </VDialog>

          <VDialog
            v-model:open="confirmOpen"
            alert
            :title="t('admin.confirm.blockTitle', { name: 'Jasur Toshmatov' })"
            :description="t('admin.confirm.blockBody')"
          >
            <template #footer="{ close }">
              <VButton variant="ghost" @click="close()">{{ t('ui.cancel') }}</VButton>
              <VButton
                variant="danger"
                @click="
                  () => {
                    close()
                    toast.show(t('admin.toast.blocked'))
                  }
                "
              >
                {{ t('admin.user.block') }}
              </VButton>
            </template>
          </VDialog>

          <VDialog v-model:open="largeOpen" size="lg" :title="t('admin.trace.raw')" :description="`${t('admin.trace.requestId')} · req_8f2c41d0`">
            <VJson :data="rawFrames" bare :expand-depth="2" :max-height="420" />
          </VDialog>

          <VSheet v-model:open="sheetOpen" :width="560" :aria-label="PEOPLE[0].name">
            <template #header>
              <div class="kit-sheet-head">
                <VAvatar :name="PEOPLE[0].name" :size="40" />
                <div class="kit-grow">
                  <p class="t-title-3">{{ PEOPLE[0].name }}</p>
                  <p class="t-body-sm t-3">{{ PEOPLE[0].login }} · {{ PEOPLE[0].dept }}</p>
                </div>
              </div>
            </template>
            <div class="kit-stack kit-stack--loose">
              <div class="kit-sheet-stats">
                <VStat variant="plain" :label="t('admin.user.turns')" :value="128" />
                <VStat variant="plain" :label="t('admin.user.reports')" :value="3" />
                <VStat variant="plain" :label="t('admin.user.medianTtft')" :value="2140" :format="msFormat" />
                <VStat variant="plain" :label="t('admin.user.voiceTurns')" :value="17" />
              </div>
              <div class="kit-stack">
                <p class="t-title-3">{{ t('admin.user.roles') }}</p>
                <VChoiceChips v-model="sheetRoles" :options="roleChoice" multiple size="sm" :aria-label="t('admin.user.roles')" />
                <p class="t-caption t-3">{{ t('admin.user.rolesSource.admin') }}</p>
              </div>
              <VDivider />
              <div class="kit-stack">
                <p class="t-title-3">{{ t('admin.user.access') }}</p>
                <VSwitch v-model="sheetBlocked" :label="t('admin.user.block')" :description="t('admin.user.blockHint')" label-first />
                <div>
                  <VButton variant="outline" size="sm" :icon="LogOut">{{ t('admin.user.signOutEverywhere') }}</VButton>
                </div>
              </div>
            </div>
            <template #footer="{ close }">
              <VButton variant="ghost" @click="close()">{{ t('ui.close') }}</VButton>
              <VButton variant="primary" @click="toast.success(t('admin.toast.rolesSaved'))">{{ t('ui.save') }}</VButton>
            </template>
          </VSheet>

          <VSheet v-model:open="bottomOpen" side="bottom" :title="t('admin.nav.menu')">
            <ul class="kit-sheet-nav">
              <li v-for="k in ['overview', 'conversations', 'reports', 'users', 'usage', 'system']" :key="k">
                <a href="#overlays" @click.prevent="bottomOpen = false">{{ t(`admin.nav.${k}`) }}</a>
              </li>
            </ul>
          </VSheet>
        </section>

        <!-- ====================================================== feedback -->
        <section id="feedback" class="kit-sec" aria-labelledby="h-feedback">
          <header class="kit-sec__head">
            <h2 id="h-feedback" class="t-title-2" tabindex="-1">Feedback</h2>
            <p class="t-body-sm t-3">useToast · VToastHost · VSpinner · VSkeleton</p>
          </header>

          <div class="kit-spec">
            <p class="kit-spec__label">Toast — neutral · good · crit · action · sticky (duration 0) · max 3 on screen, hover pauses</p>
            <div class="kit-row">
              <VButton size="sm" @click="toastNeutral">neutral</VButton>
              <VButton size="sm" @click="toastGood">good</VButton>
              <VButton size="sm" @click="toastCrit">crit</VButton>
              <VButton size="sm" @click="toastAction">action</VButton>
              <VButton size="sm" @click="toastSticky">sticky</VButton>
              <VButton size="sm" variant="ghost" @click="toast.clear()">{{ t('ui.clearAll') }}</VButton>
            </div>
          </div>

          <div class="kit-grid kit-grid--2">
            <div class="kit-spec">
              <p class="kit-spec__label">VSpinner — 12 · 16 · 20 · 24 · labelled</p>
              <div class="kit-row kit-row--end">
                <VSpinner :size="12" />
                <VSpinner />
                <VSpinner :size="20" />
                <VSpinner :size="24" :label="t('ui.loading')" />
                <span class="t-body-sm t-3">{{ t('ui.loading') }}</span>
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VSkeleton — first load only (then previous data at 50%)</p>
              <div class="kit-row">
                <VSkeleton :width="96" :height="28" radius="sm" />
                <VSkeleton :width="140" />
                <VSkeleton circle :width="24" />
                <VSkeleton :width="64" :height="20" radius="full" />
              </div>
            </div>
          </div>
        </section>

        <!-- ====================================================== filters -->
        <section id="filters" class="kit-sec" aria-labelledby="h-filters">
          <header class="kit-sec__head">
            <h2 id="h-filters" class="t-title-2" tabindex="-1">Filters</h2>
            <p class="t-body-sm t-3">VDateRange · useAdminFilters · VFilterBar · VFilterChip · VSearchField · VCommandPalette</p>
          </header>

          <div class="kit-spec">
            <p class="kit-spec__label">Global admin filter — synced to this page’s URL (router.replace, no history)</p>
            <div class="kit-filter-row">
              <VDateRange v-model="range" :max="isoToday" />
              <VSegmented v-model="filterChannel" :options="channelSegments" size="sm" :aria-label="t('admin.filter.channel')" />
              <VButton v-if="!isDefault" variant="ghost" size="sm" @click="resetFilters">{{ t('ui.clear') }}</VButton>
            </div>
            <div class="kit-grid kit-grid--2">
              <VJson :data="{ query: filterQuery, params }" :label="'useAdminFilters'" :expand-depth="3" />
              <p class="t-body-sm t-3">
                API params are exact instants (local midnight → ISO, <code class="kit-code">to</code> exclusive, capped at now), the URL keeps
                readable local days. Default preset 30d and channel “all” are omitted from the URL.
              </p>
            </div>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VFilterBar — search + chips (multi with dots · single · toggle · remote search) · clear all</p>
            <VFilterBar :active="!!fbSearch" @clear="fbSearch = ''">
              <template #search>
                <VSearchField v-model="fbSearch" :placeholder="t('admin.conversations.searchPlaceholder')" shortcut="/" :hotkey="false" />
              </template>
              <VFilterChip v-model="fbChannels" :label="t('admin.filter.channel')" :options="channelFilterOptions" multiple />
              <VFilterChip v-model="fbRoute" :label="t('admin.filter.route')" :options="routeFilterOptions" />
              <VFilterChip v-model="fbStatus" :label="t('admin.filter.status')" :options="statusFilterOptions" />
              <VFilterChip
                v-model="fbUser"
                :label="t('admin.filter.user')"
                :options="userFilterOptions"
                :icon="User"
                searchable
                remote
                :loading="fbUserLoading"
                @search="onUserSearch"
              />
              <VFilterChip v-model="fbReported" :label="t('admin.filter.reported')" :icon="Flag" toggle />
              <template #end>
                <span class="t-body-sm t-3 tabular">{{ t('ui.resultCount', { n: fbMatches }, fbMatches) }}</span>
              </template>
            </VFilterBar>
          </div>

          <div class="kit-spec">
            <p class="kit-spec__label">VCommandPalette — ⌘K / Ctrl K · pages + async people search · recents</p>
            <div class="kit-row">
              <VButton variant="outline" :icon="Search" @click="palette.open()">
                {{ t('admin.nav.search') }}
                <template #iconEnd><VKbd keys="mod+k" size="sm" /></template>
              </VButton>
              <VButton variant="ghost" size="sm" @click="palette.open('aziza')">open('aziza')</VButton>
            </div>
          </div>
        </section>

        <!-- ====================================================== table -->
        <section id="table" class="kit-sec" aria-labelledby="h-table">
          <header class="kit-sec__head">
            <h2 id="h-table" class="t-title-2" tabindex="-1">Data table</h2>
            <p class="t-body-sm t-3">VDataTable — 30 rows · sort · keyboard rows · refetch keeps rows at 50% · cards on phone</p>
          </header>

          <div class="kit-row">
            <VSwitch v-model="tableLoading" size="sm" :label="t('ui.loading')" />
            <VSwitch v-model="tableDense" size="sm" label="Dense" />
            <VSwitch v-model="tableEmpty" size="sm" :label="t('admin.empty.generic')" />
          </div>

          <VDataTable
            :rows="shownRows"
            :columns="tableColumns"
            row-key="id"
            :loading="tableLoading"
            :dense="tableDense"
            :selected-key="tableSelected"
            :label="t('admin.nav.conversations')"
            @row-click="onRowClick"
          >
            <template #cell-user="{ row }">
              <span class="kit-cell-user">
                <VAvatar :name="row.user" :size="24" />
                <span class="truncate">{{ row.user }}</span>
              </span>
            </template>
            <template #cell-channel="{ row }">
              <span class="kit-cell-channel">
                <component :is="CHANNEL_ICON[row.channel]" :size="16" :stroke-width="1.75" :style="{ color: `var(--ch-${row.channel})` }" aria-hidden="true" />
                {{ t(`admin.channel.${row.channel}`) }}
              </span>
            </template>
            <template #cell-question="{ row }">
              <span class="truncate">{{ row.question }}</span>
            </template>
            <template #cell-route="{ row }">
              <VBadge v-if="row.route" size="sm" :tone="ROUTE_TONE[row.route] ?? 'neutral'">{{ t(`admin.route.${row.route}`) }}</VBadge>
              <span v-else class="t-3">—</span>
            </template>
            <template #cell-status="{ row }">
              <VBadge dot :tone="STATUS_TONE[row.status]">{{ t(`admin.status.${row.status}`) }}</VBadge>
            </template>
            <template #empty>
              <VEmpty compact :icon="MessagesSquare" :title="t('admin.empty.turns')" />
            </template>
            <template #footer>
              <VButton variant="ghost" size="sm" :loading="loadingMore" @click="loadMore">{{ t('ui.loadMore') }}</VButton>
            </template>
          </VDataTable>
        </section>

        <!-- ====================================================== stats -->
        <section id="stats" class="kit-sec" aria-labelledby="h-stats">
          <header class="kit-sec__head">
            <h2 id="h-stats" class="t-title-2" tabindex="-1">Stats</h2>
            <p class="t-body-sm t-3">VStat — delta vs previous period (colour only when direction has meaning) · 14-point sparkline</p>
          </header>
          <div class="kit-row">
            <VSwitch v-model="kpiLoading" size="sm" :label="t('ui.loading')" />
          </div>
          <div class="kit-kpis">
            <VStat
              :label="t('admin.kpi.turns')"
              :value="sum(totalSeries)"
              :previous="Math.round(sum(totalSeries) * 0.88)"
              :trend="spark14(totalSeries)"
              :delta-label="t('admin.kpi.vsPrevious')"
              :loading="kpiLoading"
              to="/admin/conversations"
            />
            <VStat
              :label="t('admin.kpi.activeUsers')"
              :value="142"
              :previous="131"
              :trend="spark14(botSeries)"
              trend-color="--viz-3"
              :delta-label="t('admin.kpi.vsPrevious')"
              :loading="kpiLoading"
            />
            <VStat
              :label="t('admin.kpi.medianTtft')"
              :value="2140"
              :previous="2380"
              :format="msFormat"
              :positive-is-good="false"
              :trend="spark14(p50)"
              trend-color="--viz-2"
              :delta-label="t('admin.kpi.vsPrevious')"
              :loading="kpiLoading"
            />
            <VStat
              :label="t('admin.kpi.errorRate')"
              :value="0.021"
              :previous="0.018"
              :format="(v: number) => fmtPercent(v, 1, loc)"
              :positive-is-good="false"
              :trend="errorSpark"
              trend-color="--viz-8"
              :delta-label="t('admin.kpi.vsPrevious')"
              :loading="kpiLoading"
            />
            <VStat :label="t('admin.kpi.newReports')" :value="7" :positive-is-good="null" :delta="0" :loading="kpiLoading" to="/admin/reports" />
          </div>
          <div class="kit-grid kit-grid--4">
            <VStat variant="plain" :label="t('admin.usage.requests')" :value="fmtCompact(48210, loc)" />
            <VStat variant="plain" :label="t('admin.usage.units.audioSec')" :value="312" :unit="'min'" />
            <VStat variant="plain" :label="t('admin.system.database')" :value="'184 MB'" />
            <VStat variant="plain" :label="t('admin.system.dropped')" :value="null" />
          </div>
        </section>

        <!-- ====================================================== charts -->
        <section id="charts" class="kit-sec" aria-labelledby="h-charts">
          <header class="kit-sec__head">
            <h2 id="h-charts" class="t-title-2" tabindex="-1">Charts</h2>
            <p class="t-body-sm t-3">Hand-written SVG · fixed channel colours · crosshair tooltip · table view · refetch keeps frame</p>
          </header>
          <div class="kit-row">
            <VSwitch v-model="chartLoading" size="sm" :label="t('ui.loading')" />
          </div>

          <div class="kit-grid kit-grid--wide">
            <VCard :title="t('admin.overview.activity')" :description="t('ui.last30')">
              <VAreaChart
                :series="activitySeries"
                :x="days"
                stacked
                :height="260"
                :y-format="numFormat"
                :loading="chartLoading"
                :label="t('admin.overview.activity')"
              />
            </VCard>
            <VCard :title="t('admin.overview.channels')">
              <div class="kit-stack kit-stack--loose">
                <VStackedBar :parts="channelParts" :value-format="numFormat" :label="t('admin.overview.channels')" :loading="chartLoading" />
                <VStackedBar
                  :parts="channelParts"
                  legend="list"
                  :thickness="8"
                  :value-format="numFormat"
                  :label="t('admin.overview.channels')"
                />
              </div>
            </VCard>
          </div>

          <div class="kit-grid kit-grid--3">
            <VCard :title="t('admin.overview.routes')">
              <VBarChart :data="routeBars" :value-format="numFormat" :loading="chartLoading" :label="t('admin.overview.routes')" />
            </VCard>
            <VCard :title="t('admin.overview.latency')" :description="t('admin.kpi.medianTtftHint')">
              <VLineChart
                :series="latencySeries"
                :x="days"
                :height="220"
                :y-format="msFormat"
                :loading="chartLoading"
                :label="t('admin.overview.latency')"
              />
            </VCard>
            <VCard :title="t('admin.overview.topDocs')">
              <ul class="kit-docs">
                <li v-for="(d, i) in ['Mehnat taʼtillari toʻgʻrisidagi nizom', 'Ichki mehnat tartibi qoidalari', 'Xizmat safarlari tartibi', 'Masofaviy ish siyosati', 'Kasallik varaqasi yoʻriqnomasi']" :key="d">
                  <span class="truncate t-body-sm">{{ d }}</span>
                  <VMeter :value="[412, 288, 171, 96, 64][i]" :max="412" size="sm" :label="d" :value-text="String([412, 288, 171, 96, 64][i])" />
                  <span class="t-body-sm t-3 tabular">{{ [412, 288, 171, 96, 64][i] }}</span>
                </li>
              </ul>
            </VCard>
          </div>

          <div class="kit-grid kit-grid--2">
            <VCard :title="t('admin.usage.p95ByService')">
              <VBarChart
                :data="serviceBars"
                orientation="vertical"
                :height="240"
                :value-format="msFormat"
                :tick-format="(v: number) => fmtMs(v, loc)"
                color="--viz-1"
                :label="t('admin.usage.p95ByService')"
                :loading="chartLoading"
              />
            </VCard>
            <VCard :title="t('admin.usage.overTime')" :description="'VSparkline · small multiples'">
              <ul class="kit-multiples">
                <li v-for="(values, service) in SERVICE_REQ" :key="service">
                  <span class="t-body-sm truncate">{{ t(`admin.usage.service.${service}`) }}</span>
                  <VSparkline :values="values" fluid :height="24" :color="service === 'stt_gapi' ? '--viz-2' : '--viz-1'" decorative />
                  <span class="t-body-sm t-3 tabular">{{ fmtCompact(sum(values), loc) }}</span>
                </li>
              </ul>
            </VCard>
          </div>

          <div class="kit-grid kit-grid--3">
            <div class="kit-spec">
              <p class="kit-spec__label">VMeter — score · warn · crit (invert: low is bad)</p>
              <div class="kit-stack">
                <div class="kit-meter-row"><span class="t-caption t-3">{{ t('admin.trace.score') }}</span><VMeter :value="0.87" invert :warn-at="0.6" :crit-at="0.4" :label="t('admin.trace.score')" /><span class="t-mono">0.87</span></div>
                <div class="kit-meter-row"><span class="t-caption t-3">{{ t('admin.trace.score') }}</span><VMeter :value="0.54" invert :warn-at="0.6" :crit-at="0.4" :label="t('admin.trace.score')" /><span class="t-mono">0.54</span></div>
                <div class="kit-meter-row"><span class="t-caption t-3">{{ t('admin.trace.score') }}</span><VMeter :value="0.31" invert :warn-at="0.6" :crit-at="0.4" :label="t('admin.trace.score')" /><span class="t-mono">0.31</span></div>
                <div class="kit-meter-row"><span class="t-caption t-3">TTS</span><VMeter :value="3" :max="4" :warn-at="3" :crit-at="4" label="TTS" value-text="3/4" /><span class="t-mono">3/4</span></div>
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VChartLegend — toggleable · list · VChartTooltip (static)</p>
              <div class="kit-stack">
                <VChartLegend :items="legendView" toggleable @toggle="toggleLegend" />
                <VChartLegend :items="legendList" layout="list" />
                <div class="kit-tooltip-stage">
                  <VChartTooltip
                    visible
                    :x="24"
                    :y="16"
                    :bounds-width="320"
                    :bounds-height="140"
                    :title="fmtDate(days[29], loc)"
                    :rows="tooltipRows"
                  />
                </div>
              </div>
            </div>
            <div class="kit-spec">
              <p class="kit-spec__label">VChartTable — the accessible view every chart can toggle to</p>
              <VChartTable :columns="tableColumnsChart" :rows="tableRowsChart" :caption="t('admin.usage.p95ByService')" />
            </div>
          </div>
        </section>

        <!-- ====================================================== trace -->
        <section id="trace" class="kit-sec" aria-labelledby="h-trace">
          <header class="kit-sec__head">
            <h2 id="h-trace" class="t-title-2" tabindex="-1">Trace</h2>
            <p class="t-body-sm t-3">VWaterfall — spans + points, ↑/↓ + Enter · VJson — collapsible, redacted secrets, copy</p>
          </header>
          <div class="kit-row">
            <VSwitch v-model="traceError" size="sm" :label="t('admin.status.error')" />
          </div>

          <div class="kit-trace">
            <VCard :title="t('admin.trace.waterfall')" :description="`${t('admin.trace.ttft')} ${fmtMs(2300, loc)} · ${t('admin.trace.total')} ${fmtMs(traceError ? 3100 : 7700, loc)}`">
              <VWaterfall
                :rows="traceRows"
                :kind-colors="kindColors"
                :selected-id="traceSelected"
                :label="t('admin.trace.waterfall')"
                @select="traceSelected = $event"
              />
              <template #footer>
                <p v-if="traceSelectedRow" class="t-body-sm t-3">
                  <strong class="kit-strong">{{ traceSelectedRow.label }}</strong>
                  <template v-if="traceSelectedRow.sub"> · {{ traceSelectedRow.sub }}</template>
                  · +{{ fmtMs(traceSelectedRow.startMs, loc) }}
                  <template v-if="traceSelectedRow.durMs"> · {{ fmtMs(traceSelectedRow.durMs, loc) }}</template>
                </p>
              </template>
            </VCard>
            <VCard :title="t('admin.trace.raw')" padding="sm">
              <VJson :data="rawFrames" :expand-depth="1" :max-height="480" bare :label="t('admin.trace.raw')" />
            </VCard>
          </div>
          <div class="kit-spec">
            <p class="kit-spec__label">VWaterfall — loading · empty</p>
            <div class="kit-grid kit-grid--2">
              <VWaterfall :rows="[]" loading :label="t('ui.loading')" />
              <VWaterfall :rows="[]" :label="t('admin.trace.noEvents')" />
            </div>
          </div>
        </section>

        <footer class="kit-foot t-caption t-4">Venera UI · {{ isoToday }}</footer>
      </main>
    </div>

    <!-- Bildirishnomalar joyi App.vue da (bitta) - bu yerda ikkinchisi takror chiqarardi. -->
    <VCommandPalette :placeholder="t('admin.palette.placeholder')" />
  </div>
</template>

<style scoped>
.kit {
  min-height: 100dvh;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
}

/* ---- tepa panel ---- */
.kit-top {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  gap: var(--s-4);
  height: 56px;
  padding: 0 var(--gutter);
  background: color-mix(in srgb, var(--bg) 86%, transparent);
  backdrop-filter: saturate(1.4) blur(12px);
  -webkit-backdrop-filter: saturate(1.4) blur(12px);
  border-bottom: 1px solid var(--line);
}
.kit-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  border-radius: var(--r-xs);
}
.kit-spark {
  display: inline-flex;
  color: var(--brand);
}
.kit-word {
  font-size: var(--fs-body);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.kit-tag {
  padding: 1px var(--s-1_5);
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
}
@media (max-width: 399.98px) {
  .kit-tag {
    display: none;
  }
}
.kit-top__end {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin-left: auto;
}

/* ---- tana ---- */
.kit-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  max-width: 1360px;
  margin: 0 auto;
  padding: 0 var(--gutter);
}
.kit-toc {
  display: none;
}
@media (min-width: 1120px) {
  .kit-body {
    grid-template-columns: 184px minmax(0, 1fr);
    gap: var(--s-12);
  }
  .kit-toc {
    display: block;
    position: sticky;
    top: 56px;
    align-self: start;
    max-height: calc(100dvh - 56px);
    overflow-y: auto;
    padding: var(--s-10) 0;
  }
}
.kit-toc ul {
  display: flex;
  flex-direction: column;
  gap: var(--s-0_5);
  margin: 0;
  padding: 0;
  list-style: none;
}
.kit-toc a {
  display: block;
  padding: var(--s-1_5) var(--s-3);
  border-radius: var(--r-sm);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  transition:
    color var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .kit-toc a:hover {
    color: var(--text);
    background: var(--fill);
  }
}
.kit-toc a.is-active {
  color: var(--text);
  font-weight: 500;
}

.kit-main {
  min-width: 0;
  padding: var(--s-12) 0 var(--s-24);
}
.kit-hero {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  padding-bottom: var(--s-8);
}

/* ---- bo'lim ---- */
.kit-sec {
  display: flex;
  flex-direction: column;
  gap: var(--s-8);
  padding: var(--s-16) 0 0;
  scroll-margin-top: 56px;
}
.kit-sec + .kit-sec {
  margin-top: var(--s-10);
  border-top: 1px solid var(--line);
}
.kit-sec__head {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
}
.kit-sec__head h2:focus {
  outline: none;
}

.kit-spec {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
  padding: var(--s-6);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
@media (max-width: 767.98px) {
  .kit-spec {
    padding: var(--s-4);
  }
}
.kit-spec__label {
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
}

.kit-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-3);
  min-width: 0;
}
.kit-row--end {
  align-items: flex-end;
}
.kit-row--right {
  justify-content: flex-end;
}
.kit-stack {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}
.kit-stack--tight {
  gap: var(--s-2);
}
.kit-stack--loose {
  gap: var(--s-6);
}
.kit-indent {
  padding-left: var(--s-6);
}
.kit-grow {
  flex: 1;
  min-width: 0;
}
.kit-narrow {
  max-width: 360px;
}

.kit-grid {
  display: grid;
  gap: var(--s-6);
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 768px) {
  .kit-grid--2,
  .kit-grid--3,
  .kit-grid--wide {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .kit-grid--4 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (min-width: 1120px) {
  .kit-grid--3 {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .kit-grid--4 {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .kit-grid--wide {
    grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  }
}

.kit-code {
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
  color: var(--text-3);
}
.kit-strong {
  color: var(--text);
  font-weight: 600;
}
.kit-error {
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

/* ---- foundations ---- */
.kit-swatches {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: var(--s-4);
}
.kit-swatch {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  min-width: 0;
}
.kit-swatch__chip {
  height: 56px;
  border-radius: var(--r-md);
  box-shadow: inset 0 0 0 1px var(--line);
}
.kit-type {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.kit-type__row {
  display: grid;
  grid-template-columns: 136px minmax(0, 1fr);
  align-items: baseline;
  gap: var(--s-4);
}
@media (max-width: 767.98px) {
  .kit-type__row {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--s-1);
  }
}
.kit-radius,
.kit-elev {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
}
.kit-radius span {
  width: 56px;
  height: 56px;
  background: var(--fill);
  border: 1px solid var(--line-strong);
}
.kit-elev span {
  width: 88px;
  height: 56px;
  border-radius: var(--r-md);
  background: var(--surface);
}

/* ---- display ---- */
.kit-ink-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-1) var(--s-2);
  border-radius: var(--r-xs);
  background: var(--ink);
  color: var(--on-ink);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.kit-toolbar {
  display: inline-flex;
  gap: var(--s-0_5);
  padding: var(--s-0_5);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
}
.kit-tabpanel {
  padding-top: var(--s-4);
}

/* ---- cards ---- */
.kit-mini-list {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.kit-mini-list li {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  font-size: var(--fs-body-sm);
}
.kit-mini-list li .truncate {
  flex: 1;
}
.kit-big {
  margin-bottom: var(--s-3);
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.022em;
}

/* ---- overlays ---- */
.kit-sheet-stats {
  display: grid;
  gap: var(--s-4);
  grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
}
.kit-sheet-head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-width: 0;
}
.kit-sheet-nav {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.kit-sheet-nav a {
  display: block;
  padding: var(--s-3) var(--s-2);
  border-radius: var(--r-sm);
  font-weight: 500;
}
@media (hover: hover) {
  .kit-sheet-nav a:hover {
    background: var(--fill);
  }
}

/* ---- filters ---- */
.kit-filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2);
}

/* ---- table ---- */
.kit-cell-user,
.kit-cell-channel {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  max-width: 100%;
}

/* ---- stats ---- */
.kit-kpis {
  display: grid;
  gap: var(--s-4);
  grid-template-columns: repeat(auto-fit, minmax(176px, 1fr));
}

/* ---- charts ---- */
.kit-docs,
.kit-multiples {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.kit-docs li {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) 40px;
  align-items: center;
  gap: var(--s-3);
}
.kit-multiples li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) 48px;
  align-items: center;
  gap: var(--s-3);
}
.kit-docs .tabular,
.kit-multiples .tabular {
  text-align: right;
}
.kit-meter-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) 40px;
  align-items: center;
  gap: var(--s-3);
}
.kit-meter-row .t-mono {
  text-align: right;
}
.kit-tooltip-stage {
  position: relative;
  height: 140px;
  border-radius: var(--r-md);
  background: var(--bg-subtle);
  overflow: hidden;
}

/* ---- trace ---- */
.kit-trace {
  display: grid;
  gap: var(--s-6);
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 1120px) {
  .kit-trace {
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  }
}

.kit-foot {
  padding-top: var(--s-16);
}
</style>
