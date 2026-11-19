// Jonli suhbat (`/barno`) suhbatdoshlari. Ism va tavsif tarjimada (`live.persona.<id>.*`):
// o'zbek kirill va rus tilida ism ham o'z yozuvida ("Барно").
//
// `voice` - TTS ovoz profili (`apps/api/app/services/tts.py`, `VOICES`): integratsiya qachon
// ulansa, shu nom serverga uzatiladi. `tone` - ovoz sharining rangi (`LiveOrb.vue`):
// `brand` - Barno brendining iliq to'q sarig'i, `cool` - ko'k (grafik palitrasidagi `--viz-1`).

export type PersonaId = 'barno' | 'sardor'
export type OrbTone = 'brand' | 'cool'
/** Ovoz sharining holati (`LiveOrb.vue`). */
export type OrbMode = 'idle' | 'ringing' | 'listening' | 'thinking' | 'speaking' | 'muted'

export interface LivePersona {
  id: PersonaId
  voice: string
  tone: OrbTone
}

export const PERSONAS: readonly LivePersona[] = [
  { id: 'barno', voice: 'uz_female_calm', tone: 'brand' },
  { id: 'sardor', voice: 'uz_male_news', tone: 'cool' },
]

export function personaById(id: unknown): LivePersona | undefined {
  return PERSONAS.find((p) => p.id === id)
}
