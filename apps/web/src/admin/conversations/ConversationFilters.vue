<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Flag } from 'lucide-vue-next'
import VFilterBar from '../../ui/VFilterBar.vue'
import VFilterChip from '../../ui/VFilterChip.vue'
import type { FilterOption } from '../../ui/VFilterChip.vue'
import VSearchField from '../../ui/VSearchField.vue'
import VSegmented from '../../ui/VSegmented.vue'
import type { SegmentedOption } from '../../ui/VSegmented.vue'
import { fmtMs } from '../../ui/format'
import { searchAdmin } from '../api'
import { CHANNELS, ENGINES, ROUTES, TURN_STATUSES } from '../types'
import type { Channel, Engine, TurnStatus } from '../types'
import { chatTitle, personName, rememberPerson } from './people'
import type { Person } from './people'
import { useConversationFilters } from './useConversationFilters'
import type { ConversationView } from './useConversationFilters'

/**
 * Suhbatlar filtri (spec §4.5.2): qidiruv, foydalanuvchi, kanal, yo'nalish, dvigatel
 * (v1/v2), holat, "faqat xabar berilganlar", minimal javob vaqti va (suhbatdan kelganda)
 * suhbat.
 * O'ng chetda "Savollar | Suhbatlar" ko'rinishi. Hamma qiymat URL'da.
 *
 * Props:
 * - `people` - joriy qatorlardagi odamlar: "Foydalanuvchi" ro'yxati ochilganda qidiruvsiz
 *              shular chiqadi (odatda aynan shu odamlar kerak bo'ladi).
 */
const props = defineProps<{ people: Person[] }>()

const { t, te, locale } = useI18n({ useScope: 'global' })
const filters = useConversationFilters()
const s = computed(() => filters.state.value)

/* ---- qidiruv ---- */
const text = ref(s.value.q)
// Tashqaridan o'zgarsa ("Hammasini tozalash", orqaga tugmasi) - maydon ham ergashsin.
watch(
  () => s.value.q,
  (q) => {
    if (q.trim() !== text.value.trim()) text.value = q
  },
)

/* ---- foydalanuvchi: qidiruvsiz - qatorlardagilar, yozilsa - server ---- */
const remote = shallowRef<Person[] | null>(null)
const searching = ref(false)
let ctrl: AbortController | null = null

async function onUserSearch(q: string) {
  ctrl?.abort()
  ctrl = null
  if (!q) {
    remote.value = null
    searching.value = false
    return
  }
  const own = new AbortController()
  ctrl = own
  searching.value = true
  try {
    const res = await searchAdmin(q, own.signal)
    if (ctrl !== own) return
    remote.value = res.users.map((u) => {
      rememberPerson(u.actorId, u.name, u.login ?? u.email)
      return { actorId: u.actorId, name: u.name, login: u.login ?? u.email }
    })
  } catch {
    if (ctrl === own) remote.value = []
  } finally {
    if (ctrl === own) {
      searching.value = false
      ctrl = null
    }
  }
}
onBeforeUnmount(() => ctrl?.abort())

const actorOptions = computed<FilterOption<number>[]>(() => {
  const opts = (remote.value ?? props.people).slice(0, 8).map((p) => ({ value: p.actorId, label: p.name }))
  const sel = s.value.actor
  if (sel && !opts.some((o) => o.value === sel)) opts.unshift({ value: sel, label: personName(sel) ?? `#${sel}` })
  return opts
})

/* ---- ro'yxatli chip'lar ---- */
const channelOptions = computed<FilterOption<Channel>[]>(() =>
  CHANNELS.map((c) => ({ value: c, label: t(`admin.channel.${c}`), dot: `var(--ch-${c})` })),
)

const routeOptions = computed<FilterOption<string>[]>(() => {
  const list: string[] = [...ROUTES, 'none']
  const cur = s.value.route
  if (cur && !list.includes(cur)) list.push(cur)
  return list.map((r) => ({ value: r, label: te(`admin.route.${r}`) ? t(`admin.route.${r}`) : r }))
})

// Dvigatel: v1 (barqaror) / v2 (yangi) - ikkalasini solishtirish uchun. Yorliq boshida
// qiymatning o'zi ("v2 · yangi"): admin uni yordamchi jamoasining hujjatidan va savol
// izidan shu nom bilan biladi.
const engineOptions = computed<FilterOption<Engine>[]>(() =>
  ENGINES.map((v) => ({ value: v, label: `${v} · ${t(`admin.engine.${v}`)}` })),
)

const statusOptions = computed<FilterOption<TurnStatus>[]>(() =>
  TURN_STATUSES.map((v) => ({ value: v, label: t(`admin.status.${v}`) })),
)

const LATENCY_STEPS = [1000, 3000, 5000, 10_000, 30_000]
const latencyOptions = computed<FilterOption<number>[]>(() => {
  const steps = [...LATENCY_STEPS]
  const cur = s.value.minMs
  if (cur && !steps.includes(cur)) steps.push(cur)
  return steps
    .sort((a, b) => a - b)
    .map((ms) => ({ value: ms, label: t('admin.filter.slowerThan', { value: fmtMs(ms, locale.value) }) }))
})
const latencyValue = (_: FilterOption<number>[], values: number[]) => `≥ ${fmtMs(values[0], locale.value)}`

const chatOptions = computed<FilterOption<string>[]>(() => {
  const id = s.value.chat
  return id ? [{ value: id, label: chatTitle(id) ?? `…${id.slice(-6)}` }] : []
})

/* ---- ko'rinish ---- */
const viewOptions = computed<SegmentedOption<ConversationView>[]>(() => [
  { value: 'turns', label: t('admin.conversations.viewTurns') },
  { value: 'chats', label: t('admin.conversations.viewChats') },
])

const pick = <T,>(v: T | T[] | null): T | null => (Array.isArray(v) ? (v[0] ?? null) : v)
</script>

<template>
  <VFilterBar :active="!!s.q.trim()" @clear="filters.set({ q: '' })">
    <template #search>
      <VSearchField
        v-model="text"
        :placeholder="t('admin.conversations.searchPlaceholder')"
        shortcut="/"
        @search="(q) => filters.set({ q })"
      />
    </template>

    <VFilterChip
      v-if="s.chat"
      :label="t('admin.col.chat')"
      :options="chatOptions"
      :model-value="s.chat"
      @update:model-value="(v) => filters.set({ chat: pick(v) })"
    />
    <VFilterChip
      :label="t('admin.filter.user')"
      :options="actorOptions"
      :model-value="s.actor"
      searchable
      remote
      :loading="searching"
      @search="onUserSearch"
      @update:model-value="(v) => filters.set({ actor: pick(v) })"
    />
    <VFilterChip
      :label="t('admin.filter.channel')"
      :options="channelOptions"
      :model-value="s.channel === 'all' ? null : s.channel"
      @update:model-value="(v) => filters.set({ channel: pick(v) ?? 'all' })"
    />
    <VFilterChip
      :label="t('admin.filter.route')"
      :options="routeOptions"
      :model-value="s.route"
      @update:model-value="(v) => filters.set({ route: pick(v) })"
    />
    <VFilterChip
      :label="t('admin.filter.engine')"
      :options="engineOptions"
      :model-value="s.engine"
      @update:model-value="(v) => filters.set({ engine: pick(v) })"
    />
    <VFilterChip
      :label="t('admin.filter.status')"
      :options="statusOptions"
      :model-value="s.status"
      @update:model-value="(v) => filters.set({ status: pick(v) })"
    />
    <VFilterChip
      :label="t('admin.filter.minLatency')"
      :options="latencyOptions"
      :model-value="s.minMs"
      :format-value="latencyValue"
      @update:model-value="(v) => filters.set({ minMs: pick(v) })"
    />
    <VFilterChip
      :label="t('admin.filter.reported')"
      :icon="Flag"
      toggle
      :model-value="s.reported"
      @update:model-value="(v) => filters.set({ reported: v === true })"
    />

    <template #end>
      <VSegmented
        :options="viewOptions"
        :model-value="s.view"
        size="sm"
        :aria-label="t('admin.page.conversations.title')"
        @update:model-value="(v) => filters.set({ view: v })"
      />
    </template>
  </VFilterBar>
</template>
