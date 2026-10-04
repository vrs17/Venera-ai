// "Pro" rejimi holati - kiritish panelidagi kalit va byudjet hisoblagichi.
//
// Modul darajasida: kalit `InputDock` da, hisob esa javob kelganda
// `ChatView` da yangilanadi - ikkalasi BITTA manbadan o'qishi kerak.
//
// BYUDJET SERVERDAN. Chegaralar (kun/hafta/oy) rolga qarab o'zgaradi va
// hujjat aniq aytadi: ularni qotirmang, `/api/v1/pro/quota` dan o'qing.
// Javob kelgach `pro.remaining` bilan yangilanadi - shunda hisoblagich
// har savoldan keyin qayta so'ramasdan to'g'ri turadi.
//
// "PRO" FAQAT v2 DVIGATELDA (2026-10-02). Qaysi dvigatel ishlashini backend
// kanal bo'yicha tanlaydi va shu so'rovda aytadi (`engine`, `available`).
// `available !== true` - kalit umuman YO'Q: bosilsa ham backend "pro" ni
// v1 ga yubormasdi, odam esa "Pro so'radim" deb o'ylab qolardi. So'rov
// yiqilsa ham yashirin: dvigatelni bilmasdan "bor" deyish - taxmin.
//
// VERSIYA TANLOVIGA ERGASHADI (2026-10-04). Odamga tanlov berilgan bo'lsa
// (`useEngines`), byudjet TANLANGAN versiya bo'yicha so'raladi (`?engine=`) va
// kalit faqat javob AYNAN shu versiya uchun kelgan bo'lsa ko'rinadi: v2 -> v1
// almashganda eski "v2 da Pro bor" javobi bir lahza ham kalitni ushlab turmasin
// (aks holda "pro" so'rovi v1 ga ketardi).

import { computed, readonly, ref, watch } from 'vue'
import { proQuota } from '../api/pro.api'
import type { ProInfo, ProQuota, ProWindows } from '../types'

/** Oxirgi holat eslab qolinadi (hujjat ruxsat beradi), lekin YOQILGAN
 *  holda emas: "pro" pulga tushadi, ya'ni odam uni o'zi yoqishi kerak.
 *  Faqat ochiq '1' yoqadi. */
const KEY = 'venera_pro_mode'

// Odamning tanlovi eslab qolinadi, lekin yuborishda HAL QILUVCHI emas (`active`):
// kalit ko'rinmasa yoki byudjet tugagan bo'lsa savol standart rejimda ketadi.
const enabled = ref(read() === '1')
const quota = ref<ProQuota | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
/** Qaysi versiya uchun so'ralgan: `null` - server default'i (tanlov yo'q, Mini App). */
const wantEngine = ref<string | null>(null)
let inflight: { engine: string | null; done: Promise<void> } | null = null
// Versiya tez almashsa, eski so'rovning javobi yangisini bosib ketmasin.
let seq = 0

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

/** Shu kanalda "Pro" bormi (v2 va byudjet o'qildi). Faqat ochiq `true`. Versiya
 *  tanlangan bo'lsa - javob o'sha versiya uchun bo'lishi ham shart (`quota.engine`). */
const available = computed(
  () =>
    quota.value?.available === true && (wantEngine.value === null || quota.value.engine === wantEngine.value),
)

/** Eng tor oynada nechta qolgan - hisoblagichda shu ko'rsatiladi. Oy
 *  bo'yicha 400 qolgani kunlik 0 ni yumshatmaydi. */
const remaining = computed(() => (available.value && quota.value ? lowest(quota.value.remaining) : null))

/** Birorta oyna tugagan - kalit bosilmaydi. "Pro" yo'q kanalda (v1) bu
 *  "tugagan" EMAS: u yerda backend nollarni qaytaradi, va odamning saqlangan
 *  tanlovi bekorga o'chib qolmasin. */
const exhausted = computed(() => remaining.value !== null && remaining.value <= 0)

/** SHU savol "pro" bo'lib ketadimi: kalit yoqiq, rejim bor, byudjet bor. */
const active = computed(() => enabled.value && available.value && !exhausted.value)

// Byudjet tugagan bo'lsa kalit o'zi o'chadi: yoqiq turgan kalit bilan
// yuborilgan savol baribir standart rejimda javob berilardi, va odam
// "pro so'radim" deb o'ylab qolardi.
watch(exhausted, (spent) => {
  if (spent) enabled.value = false
})

/** `engine` - odam tanlagan versiya (`useEngines().requestEngine`); berilmasa -
 *  server default'i (eski xatti-harakat). */
function load(engine: string | null = null): Promise<void> {
  wantEngine.value = engine
  if (inflight && inflight.engine === engine) return inflight.done
  const id = ++seq
  loading.value = true
  const done = (async () => {
    try {
      const res = await proQuota(engine)
      if (id !== seq) return
      quota.value = res
      loadFailed.value = false
    } catch {
      if (id !== seq) return
      // Kalit KO'RINMAYDI (`available` - faqat ochiq `true`): qaysi dvigatel
      // ishlashini bilmasdan "Pro bor" deyish - taxmin, v1 da esa "pro"
      // baribir yuborilmasdi. Keyingi ochilishda qayta so'raladi.
      loadFailed.value = true
    } finally {
      if (id === seq) {
        loading.value = false
        inflight = null
      }
    }
  })()
  inflight = { engine, done }
  return done
}

/** Javob keldi: xizmat aytgan qoldiqni olamiz (qayta so'ramasdan).
 *  `engine`/`available` SAQLANADI - aks holda birinchi "pro" javobdan keyin
 *  kalit yo'qolib qolardi. */
function noteAnswer(pro: ProInfo | null | undefined): void {
  if (!pro) return
  const prev = quota.value
  // Server "bu dvigatelda pro yo'q" dedi (sozlama o'zgargan) - kalit yashirinadi.
  if (pro.reason === 'engine') {
    if (prev) quota.value = { ...prev, available: false }
    return
  }
  if (!pro.remaining) return
  const limits = pro.limits ?? prev?.limits ?? pro.remaining
  quota.value = {
    // `remaining` bor `pro` bloki - v2 javobi: so'rov yiqilgan bo'lsa ham endi aniq.
    engine: prev?.engine ?? 'v2',
    available: prev?.available ?? true,
    remaining: pro.remaining,
    limits,
    used: {
      day: Math.max(0, limits.day - pro.remaining.day),
      week: Math.max(0, limits.week - pro.remaining.week),
      month: Math.max(0, limits.month - pro.remaining.month),
    },
  }
}

/** Chiqishda: keyingi odam boshqa byudjet bilan keladi. */
function reset(): void {
  seq += 1
  inflight = null
  quota.value = null
  loadFailed.value = false
  loading.value = false
  wantEngine.value = null
}

export function usePro() {
  return { enabled, quota: readonly(quota), available, active, remaining, exhausted, loading, loadFailed, load, noteAnswer, reset }
}
