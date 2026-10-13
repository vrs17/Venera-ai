<script setup lang="ts">
import { computed, nextTick, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Info, PanelLeftOpen } from 'lucide-vue-next'
import { ApiError } from '../../api/http'
import VButton from '../../ui/VButton.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSearchField from '../../ui/VSearchField.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import { useIsPhone } from '../../ui/composables/useMediaQuery'
import { getOsMap } from '../api'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import { useAdminQuery } from '../components/useAdminQuery'
import { KINDS, KIND_ORDER } from '../osmap/kinds'
import OsMapCanvas from '../osmap/OsMapCanvas.vue'
import OsMapDrawer from '../osmap/OsMapDrawer.vue'
import type { OsCode, OsEdge, OsFlow, OsMapData, OsNode, OsPrompt, OsStreamingRow } from '../osmap/types'

// "Tizim xaritasi": butun Barno AI OS - oqimlar (STT, TTS, chat, guruh, brif...), har
// birida qadamlar va ular orasidagi chiziqlar, n8n kabi kanvasda. Qadam bosilsa - o'ngda
// promptlar (koddan so'zma-so'z), kod, kalitlar va "Sinab ko'rish" (qadamni jonli serverda
// AYNI kod bilan ishga tushirish, `admin_probe.py`).
//
// Ma'lumot `GET /admin/osmap` dan (ichida ichki promptlar - statik fayl emas, faqat ADMIN).
// Havola: `?flow=<oqim>&node=<qadam>` - qadamga to'g'ridan-to'g'ri (xarita sahifasidagi
// "Live test" havolasi shu shaklda).

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const isPhone = useIsPhone()

const q = useAdminQuery((_p: null, signal: AbortSignal) => getOsMap(signal), { params: null })
const data = computed<OsMapData | null>(() => q.data.value)
const flows = computed<OsFlow[]>(() => normalizeFlows(data.value))

/* ---------------------------------------------------------------- fayl shakli */

const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : v == null ? fallback : String(v))
const codes = (v: unknown): OsCode[] => arr<OsCode>(v).filter((c) => !!c && typeof c.path === 'string')

/** Fayl qo'lda qo'yiladi (build.py) va server faqat `flows` ro'yxatini tekshiradi: eski yoki
 *  chala yozuv (qadamsiz oqim, matnsiz prompt, yo'lsiz kod) sahifani yiqitmasin - bo'sh
 *  ro'yxat va satr bilan to'ldiriladi, id siz qadam va uchsiz chiziq tashlanadi. */
function normalizeFlows(raw: OsMapData | null): OsFlow[] {
  return arr<OsFlow>(raw?.flows)
    .filter((f) => !!f && typeof f.id === 'string' && !!f.id)
    .map((f) => ({
      ...f,
      title: str(f.title, f.id),
      gaps: arr<unknown>(f.gaps).map((g) => str(g)),
      streaming: arr<OsStreamingRow>(f.streaming).map((row) => ({ ...row, code: codes(row?.code) })),
      nodes: arr<OsNode>(f.nodes)
        .filter((n) => !!n && typeof n.id === 'string' && !!n.id)
        .map((n) => ({
          ...n,
          label: str(n.label, n.id),
          summary: str(n.summary),
          flags: arr<unknown>(n.flags).map((x) => str(x)),
          prompts: arr<OsPrompt>(n.prompts).map((p) => ({ ...p, title: str(p?.title), text: str(p?.text) })),
          code: codes(n.code),
          probe: typeof n.probe === 'string' && n.probe ? n.probe : undefined,
        })),
      edges: arr<OsEdge>(f.edges)
        .filter((e) => !!e && typeof e.from === 'string' && typeof e.to === 'string')
        .map((e) => ({ ...e, code: codes(e.code) })),
    }))
}
const missing = computed(() => q.errorStatus.value === 404)
// 404 da serverning O'Z xabari (faylni qayerga qo'yish) - umumiy "topilmadi" emas.
const missingText = computed(() => (q.error.value instanceof ApiError ? q.error.value.message : ''))

/* ---------------------------------------------------------------- oqim va tanlov */

const flowId = ref('')
const flow = computed<OsFlow | null>(() => flows.value.find((f) => f.id === flowId.value) ?? flows.value[0] ?? null)
const selection = shallowRef<{ type: 'node' | 'edge' | 'flow'; id: string } | null>(null)
const labels = ref(false)
const canvas = ref<InstanceType<typeof OsMapCanvas> | null>(null)

/** Qadam qaysi oqimda (havola faqat `node` bilan kelsa ham ochilsin). */
function flowOfNode(id: string): OsFlow | null {
  return flows.value.find((f) => f.nodes.some((n) => n.id === id)) ?? null
}

function syncQuery() {
  const query = { ...route.query }
  if (flow.value) query.flow = flow.value.id
  if (selection.value?.type === 'node') query.node = selection.value.id
  else delete query.node
  void router.replace({ query })
}

function openFlow(id: string, nodeId?: string) {
  flowId.value = id
  selection.value = null
  railOpen.value = false
  syncQuery()
  if (nodeId) {
    // Kanvas yangi oqimni joylab, bo'ylarni o'lchaguncha kutiladi.
    void nextTick(() => setTimeout(() => selectNode(nodeId, true), 60))
  }
}

function selectNode(id: string, center = false) {
  selection.value = { type: 'node', id }
  syncQuery()
  // Varaq ochilgach (o'ng 500px band) - qadam uning ostida qolmasin.
  void nextTick(() => (center ? canvas.value?.centerOn(id) : canvas.value?.ensureVisible(id)))
}
function selectEdge(id: string) {
  selection.value = { type: 'edge', id }
  syncQuery()
}
function clearSelection() {
  if (!selection.value) return
  selection.value = null
  syncQuery()
}
function showAbout() {
  selection.value = flow.value ? { type: 'flow', id: flow.value.id } : null
}

// Birinchi yuklash: havoladagi oqim/qadam.
watch(
  flows,
  (list) => {
    if (!list.length || flowId.value) return
    const node = typeof route.query.node === 'string' ? route.query.node : ''
    const wanted = typeof route.query.flow === 'string' ? route.query.flow : ''
    const target = (node && flowOfNode(node)) || list.find((f) => f.id === wanted) || list[0]
    flowId.value = target.id
    if (node && target.nodes.some((n) => n.id === node)) {
      void nextTick(() => setTimeout(() => selectNode(node, true), 120))
    }
  },
  { immediate: true },
)

function onKey(ev: KeyboardEvent) {
  if (ev.key === 'Escape' && selection.value) clearSelection()
}

/* ---------------------------------------------------------------- chap panel: oqimlar va qidiruv */

const railOpen = ref(false)
const search = ref('')

const groups = computed(() => {
  const out = new Map<string, OsFlow[]>()
  for (const f of flows.value) {
    const g = f.group || t('admin.osmap.flows')
    if (!out.has(g)) out.set(g, [])
    out.get(g)!.push(f)
  }
  return [...out.entries()]
})

function flowStats(f: OsFlow): string {
  return t('admin.osmap.stats', {
    nodes: f.nodes.length,
    edges: f.edges.length,
    llm: f.nodes.filter((n) => n.kind === 'llm').length,
    prompts: f.nodes.reduce((a, n) => a + (n.prompts?.length || 0), 0),
  })
}

interface Hit {
  flow: OsFlow
  node: OsNode
  inPrompt: boolean
}
const hits = computed<Hit[]>(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return []
  const out: Hit[] = []
  for (const f of flows.value) {
    for (const n of f.nodes) {
      const hay = [
        n.label,
        n.summary,
        n.details,
        n.model,
        (n.flags || []).join(' '),
        (n.code || []).map((c) => c.path).join(' '),
        (n.prompts || []).map((p) => `${p.title} ${p.path} ${p.text}`).join(' '),
        n.probe,
      ]
        .join(' ')
        .toLowerCase()
      if (hay.includes(needle)) {
        out.push({ flow: f, node: n, inPrompt: (n.prompts || []).some((p) => p.text.toLowerCase().includes(needle)) })
      }
    }
  }
  return out.slice(0, 200)
})

function openHit(h: Hit) {
  if (flow.value?.id === h.flow.id) {
    selectNode(h.node.id, true)
    railOpen.value = false
  } else openFlow(h.flow.id, h.node.id)
}

const flowIds = computed(() => flows.value.map((f) => f.id))
const drawerWidth = computed(() => (selection.value && !isPhone.value ? 500 : 0))
</script>

<template>
  <section class="osm" aria-labelledby="admin-page-title" @keydown="onKey">
    <AdminPageHeader
      :title="t('admin.page.osmap.title')"
      :subtitle="t('admin.page.osmap.subtitle')"
      :refreshing="q.loading.value"
      @refresh="q.refresh"
    >
      <template v-if="data?.meta?.snapshot" #meta>
        <span class="osm__snap">{{ data.meta.snapshot }}</span>
      </template>
    </AdminPageHeader>

    <VEmpty v-if="missing" :icon="Info" :title="t('admin.osmap.missingTitle')" :description="missingText" />

    <AdminError v-else-if="q.error.value && !data" :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

    <div v-else-if="q.firstLoad.value" class="osm__shell" aria-hidden="true">
      <div class="osm__rail"><VSkeleton :lines="8" /></div>
      <div class="osm__stage-wrap"><VSkeleton height="100%" /></div>
    </div>

    <div v-else-if="data && flow" class="osm__shell">
      <aside class="osm__rail" :class="{ 'is-open': railOpen }" :aria-label="t('admin.osmap.flows')">
        <div class="osm__search">
          <VSearchField v-model="search" size="sm" :placeholder="t('admin.osmap.search')" :aria-label="t('admin.osmap.search')" />
        </div>
        <div class="osm__rail-scroll">
          <template v-if="search.trim()">
            <h3 class="osm__group">{{ t('admin.osmap.results', { n: hits.length }) }}</h3>
            <button v-for="h in hits" :key="`${h.flow.id}|${h.node.id}`" type="button" class="osm__item" @click="openHit(h)">
              <b>{{ h.node.label }}</b>
              <span>{{ h.flow.title }}<template v-if="h.inPrompt"> · {{ t('admin.osmap.inPrompt') }}</template></span>
            </button>
          </template>
          <template v-else>
            <template v-for="[g, list] in groups" :key="g">
              <h3 class="osm__group">{{ g }}</h3>
              <button
                v-for="f in list"
                :key="f.id"
                type="button"
                class="osm__item"
                :class="{ 'is-on': f.id === flow.id }"
                :aria-current="f.id === flow.id ? 'true' : undefined"
                @click="openFlow(f.id)"
              >
                <b>{{ f.title }}</b>
                <span>{{ flowStats(f) }}</span>
              </button>
            </template>
          </template>
        </div>
        <div class="osm__legend">
          <span v-for="k in KIND_ORDER" :key="k"><i :style="{ background: KINDS[k].color }" />{{ t(`admin.osmap.kind.${k}`) }}</span>
        </div>
      </aside>

      <div class="osm__stage-wrap">
        <div class="osm__flowhead">
          <h2 class="osm__flowtitle">{{ flow.title }}</h2>
          <p v-if="flow.summary" class="osm__flowsum">{{ flow.summary }}</p>
          <div class="osm__flowbtns">
            <VButton v-if="isPhone" size="sm" :icon="PanelLeftOpen" @click="railOpen = !railOpen">{{ t('admin.osmap.flows') }}</VButton>
            <VButton size="sm" @click="showAbout">{{ t('admin.osmap.about') }}</VButton>
          </div>
        </div>
        <OsMapCanvas
          ref="canvas"
          v-model:labels="labels"
          :flow="flow"
          :selected="selection"
          :right-inset="drawerWidth"
          :known-flows="flowIds"
          @select-node="(id: string) => selectNode(id)"
          @select-edge="selectEdge"
          @open-flow="(id: string) => openFlow(id)"
          @clear="clearSelection"
        />
        <OsMapDrawer
          v-if="selection"
          :flows="flows"
          :flow="flow"
          :selection="selection"
          @close="clearSelection"
          @select-node="(id: string) => selectNode(id, true)"
          @select-edge="selectEdge"
          @open-flow="(id: string) => openFlow(id)"
        />
      </div>
    </div>

    <VEmpty v-else-if="data" :title="t('admin.osmap.emptyTitle')" />
  </section>
</template>

<style scoped>
.osm {
  display: grid;
  gap: 16px;
}
.osm__snap {
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 12px;
  overflow-wrap: anywhere;
}
/* Kanvas sahifaning qolgan balandligini oladi: xarita - bu sahifaning o'zi. */
.osm__shell {
  position: relative;
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  height: max(560px, calc(100dvh - 210px));
  /* `clip`, `hidden` emas: ichidagi fokus yoki `scrollIntoView` qobiqni o'zini surib,
     kanvasni yuqoriga "olib qochmasin". */
  overflow: clip;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
.osm__rail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: var(--surface);
}
.osm__search {
  padding: 10px;
  border-bottom: 1px solid var(--line);
}
.osm__rail-scroll {
  flex: 1;
  min-height: 0;
  padding: 6px;
  overflow-y: auto;
}
.osm__group {
  margin: 12px 8px 6px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.osm__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--r-sm);
  text-align: start;
  cursor: pointer;
}
.osm__item:hover {
  background: var(--fill-hover);
}
.osm__item.is-on {
  background: var(--brand-soft);
}
.osm__item b {
  font-size: 13px;
  font-weight: 600;
}
.osm__item span {
  color: var(--text-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.osm__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  padding: 10px 12px;
  border-top: 1px solid var(--line);
}
.osm__legend span {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-2);
  font-size: 11.5px;
}
.osm__legend i {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 3px;
}
.osm__stage-wrap {
  position: relative;
  min-width: 0;
  min-height: 0;
}
.osm__flowhead {
  position: absolute;
  top: 12px;
  left: 14px;
  right: 14px;
  z-index: 3;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 680px;
  pointer-events: none;
}
.osm__flowtitle {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -0.015em;
  text-wrap: balance;
}
.osm__flowsum {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.45;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.osm__flowbtns {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  pointer-events: auto;
}
@media (max-width: 767.98px) {
  .osm__shell {
    grid-template-columns: minmax(0, 1fr);
    height: max(520px, calc(100dvh - 170px));
  }
  .osm__rail {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 8;
    display: none;
    width: min(300px, 86vw);
    box-shadow: var(--e2);
  }
  .osm__rail.is-open {
    display: flex;
  }
  .osm__flowsum {
    -webkit-line-clamp: 1;
  }
}
</style>
