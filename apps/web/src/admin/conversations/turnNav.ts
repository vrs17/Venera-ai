// Savol izida "oldingi / keyingi savol": ro'yxat sahifasi yuklagan qatorlar shu yerda
// (modul darajasida) qoladi. Iz sahifasi URL'dagi filtrlar ro'yxatnikiga aynan mos
// kelsagina tugmalarni ko'rsatadi - aks holda (boshqa sahifadan kelgan havola, yangilangan
// varaq) "keyingi" noma'lum ro'yxatdagi tasodifiy savol bo'lib qolardi.
//
// Ro'yxat oxirida `nextCursor` bo'lsa, "keyingi" keyingi sahifani o'zi yuklaydi.

import { computed, shallowRef } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { LocationQuery } from 'vue-router'
import { listTurns } from '../api'
import type { TurnQuery } from '../types'
import { listKey } from './useConversationFilters'

interface TurnNavList {
  key: string
  ids: string[]
  nextCursor: string | null
  params: TurnQuery
}

const list = shallowRef<TurnNavList | null>(null)

/** Ro'yxatdan oxirgi ochilgan savol - qaytganda qator belgilangan turadi. */
export const lastVisitedTurn = shallowRef<string | null>(null)

export function publishTurnList(query: LocationQuery, ids: string[], nextCursor: string | null, params: TurnQuery) {
  list.value = { key: listKey(query), ids, nextCursor, params }
}

export interface TurnNav {
  /** Yangiroq savol (ro'yxatda tepadagi). */
  prev: ComputedRef<string | null>
  /** Eskiroq savol; ro'yxat oxirida bo'lsa ham keyingi sahifa bor bo'lishi mumkin. */
  hasNext: ComputedRef<boolean>
  available: ComputedRef<boolean>
  /** Keyingi savolning id si (kerak bo'lsa keyingi sahifani yuklab). */
  resolveNext: () => Promise<string | null>
}

export function useTurnNav(id: Ref<string>, query: Ref<LocationQuery>): TurnNav {
  const current = computed(() => {
    const l = list.value
    if (!l || l.key !== listKey(query.value)) return null
    const index = l.ids.indexOf(id.value)
    return index < 0 ? null : { l, index }
  })

  let loading: Promise<string | null> | null = null

  async function resolveNext(): Promise<string | null> {
    const c = current.value
    if (!c) return null
    const next = c.l.ids[c.index + 1]
    if (next) return next
    if (!c.l.nextCursor) return null
    loading ??= listTurns({ ...c.l.params, cursor: c.l.nextCursor })
      .then((page) => {
        // Kutish paytida ro'yxat almashgan bo'lsa - eski natijani yozmaymiz.
        if (list.value !== c.l) return null
        const ids = [...c.l.ids, ...page.items.map((x) => x.id).filter((x) => !c.l.ids.includes(x))]
        list.value = { ...c.l, ids, nextCursor: page.nextCursor }
        return ids[c.index + 1] ?? null
      })
      .catch(() => null)
      .finally(() => {
        loading = null
      })
    return loading
  }

  return {
    available: computed(() => current.value !== null),
    prev: computed(() => (current.value && current.value.index > 0 ? current.value.l.ids[current.value.index - 1] : null)),
    hasNext: computed(() => {
      const c = current.value
      return !!c && (c.index < c.l.ids.length - 1 || !!c.l.nextCursor)
    }),
    resolveNext,
  }
}
