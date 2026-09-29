// Suhbat ustidagi amallar - nomini o'zgartirish va o'chirish (+ "Bekor qilish").
//
// Ikki joydan chaqiriladi: yon paneldagi qatorning ⋯ menyusi va yuqori paneldagi
// sarlavha / ⋯. Ikkalasi AYNI yo'ldan yursin: optimistik o'zgarish `useChats` da,
// xato va "Bekor qilish" - global toast'da (yon panel yig'ilsa ham ko'rinib turadi).

import { useI18n } from 'vue-i18n'
import { localizeApiError } from '../../api/errors'
import { UNDO_MS, useChats } from '../../composables/useChats'
import { forgetSources } from '../../sourcesCache'
import { toast } from '../../ui/useToast'
import type { ChatSummary } from '../../types'

const DELETED_TOAST = 'chat-deleted'

export function useChatActions() {
  const chats = useChats()
  const { t } = useI18n({ useScope: 'global' })

  function fail(err: unknown) {
    toast.error(localizeApiError(err, t))
  }

  /** Bo'sh yoki o'zgarmagan nom - hech narsa (useChats o'zi tekshiradi). */
  async function renameChat(id: string, title: string): Promise<void> {
    try {
      await chats.rename(id, title)
    } catch (err) {
      fail(err)
    }
  }

  async function undo(row: ChatSummary | null): Promise<void> {
    try {
      await chats.undoDelete(row ?? undefined)
    } catch (err) {
      fail(err)
    }
  }

  /** Tasdiqsiz o'chirish + 8 s "Bekor qilish". Ochiq suhbat o'chsa - `onRemovedActive`
   *  (ekran yangi suhbatga o'tadi). */
  async function deleteChat(id: string, onRemovedActive?: () => void): Promise<void> {
    const wasActive = id === chats.activeId.value
    try {
      await chats.remove(id)
    } catch (err) {
      fail(err)
      return
    }
    if (wasActive) onRemovedActive?.()
    // Aynan shu qator: toast to'xtab turganda (hover) useChats taymeri tugasa ham
    // "Bekor qilish" o'sha suhbatni qaytaradi.
    const last = chats.lastDeleted.value
    const removed: ChatSummary | null = last?.chat_id === id ? { ...last } : null
    toast.show({
      id: DELETED_TOAST,
      message: t('chatDeleted'),
      duration: UNDO_MS,
      action: { label: t('undo'), onClick: () => void undo(removed) },
    })
    // Qaytarilmagan suhbatning manbalari brauzerda qolmasin (ichida HRM/CRM
    // ma'lumoti bo'lishi mumkin). Bekor qilish oynasi yopilgandan keyin.
    setTimeout(() => {
      if (!chats.chats.value.some((c) => c.chat_id === id)) forgetSources(id)
    }, UNDO_MS + 1000)
  }

  return { renameChat, deleteChat }
}
