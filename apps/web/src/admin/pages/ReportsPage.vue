<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { LocationQueryRaw, RouteLocationRaw } from 'vue-router'
import { ArrowLeft, Inbox, SearchX } from 'lucide-vue-next'
import VButton from '../../ui/VButton.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VTabs from '../../ui/VTabs.vue'
import type { TabItem } from '../../ui/VTabs.vue'
import { useMediaQuery } from '../../ui/composables/useMediaQuery'
import { toast } from '../../ui/useToast'
import { getReport, listReports, updateReport } from '../api'
import { REPORT_STATUSES } from '../types'
import type { ReportCounts, ReportDetail, ReportPage, ReportQuery, ReportStatus, ReportSummary } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import { refreshAdminMe } from '../components/useAdminMe'
import { useAdminQuery } from '../components/useAdminQuery'
import { useBackLink } from '../conversations/backLink'
import { useKeysetList } from '../conversations/useKeysetList'
import ReportList from '../reports/ReportList.vue'
import ReportView from '../reports/ReportView.vue'
import AdminDocViewer from '../trace/AdminDocViewer.vue'

// "Xabarlar" (spec §4.5.4): quti - chapda ro'yxat (holat yorliqlari bilan), o'ngda
// tanlangan xabar. `/admin/reports/:id` - to'g'ridan-to'g'ri havola, o'sha xabar ochiladi.
// 1120px dan torda bitta ustun: ro'yxat -> xabar ("Orqaga" bilan).
const props = defineProps<{ id?: string }>()

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const global = useAdminFilters()
const split = useMediaQuery('(min-width: 1120px)')

/* ---- holat yorlig'i: URL'da (`?status=reviewing`), standart - yangi ---- */
const status = computed<ReportStatus>(() => {
  const raw = route.query.status
  const v = Array.isArray(raw) ? raw[0] : raw
  return (REPORT_STATUSES as readonly string[]).includes(v ?? '') ? (v as ReportStatus) : 'new'
})
function setStatus(next: ReportStatus) {
  const query: LocationQueryRaw = { ...route.query, status: next === 'new' ? undefined : next }
  void router.replace({ path: route.path, query, hash: route.hash })
}

/* ---- ro'yxat ---- */
const PAGE = 50
const params = computed<ReportQuery>(() => ({ ...global.params.value, status: status.value, limit: PAGE }))
const fresh = (): ReportQuery => ({ ...global.freshParams(), status: status.value, limit: PAGE })
const reports = useKeysetList<ReportSummary, ReportPage, ReportQuery>(listReports, { params, fresh })
const counts = computed<ReportCounts | null>(() => reports.data.value?.counts ?? null)

const tabs = computed<TabItem<ReportStatus>[]>(() =>
  REPORT_STATUSES.map((s) => ({ value: s, label: t(`admin.reportTab.${s}`), count: counts.value?.[s] })),
)

const selectedId = computed(() => props.id ?? null)
const listTo = computed<RouteLocationRaw>(() => ({ path: '/admin/reports', query: route.query }))
const onBack = useBackLink((path) => path === '/admin/reports')
const itemTo = (r: ReportSummary): RouteLocationRaw => ({
  path: `/admin/reports/${encodeURIComponent(r.id)}`,
  query: route.query,
})

/* ---- yonma-yon ko'rinishda bo'sh o'ng panel bo'lmasin ---- */
// Keng ekranda (≥1120) xabar tanlanmagan bo'lsa - joriy yorliqdagi birinchisi ochiladi:
// quti ochilganda o'ng yarmi "Xabarni tanlang" bo'lib bo'sh turmasin. `replace` - tarixga
// yozilmaydi ("Orqaga" boshqa sahifaga qaytaradi, shu URL'ga emas). Faqat ro'yxat JORIY
// yorliq bo'yicha kelgach: yorliq almashib, eski yorliq qatorlari hali xira turganda
// boshqa holatdagi xabarni ochib yubormaylik. Telefonda (bitta ustun) - avval ro'yxat.
watch(
  [split, selectedId, () => reports.items.value, () => reports.loading.value],
  ([wide, id, items, loading]) => {
    if (!wide || id || loading || !items.length) return
    if (reports.pageParams()?.status !== status.value) return
    // Optimistik o'zgartirilgan (boshqa holatga o'tgan) qator ro'yxatda qoladi - uni emas.
    const first = items.find((r) => r.status === status.value)
    if (!first) return
    void router.replace({ path: `/admin/reports/${encodeURIComponent(first.id)}`, query: route.query, hash: route.hash })
  },
  { immediate: true },
)

/* ---- tanlangan xabar ---- */
const detail = useAdminQuery<ReportDetail, string | null>(
  (id, signal) => getReport(id as string, signal),
  { params: () => selectedId.value, enabled: () => !!selectedId.value },
)
const shown = computed(() => (selectedId.value ? detail.data.value : null))
const stale = computed(() => !!shown.value && shown.value.id !== selectedId.value)
// Xato faqat so'rov tugagach va joriy xabarga tegishli bo'lsa: eski xabar xira turgan
// (`stale`) paytda yangisi yiqilsa ham xato va "Qayta urinish" ko'rinsin - aks holda
// o'chirilgan tugmali eski xabar izohsiz qolardi. Yangi so'rov ketayotganda - eskisining
// xatosi emas, yuklanish holati.
const detailSettledError = computed(
  () => !!detail.error.value && !detail.loading.value && (!shown.value || stale.value),
)
const detailMissing = computed(() => detailSettledError.value && detail.errorStatus.value === 404)
const detailFailed = computed(() => detailSettledError.value && detail.errorStatus.value !== 404)

/* ---- fokus: bitta ustunda ro'yxat <-> xabar ---- */
// Bosilgan qator DOM'dan chiqib ketadi - fokus <body> ga tushmasin: xabar kelgach uning
// sarlavhasiga (ekran o'quvchi nima ochilganini eshitadi), orqaga qaytganda - o'sha qatorga.
const listRef = ref<InstanceType<typeof ReportList> | null>(null)
const viewRef = ref<InstanceType<typeof ReportView> | null>(null)
let focusDetail = false
watch(selectedId, async (id, prev) => {
  if (split.value) return
  focusDetail = !!id
  await nextTick()
  if (!id && prev) void listRef.value?.focusRow(prev)
  // Xabar allaqachon yuklangan (o'shaning o'zi qayta ochildi) - kutadigan narsa yo'q.
  if (id && focusDetail && shown.value?.id === id && !stale.value) {
    focusDetail = false
    viewRef.value?.focus()
  }
})
watch(
  () => (shown.value && !stale.value ? shown.value.id : null),
  async (id) => {
    if (!focusDetail || !id || id !== selectedId.value) return
    focusDetail = false
    await nextTick()
    viewRef.value?.focus()
  },
)

/* ---- holatni o'zgartirish: optimistik, xatoda qaytariladi, "Bekor qilish" bilan ---- */
const saving = ref<ReportStatus | null>(null)

function adjust(c: ReportCounts, from: ReportStatus, to: ReportStatus): ReportCounts {
  return { ...c, [from]: Math.max(0, c[from] - 1), [to]: c[to] + 1 }
}

function apply(id: string, from: ReportStatus, to: ReportStatus) {
  detail.mutate((d) => (d.id === id ? { ...d, status: to } : d))
  // Hisoblagich faqat xabar joriy filtr ichida bo'lsa (ro'yxatda turgan bo'lsa) o'zgaradi:
  // to'g'ridan-to'g'ri havola bilan ochilgan boshqa davrdagi xabar yorliqlarni buzmasin.
  if (reports.items.value.some((r) => r.id === id)) {
    reports.mutatePage((p) => ({ ...p, counts: adjust(p.counts, from, to) }))
  }
  reports.patchItems((r) => (r.id === id ? { ...r, status: to } : r))
}

async function changeStatus(id: string, from: ReportStatus, to: ReportStatus, undoable: boolean) {
  if (from === to) return
  apply(id, from, to)
  if (shown.value?.id === id) saving.value = to
  try {
    const saved = await updateReport(id, { status: to })
    detail.mutate((d) => (d.id === id ? saved : d))
    void refreshAdminMe()
    if (undoable) {
      toast.success(t('admin.toast.statusChanged'), {
        id: `report-status-${id}`,
        action: { label: t('undo'), onClick: () => void changeStatus(id, to, from, false) },
      })
    }
  } catch {
    apply(id, to, from)
    toast.error(t('admin.toast.failed'))
  } finally {
    if (saving.value === to) saving.value = null
  }
}

function onStatus(next: ReportStatus) {
  const d = shown.value
  if (!d || stale.value || saving.value) return
  void changeStatus(d.id, d.status, next, true)
}

/* ---- admin izohi (maydondan chiqqanda) ---- */
async function onNote(id: string, text: string) {
  const value = text.trim()
  try {
    const saved = await updateReport(id, { adminNote: value || null })
    detail.mutate((d) =>
      d.id === id ? { ...d, adminNote: saved.adminNote, updatedAt: saved.updatedAt, updatedBy: saved.updatedBy } : d,
    )
    toast.success(t('admin.toast.noteSaved'))
  } catch {
    // Yozilgan matn maydonda qoladi - admin qayta urinishi mumkin.
    toast.error(t('admin.toast.failed'))
  }
}

function refreshAll() {
  void reports.refresh()
  if (selectedId.value) void detail.refresh()
}
</script>

<template>
  <section class="rp" :class="{ 'is-split': split }" aria-labelledby="admin-page-title">
    <!-- ============ bitta ustun: xabar ============ -->
    <template v-if="!split && selectedId">
      <VButton class="rp-back" variant="ghost" size="sm" :icon="ArrowLeft" :to="listTo" @click.capture="onBack">
        {{ t('admin.nav.reports') }}
      </VButton>
      <h1 id="admin-page-title" class="sr-only">{{ t('admin.page.reports.title') }}</h1>
      <div class="rp-detail">
        <VEmpty v-if="detailMissing" class="rp-empty" :icon="SearchX" :title="t('admin.error.notFound')" />
        <AdminError
          v-else-if="detailFailed"
          :message="detail.errorText.value"
          :busy="detail.loading.value"
          @retry="detail.refresh"
        />
        <div v-else-if="!shown" class="rp-detail-sk" aria-hidden="true">
          <VSkeleton width="40%" :height="14" />
          <VSkeleton :lines="3" width="100%" />
          <VSkeleton width="100%" height="200px" radius="md" />
        </div>
        <ReportView
          v-else
          ref="viewRef"
          :report="shown"
          :stale="stale"
          :saving="saving"
          @status="onStatus"
          @note="onNote"
        />
      </div>
    </template>

    <!-- ============ quti ============ -->
    <template v-else>
      <AdminPageHeader
        :title="t('admin.page.reports.title')"
        :subtitle="t('admin.page.reports.subtitle')"
        filters
        :refreshing="reports.loading.value"
        @refresh="refreshAll"
      />

      <div class="rp-body">
        <VTabs
          :model-value="status"
          :tabs="tabs"
          :aria-label="t('admin.filter.status')"
          @update:model-value="setStatus"
        />

        <AdminError
          v-if="reports.error.value"
          :inline="!!reports.data.value"
          :message="reports.errorText.value"
          :busy="reports.loading.value"
          @retry="reports.refresh"
        />

        <div class="rp-split">
          <div v-if="!(reports.error.value && !reports.data.value)" class="rp-list">
            <ReportList
              ref="listRef"
              :items="reports.items.value"
              :status="status"
              :selected-id="selectedId"
              :loading="reports.loading.value"
              :refetching="reports.refetching.value"
              :next-cursor="reports.nextCursor.value"
              :loading-more="reports.loadingMore.value"
              :link-to="itemTo"
              :replace="split"
              @load-more="reports.loadMore"
            />
          </div>

          <div v-if="split" class="rp-detail">
            <VEmpty v-if="!selectedId" class="rp-empty" :icon="Inbox" :title="t('admin.empty.selectReport')" />
            <VEmpty v-else-if="detailMissing" class="rp-empty" :icon="SearchX" :title="t('admin.error.notFound')" />
            <AdminError
              v-else-if="detailFailed"
              :message="detail.errorText.value"
              :busy="detail.loading.value"
              @retry="detail.refresh"
            />
            <div v-else-if="!shown" class="rp-detail-sk" aria-hidden="true">
              <VSkeleton width="40%" :height="14" />
              <VSkeleton :lines="3" width="100%" />
              <VSkeleton width="100%" height="240px" radius="md" />
            </div>
            <ReportView v-else :report="shown" :stale="stale" :saving="saving" @status="onStatus" @note="onNote" />
          </div>
        </div>
      </div>
    </template>

    <AdminDocViewer />
  </section>
</template>

<style scoped>
.rp {
  display: flex;
  flex-direction: column;
  gap: var(--s-8);
}
.rp-body {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}
.rp-back {
  align-self: flex-start;
  margin-left: calc(var(--s-2) * -1);
  color: var(--text-2);
}

.rp-split {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-6);
  align-items: start;
}
.rp-list,
.rp-detail {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}

/* Yonma-yon: ro'yxat o'z ichida aylanadi va joyida turadi, xabar sahifa bilan aylanadi. */
.is-split .rp-split {
  grid-template-columns: minmax(320px, 2fr) minmax(0, 3fr);
}
.is-split .rp-list {
  position: sticky;
  top: var(--s-6);
  max-height: calc(100dvh - var(--s-12));
  overflow-y: auto;
  overscroll-behavior: contain;
}

.rp-empty {
  padding-block: var(--s-16);
}
.rp-detail-sk {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
  padding: var(--s-6);
}

@media (max-width: 767.98px) {
  .rp {
    gap: var(--s-6);
  }
}
</style>
