// Admin sahifasining "so'rov holati" - bitta API chaqiruv, global filtrga bog'langan.
//
//   const q = useAdminQuery(getOverview)                   // params = useAdminFilters().params
//   const q = useAdminQuery(listTurns, {
//     params: () => ({ ...filters.params.value, q: search.value }),
//     fresh: () => ({ ...filters.freshParams(), q: search.value }),   // ixtiyoriy, "Yangilash" uchun
//   })
//   const q = useAdminQuery((_: null, signal) => getSystem(signal), { params: null })  // filtrsiz
//   q.data.value      - oxirgi muvaffaqiyatli javob (qayta yuklashda ham ESKISI turadi)
//   q.firstLoad       - birinchi yuklash: skelet ko'rsating
//   q.refetching      - filtr o'zgardi, yangisi kelyapti: eski kadr xira (opacity .5)
//   q.error / q.errorText - oxirgi urinish xatosi; `data` bo'lsa u saqlanadi
//   q.refresh()       - "Yangilash" va "Qayta urinish" tugmalari uchun
//
// Nega AbortController: sana va kanal tez-tez almashadi; eski so'rovning javobi
// yangisidan KEYIN kelib, ekranni boshqa davr bilan bosib ketmasin.
// Nega parametrlar satr (JSON) bo'yicha solishtiriladi: `params` computed har safar yangi
// obyekt qaytaradi - qiymati o'zgarmagan bo'lsa ortiqcha so'rov ketmasin.

import { computed, getCurrentScope, onScopeDispose, ref, shallowRef, toValue, watch } from 'vue'
import type { ComputedRef, MaybeRefOrGetter, Ref, ShallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '../../api/http'
import { useAdminFilters } from '../useAdminFilters'
import type { RangeParams } from '../types'

export type AdminFetcher<T, P> = (params: P, signal: AbortSignal) => Promise<T>

export interface AdminQueryOptions<P> {
  /** So'rov parametrlari (ref, computed yoki getter). Standart - global filtr; `null` - parametrsiz. */
  params?: MaybeRefOrGetter<P>
  /** `false` bo'lsa so'rov yuborilmaydi (masalan, id hali yo'q). */
  enabled?: MaybeRefOrGetter<boolean>
  /**
   * "Yangilash" uchun parametrlar - oraliq oxiri AYNI HOZIR bo'lsin. Global filtr
   * `params` i sahifa ochilgan daqiqada qotib qoladi; standart holatda
   * `useAdminFilters().freshParams` o'zi ulanadi, o'z `params` ingiz bo'lsa - shu yerda bering.
   */
  fresh?: () => P
}

export interface AdminQuery<T> {
  data: ShallowRef<T | null>
  error: ShallowRef<unknown>
  /** Foydalanuvchiga ko'rsatiladigan bitta jumla (til bo'yicha) yoki null. */
  errorText: ComputedRef<string | null>
  /** HTTP holati (403, 404, 503...) - maxsus bo'sh holatlar uchun. */
  errorStatus: ComputedRef<number | null>
  loading: Ref<boolean>
  /** Hali hech narsa kelmagan va kutilmoqda - skelet. */
  firstLoad: ComputedRef<boolean>
  /** Eski ma'lumot bor, yangisi kelmoqda - xira kadr. */
  refetching: ComputedRef<boolean>
  refresh: () => Promise<void>
  /** Javobni joyida o'zgartirish (optimistik yangilash, PATCH natijasi). */
  mutate: (fn: (current: T) => T) => void
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException ? err.name === 'AbortError' : (err as { name?: string })?.name === 'AbortError'
}

export function useAdminQuery<T>(
  fetcher: AdminFetcher<T, RangeParams>,
  options?: AdminQueryOptions<RangeParams>,
): AdminQuery<T>
export function useAdminQuery<T, P>(
  fetcher: AdminFetcher<T, P>,
  options: AdminQueryOptions<P> & { params: MaybeRefOrGetter<P> },
): AdminQuery<T>
export function useAdminQuery<T, P>(
  fetcher: AdminFetcher<T, P>,
  options: AdminQueryOptions<P> = {},
): AdminQuery<T> {
  const { t } = useI18n({ useScope: 'global' })
  // Parametr berilmasa - global filtr (sana + kanal). `params: null` - ATAYLAB filtrsiz
  // so'rov (masalan, tizim holati): `??` emas, aks holda null ham filtrga aylanardi.
  const filters = options.params === undefined ? useAdminFilters() : null
  const source: MaybeRefOrGetter<P> = filters
    ? (filters.params as unknown as MaybeRefOrGetter<P>)
    : (options.params as MaybeRefOrGetter<P>)
  const fresh: (() => P) | undefined = options.fresh ?? (filters ? () => filters.freshParams() as unknown as P : undefined)

  const data = shallowRef<T | null>(null)
  const error = shallowRef<unknown>(null)
  const loading = ref(false)

  let controller: AbortController | null = null
  let seq = 0

  async function run(override?: P): Promise<void> {
    controller?.abort()
    if (options.enabled !== undefined && !toValue(options.enabled)) {
      controller = null
      loading.value = false
      return
    }
    const ctrl = new AbortController()
    controller = ctrl
    const id = ++seq
    loading.value = true
    try {
      const result = await fetcher(override ?? toValue(source), ctrl.signal)
      if (id !== seq) return
      data.value = result
      error.value = null
    } catch (err) {
      if (id !== seq || isAbort(err)) return
      error.value = err
    } finally {
      if (id === seq) {
        loading.value = false
        if (controller === ctrl) controller = null
      }
    }
  }

  const key = computed(() => {
    const enabled = options.enabled === undefined ? true : toValue(options.enabled)
    return `${enabled ? 1 : 0}|${JSON.stringify(toValue(source) ?? null)}`
  })
  watch(key, () => void run(), { immediate: true })

  /** "Yangilash" / "Qayta urinish": oraliq oxiri - hozir (yangi yozuvlar ham kirsin). */
  function refresh(): Promise<void> {
    return run(fresh?.())
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      seq += 1
      controller?.abort()
      controller = null
    })
  }

  const errorStatus = computed<number | null>(() => {
    const e = error.value
    return e instanceof ApiError && typeof e.status === 'number' ? e.status : null
  })

  const errorText = computed<string | null>(() => {
    if (!error.value) return null
    switch (errorStatus.value) {
      case 403:
        return t('admin.error.forbidden')
      case 404:
        return t('admin.error.notFound')
      case 503:
        return t('admin.error.storage')
      default:
        return t('ui.errorLoad')
    }
  })

  return {
    data,
    error,
    errorText,
    errorStatus,
    loading,
    firstLoad: computed(() => loading.value && data.value === null),
    refetching: computed(() => loading.value && data.value !== null),
    refresh,
    mutate(fn) {
      if (data.value !== null) data.value = fn(data.value)
    },
  }
}
