// Iqtibos qilingan hujjatni ko'rish paneli - holat.
//
// Manba ro'yxati (`AnswerSources.vue`) hujjatni OCHADI, panel esa chat
// yonida (`ChatView.vue`) turadi - ular ota-bola emas, shuning uchun holat
// modul darajasida: bir joydan ochiladi, boshqa joyda ko'rinadi.

import { readonly, ref } from 'vue'
import type { AnswerSource } from '../types'

export interface ViewerDoc {
  /** Brauzer ocha oladigan yo'l (`/api/v1/chat/doc/...`), `#page` siz. */
  url: string
  title: string
  docId: string | null
  /** Iqtibos qilingan sahifa - panel shu sahifadan ochiladi. */
  page: number | null
  section: string | null
}

const current = ref<ViewerDoc | null>(null)

export function useDocViewer() {
  function open(source: AnswerSource) {
    if (!source.docUrl) return
    const [url] = source.docUrl.split('#')
    const fromHash = /#page=(\d+)/.exec(source.docUrl)
    const page = source.page && source.page > 0 ? source.page : fromHash ? Number(fromHash[1]) : null
    current.value = {
      url,
      title: source.title?.trim() || source.doc_id || '',
      docId: source.doc_id ?? null,
      page,
      section: source.section?.trim() || null,
    }
  }
  function close() {
    current.value = null
  }
  return { doc: readonly(current), open, close }
}
