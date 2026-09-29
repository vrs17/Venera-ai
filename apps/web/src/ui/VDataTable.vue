<script lang="ts">
import type { RouteLocationRaw } from 'vue-router'

export interface DataTableColumn<T = unknown> {
  key: string
  label: string
  /** CSS kenglik ('120px', '24%') yoki px raqam. */
  width?: string | number
  align?: 'start' | 'center' | 'end'
  sortable?: boolean
  /** Katak (th/td) uchun qo'shimcha sinf. */
  class?: string
  /** Katak qiymati (standart - row[key]); slot va saralash ham shuni oladi. */
  value?: (row: T) => unknown
  /** Slot bo'lmasa katakdagi matn. */
  format?: (row: T) => string
  /** Mijoz tomonda saralash kaliti (standart - value). */
  sortValue?: (row: T) => unknown
  mono?: boolean
  /** Matn qatorga sig'masa o'ralsin (standart - bitta qator, "…"). */
  wrap?: boolean
  /** Telefondagi kartochkada ko'rsatilmasin. */
  hideOnCard?: boolean
}

export type SortDir = 'asc' | 'desc'
export interface SortState {
  key: string
  dir: SortDir
}
</script>

<script setup lang="ts" generic="T">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-vue-next'
import VSkeleton from './VSkeleton.vue'
import { useIsPhone } from './composables/useMediaQuery'
import { intlLocale } from './format'

/**
 * Admin jadvali.
 *
 * - Sarlavha yopishqoq (--bg-subtle), qatorlar 44px (dense - 36), sochdek ajratgich.
 * - Qator bosiladigan bo'lsa (`@row-click` yoki `rowTo`): ↑/↓ fokusni suradi, Enter ochadi,
 *   Ctrl/⌘ yoki o'rta tugma - yangi varaqda (`rowTo` bilan). Qator ichidagi tugma/havola
 *   bosilsa yoki matn belgilansa - qator ochilmaydi (nusxa olish buzilmasin).
 * - Saralash: `@sort` tinglovchisi bo'lsa - serverga (hodisa), bo'lmasa - shu yerda.
 * - Yuklash: skelet FAQAT birinchi marta; keyin eski qatorlar 50% xira, sakrash yo'q.
 * - Telefonda (<768px) qatorlar "nom: qiymat" kartochkalariga aylanadi (`noCards` o'chiradi).
 *
 * Tinglovchilar prop sifatida e'lon qilingan (`onRowClick`, `onSort`): shunda ota
 * komponent tinglayotganini bilamiz - aks holda saralashni o'zimiz qilamiz.
 */
const props = withDefaults(
  defineProps<{
    rows: T[]
    columns: DataTableColumn<T>[]
    rowKey: keyof T | ((row: T) => string | number)
    loading?: boolean
    dense?: boolean
    /** Boshlang'ich/boshqariladigan saralash holati. */
    sort?: SortState | null
    /** Tanlangan qator (split ko'rinishda o'ng panelda ochilgani). */
    selectedKey?: string | number | null
    rowTo?: (row: T) => RouteLocationRaw
    noCards?: boolean
    /** Yopishqoq sarlavha tepadan qancha pastda (sahifa sarlavhasi balandligi). */
    stickyTop?: number | string
    /** Berilsa jadval o'z ichida aylanadi (sarlavha shu ichida yopishadi). */
    maxHeight?: number | string
    skeletonRows?: number
    label?: string
    onRowClick?: (row: T, index: number, event: MouseEvent | KeyboardEvent) => void
    onSort?: (sort: SortState) => void
  }>(),
  { skeletonRows: 6, stickyTop: 0, sort: null, selectedKey: null },
)

defineSlots<
  {
    [K in `cell-${string}`]?: (p: { row: T; value: unknown; index: number }) => unknown
  } & {
    [K in `head-${string}`]?: (p: { column: DataTableColumn<T> }) => unknown
  } & {
    empty?: () => unknown
    footer?: () => unknown
  }
>()

const { t, locale } = useI18n({ useScope: 'global' })
const router = useRouter()
const isPhone = useIsPhone()

const cards = computed(() => isPhone.value && !props.noCards)
const clickable = computed(() => !!props.onRowClick || !!props.rowTo)
const firstLoad = computed(() => props.loading && props.rows.length === 0)
const refetching = computed(() => props.loading && props.rows.length > 0)

const px = (v: string | number | undefined) => (v === undefined ? undefined : typeof v === 'number' ? `${v}px` : v)

/* ---- qiymatlar ---- */

function keyOf(row: T): string | number {
  const k = props.rowKey
  if (typeof k === 'function') return k(row)
  return String((row as Record<PropertyKey, unknown>)[k as PropertyKey])
}

function valueOf(row: T, col: DataTableColumn<T>): unknown {
  return col.value ? col.value(row) : (row as Record<string, unknown>)[col.key]
}

function textOf(row: T, col: DataTableColumn<T>): string {
  if (col.format) return col.format(row)
  const v = valueOf(row, col)
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

/* ---- saralash ---- */

const sortState = ref<SortState | null>(props.sort)
watch(
  () => props.sort,
  (s) => (sortState.value = s),
)

function toggleSort(col: DataTableColumn<T>) {
  const cur = sortState.value
  // Raqamli (o'ngga tekislangan) ustun avval kamayish bo'yicha - "eng ko'p" birinchi.
  const first: SortDir = col.align === 'end' ? 'desc' : 'asc'
  const next: SortState = cur?.key === col.key ? { key: col.key, dir: cur.dir === 'asc' ? 'desc' : 'asc' } : { key: col.key, dir: first }
  sortState.value = next
  props.onSort?.(next)
}

const collator = computed(() => new Intl.Collator(intlLocale(locale.value), { numeric: true, sensitivity: 'base' }))

function cmp(a: unknown, b: unknown): number {
  const na = a === null || a === undefined || a === ''
  const nb = b === null || b === undefined || b === ''
  if (na || nb) return na === nb ? 0 : na ? 1 : -1
  if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime()
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b)
  return collator.value.compare(String(a), String(b))
}

const viewRows = computed<T[]>(() => {
  const s = sortState.value
  if (!s || props.onSort) return props.rows
  const col = props.columns.find((c) => c.key === s.key)
  if (!col) return props.rows
  const get = col.sortValue ?? ((r: T) => valueOf(r, col))
  const sign = s.dir === 'asc' ? 1 : -1
  return [...props.rows].sort((a, b) => {
    const va = get(a)
    const vb = get(b)
    const empty = (v: unknown) => v === null || v === undefined || v === ''
    // Bo'sh qiymatlar yo'nalishdan qat'i nazar oxirida.
    if (empty(va) || empty(vb)) return cmp(va, vb)
    return cmp(va, vb) * sign
  })
})

function ariaSort(col: DataTableColumn<T>): 'ascending' | 'descending' | 'none' | undefined {
  if (!col.sortable) return undefined
  const s = sortState.value
  if (!s || s.key !== col.key) return 'none'
  return s.dir === 'asc' ? 'ascending' : 'descending'
}

/* ---- qatorlar: bosish va klaviatura ---- */

const focusIdx = ref(0)
watch(
  () => viewRows.value.length,
  (n) => {
    if (focusIdx.value > n - 1) focusIdx.value = Math.max(0, n - 1)
  },
)

const rowEls: (HTMLElement | undefined)[] = []
function setRowEl(i: number, el: unknown) {
  rowEls[i] = el instanceof HTMLElement ? el : undefined
}

const INTERACTIVE =
  'a[href],button,input,select,textarea,label,summary,[role="button"],[role="link"],[role="menuitem"],[role="checkbox"],[role="switch"],[contenteditable="true"]'

function fromInside(e: Event): boolean {
  const target = e.target as Element | null
  const hit = target?.closest?.(INTERACTIVE)
  return !!hit && hit !== e.currentTarget && (e.currentTarget as Element).contains(hit)
}

function activate(row: T, i: number, e: MouseEvent | KeyboardEvent) {
  focusIdx.value = i
  if (props.rowTo && router) {
    const to = props.rowTo(row)
    const newTab = e.metaKey || e.ctrlKey || (e instanceof MouseEvent && e.button === 1)
    if (newTab) window.open(router.resolve(to).href, '_blank', 'noopener')
    else void router.push(to)
  }
  props.onRowClick?.(row, i, e)
}

function onRowClick(row: T, i: number, e: MouseEvent) {
  if (!clickable.value || fromInside(e)) return
  // Matn belgilanayotgan bo'lsa - bu nusxa olish, qatorni ochmaymiz.
  const sel = window.getSelection?.()
  if (sel && !sel.isCollapsed && sel.toString().trim() && (e.currentTarget as Element).contains(sel.anchorNode)) return
  activate(row, i, e)
}

function onRowAux(row: T, i: number, e: MouseEvent) {
  if (e.button !== 1 || !props.rowTo || fromInside(e)) return
  e.preventDefault()
  activate(row, i, e)
}

function focusRow(i: number) {
  const n = viewRows.value.length
  if (!n) return
  const next = Math.max(0, Math.min(n - 1, i))
  focusIdx.value = next
  rowEls[next]?.focus()
  rowEls[next]?.scrollIntoView?.({ block: 'nearest' })
}

function onRowKey(row: T, i: number, e: KeyboardEvent) {
  if (!clickable.value || e.target !== e.currentTarget) return
  switch (e.key) {
    case 'ArrowDown':
      focusRow(i + 1)
      break
    case 'ArrowUp':
      focusRow(i - 1)
      break
    case 'Home':
      focusRow(0)
      break
    case 'End':
      focusRow(viewRows.value.length - 1)
      break
    case 'Enter':
      activate(row, i, e)
      break
    default:
      return
  }
  e.preventDefault()
}

/**
 * Qisqargan ("…") katak ustiga kelganda to'liq matn `title` da. Faqat haqiqatan
 * kesilgan bo'lsa - har katakda keraksiz brauzer tooltipi chiqmasin.
 */
function onCellOver(e: PointerEvent) {
  const cell = (e.target as Element | null)?.closest?.('.vdt-cell')
  if (!(cell instanceof HTMLElement)) return
  if (cell.scrollWidth > cell.clientWidth + 1) cell.title = cell.textContent?.trim() ?? ''
  else cell.removeAttribute('title')
}

function tabIndexOf(i: number): number | undefined {
  if (!clickable.value) return undefined
  return i === focusIdx.value ? 0 : -1
}

function isSelected(row: T): boolean {
  return props.selectedKey !== null && props.selectedKey !== undefined && String(keyOf(row)) === String(props.selectedKey)
}

/* ---- kartochka ko'rinishi ---- */

const titleCol = computed(() => props.columns[0])
const cardCols = computed(() => props.columns.slice(1).filter((c) => !c.hideOnCard))

// Skelet kengliklari o'zgarmas (tasodifiy emas) - har renderda "sakramaydi".
const SK_W = ['72%', '48%', '60%', '36%', '54%', '66%']
const skWidth = (r: number, c: number) => SK_W[(r * 7 + c * 3) % SK_W.length]
</script>

<template>
  <div
    class="vdt"
    :class="{ 'is-dense': dense, 'is-clickable': clickable, 'is-refetch': refetching, 'is-cards': cards }"
    :style="{ '--vdt-top': px(stickyTop) }"
    :aria-busy="loading || undefined"
  >
    <!-- ================= telefon: kartochkalar ================= -->
    <template v-if="cards">
      <ul class="vdt-cards" role="list" :aria-label="label">
        <template v-if="firstLoad">
          <li v-for="r in Math.min(skeletonRows, 4)" :key="`sk${r}`" class="vdt-card is-skeleton" aria-hidden="true">
            <VSkeleton :width="skWidth(r, 0)" :height="14" />
            <VSkeleton :width="skWidth(r, 1)" :height="12" />
            <VSkeleton :width="skWidth(r, 2)" :height="12" />
          </li>
        </template>
        <li v-else-if="viewRows.length === 0" class="vdt-empty">
          <slot name="empty">{{ t('ui.noResults') }}</slot>
        </li>
        <template v-else>
        <li
          v-for="(row, i) in viewRows"
          :key="keyOf(row)"
          :ref="(el) => setRowEl(i, el)"
          class="vdt-card"
          :class="{ 'is-selected': isSelected(row) }"
          :tabindex="tabIndexOf(i)"
          :aria-current="isSelected(row) || undefined"
          @click="onRowClick(row, i, $event)"
          @auxclick="onRowAux(row, i, $event)"
          @keydown="onRowKey(row, i, $event)"
          @focus="focusIdx = i"
        >
          <div v-if="titleCol" class="vdt-card-title" :class="titleCol.class">
            <slot :name="`cell-${titleCol.key}`" :row="row" :value="valueOf(row, titleCol)" :index="i">
              {{ textOf(row, titleCol) }}
            </slot>
          </div>
          <dl v-if="cardCols.length" class="vdt-card-dl">
            <div v-for="col in cardCols" :key="col.key" class="vdt-card-pair">
              <dt>{{ col.label }}</dt>
              <dd :class="[col.class, { 't-mono': col.mono }]">
                <slot :name="`cell-${col.key}`" :row="row" :value="valueOf(row, col)" :index="i">
                  {{ textOf(row, col) }}
                </slot>
              </dd>
            </div>
          </dl>
        </li>
        </template>
      </ul>
    </template>

    <!-- ================= jadval ================= -->
    <div v-else class="vdt-scroll" :class="{ 'is-contained': maxHeight !== undefined }" :style="{ maxHeight: px(maxHeight) }">
      <table class="vdt-table" :aria-label="label" :aria-rowcount="firstLoad ? undefined : viewRows.length + 1">
        <colgroup>
          <col v-for="col in columns" :key="col.key" :style="{ width: px(col.width) }" />
        </colgroup>
        <thead>
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              scope="col"
              :class="[`is-${col.align ?? 'start'}`, col.class]"
              :aria-sort="ariaSort(col)"
            >
              <button
                v-if="col.sortable"
                type="button"
                class="vdt-sort"
                :class="{ 'is-on': sortState?.key === col.key }"
                @click="toggleSort(col)"
              >
                <slot :name="`head-${col.key}`" :column="col">{{ col.label }}</slot>
                <ArrowUp v-if="sortState?.key === col.key && sortState.dir === 'asc'" :size="14" :stroke-width="2" aria-hidden="true" />
                <ArrowDown v-else-if="sortState?.key === col.key" :size="14" :stroke-width="2" aria-hidden="true" />
                <ChevronsUpDown v-else class="vdt-sort-idle" :size="14" :stroke-width="1.75" aria-hidden="true" />
              </button>
              <span v-else class="vdt-th">
                <slot :name="`head-${col.key}`" :column="col">{{ col.label }}</slot>
              </span>
            </th>
          </tr>
        </thead>

        <tbody v-if="firstLoad" aria-hidden="true">
          <tr v-for="r in skeletonRows" :key="`sk${r}`" class="vdt-row is-skeleton">
            <td v-for="(col, c) in columns" :key="col.key" :class="`is-${col.align ?? 'start'}`">
              <VSkeleton :width="skWidth(r, c)" :height="12" />
            </td>
          </tr>
        </tbody>

        <tbody v-else-if="viewRows.length === 0">
          <tr>
            <td :colspan="columns.length" class="vdt-empty">
              <slot name="empty">{{ t('ui.noResults') }}</slot>
            </td>
          </tr>
        </tbody>

        <tbody v-else @pointerover="onCellOver">
          <tr
            v-for="(row, i) in viewRows"
            :key="keyOf(row)"
            :ref="(el) => setRowEl(i, el)"
            class="vdt-row"
            :class="{ 'is-selected': isSelected(row) }"
            :tabindex="tabIndexOf(i)"
            :aria-current="isSelected(row) || undefined"
            @click="onRowClick(row, i, $event)"
            @auxclick="onRowAux(row, i, $event)"
            @keydown="onRowKey(row, i, $event)"
            @focus="focusIdx = i"
          >
            <td v-for="col in columns" :key="col.key" :class="[`is-${col.align ?? 'start'}`, col.class]">
              <div class="vdt-cell" :class="{ 'is-wrap': col.wrap, 't-mono': col.mono }">
                <slot :name="`cell-${col.key}`" :row="row" :value="valueOf(row, col)" :index="i">
                  {{ textOf(row, col) }}
                </slot>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="$slots.footer && !firstLoad" class="vdt-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
/* --vdt-radius: jadval kartaning ichida tursa, sarlavhaning yuqori burchaklari karta
   radiusiga mos yumaloqlansin (overflow: hidden yopishqoq sarlavhani buzadi). */
.vdt {
  --vdt-pad-x: var(--s-4);
  --vdt-row: 44px;
  --vdt-radius: 0px;
  position: relative;
  min-width: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  letter-spacing: -0.003em;
}
.vdt.is-dense {
  --vdt-row: 36px;
}

/* ---------------- jadval ---------------- */
.vdt-scroll.is-contained {
  overflow: auto;
  overscroll-behavior: contain;
}
.vdt-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
}

thead th {
  position: sticky;
  top: var(--vdt-top, 0);
  z-index: var(--z-sticky);
  height: 36px;
  padding: 0 var(--s-3);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--line);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
  text-align: start;
  white-space: nowrap;
  vertical-align: middle;
}
.is-contained thead th {
  top: 0;
}
thead th:first-child {
  border-start-start-radius: var(--vdt-radius);
}
thead th:last-child {
  border-start-end-radius: var(--vdt-radius);
}
th:first-child,
td:first-child {
  padding-inline-start: var(--vdt-pad-x);
}
th:last-child,
td:last-child {
  padding-inline-end: var(--vdt-pad-x);
}
.is-end {
  text-align: end;
}
.is-center {
  text-align: center;
}
td.is-end {
  font-variant-numeric: tabular-nums;
}

.vdt-th {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}
.vdt-sort {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  max-width: 100%;
  margin: 0 calc(var(--s-1_5) * -1);
  padding: var(--s-1) var(--s-1_5);
  border-radius: var(--r-xs);
  font: inherit;
  color: inherit;
  transition: background-color var(--dur-1) var(--ease-out), color var(--dur-1) var(--ease-out);
}
.is-end .vdt-sort {
  flex-direction: row-reverse;
}
.vdt-sort.is-on {
  color: var(--text);
}
@media (hover: hover) {
  .vdt-sort:hover {
    color: var(--text);
    background: var(--fill);
  }
}
.vdt-sort-idle {
  opacity: 0;
  transition: opacity var(--dur-1) var(--ease-out);
}
.vdt-sort:hover .vdt-sort-idle,
.vdt-sort:focus-visible .vdt-sort-idle {
  opacity: 0.7;
}

td {
  height: var(--vdt-row);
  padding: 0 var(--s-3);
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
  transition: background-color var(--dur-1) var(--ease-out);
}
tbody tr:last-child td {
  border-bottom: 0;
}
.vdt-cell {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vdt-cell.is-wrap {
  padding: 10px 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

/* Qayta yuklash: eski qatorlar joyida, xira. */
tbody {
  transition: opacity var(--dur-2) var(--ease-out);
}
.is-refetch tbody,
.is-refetch .vdt-cards {
  opacity: 0.5;
}

.is-clickable .vdt-row {
  cursor: pointer;
}
@media (hover: hover) {
  .is-clickable .vdt-row:hover td {
    background: color-mix(in srgb, var(--fill) 70%, transparent);
  }
}
.vdt-row.is-selected td {
  background: var(--fill);
}
.vdt-row:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
  border-radius: 0;
}
.vdt-row:focus-visible td {
  background: var(--fill);
}

.vdt-empty {
  height: auto;
  padding: var(--s-12) var(--s-4);
  text-align: center;
  color: var(--text-3);
  white-space: normal;
}

.vdt-footer {
  display: flex;
  justify-content: center;
  padding: var(--s-3) var(--vdt-pad-x);
  border-top: 1px solid var(--line);
}

/* ---------------- telefon: kartochkalar ---------------- */
.vdt-cards {
  margin: 0;
  padding: 0;
  list-style: none;
  transition: opacity var(--dur-2) var(--ease-out);
}
.vdt-card {
  display: grid;
  gap: var(--s-2);
  padding: var(--s-4) var(--vdt-pad-x);
  border-bottom: 1px solid var(--line);
  transition: background-color var(--dur-1) var(--ease-out);
}
.vdt-card:last-child {
  border-bottom: 0;
}
.vdt-card.is-skeleton {
  gap: var(--s-3);
}
.is-clickable .vdt-card {
  cursor: pointer;
}
.is-clickable .vdt-card:active,
.vdt-card.is-selected {
  background: var(--fill);
}
.vdt-card:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
  border-radius: 0;
}
.vdt-card-title {
  min-width: 0;
  font-weight: 500;
  color: var(--text);
  overflow-wrap: anywhere;
}
.vdt-card-dl {
  display: grid;
  gap: var(--s-1);
  margin: 0;
}
.vdt-card-pair {
  display: grid;
  grid-template-columns: minmax(88px, 36%) minmax(0, 1fr);
  gap: var(--s-3);
  align-items: baseline;
}
.vdt-card-pair dt {
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
}
.vdt-card-pair dd {
  min-width: 0;
  margin: 0;
  color: var(--text);
  overflow-wrap: anywhere;
}
</style>
