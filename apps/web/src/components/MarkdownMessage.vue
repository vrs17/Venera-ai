<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { useI18n } from 'vue-i18n'
import { useDocViewer } from '../composables/useDocViewer'
import type { AnswerSource } from '../types'

/**
 * Renders a Markdown answer to sanitized HTML. The answer text is
 * backend-controlled, so we render with raw HTML disabled and then run the
 * output through DOMPurify before injecting it via v-html. The `.md` class
 * carries the global markdown styling (see index.css).
 *
 * IQTIBOS CHIPLARI. Yordamchi har gapni `[1]`, `[2]` (hujjat) yoki `[T1]`
 * (jonli so'rov) bilan belgilaydi. Yalang'och `[1]` odamga hech narsa
 * demaydi - shuning uchun sanitizatsiyadan KEYIN matn tugunlari bo'ylab
 * yurib, tanish belgilar chipga aylantiriladi: sichqoncha ustida hujjat nomi
 * va sahifa, bosilsa hujjat o'sha sahifada ochiladi. Kod bloklari va
 * havolalar ichiga tegilmaydi. Matnda bor, lekin manbalar ro'yxatida yo'q
 * raqam o'zgarishsiz qoladi - u iqtibos emas.
 */
const props = defineProps<{ source: string; sources?: AnswerSource[] }>()
const { t } = useI18n({ useScope: 'global' })
const { open: openDoc } = useDocViewer()

// linkify + the default markdown-it preset cover the GFM-ish surface
// (tables, strikethrough, autolinks) the old remark-gfm stack provided.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })

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
function decorate(html: string): string {
  if (!docs.value.size && !lookups.value.size) return html
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement
    if (!el || el.closest('code, pre, a, .cite')) continue
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
      chip.className = isTool ? 'cite cite--tool' : 'cite'
      chip.textContent = id
      chip.setAttribute('data-tip', isTool ? source.tool || id : docTip(source))
      if (!isTool && source.docUrl) {
        chip.setAttribute('data-cite', id)
        chip.setAttribute('role', 'button')
        chip.setAttribute('tabindex', '0')
        chip.setAttribute('aria-label', `${docTip(source)} - ${t('sourceOpen')}`)
      }
      frag.appendChild(chip)
      last = (m.index ?? 0) + m[0].length
    }
    frag.appendChild(doc.createTextNode(value.slice(last)))
    text.replaceWith(frag)
  }
  return doc.body.innerHTML
}

const rendered = computed(() => decorate(DOMPurify.sanitize(md.render(props.source))))

/** Chipga bosish / Enter - hujjat ko'ruvchisi. Hodisa ildizda ushlanadi:
 *  chiplar v-html ichida, ularga to'g'ridan-to'g'ri tinglovchi qo'yib bo'lmaydi. */
function onActivate(e: Event) {
  const chip = (e.target as HTMLElement | null)?.closest<HTMLElement>('.cite[data-cite]')
  if (!chip) return
  if (e instanceof KeyboardEvent && e.key !== 'Enter' && e.key !== ' ') return
  e.preventDefault()
  const source = docs.value.get(Number(chip.dataset.cite))
  if (source) openDoc(source)
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="md" v-html="rendered" @click="onActivate" @keydown="onActivate" />
</template>
