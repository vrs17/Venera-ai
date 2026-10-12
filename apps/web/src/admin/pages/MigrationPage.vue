<script setup lang="ts">
import { computed, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, RefreshCw } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VDialog from '../../ui/VDialog.vue'
import VSegmented from '../../ui/VSegmented.vue'
import type { SegmentedOption } from '../../ui/VSegmented.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import { fmtMs, fmtNumber, fmtPercent } from '../../ui/format'
import { useToast } from '../../ui/useToast'
import { useIsPhone } from '../../ui/composables/useMediaQuery'
import { getBrain, getBrainShadow, putBrain } from '../api'
import type { AdminBrain, BrainFeatureRow, BrainShadow, BrainShadowStats, BrainState } from '../types'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import { useAdminQuery } from '../components/useAdminQuery'
import { userActionError } from '../users/userErrors'

// "AI ko'chirish": Barno serveridagi har bir "aqlli" ish (xulosa, brif, CRM so'rovi...) qayerda
// bajarilishi - bizda (`local`), taqqoslashda (`shadow`: foydalanuvchi bizning javobni oladi,
// agent javobi fonda solishtiriladi) yoki agentda (`agent`, xatoda o'zi bizga qaytadi).
// Egasi qarorni pastdagi taqqoslash raqamlariga qarab beradi (migratsiya rejasi 7.2).
// Agent tayyor bo'lmasa (o'chiq, imkoniyati yo'q) flag saqlanadi, lekin ish bizda qoladi -
// "Hozir" belgisi va sababi shuni aytadi.

const { t, te, locale } = useI18n({ useScope: 'global' })
const tr = (key: string) => t(key)
const toast = useToast()
// Telefonda holat tanlovi to'liq enda - barmoq uchun katta nishon (Versiyalar sahifasidagidek).
const isPhone = useIsPhone()

const refreshCaps = ref(false)
const q = useAdminQuery((_p: null, signal: AbortSignal) => getBrain(refreshCaps.value, signal), { params: null })
const data = computed<AdminBrain | null>(() => q.data.value)
const sq = useAdminQuery((_p: null, signal: AbortSignal) => getBrainShadow(7, signal), { params: null })
const shadow = computed<BrainShadow | null>(() => sq.data.value)

function refreshAll() {
  refreshCaps.value = true
  q.refresh()
  sq.refresh()
}

/* ---------------------------------------------------------------- agent holati */

const agent = computed(() => data.value?.agent ?? {})
// `capabilities` - kesh holati: `{value: {contract, inNetwork, externalAllowed, ...} | null, error, ...}`.
const caps = computed(
  () => ((agent.value.capabilities as { value?: Record<string, unknown> | null } | undefined)?.value ?? {}) as Record<string, unknown>,
)
const agentTone = computed<'good' | 'warn' | 'neutral'>(() =>
  agent.value.usable ? 'good' : agent.value.enabled ? 'warn' : 'neutral',
)
const agentStatus = computed(() =>
  agent.value.usable ? t('admin.migration.agentOn') : agent.value.enabled ? t('admin.migration.agentNotReady') : t('admin.migration.agentOff'),
)
const circuitOpen = computed(() => (agent.value.circuit as { open?: boolean } | undefined)?.open === true)

/* ---------------------------------------------------------------- funksiyalar */

const stateOptions = computed<SegmentedOption<BrainState>[]>(() => [
  { value: 'local', label: t('admin.migration.state.local') },
  { value: 'shadow', label: t('admin.migration.state.shadow') },
  { value: 'agent', label: t('admin.migration.state.agent') },
])

function featureName(f: BrainFeatureRow): string {
  const key = `admin.migration.feature.${f.feature}`
  return te(key) ? t(key) : f.label || f.feature
}

function featureHint(f: BrainFeatureRow): string {
  const key = `admin.migration.hint.${f.feature}`
  return te(key) ? t(key) : ''
}

/** Sabab kodi -> odam tushunadigan matn (`capability_missing:a,b` - agentda yetishmaydi). */
function reasonText(reason: string | null): string {
  if (!reason) return ''
  // `capability_missing:job_kinds:meeting_summary` - kod birinchi `:` gacha, qolgani butunligicha.
  const cut = reason.indexOf(':')
  const code = cut < 0 ? reason : reason.slice(0, cut)
  const detail = cut < 0 ? '' : reason.slice(cut + 1)
  const key = `admin.migration.reason.${code}`
  const base = te(key) ? t(key) : code
  return detail ? `${base}: ${detail}` : base
}

function stats(feature: string): BrainShadowStats | null {
  return shadow.value?.features?.[feature] ?? null
}

const num = (n: number | null | undefined) => fmtNumber(n ?? 0, locale.value)
const ms = (n: number | null | undefined) => fmtMs(n ?? null, locale.value)
const pct = (n: number | null | undefined) => (n == null ? '—' : fmtPercent(n, 0, locale.value))

/* ---------------------------------------------------------------- holatni o'zgartirish */

const pending = shallowRef<{ row: BrainFeatureRow; to: BrainState } | null>(null)
const confirmOpen = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

function ask(row: BrainFeatureRow, to: BrainState) {
  if (to === row.state) return
  pending.value = { row, to }
  error.value = null
  confirmOpen.value = true
}

const confirmTitle = computed(() =>
  pending.value ? t('admin.migration.confirmTitle', { name: featureName(pending.value.row), state: t(`admin.migration.state.${pending.value.to}`) }) : '',
)
const confirmBody = computed(() => (pending.value ? t(`admin.migration.confirmBody.${pending.value.to}`) : ''))

async function apply() {
  const p = pending.value
  if (!p || busy.value) return
  busy.value = true
  error.value = null
  try {
    q.data.value = await putBrain(p.row.feature, { state: p.to })
    confirmOpen.value = false
    toast.show({ message: t('admin.migration.saved', { name: featureName(p.row), state: t(`admin.migration.state.${p.to}`) }), tone: 'good' })
  } catch (err) {
    error.value = userActionError(err, tr)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="mg" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.migration.title')"
      :subtitle="t('admin.page.migration.subtitle')"
      :refreshing="q.loading.value || sq.loading.value"
      @refresh="refreshAll"
    />

    <AdminError v-if="q.error.value && !data" :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

    <div v-else-if="q.firstLoad.value" class="mg-list" aria-hidden="true">
      <div v-for="k in 4" :key="k" class="mg-row"><VSkeleton :lines="2" /></div>
    </div>

    <template v-else-if="data">
      <p class="mg-intro">{{ t('admin.migration.intro') }}</p>

      <!-- agent holati -->
      <article class="mg-agent" aria-labelledby="mg-agent-title">
        <header class="mg-agent__head">
          <h2 id="mg-agent-title" class="mg-agent__title">{{ t('admin.migration.agentTitle') }}</h2>
          <VBadge :tone="agentTone" size="sm" dot>{{ agentStatus }}</VBadge>
          <VBadge v-if="circuitOpen" tone="crit" size="sm">{{ t('admin.migration.circuit') }}</VBadge>
        </header>
        <p v-if="agent.reason" class="mg-muted">{{ reasonText(agent.reason ?? null) }}</p>
        <dl class="mg-facts">
          <div>
            <dt>{{ t('admin.migration.contract') }}</dt>
            <dd>{{ (caps.contract as string) || '—' }}</dd>
          </div>
          <div>
            <dt>{{ t('admin.migration.models') }}</dt>
            <dd>
              {{
                caps.inNetwork
                  ? t('admin.migration.modelsInNetwork')
                  : caps.externalAllowed
                    ? t('admin.migration.modelsExternal')
                    : '—'
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t('admin.migration.hold') }}</dt>
            <dd>{{ data.holdClassifier === 'keyword' ? t('admin.migration.holdKeyword') : t('admin.migration.holdLlm') }}</dd>
          </div>
        </dl>
        <VButton variant="ghost" size="sm" :icon="RefreshCw" :loading="q.loading.value" @click="refreshAll">
          {{ t('admin.migration.recheck') }}
        </VButton>
      </article>

      <!-- funksiyalar -->
      <ul class="mg-list" :class="{ 'is-busy': q.refetching.value }">
        <li v-for="f in data.features" :key="f.feature" class="mg-row">
          <div class="mg-row__main">
            <h3 class="mg-row__name">{{ featureName(f) }}</h3>
            <p v-if="featureHint(f)" class="mg-row__hint">{{ featureHint(f) }}</p>
            <p v-if="f.effective !== f.state" class="mg-row__now">
              <CircleAlert :size="13" :stroke-width="1.75" aria-hidden="true" />
              {{ t('admin.migration.now', { state: t(`admin.migration.state.${f.effective}`) }) }}
              <span v-if="f.reason" class="mg-muted">— {{ reasonText(f.reason) }}</span>
            </p>
            <dl v-if="stats(f.feature)" class="mg-stats">
              <div>
                <dt>{{ t('admin.migration.compared') }}</dt>
                <dd>{{ num(stats(f.feature)?.count) }}</dd>
              </div>
              <div>
                <dt>{{ t('admin.migration.similarity') }}</dt>
                <dd>{{ pct(stats(f.feature)?.similarityAvg) }}</dd>
              </div>
              <div>
                <dt>{{ t('admin.migration.speed') }}</dt>
                <dd>{{ ms(stats(f.feature)?.localP50) }} / {{ ms(stats(f.feature)?.agentP50) }}</dd>
              </div>
              <div>
                <dt>{{ t('admin.migration.failures') }}</dt>
                <dd :class="{ 'is-bad': (stats(f.feature)?.errors ?? 0) + (stats(f.feature)?.timeouts ?? 0) > 0 }">
                  {{ num((stats(f.feature)?.errors ?? 0) + (stats(f.feature)?.timeouts ?? 0)) }}
                </dd>
              </div>
            </dl>
            <p v-else-if="f.state === 'shadow'" class="mg-muted">{{ t('admin.migration.noShadowYet') }}</p>
          </div>
          <VSegmented
            class="mg-row__state"
            size="sm"
            :block="isPhone"
            :options="stateOptions"
            :model-value="f.state"
            :aria-label="featureName(f)"
            @update:model-value="(v: BrainState) => ask(f, v)"
          />
        </li>
      </ul>
      <p class="mg-muted mg-legend">{{ t('admin.migration.legend') }}</p>
    </template>

    <VDialog v-model:open="confirmOpen" alert :title="confirmTitle" :description="confirmBody" :dismissible="!busy">
      <p v-if="error" class="mg-err" role="alert">
        <CircleAlert :size="14" :stroke-width="1.75" aria-hidden="true" />
        {{ error }}
      </p>
      <template #footer="{ close }">
        <VButton variant="ghost" :disabled="busy" @click="close">{{ t('ui.cancel') }}</VButton>
        <VButton variant="primary" :loading="busy" @click="apply">{{ t('admin.migration.apply') }}</VButton>
      </template>
    </VDialog>
  </section>
</template>

<style scoped>
.mg {
  display: grid;
  gap: 16px;
}
.mg-intro {
  margin: 0;
  max-width: 72ch;
  color: var(--ink-2);
  font-size: 14px;
  line-height: 1.55;
}
.mg-muted {
  margin: 0;
  color: var(--ink-3);
  font-size: 13px;
}
.mg-agent {
  display: grid;
  gap: 10px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface);
  justify-items: start;
}
.mg-agent__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.mg-agent__title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.mg-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 28px;
  margin: 0;
}
.mg-facts dt,
.mg-stats dt {
  color: var(--ink-3);
  font-size: 12px;
}
.mg-facts dd,
.mg-stats dd {
  margin: 2px 0 0;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.mg-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  transition: opacity 0.15s;
}
.mg-list.is-busy {
  opacity: 0.5;
}
.mg-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 20px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}
.mg-row__main {
  display: grid;
  gap: 4px;
  min-width: 0;
  flex: 1 1 320px;
}
.mg-row__name {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.mg-row__hint {
  margin: 0;
  color: var(--ink-2);
  font-size: 13px;
}
.mg-row__now {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin: 2px 0 0;
  color: var(--warn-text);
  font-size: 13px;
}
.mg-row__state {
  flex: 0 0 auto;
}
.mg-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 22px;
  margin: 6px 0 0;
}
.mg-stats dd.is-bad {
  color: var(--crit-text);
}
.mg-legend {
  max-width: 72ch;
}
.mg-err {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--crit-text);
  font-size: 13px;
}
@media (max-width: 560px) {
  .mg-row__state {
    width: 100%;
  }
}
</style>
