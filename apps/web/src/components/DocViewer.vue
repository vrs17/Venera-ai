<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { ChevronLeft, ChevronRight, Download, Minus, Plus, X } from 'lucide-vue-next'
import { downloadFile } from '../api/chat.api'
import { localizeApiError } from '../api/errors'
import { ApiError, BASE_URL, getToken } from '../api/http'
import type { ViewerDoc } from '../composables/useDocViewer'
import type { ApiErrorResponse } from '../types'
import VIconButton from '../ui/VIconButton.vue'
import VSpinner from '../ui/VSpinner.vue'
import VTooltip from '../ui/VTooltip.vue'
import { toast } from '../ui/useToast'
import { useFocusTrap } from '../ui/composables/useFocusTrap'
import { useId } from '../ui/composables/useId'
import { useIsPhone } from '../ui/composables/useMediaQuery'
import { useLayer } from '../ui/composables/useClickOutside'

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

const rootRef = ref<HTMLElement | null>(null)
const titleId = useId('dv-title')
const title = computed(() => props.doc.title || t('sourceDocument'))
// Telefonda panel butun ekranni egallaydi - u yerda u haqiqiy modal oyna (fokus
// tuzog'i, aria-modal). Kattaroq ekranda chat bilan yonma-yon ishlanadi - tuzoq yo'q.
const isPhone = useIsPhone()

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
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      Accept: 'application/pdf, */*',
      // Kanal statistikasi: sarlavhasiz so'rovni server "API" deb hisoblaydi.
      'X-Venera-Client': 'web',
    },
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
  // Harf va raqam HAR QANDAY yozuvda qoladi: kirillcha nom "_____.pdf" bo'lib ketmasin.
  const base = (props.doc.title || props.doc.docId || 'hujjat').replace(/[^\p{L}\p{M}\p{N}.\- ]+/gu, '_')
  try {
    await downloadFile(props.doc.url, base.toLowerCase().endsWith('.pdf') ? base : `${base}.pdf`)
  } catch (err) {
    // Toast'da: ochiq hujjat xato matni ostida qolib ketmasin.
    toast.error(localizeApiError(err, t))
  }
}

// Escape panelni yopadi - umumiy qatlam steki orqali: ustida menyu yoki dialog ochiq
// bo'lsa, Esc avval o'shani yopadi (bitta bosish ikki narsani yopmaydi). Stek
// `preventDefault` qiladi - ChatView yon panelni yig'ib yubormaydi. Tashqariga bosish
// yopmaydi: panel yonida chat ishlatiladi.
const layer = useLayer(true, {
  kind: 'sheet',
  elements: () => [rootRef.value],
  onDismiss: (reason) => reason === 'escape' && emit('close'),
  closeOnOutside: false,
})
useFocusTrap(rootRef, isPhone, { allowOutside: (node) => layer.contains(node) })

// Fokus panelga kiradi va yopilganda ochgan joyga (iqtibos chipi) qaytadi.
let opener: HTMLElement | null = null

onMounted(() => {
  const active = document.activeElement
  opener = active instanceof HTMLElement && active !== document.body ? active : null
  rootRef.value?.focus({ preventScroll: true })
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
  const active = document.activeElement
  if (opener?.isConnected && (!active || active === document.body || rootRef.value?.contains(active))) {
    opener.focus({ preventScroll: true })
  }
  resizeObserver?.disconnect()
  window.clearTimeout(resizeTimer)
  void destroy()
})
</script>

<template>
  <aside
    ref="rootRef"
    class="dv"
    :role="isPhone ? 'dialog' : 'region'"
    :aria-modal="isPhone ? 'true' : undefined"
    :aria-labelledby="titleId"
    tabindex="-1"
    :style="{ zIndex: layer.zIndex.value }"
  >
    <header class="dv__head">
      <div class="dv__top">
        <div class="dv__titles">
          <VTooltip :text="title" placement="bottom-start" :describe="false">
            <h2 :id="titleId" class="dv__title">{{ title }}</h2>
          </VTooltip>
          <p v-if="doc.docId || doc.page || doc.section" class="dv__meta">
            <span v-if="doc.docId" class="dv__id">{{ doc.docId }}</span>
            <span v-if="doc.page"><template v-if="doc.docId"> · </template>{{ t('sourcePage', { n: doc.page }) }}</span>
            <span v-if="doc.section"> · {{ doc.section }}</span>
          </p>
        </div>
        <VIconButton :label="t('close')" :icon="X" size="sm" tooltip-placement="bottom" @click="emit('close')" />
      </div>

      <div class="dv__bar">
        <div class="dv__group">
          <VIconButton
            :label="t('viewerPrev')"
            :icon="ChevronLeft"
            size="sm"
            tooltip-placement="bottom"
            :disabled="pageNo <= 1"
            @click="go(pageNo - 1)"
          />
          <span class="dv__pages">
            <input
              class="dv__input"
              type="number"
              inputmode="numeric"
              min="1"
              :max="numPages || 1"
              :value="pageNo"
              :disabled="!numPages"
              :aria-label="t('viewerPageOf', { n: pageNo, m: numPages })"
              @change="onPageInput"
            />
            <span class="dv__of" aria-hidden="true">/ {{ numPages || '–' }}</span>
          </span>
          <VIconButton
            :label="t('viewerNext')"
            :icon="ChevronRight"
            size="sm"
            tooltip-placement="bottom"
            :disabled="!numPages || pageNo >= numPages"
            @click="go(pageNo + 1)"
          />
        </div>

        <div class="dv__group">
          <VIconButton
            :label="t('viewerZoomOut')"
            :icon="Minus"
            size="sm"
            tooltip-placement="bottom"
            :disabled="!numPages"
            @click="setZoom(zoom / 1.2)"
          />
          <!-- Foiz - "kenglikka moslash" tugmasi ham: bosilsa 100% ga qaytadi. -->
          <VTooltip :text="t('composer.fit')" placement="bottom" :describe="false">
            <button
              type="button"
              class="dv__pct"
              :disabled="!numPages"
              :aria-label="`${t('composer.fit')} (${zoomPct}%)`"
              @click="setZoom(1)"
            >
              {{ zoomPct }}%
            </button>
          </VTooltip>
          <VIconButton
            :label="t('viewerZoomIn')"
            :icon="Plus"
            size="sm"
            tooltip-placement="bottom"
            :disabled="!numPages"
            @click="setZoom(zoom * 1.2)"
          />
          <span class="dv__sep" aria-hidden="true" />
          <VIconButton :label="t('viewerDownload')" :icon="Download" size="sm" tooltip-placement="bottom" @click="download" />
        </div>
      </div>
    </header>

    <div ref="bodyRef" class="dv__body" @scroll.passive="onScroll">
      <div v-if="loading" class="dv__state" role="status">
        <VSpinner :size="20" />
        <span>{{ t('viewerLoading') }}</span>
      </div>
      <p v-else-if="error" class="dv__state dv__state--bad" role="alert">{{ error }}</p>
      <div ref="pagesRef" class="dv__host" />
    </div>
  </aside>
</template>

<style scoped>
/* Joylashuv (spec §4.3): ≥1680 - chat yonida (ustun), undan kichikda - o'ngdan
   suzuvchi panel (chat orqada ishlashda davom etadi), telefonda - butun ekran. */
.dv {
  /* Qog'oz ATAYLAB oq: PDF sahifasi mavzuga bo'ysunmaydi. Qorong'i mavzuda --ink
     deyarli oq (#F4F4F3) - xom rang yozmasdan "qog'oz" olamiz. */
  --dv-paper: var(--surface);
  position: fixed;
  top: var(--s-2);
  right: var(--s-2);
  bottom: var(--s-2);
  display: flex;
  flex-direction: column;
  width: min(560px, calc(100vw - var(--s-4)));
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  background: var(--surface);
  box-shadow: var(--e3);
  color: var(--text);
  outline: none;
  animation: dv-in var(--dur-3) var(--ease-sheet) both;
}
:root[data-theme='dark'] .dv {
  --dv-paper: var(--ink);
}
.dv:focus-visible {
  outline: none;
}
@keyframes dv-in {
  from {
    opacity: 0;
    transform: translateX(24px);
  }
}
@media (min-width: 1680px) {
  .dv {
    position: relative;
    inset: auto;
    flex-shrink: 0;
    width: clamp(480px, 38%, 760px);
    height: 100%;
    border-width: 0 0 0 1px;
    border-radius: 0;
    box-shadow: none;
    background: var(--bg);
  }
}
@media (max-width: 767.98px) {
  .dv {
    inset: 0;
    width: auto;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    padding-top: env(safe-area-inset-top, 0px);
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
}

.dv__head {
  flex-shrink: 0;
  padding: var(--s-4) var(--s-3) var(--s-2) var(--s-5);
  border-bottom: 1px solid var(--line);
}
.dv__top {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
}
.dv__titles {
  flex: 1;
  min-width: 0;
  padding-top: var(--s-1);
}
.dv__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.dv__meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.dv__id {
  font-family: var(--font-mono);
}

.dv__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-2);
  margin: var(--s-2) 0 0 calc(var(--s-2) * -1);
}
.dv__group {
  display: flex;
  align-items: center;
  gap: 2px;
}
.dv__sep {
  width: 1px;
  height: 16px;
  margin: 0 var(--s-1);
  background: var(--line);
}
.dv__pages {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  padding: 0 var(--s-1);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  font-variant-numeric: tabular-nums;
}
.dv__input {
  width: 44px;
  height: 28px;
  padding: 0 var(--s-1);
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: var(--fill);
  color: var(--text);
  font: inherit;
  text-align: center;
  -moz-appearance: textfield;
  appearance: textfield;
  transition:
    border-color var(--dur-1) var(--ease-out),
    box-shadow var(--dur-1) var(--ease-out);
}
.dv__input:focus-visible {
  outline: none;
  border-color: var(--ink);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--text) 10%, transparent);
}
.dv__input::-webkit-outer-spin-button,
.dv__input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.dv__input:disabled {
  color: var(--text-4);
}
.dv__of {
  color: var(--text-3);
}
.dv__pct {
  min-width: 48px;
  height: 32px;
  padding: 0 var(--s-1_5);
  border-radius: var(--r-sm);
  color: var(--text-2);
  font-size: var(--fs-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .dv__pct:not(:disabled):hover {
    background: var(--fill);
    color: var(--text);
  }
}
.dv__pct:disabled {
  color: var(--text-4);
}

.dv__body {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: var(--s-4) var(--s-4) var(--s-8);
  background: var(--fill);
}
.dv__state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  margin: var(--s-8) 0;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  text-align: center;
}
.dv__state--bad {
  color: var(--crit-text);
}
.dv__host {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-3);
}
/* Sahifa elementlari DOM orqali yaratiladi - `:deep` shuning uchun. */
/* Qog'oz: hairline chegara + e1. Chegara box-shadow bilan (border emas) - sahifa o'lchami
   JS da canvas'ga teng qo'yiladi, 1px border uni siqib qo'yardi. */
.dv :deep(.dv__page) {
  position: relative;
  background: var(--dv-paper);
  border-radius: 2px;
  box-shadow:
    0 0 0 1px var(--line),
    var(--e1);
}
.dv :deep(.dv__page canvas) {
  display: block;
}
/* Iqtibos qilingan sahifa - faqat biroz quyuqroq hairline. Oldingi 2px siyoh outline
   sahifani qalin qora ramkaga o'rardi; sahifa baribir ochilganda shu yerga suriladi,
   sarlavhada "N-bet" turadi va iqtibos matni hujjatning o'zida belgilangan. */
.dv :deep(.dv__page.is-cited) {
  box-shadow:
    0 0 0 1px var(--line-strong),
    var(--e1);
}

@media (prefers-reduced-motion: reduce) {
  .dv {
    animation: none;
  }
}
</style>
