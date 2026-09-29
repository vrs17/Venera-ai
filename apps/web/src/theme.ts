// Mavzu: foydalanuvchi TANLOVI ('light' | 'dark' | 'system') localStorage da
// saqlanadi, <html data-theme> esa doim aniq natija - 'light' yoki 'dark'. Tokenlar
// faqat atributga qaraydi, shuning uchun 'system' ham shu ikkitadan biriga yechiladi.
//
// index.html dagi bootstrap.js buni birinchi bo'yashdan OLDIN qiladi (miltillash
// bo'lmasin); bu modul keyin davom ettiradi: OS mavzusi o'zgarsa ('system' da) va
// boshqa tabda tanlov o'zgarsa - sahifa o'zi qayta bo'yaladi.

import { getCurrentScope, onScopeDispose, readonly, ref } from 'vue'
import type { Ref } from 'vue'

export type Theme = 'light' | 'dark'
export type ThemePreference = Theme | 'system'

const KEY = 'venera_theme'

const media: MediaQueryList | null =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  } catch {
    /* maxfiy rejim / sandbox - OS mavzusi */
  }
  return 'system'
}

function writePreference(pref: ThemePreference): void {
  try {
    localStorage.setItem(KEY, pref)
  } catch {
    /* saqlab bo'lmadi - tanlov shu sahifada baribir ishlaydi */
  }
}

function systemTheme(): Theme {
  return media?.matches ? 'dark' : 'light'
}

export function resolveTheme(pref: ThemePreference): Theme {
  return pref === 'system' ? systemTheme() : pref
}

type Listener = (theme: Theme, preference: ThemePreference) => void

let preference: ThemePreference = readPreference()
let painted: Theme | null = null
const listeners = new Set<Listener>()

function paint(): void {
  const theme = resolveTheme(preference)
  if (typeof document !== 'undefined') {
    const root = document.documentElement
    if (root.getAttribute('data-theme') !== theme) root.setAttribute('data-theme', theme)
    // Mobil brauzer paneli: rang tokendan (--bg) olinadi, zahirasi bootstrap.js niki.
    const bg = getComputedStyle(root).getPropertyValue('--bg').trim() || (theme === 'dark' ? '#0e0e0f' : '#ffffff')
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute('content', bg))
  }
  painted = theme
  listeners.forEach((fn) => fn(theme, preference))
}

let started = false

/** Ilova ochilganda bir marta (main.ts): atributni tekshiradi va OS / boshqa tab
 *  o'zgarishlariga obuna bo'ladi. Qayta chaqirish zararsiz. */
export function initTheme(): void {
  if (started) return
  started = true
  paint()
  const onSystem = () => {
    if (preference === 'system') paint()
  }
  if (media) {
    if (typeof media.addEventListener === 'function') media.addEventListener('change', onSystem)
    else media.addListener(onSystem)
  }
  if (typeof window !== 'undefined') {
    // Boshqa tabda tanlov o'zgardi (yoki localStorage.clear()) - shu tab ham ergashsin.
    window.addEventListener('storage', (e) => {
      if (e.key !== null && e.key !== KEY) return
      preference = readPreference()
      paint()
    })
  }
}

/** Saqlangan tanlov: 'light' | 'dark' | 'system'. */
export function getThemePreference(): ThemePreference {
  return preference
}

/** Hozir ekrandagi mavzu (tanlov yechilgan holda). */
export function getTheme(): Theme {
  return painted ?? resolveTheme(preference)
}

/** Tanlovni saqlaydi va darhol qo'llaydi. Akkaunt menyusidagi uch holatli tanlov shu. */
export function setThemePreference(pref: ThemePreference): void {
  preference = pref
  writePreference(pref)
  paint()
}

/** Mavzu yoki tanlov o'zgarganda chaqiriladi. Obunani bekor qiluvchi funksiya qaytaradi. */
export function onThemeChange(cb: Listener): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

/** Komponent uchun reaktiv o'rama: scope yopilganda obuna o'zi bekor bo'ladi. */
export function useTheme(): {
  theme: Readonly<Ref<Theme>>
  preference: Readonly<Ref<ThemePreference>>
  setPreference: (pref: ThemePreference) => void
  toggle: () => void
} {
  const theme = ref<Theme>(getTheme())
  const pref = ref<ThemePreference>(preference)
  const off = onThemeChange((t, p) => {
    theme.value = t
    pref.value = p
  })
  if (getCurrentScope()) onScopeDispose(off)
  return {
    theme: readonly(theme),
    preference: readonly(pref),
    setPreference: setThemePreference,
    // Tugma "teskarisiga" o'tkazadi va tanlovni aniq saqlaydi ('system' ni bekor qiladi).
    toggle: () => setThemePreference(theme.value === 'dark' ? 'light' : 'dark'),
  }
}
