<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { useI18n } from 'vue-i18n'
import { useDocViewer } from '../composables/useDocViewer'
import type { AnswerSource } from '../types'
import VTooltip from '../ui/VTooltip.vue'
import { hasToolMarks, splitTaskKeys, stripToolMarks } from './chat/answerMarks'
import { markNotes, separateNotes } from './chat/answerNotes'
import { isLookupSource } from './chat/platforms'
import { isLaw, lawTitle, lawUrl } from './chat/sources'

/**
 * Markdown javobni xavfsiz HTML ga aylantiradi. Javob matni backenddan keladi:
 * markdown-it xom HTML'siz (`html: false`) ishlaydi, natija DOMPurify'dan o'tadi va
 * shundan KEYIN v-html ga tushadi.
 *
 * IQTIBOSLAR. Yordamchi har gapni `[1]`, `[2]` (hujjat) yoki `[T1]` (jonli so'rov)
 * bilan belgilaydi. Sanitizatsiyadan KEYIN matn tugunlari bo'ylab yuriladi (kod bloklari
 * va havolalar ichiga tegilmaydi; chat/answerMarks.ts):
 *   * `[T1]` YASHIRILADI (2026-10-10): har band oxiridagi kulrang "T2" qutisi javobni
 *     o'qishni qiyinlashtirardi; qaysi so'rov ekani "Manbalar" tugmasida qoladi;
 *   * `[1]` - kichik yuqori indeks (¹): ustiga kelsa - hujjat nomi va sahifa (tooltip),
 *     bosilsa - hujjat o'sha sahifada ochiladi. Matnda bor, lekin manbalar ro'yxatida
 *     yo'q raqam o'zgarishsiz qoladi - u iqtibos emas;
 *   * vazifa kaliti (`DVSIB-245`) - kichik va xira: vazifa nomi asosiy bo'lib qolsin.
 *
 * QONUN MODDASI (`kind: "law"`, v2) ham `[n]` bilan keladi, lekin ko'ruvchida EMAS,
 * LEX.UZ da ochiladi: chip - haqiqiy `<a target="_blank">` (o'rta tugma, "havolani
 * nusxalash" ham ishlaydi). Havola FAQAT `https://` bo'lsa; aks holda chip jim.
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
    // Jonli so'rovlar (HRM, CRM) - `[T1]`, hujjat raqamlashiga kirmaydi.
    if (!isLookupSource(s) && s.citation_index != null) map.set(s.citation_index, s)
  }
  return map
})

function docTip(source: AnswerSource): string {
  const name = source.title?.trim() || source.doc_id || t('sourceDocument')
  return source.page ? `${name}, ${t('sourcePage', { n: source.page })}` : name
}

const CITE = /\[(\d{1,3})\]/g

/** Matn tugunlari (`skip` selektoriga tushgan elementlar ichidagilardan tashqari). Ro'yxat
 *  OLDINDAN yig'iladi: yurish paytida tugunni almashtirish TreeWalker'ni adashtiradi. */
function textNodes(doc: Document, skip: string): Text[] {
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  const out: Text[] = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement
    if (el && !el.closest(skip)) out.push(node as Text)
  }
  return out
}

/** `[T1]` - matndan olib tashlanadi (manba "Manbalar" tugmasida qoladi). */
function hideToolMarks(doc: Document) {
  for (const text of textNodes(doc, 'code, pre')) {
    const value = text.nodeValue ?? ''
    if (hasToolMarks(value)) text.nodeValue = stripToolMarks(value)
  }
}

/** Tugun iqtibos bilan TUGAYDIMI (`<strong>qoldi<sup class="vmd-cite">1</sup></strong>` ham). */
function endsWithCite(node: Node | null): boolean {
  let n: Node | null = node
  while (n instanceof Element && !n.classList.contains('vmd-cite')) n = n.lastChild
  return n instanceof Element
}

/** `[n]` matn tugunlarini yuqori indeksli iqtibosga aylantiradi. DOMPurify'dan keyin,
 *  o'z hujjatimizda: satr ustida regex yurgizish teg ichini ham buzardi. */
function chipify(doc: Document) {
  const texts = textNodes(doc, 'code, pre, a, .vmd-cite').filter((node) => {
    CITE.lastIndex = 0
    return CITE.test(node.nodeValue ?? '')
  })
  CITE.lastIndex = 0
  for (const text of texts) {
    const frag = doc.createDocumentFragment()
    const value = text.nodeValue ?? ''
    let last = 0
    // Oldingi iqtibos bilan ORASIDA matn yo'q ("[1] [2]", "[1][2]") - `vmd-cite--next` (vergul
    // bilan: "¹,²", aks holda "¹²" 12-manba deb o'qiladi). NEGA JS da, CSS `+` bilan emas:
    // qo'shni-element selektori matn tugunlarini ko'rmaydi - "qoldi¹. Keyin ...²" ham
    // "qo'shni" bo'lib, ikkinchisi oldiga vergul tushardi. Oldingi matn tugunidagi iqtibos
    // ham hisobga olinadi (tugunlar hujjat tartibida almashtiriladi).
    let prevChip = endsWithCite(text.previousSibling)
    for (const m of value.matchAll(CITE)) {
      const id = m[1]
      const source = docs.value.get(Number(id))
      if (!source) continue
      // Bo'shliqsiz yuqori indeks: "kech qoldi [2]." -> "kech qoldi²." (bo'shliq qolsa
      // raqam so'zdan uzilib, keyingi qatorga yolg'iz tushishi mumkin). Bo'sh bo'lak umuman
      // qo'yilmaydi: bo'sh matn tuguni Mini App'da ketma-ket iqtiboslarni "ajratib" qo'yardi.
      const before = value.slice(last, m.index).replace(/[ \u00a0]+$/, '')
      if (before) frag.appendChild(doc.createTextNode(before))
      const next = prevChip && !before.trim()
      const law = isLaw(source)
      const href = law ? lawUrl(source) : null
      // Qonun havolasi - DOMPurify'dan KEYIN qo'yiladi, shuning uchun manzil shu yerda
      // tekshirilgan (`lawUrl`: faqat https) bo'lishi shart.
      const chip = href ? doc.createElement('a') : doc.createElement('sup')
      chip.className = `${law ? 'vmd-cite vmd-cite--law' : 'vmd-cite'}${next ? ' vmd-cite--next' : ''}`
      chip.textContent = id
      const tip = law ? lawTitle(source, t('sourceDocument')) : docTip(source)
      chip.setAttribute('data-tip', tip)
      if (href) {
        chip.setAttribute('href', href)
        chip.setAttribute('target', '_blank')
        chip.setAttribute('rel', 'noopener noreferrer')
        chip.setAttribute('aria-label', `${tip} - ${t('chat.lawOpen')}`)
      } else if (!law && source.docUrl) {
        chip.setAttribute('data-cite', id)
        chip.setAttribute('role', 'button')
        chip.setAttribute('tabindex', '0')
        chip.setAttribute('aria-label', `${tip} - ${t('sourceOpen')}`)
      } else {
        // Ochiladigan narsa yo'q - ekran o'quvchi "1" emas, nomini eshitsin.
        chip.setAttribute('role', 'img')
        chip.setAttribute('aria-label', `${id}: ${tip}`)
      }
      frag.appendChild(chip)
      prevChip = true
      last = (m.index ?? 0) + m[0].length
    }
    const tail = value.slice(last)
    if (tail) frag.appendChild(doc.createTextNode(tail))
    text.replaceWith(frag)
  }
}

/** Vazifa kalitlari (`DVSIB-245`) - `.vmd-key` (kichik, xira). Havola ichida ham (kalit
 *  CRM'ga havola bo'lishi mumkin), kod ichida emas. */
function muteTaskKeys(doc: Document) {
  for (const text of textNodes(doc, 'code, pre, .vmd-cite, .vmd-key')) {
    const parts = splitTaskKeys(text.nodeValue ?? '')
    if (!parts.some((part) => part.key)) continue
    const frag = doc.createDocumentFragment()
    for (const part of parts) {
      if (!part.key) {
        frag.appendChild(doc.createTextNode(part.text))
        continue
      }
      const key = doc.createElement('span')
      key.className = 'vmd-key'
      key.textContent = part.text
      frag.appendChild(key)
    }
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
    // Iqtibos va vazifa kaliti ICHIGA emas - ulardan keyin (kalit xira va kichik).
    if (!(n instanceof Element) || n.matches('.vmd-cite, .vmd-key') || /^(BR|HR|IMG)$/.test(n.tagName)) break
    el = n
  }
  const caret = doc.createElement('span')
  caret.className = 'vmd-caret'
  caret.setAttribute('aria-hidden', 'true')
  el.appendChild(caret)
}

function decorate(html: string, streaming: boolean): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  hideToolMarks(doc)
  markNotes(doc)
  if (docs.value.size) chipify(doc)
  muteTaskKeys(doc)
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

const rendered = computed(() => decorate(DOMPurify.sanitize(md.render(separateNotes(text.value))), props.streaming))

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
/* Sarlavhalar darajasi ko'zga ajralsin (ega, 2026-10-15): avval hammasi 16px - matn bilan bir
   o'lchamda edi, sarlavha faqat qalinligi bilan farq qilardi. Agent `###` ni faqat 2+ bo'limli
   uzun javobda yozadi (H1/H2 ni ham `###` ga tushiradi) - h3 javobning asosiy bo'lim sarlavhasi;
   h1/h2 - qo'lda yozilgan yoki eski matn uchun; h4-h6 - bo'lim ichidagi kichik yorliq. */
.vmd :deep(h1),
.vmd :deep(h2),
.vmd :deep(h3),
.vmd :deep(h4),
.vmd :deep(h5),
.vmd :deep(h6) {
  margin: var(--s-6) 0 var(--s-2);
  font-weight: 650;
  color: var(--text);
}
.vmd :deep(h1) {
  font-size: 24px;
  line-height: 30px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.vmd :deep(h2) {
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  letter-spacing: -0.015em;
}
.vmd :deep(h3) {
  font-size: 18px;
  line-height: 26px;
  letter-spacing: -0.012em;
}
.vmd :deep(h4),
.vmd :deep(h5),
.vmd :deep(h6) {
  margin: var(--s-4) 0 var(--s-1_5);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text-2);
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

/* Hujjat iqtibosi - kichik yuqori indeks ("qoldi²"), quti emas (2026-10-10): javob matni
   asosiy, raqam faqat "manba bor" ishorasi. `line-height: 0` - indeks qator oralig'ini
   kengaytirmasin; `inline` - raqam bilan keyingi nuqta orasida qator uzilmasin. */
.vmd :deep(.vmd-cite) {
  display: inline;
  margin: 0 0 0 1px;
  padding: 0 1px;
  border-radius: 3px;
  color: var(--text-2);
  font-size: 0.7em;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 0;
  vertical-align: super;
  white-space: nowrap;
  cursor: default;
  transition: color var(--dur-1) var(--ease-out);
}
/* Ketma-ket iqtiboslar "¹²" emas, "¹,²" (aks holda 12-manba deb o'qiladi). Qo'shnilik JS da
   aniqlanadi (`chipify`): CSS `+` orasidagi matnni ko'rmaydi. */
.vmd :deep(.vmd-cite--next::before) {
  content: ',';
}
.vmd :deep(.vmd-cite[data-cite]),
.vmd :deep(a.vmd-cite) { cursor: pointer; }
/* Qonun iqtibosi - havola, lekin ko'rinishi boshqalari bilan bir xil (raqamlash umumiy). */
.vmd :deep(a.vmd-cite) {
  color: var(--text-2);
  text-decoration: none;
}
@media (hover: hover) {
  .vmd :deep(.vmd-cite[data-cite]:hover),
  .vmd :deep(a.vmd-cite:hover) {
    color: var(--text);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
}
.vmd :deep(.vmd-cite:focus-visible) {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}

/* "Eslatma: ..." (sana izohi va h.k., chat/answerNotes.ts) - javobning o'zi emas, izoh:
   kichik, xira, chapda ingichka chiziq. Fon juda och - qorong'i mavzuda ham "plita" emas. */
.vmd :deep(p.vmd-note) {
  margin: var(--s-4) 0;
  padding: var(--s-2) var(--s-3);
  border-left: 3px solid var(--line-strong);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  background: color-mix(in srgb, var(--fill) 60%, transparent);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.vmd :deep(p.vmd-note:last-child) { margin-bottom: 0; }
.vmd :deep(p.vmd-note:first-child) { margin-top: 0; }
.vmd :deep(p.vmd-note strong) { color: var(--text-2); }

/* "Manba: HRM, CRM" - hikoya javobining oxirgi qatori (answerNotes.ts): "N manba"
   tugmasini takrorlaydi, shuning uchun javob bilan bahslashmaydigan kichik izoh, qutisiz. */
.vmd :deep(p.vmd-source) {
  margin-top: var(--s-3);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.vmd :deep(p.vmd-source strong) {
  color: var(--text-3);
  font-weight: 600;
}

/* Vazifa kaliti (`DVSIB-245`) - kichik va xira: ro'yxatda vazifa NOMI ko'zga tashlansin,
   kalit faqat izlash uchun. Qalin matn ichida ham og'ir emas. */
.vmd :deep(.vmd-key) {
  color: var(--text-3);
  font-size: 0.82em;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  white-space: nowrap;
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
