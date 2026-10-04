<script setup lang="ts">
import { computed, reactive, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, Pencil, Plus, Trash2, UserCog, Users } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VDataTable from '../../ui/VDataTable.vue'
import type { DataTableColumn } from '../../ui/VDataTable.vue'
import VDialog from '../../ui/VDialog.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VSegmented from '../../ui/VSegmented.vue'
import type { SegmentedOption } from '../../ui/VSegmented.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VSpinner from '../../ui/VSpinner.vue'
import { fmtMs, fmtNumber, fmtPercent } from '../../ui/format'
import { useToast } from '../../ui/useToast'
import { useIsPhone } from '../../ui/composables/useMediaQuery'
import { deleteEngineAccess, getEngines, putEnginePolicy } from '../api'
import { ENGINE_CHANNELS } from '../types'
import type { AdminEngines, EngineAccessRow, EngineChannel, EngineInfo } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import RelTime from '../components/RelTime.vue'
import UserCell from '../components/UserCell.vue'
import { channelIcon } from '../components/channel'
import { useAdminQuery } from '../components/useAdminQuery'
import { userActionError } from '../users/userErrors'
import EngineAccessDialog from '../versions/EngineAccessDialog.vue'
import type { AccessPerson } from '../versions/EngineAccessDialog.vue'
import { catalogIds, engineDesc, engineLabel, engineName, inheritedFor, publicDefault } from '../versions/engineText'

// "Versiyalar": yordamchining qaysi versiyasi kimga ishlaydi. Uch qavat, tepadan pastga
// - eng kengdan eng torga (backend tartibi ham shu, `services/engine_control.py`):
//   1. Hamma uchun   - ikki karta, biri "Hammaga" belgili; ikkinchisida "Hammaga berish".
//   2. Kanallar      - Web / Mini App / Bot uchun boshqa versiya (yoki "Umumiy").
//   3. Alohida ruxsat - aniq odamlar; ikki versiya berilsa odam chatda o'zi tanlaydi.
// Har qavat yuqoridagisidan ustun - shuning uchun "Hammaga berish" tasdig'i qaysi
// kanallar o'zgarmay qolishini aytadi (aks holda "hammaga berdim, bot nega eskisida?").
//
// Global davr/kanal filtri bu yerga TEGISHLI EMAS (sozlama "hozir" haqida; statistika
// doim oxirgi 7 kun) - sarlavhada filtr yo'q, faqat "Yangilash".

const { t, te, locale } = useI18n({ useScope: 'global' })
const tr = (key: string) => t(key)
const toast = useToast()
const { withFilters } = useAdminFilters()
// Telefonda kanal segmentlari to'liq enda va teng - barmoq uchun katta nishon.
const isPhone = useIsPhone()

const q = useAdminQuery((_p: null, signal: AbortSignal) => getEngines(signal), { params: null })
const data = computed<AdminEngines | null>(() => q.data.value)

const label = (id: string | null | undefined) => engineLabel(id, t, te)
const num = (n: number | null | undefined) => fmtNumber(n, locale.value)
const channelName = (ch: string) => t(`admin.channel.${ch}`)

/* ---------------------------------------------------------------- tasdiqlash */

interface ConfirmSpec {
  title: string
  body: string
  action: string
  danger: boolean
  run: () => Promise<void>
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
  } catch (err) {
    // Oyna ochiq qoladi: sabab shu yerda, "Bekor qilish" yoki qayta urinish qo'l ostida.
    confirmError.value = userActionError(err, tr)
  } finally {
    confirmBusy.value = false
  }
}

function done(message: string, id?: string) {
  toast.show({ message, tone: 'good', id })
}

/* ---------------------------------------------------------------- versiya kartalari */

interface EngineCard {
  info: EngineInfo
  name: string
  desc: string
  isPublic: boolean
  stats: { key: string; label: string; value: string }[]
  hasTurns: boolean
}

const publicEngine = computed(() => (data.value ? publicDefault(data.value) : ''))
/** Birorta kartada imkoniyat belgisi bo'lsa - hammasida shu qator joyi bor: statistika
 *  kartalar orasida bir chiziqda tursin (yonma-yon solishtiriladi). */
const anyCaps = computed(() => cards.value.some((c) => c.info.pro || c.info.law))

const cards = computed<EngineCard[]>(() => {
  const d = data.value
  if (!d) return []
  const list = d.catalog.length ? d.catalog : catalogIds(d).map((id) => ({ id, pro: false, law: false }))
  return list.map((info) => {
    const s = d.stats.find((x) => x.engine === info.id)
    const turns = s?.turns ?? 0
    return {
      info,
      name: engineName(info.id, t, te),
      desc: engineDesc(info.id, t, te),
      isPublic: info.id === publicEngine.value,
      hasTurns: turns > 0,
      stats: [
        { key: 'turns', label: t('admin.kpi.turns'), value: num(turns) },
        { key: 'errors', label: t('admin.kpi.errorRate'), value: turns ? fmtPercent((s?.errors ?? 0) / turns, 1, locale.value) : '—' },
        { key: 'ttft', label: t('admin.kpi.medianTtft'), value: fmtMs(s?.medianTtftMs ?? null, locale.value) },
        { key: 'users', label: t('admin.versions.people'), value: num(s?.users ?? 0) },
      ],
    }
  })
})

/** "Sozlamadan (.env)" yoki "Admin: Ism" (+ vaqt alohida RelTime bilan). */
const policySource = computed(() => {
  const p = data.value?.policy
  if (!p) return null
  if (p.source !== 'admin' || !p.default) return { text: t('admin.versions.sourceEnv'), at: null }
  return { text: t('admin.versions.sourceAdmin', { who: p.updatedBy || t('admin.common.unknownUser') }), at: p.updatedAt }
})

function askEveryone(id: string) {
  const d = data.value
  if (!d) return
  // O'z sozlamasi bor va boshqa versiyadagi kanallar - "hammaga" ulardan pastda turadi.
  const kept = ENGINE_CHANNELS.filter((ch) => {
    const own = d.policy.channels[ch]
    return !!own && own !== id
  }).map((ch) => `${channelName(ch)} (${d.policy.channels[ch]})`)
  const body = [
    t('admin.versions.confirmBody', { v: id }),
    kept.length ? t('admin.versions.confirmChannels', { list: kept.join(', ') }) : '',
  ]
    .filter(Boolean)
    .join(' ')
  askConfirm({
    title: t('admin.versions.confirmTitle', { v: id }),
    body,
    action: t('admin.versions.move'),
    danger: false,
    run: async () => {
      const res = await putEnginePolicy({ default: id })
      q.mutate(() => res)
      done(t('admin.versions.saved'), 'admin-engine-policy')
    },
  })
}

/* ---------------------------------------------------------------- kanallar */

/** VSegmented `null` qiymatni bilmaydi - "Umumiy" (meros) uchun belgi. */
const INHERIT = '__inherit__'

const channelOptions = computed<SegmentedOption<string>[]>(() => [
  { value: INHERIT, label: t('admin.versions.inherit') },
  ...catalogIds(data.value).map((id) => ({ value: id, label: id })),
])

/** Saqlanayotgan qiymat: so'rov ketguncha segment yangi joyda tursin (orqaga sakramasin). */
const draft = reactive<Partial<Record<EngineChannel, string>>>({})
const saving = reactive<Partial<Record<EngineChannel, boolean>>>({})

function channelValue(ch: EngineChannel): string {
  return draft[ch] ?? data.value?.policy.channels[ch] ?? INHERIT
}

async function saveChannel(ch: EngineChannel, value: string) {
  const engine = value === INHERIT ? null : value
  draft[ch] = value
  saving[ch] = true
  try {
    const res = await putEnginePolicy({ channels: { [ch]: engine } })
    q.mutate(() => res)
    done(t('admin.versions.channelSaved', { channel: channelName(ch), v: label(res.effective[ch]) }), `admin-engine-ch-${ch}`)
  } catch (err) {
    toast.show({ message: userActionError(err, tr), tone: 'crit', id: `admin-engine-ch-${ch}` })
  } finally {
    delete draft[ch]
    saving[ch] = false
  }
}

function onChannel(ch: EngineChannel, value: string) {
  const d = data.value
  if (!d || saving[ch] || value === channelValue(ch)) return
  const base = inheritedFor(d, ch)
  // Tasdiq faqat kanal "hammadan" AJRALIB chiqayotganda: shu kanaldagi hamma odam boshqa
  // versiyaga o'tadi. "Umumiy" ga qaytish yoki umumiy bilan bir xil versiya - xavfsiz.
  if (value !== INHERIT && value !== base) {
    askConfirm({
      title: t('admin.versions.channelTitle', { channel: channelName(ch), v: value }),
      body: t('admin.versions.channelBody', { base: label(base) }),
      action: t('admin.versions.move'),
      danger: false,
      run: async () => {
        confirmOpen.value = false
        await saveChannel(ch, value)
      },
    })
    return
  }
  void saveChannel(ch, value)
}

/* ---------------------------------------------------------------- alohida ruxsat */

const accessRows = computed<EngineAccessRow[]>(() => data.value?.access ?? [])
const asRow = (r: unknown) => r as EngineAccessRow

const columns = computed<DataTableColumn<EngineAccessRow>[]>(() => [
  {
    key: 'user',
    label: t('admin.col.user'),
    sortable: true,
    sortValue: (r) => (r.name || r.login || '').toLocaleLowerCase(),
  },
  { key: 'engines', label: t('admin.versions.colEngines'), width: 132 },
  { key: 'defaultEngine', label: t('admin.versions.colDefault'), width: 132 },
  { key: 'note', label: t('admin.versions.colNote'), width: '22%' },
  {
    key: 'updatedAt',
    label: t('admin.versions.colChanged'),
    width: 168,
    sortable: true,
    sortValue: (r) => (r.updatedAt ? Date.parse(r.updatedAt) : null),
  },
  { key: 'actions', label: '', width: 88, align: 'end' },
])

/** Standart ustuni: aytilgani; aytilmagan - bitta versiya bo'lsa o'sha, bir nechta - "Umumiy". */
function defaultText(r: EngineAccessRow): string {
  if (r.defaultEngine) return r.defaultEngine
  if (r.engines.length === 1) return r.engines[0]
  return t('admin.versions.inherit')
}

const editorOpen = ref(false)
const editorPerson = ref<AccessPerson | null>(null)
const editorInitial = ref<{ engines: string[]; defaultEngine: string | null; note: string | null } | null>(null)

function openAdd() {
  editorPerson.value = null
  editorInitial.value = null
  editorOpen.value = true
}

function openEdit(r: EngineAccessRow) {
  editorPerson.value = { actorId: r.actorId, name: r.name, login: r.login }
  editorInitial.value = { engines: [...r.engines], defaultEngine: r.defaultEngine, note: r.note }
  editorOpen.value = true
}

function onSaved(row: EngineAccessRow) {
  q.mutate((d) => {
    const has = d.access.some((r) => r.actorId === row.actorId)
    const access = has ? d.access.map((r) => (r.actorId === row.actorId ? row : r)) : [row, ...d.access]
    return { ...d, access }
  })
}

// Oyna yopilganda fokus uni ochgan tugmaga qaytadi - lekin u tugma yo'qolishi mumkin:
// birinchi ruxsat saqlandi (bo'sh holatdagi "Qo'shish" endi yo'q) yoki qator o'chirildi
// (uning savatchasi ham). Shunda fokus `body` ga tushib, klaviatura va ekran o'quvchi
// sahifa boshidan boshlardi - bo'lim sarlavhasida qolsin. Oyna yopilish animatsiyasi
// tugagach (`after-leave`): undan oldin fokus hali yopilayotgan oynaning tugmasida.
const accessHeading = ref<HTMLElement | null>(null)
function keepAccessFocus() {
  const active = document.activeElement
  if (!active || active === document.body) accessHeading.value?.focus({ preventScroll: true })
}

function askRemove(r: EngineAccessRow) {
  const name = r.name || r.login || `#${r.actorId}`
  askConfirm({
    title: t('admin.versions.removeTitle', { name }),
    // Qavs ichida - "hamma uchun" versiya (kanal sozlamasi bo'lsa u kanalda boshqacha bo'ladi).
    body: publicEngine.value
      ? t('admin.versions.removeBody', { v: label(publicEngine.value) })
      : t('admin.versions.removeBodyShort'),
    action: t('admin.versions.remove'),
    danger: true,
    run: async () => {
      await deleteEngineAccess(r.actorId)
      q.mutate((cur) => ({ ...cur, access: cur.access.filter((x) => x.actorId !== r.actorId) }))
      done(t('admin.versions.accessRemoved'), 'admin-engine-access')
    },
  })
}
</script>

<template>
  <section class="vp" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.versions.title')"
      :subtitle="t('admin.page.versions.subtitle')"
      :refreshing="q.loading.value"
      @refresh="q.refresh"
    />

    <AdminError v-if="q.error.value && !data" :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

    <!-- birinchi yuklash: kartalar va ro'yxat o'rnida skelet (sakrash yo'q) -->
    <div v-else-if="q.firstLoad.value" class="vp-cards" aria-hidden="true">
      <div v-for="k in 2" :key="k" class="vp-card">
        <VSkeleton :width="120" :height="20" />
        <VSkeleton :lines="2" />
        <VSkeleton :width="'70%'" :height="36" />
      </div>
    </div>

    <template v-else-if="data">
      <AdminError v-if="q.error.value" inline :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

      <!-- 1. hamma uchun -->
      <div class="vp-cards" :class="{ 'is-busy': q.refetching.value }">
        <article
          v-for="c in cards"
          :key="c.info.id"
          class="vp-card"
          :class="{ 'is-public': c.isPublic }"
          :aria-labelledby="`vp-card-${c.info.id}`"
        >
          <header class="vp-card__head">
            <h2 :id="`vp-card-${c.info.id}`" class="vp-card__title">
              <span class="vp-card__id">{{ c.info.id }}</span>
              <span v-if="c.name" class="vp-card__name">{{ c.name }}</span>
            </h2>
            <VBadge v-if="c.isPublic" tone="good" size="sm" :icon="Users">{{ t('admin.versions.everyone') }}</VBadge>
          </header>

          <p v-if="c.desc" class="vp-card__desc">{{ c.desc }}</p>
          <div v-if="anyCaps" class="vp-card__caps" :class="{ 'is-empty': !c.info.pro && !c.info.law }">
            <VBadge v-if="c.info.pro" size="sm">Pro</VBadge>
            <VBadge v-if="c.info.law" size="sm">LEX.UZ</VBadge>
          </div>

          <div class="vp-card__statsbox">
            <p class="vp-card__period">{{ t('admin.versions.last7') }}</p>
            <dl class="vp-card__stats">
              <div v-for="s in c.stats" :key="s.key" class="vp-stat">
                <dt>{{ s.label }}</dt>
                <dd :class="{ 'is-zero': !c.hasTurns }">{{ s.value }}</dd>
              </div>
            </dl>
          </div>

          <footer class="vp-card__foot">
            <p v-if="c.isPublic && policySource" class="vp-card__source">
              <span>{{ policySource.text }}</span>
              <template v-if="policySource.at">
                <span aria-hidden="true">·</span>
                <RelTime :value="policySource.at" />
              </template>
            </p>
            <VButton v-else-if="!c.isPublic" variant="primary" size="sm" @click="askEveryone(c.info.id)">
              {{ t('admin.versions.giveEveryone') }}
            </VButton>
          </footer>
        </article>
      </div>

      <!-- 2. kanallar -->
      <section class="vp-sec" :class="{ 'is-busy': q.refetching.value }" aria-labelledby="vp-channels">
        <div class="vp-sec__head">
          <div class="vp-sec__titles">
            <h2 id="vp-channels" class="vp-h2">{{ t('admin.versions.channels') }}</h2>
            <p class="vp-sec__hint">{{ t('admin.versions.channelsHint') }}</p>
          </div>
        </div>
        <ul class="vp-channels">
          <li v-for="ch in ENGINE_CHANNELS" :key="ch" class="vp-ch">
            <span class="vp-ch__name">
              <component :is="channelIcon(ch)" :size="18" :stroke-width="1.75" aria-hidden="true" />
              <span :id="`vp-ch-${ch}`">{{ channelName(ch) }}</span>
            </span>
            <VSegmented
              class="vp-ch__seg"
              size="sm"
              :block="isPhone"
              :options="channelOptions"
              :model-value="channelValue(ch)"
              :disabled="!!saving[ch]"
              :aria-label="channelName(ch)"
              @update:model-value="(v: string) => onChannel(ch, v)"
            />
            <span class="vp-ch__now" aria-live="polite">
              <VSpinner v-if="saving[ch]" :size="14" :label="t('ui.loading')" />
              {{ t('admin.versions.now', { v: label(data.effective[ch]) }) }}
            </span>
          </li>
        </ul>
      </section>

      <!-- 3. alohida ruxsat -->
      <section class="vp-sec" aria-labelledby="vp-access">
        <div class="vp-sec__head">
          <div class="vp-sec__titles">
            <h2 id="vp-access" ref="accessHeading" class="vp-h2" tabindex="-1">{{ t('admin.versions.access') }}</h2>
            <p class="vp-sec__hint">{{ t('admin.versions.accessHint') }}</p>
          </div>
          <VButton v-if="accessRows.length" size="sm" :icon="Plus" @click="openAdd">{{ t('admin.versions.add') }}</VButton>
        </div>

        <div class="vp-table">
          <VDataTable
            :rows="accessRows"
            :columns="columns"
            :row-key="(r: EngineAccessRow) => r.actorId"
            :loading="q.refetching.value"
            :label="t('admin.versions.access')"
            :skeleton-rows="3"
          >
            <template #cell-user="{ row }">
              <UserCell
                :name="asRow(row).name"
                :login="asRow(row).login"
                :to="withFilters(`/admin/users/${asRow(row).actorId}`)"
              />
            </template>
            <template #cell-engines="{ row }">
              <span class="vp-chips">
                <VBadge v-for="e in asRow(row).engines" :key="e" size="sm">{{ e }}</VBadge>
              </span>
            </template>
            <template #cell-defaultEngine="{ row }">
              <span class="vp-default">{{ defaultText(asRow(row)) }}</span>
            </template>
            <template #cell-note="{ row }">
              <span v-if="asRow(row).note" class="vp-note" :title="asRow(row).note ?? undefined">{{ asRow(row).note }}</span>
              <span v-else class="vp-none">—</span>
            </template>
            <template #cell-updatedAt="{ row }">
              <span class="vp-changed">
                <RelTime :value="asRow(row).updatedAt" />
                <span v-if="asRow(row).updatedBy" class="vp-changed__by">{{ asRow(row).updatedBy }}</span>
              </span>
            </template>
            <template #cell-actions="{ row }">
              <span class="vp-acts">
                <VIconButton size="sm" :icon="Pencil" :label="t('admin.versions.edit')" @click="openEdit(asRow(row))" />
                <VIconButton size="sm" :icon="Trash2" :label="t('admin.versions.remove')" @click="askRemove(asRow(row))" />
              </span>
            </template>
            <template #empty>
              <VEmpty compact :icon="UserCog" :title="t('admin.versions.emptyAccess')">
                <VButton size="sm" :icon="Plus" @click="openAdd">{{ t('admin.versions.add') }}</VButton>
              </VEmpty>
            </template>
          </VDataTable>
        </div>
      </section>
    </template>

    <EngineAccessDialog
      v-model:open="editorOpen"
      :person="editorPerson"
      :initial="editorInitial"
      :engines="catalogIds(data)"
      :preferred="publicEngine"
      :existing="accessRows"
      @saved="onSaved"
      @after-leave="keepAccessFocus"
    />

    <VDialog
      v-model:open="confirmOpen"
      alert
      :title="confirm?.title"
      :description="confirm?.body"
      :dismissible="!confirmBusy"
      @after-leave="keepAccessFocus"
    >
      <p v-if="confirmError" class="vp-err" role="alert">
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
  </section>
</template>

<style scoped>
.vp {
  display: flex;
  flex-direction: column;
  gap: var(--s-10);
  min-width: 0;
}
.is-busy {
  opacity: 0.5;
  transition: opacity var(--dur-2) var(--ease-out);
}

/* ---- versiya kartalari: yonma-yon, telefonda ustma-ust ---- */
.vp-cards {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-4);
}
@media (min-width: 768px) {
  .vp-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--s-6);
  }
}
.vp-card {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
  padding: var(--s-6);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
/* "Hammaga" kartasi - chegara biroz to'qroq: qaysi biri ishlayotgani bir qarashda. */
.vp-card.is-public {
  border-color: var(--line-strong);
  box-shadow: var(--e1);
}
.vp-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  min-width: 0;
}
.vp-card__title {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
  min-width: 0;
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  font-weight: 600;
  letter-spacing: -0.016em;
}
.vp-card__id {
  font-family: var(--font-mono);
}
.vp-card__name {
  overflow: hidden;
  color: var(--text-2);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vp-card__desc {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.vp-card__caps {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-1_5);
  min-height: 20px;
  margin-top: calc(var(--s-1) * -1);
}
.vp-card__statsbox {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  padding-top: var(--s-4);
  border-top: 1px solid var(--line);
}
.vp-card__period {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.vp-card__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s-3);
  margin: 0;
}
.vp-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.vp-stat dt {
  overflow: hidden;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vp-stat dd {
  margin: 0;
  color: var(--text);
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body-lg);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.vp-stat dd.is-zero {
  color: var(--text-3);
}
.vp-card__foot {
  display: flex;
  align-items: center;
  min-height: 32px;
  margin-top: auto;
}
.vp-card__source {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

/* ---- bo'limlar ---- */
.vp-sec {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}
.vp-sec__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s-3);
}
.vp-sec__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.vp-h2 {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.vp-sec__hint {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

/* ---- kanallar: nom | segment | hozirgi. Telefonda segment o'z qatorida, to'liq enda. */
.vp-channels {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0 var(--s-5);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  list-style: none;
}
.vp-ch {
  display: grid;
  grid-template-columns: 140px auto minmax(0, 1fr);
  align-items: center;
  gap: var(--s-4);
  min-height: 60px;
  padding: var(--s-3) 0;
}
.vp-ch + .vp-ch {
  border-top: 1px solid var(--line);
}
.vp-ch__name {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.vp-ch__name > svg {
  flex: none;
  color: var(--text-3);
}
.vp-ch__now {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s-1_5);
  min-width: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-align: end;
}
@media (max-width: 767.98px) {
  .vp-channels {
    padding: 0 var(--s-4);
  }
  .vp-ch {
    grid-template-columns: minmax(0, 1fr) auto;
    row-gap: var(--s-2);
    padding: var(--s-4) 0;
  }
  .vp-ch__seg {
    grid-column: 1 / -1;
    grid-row: 2;
  }
}

/* ---- alohida ruxsat jadvali ---- */
/* `clip` - `hidden` emas: yopishqoq sarlavha ishlashda davom etadi. */
.vp-table {
  overflow: clip;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
.vp-chips,
.vp-acts {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  vertical-align: middle;
}
.vp-chips :deep(.v-badge) {
  font-family: var(--font-mono);
}
.vp-default {
  color: var(--text-2);
}
.vp-note {
  display: block;
  overflow: hidden;
  color: var(--text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vp-none {
  color: var(--text-4);
}
.vp-changed {
  display: inline-flex;
  flex-direction: column;
  min-width: 0;
  color: var(--text-2);
}
.vp-changed__by {
  overflow: hidden;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vp-err {
  display: flex;
  align-items: flex-start;
  gap: var(--s-1_5);
  color: var(--crit-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.vp-err > svg {
  flex: none;
  margin-top: 1px;
}

@media (max-width: 767.98px) {
  .vp-card {
    padding: var(--s-5);
  }
  /* Ustma-ust kartalarda tekislashning keragi yo'q - bo'sh joy qoldirilmaydi. */
  .vp-card__caps.is-empty {
    display: none;
  }
  .vp-card__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    row-gap: var(--s-3);
  }
}
</style>
