<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import { Users } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VDataTable from '../../ui/VDataTable.vue'
import type { DataTableColumn } from '../../ui/VDataTable.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VFilterBar from '../../ui/VFilterBar.vue'
import VFilterChip from '../../ui/VFilterChip.vue'
import type { FilterOption } from '../../ui/VFilterChip.vue'
import VSearchField from '../../ui/VSearchField.vue'
import { fmtNumber } from '../../ui/format'
import { useAuth } from '../../composables/useAuth'
import { listUsers } from '../api'
import { CHANNELS, KNOWN_ROLES } from '../types'
import type { AdminUser, AdminUserList, Channel, UserQuery } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import ChannelBadge from '../components/ChannelBadge.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'
import UserCell from '../components/UserCell.vue'
import { channelColor, channelIcon } from '../components/channel'
import { useAdminQuery } from '../components/useAdminQuery'
import UserSheet from '../users/UserSheet.vue'
import type { UserPatch } from '../users/UserSheet.vue'
import { roleLabel } from '../users/auditText'
import { useUserFilters } from '../users/useUserFilters'
import type { UserStatusFilter } from '../users/useUserFilters'

// "Foydalanuvchilar" (spec §4.5.5): filtrlar qatori + jadval; qator bosilsa o'ngdan
// foydalanuvchi varag'i ochiladi. `/admin/users/:id` ham SHU sahifa (marshrut
// bir xil komponentni beradi - ro'yxat qayta yuklanmaydi): havola ulashilsa varaq
// ro'yxat ustida ochiladi, yopilganda filtrlar saqlangan holda `/admin/users` ga qaytiladi.
//
// Sana global filtrdan (sarlavhada), kanal esa shu yerdagi chip'da - kalit bitta
// (`?channel=`), boshqa sahifalarga o'tganda ham saqlanadi. Bu sahifada kanal
// "shu kanaldan foydalanganlar" degani, shuning uchun u qolgan filtrlar yonida turadi.
const props = defineProps<{ id?: string }>()

const { t, te, locale } = useI18n({ useScope: 'global' })
const tr = (key: string) => t(key)
const has = (key: string) => te(key)
const router = useRouter()
const filters = useAdminFilters()
const uf = useUserFilters()
const { user: me } = useAuth()

/* ---------------------------------------------------------------- ro'yxat */

const q = useAdminQuery<AdminUserList, UserQuery>((params, signal) => listUsers(params, signal), {
  params: () => uf.apiParams(filters.params.value),
  fresh: () => uf.apiParams(filters.freshParams()),
})

const rows = computed<AdminUser[]>(() => q.data.value?.items ?? [])
const total = computed(() =>
  q.data.value ? t('admin.users.total', { n: fmtNumber(rows.value.length, locale.value) }) : '',
)

/* ---------------------------------------------------------------- filtrlar */

const search = ref(uf.state.value.q)
// Tashqaridan o'zgarsa ("Hammasini tozalash", "Orqaga") - maydon ham ergashsin.
watch(
  () => uf.state.value.q,
  (v) => {
    if (v.trim() !== search.value.trim()) search.value = v
  },
)

const roleOptions = computed<FilterOption<string>[]>(() =>
  KNOWN_ROLES.map((r) => ({ value: r, label: roleLabel(r, tr, has) })),
)
const statusOptions = computed<FilterOption<UserStatusFilter>[]>(() => [
  { value: 'active', label: t('admin.user.active') },
  { value: 'blocked', label: t('admin.user.blocked') },
])
const channelOptions = computed<FilterOption<Channel>[]>(() =>
  CHANNELS.map((c) => ({ value: c, label: t(`admin.channel.${c}`), icon: channelIcon(c), dot: `var(${channelColor(c)})` })),
)

function single<T>(v: T | T[] | null): T | null {
  return Array.isArray(v) ? (v[0] ?? null) : v
}

function clearAll() {
  search.value = ''
  uf.set({ q: '', role: null, status: null, channel: null })
}

/* ---------------------------------------------------------------- jadval */

const isSelf = (u: AdminUser) => me.value?.actorId === u.actorId
// VDataTable slot'lari qatorni `unknown` deb beradi.
const asUser = (r: unknown) => r as AdminUser

const ROLE_ORDER = KNOWN_ROLES as readonly string[]
function sortedRoles(roles: string[]): string[] {
  const rank = (r: string) => {
    const i = ROLE_ORDER.indexOf(r)
    return i < 0 ? ROLE_ORDER.length : i
  }
  return [...roles].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

function subLine(u: AdminUser): string | null {
  const login = u.login ?? u.email
  if (!isSelf(u)) return u.name?.trim() ? login : null
  return [t('admin.user.you'), login].filter(Boolean).join(' · ')
}

const columns = computed<DataTableColumn<AdminUser>[]>(() => [
  {
    key: 'user',
    label: t('admin.col.user'),
    sortable: true,
    sortValue: (r) => (r.name || r.login || '').toLocaleLowerCase(),
  },
  // Odam ustuni eng muhimi - qolganlari tor va qat'iy, planshetda ham ism sig'sin.
  { key: 'roles', label: t('admin.col.roles'), width: '20%' },
  { key: 'channels', label: t('admin.col.channels'), width: 112 },
  { key: 'turns', label: t('admin.col.turns'), width: 104, align: 'end', sortable: true, value: (r) => r.turns },
  {
    key: 'lastSeenAt',
    label: t('admin.col.lastSeen'),
    width: 140,
    sortable: true,
    sortValue: (r) => (r.lastSeenAt ? Date.parse(r.lastSeenAt) : null),
  },
  { key: 'status', label: t('admin.col.status'), width: 144 },
])

/* ---------------------------------------------------------------- varaq */

const LIST_PATH = '/admin/users'

const sheetOpen = computed(() => props.id !== undefined)
const routeId = computed<number | null>(() => {
  const raw = props.id
  if (raw === undefined || !/^\d{1,15}$/.test(raw)) return null
  const n = Number(raw)
  return Number.isSafeInteger(n) ? n : null
})
// Yopilish animatsiyasi paytida varaq bo'sh qolmasin - oxirgi odam saqlanadi.
const lastId = ref<number | null>(routeId.value)
watch(routeId, (id) => {
  if (id !== null) lastId.value = id
})
const sheetId = computed(() => (sheetOpen.value ? routeId.value : lastId.value))
const sheetRow = computed(() => rows.value.find((u) => u.actorId === sheetId.value) ?? null)
const selectedKey = computed(() => (sheetOpen.value ? routeId.value : null))

// Qatorni ochish - `push`: brauzerning "Orqaga" tugmasi varaqni yopadi. Filtrlar
// URL'da qoladi, yopilganda ro'yxat aynan shu holatga qaytadi.
function rowTo(u: AdminUser): RouteLocationRaw {
  return { path: `${LIST_PATH}/${u.actorId}`, query: uf.query.value }
}

function closeSheet() {
  // Ro'yxatdan ochilgan bo'lsa - tarixda bir qadam orqaga (keyin "Orqaga" varaqni
  // qayta ochmasin). To'g'ridan-to'g'ri havola bilan kelgan bo'lsa - ro'yxatga almashtiramiz.
  const back = (window.history.state as { back?: unknown } | null)?.back
  if (typeof back === 'string' && router.resolve(back).path === LIST_PATH) router.back()
  else void router.replace({ path: LIST_PATH, query: uf.query.value })
}

function applyPatch(id: number, patch: UserPatch) {
  q.mutate((list) => ({ ...list, items: list.items.map((u) => (u.actorId === id ? { ...u, ...patch } : u)) }))
}

function onChanged() {
  // Rol yoki holat o'zgargach qator filtrga endi mos kelmasligi mumkin - jimgina qayta so'raymiz.
  void q.refresh()
}
</script>

<template>
  <section class="up" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.users.title')"
      :subtitle="t('admin.page.users.subtitle')"
      filters
      :channel="false"
      :refreshing="q.refetching.value"
      @refresh="q.refresh"
    />

    <div class="up-body">
      <VFilterBar :active="!!uf.state.value.q.trim()" @clear="clearAll">
        <template #search>
          <VSearchField
            v-model="search"
            :placeholder="t('admin.users.search')"
            :aria-label="t('admin.nav.search')"
            shortcut="/"
            @search="(v: string) => uf.set({ q: v })"
          />
        </template>
        <VFilterChip
          :label="t('admin.filter.role')"
          :options="roleOptions"
          :model-value="uf.state.value.role"
          @update:model-value="(v: string | string[] | null) => uf.set({ role: single(v) })"
        />
        <VFilterChip
          :label="t('admin.filter.status')"
          :options="statusOptions"
          :model-value="uf.state.value.status"
          @update:model-value="(v: UserStatusFilter | UserStatusFilter[] | null) => uf.set({ status: single(v) })"
        />
        <VFilterChip
          :label="t('admin.filter.channel')"
          :options="channelOptions"
          :model-value="uf.state.value.channel"
          @update:model-value="(v: Channel | Channel[] | null) => uf.set({ channel: single(v) })"
        />
        <template v-if="total" #end>
          <span aria-live="polite">{{ total }}</span>
        </template>
      </VFilterBar>

      <AdminError
        v-if="q.error.value && !q.data.value"
        :message="q.errorText.value"
        :busy="q.loading.value"
        @retry="q.refresh"
      />

      <template v-else>
        <AdminError v-if="q.error.value" inline :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

        <div class="up-table">
          <VDataTable
            :rows="rows"
            :columns="columns"
            :row-key="(r: AdminUser) => r.actorId"
            :loading="q.loading.value"
            :selected-key="selectedKey"
            :row-to="rowTo"
            :label="t('admin.page.users.title')"
            :skeleton-rows="8"
          >
            <template #cell-user="{ row }">
              <UserCell :name="asUser(row).name" :login="asUser(row).login ?? asUser(row).email" :sub="subLine(asUser(row))" />
            </template>

            <template #cell-roles="{ row }">
              <span v-if="asUser(row).roles.length" class="up-roles">
                <VBadge v-for="r in sortedRoles(asUser(row).roles)" :key="r" size="sm">{{ roleLabel(r, tr, has) }}</VBadge>
              </span>
              <span v-else class="up-none">—</span>
            </template>

            <template #cell-channels="{ row }">
              <span v-if="asUser(row).channels.length" class="up-channels">
                <ChannelBadge v-for="c in asUser(row).channels" :key="c" :channel="c" icon-only />
              </span>
              <span v-else class="up-none">—</span>
            </template>

            <template #cell-turns="{ row }">
              <span :class="{ 'up-zero': !asUser(row).turns }">{{ fmtNumber(asUser(row).turns, locale) }}</span>
            </template>

            <template #cell-lastSeenAt="{ row }">
              <span class="up-seen"><RelTime :value="asUser(row).lastSeenAt" /></span>
            </template>

            <template #cell-status="{ row }">
              <StatusDot v-if="asUser(row).disabled" status="blocked" tone="crit" :label="t('admin.user.blocked')" />
              <StatusDot
                v-else-if="asUser(row).source === 'telemetry'"
                status="telemetry"
                tone="neutral"
                :label="t('admin.user.source.telemetry')"
              />
              <StatusDot v-else status="active" tone="good" :label="t('admin.user.active')" />
            </template>

            <template #empty>
              <VEmpty
                compact
                :icon="Users"
                :title="uf.hasFilters.value ? t('admin.empty.filtered') : t('admin.empty.users')"
              >
                <VButton v-if="uf.hasFilters.value" size="sm" @click="clearAll">{{ t('ui.clearAll') }}</VButton>
              </VEmpty>
            </template>
          </VDataTable>
        </div>
      </template>
    </div>

    <UserSheet
      :open="sheetOpen"
      :actor-id="sheetId"
      :row="sheetRow"
      @close="closeSheet"
      @patch="applyPatch"
      @changed="onChanged"
    />
  </section>
</template>

<style scoped>
.up {
  display: flex;
  flex-direction: column;
  gap: var(--s-10);
  min-width: 0;
}
.up-body {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}

/* Jadval kartada: `overflow: clip` burchaklarni kesadi, lekin aylantirish konteyneri
   yaratmaydi - yopishqoq sarlavha sahifa bilan birga ishlashda davom etadi. */
.up-table {
  overflow: clip;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}

.up-roles,
.up-channels {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  max-width: 100%;
  vertical-align: middle;
}
.up-channels {
  gap: var(--s-3);
}
.up-none {
  color: var(--text-4);
}
.up-zero {
  color: var(--text-3);
}
.up-seen {
  color: var(--text-2);
}
</style>
