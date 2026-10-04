// Yordamchi versiyasi (v1 / v2) - kompozerdagi "v2 ▾" tanlovi va so'rov tanasidagi `engine`.
//
// Modul darajasida: tanlov `InputDock` dagi tugmada, so'rov esa `ChatView` dan ketadi -
// ikkalasi BITTA manbadan o'qishi kerak (usePro bilan bir xil sabab).
//
// QAYSI VERSIYA ISHLASHINI ADMIN HAL QILADI. Server aytadi: hozirgisi (`current`), odam
// tanlay oladimi (`selectable`) va nimalardan (`available`). Tanlov yo'q bo'lsa UI hech
// narsa ko'rsatmaydi va so'rovga `engine` qo'shilmaydi - eski xatti-harakat aynan saqlanadi.
//
// TANLOV ODAMGA BOG'LANGAN (localStorage, `actorId` bo'yicha): bitta brauzerda boshqa
// odam kirsa, oldingisining tanlovi unga o'tmasin. Saqlangan qiymat ruxsat etilganlar
// ichida bo'lmasa (admin olib qo'ygan) - e'tiborsiz, `current` ishlaydi; o'chirilmaydi:
// admin qaytarsa, odamning tanlovi ham qaytadi.
//
// Mini App bu modulni YUKLAMAYDI (alohida kirish nuqtasi) - unga hech narsa o'zgarmaydi.

import { computed, readonly, ref } from 'vue'
import { chatEngines } from '../api/engines.api'
import type { EngineChoice, EngineInfo } from '../types'

const KEY_PREFIX = 'venera_engine:'

const choice = ref<EngineChoice | null>(null)
/** Kimning tanlovi (`actorId` satr). */
const owner = ref<string | null>(null)
/** Odam o'zi tanlagan versiya (saqlangan). Ruxsat etilmagan bo'lishi mumkin - `selected` hal qiladi. */
const picked = ref<string | null>(null)
const loading = ref(false)
// Ketma-ket yuklashlar: eski javob yangisidan keyin kelib, boshqa odamning
// versiyalarini ko'rsatib qo'ymasin (chiqish -> boshqa odam kirishi).
let seq = 0

function storageKey(who: string): string {
  return `${KEY_PREFIX}${who}`
}

function readPick(who: string): string | null {
  try {
    return localStorage.getItem(storageKey(who))
  } catch {
    return null
  }
}

function writePick(who: string, value: string): void {
  try {
    localStorage.setItem(storageKey(who), value)
  } catch {
    /* saqlanmasa ham shu sessiyada ishlaydi */
  }
}

/** Server javobini himoyalab o'qish: maydon yo'q yoki noto'g'ri turda bo'lsa ham UI yiqilmasin. */
function normalize(raw: EngineChoice): EngineChoice {
  const strings = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.length > 0) : []
  const catalog = Array.isArray(raw?.catalog)
    ? raw.catalog
        .filter((e): e is EngineInfo => !!e && typeof e.id === 'string')
        .map((e) => ({ id: e.id, pro: e.pro === true, law: e.law === true }))
    : []
  return {
    current: typeof raw?.current === 'string' ? raw.current : '',
    selectable: raw?.selectable === true,
    available: strings(raw?.available),
    catalog,
  }
}

/** Tanlov tugmasi ko'rinadimi: server ruxsat bergan VA tanlash uchun kamida ikkita versiya bor. */
const selectable = computed(() => !!choice.value?.selectable && choice.value.available.length > 1)

/** Hozir ishlaydigan versiya: odamning tanlovi (ruxsat bo'lsa), aks holda serverniki. */
const selected = computed<string | null>(() => {
  const c = choice.value
  if (!c) return null
  if (selectable.value && picked.value && c.available.includes(picked.value)) return picked.value
  return c.current || null
})

/**
 * So'rov tanasidagi `engine`. Tanlov bor bo'lsa - DOIM ko'rinib turgan versiya (hatto
 * odam hech narsa bosmagan bo'lsa ham): sahifa ochilgandan keyin admin default'ni
 * o'zgartirsa, tugma bir narsani, javob boshqasini ko'rsatmasin. Tanlov yo'q - `null`
 * (maydon yuborilmaydi, server o'zi hal qiladi).
 */
const requestEngine = computed<string | null>(() => (selectable.value ? selected.value : null))

function info(id: string | null | undefined): EngineInfo | null {
  if (!id) return null
  return choice.value?.catalog.find((e) => e.id === id) ?? null
}

/** Menyudagi bandlar: ruxsat etilganlar, katalogdagi imkoniyatlari bilan. */
const options = computed<EngineInfo[]>(() =>
  selectable.value ? (choice.value?.available ?? []).map((id) => info(id) ?? { id, pro: false, law: false }) : [],
)

/**
 * Versiyalarni serverdan olish. Sahifa ochilganda, kirgandan keyin va odam tabga
 * qaytganda chaqiriladi (admin endigina versiya bergan bo'lishi mumkin). Yiqilsa -
 * oldingi holat qoladi; birinchi marta yiqilsa tanlov ko'rinmaydi va so'rov `engine`
 * siz ketadi (server default'i) - bu xavfsiz tomoni.
 */
async function load(actorId: number | string | null | undefined): Promise<void> {
  const who = actorId === null || actorId === undefined ? null : String(actorId)
  if (who !== owner.value) {
    owner.value = who
    picked.value = who ? readPick(who) : null
    choice.value = null
  }
  if (!who) return
  const id = ++seq
  loading.value = true
  try {
    const res = normalize(await chatEngines())
    if (id === seq) choice.value = res
  } catch {
    /* tarmoq yoki eski server (404) - tanlov ko'rinmaydi, chat odatdagidek ishlaydi */
  } finally {
    if (id === seq) loading.value = false
  }
}

/** Odam versiya tanladi. Ruxsat etilmagan qiymat - jimgina e'tiborsiz (menyuda baribir yo'q). */
function select(id: string): void {
  const c = choice.value
  if (!c || !selectable.value || !c.available.includes(id)) return
  picked.value = id
  if (owner.value) writePick(owner.value, id)
}

/** Chiqishda: keyingi odam o'z versiyalari bilan keladi. Saqlangan tanlov o'chirilmaydi -
 *  u egasiga bog'langan va qayta kirganda qaytadi. */
function reset(): void {
  seq += 1
  choice.value = null
  owner.value = null
  picked.value = null
  loading.value = false
}

export function useEngines() {
  return {
    choice: readonly(choice),
    loading: readonly(loading),
    selectable,
    selected,
    requestEngine,
    options,
    info,
    load,
    select,
    reset,
  }
}
