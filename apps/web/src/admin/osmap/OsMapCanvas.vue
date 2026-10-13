<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize, Minus, Plus, Tags } from 'lucide-vue-next'
import VIconButton from '../../ui/VIconButton.vue'
import { KINDS, kindOf } from './kinds'
import type { OsEdge, OsFlow, OsNode } from './types'

/**
 * Oqim kanvasi (n8n kabi): nuqtali fon, ustunlarga terilgan qadamlar va ular orasidagi
 * egri (bezier) chiziqlar. Sudrab surish, g'ildirak yoki ikki barmoq bilan kattalashtirish,
 * qadam yoki chiziqni bosish - tanlash, ikki marta bosish - ichki oqimni ochish.
 *
 * Joylashuv xarita yig'uvchisidagi sahifa bilan BIR XIL algoritm: ustun (`col`) bo'yicha,
 * keyin qo'shnilar o'rtachasi bo'yicha 4 o'tish (chiziqlar kamroq kesishsin). Tartib oqim
 * bo'yicha keshlanadi; bo'ylar esa o'lchanadi - baland qadamlar ustma-ust tushmaydi.
 *
 * Props:
 * - `flow`       - chiziladigan oqim.
 * - `selected`   - tanlangan qadam yoki chiziq (qo'shnilari yoritiladi, qolgani xira).
 * - `labels`     - chiziq yozuvlari doim ko'rinsinmi (aks holda 125% dan kattada).
 * - `rightInset` - o'ngdagi varaq kengligi: markazlash ko'rinadigan qismga qilinsin.
 * - `knownFlows` - mavjud oqimlar id lari (ichki oqim nishoni va ikki marta bosish uchun).
 * Emits: `select-node`, `select-edge`, `open-flow` (ichki oqim), `clear` (bo'sh joy bosildi),
 *        `update:labels`.
 */
const props = withDefaults(
  defineProps<{
    flow: OsFlow
    selected?: { type: 'node' | 'edge' | 'flow'; id: string } | null
    labels?: boolean
    rightInset?: number
    /** Xaritadagi oqimlar: "oqim ochadi" nishoni faqat bor oqimga (fayldagi `subflow`
     *  ba'zan guruh nomi - u oqim emas). */
    knownFlows?: string[]
  }>(),
  { selected: null, labels: false, rightInset: 0, knownFlows: () => [] },
)
const emit = defineEmits<{
  'select-node': [id: string]
  'select-edge': [id: string]
  'open-flow': [id: string]
  clear: []
  'update:labels': [value: boolean]
}>()

const { t, locale } = useI18n({ useScope: 'global' })

/** Qadam eni, eng kam bo'yi, ustunlar va qatorlar orasidagi masofa (px, dunyo koordinatasida). */
const NW = 236
const NH = 76
const CG = 120
const RG = 26
const TOP = 96

type Point = { x: number; y: number }

/* ---------------------------------------------------------------- joylashuv */

// Ustunlar va ulardagi TARTIB oqim bo'yicha keshlanadi (oqimga qaytilganda joylar sakramaydi).
// Y koordinatalar esa qadamlarning O'LCHANGAN bo'yidan: yozuvi uzun yoki nishonlari ikki
// qatorga tushgan qadam balandroq, qat'iy qadam bilan terilsa ular ustma-ust tushardi.
const orders = new WeakMap<OsFlow, string[][]>()
/** O'lchangan bo'ylar (px); o'lchanmagan qadam - `NH`. */
const heights = ref<Record<string, number>>({})

function columnOrder(f: OsFlow): string[][] {
  const cols = [...new Set(f.nodes.map((n) => Number(n.col) || 0))].sort((a, b) => a - b)
  const colIdx = new Map(cols.map((c, i) => [c, i]))
  const colNodes: OsNode[][] = cols.map(() => [])
  f.nodes.forEach((n) => colNodes[colIdx.get(Number(n.col) || 0) ?? 0].push(n))
  const nbr = new Map<string, string[]>(f.nodes.map((n) => [n.id, []]))
  for (const e of f.edges) {
    if (nbr.has(e.from) && nbr.has(e.to)) {
      nbr.get(e.from)!.push(e.to)
      nbr.get(e.to)!.push(e.from)
    }
  }
  const pos = new Map<string, number>()
  colNodes.forEach((list) => list.forEach((n, i) => pos.set(n.id, i)))
  // Qo'shnilar o'rtachasi bo'yicha saralash (barycenter) - chiziqlar kamroq kesishadi.
  for (let pass = 0; pass < 4; pass++) {
    colNodes.forEach((list, ci) => {
      if (ci === 0 && pass % 2 === 0) return
      const bary = new Map<string, number>()
      for (const n of list) {
        const ns = (nbr.get(n.id) ?? []).filter((m) => pos.has(m))
        bary.set(n.id, ns.length ? ns.reduce((a, m) => a + (pos.get(m) ?? 0), 0) / ns.length : (pos.get(n.id) ?? 0))
      }
      list.sort((a, b) => (bary.get(a.id) ?? 0) - (bary.get(b.id) ?? 0))
      list.forEach((n, i) => pos.set(n.id, i))
    })
  }
  return colNodes.map((list) => list.map((n) => n.id))
}

const layout = computed<Record<string, Point>>(() => {
  let cols = orders.get(props.flow)
  if (!cols) {
    cols = columnOrder(props.flow)
    orders.set(props.flow, cols)
  }
  const h = (id: string) => heights.value[id] ?? NH
  const colHeights = cols.map((list) => list.reduce((a, id) => a + h(id) + RG, 0))
  const height = Math.max(1, ...colHeights)
  const out: Record<string, Point> = {}
  cols.forEach((list, ci) => {
    let y = TOP + (height - colHeights[ci]) / 2
    for (const id of list) {
      out[id] = { x: ci * (NW + CG), y }
      y += h(id) + RG
    }
  })
  return out
})

/* ---------------------------------------------------------------- qadam bo'ylari */

// Chiziq qadamning o'rtasiga ulanadi va ustun shu bo'ylar bilan teriladi (`heights` yuqorida).
const nodeEls = new Map<string, HTMLElement>()
function setNodeEl(id: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) nodeEls.set(id, el)
  else nodeEls.delete(id)
}
function measure() {
  const next: Record<string, number> = {}
  for (const [id, el] of nodeEls) next[id] = el.offsetHeight || NH
  heights.value = next
}

function anchor(id: string, side: 'in' | 'out'): Point | null {
  const p = layout.value[id]
  if (!p) return null
  return { x: p.x + (side === 'out' ? NW : 0), y: p.y + (heights.value[id] ?? NH) / 2 }
}

/* ---------------------------------------------------------------- chiziqlar */

interface DrawnEdge {
  id: string
  edge: OsEdge
  d: string
  arrow: string
  mid: Point
}

const edgeId = (e: OsEdge, i: number) => e.id || `${props.flow.id}#e${i}`

/** Chiziqlar qatlami butun oqimni qamrasin: juda kichik `<svg>` (masalan 1px) kichik
 *  masshtabda brauzer tomonidan umuman chizilmay qoladi, `overflow: visible` bo'lsa ham. */
const extent = computed(() => {
  let w = NW
  let h = NH
  for (const [id, p] of Object.entries(layout.value)) {
    w = Math.max(w, p.x + NW)
    h = Math.max(h, p.y + (heights.value[id] ?? NH))
  }
  return { w: Math.ceil(w + CG), h: Math.ceil(h + 120) }
})

const drawn = computed<DrawnEdge[]>(() => {
  const out: DrawnEdge[] = []
  props.flow.edges.forEach((e, i) => {
    const a = anchor(e.from, 'out')
    const b = anchor(e.to, 'in')
    if (!a || !b) return
    let d: string
    let mid: Point
    if (b.x > a.x + 20) {
      const dx = Math.max(40, (b.x - a.x) / 2)
      d = `M${a.x} ${a.y} C${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${b.x} ${b.y}`
      mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
    } else {
      // Orqaga (yoki bir ustundagi) chiziq - qadamlar ustidan aylanib o'tadi.
      const lift = Math.min(a.y, b.y) - 70
      d = `M${a.x} ${a.y} C${a.x + 90} ${a.y} ${a.x + 90} ${lift} ${(a.x + b.x) / 2} ${lift} S${b.x - 90} ${b.y} ${b.x} ${b.y}`
      mid = { x: (a.x + b.x) / 2, y: lift }
    }
    out.push({ id: edgeId(e, i), edge: e, d, mid, arrow: `M${b.x - 9} ${b.y - 5} L${b.x} ${b.y} L${b.x - 9} ${b.y + 5} z` })
  })
  return out
})

/* ---------------------------------------------------------------- tanlov va yoritish */

const hovered = ref<string | null>(null)

const lit = computed<{ nodes: Set<string>; edges: Set<string> } | null>(() => {
  const sel = props.selected
  if (!sel || sel.type === 'flow') return null
  if (sel.type === 'node') {
    const edges = drawn.value.filter((d) => d.edge.from === sel.id || d.edge.to === sel.id)
    return {
      nodes: new Set([sel.id, ...edges.map((d) => d.edge.from), ...edges.map((d) => d.edge.to)]),
      edges: new Set(edges.map((d) => d.id)),
    }
  }
  const e = drawn.value.find((d) => d.id === sel.id)
  return e ? { nodes: new Set([e.edge.from, e.edge.to]), edges: new Set([e.id]) } : null
})

function nodeClass(n: OsNode) {
  return {
    'is-llm': n.kind === 'llm',
    'is-sel': props.selected?.type === 'node' && props.selected.id === n.id,
    'is-dim': !!lit.value && !lit.value.nodes.has(n.id),
  }
}
function edgeClass(d: DrawnEdge) {
  const sel = props.selected?.type === 'edge' && props.selected.id === d.id
  return {
    'is-sel': sel,
    'is-hot': !sel && (hovered.value === d.id || !!lit.value?.edges.has(d.id)),
    'is-dim': !!lit.value && !lit.value.edges.has(d.id),
  }
}

function nodeSub(n: OsNode): string {
  return [t(`admin.osmap.kind.${kindOf(n.kind)}`), n.model].filter(Boolean).join(' · ')
}

/* ---------------------------------------------------------------- surish va kattalashtirish */

const stage = ref<HTMLElement | null>(null)
const T = reactive({ x: 0, y: 0, k: 1 })
const worldStyle = computed(() => ({ transform: `translate(${T.x}px, ${T.y}px) scale(${T.k})` }))
const zoomText = computed(() => `${Math.round(T.k * 100)}%`)
const showLabels = computed(() => props.labels || T.k >= 1.25)

function zoomAt(k: number, cx: number, cy: number) {
  const next = Math.min(2.5, Math.max(0.15, k))
  T.x = cx - (cx - T.x) * (next / T.k)
  T.y = cy - (cy - T.y) * (next / T.k)
  T.k = next
}
function zoomBy(factor: number) {
  const r = stage.value?.getBoundingClientRect()
  if (r) zoomAt(T.k * factor, r.width / 2, r.height / 2)
}

function fit() {
  const ids = Object.keys(layout.value)
  const r = stage.value?.getBoundingClientRect()
  if (!ids.length || !r || !r.width) return
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const id of ids) {
    const p = layout.value[id]
    x0 = Math.min(x0, p.x)
    y0 = Math.min(y0, p.y)
    x1 = Math.max(x1, p.x + NW)
    y1 = Math.max(y1, p.y + (heights.value[id] ?? NH) + 30)
  }
  const top = TOP
  const k = Math.min(1.1, Math.max(0.15, Math.min((r.width - 60) / (x1 - x0), (r.height - top - 40) / (y1 - y0))))
  T.k = k
  T.x = (r.width - (x1 - x0) * k) / 2 - x0 * k
  T.y = top - y0 * k + Math.max(0, (r.height - top - 40 - (y1 - y0) * k) / 2)
}

/** Qadamni ko'rinadigan qism markaziga olib keladi (o'ngdagi varaqni hisobga olib). */
function centerOn(id: string) {
  const p = layout.value[id]
  const r = stage.value?.getBoundingClientRect()
  if (!p || !r) return
  T.k = Math.max(T.k, 0.8)
  const visible = Math.max(240, r.width - props.rightInset)
  T.x = visible / 2 - (p.x + NW / 2) * T.k
  T.y = r.height / 2 - (p.y + (heights.value[id] ?? NH) / 2) * T.k
}

/** Qadam varaq ostida yoki ekrandan tashqarida qolsa - markazga (bosilganda tanlangan
 *  qadam ko'rinib tursin), ko'rinib turgan bo'lsa - kanvas qimirlamaydi. */
function ensureVisible(id: string) {
  const p = layout.value[id]
  const r = stage.value?.getBoundingClientRect()
  if (!p || !r) return
  const left = p.x * T.k + T.x
  const top = p.y * T.k + T.y
  const right = left + NW * T.k
  const bottom = top + (heights.value[id] ?? NH) * T.k
  if (left < 0 || top < 0 || right > r.width - props.rightInset || bottom > r.height) centerOn(id)
}

defineExpose({ fit, centerOn, ensureVisible })

const INTERACTIVE = '.om-node, .om-edge-label, .om-edge-hit, .om-tools'

function onWheel(ev: WheelEvent) {
  ev.preventDefault()
  const r = stage.value!.getBoundingClientRect()
  // Sichqoncha g'ildiragi (katta qadam) va pinch (ctrl) - kattalashtirish; sensorli panel - surish.
  const zoom = ev.ctrlKey || (!ev.shiftKey && Math.abs(ev.deltaX) < 1 && ev.deltaMode === 0 && Math.abs(ev.deltaY) >= 40)
  if (zoom) zoomAt(T.k * Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0015)), ev.clientX - r.left, ev.clientY - r.top)
  else {
    T.x -= ev.deltaX
    T.y -= ev.deltaY
  }
}

const pointers = new Map<number, Point>()
let drag: { x: number; y: number; tx: number; ty: number } | null = null
let pinch: { d: number; k: number } | null = null
let moved = false
const dragging = ref(false)

function onPointerDown(ev: PointerEvent) {
  if ((ev.target as Element).closest(INTERACTIVE)) return
  stage.value?.setPointerCapture(ev.pointerId)
  pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY })
  moved = false
  if (pointers.size === 1) {
    drag = { x: ev.clientX, y: ev.clientY, tx: T.x, ty: T.y }
    dragging.value = true
  }
  if (pointers.size === 2) {
    const [p, q] = [...pointers.values()]
    pinch = { d: Math.hypot(p.x - q.x, p.y - q.y), k: T.k }
    drag = null
  }
}
function onPointerMove(ev: PointerEvent) {
  if (!pointers.has(ev.pointerId)) return
  pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY })
  if (pinch && pointers.size === 2) {
    const [p, q] = [...pointers.values()]
    const r = stage.value!.getBoundingClientRect()
    zoomAt((pinch.k * Math.hypot(p.x - q.x, p.y - q.y)) / pinch.d, (p.x + q.x) / 2 - r.left, (p.y + q.y) / 2 - r.top)
    moved = true
    return
  }
  if (drag) {
    const dx = ev.clientX - drag.x
    const dy = ev.clientY - drag.y
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true
    T.x = drag.tx + dx
    T.y = drag.ty + dy
  }
}
function endPointer(ev: PointerEvent) {
  pointers.delete(ev.pointerId)
  if (pointers.size < 2) pinch = null
  if (!pointers.size) {
    drag = null
    dragging.value = false
  }
}
function onPointerUp(ev: PointerEvent) {
  const was = moved
  endPointer(ev)
  if (!was && !(ev.target as Element).closest(INTERACTIVE)) emit('clear')
}

const hasSubflow = (n: OsNode) => !!n.subflow && props.knownFlows.includes(n.subflow)

function onNodeDblClick(n: OsNode) {
  if (hasSubflow(n)) emit('open-flow', n.subflow!)
}

/* ---------------------------------------------------------------- oqim almashganda */

async function relayout() {
  heights.value = {}
  await nextTick()
  measure()
  fit()
}
watch(() => props.flow, relayout)
// Til almashsa yozuvlar uzunligi (demak qadam bo'yi) o'zgaradi - qayta o'lchanadi.
watch(locale, relayout)

let resize: ResizeObserver | null = null
onMounted(() => {
  stage.value?.addEventListener('wheel', onWheel, { passive: false })
  void relayout()
  // Sahifa kengligi o'zgarsa (menyu yig'ildi, oyna kichraydi) - joyida qoladi, faqat
  // birinchi o'lchovdan oldin (kenglik 0) bo'lsa qayta joylanadi.
  if ('ResizeObserver' in window && stage.value) {
    let first = true
    resize = new ResizeObserver(() => {
      if (first) {
        first = false
        return
      }
      if (!Object.keys(heights.value).length) void relayout()
    })
    resize.observe(stage.value)
  }
})
onBeforeUnmount(() => {
  stage.value?.removeEventListener('wheel', onWheel)
  resize?.disconnect()
})
</script>

<template>
  <div
    ref="stage"
    class="om-stage"
    :class="{ 'is-dragging': dragging }"
    :aria-label="t('admin.osmap.canvas')"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="endPointer"
  >
    <div class="om-world" :style="worldStyle">
      <svg class="om-edges" :width="extent.w" :height="extent.h" aria-hidden="true">
        <g
          v-for="d in drawn"
          :key="d.id"
          class="om-edge"
          :class="edgeClass(d)"
          @click.stop="emit('select-edge', d.id)"
          @mouseenter="hovered = d.id"
          @mouseleave="hovered = null"
        >
          <path class="om-edge-path" :d="d.d" />
          <path class="om-edge-hit" :d="d.d" />
          <path class="om-edge-arrow" :d="d.arrow" />
        </g>
      </svg>

      <template v-for="d in drawn" :key="`l-${d.id}`">
        <button
          v-if="d.edge.label"
          type="button"
          class="om-edge-label"
          :class="{
            ...edgeClass(d),
            'is-shown': showLabels || hovered === d.id || !!lit?.edges.has(d.id),
          }"
          :style="{ left: `${d.mid.x}px`, top: `${d.mid.y}px` }"
          :title="d.edge.label"
          @click.stop="emit('select-edge', d.id)"
          @mouseenter="hovered = d.id"
          @mouseleave="hovered = null"
        >
          {{ d.edge.label }}
        </button>
      </template>

      <div
        v-for="n in flow.nodes"
        :key="n.id"
        :ref="(el) => setNodeEl(n.id, el)"
        class="om-node"
        :class="nodeClass(n)"
        :style="{ left: `${layout[n.id]?.x ?? 0}px`, top: `${layout[n.id]?.y ?? 0}px` }"
        role="button"
        tabindex="0"
        :aria-label="n.label"
        @click.stop="emit('select-node', n.id)"
        @dblclick.stop="onNodeDblClick(n)"
        @keydown.enter.prevent="emit('select-node', n.id)"
        @keydown.space.prevent="emit('select-node', n.id)"
      >
        <span class="om-node__ico" :style="{ background: KINDS[kindOf(n.kind)].color }">
          <component :is="KINDS[kindOf(n.kind)].icon" :size="18" :stroke-width="2" aria-hidden="true" />
        </span>
        <span class="om-node__body">
          <span class="om-node__lbl">{{ n.label }}</span>
          <span class="om-node__sub">{{ nodeSub(n) }}</span>
          <span v-if="n.prompts?.length || n.flags?.length || hasSubflow(n) || n.probe" class="om-node__badges">
            <span v-if="n.prompts?.length" class="om-badge om-badge--prompt">
              {{ t('admin.osmap.badgePrompts', { n: n.prompts.length }) }}
            </span>
            <span v-if="n.flags?.length" class="om-badge">{{ t('admin.osmap.badgeFlags', { n: n.flags.length }) }}</span>
            <span v-if="n.probe" class="om-badge om-badge--probe">{{ t('admin.osmap.badgeProbe') }}</span>
            <span v-if="hasSubflow(n)" class="om-badge om-badge--sub">{{ t('admin.osmap.badgeSubflow') }}</span>
          </span>
        </span>
        <span class="om-port om-port--in" aria-hidden="true" />
        <span class="om-port om-port--out" aria-hidden="true" />
      </div>
    </div>

    <p class="om-hint">{{ t('admin.osmap.hint') }}</p>

    <div class="om-tools">
      <VIconButton :icon="Tags" size="sm" :label="t('admin.osmap.labels')" :pressed="labels" @click="emit('update:labels', !labels)" />
      <VIconButton :icon="Minus" size="sm" :label="t('admin.osmap.zoomOut')" @click="zoomBy(1 / 1.2)" />
      <span class="om-zoom" aria-live="polite">{{ zoomText }}</span>
      <VIconButton :icon="Plus" size="sm" :label="t('admin.osmap.zoomIn')" @click="zoomBy(1.2)" />
      <VIconButton :icon="Maximize" size="sm" :label="t('admin.osmap.fit')" @click="fit" />
    </div>
  </div>
</template>

<style scoped>
.om-stage {
  position: relative;
  min-width: 0;
  height: 100%;
  overflow: clip;
  background-color: var(--bg-subtle);
  background-image: radial-gradient(var(--line-strong) 1.2px, transparent 1.2px);
  background-size: 22px 22px;
  touch-action: none;
  cursor: grab;
  user-select: none;
}
.om-stage.is-dragging {
  cursor: grabbing;
}
.om-world {
  position: absolute;
  left: 0;
  top: 0;
  transform-origin: 0 0;
}
/* `max-width: none` - umumiy reset (`svg { max-width: 100% }`) qatlamni dunyo
   konteynerining enigacha (0) siqib qo'yardi va chiziqlar umuman ko'rinmasdi. */
.om-edges {
  position: absolute;
  left: 0;
  top: 0;
  max-width: none;
  max-height: none;
  overflow: visible;
  pointer-events: none;
}
/* Chiziq qalinligi masshtabga bog'liq EMAS (`non-scaling-stroke`): butun oqim ekranga
   sig'dirilganda (20-30%) ham chiziqlar ko'rinib tursin. */
.om-edge-path {
  fill: none;
  stroke: var(--text-4);
  stroke-width: 1.75;
  vector-effect: non-scaling-stroke;
}
.om-edge-hit {
  fill: none;
  stroke: transparent;
  stroke-width: 14;
  vector-effect: non-scaling-stroke;
  pointer-events: stroke;
  cursor: pointer;
}
.om-edge-arrow {
  fill: var(--text-4);
}
.om-edge.is-hot .om-edge-path {
  stroke: var(--brand);
  stroke-width: 2.5;
}
.om-edge.is-hot .om-edge-arrow {
  fill: var(--brand);
}
.om-edge.is-sel .om-edge-path {
  stroke: var(--info-text);
  stroke-width: 3;
}
.om-edge.is-sel .om-edge-arrow {
  fill: var(--info-text);
}
.om-edge.is-dim {
  opacity: 0.18;
}

.om-edge-label {
  position: absolute;
  z-index: 1;
  display: none;
  max-width: 220px;
  padding: 2px 8px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface);
  color: var(--text-2);
  font-size: 11px;
  line-height: 16px;
  white-space: nowrap;
  text-overflow: ellipsis;
  transform: translate(-50%, -50%);
  cursor: pointer;
}
.om-edge-label.is-shown {
  display: block;
}
.om-edge-label.is-dim {
  opacity: 0.15;
}
.om-edge-label.is-sel {
  border-color: var(--info-text);
  color: var(--info-text);
}

.om-node {
  position: absolute;
  z-index: 2;
  display: flex;
  align-items: stretch;
  width: 236px;
  min-height: 76px;
  border: 1.5px solid var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--e1);
  cursor: pointer;
  transition: opacity var(--dur-1) var(--ease-out);
}
.om-node:hover {
  border-color: var(--text-4);
}
.om-node.is-llm {
  border-color: var(--brand);
}
.om-node.is-sel {
  border-color: var(--info-text);
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--info-text) 25%, transparent),
    var(--e1);
}
.om-node.is-dim {
  opacity: 0.28;
}
.om-node:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.om-node__ico {
  display: grid;
  flex: none;
  width: 42px;
  place-items: center;
  border-radius: calc(var(--r-lg) - 2px) 0 0 calc(var(--r-lg) - 2px);
  color: #fff;
}
.om-node__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 8px 10px;
}
.om-node__lbl {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.om-node__sub {
  overflow: hidden;
  color: var(--text-3);
  font-size: 11.5px;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.om-node__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}
.om-badge {
  padding: 0 5px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 16px;
}
.om-badge--prompt {
  border-color: transparent;
  background: var(--brand-soft);
  color: var(--brand);
}
.om-badge--probe {
  border-color: transparent;
  background: var(--good-soft);
  color: var(--good-text);
}
.om-badge--sub {
  color: var(--info-text);
}
.om-port {
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  margin-top: -5px;
  border: 2px solid var(--line-strong);
  border-radius: 50%;
  background: var(--surface);
}
.om-port--in {
  left: -6px;
}
.om-port--out {
  right: -6px;
}

.om-hint {
  position: absolute;
  left: var(--s-3);
  bottom: var(--s-3);
  z-index: 3;
  margin: 0;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--text-3);
  font-size: 12px;
  pointer-events: none;
}
.om-tools {
  position: absolute;
  right: var(--s-3);
  bottom: var(--s-3);
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  box-shadow: var(--e1);
}
.om-zoom {
  min-width: 44px;
  color: var(--text-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}
@media (max-width: 767.98px) {
  .om-hint {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .om-node {
    transition: none;
  }
}
</style>
