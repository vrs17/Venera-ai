// Barno XOTIRASI ekrani holati - web oynasi (MemoryDialog) va Mini App oynasi (MemorySheet)
// uchun bitta mantiq. Faqat HTTP va holat; ko'rinish komponentlarda.
//
// NEGA MODUL DARAJASIDA EMAS (useConnectors'dan farqli). Xotira faqat oyna ochilganda
// kerak va har ochilishda serverdan yangidan olinadi (odam chatda "eslab qol" deb
// yangisini qo'shgan bo'lishi mumkin). Har oyna o'z nusxasini yaratadi - chiqib boshqa
// hisob bilan kirilganda oldingi odamning xotirasi xotirada qolib ketmaydi.
//
// O'CHIRISH OPTIMISTIK EMAS: qaytarib bo'lmaydigan amal - server "o'chirdim" demaguncha
// band ro'yxatda turadi (kichik spinner bilan). `memory_not_found` kodli 404 - band
// allaqachon yo'q (boshqa tabda yoki chatda "unut" deyilgan): xato emas, ro'yxatdan
// olinadi. KODSIZ 404 (yo'l yo'q - rollback, nginx) esa xato: `assistantErrorKind` uni
// `unavailable` qiladi, band ro'yxatda qoladi va odamga "unutildi" deyilmaydi.
//
// MAXFIYLIK: band matni hech qayerga yozilmaydi (console ham) - faqat ekranda.

import { computed, ref } from 'vue'
import { assistantErrorKind, deleteMemoryItem, forgetAllMemory, listMemory } from '../api/assistant.api'
import type { AssistantErrorKind, MemoryItem } from '../api/assistant.api'

export type MemoryStatus = 'idle' | 'loading' | 'ready' | 'error'

/** Yangisi birinchi (sana bo'lmagani - oxirida, server tartibida). */
function byRecent(items: MemoryItem[]): MemoryItem[] {
  const at = (m: MemoryItem) => Date.parse(m.updated_at ?? m.created_at ?? '') || 0
  return items
    .map((item, i) => ({ item, i, t: at(item) }))
    .sort((a, b) => b.t - a.t || a.i - b.i)
    .map((x) => x.item)
}

/** Bandning kelib chiqishi - `assistant.memory.*` kaliti. */
export function memoryOriginKey(item: MemoryItem): 'sourceUser' | 'sourceRoutine' | 'sourceLearned' {
  if (item.source === 'user') return 'sourceUser'
  if (item.kind === 'routine') return 'sourceRoutine'
  return 'sourceLearned'
}

export function useAssistantMemory() {
  const items = ref<MemoryItem[]>([])
  const status = ref<MemoryStatus>('idle')
  const error = ref<AssistantErrorKind | null>(null)
  /** Hozir o'chirilayotgan band (bir vaqtda bittasi - ikki marta bosish ikki so'rov emas). */
  const removing = ref<string | null>(null)
  const clearing = ref(false)
  /** Har yuklash avlodi: kech kelgan eski javob yangisini bosib ketmasin. */
  let generation = 0

  const count = computed(() => items.value.length)

  async function load(): Promise<void> {
    const gen = ++generation
    // Ro'yxat bor bo'lsa (qayta yuklash) - u ko'rinib turadi, skeletga qaytmaydi.
    if (!items.value.length) status.value = 'loading'
    error.value = null
    try {
      const list = await listMemory()
      if (gen !== generation) return
      items.value = byRecent(list.items)
      status.value = 'ready'
    } catch (err) {
      if (gen !== generation) return
      error.value = assistantErrorKind(err)
      status.value = 'error'
    }
  }

  /** `true` - o'chdi (yoki allaqachon yo'q edi); aks holda xato turi. */
  async function remove(id: string): Promise<true | AssistantErrorKind> {
    if (removing.value || clearing.value) return 'generic'
    removing.value = id
    try {
      await deleteMemoryItem(id)
      items.value = items.value.filter((m) => m.id !== id)
      return true
    } catch (err) {
      const kind = assistantErrorKind(err)
      if (kind === 'notFound') {
        items.value = items.value.filter((m) => m.id !== id)
        return true
      }
      return kind
    } finally {
      removing.value = null
    }
  }

  /** HAMMASINI unutish (tasdiq chaqiruvchida). */
  async function forgetAll(): Promise<true | AssistantErrorKind> {
    if (clearing.value) return 'generic'
    clearing.value = true
    try {
      await forgetAllMemory()
      generation++
      items.value = []
      status.value = 'ready'
      return true
    } catch (err) {
      return assistantErrorKind(err)
    } finally {
      clearing.value = false
    }
  }

  /** Oyna yopildi: matnlar xotirada qolmasin. */
  function reset(): void {
    generation++
    items.value = []
    status.value = 'idle'
    error.value = null
    removing.value = null
  }

  return { items, count, status, error, removing, clearing, load, remove, forgetAll, reset }
}
