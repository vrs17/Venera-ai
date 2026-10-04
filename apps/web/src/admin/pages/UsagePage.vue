<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plug, TriangleAlert } from 'lucide-vue-next'
import VButton from '../../ui/VButton.vue'
import VCard from '../../ui/VCard.vue'
import VDataTable from '../../ui/VDataTable.vue'
import type { DataTableColumn, SortState } from '../../ui/VDataTable.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VBarChart from '../../ui/charts/VBarChart.vue'
import VChartLegend from '../../ui/charts/VChartLegend.vue'
import VSparkline from '../../ui/charts/VSparkline.vue'
import VStackedBar from '../../ui/charts/VStackedBar.vue'
import type { BarDatum, LegendItem, StackPart } from '../../ui/charts/scale'
import { fmtCompact, fmtDate, fmtDateTime, fmtMs, fmtNumber, fmtPercent, intlLocale } from '../../ui/format'
import { getUsage } from '../api'
import type { UsageOp, UsageService } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import DurationText from '../components/DurationText.vue'
import { channelColor } from '../components/channel'
import { fmtUnit, unitEntries } from '../components/units'
import { useAdminQuery } from '../components/useAdminQuery'

// "Foydalanish" (spec §4.5.6): har bir tashqi xizmat - so'rovlar, xato ulushi, p95,
// birliklar; vaqt bo'yicha kichik grafiklar (har xizmatga bittadan - 9 rangli
// "spagetti" o'rniga), p95 ustunlari, kanal bo'yicha taqsimot va eng sekin amallar.
const { t, te, locale } = useI18n({ useScope: 'global' })
const { isDefault, reset } = useAdminFilters()
const q = useAdminQuery(getUsage)

const usage = computed(() => q.data.value)
const busy = computed(() => q.refetching.value)

const num = (v: number) => fmtNumber(v, locale.value)
const ms = (v: number) => fmtMs(v, locale.value)
const pct = (v: number | null | undefined) =>
  typeof v === 'number' ? fmtPercent(v, v > 0 && v < 0.1 ? 1 : 0, locale.value) : '—'

/** Xato ulushi shundan yuqori bo'lsa kartada belgi bilan ko'rsatiladi. */
const ERROR_FLAG = 0.05

function serviceLabel(service: string): string {
  const key = `admin.usage.service.${service}`
  return te(key) ? t(key) : service
}
function laneLabel(lane: string): string {
  const key = `admin.channel.${lane}`
  return te(key) ? t(key) : lane
}

/* ---- xizmatlar ---- */

const services = computed<UsageService[]>(() => usage.value?.services ?? [])
/** Chaqiruvi borlar - ko'pi birinchi; chaqiruvsizlar bitta jim qatorda. */
const active = computed(() => services.value.filter((s) => s.requests > 0).sort((a, b) => b.requests - a.requests))
const idle = computed(() => services.value.filter((s) => s.requests === 0).map((s) => serviceLabel(s.service)))
const isEmpty = computed(() => !!usage.value && active.value.length === 0)

/* ---- vaqt bo'yicha: kichik grafiklar ---- */

const points = computed(() => usage.value?.series.points ?? [])
const multiples = computed(() =>
  active.value.map((s) => {
    const values = points.value.map((p) => Number(p[s.service]) || 0)
    const total = values.reduce((a, b) => a + b, 0)
    return { service: s.service, label: serviceLabel(s.service), values, total }
  }),
)
/** Kichik grafiklar ostidagi vaqt chegaralari (umumiy x o'qi). */
const axisEnds = computed(() => {
  const list = points.value
  if (list.length < 2) return null
  const fmt = (v: string) =>
    usage.value?.series.bucket === 'hour' ? fmtDateTime(v, locale.value, 'medium') : fmtDate(v, locale.value)
  return { start: fmt(String(list[0].t)), end: fmt(String(list[list.length - 1].t)) }
})

/* ---- p95 ---- */

const p95Bars = computed<BarDatum[]>(() =>
  active.value
    .filter((s) => typeof s.p95Ms === 'number')
    .sort((a, b) => (b.p95Ms ?? 0) - (a.p95Ms ?? 0))
    .map((s) => ({
      key: s.service,
      label: serviceLabel(s.service),
      value: s.p95Ms,
      sub: typeof s.p50Ms === 'number' ? `${t('admin.usage.p50')}: ${ms(s.p50Ms)}` : undefined,
    })),
)

/* ---- kanal bo'yicha ---- */

const lanes = computed(() => (usage.value?.byChannel ?? []).map((row) => String(row.channel)))
const laneLegend = computed<LegendItem[]>(() =>
  lanes.value.map((lane) => ({ key: lane, label: laneLabel(lane), color: channelColor(lane), mark: 'rect' })),
)
const byChannel = computed(() => {
  const rows = usage.value?.byChannel ?? []
  return active.value
    .map((s) => {
      const parts: StackPart[] = rows.map((row) => ({
        key: String(row.channel),
        label: laneLabel(String(row.channel)),
        value: Number(row[s.service]) || 0,
        color: channelColor(String(row.channel)),
      }))
      return { service: s.service, label: serviceLabel(s.service), parts, total: parts.reduce((a, p) => a + p.value, 0) }
    })
    .filter((r) => r.total > 0)
})
const channelMax = computed(() => Math.max(1, ...byChannel.value.map((r) => r.total)))

/* ---- amallar jadvali: saralash shu yerda, keyin kesiladi ---- */

const OPS_PREVIEW = 12
const sort = ref<SortState>({ key: 'p95Ms', dir: 'desc' })
const showAllOps = ref(false)

const collator = computed(() => new Intl.Collator(intlLocale(locale.value), { numeric: true, sensitivity: 'base' }))
function opValue(op: UsageOp, key: string): string | number | null {
  switch (key) {
    case 'service':
      return serviceLabel(op.service)
    case 'op':
      return op.op
    case 'requests':
      return op.requests
    case 'errors':
      return op.errors
    case 'errorRate':
      return op.requests > 0 ? op.errors / op.requests : null
    default:
      return op.p95Ms
  }
}
const sortedOps = computed(() => {
  const list = [...(usage.value?.ops ?? [])]
  const { key, dir } = sort.value
  const sign = dir === 'asc' ? 1 : -1
  return list.sort((a, b) => {
    const va = opValue(a, key)
    const vb = opValue(b, key)
    // Bo'sh qiymat yo'nalishdan qat'i nazar oxirida.
    if (va === null || vb === null) return va === vb ? 0 : va === null ? 1 : -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * sign
    return collator.value.compare(String(va), String(vb)) * sign
  })
})
const visibleOps = computed(() => (showAllOps.value ? sortedOps.value : sortedOps.value.slice(0, OPS_PREVIEW)))

const opColumns = computed<DataTableColumn<UsageOp>[]>(() => [
  { key: 'service', label: t('admin.col.service'), sortable: true, width: '22%', format: (r) => serviceLabel(r.service) },
  { key: 'op', label: t('admin.col.op'), sortable: true, mono: true },
  { key: 'requests', label: t('admin.col.requests'), sortable: true, align: 'end', width: '12%', format: (r) => num(r.requests) },
  {
    key: 'errorRate',
    label: t('admin.usage.errorRate'),
    sortable: true,
    align: 'end',
    width: '14%',
    format: (r) => (r.requests > 0 ? pct(r.errors / r.requests) : '—'),
  },
  { key: 'p95Ms', label: t('admin.usage.p95'), sortable: true, align: 'end', width: '12%' },
])
</script>

<template>
  <section class="us" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.usage.title')"
      :subtitle="t('admin.page.usage.subtitle')"
      filters
      :refreshing="q.loading.value"
      @refresh="q.refresh"
    />

    <AdminError v-if="q.error.value && !usage" :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

    <!-- birinchi yuklash -->
    <div v-else-if="q.firstLoad.value" class="us-tiles" aria-hidden="true">
      <VCard v-for="k in 6" :key="k">
        <VSkeleton :width="96" :height="14" />
        <VSkeleton class="us-sk" :width="88" :height="28" radius="sm" />
        <VSkeleton class="us-sk" width="70%" :height="12" />
      </VCard>
    </div>

    <template v-else-if="usage">
      <AdminError v-if="q.error.value" inline :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

      <VEmpty
        v-if="isEmpty"
        class="us-empty"
        :icon="Plug"
        :title="isDefault ? t('admin.empty.usage') : t('admin.empty.filtered')"
      >
        <VButton v-if="!isDefault" variant="secondary" size="sm" @click="reset">{{ t('ui.clearAll') }}</VButton>
      </VEmpty>

      <template v-else>
        <!-- xizmatlar -->
        <section class="us-section" aria-labelledby="us-services">
          <h2 id="us-services" class="sr-only">{{ t('admin.usage.services') }}</h2>
          <ul class="us-tiles" :class="{ 'is-busy': busy }">
            <li v-for="s in active" :key="s.service" class="us-tile">
              <div class="us-tile__head">
                <h3 class="us-tile__name">{{ serviceLabel(s.service) }}</h3>
                <span v-if="(s.errorRate ?? 0) >= ERROR_FLAG" class="us-tile__flag">
                  <TriangleAlert :size="14" :stroke-width="1.75" aria-hidden="true" />
                  <span class="sr-only">{{ t('admin.usage.errorRate') }}:</span>
                  {{ pct(s.errorRate) }}
                </span>
              </div>
              <p class="us-tile__value">
                <span class="us-tile__num">{{ num(s.requests) }}</span>
                <span class="us-tile__cap">{{ t('admin.usage.requests') }}</span>
              </p>
              <dl class="us-tile__meta">
                <div>
                  <dt>{{ t('admin.usage.errors') }}</dt>
                  <dd>{{ pct(s.errorRate) }}</dd>
                </div>
                <div>
                  <dt>{{ t('admin.usage.p95') }}</dt>
                  <dd><DurationText :ms="s.p95Ms" /></dd>
                </div>
                <div v-for="u in unitEntries(s.units)" :key="u.key">
                  <dt>{{ t(`admin.usage.units.${u.key}`) }}</dt>
                  <dd>{{ fmtUnit(u.key, u.value, locale) }}</dd>
                </div>
              </dl>
            </li>
          </ul>
          <p v-if="idle.length" class="us-idle">
            <span class="us-idle__label">{{ t('admin.usage.idle') }}</span>
            {{ idle.join(', ') }}
          </p>
        </section>

        <!-- vaqt bo'yicha | p95 -->
        <div class="us-row">
          <VCard :title="t('admin.usage.overTime')" :heading-level="2">
            <ul class="us-multiples" :class="{ 'is-busy': busy }">
              <li v-for="m in multiples" :key="m.service" class="us-mult">
                <span class="us-mult__name">{{ m.label }}</span>
                <VSparkline
                  class="us-mult__spark"
                  :values="m.values"
                  fluid
                  :height="28"
                  color="--viz-1"
                  :label="`${m.label}: ${num(m.total)}`"
                />
                <span class="us-mult__total">{{ fmtCompact(m.total, locale) }}</span>
              </li>
            </ul>
            <div v-if="axisEnds" class="us-axis" aria-hidden="true">
              <span />
              <span class="us-axis__ends">
                <span>{{ axisEnds.start }}</span>
                <span>{{ axisEnds.end }}</span>
              </span>
              <span />
            </div>
          </VCard>

          <VCard :title="t('admin.usage.p95ByService')" :heading-level="2">
            <VBarChart
              :data="p95Bars"
              color="--viz-1"
              :value-format="ms"
              :loading="busy"
              :label="t('admin.usage.p95ByService')"
            />
          </VCard>
        </div>

        <!-- kanal bo'yicha -->
        <VCard :title="t('admin.usage.byChannel')" :heading-level="2">
          <div class="us-channels" :class="{ 'is-busy': busy }">
            <VChartLegend v-if="laneLegend.length > 1" :items="laneLegend" />
            <ul class="us-lanes">
              <li v-for="row in byChannel" :key="row.service" class="us-lane">
                <span class="us-lane__name">{{ row.label }}</span>
                <VStackedBar
                  class="us-lane__bar"
                  :parts="row.parts"
                  mode="absolute"
                  :max="channelMax"
                  :thickness="10"
                  legend="none"
                  :value-format="num"
                  :label="row.label"
                />
                <span class="us-lane__total">{{ num(row.total) }}</span>
              </li>
            </ul>
          </div>
        </VCard>

        <!-- amallar -->
        <VCard class="us-table-card" :title="t('admin.usage.slowest')" :heading-level="2" padding="none">
          <VDataTable
            :rows="visibleOps"
            :columns="opColumns"
            :row-key="(r: UsageOp) => `${r.service}:${r.op}`"
            :sort="sort"
            :loading="busy"
            dense
            :label="t('admin.usage.slowest')"
            @sort="(s: SortState) => (sort = s)"
          >
            <template #cell-p95Ms="{ row }">
              <DurationText :ms="(row as UsageOp).p95Ms" />
            </template>
            <template #empty>{{ t('admin.empty.usage') }}</template>
            <template v-if="sortedOps.length > OPS_PREVIEW" #footer>
              <div class="us-more">
                <VButton variant="ghost" size="sm" @click="showAllOps = !showAllOps">
                  {{ showAllOps ? t('ui.less') : `${t('admin.overview.viewAll')} · ${num(sortedOps.length)}` }}
                </VButton>
              </div>
            </template>
          </VDataTable>
        </VCard>
      </template>
    </template>
  </section>
</template>

<style scoped>
.us {
  display: flex;
  flex-direction: column;
  gap: var(--s-10);
}
.us-section {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
/* Jadval kartaning ichida: pastki burchaklarda qator foni chiqib ketmasin. `clip` -
   `hidden` emas: u yopishqoq sarlavhani buzmaydi. */
.us-table-card {
  overflow: clip;
}
.us-empty {
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-lg);
}
.us-sk {
  display: block;
  margin-top: var(--s-3);
}
.is-busy {
  opacity: 0.5;
}

/* ---- xizmat kartalari ---- */
.us-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(232px, 1fr));
  gap: var(--s-3);
  margin: 0;
  padding: 0;
  list-style: none;
  transition: opacity var(--dur-2) var(--ease-out);
}
.us-tile {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--s-5);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
.us-tile__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-2);
  min-width: 0;
}
.us-tile__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
/* Holat rangi faqat belgi va raqam bilan birga. */
.us-tile__flag {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--s-1);
  color: var(--crit-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.us-tile__value {
  display: flex;
  flex-direction: column;
  margin-top: var(--s-3);
}
.us-tile__num {
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.022em;
}
.us-tile__cap {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.us-tile__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2) var(--s-5);
  margin: var(--s-4) 0 0;
  padding-top: var(--s-3);
  border-top: 1px solid var(--line);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.us-tile__meta div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.us-tile__meta dt {
  color: var(--text-3);
  font-weight: 500;
}
.us-tile__meta dd {
  margin: 0;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.us-idle {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.us-idle__label {
  margin-right: var(--s-1);
  color: var(--text-2);
  font-weight: 500;
}

/* ---- grafiklar qatori ---- */
.us-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-6);
}
@media (min-width: 1120px) {
  .us-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Kichik grafiklar: nom | chiziq | jami - hamma qatorda bir xil ustunlar. */
.us-multiples,
.us-axis {
  display: grid;
  grid-template-columns: minmax(88px, 34%) minmax(0, 1fr) 56px;
  column-gap: var(--s-3);
}
.us-multiples {
  margin: 0;
  padding: 0;
  list-style: none;
  transition: opacity var(--dur-2) var(--ease-out);
}
.us-mult {
  display: grid;
  grid-template-columns: subgrid;
  grid-column: 1 / -1;
  align-items: center;
  min-height: 40px;
}
.us-mult + .us-mult {
  border-top: 1px solid var(--line);
}
.us-mult__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.us-mult__spark {
  min-width: 0;
}
.us-mult__total {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
  text-align: end;
}
.us-axis {
  margin-top: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}
.us-axis__ends {
  display: flex;
  justify-content: space-between;
  gap: var(--s-2);
  min-width: 0;
}

/* ---- kanal bo'yicha ---- */
.us-channels {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  transition: opacity var(--dur-2) var(--ease-out);
}
.us-lanes {
  display: grid;
  grid-template-columns: minmax(88px, 22%) minmax(0, 1fr) 64px;
  column-gap: var(--s-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.us-lane {
  display: grid;
  grid-template-columns: subgrid;
  grid-column: 1 / -1;
  align-items: center;
  min-height: 36px;
}
.us-lane__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.us-lane__bar {
  min-width: 0;
}
.us-lane__total {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
  text-align: end;
}

.us-more {
  display: flex;
  justify-content: center;
  padding: var(--s-2) 0;
}

@media (max-width: 767.98px) {
  .us-multiples,
  .us-axis {
    grid-template-columns: minmax(72px, 30%) minmax(0, 1fr) 48px;
  }
  /* Yuqoridagi dinamika kartasi bilan bir xil 30%: telefonda 28% (~88px) da "HR yordamchi" /
     "HR-ассистент" kesilib qolardi, ikki karta nomlar ustuni ham bir chiziqda turmasdi. */
  .us-lanes {
    grid-template-columns: minmax(72px, 30%) minmax(0, 1fr) 48px;
  }
}
</style>
