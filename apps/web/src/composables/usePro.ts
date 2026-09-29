// "Pro" rejimi holati - kiritish panelidagi kalit va byudjet hisoblagichi.
//
// Modul darajasida: kalit `InputDock` da, hisob esa javob kelganda
// `ChatView` da yangilanadi - ikkalasi BITTA manbadan o'qishi kerak.
//
// BYUDJET SERVERDAN. Chegaralar (kun/hafta/oy) rolga qarab o'zgaradi va
// hujjat aniq aytadi: ularni qotirmang, `/api/v1/pro/quota` dan o'qing.
// Javob kelgach `pro.remaining` bilan yangilanadi - shunda hisoblagich
// har savoldan keyin qayta so'ramasdan to'g'ri turadi.

import { computed, readonly, ref, watch } from 'vue'
import { proQuota } from '../api/pro.api'
import type { ProInfo, ProQuota, ProWindows } from '../types'

/** Oxirgi holat eslab qolinadi (hujjat ruxsat beradi), lekin YOQILGAN
 *  holda emas: "pro" pulga tushadi, ya'ni odam uni o'zi yoqishi kerak.
 *  Faqat ochiq '1' yoqadi. */
const KEY = 'venera_pro_mode'

const enabled = ref(read() === '1')
const quota = ref<ProQuota | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
let inflight: Promise<void> | null = null

function read(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

watch(enabled, (on) => {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* storage yo'q - kalit shu sessiyada ishlaydi */
  }
})

function lowest(w: ProWindows | undefined): number {
  if (!w) return Number.POSITIVE_INFINITY
  return Math.min(w.day ?? 0, w.week ?? 0, w.month ?? 0)
}

/** Eng tor oynada nechta qolgan - hisoblagichda shu ko'rsatiladi. Oy
 *  bo'yicha 400 qolgani kunlik 0 ni yumshatmaydi. */
const remaining = computed(() => (quota.value ? lowest(quota.value.remaining) : null))

/** Birorta oyna tugagan - kalit bosilmaydi. */
const exhausted = computed(() => remaining.value !== null && remaining.value <= 0)

// Byudjet tugagan bo'lsa kalit o'zi o'chadi: yoqiq turgan kalit bilan
// yuborilgan savol baribir standart rejimda javob berilardi, va odam
// "pro so'radim" deb o'ylab qolardi.
watch(exhausted, (spent) => {
  if (spent) enabled.value = false
})

function load(): Promise<void> {
  if (inflight) return inflight
  loading.value = true
  inflight = (async () => {
    try {
      quota.value = await proQuota()
      loadFailed.value = false
    } catch {
      // Hisoblagich ko'rinmaydi, lekin kalit ISHLAYDI: byudjetni
      // yuqoridagi xizmat baribir o'zi tekshiradi va bermasa sababini
      // javob bilan qaytaradi.
      loadFailed.value = true
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

/** Javob keldi: xizmat aytgan qoldiqni olamiz (qayta so'ramasdan). */
function noteAnswer(pro: ProInfo | null | undefined): void {
  if (!pro) return
  if (pro.remaining) {
    quota.value = {
      remaining: pro.remaining,
      limits: pro.limits ?? quota.value?.limits ?? pro.remaining,
      used: quota.value?.used ?? { day: 0, week: 0, month: 0 },
    }
  }
}

/** Chiqishda: keyingi odam boshqa byudjet bilan keladi. */
function reset(): void {
  quota.value = null
  loadFailed.value = false
}

export function usePro() {
  return { enabled, quota: readonly(quota), remaining, exhausted, loading, loadFailed, load, noteAnswer, reset }
}
