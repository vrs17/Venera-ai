import { computed, getCurrentScope, onScopeDispose, readonly, ref, shallowRef } from 'vue'
import type { Component } from 'vue'

/* Buyruqlar palitrasi (⌘K / Ctrl K) holati - modul darajasida, ilova bo'ylab BITTA.

   Nega global: palitrani admin qobig'i (shell) bir marta chizadi, "manba"larni esa
   har bir sahifa o'zi ulaydi (sahifalar, foydalanuvchilar, savollar qidiruvi).
   Sahifa yopilsa - uning manbasi ham o'zi uziladi (onScopeDispose).

   Manba (provider) - `(q, signal) => natija | Promise<natija>`. Palitra hamma
   manbalarni parallel so'raydi, eskirgan so'rovlarni `signal` bilan bekor qiladi va
   natijalarni guruhlarga birlashtiradi. Bo'sh `q` bilan ham chaqiriladi: sahifalar
   ro'yxati kabi manba bo'sh so'rovga ham javob beradi, API qidiruvi esa `null`
   qaytaradi.

   ⌘K faqat palitra (VCommandPalette) sahifada o'rnatilgan bo'lsa ushlanadi: chat
   sahifasida brauzerning o'z Ctrl K si ishlayversin. */

export interface CommandItem {
  /** Barqaror id: "so'nggilar" va takrorni olib tashlash shu bo'yicha. */
  id: string
  label: string
  /** Nomdan keyin kulrang izoh (login, bo'lim, sana...). */
  sub?: string
  icon?: Component
  /** O'ng chetdagi qisqa belgi (masalan, "Sahifa" yoki soni). */
  hint?: string
  shortcut?: string | string[]
  /** Qidiruvda nomga qo'shimcha mos so'zlar (statik buyruqlar uchun). */
  keywords?: string[]
  /** Router yo'li. Satr bo'lishi shart - "so'nggilar" localStorage'da saqlanadi. */
  to?: string
  href?: string
  /** Bajariladigan amal. Bo'lmasa `to` / `href` ga o'tiladi. */
  run?: () => void | Promise<void>
}

export interface CommandGroup {
  group: string
  items: CommandItem[]
}

export type CommandProviderResult = CommandGroup | CommandGroup[] | null | undefined
export type CommandProvider = (
  query: string,
  signal: AbortSignal,
) => CommandProviderResult | Promise<CommandProviderResult>

export interface CommandProviderOptions {
  /** Takror ro'yxatdan o'tkazishda eski manba almashtiriladi. */
  id?: string
  /** Kattaroq - yuqoriroqda. Teng bo'lsa - ro'yxatdan o'tish tartibi. */
  priority?: number
}

export interface RegisteredProvider {
  id: string
  fn: CommandProvider
  priority: number
  order: number
}

/** localStorage'da saqlanadigan "so'nggi" band (funksiya va belgisiz). */
export interface RecentCommand {
  id: string
  label: string
  sub?: string
  group: string
  to?: string
  href?: string
}

/* ------------------------------------------------------------ klaviatura yordamchilari */

const IS_MAC =
  typeof navigator !== 'undefined' &&
  /mac|iphone|ipad|ipod/i.test(
    (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ??
      navigator.platform ??
      '',
  )

const NAMED_CODES: Record<string, string> = {
  '/': 'Slash',
  '.': 'Period',
  ',': 'Comma',
  ';': 'Semicolon',
  "'": 'Quote',
  '[': 'BracketLeft',
  ']': 'BracketRight',
  '\\': 'Backslash',
  '-': 'Minus',
  '=': 'Equal',
  '`': 'Backquote',
  enter: 'Enter',
  return: 'Enter',
  esc: 'Escape',
  escape: 'Escape',
  space: 'Space',
  tab: 'Tab',
  backspace: 'Backspace',
  delete: 'Delete',
  up: 'ArrowUp',
  down: 'ArrowDown',
  left: 'ArrowLeft',
  right: 'ArrowRight',
  arrowup: 'ArrowUp',
  arrowdown: 'ArrowDown',
  arrowleft: 'ArrowLeft',
  arrowright: 'ArrowRight',
}

function codeFor(key: string): string | undefined {
  if (/^[a-z]$/.test(key)) return `Key${key.toUpperCase()}`
  if (/^[0-9]$/.test(key)) return `Digit${key}`
  return NAMED_CODES[key]
}

/**
 * Klaviatura hodisasi yorliqqa mosmi: `'mod+k'`, `'/'`, `'shift+enter'`, `['mod', 'k']`.
 * `mod` - macOS'da ⌘, boshqalarda Ctrl (VKbd bilan bir xil yozuv).
 *
 * Harf `e.code` bo'yicha ham tekshiriladi: rus / o'zbek kirill tartibida ⌘K bosilganda
 * `e.key` "л" bo'ladi - tugma joyi esa baribir `KeyK`. Belgi yorliqlarida (`/`) Shift
 * e'tiborga olinmaydi: ba'zi tartiblarda `/` faqat Shift bilan chiqadi.
 */
export function matchesShortcut(e: KeyboardEvent, shortcut: string | string[]): boolean {
  const parts = (Array.isArray(shortcut) ? shortcut : shortcut.split('+'))
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean)
  const want = { ctrl: false, meta: false, alt: false, shift: false }
  let key = ''
  for (const p of parts) {
    if (p === 'mod' || p === 'cmd') {
      if (IS_MAC) want.meta = true
      else want.ctrl = true
    } else if (p === 'meta') want.meta = true
    else if (p === 'ctrl' || p === 'control') want.ctrl = true
    else if (p === 'alt' || p === 'option') want.alt = true
    else if (p === 'shift') want.shift = true
    else key = p
  }
  if (!key) return false
  if (e.ctrlKey !== want.ctrl || e.metaKey !== want.meta || e.altKey !== want.alt) return false
  const symbol = key.length === 1 && !/[a-z0-9]/.test(key)
  if (!symbol && e.shiftKey !== want.shift) return false
  if ((e.key ?? '').toLowerCase() === key) return true
  const code = codeFor(key)
  return !!code && e.code === code
}

/** `aria-keyshortcuts` qiymati: 'mod+k' -> "Meta+K" (mac) / "Control+K". */
export function ariaShortcut(shortcut: string | string[]): string {
  const parts = Array.isArray(shortcut) ? shortcut : shortcut.split('+')
  return parts
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => {
      const l = p.toLowerCase()
      if (l === 'mod' || l === 'cmd') return IS_MAC ? 'Meta' : 'Control'
      if (l === 'ctrl' || l === 'control') return 'Control'
      if (l === 'meta') return 'Meta'
      if (l === 'alt' || l === 'option') return 'Alt'
      if (l === 'shift') return 'Shift'
      if (l === 'esc') return 'Escape'
      return p.length === 1 ? p.toUpperCase() : p
    })
    .join('+')
}

/** Foydalanuvchi matn yozayotgan joy (u yerda `/` kabi bitta harfli yorliq ishlamaydi). */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true
  if (target instanceof HTMLInputElement) {
    return !['button', 'checkbox', 'radio', 'submit', 'reset', 'range', 'color', 'file', 'image'].includes(target.type)
  }
  return false
}

/* ------------------------------------------------------------ qidiruv yordamchilari */

// O'zbekcha tutuq belgisining barcha ko'rinishlari (ʻ ʼ ’ ‘ ` ´) bittaga: foydalanuvchi
// "o'" yozadi, ma'lumotda "oʻ" turadi. Almashtirish 1:1 - belgilash (highlight)
// indekslari asl matnga mos qoladi.
const APOSTROPHES = /[ʻʼ’‘`´]/g

export function normalizeSearch(s: string): string {
  return s.toLocaleLowerCase().replace(APOSTROPHES, "'")
}

/** Statik buyruq so'rovga qanchalik mos: 0 - mos emas; kattaroq - yaxshiroq. */
export function scoreCommand(item: CommandItem, query: string): number {
  const tokens = normalizeSearch(query).split(/\s+/).filter(Boolean)
  if (!tokens.length) return 1
  const label = normalizeSearch(item.label)
  const extra = normalizeSearch([item.sub ?? '', ...(item.keywords ?? [])].join(' '))
  let score = 0
  for (const tok of tokens) {
    if (label.startsWith(tok)) score += 4
    else if (label.includes(` ${tok}`) || label.includes(`-${tok}`)) score += 3
    else if (label.includes(tok)) score += 2
    else if (extra.includes(tok)) score += 1
    else return 0
  }
  return score
}

/* ------------------------------------------------------------ holat */

const RECENT_KEY = 'venera_cmdk_recent'
const RECENT_MAX = 6
const LIVE_MAX = 200

function loadRecents(): RecentCommand[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const list: unknown = JSON.parse(raw)
    if (!Array.isArray(list)) return []
    return list
      .filter(
        (r): r is RecentCommand =>
          !!r && typeof r === 'object' && typeof r.id === 'string' && typeof r.label === 'string' && typeof r.group === 'string',
      )
      .slice(0, RECENT_MAX)
  } catch {
    return []
  }
}

function saveRecents(list: RecentCommand[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list))
  } catch {
    /* maxfiy rejim / kvota - so'nggilar shu sessiya bilan cheklanadi */
  }
}

const isOpen = ref(false)
const initialQuery = ref('')
const providers = shallowRef<RegisteredProvider[]>([])
const recents = ref<RecentCommand[]>(loadRecents())
let order = 0
let autoId = 0

// Oxirgi ko'rsatilgan bandlar (id -> band): "so'nggi" band bosilganda uning `run()`
// funksiyasi shu yerdan olinadi. Sahifa qayta yuklansa - faqat `to` / `href` li
// so'nggilar qoladi (funksiyani saqlab bo'lmaydi).
const live = new Map<string, CommandItem>()

// Bir nechta palitra o'rnatilsa ham faqat bittasi chiziladi (birinchisi).
const hosts = ref<symbol[]>([])

function open(query = '') {
  initialQuery.value = query
  isOpen.value = true
}
function close() {
  isOpen.value = false
}
function toggle() {
  if (isOpen.value) close()
  else open()
}

function register(fn: CommandProvider, opts: CommandProviderOptions = {}): () => void {
  const id = opts.id ?? `p${++autoId}`
  const entry: RegisteredProvider = { id, fn, priority: opts.priority ?? 0, order: ++order }
  providers.value = [...providers.value.filter((p) => p.id !== id), entry]
  let done = false
  const dispose = () => {
    if (done) return
    done = true
    providers.value = providers.value.filter((p) => p !== entry)
  }
  if (getCurrentScope()) onScopeDispose(dispose)
  return dispose
}

/**
 * Statik buyruqlar guruhi (sahifalar, amallar): mijoz tomonda saralanadi.
 * Nom va bandlar getter bo'lishi mumkin - til almashganda yangi matn olinadi.
 */
function registerCommands(
  group: string | (() => string),
  items: CommandItem[] | (() => CommandItem[]),
  opts: CommandProviderOptions & { showOnEmpty?: boolean; limit?: number } = {},
): () => void {
  const provider: CommandProvider = (q) => {
    const list = typeof items === 'function' ? items() : items
    const name = typeof group === 'function' ? group() : group
    if (!q.trim()) return opts.showOnEmpty === false ? null : { group: name, items: list }
    const hits = list
      .map((item, i) => ({ item, i, s: scoreCommand(item, q) }))
      .filter((h) => h.s > 0)
      .sort((a, b) => b.s - a.s || a.i - b.i)
      .slice(0, opts.limit ?? 50)
      .map((h) => h.item)
    return hits.length ? { group: name, items: hits } : null
  }
  return register(provider, opts)
}

function remember(items: Iterable<CommandItem>) {
  for (const it of items) {
    live.delete(it.id)
    live.set(it.id, it)
  }
  while (live.size > LIVE_MAX) {
    const oldest = live.keys().next().value
    if (oldest === undefined) break
    live.delete(oldest)
  }
}

function addRecent(item: CommandItem, group: string) {
  remember([item])
  const entry: RecentCommand = { id: item.id, label: item.label, group }
  if (item.sub) entry.sub = item.sub
  if (item.to) entry.to = item.to
  if (item.href) entry.href = item.href
  const next = [entry, ...recents.value.filter((r) => r.id !== item.id)].slice(0, RECENT_MAX)
  recents.value = next
  saveRecents(next)
}

function removeRecent(id: string) {
  const next = recents.value.filter((r) => r.id !== id)
  recents.value = next
  saveRecents(next)
}

/** Chiqishda (logout) chaqirilsin: boshqa admin avvalgisining so'nggilarini ko'rmasin. */
function clearRecents() {
  recents.value = []
  try {
    localStorage.removeItem(RECENT_KEY)
  } catch {
    /* e'tiborsiz */
  }
}

/** "So'nggi" bandni bajariladigan bandga aylantiradi (bo'lmasa - null, ko'rsatilmaydi). */
function resolveRecent(r: RecentCommand): CommandItem | null {
  const hit = live.get(r.id)
  if (hit) return hit
  if (r.to || r.href) return { id: r.id, label: r.label, sub: r.sub, to: r.to, href: r.href }
  return null
}

/* ------------------------------------------------------------ global ⌘K */

// Tinglovchi faqat palitra (xost) sahifada o'rnatilgan paytda ulanadi: admin'dan
// chiqilganda global ⌘K ushlagichi ham yo'qoladi.
let listening = false
function onGlobalKeyDown(e: KeyboardEvent) {
  if (!hosts.value.length || e.defaultPrevented || e.isComposing || e.repeat) return
  if (!matchesShortcut(e, 'mod+k')) return
  e.preventDefault()
  toggle()
}
function listen() {
  if (listening || typeof window === 'undefined') return
  listening = true
  // capture: yozuv maydoni yoki boshqa komponent hodisani to'xtatsa ham ⌘K ishlasin.
  window.addEventListener('keydown', onGlobalKeyDown, true)
}
function unlisten() {
  if (!listening) return
  listening = false
  window.removeEventListener('keydown', onGlobalKeyDown, true)
}

/** Faqat VCommandPalette uchun: chizuvchi "xost"ni ro'yxatga oladi. */
function claimHost(): { isHost: () => boolean; release: () => void } {
  const token = Symbol('cmdk-host')
  hosts.value = [...hosts.value, token]
  listen()
  return {
    isHost: () => hosts.value[0] === token,
    release: () => {
      hosts.value = hosts.value.filter((h) => h !== token)
      if (hosts.value.length) return
      isOpen.value = false
      unlisten()
    },
  }
}

const sortedProviders = computed(() =>
  [...providers.value].sort((a, b) => b.priority - a.priority || a.order - b.order),
)

export function useCommandPalette() {
  return {
    isOpen: readonly(isOpen),
    /** Ochilgandagi boshlang'ich so'rov (`open('ali')`). */
    initialQuery: readonly(initialQuery),
    providers: sortedProviders,
    recents: readonly(recents),
    open,
    close,
    toggle,
    register,
    registerCommands,
    addRecent,
    removeRecent,
    clearRecents,
    resolveRecent,
    remember,
    claimHost,
  }
}
