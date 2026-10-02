// "Pro" natijasi -> javob ostidagi belgi (chat) va savol izidagi qadam izohi (admin).
//
// BITTA joyda, chunki ikkalasi bir xil gapni aytishi shart: admin izida "kerak
// bo'lmadi", chatda esa "ishlatildi" ko'rinsa - odam byudjeti nimaga ketganini
// tushunmay qoladi. Holatlar ATAYLAB farqlanadi: byudjet FAQAT `used` da yeyiladi.
//
// Kirish - `done.pro` bloki (chat) yoki jurnaldagi `pro` hodisasining payload'i
// (admin), shuning uchun maydonlar `unknown` deb tekshiriladi.

type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string

export interface ProBadge {
  /** used - byudjet yeyildi; idle - kerak bo'lmadi; denied - berilmadi (sababi bilan). */
  state: 'used' | 'idle' | 'denied'
  /** Ko'rinib turadigan qisqa yozuv: "ishlatildi (1 ta murojaat)". */
  text: string
  /** To'liq gap (tooltip, admin izi). */
  detail: string
  tone: 'neutral' | 'warn'
}

const WHY: Record<string, [short: string, long: string]> = {
  limit: ['pro.whyLimit', 'pro.reasonLimit'],
  'no user': ['pro.whyNoUser', 'pro.reasonNoUser'],
  engine: ['pro.whyEngine', 'pro.reasonEngine'],
}

export function proBadge(raw: unknown, t: Translate): ProBadge | null {
  if (!raw || typeof raw !== 'object') return null
  const p = raw as Record<string, unknown>
  if (p.used === true) {
    const calls = typeof p.calls === 'number' && p.calls > 0 ? p.calls : null
    return {
      state: 'used',
      text: calls ? t('pro.badgeUsed', { n: calls }, calls) : t('pro.badgeUsedPlain'),
      detail: t('pro.used'),
      tone: 'neutral',
    }
  }
  if (typeof p.reason === 'string' && p.reason) {
    const keys = WHY[p.reason]
    // Notanish sabab - o'zicha (yangi sababni yashirgandan ko'ra xom ko'rsatgan yaxshi).
    const short = keys ? t(keys[0]) : p.reason
    const long = keys ? t(keys[1]) : p.reason
    return { state: 'denied', text: t('pro.badgeDenied', { why: short }), detail: t('pro.denied', { why: long }), tone: 'warn' }
  }
  // `requested: false` bilan blok kelmaydi; kelsa ham - "pro" so'ralmagan, belgi yo'q.
  if (p.requested === false) return null
  return { state: 'idle', text: t('pro.badgeNotNeeded'), detail: t('pro.notNeeded'), tone: 'neutral' }
}
