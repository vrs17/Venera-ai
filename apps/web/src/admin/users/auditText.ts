// Audit yozuvi -> "nima bo'ldi" (bir so'z) va tafsilot (bir qator).
// Foydalanuvchi varag'idagi "O'zgarishlar" ro'yxati uchun; "Tizim" sahifasidagi
// jurnal bilan bir xil o'qiladi (kalitlar `admin.auditAction.*`, `admin.user.role.*`).

import type { AuditEntry } from '../types'

type Translate = (key: string) => string
type Exists = (key: string) => boolean

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
const rec = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null

/** Versiya ruxsati (`{engines, defaultEngine}` | null) -> "v1, v2 · v2" ("·" dan keyin
 *  standart; bitta versiyada u o'zi standart - takrorlanmaydi). Yo'q - "—". */
export function grantText(v: unknown): string {
  const g = rec(v)
  const list = strList(g?.engines)
  if (!list.length) return '—'
  const def = str(g?.defaultEngine)
  return def && list.length > 1 ? `${list.join(', ')} · ${def}` : list.join(', ')
}

/** Versiya siyosati o'zgarishi (`{default, channels}` dan -> ga): faqat o'zgargan
 *  kalitlar, "Hammaga: v1 → v2; Bot: — → v1". "—" - kalit yo'q (keyingi bo'g'inga meros). */
export function policyDiff(from: unknown, to: unknown, t: Translate, te: Exists): string {
  const a = rec(from) ?? {}
  const b = rec(to) ?? {}
  const show = (v: unknown) => str(v) ?? '—'
  const parts: string[] = []
  if (show(a.default) !== show(b.default)) {
    parts.push(`${t('admin.versions.everyone')}: ${show(a.default)} → ${show(b.default)}`)
  }
  const ca = rec(a.channels) ?? {}
  const cb = rec(b.channels) ?? {}
  for (const ch of [...new Set([...Object.keys(ca), ...Object.keys(cb)])]) {
    if (show(ca[ch]) === show(cb[ch])) continue
    const key = `admin.channel.${ch}`
    parts.push(`${te(key) ? t(key) : ch}: ${show(ca[ch])} → ${show(cb[ch])}`)
  }
  return parts.join('; ')
}

export function roleLabel(role: string, t: Translate, te: Exists): string {
  const key = `admin.user.role.${role}`
  return te(key) ? t(key) : role
}

export function auditLabel(action: string, t: Translate, te: Exists): string {
  const key = `admin.auditAction.${action}`
  return te(key) ? t(key) : action
}

/** "Foydalanuvchi → Admin", "HRM", izohning boshi. Bo'sh satr - tafsilot yo'q. */
export function auditDetail(e: AuditEntry, t: Translate, te: Exists): string {
  const d = e.detail ?? {}
  const roles = (v: unknown) => {
    const list = strList(v)
    return list.length ? list.map((r) => roleLabel(r, t, te)).join(', ') : '—'
  }
  switch (e.action) {
    case 'user.roles':
      return `${roles(d.from)} → ${roles(d.to)}`
    case 'user.connector.disconnect':
      return (str(d.platform) ?? '').toUpperCase()
    case 'user.note':
      return str(d.preview) ?? ''
    case 'engine.access.set':
      return `${grantText(d.from)} → ${grantText(d.to)}`
    case 'engine.access.remove':
      return grantText(d.from)
    case 'engine.policy':
      return policyDiff(d.from, d.to, t, te)
    default:
      return ''
  }
}
