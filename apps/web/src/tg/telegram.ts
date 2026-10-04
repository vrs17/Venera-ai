// Telegram WebApp qobig'i - TIPLANGAN va DEV STUB bilan.
//
// NEGA O'RAMA. `window.Telegram.WebApp` ning har metodi o'z Bot API versiyasidan
// boshlab bor (masalan `disableVerticalSwipes` - 7.7, `safeAreaInset` - 8.0) va eski
// klientda chaqirilsa SDK konsolga ogohlantirish yozadi yoki xato tashlaydi. Ilova
// kodi buni bilmasligi kerak: bu yerda har chaqiruv versiya bilan tekshiriladi va
// try/catch ichida - Telegram imkoniyati faqat "yaxshilaydi", hech narsani buzmaydi.
//
// DEV STUB. SDK Telegram'dan tashqarida ham yuklanadi va `WebApp` obyekti bor bo'ladi
// (platform 'unknown', initData bo'sh) - lekin uning metodlari jim ishlamaydi. Shuning
// uchun "haqiqiy Telegram" = initData YOKI ma'lum platforma; aks holda o'zimizning stub.
// Stub oddiy brauzerda va headless QA'da ilovani to'liq ishlatadi. Boshqaruv (URL
// parametri ustun, keyin localStorage):
//
//   ?tg_theme=dark|light        Telegram colorScheme (yoki localStorage venera_tg_stub_theme;
//                               bo'lmasa OS'ning prefers-color-scheme)
//   ?tg_safe=47,34[,l,r]        safeAreaInset top,bottom[,left,right] (iPhone o'yig'i /
//                               uy chizig'i; yotiq holatda chap/o'ng o'yiq)
//   ?tg_content=0,0[,l,r]       contentSafeAreaInset (to'liq ekran rejimi)
//   ?tg_platform=ios|android|tdesktop   Enter xulqi (tdesktop - Enter yuboradi)
//   ?tg_init=<satr>             soxta initData - /telegram/session zaxira yo'lini sinash
//   ?tg_stub=1                  SDK "haqiqiy" ko'rinsa ham stub'ga majburlash
//
// QA uchun `window.__tgStub`: `.back()` - Telegram'ning "Orqaga" tugmasini bosish,
// `.setScheme('dark')` - themeChanged hodisasi, `.state()` - BackButton/MainButton/
// closingConfirmation holati va oxirgi tebranishlar (`haptics`) - skrinshot
// skriptlari tekshiradi.

import { readonly, ref } from 'vue'

export type ColorScheme = 'light' | 'dark'
export interface Insets {
  top: number
  bottom: number
  left: number
  right: number
}
export interface TgUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
  language_code?: string
}

type Handler = (...args: unknown[]) => void

/** Telegram'ning o'z oynasidagi tugma (Bot API 6.2). `destructive` - qizil matn. */
export interface PopupButton {
  id?: string
  type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive'
  text?: string
}

interface SdkButton {
  isVisible?: boolean
  setParams(params: Record<string, unknown>): void
  show(): void
  hide(): void
  onClick(cb: Handler): void
  offClick(cb: Handler): void
  showProgress?(leaveActive?: boolean): void
  hideProgress?(): void
}

interface SdkWebApp {
  initData: string
  initDataUnsafe?: { user?: TgUser }
  version: string
  platform: string
  colorScheme?: ColorScheme
  viewportHeight?: number
  viewportStableHeight?: number
  safeAreaInset?: Partial<Insets>
  contentSafeAreaInset?: Partial<Insets>
  isVersionAtLeast(v: string): boolean
  ready(): void
  expand(): void
  disableVerticalSwipes?(): void
  enableClosingConfirmation?(): void
  disableClosingConfirmation?(): void
  setHeaderColor?(c: string): void
  setBackgroundColor?(c: string): void
  setBottomBarColor?(c: string): void
  onEvent(e: string, cb: Handler): void
  offEvent(e: string, cb: Handler): void
  openLink?(url: string, opts?: Record<string, unknown>): void
  downloadFile?(params: { url: string; file_name: string }, cb?: (accepted: boolean) => void): void
  showPopup?(params: { title?: string; message: string; buttons?: PopupButton[] }, cb?: (id: string) => void): void
  /** Bot API 8.0: Mini App hozir oldingi planda (boshqa chatga o'tilmagan). */
  isActive?: boolean
  BackButton?: { show(): void; hide(): void; onClick(cb: Handler): void; offClick(cb: Handler): void }
  MainButton?: SdkButton
  SettingsButton?: { show(): void; hide(): void; onClick(cb: Handler): void; offClick(cb: Handler): void }
  HapticFeedback?: {
    impactOccurred(style: string): void
    notificationOccurred(type: string): void
    selectionChanged(): void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp?: SdkWebApp }
    __tgStub?: { back(): void; setScheme(s: ColorScheme): void; state(): Record<string, unknown> }
  }
}

/* ── Qaysi rejim ───────────────────────────────────────────────────────── */

const params = (() => {
  try {
    return new URLSearchParams(location.search)
  } catch {
    return new URLSearchParams()
  }
})()

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

const sdk: SdkWebApp | null = (() => {
  const app = window.Telegram?.WebApp
  if (!app || params.get('tg_stub') === '1') return null
  const real = !!app.initData || (!!app.platform && app.platform !== 'unknown')
  return real ? app : null
})()

/** Haqiqiy Telegram klientida ochilganmi (stub emas). */
export const isTelegram = sdk !== null

function atLeast(version: string): boolean {
  try {
    return !!sdk && sdk.isVersionAtLeast(version)
  } catch {
    return false
  }
}

/** Xatoni yutadi: Telegram faqat yaxshilaydi, uning nosozligi ilovani yiqitmasin. */
function safe(fn: () => void): void {
  try {
    fn()
  } catch {
    /* eski klient yoki SDK nosozligi - e'tiborsiz */
  }
}

const platform: string = sdk?.platform || params.get('tg_platform') || 'stub'

/** `ios` | `android` | `tdesktop` | ... | `stub`. CSS ham biladi (`html[data-tg-platform]`):
 *  masalan Android'da og'ir `backdrop-filter` o'rniga oddiy parda. */
export const tgPlatform = platform

/** Enter yuboradimi: faqat jismoniy klaviaturali klientlarda (Telegram Desktop, macOS,
 *  Web). Telefonda Enter - yangi qator: ekran klaviaturasida "yuborish" tugmasi
 *  bor, va adashib bosilgan Enter yarim savolni jo'natib yuborardi. */
export const enterSends: boolean = (() => {
  if (sdk) return ['tdesktop', 'macos', 'web', 'weba', 'webk', 'unigram'].includes(sdk.platform)
  if (platform === 'tdesktop') return true
  if (platform === 'ios' || platform === 'android') return false
  try {
    return window.matchMedia('(hover: hover) and (pointer: fine)').matches
  } catch {
    return false
  }
})()

/** Imzolangan Telegram ma'lumoti - serverda bot tokeni bilan tekshiriladi. */
export const initData: string = sdk?.initData || params.get('tg_init') || ''

export const tgUser: TgUser | null = sdk?.initDataUnsafe?.user ?? null

/* ── Mavzu ─────────────────────────────────────────────────────────────── */

function stubScheme(): ColorScheme {
  const fromUrl = params.get('tg_theme')
  if (fromUrl === 'dark' || fromUrl === 'light') return fromUrl
  const saved = stored('venera_tg_stub_theme')
  if (saved === 'dark' || saved === 'light') return saved
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

const scheme = ref<ColorScheme>(sdk?.colorScheme === 'dark' ? 'dark' : sdk ? 'light' : stubScheme())
/** Telegram'ning yorug'/qorong'i rejimi. Ranglar O'ZIMIZNIKI (tokens.css) - Telegram
 *  palitrasi emas: brend bir xil ko'rinsin, faqat yorug'lik Telegram'ga ergashadi. */
export const colorScheme = readonly(scheme)

/** `<html data-theme>` ni qo'yadi va Telegram "xrom"ini (sarlavha, fon, pastki panel)
 *  bizning --bg ga bo'yaydi - ilova va Telegram orasida chegara ko'rinmasin. */
export function applyTheme(): void {
  const root = document.documentElement
  root.setAttribute('data-theme', scheme.value)
  const bg = getComputedStyle(root).getPropertyValue('--bg').trim() || (scheme.value === 'dark' ? '#0e0e0f' : '#ffffff')
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = 'theme-color'
    document.head.appendChild(meta)
  }
  meta.content = bg
  if (!sdk) return
  // Hex rang sarlavhada 6.9 dan; undan eskisi faqat kalit nomini oladi.
  if (atLeast('6.9')) safe(() => sdk.setHeaderColor?.(bg))
  else if (atLeast('6.1')) safe(() => sdk.setHeaderColor?.('bg_color'))
  if (atLeast('6.1')) safe(() => sdk.setBackgroundColor?.(bg))
  if (atLeast('7.10')) safe(() => sdk.setBottomBarColor?.(bg))
}

/* ── Xavfsiz zona ──────────────────────────────────────────────────────── */

/** `?tg_safe=top,bottom[,left,right]` -> to'rtta son (yo'qlari 0). */
function stubInsets(name: string): Insets {
  const raw = params.get(name)
  const [top = 0, bottom = 0, left = 0, right = 0] = (raw ?? '').split(',').map((v) => Math.max(0, Number(v) || 0))
  return { top, bottom, left, right }
}

/** Telegram aytgan xavfsiz zona (qurilma o'yig'i + to'liq ekranda Telegram'ning o'z
 *  tugmalari) -> CSS o'zgaruvchilari. CSS ularni `env(safe-area-inset-*)` bilan
 *  `max()` qiladi (styles.css): qaysi biri katta bo'lsa o'sha, ikki marta qo'shilmaydi.
 *
 *  CHAP/O'NG ham: telefon yotiq holatda o'yiq yon tomonda bo'ladi va Telegram uni
 *  `safeAreaInset.left/right` da aytadi - faqat env() ga tayansak, Android WebView
 *  (u env() ni har doim ham bermaydi) matnni o'yiq ostiga qo'yardi. */
function applyInsets(): void {
  let inset: Insets = { top: 0, bottom: 0, left: 0, right: 0 }
  if (sdk) {
    if (atLeast('8.0')) {
      const a = sdk.safeAreaInset ?? {}
      const c = sdk.contentSafeAreaInset ?? {}
      inset = {
        top: (a.top ?? 0) + (c.top ?? 0),
        bottom: (a.bottom ?? 0) + (c.bottom ?? 0),
        left: (a.left ?? 0) + (c.left ?? 0),
        right: (a.right ?? 0) + (c.right ?? 0),
      }
    }
  } else {
    const s = stubInsets('tg_safe')
    const c = stubInsets('tg_content')
    inset = { top: s.top + c.top, bottom: s.bottom + c.bottom, left: s.left + c.left, right: s.right + c.right }
  }
  const root = document.documentElement.style
  root.setProperty('--tg-js-safe-top', `${inset.top}px`)
  root.setProperty('--tg-js-safe-bottom', `${inset.bottom}px`)
  root.setProperty('--tg-js-safe-left', `${inset.left}px`)
  root.setProperty('--tg-js-safe-right', `${inset.right}px`)
}

/* ── Viewport (klaviatura) ─────────────────────────────────────────────── */

/** Telegram'ning barqaror balandligi (animatsiya paytida tebranmaydi). Stub'da -
 *  oyna balandligi. 0 - noma'lum. */
export function viewportStableHeight(): number {
  if (sdk) return sdk.viewportStableHeight || sdk.viewportHeight || 0
  return window.innerHeight
}

const viewportListeners = new Set<() => void>()
export function onViewportChange(cb: () => void): () => void {
  viewportListeners.add(cb)
  return () => viewportListeners.delete(cb)
}

/* ── Tugmalar: BackButton, MainButton, SettingsButton ──────────────────── */

const stubState = {
  back: false,
  main: { text: '', visible: false, active: true, progress: false },
  closing: false,
  /** Stub'da tebranishlar jurnali - QA "bitta harakat - bitta tebranish" ni tekshiradi. */
  haptics: [] as string[],
}
function logHaptic(kind: string): void {
  if (sdk) return
  stubState.haptics.push(kind)
  if (stubState.haptics.length > 30) stubState.haptics.shift()
}
const backHandlers = new Set<() => void>()

export const backButton = {
  show(): void {
    stubState.back = true
    if (sdk && atLeast('6.1')) safe(() => sdk.BackButton?.show())
  },
  hide(): void {
    stubState.back = false
    if (sdk && atLeast('6.1')) safe(() => sdk.BackButton?.hide())
  },
  onClick(cb: () => void): () => void {
    backHandlers.add(cb)
    if (sdk && atLeast('6.1')) safe(() => sdk.BackButton?.onClick(cb))
    return () => {
      backHandlers.delete(cb)
      if (sdk && atLeast('6.1')) safe(() => sdk.BackButton?.offClick(cb))
    }
  },
}

export interface MainButtonParams {
  text?: string
  visible?: boolean
  active?: boolean
  progress?: boolean
}

/** Telegram'ning pastki asosiy tugmasi. FAQAT kirish ekranida ("Kirish"): chatda
 *  yuborish o'zimizning kompozerimizda - u matn yonida, bosh barmoq ostida. */
export const mainButton = {
  /** Haqiqiy tugma bormi. Yo'q bo'lsa (stub) - sahifa o'z tugmasini chizadi. */
  native: !!sdk?.MainButton,
  set(p: MainButtonParams): void {
    Object.assign(stubState.main, Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined)))
    const mb = sdk?.MainButton
    if (!mb) return
    safe(() => {
      const bg = getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()
      const fg = getComputedStyle(document.documentElement).getPropertyValue('--on-ink').trim()
      mb.setParams({
        ...(p.text !== undefined ? { text: p.text } : {}),
        ...(p.visible !== undefined ? { is_visible: p.visible } : {}),
        ...(p.active !== undefined ? { is_active: p.active } : {}),
        // Tugma ham bizning siyoh rangimizda - Telegram'ning ko'k tugmasi emas.
        ...(bg ? { color: bg } : {}),
        ...(fg ? { text_color: fg } : {}),
      })
      if (p.progress === true) mb.showProgress?.(false)
      if (p.progress === false) mb.hideProgress?.()
    })
  },
  onClick(cb: () => void): () => void {
    const mb = sdk?.MainButton
    if (mb) safe(() => mb.onClick(cb))
    return () => {
      if (mb) safe(() => mb.offClick(cb))
    }
  },
}

/** "⋯" menyusidagi "Sozlamalar" - Telegram foydalanuvchisi uchun tanish joy. */
export function onSettingsButton(cb: () => void): () => void {
  const sb = sdk?.SettingsButton
  if (!sb || !atLeast('7.0')) return () => {}
  safe(() => {
    sb.onClick(cb)
    sb.show()
  })
  return () =>
    safe(() => {
      sb.offClick(cb)
      sb.hide()
    })
}

/* ── Yopishdan oldin so'rash ───────────────────────────────────────────── */

/** Javob yozilayotganda yoki ovoz yozilayotganda ilovani tasodifan yopishdan
 *  saqlaydi ("O'zgarishlar yo'qoladi" so'rovi). Qolgan paytda YO'Q - har yopishda
 *  so'rash bezovta qiladi. */
export function setClosingConfirmation(on: boolean): void {
  stubState.closing = on
  if (!sdk || !atLeast('6.2')) return
  safe(() => (on ? sdk.enableClosingConfirmation?.() : sdk.disableClosingConfirmation?.()))
}

/* ── Tebranish ─────────────────────────────────────────────────────────── */

// BITTA XARITA - tebranish ma'nosini yo'qotmasin (har bosishda tebransa, odam uni
// sezmay qo'yadi):
//
//   yuborish / taklif kartasi          impact light (bir marta)
//   uzoq bosish ishladi, surish chegarasi  impact medium
//   "javob tayyor" (>4 s kutilgan)     impact soft
//   chip, til, Pro, kalit              selectionChanged
//   tasdiq muvaffaqiyati, nusxa        notification success
//   xato                               notification error
//   oyna ochish / navigatsiya          YO'Q
export const haptic = {
  impact(style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft' = 'light'): void {
    logHaptic(`impact:${style}`)
    if (sdk && atLeast('6.1')) safe(() => sdk.HapticFeedback?.impactOccurred(style))
  },
  select(): void {
    logHaptic('select')
    if (sdk && atLeast('6.1')) safe(() => sdk.HapticFeedback?.selectionChanged())
  },
  notify(type: 'success' | 'error' | 'warning'): void {
    logHaptic(`notify:${type}`)
    if (sdk && atLeast('6.1')) safe(() => sdk.HapticFeedback?.notificationOccurred(type))
  },
}

/* ── Havolalar va fayllar ──────────────────────────────────────────────── */

/** Tashqi havola (LEX.UZ, imzolangan fayl): Telegram ichida - `openLink`, ya'ni
 *  tashqi brauzer va Mini App YOPILMAYDI. Stub'da - yangi oyna, `noopener` bilan. */
export function openLink(url: string): void {
  if (sdk?.openLink) {
    try {
      sdk.openLink(url)
      return
    } catch {
      /* pastdagi zaxiraga */
    }
  }
  const win = window.open(url, '_blank', 'noopener,noreferrer')
  if (win) win.opener = null
}

/** Faylni Telegram'ning O'Z yuklab olgichi bilan saqlash (Bot API 8.0). `false` -
 *  bu klientda yo'q: chaqiruvchi `openLink` ga o'tadi. */
export function downloadFile(url: string, filename: string): boolean {
  if (!sdk?.downloadFile || !atLeast('8.0')) return false
  try {
    sdk.downloadFile({ url, file_name: filename })
    return true
  } catch {
    return false
  }
}

/** Telegram'ning o'z oynasi (tizim ko'rinishida) - `showPopup`, `showConfirm` emas:
 *  unda tugmalar umumiy "OK / Cancel" va xavfli amal qizil bo'lmaydi. Natija - bosilgan
 *  tugmaning `id` si (bekor qilinsa `null`). Funksiya `null` qaytarsa - bu klientda
 *  yo'q (stub yoki eski klient): chaqiruvchi sahifa ichidagi tasdiqni ko'rsatadi. */
export function nativePopup(p: { title?: string; message: string; buttons: PopupButton[] }): Promise<string | null> | null {
  if (!sdk?.showPopup || !atLeast('6.2')) return null
  return new Promise((resolve) => {
    try {
      sdk.showPopup!(p, (id) => resolve(id || null))
    } catch {
      resolve(null)
    }
  })
}

/** Odam hozir ilovaga qarab turibdimi: sahifa ko'rinadi va (8.0+) Mini App boshqa
 *  chat ortida yashirilmagan. "Javob tayyor" tebranishi faqat shunda - yashirin
 *  ilovaning tebranishi hech narsa demaydi. */
export function isForeground(): boolean {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return false
  if (sdk && typeof sdk.isActive === 'boolean') return sdk.isActive
  return true
}

/* ── Ishga tushirish ───────────────────────────────────────────────────── */

let started = false

/** main.ts dan BIR marta. Telegram'ga "tayyormiz" deydi, ekranni to'liq ochadi,
 *  pastga surib yopishni o'chiradi (aks holda suhbatni yuqoriga aylantirish ilovani
 *  yopib yuborardi) va hodisalarga obuna bo'ladi. */
export function startTelegram(): void {
  if (started) return
  started = true
  document.documentElement.classList.add(isTelegram ? 'is-telegram' : 'is-tg-stub')
  document.documentElement.dataset.tgPlatform = platform
  applyTheme()
  applyInsets()

  if (sdk) {
    safe(() => sdk.ready())
    safe(() => sdk.expand())
    if (atLeast('7.7')) safe(() => sdk.disableVerticalSwipes?.())
    safe(() =>
      sdk.onEvent('themeChanged', () => {
        scheme.value = sdk.colorScheme === 'dark' ? 'dark' : 'light'
        applyTheme()
      }),
    )
    if (atLeast('8.0')) {
      safe(() => sdk.onEvent('safeAreaChanged', applyInsets))
      safe(() => sdk.onEvent('contentSafeAreaChanged', applyInsets))
    }
    safe(() => sdk.onEvent('viewportChanged', () => viewportListeners.forEach((cb) => cb())))
  } else {
    window.addEventListener('resize', () => viewportListeners.forEach((cb) => cb()))
    // QA boshqaruvi - faqat stub'da (haqiqiy Telegram'da bu obyekt yo'q).
    window.__tgStub = {
      back() {
        const handlers = [...backHandlers]
        handlers[handlers.length - 1]?.()
      },
      setScheme(s: ColorScheme) {
        scheme.value = s
        applyTheme()
      },
      state() {
        return { platform, ...JSON.parse(JSON.stringify(stubState)) }
      },
    }
  }
}
