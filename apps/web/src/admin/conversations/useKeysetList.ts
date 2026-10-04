// Kursorli ro'yxat ("Yana yuklash"): birinchi sahifa - `useAdminQuery` (filtr o'zgarsa
// eski so'rov bekor, eski qatorlar xira turadi), keyingilari shu yerda qo'shiladi.
//
//   const list = useKeysetList(listTurns, { params: () => ({ ...range, q }) })
//   list.items.value        - hamma yuklangan qatorlar (1-sahifa + qo'shimchalar)
//   list.nextCursor.value   - bo'lsa "Yana yuklash" tugmasi ko'rinadi
//   list.loadMore()         - keyingi sahifa
//   list.patchItems(fn)     - optimistik o'zgarish (xabar holati) - sahifalar TASHLANMAYDI
//
// Nega alohida: 1-sahifa qayta kelganda (filtr, "Yangilash") qo'shimcha sahifalar
// eskiradi va tashlanishi kerak; lekin optimistik `mutate` ham `data` ni almashtiradi -
// o'shanda tashlab yuborilsa, admin 3-sahifada turgan joyidan uloqtirilardi.

import { computed, getCurrentScope, onScopeDispose, ref, shallowRef, toValue, watch } from 'vue'
import type { ComputedRef, MaybeRefOrGetter, Ref, ShallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from '../../ui/useToast'
import { useAdminQuery } from '../components/useAdminQuery'
import type { AdminQuery } from '../components/useAdminQuery'

export interface KeysetPage<T> {
  items: T[]
  nextCursor: string | null
}

export interface KeysetListOptions<P> {
  params: MaybeRefOrGetter<P>
  fresh?: () => P
  enabled?: MaybeRefOrGetter<boolean>
}

export interface KeysetList<T, Page extends KeysetPage<T>, P = object> extends AdminQuery<Page> {
  items: ComputedRef<T[]>
  nextCursor: ShallowRef<string | null>
  /** Ko'rinib turgan 1-sahifa AYNAN qaysi parametrlar bilan olingan (kursor shularga tegishli). */
  pageParams: () => P | null
  loadingMore: Ref<boolean>
  loadMore: () => Promise<void>
  /** Birinchi sahifa javobini o'zgartirish (masalan `counts`), qo'shimchalarni saqlab. */
  mutatePage: (fn: (page: Page) => Page) => void
  /** Har bir yuklangan qatorga (hamma sahifalarda) qo'llanadi. */
  patchItems: (fn: (item: T) => T) => void
}

function isAbort(err: unknown): boolean {
  return (err as { name?: string } | null)?.name === 'AbortError'
}

export function useKeysetList<T, Page extends KeysetPage<T>, P extends object>(
  fetcher: (params: P & { cursor?: string }, signal: AbortSignal) => Promise<Page>,
  options: KeysetListOptions<P>,
): KeysetList<T, Page, P> {
  const { t } = useI18n({ useScope: 'global' })
  // Kursor o'zini bergan so'rovning parametrlariga bog'liq: "Yangilash" (`fresh` - oraliq
  // oxiri HOZIR) dan keyin keyingi sahifa eski `to` bilan so'ralsa, orada kelgan yozuvlar
  // tushib qolardi; filtr almashib, yangi 1-sahifa hali kelmaganda esa eski qatorlarga
  // boshqa filtrniki qo'shilardi. Shuning uchun har javob o'z parametrlari bilan eslanadi.
  const sent = new WeakMap<object, P>()
  const q = useAdminQuery<Page, P>(async (p, signal) => {
    const page = await fetcher(p, signal)
    sent.set(page, p)
    return page
  }, options)

  const extra = shallowRef<T[]>([])
  const cursor = shallowRef<string | null>(null)
  const loadingMore = ref(false)
  let basis: P | null = null
  let ctrl: AbortController | null = null
  let mutating = false

  // `sync`: optimistik `mutate` paytida bayroq hali o'rnatilgan bo'lsin.
  watch(
    q.data,
    (page) => {
      if (mutating) return
      ctrl?.abort()
      ctrl = null
      loadingMore.value = false
      extra.value = []
      cursor.value = page?.nextCursor ?? null
      basis = page ? (sent.get(page) ?? null) : null
    },
    { flush: 'sync' },
  )

  const items = computed<T[]>(() => {
    const first = q.data.value?.items ?? []
    return extra.value.length ? [...first, ...extra.value] : first
  })

  async function loadMore(): Promise<void> {
    const from = cursor.value
    if (!from || loadingMore.value) return
    const own = new AbortController()
    ctrl = own
    loadingMore.value = true
    try {
      const page = await fetcher({ ...(basis ?? toValue(options.params)), cursor: from }, own.signal)
      if (ctrl !== own) return
      extra.value = [...extra.value, ...page.items]
      cursor.value = page.nextCursor
    } catch (err) {
      if (ctrl === own && !isAbort(err)) toast.error(t('ui.errorLoad'))
    } finally {
      if (ctrl === own) {
        loadingMore.value = false
        ctrl = null
      }
    }
  }

  function mutatePage(fn: (page: Page) => Page) {
    mutating = true
    try {
      q.mutate(fn)
    } finally {
      mutating = false
    }
  }

  function patchItems(fn: (item: T) => T) {
    mutatePage((page) => ({ ...page, items: page.items.map(fn) }))
    if (extra.value.length) extra.value = extra.value.map(fn)
  }

  if (getCurrentScope()) onScopeDispose(() => ctrl?.abort())

  return { ...q, items, nextCursor: cursor, pageParams: () => basis, loadingMore, loadMore, mutatePage, patchItems }
}
