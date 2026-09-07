// Desktop ilovasini yuklab olish uchun manifest o'quvchi.
//
// Manba: /download/version.json — bu AYNAN desktop ilovaning avtomatik
// yangilanish manifesti (release/version.json, apps/desktop/tools/make_manifest.py
// generatsiya qiladi). nginx bitta papkani ikkita yo'l ostida ko'rsatadi, shuning
// uchun sayt va auto-update har doim bir xil versiyani ko'radi — ikkinchi nusxa
// yo'q, sinxrondan chiqish ham yo'q.
//
// apiFetch ISHLATILMAYDI: bu Spring Boot kontrakti emas, nginx bergan statik
// fayl. Bearer token ham, /api prefiksi ham kerak emas.

/** Bitta platforma uchun o'rnatuvchi fayl. */
export interface DesktopSetup {
  /** Fayl nomi, manifest yonida turadi. Masalan Venera-AI-Assistant-Setup-0.2.4.exe */
  file: string
  sha256: string
  size: number
  /** Faqat macOS: "universal" | "arm64" | "x86_64". */
  arch?: string
  /** Eng past OS versiyasi, masalan "11.0". */
  min_os?: string
}

/** Manifest tanigan platformalar. */
export type PlatformKey = 'windows' | 'macos'

/** /download/version.json ning to'liq shakli.
 *
 *  `setup` va `platforms` ikkalasi ham bor: `setup` — tarqatilgan eski desktop
 *  mijozlar (0.2.3 va oldingilar) uchun majburiy meros, `platforms` esa yangi
 *  ko'p platformali blok. Sayt HAR DOIM `platforms` dan foydalanadi va faqat
 *  u yo'q bo'lsa `setup` ni Windows deb talqin qiladi.
 */
export interface DesktopRelease {
  version: string
  /** ISO sana, masalan "2026-09-04". */
  released?: string
  notes?: string
  setup?: DesktopSetup
  platforms?: Partial<Record<PlatformKey, DesktopSetup>>
}

/** nginx shu prefiks ostida release papkasini ko'rsatadi (deploy/nginx.container.conf). */
export const DOWNLOAD_BASE = '/download'

export const MANIFEST_URL = `${DOWNLOAD_BASE}/version.json`

/**
 * Berilgan platforma uchun fayl. Reliz bu platformani qamramasa `null`.
 *
 * Zaxira qoidasi FAQAT Windows uchun: eski formatdagi (`platforms` yo'q)
 * manifestda yagona `setup` — kelishuvga ko'ra Windows o'rnatuvchisi.
 *
 * Bu desktop mijozdagi `Manifest.asset_for()` dan ATAYLAB qattiqroq. U yerda
 * eski manifest hamma platformaga tegishli deb hisoblanadi, chunki tarqatilgan
 * eski mijozlarning yangilanishini buzmaslik kerak. Saytda esa bunday meros
 * yo'q, shuning uchun macOS foydalanuvchisiga hech qachon `.exe` taklif
 * qilinmaydi — u yerda bu shunchaki ishlamaydigan fayl bo'lardi.
 */
export function assetFor(release: DesktopRelease, platform: PlatformKey): DesktopSetup | null {
  const fromPlatforms = release.platforms?.[platform]
  if (fromPlatforms?.file) return fromPlatforms
  if (platform === 'windows' && release.setup?.file) return release.setup
  return null
}

/** O'rnatuvchi faylining to'liq URL'i. */
export function setupUrl(asset: DesktopSetup): string {
  return `${DOWNLOAD_BASE}/${asset.file}`
}

/**
 * Brauzerdan foydalanuvchi OS'ini taxmin qiladi — qaysi kartani birinchi
 * ko'rsatishni hal qilish uchun.
 *
 * `navigator.platform` eskirgan, lekin `userAgentData` hali Safari va
 * Firefox'da yo'q; ikkalasini ham sinaymiz va aniqlanmasa `null` qaytaramiz.
 * Bu FAQAT tartibga ta'sir qiladi — ikkala karta ham doim ko'rinadi, shuning
 * uchun noto'g'ri taxmin hech kimni yuklab olishdan to'smaydi.
 */
export function detectPlatform(): PlatformKey | null {
  if (typeof navigator === 'undefined') return null
  const uaData = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData
  const hint = `${uaData?.platform ?? ''} ${navigator.platform ?? ''} ${navigator.userAgent ?? ''}`
    .toLowerCase()
  // iPhone/iPad'ni macOS deb ko'rsatmaslik kerak — u yerda .dmg ishlamaydi.
  if (/iphone|ipad|ipod|android/.test(hint)) return null
  if (/mac/.test(hint)) return 'macos'
  if (/win/.test(hint)) return 'windows'
  return null
}

/** Baytni odam o'qiydigan ko'rinishga o'giradi: 44996397 -> "42.9 MB". */
export function formatSize(bytes: number, locale = 'uz'): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return ''
  const mb = bytes / (1024 * 1024)
  if (mb >= 1024) {
    return `${(mb / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} GB`
  }
  return `${mb.toLocaleString(locale, { maximumFractionDigits: mb >= 100 ? 0 : 1 })} MB`
}

function isSetup(value: unknown): value is DesktopSetup {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return typeof v.file === 'string' && v.file.length > 0 && typeof v.size === 'number'
}

function isRelease(value: unknown): value is DesktopRelease {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  if (typeof v.version !== 'string') return false
  // `setup` YOKI hech bo'lmasa bitta platforma bo'lishi kifoya — desktop
  // mijozdagi Manifest.parse() bilan bir xil shart.
  if (isSetup(v.setup)) return true
  const platforms = v.platforms
  if (typeof platforms !== 'object' || platforms === null) return false
  return Object.values(platforms as Record<string, unknown>).some(isSetup)
}

/**
 * Joriy desktop relizini o'qiydi.
 *
 * `cache: 'no-store'` — manifest kichkina, lekin u yangi versiya chiqqanini
 * bildiradigan yagona signal. Keshdan eski versiya ko'rsatilsa, foydalanuvchi
 * mavjud bo'lmagan faylga havola bosadi.
 *
 * Xatolikda `null` qaytaradi (throw qilmaydi): yuklab olish bloki sahifaning
 * ikkinchi darajali qismi, u ishlamasa ham splash ochilaverishi kerak.
 */
export async function fetchDesktopRelease(signal?: AbortSignal): Promise<DesktopRelease | null> {
  try {
    const response = await fetch(MANIFEST_URL, {
      signal,
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) return null
    const data: unknown = await response.json()
    return isRelease(data) ? data : null
  } catch {
    // Tarmoq yo'q, JSON buzuq yoki so'rov bekor qilindi — barchasi "mavjud emas".
    return null
  }
}
