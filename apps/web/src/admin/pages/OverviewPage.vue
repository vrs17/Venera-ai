<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import { ArrowRight, ChartNoAxesColumn } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VCard from '../../ui/VCard.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VStat from '../../ui/VStat.vue'
import VAreaChart from '../../ui/charts/VAreaChart.vue'
import VBarChart from '../../ui/charts/VBarChart.vue'
import VLineChart from '../../ui/charts/VLineChart.vue'
import VMeter from '../../ui/charts/VMeter.vue'
import VStackedBar from '../../ui/charts/VStackedBar.vue'
import type { BarDatum, ChartSeries, StackPart } from '../../ui/charts/scale'
import { fmtDate, fmtMs, fmtNumber, fmtPercent, toDate } from '../../ui/format'
import { getOverview } from '../api'
import { CHANNELS } from '../types'
import type { Kpi } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import ChannelBadge from '../components/ChannelBadge.vue'
import DurationText from '../components/DurationText.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'
import { channelColor } from '../components/channel'
import { useAdminQuery } from '../components/useAdminQuery'

// "Umumiy" (spec §4.5.1): 5 ta KPI, faollik kanallar bo'yicha, kanallar ulushi,
// yo'nalishlar, javob vaqti, ko'p iqtibos qilingan hujjatlar, so'nggi xabarlar va eng
// sekin javoblar. Hammasi global filtr (davr + kanal) bo'yicha BITTA so'rov.
const { t, te, locale } = useI18n({ useScope: 'global' })
const { withFilters, isDefault, reset } = useAdminFilters()
const q = useAdminQuery(getOverview)

const ov = computed(() => q.data.value)
const busy = computed(() => q.refetching.value)

const num = (v: number) => fmtNumber(v, locale.value)
const ms = (v: number) => fmtMs(v, locale.value)
const pct = (v: number) => fmtPercent(v, v > 0 && v < 0.1 ? 1 : 0, locale.value)

/* ---- KPI ---- */

interface KpiTile {
  key: string
  label: string
  kpi: Kpi | undefined
  format?: (v: number) => string
  good: boolean | null
  to: RouteLocationRaw
}

const tiles = computed<KpiTile[]>(() => {
  const k = ov.value?.kpis
  return [
    { key: 'turns', label: t('admin.kpi.turns'), kpi: k?.turns, good: true, to: withFilters('/admin/conversations') },
    { key: 'users', label: t('admin.kpi.activeUsers'), kpi: k?.activeUsers, good: true, to: withFilters('/admin/users') },
    {
      key: 'ttft',
      label: t('admin.kpi.medianTtft'),
      kpi: k?.medianTtftMs,
      format: ms,
      good: false,
      to: withFilters('/admin/conversations'),
    },
    {
      key: 'errors',
      label: t('admin.kpi.errorRate'),
      kpi: k?.errorRate,
      format: pct,
      good: false,
      to: withFilters('/admin/conversations', { status: 'error' }),
    },
    // Davrda KELGAN hamma xabarlar (holatidan qat'i nazar) - shuning uchun "Xabarlar",
    // "Yangi" emas: menyudagi nishon esa hali ko'rilmagan (status=new) larni sanaydi.
    // Xabarlar ko'payishi o'zicha yaxshi ham, yomon ham emas - farq neytral.
    { key: 'reports', label: t('admin.kpi.reports'), kpi: k?.newReports, good: null, to: withFilters('/admin/reports') },
  ]
})

/** "Oldingi davrga nisbatan · 31-avg – 29-sen": farqlar nimaga nisbatan ekani - bir marta. */
const prevText = computed(() => {
  const r = ov.value?.range
  const head = t('admin.kpi.vsPrevious')
  const cap = head.charAt(0).toLocaleUpperCase(locale.value) + head.slice(1)
  const a = toDate(r?.prevFrom)
  const b = toDate(r?.prevTo)
  if (!a || !b) return cap
  // `prevTo` kirmaydi: oxirgi kun - undan bir lahza oldin.
  const last = new Date(b.getTime() - 1)
  const range =
    a.toDateString() === last.toDateString()
      ? fmtDate(a, locale.value)
      : `${fmtDate(a, locale.value)} – ${fmtDate(last, locale.value)}`
  return `${cap} · ${range}`
})

/* ---- bo'sh davr ---- */

const isEmpty = computed(() => {
  const o = ov.value
  return !!o && (o.kpis.turns.value ?? 0) === 0 && o.recentReports.length === 0
})

/* ---- faollik ---- */

const activityX = computed(() => (ov.value?.activity ?? []).map((p) => p.t))
const activitySeries = computed<ChartSeries[]>(() => {
  const pts = ov.value?.activity ?? []
  return CHANNELS.map((c) => ({
    key: c,
    label: t(`admin.channel.${c}`),
    color: channelColor(c),
    values: pts.map((p) => p[c] ?? 0),
  })).filter((s) => s.values.some((v) => v > 0))
})

/* ---- kanallar ---- */

const channelRows = computed(() => {
  const rows = (ov.value?.channels ?? []).filter((c) => c.turns > 0 || c.users > 0)
  const total = rows.reduce((s, r) => s + r.turns, 0)
  return [...rows].sort((a, b) => b.turns - a.turns).map((r) => ({ ...r, share: total > 0 ? r.turns / total : 0 }))
})
const channelParts = computed<StackPart[]>(() =>
  channelRows.value.map((r) => ({
    key: r.channel,
    label: te(`admin.channel.${r.channel}`) ? t(`admin.channel.${r.channel}`) : r.channel,
    value: r.turns,
    color: channelColor(r.channel),
  })),
)

/* ---- yo'nalishlar ---- */

const routeBars = computed<BarDatum[]>(() =>
  [...(ov.value?.routes ?? [])]
    .filter((r) => r.turns > 0)
    .sort((a, b) => b.turns - a.turns)
    .map((r) => {
      const key = r.route || 'none'
      return {
        key,
        label: te(`admin.route.${key}`) ? t(`admin.route.${key}`) : key,
        value: r.turns,
        // Yo'nalishsiz - "toifa yo'q", xato emas: holat rangi (qizil) yolg'iz ma'no tashimasin.
        // Jim kulrang; qolgan yo'nalishlar bitta rangda (ranglar toifani ajratmaydi, uzunlik ajratadi).
        color: key === 'none' ? '--text-4' : undefined,
        sub: r.errors > 0 ? `${t('admin.col.errors')}: ${num(r.errors)}` : undefined,
        // Qator - shu yo'nalishdagi savollar ro'yxatiga havola (davr saqlanadi).
        to: withFilters('/admin/conversations', { route: key }),
      }
    }),
)

/* ---- javob vaqti ---- */

const latencyX = computed(() => (ov.value?.latency ?? []).map((p) => p.t))
const latencySeries = computed<ChartSeries[]>(() => {
  const pts = ov.value?.latency ?? []
  // Bir rangning ikki pog'onasi (ketma-ket shkala): p50 va p95 - bitta o'lchovning ikki
  // kvantili, alohida toifa emas. Kanal ranglari (web ko'k, mini app to'q sariq) qo'shni
  // grafikda turibdi - ular bilan adashmasin. p95 sirtdan uzoqroq pog'ona (yorug'da to'q,
  // qorong'ida och - tokens.css shkalani teskari qiladi), ya'ni "og'irroq" chiziq.
  return [
    { key: 'p50', label: t('admin.overview.p50'), color: '--viz-seq-3', values: pts.map((p) => p.p50) },
    { key: 'p95', label: t('admin.overview.p95'), color: '--viz-seq-5', values: pts.map((p) => p.p95) },
  ]
})

/* ---- hujjatlar ---- */

const docs = computed(() => (ov.value?.topDocs ?? []).slice(0, 8))
const docMax = computed(() => Math.max(1, ...docs.value.map((d) => d.citations)))

/* ---- ro'yxatlar ---- */

const reports = computed(() => (ov.value?.recentReports ?? []).slice(0, 5))
const slow = computed(() => (ov.value?.slowTurns ?? []).slice(0, 5))

function reasonLabel(reason: string | null): string {
  const key = `admin.reason.${reason ?? 'none'}`
  return te(key) ? t(key) : (reason ?? '')
}
</script>

<template>
  <section class="ov" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.overview.title')"
      :subtitle="t('admin.page.overview.subtitle')"
      filters
      :refreshing="q.loading.value"
      @refresh="q.refresh"
    />

    <AdminError v-if="q.error.value && !ov" :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

    <template v-else>
      <AdminError v-if="q.error.value" inline :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

      <!-- KPI -->
      <div class="ov-kpis-wrap">
        <div class="ov-kpis">
          <VStat
            v-for="tile in tiles"
            :key="tile.key"
            :label="tile.label"
            :value="tile.kpi?.value"
            :previous="tile.kpi?.prev"
            :format="tile.format"
            :positive-is-good="tile.good"
            :trend="tile.kpi?.spark"
            :loading="q.loading.value"
            :to="tile.to"
          />
        </div>
        <p v-if="ov" class="ov-caption">{{ prevText }}</p>
      </div>

      <!-- birinchi yuklash: grafiklar o'rnida skelet (keyin kadr sakramasin) -->
      <div v-if="q.firstLoad.value" class="ov-rows" aria-hidden="true">
        <div class="ov-row ov-row--a">
          <VCard v-for="k in 2" :key="k">
            <VSkeleton :width="112" :height="16" />
            <VSkeleton class="ov-sk" width="100%" height="240px" radius="md" />
          </VCard>
        </div>
        <div class="ov-row ov-row--b">
          <VCard v-for="k in 3" :key="k" :class="{ 'ov-docs-card': k === 3 }">
            <VSkeleton :width="112" :height="16" />
            <VSkeleton class="ov-sk" width="100%" height="200px" radius="md" />
          </VCard>
        </div>
      </div>

      <VEmpty
        v-else-if="isEmpty"
        class="ov-empty"
        :icon="ChartNoAxesColumn"
        :title="isDefault ? t('admin.empty.turns') : t('admin.empty.filtered')"
      >
        <VButton v-if="!isDefault" variant="secondary" size="sm" @click="reset">{{ t('ui.clearAll') }}</VButton>
      </VEmpty>

      <div v-else-if="ov" class="ov-rows">
        <!-- faollik | kanallar -->
        <div class="ov-row ov-row--a">
          <VCard :title="t('admin.overview.activity')" :heading-level="2">
            <VAreaChart
              :series="activitySeries"
              :x="activityX"
              stacked
              :height="260"
              :y-format="num"
              :loading="busy"
              :label="t('admin.overview.activity')"
            />
          </VCard>

          <VCard :title="t('admin.overview.channels')" :heading-level="2">
            <div class="ov-channels" :class="{ 'is-busy': busy }">
              <VStackedBar
                :parts="channelParts"
                legend="none"
                :thickness="12"
                :value-format="num"
                :label="t('admin.overview.channels')"
              />
              <!-- Jadval - afsona ham: kanal nishonidagi nuqta tasmadagi rang bilan bir xil. -->
              <table v-if="channelRows.length" class="ov-table">
                <thead>
                  <tr>
                    <th scope="col">{{ t('admin.col.channel') }}</th>
                    <th scope="col" class="is-num">{{ t('admin.col.turns') }}</th>
                    <th scope="col" class="is-num">{{ t('admin.overview.share') }}</th>
                    <th scope="col" class="is-num ov-hide-narrow">{{ t('admin.overview.users') }}</th>
                    <th scope="col" class="is-num">{{ t('admin.col.errors') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in channelRows" :key="row.channel">
                    <th scope="row"><ChannelBadge :channel="row.channel" size="sm" /></th>
                    <td class="is-num">{{ num(row.turns) }}</td>
                    <td class="is-num">{{ pct(row.share) }}</td>
                    <td class="is-num ov-hide-narrow">{{ num(row.users) }}</td>
                    <td class="is-num" :class="{ 'is-zero': row.errors === 0 }">{{ num(row.errors) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </VCard>
        </div>

        <!-- yo'nalishlar | javob vaqti | hujjatlar -->
        <div class="ov-row ov-row--b">
          <VCard :title="t('admin.overview.routes')" :heading-level="2">
            <VBarChart
              :data="routeBars"
              color="--viz-1"
              :value-format="num"
              :loading="busy"
              :label="t('admin.overview.routes')"
            />
          </VCard>

          <VCard :title="t('admin.overview.latency')" :description="t('admin.overview.latencyHint')" :heading-level="2">
            <VLineChart
              :series="latencySeries"
              :x="latencyX"
              :height="220"
              :y-format="ms"
              :y-tick-format="ms"
              :loading="busy"
              :label="t('admin.overview.latency')"
            />
          </VCard>

          <VCard class="ov-docs-card" :title="t('admin.overview.topDocs')" :heading-level="2">
            <ol v-if="docs.length" class="ov-docs" :class="{ 'is-busy': busy }">
              <li v-for="d in docs" :key="d.ref" class="ov-doc">
                <span class="ov-doc__title" :title="d.title || d.ref">{{ d.title || d.ref }}</span>
                <span class="ov-doc__n">{{ num(d.citations) }}</span>
                <VMeter
                  class="ov-doc__meter"
                  :value="d.citations"
                  :max="docMax"
                  size="sm"
                  :label="d.title || d.ref"
                  :value-text="num(d.citations)"
                />
              </li>
            </ol>
            <p v-else class="ov-none">{{ t('ui.noData') }}</p>
          </VCard>
        </div>

        <!-- so'nggi xabarlar | sekin javoblar -->
        <div class="ov-row ov-row--c">
          <VCard :title="t('admin.overview.recentReports')" :heading-level="2">
            <template #actions>
              <VButton variant="ghost" size="sm" :icon-end="ArrowRight" :to="withFilters('/admin/reports')">
                {{ t('admin.overview.viewAll') }}
              </VButton>
            </template>
            <ul v-if="reports.length" class="ov-list" :class="{ 'is-busy': busy }">
              <li v-for="r in reports" :key="r.id">
                <RouterLink :to="withFilters(`/admin/reports/${r.id}`)" class="ov-item">
                  <span class="ov-item__top">
                    <StatusDot :status="r.status" hide-label />
                    <span class="ov-item__title">{{ r.commentPreview || reasonLabel(r.reason) }}</span>
                    <span class="ov-item__aside"><RelTime :value="r.createdAt" /></span>
                  </span>
                  <span class="ov-item__meta">
                    <VBadge v-if="r.reason" size="sm">{{ reasonLabel(r.reason) }}</VBadge>
                    <span class="ov-item__who">{{ r.userName || t('admin.common.unknownUser') }}</span>
                    <ChannelBadge v-if="r.channel" :channel="r.channel" size="sm" icon-only />
                  </span>
                </RouterLink>
              </li>
            </ul>
            <p v-else class="ov-none">{{ t('admin.empty.reports') }}</p>
          </VCard>

          <VCard :title="t('admin.overview.slowTurns')" :heading-level="2">
            <template #actions>
              <VButton variant="ghost" size="sm" :icon-end="ArrowRight" :to="withFilters('/admin/conversations')">
                {{ t('admin.overview.viewAll') }}
              </VButton>
            </template>
            <ul v-if="slow.length" class="ov-list" :class="{ 'is-busy': busy }">
              <li v-for="turn in slow" :key="turn.id">
                <RouterLink :to="withFilters(`/admin/turns/${turn.id}`)" class="ov-item">
                  <span class="ov-item__top">
                    <span class="ov-item__title">{{ turn.question }}</span>
                    <span class="ov-item__aside"><DurationText :ms="turn.totalMs" /></span>
                  </span>
                  <span class="ov-item__meta">
                    <span class="ov-item__who">{{ turn.userName || t('admin.common.unknownUser') }}</span>
                    <ChannelBadge :channel="turn.channel" size="sm" icon-only />
                    <span aria-hidden="true">·</span>
                    <RelTime :value="turn.startedAt" />
                  </span>
                </RouterLink>
              </li>
            </ul>
            <p v-else class="ov-none">{{ t('ui.noData') }}</p>
          </VCard>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ov {
  display: flex;
  flex-direction: column;
  gap: var(--s-10);
}

/* ---- KPI ---- */
.ov-kpis-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.ov-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s-3);
}
.ov-caption {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

/* ---- qatorlar: 2/3 + 1/3, keyin 3 ustun, keyin 2 ustun ---- */
.ov-rows {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
}
.ov-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-6);
}
@media (min-width: 768px) {
  .ov-row--b,
  .ov-row--c {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .ov-row--b > .ov-docs-card {
    grid-column: 1 / -1;
  }
}
@media (min-width: 1120px) {
  .ov-row--a {
    grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  }
  .ov-row--b {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .ov-row--b > .ov-docs-card {
    grid-column: auto;
  }
}

.ov-sk {
  display: block;
  margin-top: var(--s-5);
}
.ov-empty {
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-lg);
}
/* Qayta yuklash: kadr joyida, faqat xiralashadi (grafiklar buni o'zi qiladi). */
.is-busy {
  opacity: 0.5;
}
.ov-none {
  padding: var(--s-6) 0;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: center;
}

/* ---- kanallar ---- */
.ov-channels {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
  /* Ustun yashirish ekran eniga emas, kartaning o'z eniga bog'liq (pastdagi @container). */
  container-type: inline-size;
  transition: opacity var(--dur-2) var(--ease-out);
}
.ov-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
}
.ov-table th,
.ov-table td {
  height: 36px;
  padding: 0 0 0 var(--s-3);
  border-top: 1px solid var(--line);
  text-align: start;
  font-weight: 400;
  white-space: nowrap;
}
.ov-table th:first-child {
  padding-left: 0;
}
.ov-table thead th {
  height: 28px;
  border-top: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.ov-table .is-num {
  text-align: end;
}
.ov-table .is-zero {
  color: var(--text-4);
}
/* Tor kartada "Foydalanuvchilar" ustuni tushib qoladi. Ekran eni emas, karta eni: 1280-1440 da
   karta uch ustunli qatorda ~280-330px bo'ladi va ru / uz-Cyrl sarlavhalari ("Пользователи",
   "Фойдаланувчилар") bilan jadval kartadan toshib, "Mini App" nomi kesilib qolardi. Kanal nomi -
   jadvalning afsonasi, uni kesib bo'lmaydi; foydalanuvchilar soni esa KPI'da ham bor. 360px -
   eng uzun til (uz-Cyrl, ~347px) sig'adigan chegara. Telefonda karta ham tor - o'sha qoida. */
@container (max-width: 359.98px) {
  .ov-hide-narrow {
    display: none;
  }
}

/* ---- hujjatlar ---- */
.ov-docs {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  transition: opacity var(--dur-2) var(--ease-out);
}
.ov-doc {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'title n'
    'meter meter';
  align-items: center;
  gap: var(--s-1_5) var(--s-3);
  padding: var(--s-2) 0;
}
.ov-doc__title {
  grid-area: title;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.ov-doc__n {
  grid-area: n;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.ov-doc__meter {
  grid-area: meter;
}

/* ---- ixcham ro'yxatlar ---- */
.ov-list {
  display: flex;
  flex-direction: column;
  margin: calc(var(--s-2) * -1) calc(var(--s-3) * -1);
  padding: 0;
  list-style: none;
  transition: opacity var(--dur-2) var(--ease-out);
}
.ov-list li + li {
  border-top: 1px solid var(--line);
}
.ov-item {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  padding: var(--s-3);
  border-radius: var(--r-md);
  color: inherit;
  transition: background-color var(--dur-1) var(--ease-out);
}
.ov-item:hover {
  background: var(--fill);
}
.ov-item:focus-visible {
  outline-offset: -2px;
}
.ov-item__top {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}
.ov-item__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.ov-item__aside {
  flex: none;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.ov-item__meta {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.ov-item__who {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
