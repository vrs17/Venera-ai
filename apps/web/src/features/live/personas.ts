// Jonli suhbat (`/barno`) suhbatdoshlari. Ism va tavsif tarjimada (`live.persona.<id>.*`): o'zbek kirill va
// rus tilida ism ham o'z yozuvida ("Барно").
//
// HOZIRCHA BITTA: Barno - Speko'dagi «Barno AI» agenti (ega qarori 2026-11-19: TTS da faqat Barno ovozi
// bor, erkak ovoz yo'q). `id` serverga yuboriladi va u yerda agentga bog'lanadi (`apps/api/app/api/v1/live.py`,
// `_agent_of`). Yangi suhbatdosh: shu ro'yxatga qator, serverda agent va `i18n/live.ts` da ism bilan tavsif.
// `tone` - ovoz sharining rangi (`LiveOrb.vue`): `brand` - Barno brendining iliq to'q sarig'i, `cool` - ko'k.

export type PersonaId = 'barno'
export type OrbTone = 'brand' | 'cool'
/** Ovoz sharining holati (`LiveOrb.vue`). */
export type OrbMode = 'idle' | 'ringing' | 'listening' | 'thinking' | 'speaking' | 'muted'

export interface LivePersona {
  id: PersonaId
  tone: OrbTone
}

export const PERSONAS: readonly LivePersona[] = [{ id: 'barno', tone: 'brand' }]
