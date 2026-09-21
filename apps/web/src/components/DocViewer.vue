<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { downloadFile } from '../api/chat.api'
import { localizeApiError } from '../api/errors'
import { ApiError, BASE_URL, getToken } from '../api/http'
import type { ViewerDoc } from '../composables/useDocViewer'
import type { ApiErrorResponse } from '../types'
import { ChevronLeftIcon, ChevronRightIcon, DownloadIcon, MinusIcon, PlusIcon, XIcon } from '../icons'

/**
 * Iqtibos qilingan hujjat - chat yonida, AYNAN PDF qanday bo'lsa shunday.
 *
 * NEGA pdf.js, BRAUZERNING O'Z KO'RUVCHISI EMAS. Sayt `script-src 'self'`
 * va `object-src 'none'` ostida, `blob:` ga ruxsat yo'q - `<iframe>` yoki
 * `<embed>` ichida PDF ochish ishlab chiqishda ishlab, production'da
 * jimgina bo'sh qolardi. pdf.js esa bizning bundle'imiz (o'z originimiz),
 * sahifalarni canvas'ga chizadi va hujjatdagi shriftlarni o'zi bilan olib
 * keladi - matn qayta terilmaydi, o'lchamlar o'zgarmaydi.
 *
 * Fayl `fetch` bilan olinadi (sessiya tokeni sarlavhada), keyin baytlar
 * pdf.js ga beriladi. Iqtibos qilingan sahifa BIRINCHI chiziladi va panel
 * o'sha yerga suriladi; qolgan sahifalar yaqinlik tartibida keyin.
 */
const props = defineProps<{ doc: ViewerDoc }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n({ useScope: 'global' })

const bodyRef = ref<HTMLDivElement | null>(null)
const pagesRef = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const error = ref('')
const numPages = ref(0)
const pageNo = ref(1)
/** 1 = panel kengligiga sig'diriladi. */
const zoom = ref(1)
const zoomPct = computed(() => Math.round(zoom.value * 100))

let pdf: PDFDocumentProxy | null = null
// pdf.js 6: yopish `destroy()` hujjatda emas, yuklash vazifasida.
let loadingTask: PDFDocumentLoadingTask | null = null
let fitScale = 1
let renderSeq = 0
let tasks: RenderTask[] = []
let resizeObserver: ResizeObserver | null = null
let resizeTimer: number | undefined

async function fetchBytes(url: string): Promise<Uint8Array> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}${url}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), Accept: 'application/pdf, */*' },
  })
  if (!response.ok) {
    let body: ApiErrorResponse | undefined
    try {
      body = (await response.json()) as ApiErrorResponse
    } catch {
      /* JSON emas */
    }
    throw new ApiError(body?.message || `Request failed (${response.status})`, body)
  }
  return new Uint8Array(await response.arrayBuffer())
}

function computeFit(pageWidth: number): number {
  const available = (bodyRef.value?.clientWidth ?? 640) - 32
  return Math.max(0.3, available / pageWidth)
}

async function load() {
  loading.value = true
  error.value = ''
  numPages.value = 0
  pageNo.value = props.doc.page ?? 1
  await destroy()
  try {
    // Alohida bo'lak: pdf.js katta, va u faqat hujjat ochilganda kerak.
    const pdfjs = await import('pdfjs-dist')
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
    const data = await fetchBytes(props.doc.url)
    const task = pdfjs.getDocument({ data })
    loadingTask = task
    const opened = await task.promise
    pdf = opened
    numPages.value = opened.numPages
    const first = await opened.getPage(1)
    fitScale = computeFit(first.getViewport({ scale: 1 }).width)
    zoom.value = 1
    loading.value = false
    await renderAll(props.doc.page ?? 1)
  } catch (err) {
    loading.value = false
    error.value = err instanceof ApiError ? localizeApiError(err, t) : t('viewerFailed')
  }
}

function cancelTasks() {
  for (const task of tasks) task.cancel()
  tasks = []
}

async function destroy() {
  cancelTasks()
  renderSeq++
  const old = loadingTask
  loadingTask = null
  pdf = null
  if (pagesRef.value) pagesRef.value.replaceChildren()
  if (old) {
    try {
      await old.destroy()
    } catch {
      /* allaqachon yopilgan */
    }
  }
}

/** Hamma sahifani chizadi; `jumpTo` sahifasi birinchi, keyin unga yaqinlari. */
async function renderAll(jumpTo: number | null) {
  const host = pagesRef.value
  if (!pdf || !host) return
  const document_ = pdf
  const seq = ++renderSeq
  cancelTasks()
  const scale = fitScale * zoom.value
  const dpr = window.devicePixelRatio || 1
  const n = document_.numPages

  // O'lchamlar OLDINDAN qo'yiladi (birinchi sahifa bo'yicha taxmin): shunda
  // iqtibos sahifasiga surish uchun uning chizilishini kutish shart emas,
  // va chizilganda joylashuv sakramaydi (sahifalar odatda bir xil o'lchamda).
  const first = await document_.getPage(1)
  if (seq !== renderSeq) return
  const estimate = first.getViewport({ scale })
  while (host.children.length > n) host.lastElementChild?.remove()
  for (let i = 1; i <= n; i++) {
    let wrap = host.children[i - 1] as HTMLDivElement | undefined
    if (!wrap) {
      wrap = document.createElement('div')
      wrap.className = 'dv__page'
      wrap.appendChild(document.createElement('canvas'))
      host.appendChild(wrap)
    }
    wrap.dataset.page = String(i)
    wrap.classList.toggle('is-cited', i === props.doc.page)
    wrap.style.width = `${Math.floor(estimate.width)}px`
    wrap.style.minHeight = `${Math.floor(estimate.height)}px`
  }
  if (jumpTo) scrollToPage(jumpTo, 'instant')

  const target = jumpTo ?? 1
  const order = Array.from({ length: n }, (_, i) => i + 1).sort(
    (a, b) => Math.abs(a - target) - Math.abs(b - target) || a - b,
  )
  for (const i of order) {
    if (seq !== renderSeq) return
    const page = await document_.getPage(i)
    if (seq !== renderSeq) return
    const viewport = page.getViewport({ scale })
    const wrap = host.children[i - 1] as HTMLDivElement
    const canvas = wrap.firstElementChild as HTMLCanvasElement
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = `${Math.floor(viewport.width)}px`
    canvas.style.height = `${Math.floor(viewport.height)}px`
    wrap.style.width = canvas.style.width
    wrap.style.minHeight = canvas.style.height
    const task = page.render({
      canvas,
      viewport,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
    })
    tasks.push(task)
    try {
      await task.promise
    } catch {
      // Bekor qilingan (masalan kattalashtirish) - yangi chizish yo'lda.
      if (seq !== renderSeq) return
    }
  }
}

function scrollToPage(i: number, behavior: ScrollBehavior) {
  const body = bodyRef.value
  const el = pagesRef.value?.children[i - 1] as HTMLElement | undefined
  if (!body || !el) return
  body.scrollTo({ top: Math.max(0, el.offsetTop - 12), behavior })
  pageNo.value = i
}

function go(i: number) {
  if (!numPages.value) return
  const clamped = Math.min(numPages.value, Math.max(1, Math.round(i)))
  scrollToPage(clamped, 'smooth')
}

function onPageInput(e: Event) {
  const value = Number((e.target as HTMLInputElement).value)
  if (Number.isFinite(value)) go(value)
}

/** Ekranning yuqori uchdan bir qismidagi sahifa - "joriy" sahifa. */
function onScroll() {
  const body = bodyRef.value
  const host = pagesRef.value
  if (!body || !host) return
  const line = body.scrollTop + body.clientHeight * 0.35
  for (let i = 0; i < host.children.length; i++) {
    const el = host.children[i] as HTMLElement
    if (el.offsetTop + el.offsetHeight > line) {
      pageNo.value = i + 1
      return
    }
  }
}

function setZoom(value: number) {
  const next = Math.min(3, Math.max(0.4, value))
  if (next === zoom.value) return
  zoom.value = next
  void renderAll(pageNo.value)
}

async function download() {
  const base = (props.doc.title || props.doc.docId || 'hujjat').replace(/[^\w.\- ]+/g, '_')
  try {
    await downloadFile(props.doc.url, base.toLowerCase().endsWith('.pdf') ? base : `${base}.pdf`)
  } catch (err) {
    error.value = localizeApiError(err, t)
  }
}

// Escape panelni yopadi. ChatView Escape'ni window'da tinglaydi va
// `defaultPrevented` bo'lsa o'tkazib yuboradi - yon panel yig'ilmasin.
function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.isComposing) return
  e.preventDefault()
  emit('close')
}

onMounted(() => {
  document.addEventListener('keydown', onKeyDown)
  // Panel kengligi o'zgarsa (oyna, yon panel) - sig'dirish qayta hisoblanadi.
  if (bodyRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(async () => {
        if (!pdf) return
        const first = await pdf.getPage(1)
        const next = computeFit(first.getViewport({ scale: 1 }).width)
        if (Math.abs(next - fitScale) / fitScale < 0.02) return
        fitScale = next
        void renderAll(pageNo.value)
      }, 150)
    })
    resizeObserver.observe(bodyRef.value)
  }
  void load()
})
watch(() => props.doc.url + '#' + props.doc.page, () => void load())
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeyDown)
  resizeObserver?.disconnect()
  window.clearTimeout(resizeTimer)
  void destroy()
})
</script>

<template>
  <aside class="dv" role="dialog" :aria-label="doc.title">
    <header class="dv__head">
      <div class="dv__titles">
        <h2 class="dv__title" :title="doc.title">{{ doc.title }}</h2>
        <p class="dv__meta">
          <span v-if="doc.docId">{{ doc.docId }}</span>
          <span v-if="doc.page"><template v-if="doc.docId"> · </template>{{ t('sourcePage', { n: doc.page }) }}</span>
          <span v-if="doc.section"> · {{ doc.section }}</span>
        </p>
      </div>
      <button type="button" class="dv__icon" :title="t('close')" :aria-label="t('close')" @click="emit('close')">
        <XIcon :size="16" />
      </button>
    </header>

    <div class="dv__bar">
      <button type="button" class="dv__icon" :disabled="pageNo <= 1" :title="t('viewerPrev')" :aria-label="t('viewerPrev')" @click="go(pageNo - 1)">
        <ChevronLeftIcon :size="12" />
      </button>
      <span class="dv__pages" :aria-label="t('viewerPageOf', { n: pageNo, m: numPages })">
        <input class="dv__input" type="number" min="1" :max="numPages || 1" :value="pageNo" :disabled="!numPages" @change="onPageInput" />
        <span class="dv__of">/ {{ numPages || '–' }}</span>
      </span>
      <button type="button" class="dv__icon" :disabled="!numPages || pageNo >= numPages" :title="t('viewerNext')" :aria-label="t('viewerNext')" @click="go(pageNo + 1)">
        <ChevronRightIcon :size="12" />
      </button>

      <span class="dv__spacer" />

      <button type="button" class="dv__icon" :disabled="!numPages" :title="t('viewerZoomOut')" :aria-label="t('viewerZoomOut')" @click="setZoom(zoom / 1.2)">
        <MinusIcon :size="14" />
      </button>
      <button type="button" class="dv__pct" :disabled="!numPages" @click="setZoom(1)">{{ zoomPct }}%</button>
      <button type="button" class="dv__icon" :disabled="!numPages" :title="t('viewerZoomIn')" :aria-label="t('viewerZoomIn')" @click="setZoom(zoom * 1.2)">
        <PlusIcon :size="14" />
      </button>
      <button type="button" class="dv__icon" :title="t('viewerDownload')" :aria-label="t('viewerDownload')" @click="download">
        <DownloadIcon :size="16" />
      </button>
    </div>

    <div ref="bodyRef" class="dv__body" @scroll.passive="onScroll">
      <p v-if="loading" class="dv__state" role="status">{{ t('viewerLoading') }}</p>
      <p v-else-if="error" class="dv__state dv__state--bad" role="alert">{{ error }}</p>
      <div ref="pagesRef" class="dv__host" />
    </div>
  </aside>
</template>

<style scoped>
.dv {
  position: relative;
  z-index: 21;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: clamp(360px, 46%, 780px);
  height: 100%;
  min-height: 0;
  border-left: 1px solid var(--border);
  background: var(--surface-sunken);
  color: var(--text);
  font-family: 'Figtree', sans-serif;
  animation: fadeUp 0.25s ease both;
}
.dv__head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 12px 10px 16px;
  border-bottom: 1px solid var(--border);
}
.dv__titles {
  flex: 1;
  min-width: 0;
}
.dv__title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 700;
  line-height: 1.3;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.dv__meta {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
.dv__bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.dv__spacer {
  flex: 1;
}
.dv__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.dv__icon:hover:not(:disabled),
.dv__pct:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text);
}
.dv__icon:disabled,
.dv__pct:disabled,
.dv__input:disabled {
  opacity: 0.45;
  cursor: default;
}
.dv__pages {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.dv__input {
  width: 42px;
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-inset);
  color: var(--text);
  font: inherit;
  text-align: center;
  -moz-appearance: textfield;
  appearance: textfield;
}
.dv__input::-webkit-outer-spin-button,
.dv__input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.dv__of {
  color: var(--text-secondary);
}
.dv__pct {
  min-width: 48px;
  padding: 0 6px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.dv__body {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 16px 24px;
  background: var(--surface-inset);
}
.dv__state {
  margin: 24px 0;
  text-align: center;
  font-size: 13.5px;
  color: var(--text-secondary);
}
.dv__state--bad {
  color: var(--bad-fg);
}
.dv__host {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
/* Sahifa elementlari DOM orqali yaratiladi - `:deep` shuning uchun. Oq fon
   ATAYLAB: PDF sahifasi qog'oz, mavzuga bo'ysunmaydi - matn hujjatdagidek
   qora bo'lib qolishi kerak. */
.dv :deep(.dv__page) {
  position: relative;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18), 0 6px 20px rgba(0, 0, 0, 0.1);
  border-radius: 2px;
}
.dv :deep(.dv__page canvas) {
  display: block;
}
/* Iqtibos qilingan sahifa - chetida yupqa aksent chiziq, ko'z darhol topsin. */
.dv :deep(.dv__page.is-cited) {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}
@media (max-width: 768px) {
  .dv {
    position: fixed;
    inset: 0;
    z-index: 45;
    width: auto;
    height: auto;
    border-left: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .dv {
    animation: none !important;
  }
}
</style>
