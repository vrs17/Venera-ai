<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { Check, PenLine, SquareKanban, TriangleAlert, Users } from 'lucide-vue-next'
import { cancelAction, confirmAction } from '../api/actions.api'
import { localizeApiError } from '../api/errors'
import type { ActionProposal, ActionResult } from '../types'
import VBadge from '../ui/VBadge.vue'
import VButton from '../ui/VButton.vue'
import VCard from '../ui/VCard.vue'

/**
 * Yordamchi TAKLIF qilgan yozuv amali (masalan CRM da vaqt yozish).
 *
 * HECH NARSA O'ZGARMAGAN: chat turi faqat taklif qiladi, va o'zgarish faqat
 * shu yerda "Tasdiqlash" bosilganda bo'ladi. Karta nima o'zgarishini
 * ko'rsatadi (xulosa, obyekt, maydonlar: eski -> yangi, ogohlantirishlar)
 * va ikki tugma beradi. Rad etish tasdiqsiz: u xavfsiz, hech narsa qilmaydi.
 *
 * Holat shu komponentda: karta taklif kaliti bo'yicha kalitlangan
 * (`:key`), ya'ni javob qayta chizilsa ham natija yo'qolmaydi; qayta
 * yaratilsa (regenerate) taklif ham yangi bo'ladi.
 */
const props = defineProps<{ proposal: ActionProposal }>()
const { t } = useI18n({ useScope: 'global' })

const result = ref<ActionResult | null>(null)
const busy = ref<'confirm' | 'cancel' | null>(null)
const error = ref('')

const ICONS: Record<string, Component> = { crm: SquareKanban, hrm: Users }
const icon = computed(() => ICONS[String(props.proposal.connector || '').toLowerCase()] ?? PenLine)
const platform = computed(() => (props.proposal.connector || '').toUpperCase())

/** Yakuniy holat: tugmalar yo'qoladi, natija qoladi. */
const settled = computed(() => {
  const s = result.value?.status
  return s === 'executed' || s === 'cancelled' || s === 'expired' || s === 'failed'
})

type Tone = 'good' | 'neutral' | 'warn' | 'crit'
const outcome = computed<{ tone: Tone; label: string } | null>(() => {
  const r = result.value
  if (!r) return null
  // ok === false - platforma "bajarildi" desa ham natija yo'q: bu muvaffaqiyatsizlik.
  if (r.status === 'executed' && r.ok !== false) return { tone: 'good', label: t('actionDone') }
  if (r.status === 'cancelled') return { tone: 'neutral', label: t('actionCancelled') }
  if (r.status === 'expired') return { tone: 'warn', label: t('actionExpired') }
  if (r.status === 'pending') return null
  return { tone: 'crit', label: t('actionFailed') }
})

/** Platforma qaytargan ko'rsatkich, masalan yaratilgan vazifa kaliti. */
const resultText = computed(() => {
  const r = result.value?.result
  if (!r) return ''
  const key = r.key ?? r.id ?? r.number
  return key != null ? String(key) : ''
})

function text(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') {
    const o = value as Record<string, unknown>
    const name = o.title ?? o.name ?? o.key ?? o.id
    return name != null ? String(name) : JSON.stringify(value)
  }
  return String(value)
}
const target = computed(() => (props.proposal.target ? text(props.proposal.target) : ''))
const changes = computed(() => (props.proposal.changes ?? []).filter((c) => c && (c.field || c.to !== undefined)))
function hasFrom(from: unknown): boolean {
  return from !== undefined && from !== null && from !== ''
}

/* ---- muddat: `expires_at` bo'lsa - qancha qolgani, har 15 s yangilanadi ---- */
const expiresAt = computed(() => {
  const ms = props.proposal.expires_at ? Date.parse(props.proposal.expires_at) : NaN
  return Number.isFinite(ms) ? ms : null
})
const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | undefined
watch(
  () => expiresAt.value !== null && !settled.value,
  (live) => {
    clearInterval(tick)
    tick = live ? setInterval(() => (now.value = Date.now()), 15_000) : undefined
  },
  { immediate: true },
)
onBeforeUnmount(() => clearInterval(tick))

const expiryText = computed(() => {
  if (expiresAt.value === null) return ''
  const left = expiresAt.value - now.value
  // Muddat o'tdi - holatni server aytadi (tugma bosilsa "Muddati tugagan" keladi).
  if (left <= 0) return t('actionExpired')
  if (left < 60_000) return t('composer.underMinute')
  return t('composer.minutesLeft', { n: Math.ceil(left / 60_000) })
})

/** Ekran o'quvchi uchun: holat o'zgarishi e'lon qilinadi (tugma yo'qolganda jim qolmasin). */
const live = computed(() => {
  if (busy.value === 'confirm') return t('actionWorking')
  if (busy.value === 'cancel') return t('actionRejecting')
  return outcome.value?.label ?? ''
})

async function run(kind: 'confirm' | 'cancel') {
  if (busy.value || settled.value) return
  busy.value = kind
  error.value = ''
  try {
    result.value = await (kind === 'confirm' ? confirmAction : cancelAction)(props.proposal.token)
  } catch (err) {
    error.value = localizeApiError(err, t)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <VCard as="section" padding="md" class="act" :aria-label="t('actionProposed')">
    <header class="act__head">
      <span class="act__glyph" aria-hidden="true"><component :is="icon" :size="16" :stroke-width="1.75" /></span>
      <div class="act__titles">
        <!-- Sarlavha - xulosaning o'zi (asl mazmun); "Taklif qilingan o'zgarish" - uning
             ustidagi jim yorliq. Yakuniy holat nishoni shu qatorda: sarlavha tor ekranda
             ham butun kenglikni oladi. -->
        <div v-if="proposal.summary || platform || outcome" class="act__top">
          <p class="act__eyebrow">
            {{ proposal.summary ? [platform, t('actionProposed')].filter(Boolean).join(' · ') : platform }}
          </p>
          <VBadge v-if="outcome" class="act__badge" :tone="outcome.tone" :icon="outcome.tone === 'good' ? Check : undefined">
            {{ outcome.label }}
          </VBadge>
        </div>
        <h3 class="act__title">{{ proposal.summary || t('actionProposed') }}</h3>
      </div>
    </header>

    <dl v-if="target || changes.length" class="act__rows">
      <div v-if="target" class="act__row">
        <dt>{{ t('actionTarget') }}</dt>
        <dd>{{ target }}</dd>
      </div>
      <div v-for="(c, i) in changes" :key="i" class="act__row">
        <dt>{{ c.field || t('actionChanges') }}</dt>
        <dd>
          <template v-if="hasFrom(c.from)">
            <s class="act__from">{{ text(c.from) }}</s>
            <span class="act__arrow" aria-hidden="true">→</span>
          </template>
          <span class="act__to">{{ text(c.to) }}</span>
        </dd>
      </div>
    </dl>

    <div v-if="proposal.warnings?.length" class="act__warn">
      <TriangleAlert class="act__warn-icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
      <ul>
        <li v-for="(w, i) in proposal.warnings" :key="i">{{ w }}</li>
      </ul>
    </div>

    <!-- Natija: bajarilgan bo'lsa platforma nima qaytargani, yiqilgan bo'lsa sababi. -->
    <p v-if="result && outcome?.tone === 'good' && resultText" class="act__result">{{ resultText }}</p>
    <p v-if="result && outcome?.tone === 'crit'" class="act__bad" role="alert">
      {{ result.error || t('actionFailedGeneric') }}
    </p>
    <p v-if="error" class="act__bad" role="alert">{{ error }}</p>

    <footer v-if="!settled" class="act__foot">
      <p class="act__hint">
        {{ t('composer.actionSafe') }}<template v-if="expiryText"> · <span class="act__expiry">{{ expiryText }}</span></template>
      </p>
      <div class="act__buttons">
        <VButton variant="ghost" size="sm" :loading="busy === 'cancel'" :disabled="busy === 'confirm'" @click="run('cancel')">
          {{ t('actionReject') }}
        </VButton>
        <VButton variant="primary" size="sm" :loading="busy === 'confirm'" :disabled="busy === 'cancel'" @click="run('confirm')">
          {{ t('actionConfirm') }}
        </VButton>
      </div>
    </footer>
    <p class="sr-only" aria-live="polite">{{ live }}</p>
  </VCard>
</template>

<style scoped>
.act {
  /* Qatorlar joylashuvi ekranga emas, KARTAning kengligiga qarab: hujjat paneli ochiq
     keng ekranda ham ustun tor bo'lishi mumkin. Karta blok element - kengligi ota
     ustundan keladi, shuning uchun inline-size cheklovi uni siqmaydi. */
  container: act / inline-size;
  gap: var(--s-4);
  margin: var(--s-3) 0 var(--s-1_5);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

.act__head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
}
.act__glyph {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.act__titles {
  flex: 1;
  min-width: 0;
  padding-top: 1px;
}
.act__eyebrow {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.act__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-2);
  margin-bottom: 2px;
}
.act__title {
  color: var(--text);
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
  overflow-wrap: anywhere;
}
.act__badge {
  flex-shrink: 0;
}

/* Tor kartada (telefon) yorliq qiymat ustida - uzun qiymat tor ustunga siqilmasin.
   Eslatma: oldingi `minmax(0, fit-content(40%))` yaroqsiz (fit-content() minmax ichida
   ruxsat etilmaydi) - brauzer butun qoidani tashlab, qatorlar doim ustma-ust turardi. */
.act__rows {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  row-gap: 2px;
}
.act__row {
  display: contents;
}
.act__row + .act__row dt {
  margin-top: var(--s-2);
}
.act__row dt {
  color: var(--text-3);
  overflow-wrap: break-word;
}
.act__row dd {
  color: var(--text);
  overflow-wrap: anywhere;
}
/* >= 560px karta: ikki ustun - chapda ~160px yorliq, o'ngda qiymat, qatorlar orasi 8px.
   Hamma qiymat bitta chiziqdan boshlanadi, karta balandligi ~ikki baravar kamayadi. */
@container act (min-width: 560px) {
  .act__rows {
    grid-template-columns: 160px minmax(0, 1fr);
    gap: var(--s-2) var(--s-4);
  }
  .act__row + .act__row dt {
    margin-top: 0;
  }
}
.act__from {
  color: var(--text-3);
  text-decoration-color: var(--text-4);
}
.act__arrow {
  margin: 0 var(--s-1_5);
  color: var(--text-4);
}
.act__to {
  font-weight: 500;
}

.act__warn {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  padding: var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
}
.act__warn-icon {
  flex-shrink: 0;
  margin-top: 2px;
}
.act__warn ul {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.act__result {
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
}
.act__bad {
  color: var(--crit-text);
}

.act__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s-3);
}
.act__hint {
  flex: 1 1 200px;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.act__expiry {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.act__buttons {
  display: flex;
  gap: var(--s-2);
  margin-left: auto;
}
</style>
