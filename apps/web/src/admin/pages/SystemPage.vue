<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { AudioLines, Bot, Flag, KeyRound, Mic, ScrollText, TriangleAlert, Users, Waypoints } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VCard from '../../ui/VCard.vue'
import VDataTable from '../../ui/VDataTable.vue'
import type { DataTableColumn } from '../../ui/VDataTable.vue'
import VDateRange from '../../ui/VDateRange.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VMeter from '../../ui/charts/VMeter.vue'
import { fmtNumber } from '../../ui/format'
import { getSystem } from '../api'
import type { AuditEntry, HealthDetail } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'
import UserCell from '../components/UserCell.vue'
import { fmtBytes } from '../components/units'
import { useAdminQuery } from '../components/useAdminQuery'

// "Tizim" (spec §4.5.7): har bir tashqi bog'liqlikning holati (`/api/health/detail`
// bilan bir xil tashxis), sozlamalar (faqat yoqilgan/o'chiq - qiymatlar hech qachon
// ko'rsatilmaydi), analitika ombori va admin amallari jurnali.
//
// Holat "hozir" haqida - davr filtri unga ta'sir qilmaydi. Davr faqat audit jurnalini
// kesadi, shuning uchun sana tanlovi o'sha kartaning o'zida turadi.
const { t, te, locale } = useI18n({ useScope: 'global' })
const { range, params, withFilters } = useAdminFilters()
// Tizim so'rovi filtrsiz: global parametrlarga bog'lanmasin (davr o'zgarsa qayta so'ralmaydi).
const q = useAdminQuery((_p: null, signal: AbortSignal) => getSystem(signal), { params: null })

const sys = computed(() => q.data.value)
const num = (v: number) => fmtNumber(v, locale.value)

/* ---- tashxisdan xavfsiz o'qish (shakl server bilan birga o'zgaradi) ---- */

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)
const int = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

type Health = 'healthy' | 'degraded' | 'down' | 'unknown' | 'off'

interface HealthCard {
  key: string
  name: string
  icon: Component
  status: Health
  /** Holat nomini almashtirish ("Sozlanmagan", "Ulangan"). */
  label?: string
  detail?: string | null
  meter?: { value: number; max: number; label: string }
}

function upstreamStatus(v: unknown): Health {
  const s = str(rec(v)?.status)
  if (s === 'ok') return 'healthy'
  if (s === 'degraded') return 'degraded'
  if (s === 'unreachable' || s === 'down' || s === 'error') return 'down'
  return 'unknown'
}

const health = computed<HealthDetail>(() => sys.value?.health ?? {})
const overall = computed<Health>(() => {
  const s = str(health.value.status)
  return s === 'ok' ? 'healthy' : s === 'degraded' ? 'degraded' : 'unknown'
})
const version = computed(() => str(health.value.version))
const warnings = computed(() => strList(health.value.warnings))

const cards = computed<HealthCard[]>(() => {
  const h = health.value
  const up = rec(h.upstream)
  const out: HealthCard[] = []

  // Nutqdan matn: router "degraded" bo'lsa QAYSI til backend'i yiqilganini aytamiz.
  const stt = rec(up?.stt)
  const sttState = upstreamStatus(stt)
  const broken = strList(stt?.broken)
  out.push({
    key: 'stt',
    name: t('admin.trace.span.stt'),
    icon: Mic,
    status: sttState,
    detail: broken.length ? `${t('admin.system.down')}: ${broken.join(', ')}` : str(rec(h.stt)?.provider),
  })

  // Matndan nutq + navbatdagi band joylar (to'lsa ovoz so'rovlari 503 oladi).
  const slots = rec(h.tts_slots)
  const busy = int(slots?.busy)
  const limit = int(slots?.limit)
  out.push({
    key: 'tts',
    name: t('admin.trace.span.tts'),
    icon: AudioLines,
    status: upstreamStatus(up?.tts),
    meter:
      busy !== null && limit !== null && limit > 0
        ? { value: busy, max: limit, label: t('admin.system.ttsQueue') }
        : undefined,
  })

  // CRM agent sessiyasi (jonli CRM savollari shunga tayanadi).
  const crm = rec(h.crm_session)
  if (!crm || crm.configured === false) {
    out.push({ key: 'crm', name: t('admin.system.crmSession'), icon: KeyRound, status: 'off', label: t('admin.system.notConfigured') })
  } else {
    const fatal = str(crm.fatal)
    const lastError = str(crm.last_error)
    const status: Health = fatal ? 'down' : crm.has_token === true ? 'healthy' : lastError ? 'down' : 'unknown'
    out.push({
      key: 'crm',
      name: t('admin.system.crmSession'),
      icon: KeyRound,
      status,
      detail: fatal ?? (status === 'healthy' ? null : lastError),
    })
  }

  // Foydalanuvchilarning HRM ulanishi - server faqat "sozlanganmi" ni biladi.
  const conn = rec(h.connectors)
  const hrmOn = conn?.hrm === true
  const connUsers = int(conn?.users)
  out.push({
    key: 'hrm',
    name: t('admin.usage.service.hrm'),
    icon: Waypoints,
    status: hrmOn ? 'healthy' : 'off',
    label: hrmOn ? t('admin.user.connected') : t('admin.system.notConfigured'),
    detail: hrmOn && connUsers !== null ? `${t('admin.overview.users')}: ${num(connUsers)}` : null,
  })

  // Telegram bot: token bor, lekin o'qiy olmayapti - bot jim turadi, buni faqat shu yerda ko'rish mumkin.
  const tg = rec(h.telegram)
  const linked = int(tg?.linked)
  const linkedText = linked !== null ? `${t('admin.user.telegramLinks')}: ${num(linked)}` : null
  if (!tg || tg.configured === false) {
    out.push({ key: 'tg', name: t('admin.system.telegramBot'), icon: Bot, status: 'off', label: t('admin.system.notConfigured') })
  } else if (tg.enabled === false) {
    out.push({ key: 'tg', name: t('admin.system.telegramBot'), icon: Bot, status: 'off', detail: linkedText })
  } else {
    const err = str(tg.error)
    const running = tg.running === true
    out.push({
      key: 'tg',
      name: t('admin.system.telegramBot'),
      icon: Bot,
      status: err || !running ? 'down' : 'healthy',
      detail: err ?? (running ? linkedText : str(tg.note)),
    })
  }
  return out
})

/* ---- sozlamalar ---- */

const flags = computed(() => {
  const c = sys.value?.config
  if (!c) return []
  return [
    { key: 'sso', label: t('admin.system.sso'), on: c.ssoEnabled },
    { key: 'local', label: t('admin.system.localLogin'), on: c.localLoginEnabled },
    { key: 'bot', label: t('admin.system.telegramBot'), on: c.telegramBotEnabled },
    { key: 'analytics', label: t('admin.system.analytics'), on: c.analyticsEnabled },
  ]
})
const botMode = computed(() => {
  const m = sys.value?.config.telegramMode
  if (!m) return '—'
  if (m === 'polling') return t('admin.system.modePolling')
  if (m === 'webhook') return t('admin.system.modeWebhook')
  return m === 'off' ? t('ui.off') : m
})

/* ---- ombor ---- */

const storage = computed(() => {
  const s = sys.value?.storage
  if (!s) return []
  return [
    { key: 'db', label: t('admin.system.database'), value: fmtBytes(s.dbBytes, locale.value) },
    { key: 'turns', label: t('admin.col.turns'), value: num(s.turns) },
    { key: 'events', label: t('admin.system.events'), value: num(s.events) },
    { key: 'api', label: t('admin.system.apiCalls'), value: num(s.apiCalls) },
    { key: 'reports', label: t('admin.nav.reports'), value: num(s.reports) },
  ]
})
const dropped = computed(() => sys.value?.storage.dropped ?? 0)
const retention = computed(() => {
  const d = sys.value?.config.retentionDays
  return typeof d === 'number' && d > 0 ? t('admin.system.days', { n: num(d) }) : '—'
})

/* ---- audit ---- */

// Global davr bilan kesiladi (server oxirgi 50 tasini beradi).
const audit = computed<AuditEntry[]>(() => {
  const list = sys.value?.audit ?? []
  const from = params.value.from ? Date.parse(params.value.from) : -Infinity
  const to = params.value.to ? Date.parse(params.value.to) : Infinity
  return list.filter((e) => {
    const at = e.createdAt ? Date.parse(e.createdAt) : NaN
    return Number.isNaN(at) || (at >= from && at < to)
  })
})

function roleList(v: unknown): string {
  const roles = strList(v)
  if (!roles.length) return '—'
  return roles.map((r) => (te(`admin.user.role.${r}`) ? t(`admin.user.role.${r}`) : r)).join(', ')
}
function reportStatus(v: unknown): string {
  const s = str(v)
  return s && te(`admin.reportStatus.${s}`) ? t(`admin.reportStatus.${s}`) : (s ?? '—')
}
function actionLabel(action: string): string {
  const key = `admin.auditAction.${action}`
  return te(key) ? t(key) : action
}
/** Amal tafsiloti bir qatorda: "Foydalanuvchi → Admin", "Yangi → Hal qilindi". */
function actionDetail(e: AuditEntry): string {
  const d = e.detail ?? {}
  switch (e.action) {
    case 'user.roles':
      return `${roleList(d.from)} → ${roleList(d.to)}`
    case 'report.status':
      return `${reportStatus(d.from)} → ${reportStatus(d.to)}`
    case 'user.connector.disconnect':
      return (str(d.platform) ?? '').toUpperCase()
    case 'user.telegram.unlink':
      return int(d.links) !== null ? `${t('admin.user.telegramLinks')}: ${num(int(d.links) as number)}` : ''
    case 'user.note':
    case 'report.note':
      return str(d.preview) ?? ''
    default:
      return ''
  }
}
function targetOf(e: AuditEntry): { to: ReturnType<typeof withFilters>; icon: Component; text: string } | null {
  if (!e.targetId) return null
  if (e.targetType === 'user') return { to: withFilters(`/admin/users/${e.targetId}`), icon: Users, text: `#${e.targetId}` }
  if (e.targetType === 'report') {
    return { to: withFilters(`/admin/reports/${e.targetId}`), icon: Flag, text: e.targetId.slice(0, 8) }
  }
  return null
}

const auditColumns = computed<DataTableColumn<AuditEntry>[]>(() => [
  { key: 'createdAt', label: t('admin.col.when'), width: '16%' },
  { key: 'admin', label: t('admin.col.admin'), width: '24%' },
  { key: 'action', label: t('admin.col.action') },
  { key: 'target', label: t('admin.col.target'), width: '14%' },
])
</script>

<template>
  <section class="sy" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.system.title')"
      :subtitle="t('admin.page.system.subtitle')"
      :refreshing="q.loading.value"
      @refresh="q.refresh"
    >
      <template v-if="sys" #meta>
        <StatusDot :status="overall" />
        <span v-if="version" class="sy-version">{{ t('admin.system.version') }} <span class="t-mono">{{ version }}</span></span>
      </template>
    </AdminPageHeader>

    <AdminError v-if="q.error.value && !sys" :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

    <div v-else-if="q.firstLoad.value" class="sy-health" aria-hidden="true">
      <VCard v-for="k in 5" :key="k">
        <VSkeleton :width="120" :height="14" />
        <VSkeleton class="sy-sk" :width="80" :height="12" />
      </VCard>
    </div>

    <template v-else-if="sys">
      <AdminError v-if="q.error.value" inline :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

      <!-- holat -->
      <section class="sy-section" :class="{ 'is-busy': q.refetching.value }" aria-labelledby="sy-health">
        <h2 id="sy-health" class="sy-h2">{{ t('admin.system.health') }}</h2>

        <div v-if="warnings.length" class="sy-warn" role="note" :aria-label="t('admin.system.warnings')">
          <TriangleAlert class="sy-warn__icon" :size="18" :stroke-width="1.75" aria-hidden="true" />
          <ul class="sy-warn__list">
            <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
          </ul>
        </div>

        <ul class="sy-health">
          <li v-for="c in cards" :key="c.key" class="sy-card">
            <div class="sy-card__head">
              <component :is="c.icon" class="sy-card__icon" :size="18" :stroke-width="1.75" aria-hidden="true" />
              <h3 class="sy-card__name">{{ c.name }}</h3>
            </div>
            <StatusDot :status="c.status" :label="c.label" />
            <p v-if="c.detail" class="sy-card__detail" :title="c.detail">{{ c.detail }}</p>
            <div v-if="c.meter" class="sy-card__meter">
              <span class="sy-card__meter-label">{{ c.meter.label }}</span>
              <VMeter
                :value="c.meter.value"
                :max="c.meter.max"
                :warn-at="Math.max(1, c.meter.max - 1)"
                :crit-at="c.meter.max"
                size="sm"
                :label="c.meter.label"
                :value-text="`${c.meter.value}/${c.meter.max}`"
              />
              <span class="sy-card__meter-val">{{ c.meter.value }}/{{ c.meter.max }}</span>
            </div>
          </li>
        </ul>
      </section>

      <!-- sozlamalar | ombor -->
      <div class="sy-row" :class="{ 'is-busy': q.refetching.value }">
        <VCard :title="t('admin.system.config')" :heading-level="2">
          <dl class="sy-flags">
            <div v-for="f in flags" :key="f.key" class="sy-flag">
              <dt>{{ f.label }}</dt>
              <dd>
                <VBadge dot :tone="f.on ? 'good' : 'neutral'">{{ f.on ? t('ui.on') : t('ui.off') }}</VBadge>
              </dd>
            </div>
            <div class="sy-flag">
              <dt>{{ t('admin.system.telegramMode') }}</dt>
              <dd class="sy-flag__text">{{ botMode }}</dd>
            </div>
          </dl>
        </VCard>

        <VCard :title="t('admin.system.storage')" :heading-level="2">
          <dl class="sy-stats">
            <div v-for="s in storage" :key="s.key">
              <dt>{{ s.label }}</dt>
              <dd>{{ s.value }}</dd>
            </div>
            <div>
              <dt>{{ t('admin.system.retention') }}</dt>
              <dd>{{ retention }}</dd>
            </div>
            <div :class="{ 'is-warn': dropped > 0 }">
              <dt>{{ t('admin.system.dropped') }}</dt>
              <dd>
                <TriangleAlert v-if="dropped > 0" :size="16" :stroke-width="1.75" aria-hidden="true" />
                {{ num(dropped) }}
              </dd>
            </div>
          </dl>
        </VCard>
      </div>

      <!-- audit -->
      <VCard
        class="sy-audit-card"
        :title="t('admin.system.audit')"
        :description="t('admin.system.auditHint')"
        :heading-level="2"
        padding="none"
      >
        <template #actions>
          <VDateRange v-model="range" :aria-label="t('admin.filter.period')" placement="bottom-end" />
        </template>
        <VDataTable
          :rows="audit"
          :columns="auditColumns"
          row-key="id"
          :loading="q.refetching.value"
          :label="t('admin.system.audit')"
        >
          <template #cell-createdAt="{ row }">
            <span class="sy-when"><RelTime :value="(row as AuditEntry).createdAt" /></span>
          </template>
          <template #cell-admin="{ row }">
            <UserCell :name="(row as AuditEntry).adminName" :size="24" />
          </template>
          <template #cell-action="{ row }">
            <span class="sy-action">
              <span class="sy-action__label">{{ actionLabel((row as AuditEntry).action) }}</span>
              <span v-if="actionDetail(row as AuditEntry)" class="sy-action__detail">
                {{ actionDetail(row as AuditEntry) }}
              </span>
            </span>
          </template>
          <template #cell-target="{ row }">
            <RouterLink v-if="targetOf(row as AuditEntry)" :to="targetOf(row as AuditEntry)!.to" class="sy-target">
              <component :is="targetOf(row as AuditEntry)!.icon" :size="14" :stroke-width="1.75" aria-hidden="true" />
              <span class="t-mono">{{ targetOf(row as AuditEntry)!.text }}</span>
            </RouterLink>
            <span v-else class="sy-none">—</span>
          </template>
          <template #empty>
            <VEmpty compact :icon="ScrollText" :title="t('admin.empty.audit')" />
          </template>
        </VDataTable>
      </VCard>
    </template>
  </section>
</template>

<style scoped>
.sy {
  display: flex;
  flex-direction: column;
  gap: var(--s-10);
}
.sy-section {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  transition: opacity var(--dur-2) var(--ease-out);
}
.sy-h2 {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.sy-version {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.sy-sk {
  display: block;
  margin-top: var(--s-3);
}
.is-busy {
  opacity: 0.5;
}

/* ---- ogohlantirishlar ---- */
.sy-warn {
  display: flex;
  gap: var(--s-3);
  padding: var(--s-4);
  border-radius: var(--r-lg);
  background: var(--warn-soft);
  color: var(--text);
}
.sy-warn__icon {
  flex: none;
  margin-top: 1px;
  color: var(--warn-text);
}
.sy-warn__list {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}

/* ---- holat kartalari ---- */
.sy-health {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--s-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.sy-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-2);
  min-width: 0;
  padding: var(--s-5);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
.sy-card__head {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  max-width: 100%;
  margin-bottom: var(--s-1);
}
.sy-card__icon {
  flex: none;
  color: var(--text-3);
}
.sy-card__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
.sy-card__detail {
  display: -webkit-box;
  max-width: 100%;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  overflow-wrap: anywhere;
}
.sy-card__meter {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s-2);
  width: 100%;
  margin-top: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.sy-card__meter-val {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

/* ---- sozlamalar va ombor ---- */
.sy-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-6);
  transition: opacity var(--dur-2) var(--ease-out);
}
@media (min-width: 1120px) {
  .sy-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.sy-flags {
  display: flex;
  flex-direction: column;
  margin: 0;
}
.sy-flag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  min-height: 40px;
}
.sy-flag + .sy-flag {
  border-top: 1px solid var(--line);
}
.sy-flag dt {
  min-width: 0;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.sy-flag dd {
  flex: none;
  margin: 0;
}
.sy-flag__text {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

.sy-stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: var(--s-5) var(--s-4);
  margin: 0;
}
.sy-stats div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.sy-stats dt {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.sy-stats dd {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  margin: 0;
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  font-weight: 600;
  letter-spacing: -0.016em;
  white-space: nowrap;
}
.sy-stats .is-warn dd {
  color: var(--warn-text);
}

/* ---- audit ---- */
/* `clip` - `hidden` emas: yopishqoq sarlavha ishlashda davom etadi. */
.sy-audit-card {
  overflow: clip;
}
.sy-when {
  color: var(--text-2);
}
.sy-action {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
  min-width: 0;
}
.sy-action__label {
  flex: none;
  color: var(--text);
}
.sy-action__detail {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
}
.sy-target {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  color: var(--text-2);
  text-decoration: underline;
  text-decoration-color: transparent;
  text-underline-offset: 3px;
  transition: text-decoration-color var(--dur-1) var(--ease-out);
}
.sy-target:hover {
  color: var(--text);
  text-decoration-color: var(--line-strong);
}
.sy-none {
  color: var(--text-4);
}
</style>
