<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { useI18n } from 'vue-i18n'
import { useDocViewer } from '../composables/useDocViewer'
import type { AnswerSource } from '../types'
import VTooltip from '../ui/VTooltip.vue'
import { lookupLabel } from './chat/sources'

/**
 * Markdown javobni xavfsiz HTML ga aylantiradi. Javob matni backenddan keladi:
 * markdown-it xom HTML'siz (`html: false`) ishlaydi, natija DOMPurify'dan o'tadi va
 * shundan KEYIN v-html ga tushadi.
 *
 * IQTIBOS CHIPLARI. Yordamchi har gapni `[1]`, `[2]` (hujjat) yoki `[T1]` (jonli
 * so'rov) bilan belgilaydi. Yalang'och `[1]` odamga hech narsa demaydi - shuning uchun
 * sanitizatsiyadan KEYIN matn tugunlari bo'ylab yurib, tanish belgilar chipga
 * aylantiriladi: ustiga kelsa - hujjat nomi va sahifa (tooltip), bosilsa - hujjat o'sha
 * sahifada ochiladi. Kod bloklari va havolalar ichiga tegilmaydi. Matnda bor, lekin
 * manbalar ro'yxatida yo'q raqam o'zgarishsiz qoladi - u iqtibos emas.
 *
 * `streaming` - javob hali yozilmoqda: oxirida 2px kursor, qayta chizish esa kadrga
 * bir marta (har token'da butun markdown'ni qayta tahlil qilish uzun javobda og'ir).
 */
const props = withDefaults(defineProps<{ source: string; sources?: AnswerSource[]; streaming?: boolean }>(), {
  sources: undefined,
  streaming: false,
})
const { t } = useI18n({ useScope: 'global' })
const { open: openDoc } = useDocViewer()

// linkify + the default markdown-it preset cover the GFM-ish surface
// (tables, strikethrough, autolinks) the old remark-gfm stack provided.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })

// Oqim paytida matn kadrga bir marta yangilanadi; tugaganda - darhol.
const text = ref(props.source)
let raf = 0
function flush() {
  cancelAnimationFrame(raf)
  raf = 0
  text.value = props.source
}
watch(
  () => props.source,
  () => {
    if (!props.streaming) return flush()
    if (!raf) raf = requestAnimationFrame(flush)
  },
)
watch(
  () => props.streaming,
  (on) => !on && flush(),
)
onBeforeUnmount(() => cancelAnimationFrame(raf))

const docs = computed(() => {
  const map = new Map<number, AnswerSource>()
  for (const s of props.sources ?? []) {
    if (s.kind !== 'hrm' && s.kind !== 'crm' && s.citation_index != null) map.set(s.citation_index, s)
  }
  return map
})
const lookups = computed(() => {
  const map = new Map<string, AnswerSource>()
  const calls = (props.sources ?? []).filter((s) => s.kind === 'hrm' || s.kind === 'crm')
  calls.forEach((s, i) => map.set((s.marker?.trim() || `T${i + 1}`).replace(/^\[|\]$/g, ''), s))
  return map
})

function docTip(source: AnswerSource): string {
  const name = source.title?.trim() || source.doc_id || t('sourceDocument')
  return source.page ? `${name}, ${t('sourcePage', { n: source.page })}` : name
}

const CITE = /\[(T?\d{1,3})\]/g

/** `[n]` / `[Tn]` matn tugunlarini chipga aylantiradi. DOMPurify'dan keyin,
 *  o'z hujjatimizda: satr ustida regex yurgizish teg ichini ham buzardi. */
function chipify(doc: Document) {
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement
    if (!el || el.closest('code, pre, a, .vmd-cite')) continue
    if (CITE.test(node.nodeValue ?? '')) texts.push(node as Text)
    CITE.lastIndex = 0
  }
  for (const text of texts) {
    const frag = doc.createDocumentFragment()
    const value = text.nodeValue ?? ''
    let last = 0
    for (const m of value.matchAll(CITE)) {
      const id = m[1]
      const isTool = id.startsWith('T')
      const source = isTool ? lookups.value.get(id) : docs.value.get(Number(id))
      if (!source) continue
      frag.appendChild(doc.createTextNode(value.slice(last, m.index)))
      const chip = doc.createElement('span')
      chip.className = isTool ? 'vmd-cite vmd-cite--tool' : 'vmd-cite'
      chip.textContent = id
      const tip = isTool ? lookupLabel(source, id) : docTip(source)
      chip.setAttribute('data-tip', tip)
      if (!isTool && source.docUrl) {
        chip.setAttribute('data-cite', id)
        chip.setAttribute('role', 'button')
        chip.setAttribute('tabindex', '0')
        chip.setAttribute('aria-label', `${tip} - ${t('sourceOpen')}`)
      } else {
        // Ochiladigan narsa yo'q - ekran o'quvchi "T1" emas, nomini eshitsin.
        chip.setAttribute('role', 'img')
        chip.setAttribute('aria-label', `${id}: ${tip}`)
      }
      frag.appendChild(chip)
      last = (m.index ?? 0) + m[0].length
    }
    frag.appendChild(doc.createTextNode(value.slice(last)))
    text.replaceWith(frag)
  }
}

/** Oqim kursori - oxirgi matn blokining OXIRIGA (yangi qatorga emas). */
function appendCaret(doc: Document) {
  const lastMeaningful = (el: Element): ChildNode | null => {
    let n = el.lastChild
    while (n && n.nodeType === Node.TEXT_NODE && !n.nodeValue?.trim()) n = n.previousSibling
    return n
  }
  let el: Element = doc.body
  for (;;) {
    const n = lastMeaningful(el)
    if (!(n instanceof Element) || n.classList.contains('vmd-cite') || /^(BR|HR|IMG)$/.test(n.tagName)) break
    el = n
  }
  const caret = doc.createElement('span')
  caret.className = 'vmd-caret'
  caret.setAttribute('aria-hidden', 'true')
  el.appendChild(caret)
}

function decorate(html: string, streaming: boolean): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  if (docs.value.size || lookups.value.size) chipify(doc)
  // Javobdagi havola yangi oynada: shu oynada ochilsa SPA va oqimdagi javob yo'qoladi.
  for (const a of doc.body.querySelectorAll('a[href]')) {
    a.setAttribute('target', '_blank')
    a.setAttribute('rel', 'noopener noreferrer')
  }
  // Keng jadval telefonda sahifani emas, o'zini aylantirsin.
  for (const table of doc.body.querySelectorAll('table')) {
    const wrap = doc.createElement('div')
    wrap.className = 'vmd-table'
    table.replaceWith(wrap)
    wrap.appendChild(table)
  }
  if (streaming) appendCaret(doc)
  return doc.body.innerHTML
}

const rendered = computed(() => decorate(DOMPurify.sanitize(md.render(text.value)), props.streaming))

/** Chipga bosish / Enter - hujjat ko'ruvchisi. Hodisa ildizda ushlanadi:
 *  chiplar v-html ichida, ularga to'g'ridan-to'g'ri tinglovchi qo'yib bo'lmaydi. */
function onActivate(e: Event) {
  const chip = (e.target as HTMLElement | null)?.closest<HTMLElement>('.vmd-cite[data-cite]')
  if (!chip) return
  if (e instanceof KeyboardEvent && e.key !== 'Enter' && e.key !== ' ') return
  e.preventDefault()
  const source = docs.value.get(Number(chip.dataset.cite))
  if (source) openDoc(source)
}

/* ---- chip tooltip'i: bitta VTooltip, nishoni - ustidagi chip ---- */
const tip = ref<InstanceType<typeof VTooltip> | null>(null)
const tipTarget = ref<HTMLElement | null>(null)
const tipText = ref('')

function aim(chip: HTMLElement, immediate: boolean) {
  tipText.value = chip.dataset.tip ?? ''
  // Shu chipda allaqachon ulangan: VTooltip o'z tinglovchilari bilan ishlaydi.
  if (tipTarget.value === chip) return
  tipTarget.value = chip
  // Tinglovchilar `target` almashgach (post-flush) ulanadi - birinchi hover'ni o'zimiz.
  void nextTick(() => tip.value?.show(immediate))
}
function onPointerOver(e: PointerEvent) {
  if (e.pointerType === 'touch') return
  const chip = (e.target as HTMLElement | null)?.closest<HTMLElement>('.vmd-cite')
  if (chip) aim(chip, false)
}
function onFocusIn(e: FocusEvent) {
  const chip = (e.target as HTMLElement | null)?.closest<HTMLElement>('.vmd-cite')
  if (chip?.matches(':focus-visible')) aim(chip, true)
}
// Oqimda HTML qayta chiziladi va eski chip DOM'dan chiqadi - tooltip osilib qolmasin.
watch(
  rendered,
  () => {
    if (tipTarget.value && !tipTarget.value.isConnected) {
      tip.value?.hide()
      tipTarget.value = null
    }
  },
  { flush: 'post' },
)
</script>

<template>
  <div class="vmd-root">
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div
      class="vmd"
      @click="onActivate"
      @keydown="onActivate"
      @pointerover="onPointerOver"
      @focusin="onFocusIn"
      v-html="rendered"
    />
    <VTooltip ref="tip" :target="tipTarget" :text="tipText" :describe="false" />
  </div>
</template>

<style scoped>
.vmd {
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body-lg);
  letter-spacing: -0.006em;
  color: var(--text);
  overflow-wrap: break-word;
}
.vmd :deep(> :first-child) { margin-top: 0; }
.vmd :deep(> :last-child) { margin-bottom: 0; }
.vmd :deep(p) {
  margin: 0 0 var(--s-4);
}
.vmd :deep(h1),
.vmd :deep(h2),
.vmd :deep(h3),
.vmd :deep(h4),
.vmd :deep(h5),
.vmd :deep(h6) {
  margin: var(--s-6) 0 var(--s-2);
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.vmd :deep(ul),
.vmd :deep(ol) {
  margin: 0 0 var(--s-4);
  padding-left: 22px;
}
.vmd :deep(li + li) { margin-top: var(--s-1_5); }
.vmd :deep(li > ul),
.vmd :deep(li > ol) { margin: var(--s-1_5) 0 0; }
.vmd :deep(li > p) { margin: 0; }
.vmd :deep(li::marker) { color: var(--text-3); }
.vmd :deep(strong) { font-weight: 600; }
.vmd :deep(a) {
  color: inherit;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
  transition: text-decoration-color var(--dur-1) var(--ease-out);
}
.vmd :deep(a:hover) { text-decoration-color: currentColor; }
.vmd :deep(code) {
  padding: 1px 5px;
  border-radius: var(--r-xs);
  background: var(--fill);
  font-family: var(--font-mono);
  font-size: 0.875em;
}
.vmd :deep(pre) {
  margin: 0 0 var(--s-4);
  padding: var(--s-3) var(--s-4);
  border-radius: var(--r-md);
  background: var(--fill);
  overflow-x: auto;
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
}
.vmd :deep(pre code) {
  padding: 0;
  background: none;
  font-size: inherit;
}
.vmd :deep(blockquote) {
  margin: 0 0 var(--s-4);
  padding-left: var(--s-4);
  border-left: 2px solid var(--line-strong);
  color: var(--text-2);
}
.vmd :deep(hr) {
  margin: var(--s-6) 0;
  border: 0;
  border-top: 1px solid var(--line);
}
.vmd :deep(.vmd-table) {
  margin: 0 0 var(--s-4);
  overflow-x: auto;
}
.vmd :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
}
.vmd :deep(th),
.vmd :deep(td) {
  padding: var(--s-2) var(--s-3) var(--s-2) 0;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
.vmd :deep(th) {
  font-weight: 600;
  color: var(--text-2);
  border-bottom-color: var(--line-strong);
}

/* Iqtibos chipi: ~18px, mono, --fill ustida. `inline` (inline-flex emas): atom-element
   bo'lsa brauzer chip bilan keyingi nuqta orasida qatorni uzib yuboradi ("[1]" / "."). */
.vmd :deep(.vmd-cite) {
  display: inline;
  margin: 0 1px;
  padding: 2px 5px;
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  vertical-align: 1px;
  white-space: nowrap;
  cursor: default;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
.vmd :deep(.vmd-cite[data-cite]) { cursor: pointer; }
@media (hover: hover) {
  .vmd :deep(.vmd-cite:hover) {
    background: var(--fill-hover);
    color: var(--text);
  }
}
.vmd :deep(.vmd-cite:focus-visible) {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}

/* Oqim kursori - spec §0.5: yagona ruxsat etilgan "doimiy" harakat. */
.vmd :deep(.vmd-caret) {
  display: inline-block;
  width: 2px;
  height: 1.1em;
  margin-left: 2px;
  border-radius: 1px;
  background: var(--text);
  vertical-align: -0.18em;
  animation: vmd-caret 1s step-end infinite;
}
@keyframes vmd-caret {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .vmd :deep(.vmd-caret) { animation: none; }
}
</style>
