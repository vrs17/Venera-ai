import { getCurrentScope, onScopeDispose, readonly, ref } from 'vue'
import type { Ref } from 'vue'

// Media query holatini reaktiv qiladi.
//
// Nega kesh: jadvalda yuzlab VTooltip bo'lishi mumkin va har biri "(hover: hover)" ni
// so'raydi. Har so'rov uchun BITTA MediaQueryList va BITTA tinglovchi yetadi.
// Nega hisoblagich: tinglovchi "abadiy" qolmasin - so'rovni ishlatayotgan oxirgi
// komponent yo'q bo'lganda u olib tashlanadi. Scope'dan tashqarida (modul darajasida)
// chaqirilsa - bu foydalanuvchi hech qachon "ketmaydi", yozuv ilova bilan yashaydi.

interface Entry {
  state: Ref<boolean>
  out: Readonly<Ref<boolean>>
  users: number
  detach: () => void
}

const cache = new Map<string, Entry>()

function create(query: string): Entry {
  const state = ref(false)
  let detach = () => {}
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const mql = window.matchMedia(query)
    state.value = mql.matches
    const onChange = (e: MediaQueryListEvent) => {
      state.value = e.matches
    }
    mql.addEventListener('change', onChange)
    detach = () => mql.removeEventListener('change', onChange)
  }
  return { state, out: readonly(state), users: 0, detach }
}

export function useMediaQuery(query: string): Readonly<Ref<boolean>> {
  let entry = cache.get(query)
  if (!entry) {
    entry = create(query)
    cache.set(query, entry)
  }
  const e = entry
  e.users++
  if (getCurrentScope()) {
    onScopeDispose(() => {
      e.users--
      if (e.users > 0 || cache.get(query) !== e) return
      e.detach()
      cache.delete(query)
    })
  }
  return e.out
}

/** Telefon: < 768px (spec §1.5 bo'yicha). */
export const PHONE_QUERY = '(max-width: 767.98px)'

export function useIsPhone(): Readonly<Ref<boolean>> {
  return useMediaQuery(PHONE_QUERY)
}

/** Sichqoncha/trekpad bor qurilma. Faqat sensorli ekranda tooltip ko'rsatilmaydi. */
export function useCanHover(): Readonly<Ref<boolean>> {
  return useMediaQuery('(hover: hover) and (pointer: fine)')
}

export function usePrefersReducedMotion(): Readonly<Ref<boolean>> {
  return useMediaQuery('(prefers-reduced-motion: reduce)')
}
