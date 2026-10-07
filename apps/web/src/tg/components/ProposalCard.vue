<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, CircleAlert, PenLine, SquareKanban, TriangleAlert, Users, X } from 'lucide-vue-next'
import { cancelAction, confirmAction, isExpiredError, targetLabel } from '../../api/actions.api'
import { localizeApiError } from '../../api/errors'
import type { ActionProposal, ActionResult } from '../../types'
import { uzApostrophes } from '../chat/polish'
import { haptic } from '../telegram'

/**
 * Yordamchi TAKLIF qilgan yozuv amali (masalan CRM vazifasiga vaqt yozish). HECH
 * NARSA O'ZGARMAGAN: o'zgarish faqat "Tasdiqlash" bosilganda.
 *
 * Mantiq web'dagi `ActionCard.vue` bilan bir xil (holatlar, muddat, natija); farqi -
 * telefon uchun: to'liq kenglikdagi karta, ikki KATTA tugma (48px, teng kenglikda,
 * bosh barmoq ostida) va tebranish - tasdiq muvaffaqiyatli bo'lsa "success", yiqilsa
 * "error" (bosishning o'zida tebranish YO'Q - natija tebranishi yetarli). Natija
 * kelgach tugmalar yo'qoladi, holat belgisi qoladi.
 *
 * Karta ichida karta yo'q: o'zgarishlar jadvali fonsiz, faqat ingichka chiziqlar.
 * Belgi (32px) tizim nomi qatorida; qolgan vaqt - sarlavhadagi kichik pill ("15 daq"),
 * izoh matniga yopishib ikkinchi qatorga tushmaydi.
 */
const props = defineProps<{ proposal: ActionProposal }>()
const { t, locale } = useI18n({ useScope: 'global' })
/** Xizmat matni o'zbek lotinida - interfeys tutuq belgilari bilan (polish.ts). */
const fix = (s: string) => (String(locale.value) === 'uz' ? uzApostrophes(s) : s)

const result = ref<ActionResult | null>(null)
const busy = ref<'confirm' | 'cancel' | null>(null)
const error = ref('')

const ICONS: Record<string, Component> = { crm: SquareKanban, hrm: Users }
const icon = computed(() => ICONS[String(props.proposal.connector || '').toLowerCase()] ?? PenLine)
const platform = computed(() => (props.proposal.connector || '').toUpperCase())

// Muddati o'tgan taklif ham yakuniy (web `ActionCard` bilan bir xil): server baribir
// rad etadi (410) - tugmani bosib xato o'qish shart emas.
const settled = computed(() => {
  const s = result.value?.status
  return s === 'executed' || s === 'cancelled' || s === 'expired' || s === 'failed' || (!result.value && timedOut.value)
})

type Tone = 'good' | 'neutral' | 'warn' | 'crit'
const outcome = computed<{ tone: Tone; label: string } | null>(() => {
  const r = result.value
  if (!r) return timedOut.value ? { tone: 'warn', label: t('actionExpired') } : null
  if (r.status === 'executed' && r.ok !== false) return { tone: 'good', label: t('actionDone') }
  if (r.status === 'cancelled') return { tone: 'neutral', label: t('actionCancelled') }
  if (r.status === 'expired') return { tone: 'warn', label: t('actionExpired') }
  if (r.status === 'pending') return null
  return { tone: 'crit', label: t('actionFailed') }
})

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
    return name != null ? fix(String(name)) : JSON.stringify(value)
  }
  return fix(String(value))
}
const target = computed(() => fix(targetLabel(props.proposal.target)))
const changes = computed(() => (props.proposal.changes ?? []).filter((c) => c && (c.field || c.to !== undefined)))
function hasFrom(from: unknown): boolean {
  return from !== undefined && from !== null && from !== ''
}

// Muddat: har 15 s yangilanadi, karta yakunlangach to'xtaydi.
const expiresAt = computed(() => {
  const ms = props.proposal.expires_at ? Date.parse(props.proposal.expires_at) : NaN
  return Number.isFinite(ms) ? ms : null
})
const now = ref(Date.now())
// Muddat telefon soatida o'tdi (har 15 s tekshiriladi) - `settled` va `outcome` shunga qaraydi.
const timedOut = computed(() => expiresAt.value !== null && now.value >= expiresAt.value)
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
  if (left <= 0) return ''
  if (left < 60_000) return t('tg.proposal.underMinute')
  return t('tg.proposal.minutes', { n: Math.ceil(left / 60_000) })
})

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
    const tone = outcome.value?.tone
    if (kind === 'confirm') haptic.notify(tone === 'good' ? 'success' : tone === 'crit' ? 'error' : 'warning')
  } catch (err) {
    // Muddati o'tgan (404/410) - xato emas, taklifning holati: "Muddati tugagan".
    if (isExpiredError(err)) {
      result.value = { token: props.proposal.token, status: 'expired' }
      haptic.notify('warning')
    } else {
      error.value = localizeApiError(err, t)
      haptic.notify('error')
    }
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <section class="prop" :class="outcome ? `is-${outcome.tone}` : ''" :aria-label="t('actionProposed')">
    <header class="prop__head">
      <div class="prop__meta">
        <span class="prop__glyph" aria-hidden="true"><component :is="icon" :size="16" :stroke-width="1.75" /></span>
        <p class="prop__eyebrow">{{ [platform, t('actionProposed')].filter(Boolean).join(' · ') }}</p>
        <span v-if="!settled && expiryText" class="prop__pill">{{ expiryText }}</span>
      </div>
      <h3 class="prop__title">{{ proposal.summary ? fix(proposal.summary) : t('actionProposed') }}</h3>
    </header>

    <dl v-if="target || changes.length" class="prop__rows">
      <div v-if="target" class="prop__row">
        <dt>{{ t('actionTarget') }}</dt>
        <dd>{{ target }}</dd>
      </div>
      <div v-for="(c, i) in changes" :key="i" class="prop__row">
        <dt>{{ c.field ? fix(c.field) : t('actionChanges') }}</dt>
        <dd>
          <template v-if="hasFrom(c.from)">
            <s class="prop__from">{{ text(c.from) }}</s>
            <span aria-hidden="true"> → </span>
          </template>
          <b>{{ text(c.to) }}</b>
        </dd>
      </div>
    </dl>

    <div v-if="proposal.warnings?.length" class="prop__warn">
      <TriangleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
      <ul>
        <li v-for="(w, i) in proposal.warnings" :key="i">{{ w }}</li>
      </ul>
    </div>

    <p v-if="error" class="prop__bad" role="alert">
      <CircleAlert :size="16" :stroke-width="2" aria-hidden="true" />
      {{ error }}
    </p>
    <p v-if="result && outcome?.tone === 'crit'" class="prop__bad" role="alert">
      <CircleAlert :size="16" :stroke-width="2" aria-hidden="true" />
      {{ result.error || t('actionFailedGeneric') }}
    </p>

    <div v-if="outcome" class="prop__outcome">
      <span class="prop__dot" aria-hidden="true">
        <Check v-if="outcome.tone === 'good'" :size="14" :stroke-width="2.5" />
        <X v-else :size="14" :stroke-width="2.5" />
      </span>
      <span>{{ outcome.label }}</span>
      <span v-if="outcome.tone === 'good' && resultText" class="prop__key">{{ resultText }}</span>
    </div>

    <template v-if="!settled">
      <p class="prop__hint">{{ t('composer.actionSafe') }}</p>
      <div class="prop__buttons">
        <button type="button" class="prop__btn" :disabled="!!busy" :aria-busy="busy === 'cancel' ? 'true' : undefined" @click="run('cancel')">
          {{ busy === 'cancel' ? t('actionRejecting') : t('actionReject') }}
        </button>
        <button
          type="button"
          class="prop__btn prop__btn--primary"
          :disabled="!!busy"
          :aria-busy="busy === 'confirm' ? 'true' : undefined"
          @click="run('confirm')"
        >
          <span v-if="busy === 'confirm'" class="prop__spinner" aria-hidden="true" />
          {{ busy === 'confirm' ? t('actionWorking') : t('actionConfirm') }}
        </button>
      </div>
    </template>
    <p class="sr-only" aria-live="polite">{{ live }}</p>
  </section>
</template>

<style scoped>
.prop {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin: var(--s-3) 0 var(--s-1);
  padding: var(--s-4);
  border: 1px solid var(--line-strong);
  border-radius: 20px;
  background: var(--surface);
  box-shadow: var(--e2);
  transition: border-color var(--dur-3) var(--ease-out);
}
.prop.is-good {
  border-color: color-mix(in srgb, var(--good) 40%, var(--line));
}
.prop__head {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.prop__meta {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}
.prop__glyph {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--fill);
  color: var(--text-2);
}
.prop__eyebrow {
  flex: 1;
  min-width: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  letter-spacing: 0.01em;
}
.prop__pill {
  flex-shrink: 0;
  padding: 3px var(--s-2);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.prop__title {
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body);
  font-weight: 600;
  text-wrap: pretty;
}
.prop__rows {
  display: flex;
  flex-direction: column;
  margin: 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.prop__row {
  display: flex;
  justify-content: space-between;
  gap: var(--s-3);
  padding: 10px 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.prop__row + .prop__row {
  border-top: 1px solid var(--line);
}
.prop__row dt {
  color: var(--text-3);
}
.prop__row dd {
  margin: 0;
  min-width: 0;
  text-align: right;
  overflow-wrap: anywhere;
}
.prop__row b {
  font-weight: 600;
}
.prop__from {
  color: var(--text-3);
}
.prop__warn {
  display: flex;
  gap: var(--s-2);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.prop__warn svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.prop__warn ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
.prop__bad {
  display: flex;
  gap: var(--s-2);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.prop__bad svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.prop__outcome {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
.prop__dot {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.is-good .prop__dot {
  background: var(--good-soft);
  color: var(--good-text);
}
.is-crit .prop__dot {
  background: var(--crit-soft);
  color: var(--crit-text);
}
.is-warn .prop__dot {
  background: var(--warn-soft);
  color: var(--warn-text);
}
.prop__key {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  color: var(--text-2);
}
.prop__hint {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.prop__buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-2);
}
.prop__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  min-height: 48px;
  padding: 0 var(--s-3);
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body);
  font-weight: 600;
  transition: transform var(--dur-1) var(--ease-out);
}
.prop__btn:active:not(:disabled) {
  transform: scale(0.97);
}
.prop__btn:disabled {
  opacity: 0.6;
}
.prop__btn--primary {
  border-color: transparent;
  background: var(--ink);
  color: var(--on-ink);
}
.prop__btn--primary:disabled {
  opacity: 0.85;
}
.prop__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid color-mix(in srgb, var(--on-ink) 35%, transparent);
  border-top-color: var(--on-ink);
  border-radius: var(--r-full);
  animation: prop-spin 0.8s linear infinite;
}
@keyframes prop-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
