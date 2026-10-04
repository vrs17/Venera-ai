// Tashqi xizmat birliklari (spec §4.5.6): audio - daqiqa/soat, belgilar - ixcham son,
// hajm - KB/MB. Birlik belgilari SI - hamma tilda bir xil (fmtMs bilan bir uslubda),
// kasr ajratgichi va guruhlash esa tilga qarab.

import { fmtCompact, fmtMs, fmtNumber } from '../../ui/format'
import type { ApiUnits } from '../types'

const NBSP = ' '
const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** 1536 -> "1.5 KB", 184_000_000 -> "175 MB" (1024 asosida - disk hajmi shunday o'qiladi). */
export function fmtBytes(bytes: number | null | undefined, locale?: string | null): string {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes)) return '—'
  let v = Math.max(0, bytes)
  let i = 0
  while (v >= 1024 && i < BYTE_UNITS.length - 1) {
    v /= 1024
    i += 1
  }
  const digits = i === 0 ? 0 : v < 10 ? 1 : 0
  return `${fmtNumber(v, locale, { digits })}${NBSP}${BYTE_UNITS[i]}`
}

/** Audio soniyalar -> "45 s", "5 min 12 s", "3 h 20 min". */
export function fmtAudio(seconds: number | null | undefined, locale?: string | null): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '—'
  return fmtMs(seconds * 1000, locale)
}

export type UnitKey = keyof ApiUnits

/** Birlik qiymati o'z formatida. */
export function fmtUnit(key: string, value: number | null | undefined, locale?: string | null): string {
  if (key === 'audioSec') return fmtAudio(value, locale)
  if (key === 'bytes') return fmtBytes(value, locale)
  return fmtCompact(value, locale)
}

/** Faqat noldan katta birliklar, doimiy tartibda (audio, belgilar, hajm, kadrlar). */
export function unitEntries(units: ApiUnits | null | undefined): { key: UnitKey; value: number }[] {
  const order: UnitKey[] = ['audioSec', 'chars', 'bytes', 'frames']
  const out: { key: UnitKey; value: number }[] = []
  for (const key of order) {
    const v = units?.[key]
    if (typeof v === 'number' && Number.isFinite(v) && v > 0) out.push({ key, value: v })
  }
  return out
}
