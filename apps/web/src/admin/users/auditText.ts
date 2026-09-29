// Audit yozuvi -> "nima bo'ldi" (bir so'z) va tafsilot (bir qator).
// Foydalanuvchi varag'idagi "O'zgarishlar" ro'yxati uchun; "Tizim" sahifasidagi
// jurnal bilan bir xil o'qiladi (kalitlar `admin.auditAction.*`, `admin.user.role.*`).

import type { AuditEntry } from '../types'

type Translate = (key: string) => string
type Exists = (key: string) => boolean

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

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
    default:
      return ''
  }
}
