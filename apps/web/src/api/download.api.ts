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

/** version.json ichidagi `setup` bloki. */
export interface DesktopSetup {
  /** Fayl nomi, manifest yonida turadi. Masalan Venera-AI-Assistant-Setup-0.2.3.exe */
  file: string
  sha256: string
  size: number
}

/** /download/version.json ning to'liq shakli. */
export interface DesktopRelease {
  version: string
  /** ISO sana, masalan "2026-09-04". */
  released?: string
  notes?: string
  setup: DesktopSetup
}

/** nginx shu prefiks ostida release papkasini ko'rsatadi (deploy/nginx.container.conf). */
export const DOWNLOAD_BASE = '/download'

export const MANIFEST_URL = `${DOWNLOAD_BASE}/version.json`

/** Sozlash faylining to'liq URL'i. */
export function setupUrl(release: DesktopRelease): string {
  return `${DOWNLOAD_BASE}/${release.setup.file}`
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

function isRelease(value: unknown): value is DesktopRelease {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  const setup = v.setup as Record<string, unknown> | undefined
  return (
    typeof v.version === 'string' &&
    typeof setup === 'object' &&
    setup !== null &&
    typeof setup.file === 'string' &&
    typeof setup.size === 'number'
  )
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
