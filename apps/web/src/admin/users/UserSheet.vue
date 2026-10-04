<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { CalendarDays, CircleAlert, Lock, LogOut, Pencil, RotateCcw, Trash2, Unlink, Unplug, UserX } from 'lucide-vue-next'
import VAvatar from '../../ui/VAvatar.vue'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VChoiceChips from '../../ui/VChoiceChips.vue'
import type { ChoiceOption } from '../../ui/VChoiceChips.vue'
import VDialog from '../../ui/VDialog.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSheet from '../../ui/VSheet.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VSpinner from '../../ui/VSpinner.vue'
import VSwitch from '../../ui/VSwitch.vue'
import VTextarea from '../../ui/VTextarea.vue'
import VTooltip from '../../ui/VTooltip.vue'
import { useId } from '../../ui/composables/useId'
import { fmtDate, fmtMs, fmtNumber, fromISODate } from '../../ui/format'
import { useCommandPalette } from '../../ui/useCommandPalette'
import { useToast } from '../../ui/useToast'
import { useAuth } from '../../composables/useAuth'
import { useChats } from '../../composables/useChats'
import { deleteEngineAccess, disconnectUserConnector, getUser, signOutUser, unlinkUserTelegram, updateUser } from '../api'
import { ENGINE_CHANNELS, ENGINES, KNOWN_ROLES } from '../types'
import type { AdminConnector, AdminUser, AdminUserDetail, EngineAccessRow, RangeParams } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'
import type { StatusTone } from '../components/StatusDot.vue'
import { useAdminQuery } from '../components/useAdminQuery'
import EngineAccessDialog from '../versions/EngineAccessDialog.vue'
import { engineLabel } from '../versions/engineText'
import UserAudit from './UserAudit.vue'
import UserRecent from './UserRecent.vue'
import { roleLabel } from './auditText'
import { userActionError } from './userErrors'

/** Ro'yxat qatoriga qaytariladigan o'zgarishlar (PATCH javobidan). Statistika EMAS:
 *  server uni standart oraliq bo'yicha qaytaradi, ro'yxat esa tanlangan oraliqda. */
export type UserPatch = Pick<AdminUser, 'roles' | 'rolesSource' | 'rolesLocked' | 'disabled'>

/**
 * Foydalanuvchi varag'i (spec §4.5.5): o'ngdan 560px panel, telefonda pastki sheet.
 * Sarlavha, davr statistikasi va bo'limlar: Rollar, Kirish, Versiya, Ulanishlar, Telegram,
 * So'nggi faollik, Izoh, O'zgarishlar. Har bir o'zgarish - toast va audit yozuvi
 * (audit server yozadi; varaq keyin jimgina yangilanadi va yozuv ro'yxatda chiqadi).
 *
 * Props:
 * - `open`    - marshrut `/admin/users/:id` da.
 * - `actorId` - ko'rsatilayotgan odam; yopilish animatsiyasi paytida ham saqlanadi.
 *               `null` - URL'dagi id yaroqsiz ("Topilmadi").
 * - `row`     - ro'yxatdagi qator: tafsilot kelguncha sarlavha, rollar va kirish
 *               bo'limi shundan darhol chiziladi (bo'sh skelet o'rniga).
 *
 * Hodisalar: `close`, `patch(actorId, patch)` - ro'yxat qatorini yangilash,
 * `changed` - ro'yxatni qayta so'rash (filtrga endi mos kelmasligi mumkin).
 */
const props = defineProps<{
  open: boolean
  actorId: number | null
  row?: AdminUser | null
}>()

const emit = defineEmits<{
  close: []
  patch: [actorId: number, patch: UserPatch]
  changed: []
}>()

const { t, te, locale } = useI18n({ useScope: 'global' })
const tr = (key: string) => t(key)
const has = (key: string) => te(key)
const toast = useToast()
const route = useRoute()
const router = useRouter()
const { user: me, logout } = useAuth()
const palette = useCommandPalette()
const filters = useAdminFilters()
const uid = useId('us')

const num = (n: number) => fmtNumber(n, locale.value)

/* ---------------------------------------------------------------- ma'lumot */

interface DetailParams {
  id: number
  from?: string
  to?: string
}

const rangeOf = (r: RangeParams) => ({ from: r.from, to: r.to })

// Varaq statistikasi global oraliq bo'yicha (kanal - yo'q: odamning hamma kanallari).
const q = useAdminQuery<AdminUserDetail, DetailParams>(
  (p, signal) => getUser(p.id, { from: p.from, to: p.to }, signal),
  {
    params: () => ({ id: props.actorId ?? 0, ...rangeOf(filters.params.value) }),
    enabled: () => props.open && props.actorId !== null,
    fresh: () => ({ id: props.actorId ?? 0, ...rangeOf(filters.freshParams()) }),
  },
)

// Oldingi odamning javobi keyingisining varag'ida bir lahza ham ko'rinmasin.
const detail = computed<AdminUserDetail | null>(() => {
  const d = q.data.value
  return d && d.actorId === props.actorId ? d : null
})
const base = computed<AdminUser | null>(
  () => detail.value ?? (props.row && props.row.actorId === props.actorId ? props.row : null),
)
// Yangi odam yuklanayotganda eski xato ko'rinmasin - faqat so'rov tugagach.
const failed = computed(() => !detail.value && !q.loading.value && !!q.error.value)
const notFound = computed(() => props.actorId === null || (failed.value && q.errorStatus.value === 404))

const isSelf = computed(() => props.actorId !== null && me.value?.actorId === props.actorId)

function refreshDetail() {
  if (props.open && props.actorId !== null) void q.refresh()
}

/* ---------------------------------------------------------------- sarlavha */

const name = computed(() => base.value?.name?.trim() || base.value?.login || t('admin.common.unknownUser'))
const loginLine = computed(() => {
  const b = base.value
  if (!b) return ''
  const email = b.email && b.email !== b.login ? b.email : null
  return [b.login, email].filter(Boolean).join(' · ')
})
const orgLine = computed(() =>
  [base.value?.department, base.value?.position].filter((s): s is string => !!s?.trim()).join(' · '),
)
const sourceLabel = computed(() => {
  const s = base.value?.source
  if (!s) return ''
  const key = `admin.user.source.${s}`
  return te(key) ? t(key) : s
})

/* ---------------------------------------------------------------- statistika */

// Davr sanalari alohida bo'laklar: tire atrofidagi oraliq shriftga bog'liq bo'lmasin.
const period = computed<string[]>(() => {
  const a = fromISODate(filters.from.value)
  const b = fromISODate(filters.to.value)
  if (!a || !b) return []
  const from = fmtDate(a, locale.value)
  const to = fmtDate(b, locale.value)
  return from === to ? [from] : [from, '–', to]
})

const stats = computed(() => {
  const s = detail.value?.stats
  return [
    { key: 'turns', label: t('admin.user.turns'), value: s ? num(s.turns) : null },
    { key: 'errors', label: t('admin.user.errors'), value: s ? num(s.errors) : null },
    { key: 'ttft', label: t('admin.user.medianTtft'), value: s ? fmtMs(s.medianTtftMs, locale.value) : null },
    { key: 'reports', label: t('admin.user.reports'), value: s ? num(s.reports) : null },
    { key: 'voice', label: t('admin.user.voiceTurns'), value: s ? num(s.voiceTurns) : null },
  ]
})

/* ---------------------------------------------------------------- tasdiqlash oynasi */

interface ConfirmSpec {
  title: string
  body: string
  action: string
  danger: boolean
  run: () => Promise<void>
  /** Amaldan keyin sahifadan chiqiladi (o'zini hamma joydan chiqarish) - yangilash kerak emas. */
  leaves?: boolean
}

const confirm = shallowRef<ConfirmSpec | null>(null)
const confirmOpen = ref(false)
const confirmBusy = ref(false)
const confirmError = ref<string | null>(null)

function askConfirm(spec: ConfirmSpec) {
  confirm.value = spec
  confirmError.value = null
  confirmOpen.value = true
}

async function runConfirm() {
  const spec = confirm.value
  if (!spec || confirmBusy.value) return
  confirmBusy.value = true
  confirmError.value = null
  try {
    await spec.run()
    confirmOpen.value = false
    if (!spec.leaves) {
      emit('changed')
      refreshDetail()
    }
  } catch (err) {
    // Oyna ochiq qoladi: sabab shu yerda, "Bekor qilish" yoki qayta urinish qo'l ostida.
    confirmError.value = userActionError(err, tr)
  } finally {
    confirmBusy.value = false
  }
}

function done(key: string, id?: string) {
  toast.show({ message: t(key), tone: 'good', id })
}

/** PATCH javobi -> varaq va ro'yxat qatori (faqat rol/holat maydonlari). */
function applyUser(id: number, res: AdminUser) {
  const patch: UserPatch = {
    roles: res.roles,
    rolesSource: res.rolesSource,
    rolesLocked: res.rolesLocked,
    disabled: res.disabled,
  }
  q.mutate((d) => (d.actorId === id ? { ...d, ...patch } : d))
  emit('patch', id, patch)
}

/* ---------------------------------------------------------------- rollar */

const rolesDraft = ref<string[] | null>(null)
const rolesError = ref<string | null>(null)
const rolesSavingId = ref<number | null>(null)
const resetting = ref(false)
// Manbadan kelgan noma'lum rollar (masalan, SSO dagi "HR"): olib tashlangach ham chip
// qolsin - aks holda noto'g'ri bosilgan rolni qaytarib bo'lmasdi.
const extraRoles = ref<string[]>([])

const shownRoles = computed(() => rolesDraft.value ?? base.value?.roles ?? [])
const rolesSaving = computed(() => props.actorId !== null && rolesSavingId.value === props.actorId)

watch(
  shownRoles,
  (list) => {
    const known = KNOWN_ROLES as readonly string[]
    const extra = list.filter((r) => !known.includes(r) && !extraRoles.value.includes(r))
    if (extra.length) extraRoles.value = [...extraRoles.value, ...extra]
  },
  { immediate: true },
)

/** ADMIN chip'i nega qulf: server sozlamasi (`admin_logins`) yoki o'zingiz. */
const adminLock = computed<{ reason: string; label: string | null } | null>(() => {
  if (base.value?.rolesLocked) return { reason: t('admin.users.lockedHint'), label: t('admin.user.rolesLocked') }
  if (isSelf.value) return { reason: t('admin.error.selfAdmin'), label: null }
  return null
})

const roleOptions = computed<ChoiceOption<string>[]>(() =>
  [...KNOWN_ROLES, ...extraRoles.value].map((r) => ({
    value: r,
    label: roleLabel(r, tr, has),
    disabled: r === 'ADMIN' && !!adminLock.value && shownRoles.value.includes('ADMIN'),
  })),
)

const rolesSourceText = computed(() => {
  const b = base.value
  if (!b) return ''
  if (b.rolesSource === 'admin') return t('admin.user.rolesSource.admin')
  return [t('admin.user.rolesSource.source'), sourceLabel.value].filter(Boolean).join(' · ')
})

// Ketma-ket bosishlar navbatda: bir vaqtda bitta PATCH, oxirgi holat albatta yuboriladi,
// xato bo'lsa - server tasdiqlagan rollarga qaytiladi.
let activeSave: { id: number; queued: boolean } | null = null

async function saveRoles(id: number, next: string[]) {
  rolesDraft.value = next
  if (activeSave?.id === id) {
    activeSave.queued = true
    return
  }
  const job = { id, queued: false }
  activeSave = job
  rolesSavingId.value = id
  let body = next
  try {
    for (;;) {
      job.queued = false
      const res = await updateUser(id, { roles: body })
      applyUser(id, res)
      const draft = props.actorId === id ? rolesDraft.value : null
      if (!job.queued || !draft) break
      body = draft
    }
    if (props.actorId === id) rolesDraft.value = null
    done('admin.toast.rolesSaved', 'admin-user-roles')
    emit('changed')
    if (props.actorId === id) refreshDetail()
  } catch (err) {
    if (props.actorId === id) {
      rolesDraft.value = null
      rolesError.value = userActionError(err, tr)
    }
  } finally {
    if (activeSave === job) {
      activeSave = null
      rolesSavingId.value = null
    }
  }
}

function onRolesChange(value: string | string[] | null) {
  const id = props.actorId
  if (id === null || !base.value) return
  const next = Array.isArray(value) ? value : value ? [value] : []
  rolesError.value = null
  const removingAdmin = shownRoles.value.includes('ADMIN') && !next.includes('ADMIN')
  if (removingAdmin && adminLock.value) {
    rolesError.value = adminLock.value.reason
    return
  }
  if (removingAdmin) {
    // Admin panel unga darhol yopiladi - bitta noto'g'ri bosish uchun juda qimmat.
    askConfirm({
      title: t('admin.confirm.removeAdminTitle', { name: name.value }),
      body: t('admin.confirm.removeAdminBody'),
      action: t('admin.users.remove'),
      danger: true,
      run: async () => {
        const res = await updateUser(id, { roles: next })
        applyUser(id, res)
        done('admin.toast.rolesSaved', 'admin-user-roles')
      },
    })
    return
  }
  void saveRoles(id, next)
}

async function resetRoles() {
  const id = props.actorId
  if (id === null || resetting.value) return
  rolesError.value = null
  resetting.value = true
  try {
    const res = await updateUser(id, { roles: null })
    applyUser(id, res)
    done('admin.toast.rolesSaved', 'admin-user-roles')
    emit('changed')
    refreshDetail()
  } catch (err) {
    if (props.actorId === id) rolesError.value = userActionError(err, tr)
  } finally {
    resetting.value = false
  }
}

/* ---------------------------------------------------------------- kirish */

/** Bloklab bo'lmaydigan holat - sabab kalitning ostida yoziladi (sensorli ekranda
 *  tooltip yo'q). Blokdan chiqarish esa har doim mumkin. */
const blockLock = computed<string | null>(() => {
  const b = base.value
  if (!b || b.disabled) return null
  if (isSelf.value) return t('admin.users.selfBlock')
  if (b.rolesLocked) return t('admin.users.lockedBlock')
  return null
})

function askBlock(next: boolean) {
  const id = props.actorId
  if (id === null || !base.value) return
  askConfirm({
    title: t(next ? 'admin.confirm.blockTitle' : 'admin.confirm.unblockTitle', { name: name.value }),
    body: t(next ? 'admin.confirm.blockBody' : 'admin.users.unblockBody'),
    action: t(next ? 'admin.user.block' : 'admin.user.unblock'),
    danger: next,
    run: async () => {
      const res = await updateUser(id, { disabled: next })
      applyUser(id, res)
      done(next ? 'admin.toast.blocked' : 'admin.toast.unblocked')
    },
  })
}

function askSignOut() {
  const id = props.actorId
  if (id === null) return
  const self = isSelf.value
  askConfirm({
    title: t('admin.confirm.signOutTitle', { name: name.value }),
    body: self ? `${t('admin.confirm.signOutBody')} ${t('admin.users.signOutSelf')}` : t('admin.confirm.signOutBody'),
    action: t('admin.confirm.signOut'),
    danger: true,
    leaves: self,
    run: async () => {
      await signOutUser(id)
      done('admin.toast.signedOut')
      if (self) await leaveAfterSelfSignOut()
    },
  })
}

// O'zini hamma joydan chiqargan admin: joriy token ham bekor bo'ldi. Menyudagi
// "Chiqish" bilan bir xil tozalash, keyin kirish sahifasi (qaytish manzili bilan).
async function leaveAfterSelfSignOut() {
  palette.clearRecents()
  useChats().reset()
  const back = route.fullPath
  await logout()
  await router.push({ name: 'login', query: { redirect: back } })
}

/* ---------------------------------------------------------------- ulanishlar */

function connStatus(c: AdminConnector): { tone: StatusTone; label: string } {
  if (c.state === 'connected') {
    return c.enabled
      ? { tone: 'good', label: t('admin.user.connected') }
      : { tone: 'neutral', label: t('admin.users.paused') }
  }
  if (c.state === 'expired') return { tone: 'warn', label: t('admin.user.expired') }
  return { tone: 'neutral', label: t('admin.user.notConnected') }
}

const platformLabel = (p: string) => p.toUpperCase()

function askDisconnect(c: AdminConnector) {
  const id = props.actorId
  if (id === null) return
  const platform = platformLabel(c.platform)
  askConfirm({
    title: t('admin.confirm.disconnectTitle', { platform }),
    body: t('admin.confirm.disconnectBody', { platform }),
    action: t('admin.user.disconnect'),
    danger: true,
    run: async () => {
      const res = await disconnectUserConnector(id, c.platform)
      q.mutate((d) =>
        d.actorId === id ? { ...d, connectors: d.connectors.map((x) => (x.platform === c.platform ? res : x)) } : d,
      )
      done('admin.toast.disconnected')
    },
  })
}

function askUnlink() {
  const id = props.actorId
  if (id === null) return
  askConfirm({
    title: t('admin.confirm.unlinkTelegramTitle'),
    body: t('admin.confirm.unlinkTelegramBody'),
    action: t('admin.user.unlink'),
    danger: true,
    run: async () => {
      await unlinkUserTelegram(id)
      q.mutate((d) => (d.actorId === id ? { ...d, telegram: { ...d.telegram, links: 0 } } : d))
      done('admin.toast.unlinked')
    },
  })
}

/* ---------------------------------------------------------------- versiya */

// Shu odamga hozir qaysi versiya ishlaydi (kanal bo'yicha) va unga alohida nima berilgan.
// Muharrir - "Versiyalar" sahifasidagi AYNI oyna (bir xil maydonlar va tekshiruv).
const engine = computed(() => detail.value?.engine ?? null)
const engineText = (id: string) => engineLabel(id, t, te)
const engineEditorOpen = ref(false)
const engineAccessText = computed(() => {
  const a = engine.value?.access
  if (!a || !a.engines.length) return null
  const list = a.engines.join(', ')
  return a.defaultEngine && a.engines.length > 1
    ? `${list} · ${t('admin.versions.defaultEngine')}: ${a.defaultEngine}`
    : list
})
// Faqat tarixda qolgan odam (hisobi manbada yo'q) - unga yangi ruxsat berish ma'nosiz.
const canGrant = computed(() => base.value?.source !== 'telemetry' || !!engine.value?.access)

function onEngineSaved(row: EngineAccessRow) {
  const id = row.actorId
  q.mutate((d) =>
    d.actorId === id && d.engine
      ? { ...d, engine: { ...d.engine, access: { engines: row.engines, defaultEngine: row.defaultEngine } } }
      : d,
  )
  // Kanal bo'yicha "hozir" va audit server hisoblaydi - jimgina qayta so'raymiz.
  refreshDetail()
}

function askRemoveEngine() {
  const id = props.actorId
  if (id === null) return
  askConfirm({
    title: t('admin.versions.removeTitle', { name: name.value }),
    body: t('admin.versions.removeBodyShort'),
    action: t('admin.versions.remove'),
    danger: true,
    run: async () => {
      await deleteEngineAccess(id)
      q.mutate((d) => (d.actorId === id && d.engine ? { ...d, engine: { ...d.engine, access: null } } : d))
      done('admin.versions.accessRemoved')
    },
  })
}

/* ---------------------------------------------------------------- izoh */

const NOTE_MAX = 500
const noteDraft = ref('')
// Oxirgi marta serverdan olingan matn: yangilanish yozilayotgan izohni bosib ketmasin.
const noteBase = ref('')
const noteSaving = ref(false)
const noteError = ref<string | null>(null)
const noteDirty = computed(() => noteDraft.value.trim() !== noteBase.value.trim())

watch(
  () => (detail.value ? (detail.value.note ?? '') : null),
  (note) => {
    if (note === null) return
    if (noteDraft.value === noteBase.value) noteDraft.value = note
    noteBase.value = note
  },
  { immediate: true },
)

async function saveNote() {
  const id = props.actorId
  if (id === null || noteSaving.value) return
  const value = noteDraft.value.trim()
  noteSaving.value = true
  noteError.value = null
  try {
    await updateUser(id, { note: value })
    if (props.actorId === id) {
      noteBase.value = value
      noteDraft.value = value
    }
    q.mutate((d) => (d.actorId === id ? { ...d, note: value || null } : d))
    done('admin.toast.noteSaved')
    refreshDetail()
  } catch (err) {
    if (props.actorId === id) noteError.value = userActionError(err, tr)
  } finally {
    noteSaving.value = false
  }
}

/* ---------------------------------------------------------------- boshqa odam */

// Boshqa odam ochilganda - oldingisining qoralamalari va xatolari qolmasin.
watch(
  () => props.actorId,
  () => {
    rolesDraft.value = null
    rolesError.value = null
    extraRoles.value = []
    noteDraft.value = ''
    noteBase.value = ''
    noteError.value = null
    confirmOpen.value = false
    engineEditorOpen.value = false
  },
)

function onOpenChange(v: boolean) {
  if (!v) emit('close')
}
</script>

<template>
  <VSheet
    :open="open"
    side="right"
    size="md"
    padding="none"
    class="us"
    @update:open="onOpenChange"
  >
    <template #header="{ titleId }">
      <div class="us-head">
        <VAvatar v-if="!notFound" :name="base?.name || base?.login || ''" :size="40" />
        <div class="us-head__text">
          <h2 :id="titleId" class="us-head__name">
            <template v-if="notFound">{{ t('admin.error.notFound') }}</template>
            <template v-else-if="base">{{ name }}</template>
            <template v-else>
              <VSkeleton :width="168" :height="18" />
              <span class="sr-only">{{ t('ui.loading') }}</span>
            </template>
          </h2>
          <p v-if="loginLine" class="us-head__sub">{{ loginLine }}</p>
          <p v-if="orgLine" class="us-head__sub">{{ orgLine }}</p>
          <div v-if="base && (isSelf || base.disabled || base.source === 'telemetry')" class="us-head__badges">
            <VBadge v-if="isSelf" size="sm">{{ t('admin.user.you') }}</VBadge>
            <StatusDot v-if="base.disabled" status="blocked" tone="crit" :label="t('admin.user.blocked')" />
            <VBadge v-if="base.source === 'telemetry'" size="sm">{{ sourceLabel }}</VBadge>
          </div>
        </div>
      </div>
    </template>

    <div class="us-body">
      <VEmpty v-if="notFound" :icon="UserX" :title="t('admin.error.notFound')" compact />

      <AdminError
        v-else-if="failed"
        :message="q.errorText.value"
        :busy="q.loading.value"
        @retry="q.refresh"
      />

      <template v-else>
        <!-- davr statistikasi -->
        <section class="us-stats" :aria-labelledby="`${uid}-stats`">
          <h3 :id="`${uid}-stats`" class="sr-only">{{ t('admin.overview.activity') }}</h3>
          <p v-if="period.length" class="us-period">
            <CalendarDays :size="14" :stroke-width="1.75" aria-hidden="true" />
            <span class="sr-only">{{ t('admin.filter.period') }}</span>
            <span v-for="(part, i) in period" :key="i">{{ part }}</span>
          </p>
          <dl class="us-stats__grid">
            <div v-for="s in stats" :key="s.key" class="us-stat">
              <dt>{{ s.label }}</dt>
              <dd>
                <template v-if="s.value !== null">{{ s.value }}</template>
                <VSkeleton v-else :width="44" :height="20" />
              </dd>
            </div>
          </dl>
        </section>

        <!-- rollar -->
        <section class="us-sec" :aria-labelledby="`${uid}-roles`">
          <div class="us-sec__head">
            <h3 :id="`${uid}-roles`" class="us-h3">{{ t('admin.user.roles') }}</h3>
            <VSpinner v-if="rolesSaving" :size="14" :label="t('ui.loading')" />
          </div>
          <template v-if="base">
            <VChoiceChips
              multiple
              size="sm"
              :options="roleOptions"
              :model-value="shownRoles"
              :aria-label="t('admin.user.roles')"
              @update:model-value="onRolesChange"
            />
            <div class="us-meta">
              <VTooltip v-if="adminLock" :text="adminLock.reason" :describe="!!adminLock.label">
                <span
                  class="us-lock"
                  tabindex="0"
                  :aria-label="adminLock.label ? undefined : adminLock.reason"
                >
                  <Lock :size="14" :stroke-width="1.75" aria-hidden="true" />
                  <span v-if="adminLock.label">{{ adminLock.label }}</span>
                </span>
              </VTooltip>
              <span class="us-meta__text">{{ rolesSourceText }}</span>
              <VButton
                v-if="base.rolesSource === 'admin'"
                class="us-meta__reset"
                variant="ghost"
                size="sm"
                :icon="RotateCcw"
                :loading="resetting"
                @click="resetRoles"
              >
                {{ t('admin.user.resetRoles') }}
              </VButton>
            </div>
            <p v-if="rolesError" class="us-err" role="alert">
              <CircleAlert :size="14" :stroke-width="1.75" aria-hidden="true" />
              {{ rolesError }}
            </p>
          </template>
          <div v-else class="us-sk-row" aria-hidden="true">
            <VSkeleton v-for="w in [64, 88, 104]" :key="w" :width="w" :height="32" radius="full" />
          </div>
        </section>

        <!-- kirish -->
        <section class="us-sec" :aria-labelledby="`${uid}-access`">
          <h3 :id="`${uid}-access`" class="us-h3">{{ t('admin.user.access') }}</h3>
          <template v-if="base">
            <VSwitch
              :model-value="base.disabled"
              :label="t('admin.user.block')"
              :description="blockLock ?? t('admin.user.blockHint')"
              :disabled="!!blockLock"
              label-first
              @update:model-value="askBlock"
            />
            <dl class="us-kv">
              <div>
                <dt>{{ t('admin.user.lastLogin') }}</dt>
                <dd><RelTime :value="base.lastLoginAt" long /></dd>
              </div>
              <div>
                <dt>{{ t('admin.user.lastSeen') }}</dt>
                <dd><RelTime :value="base.lastSeenAt" long /></dd>
              </div>
            </dl>
            <div class="us-actions">
              <VButton variant="outline" size="sm" :icon="LogOut" @click="askSignOut">
                {{ t('admin.user.signOutEverywhere') }}
              </VButton>
            </div>
          </template>
          <VSkeleton v-else :lines="2" />
        </section>

        <!-- versiya: eski server bu maydonni bermaydi - bo'lim umuman chizilmaydi -->
        <section v-if="!detail || engine" class="us-sec" :aria-labelledby="`${uid}-engine`">
          <h3 :id="`${uid}-engine`" class="us-h3">{{ t('admin.versions.section') }}</h3>
          <template v-if="engine">
            <dl class="us-kv">
              <div v-for="ch in ENGINE_CHANNELS" :key="ch">
                <dt>{{ t(`admin.channel.${ch}`) }}</dt>
                <dd class="us-engine">{{ engineText(engine.effective[ch]) }}</dd>
              </div>
            </dl>
            <div class="us-row us-row--engine">
              <div class="us-engine-access">
                <span class="us-engine-access__label">{{ t('admin.versions.access') }}</span>
                <span v-if="engineAccessText" class="us-engine-access__value">{{ engineAccessText }}</span>
                <span v-else class="us-engine-access__none">{{ t('admin.versions.general') }}</span>
              </div>
              <span class="us-row__action us-engine-acts">
                <VButton
                  v-if="engine.access"
                  variant="ghost"
                  size="sm"
                  :icon="Trash2"
                  @click="askRemoveEngine"
                >
                  {{ t('admin.versions.remove') }}
                </VButton>
                <VButton
                  v-if="canGrant"
                  variant="ghost"
                  size="sm"
                  :icon="Pencil"
                  @click="engineEditorOpen = true"
                >
                  {{ engine.access ? t('admin.versions.edit') : t('admin.versions.grant') }}
                </VButton>
              </span>
            </div>
          </template>
          <VSkeleton v-else :lines="2" />
        </section>

        <!-- ulanishlar -->
        <section class="us-sec" :aria-labelledby="`${uid}-conn`">
          <h3 :id="`${uid}-conn`" class="us-h3">{{ t('admin.user.connections') }}</h3>
          <template v-if="detail">
            <ul v-if="detail.connectors.length" class="us-rows" :aria-labelledby="`${uid}-conn`">
              <li v-for="c in detail.connectors" :key="c.platform" class="us-row">
                <span class="us-row__name">{{ platformLabel(c.platform) }}</span>
                <span class="us-row__main">
                  <StatusDot :status="c.state" :tone="connStatus(c).tone" :label="connStatus(c).label" />
                  <span v-if="c.login || (c.expiresAt && c.state !== 'disconnected')" class="us-row__meta">
                    <span v-if="c.login" class="us-row__login">{{ c.login }}</span>
                    <span v-if="c.login && c.expiresAt && c.state !== 'disconnected'" aria-hidden="true">·</span>
                    <span v-if="c.expiresAt && c.state !== 'disconnected'" class="us-row__exp">
                      {{ t('admin.users.expires') }} <RelTime :value="c.expiresAt" />
                    </span>
                  </span>
                </span>
                <VButton
                  v-if="c.state !== 'disconnected'"
                  class="us-row__action"
                  variant="ghost"
                  size="sm"
                  :icon="Unplug"
                  @click="askDisconnect(c)"
                >
                  {{ t('admin.user.disconnect') }}
                </VButton>
              </li>
            </ul>
            <p v-else class="us-none">{{ t('admin.user.notConnected') }}</p>
          </template>
          <VSkeleton v-else :lines="2" />
        </section>

        <!-- telegram -->
        <section class="us-sec" :aria-labelledby="`${uid}-tg`">
          <h3 :id="`${uid}-tg`" class="us-h3">{{ t('admin.user.telegram') }}</h3>
          <template v-if="detail">
            <div v-if="detail.telegram.links > 0" class="us-row us-row--tg">
              <dl class="us-kv">
                <div>
                  <dt>{{ t('admin.user.telegramLinks') }}</dt>
                  <dd class="us-num">{{ num(detail.telegram.links) }}</dd>
                </div>
                <div>
                  <dt>{{ t('admin.user.lastSeen') }}</dt>
                  <dd><RelTime :value="detail.telegram.lastSeenAt" long /></dd>
                </div>
              </dl>
              <VButton class="us-row__action" variant="ghost" size="sm" :icon="Unlink" @click="askUnlink">
                {{ t('admin.user.unlink') }}
              </VButton>
            </div>
            <p v-else class="us-none">{{ t('admin.user.notConnected') }}</p>
          </template>
          <VSkeleton v-else :width="160" :height="12" />
        </section>

        <!-- so'nggi faollik -->
        <section class="us-sec" :aria-labelledby="`${uid}-recent`">
          <h3 :id="`${uid}-recent`" class="us-h3">{{ t('admin.user.recentActivity') }}</h3>
          <UserRecent
            v-if="actorId !== null"
            :turns="detail ? detail.recentTurns : null"
            :actor-id="actorId"
            :name="base?.name"
            :login="base?.login ?? base?.email"
            :labelledby="`${uid}-recent`"
          />
        </section>

        <!-- izoh -->
        <section class="us-sec" :aria-labelledby="`${uid}-note`">
          <h3 :id="`${uid}-note`" class="us-h3">{{ t('admin.user.note') }}</h3>
          <VTextarea
            v-model="noteDraft"
            :rows="2"
            :max-rows="6"
            :maxlength="NOTE_MAX"
            :placeholder="t('admin.reports.notePlaceholder')"
            :error="noteError"
            :disabled="!detail"
            :aria-labelledby="`${uid}-note`"
          />
          <div v-if="noteDirty" class="us-actions us-actions--end">
            <VButton variant="ghost" size="sm" :disabled="noteSaving" @click="noteDraft = noteBase">
              {{ t('ui.cancel') }}
            </VButton>
            <VButton variant="primary" size="sm" :loading="noteSaving" @click="saveNote">
              {{ t('ui.save') }}
            </VButton>
          </div>
        </section>

        <!-- o'zgarishlar -->
        <section class="us-sec" :aria-labelledby="`${uid}-audit`">
          <h3 :id="`${uid}-audit`" class="us-h3">{{ t('admin.users.changes') }}</h3>
          <UserAudit :entries="detail ? detail.audit : null" :labelledby="`${uid}-audit`" />
        </section>
      </template>
    </div>
  </VSheet>

  <EngineAccessDialog
    v-if="actorId !== null"
    v-model:open="engineEditorOpen"
    :person="{ actorId, name: base?.name ?? null, login: base?.login ?? base?.email ?? null }"
    :initial="engine?.access ?? null"
    :engines="[...ENGINES]"
    :preferred="engine?.effective.web ?? null"
    @saved="onEngineSaved"
  />

  <VDialog
    v-model:open="confirmOpen"
    alert
    :title="confirm?.title"
    :description="confirm?.body"
    :dismissible="!confirmBusy"
  >
    <p v-if="confirmError" class="us-err" role="alert">
      <CircleAlert :size="14" :stroke-width="1.75" aria-hidden="true" />
      {{ confirmError }}
    </p>
    <template #footer="{ close }">
      <VButton variant="ghost" :disabled="confirmBusy" @click="close">{{ t('ui.cancel') }}</VButton>
      <VButton :variant="confirm?.danger ? 'danger' : 'primary'" :loading="confirmBusy" @click="runConfirm">
        {{ confirm?.action }}
      </VButton>
    </template>
  </VDialog>
</template>

<style scoped>
/* ---- sarlavha ---- */
.us-head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-4);
  min-width: 0;
}
.us-head__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding-top: 2px;
}
.us-head__name {
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  font-weight: 600;
  letter-spacing: -0.016em;
  overflow-wrap: anywhere;
}
.us-head__sub {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.us-head__badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2);
  margin-top: var(--s-2);
}

/* ---- tana ---- */
.us-body {
  display: flex;
  flex-direction: column;
  padding: var(--s-2) var(--s-6) var(--s-10);
}

.us-stats {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  padding-bottom: var(--s-6);
}
.us-period {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.us-stats__grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s-4);
  margin: 0;
}
.us-stat {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
}
.us-stat dt {
  overflow: hidden;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.us-stat dd {
  display: flex;
  align-items: center;
  min-height: var(--lh-title-2);
  margin: 0;
  color: var(--text);
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  font-weight: 600;
  letter-spacing: -0.016em;
  white-space: nowrap;
}

.us-sec {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--s-3);
  padding: var(--s-6) 0;
  border-top: 1px solid var(--line);
}
.us-sec:last-child {
  padding-bottom: 0;
}
.us-sec__head {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  color: var(--text-3);
}
.us-h3 {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
  letter-spacing: -0.003em;
}

.us-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-1) var(--s-3);
  min-height: 32px;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.us-meta__text {
  min-width: 0;
}
.us-meta__reset {
  margin-left: calc(var(--s-2) * -1);
}
.us-lock {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  padding: 2px var(--s-1_5);
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-weight: 500;
}
.us-lock:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.us-err {
  display: flex;
  align-items: flex-start;
  gap: var(--s-1_5);
  color: var(--crit-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.us-err > svg {
  flex: none;
  margin-top: 1px;
}

.us-kv {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2) var(--s-8);
  min-width: 0;
  margin: 0;
}
.us-kv > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.us-kv dt {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.us-kv dd {
  margin: 0;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.us-num {
  font-variant-numeric: tabular-nums;
}

.us-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
}
.us-actions--end {
  justify-content: flex-end;
}

/* ulanishlar / telegram qatorlari */
.us-rows {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.us-row {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s-3);
  min-height: 48px;
  padding: var(--s-1) 0;
}
.us-rows .us-row + .us-row {
  border-top: 1px solid var(--line);
}
.us-row--tg {
  grid-template-columns: minmax(0, 1fr) auto;
}
/* Versiya: matn va ikki tugma. Grid emas - tor ekranda tugmalar matnni 40px ga siqib
   qo'ymasin ("Stand / art"), balki keyingi qatorga tushsin. */
.us-row--engine {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  column-gap: var(--s-3);
  row-gap: var(--s-1);
}
.us-row--engine .us-engine-access {
  flex: 1 1 10rem;
}
.us-row--engine .us-engine-acts {
  margin-inline-start: auto;
}
.us-row__name {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.us-row__main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-1) var(--s-3);
  min-width: 0;
}
.us-row__meta {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  min-width: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.us-row__login {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.us-row__exp {
  white-space: nowrap;
}
.us-row__action {
  justify-self: end;
}

/* versiya */
.us-engine {
  font-variant-numeric: tabular-nums;
}
.us-engine-access {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.us-engine-access__label {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.us-engine-access__value {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.us-engine-access__none {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.us-engine-acts {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--s-1);
}

.us-none {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.us-sk-row {
  display: flex;
  gap: var(--s-2);
}

/* ---- telefon: pastki sheet ---- */
@media (max-width: 767.98px) {
  .us-body {
    padding: var(--s-1) var(--s-5) var(--s-8);
  }
  .us-stats__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    row-gap: var(--s-3);
  }
  .us-row {
    grid-template-columns: 40px minmax(0, 1fr) auto;
  }
  /* Yuqoridagi qoida ikki ustunli Telegram qatorini ham uch ustunga aylantirardi. */
  .us-row--tg {
    grid-template-columns: minmax(0, 1fr) auto;
  }
}
</style>
