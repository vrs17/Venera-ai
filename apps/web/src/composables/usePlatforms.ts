// PLATFORMA KALITLARI holati ("Barno shu manbadan foydalansinmi") - web ulanishlar oynasi
// (PlatformList) va Mini App sozlamalari uchun bitta mantiq.
//
// KALIT OPTIMISTIK: bosilgan zahoti yangi holat ko'rinadi, server rad etsa - avvalgisiga
// qaytadi va chaqiruvchi xabar ko'rsatadi (`false`). Jimgina orqaga qaytsa odam bosgani
// "yutilib ketdi" deb o'ylaydi (useConnectors bilan bir xil qoida).
//
// Bir platforma uchun bir vaqtda bitta so'rov: javob kelguncha kalit band (`pending`).
// Aks holda tez-tez bosishda javoblar tartibsiz kelib, ekran va server farq qilib qolardi.
//
// Tartib - `PLATFORM_IDS` (HRM, CRM, DWH, ...): server tartibi o'zgarsa ham ro'yxat
// "sakramaydi". Notanish platforma - oxirida, server tartibida.

import { reactive, ref } from 'vue'
import { assistantErrorKind, listPlatforms, setPlatform } from '../api/assistant.api'
import type { AssistantErrorKind, Platform } from '../api/assistant.api'
import { PLATFORM_IDS } from '../components/chat/platforms'

export type PlatformsStatus = 'idle' | 'loading' | 'ready' | 'error'

function ordered(list: Platform[]): Platform[] {
  const rank = (id: string) => {
    const i = (PLATFORM_IDS as readonly string[]).indexOf(id)
    return i < 0 ? PLATFORM_IDS.length : i
  }
  return list
    .map((p, i) => ({ p, i }))
    .sort((a, b) => rank(a.p.id) - rank(b.p.id) || a.i - b.i)
    .map((x) => x.p)
}

export function usePlatforms() {
  const platforms = ref<Platform[]>([])
  const status = ref<PlatformsStatus>('idle')
  const error = ref<AssistantErrorKind | null>(null)
  const pending = reactive(new Set<string>())
  let generation = 0

  async function load(): Promise<void> {
    const gen = ++generation
    if (!platforms.value.length) status.value = 'loading'
    error.value = null
    try {
      const list = await listPlatforms()
      if (gen !== generation) return
      platforms.value = ordered(list)
      status.value = 'ready'
    } catch (err) {
      if (gen !== generation) return
      error.value = assistantErrorKind(err)
      // Avval yuklangan ro'yxat bo'lsa - u qoladi (eski holat bo'sh ekrandan yaxshi).
      status.value = platforms.value.length ? 'ready' : 'error'
    }
  }

  function patch(id: string, next: Partial<Platform>) {
    const i = platforms.value.findIndex((p) => p.id === id)
    if (i >= 0) platforms.value.splice(i, 1, { ...platforms.value[i], ...next })
  }

  /** Kalit. `true` - saqlandi; `false` - rad etildi va avvalgi holat qaytarildi. */
  async function toggle(id: string): Promise<boolean> {
    const p = platforms.value.find((x) => x.id === id)
    if (!p || !p.available || pending.has(id)) return false
    const before = { user_enabled: p.user_enabled, enabled: p.enabled }
    const wanted = !p.user_enabled
    patch(id, { user_enabled: wanted, enabled: wanted && p.available })
    pending.add(id)
    const gen = generation
    try {
      const saved = await setPlatform(id, wanted)
      if (saved && gen === generation) patch(id, saved)
      return true
    } catch {
      if (gen === generation) patch(id, before)
      return false
    } finally {
      pending.delete(id)
    }
  }

  function reset(): void {
    generation++
    platforms.value = []
    status.value = 'idle'
    error.value = null
    pending.clear()
  }

  return { platforms, status, error, pending, load, toggle, reset }
}
