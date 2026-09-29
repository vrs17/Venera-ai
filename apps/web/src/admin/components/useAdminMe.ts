// "Kim kirgan va nechta yangi xabar bor" - menyudagi Xabarlar nishoni uchun.
//
// Holat modul darajasida (bitta): qobiq (AdminLayout) uni har 60 soniyada, faqat varaq
// ko'rinib turganda yangilaydi. Xabarlar sahifasi holatni o'zgartirgach
// `refreshAdminMe()` ni chaqirsin - nishon bir daqiqa eski son bilan turmasin.
//
//   const { newReports } = useAdminMe()      // o'qish
//   refreshAdminMe()                          // xabar holati o'zgargach

import { computed, onBeforeUnmount, onMounted, shallowRef } from 'vue'
import type { ComputedRef, ShallowRef } from 'vue'
import { getAdminMe } from '../api'
import type { AdminMe } from '../types'

const POLL_MS = 60_000

const me = shallowRef<AdminMe | null>(null)
let controller: AbortController | null = null
let lastAt = 0

/** Nishonni hozir yangilash. Xato jim o'tadi - nishon shunchaki eski qiymatda qoladi. */
export async function refreshAdminMe(): Promise<void> {
  controller?.abort()
  const ctrl = new AbortController()
  controller = ctrl
  try {
    me.value = await getAdminMe(ctrl.signal)
    lastAt = Date.now()
  } catch {
    /* tarmoq yoki 403 - nishon ko'rinmay qoladi, sahifaning o'zi xatoni aytadi */
  } finally {
    if (controller === ctrl) controller = null
  }
}

export interface AdminMeState {
  me: ShallowRef<AdminMe | null>
  newReports: ComputedRef<number>
  refresh: () => Promise<void>
}

/**
 * `poll: true` - faqat qobiq uchun: davriy yangilash va varaqqa qaytganda darhol
 * yangilash. Yashirin varaqda so'rov yo'q - server va batareya tejaladi.
 */
export function useAdminMe(options: { poll?: boolean } = {}): AdminMeState {
  if (options.poll) {
    let timer: ReturnType<typeof setInterval> | undefined
    const tick = () => {
      if (document.visibilityState === 'visible') void refreshAdminMe()
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible' && Date.now() - lastAt >= POLL_MS) void refreshAdminMe()
    }
    onMounted(() => {
      void refreshAdminMe()
      timer = setInterval(tick, POLL_MS)
      document.addEventListener('visibilitychange', onVisible)
    })
    onBeforeUnmount(() => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      controller?.abort()
    })
  }
  return {
    me,
    newReports: computed(() => Math.max(0, me.value?.newReports ?? 0)),
    refresh: refreshAdminMe,
  }
}
