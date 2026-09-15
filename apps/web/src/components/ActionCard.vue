<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FunctionalComponent } from 'vue'
import { cancelAction, confirmAction } from '../api/actions.api'
import { localizeApiError } from '../api/errors'
import type { ActionProposal, ActionResult } from '../types'
import { BoardIcon, CheckIcon, PencilIcon, UsersIcon } from '../icons'

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

const ICONS: Record<string, FunctionalComponent<{ size?: number }>> = { crm: BoardIcon, hrm: UsersIcon }
const icon = computed(() => ICONS[String(props.proposal.connector || '').toLowerCase()] ?? PencilIcon)
const platform = computed(() => (props.proposal.connector || '').toUpperCase())

/** Yakuniy holat: tugmalar yo'qoladi, natija qoladi. */
const settled = computed(() => {
  const s = result.value?.status
  return s === 'executed' || s === 'cancelled' || s === 'expired' || s === 'failed'
})

const outcome = computed(() => {
  const r = result.value
  if (!r) return null
  if (r.status === 'executed' && r.ok !== false) return { tone: 'ok', label: t('actionDone') }
  if (r.status === 'cancelled') return { tone: 'muted', label: t('actionCancelled') }
  if (r.status === 'expired') return { tone: 'warn', label: t('actionExpired') }
  if (r.status === 'pending') return null
  return { tone: 'bad', label: t('actionFailed') }
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
  <section class="act" :class="outcome ? `is-${outcome.tone}` : ''" :aria-label="t('actionProposed')">
    <header class="act__head">
      <span class="act__icon" aria-hidden="true"><component :is="icon" :size="15" stroke="currentColor" /></span>
      <span class="act__title">{{ t('actionProposed') }}</span>
      <span v-if="platform" class="act__platform">{{ platform }}</span>
      <span v-if="outcome" class="act__status" :class="`is-${outcome.tone}`">
        <CheckIcon v-if="outcome.tone === 'ok'" :size="12" stroke="currentColor" />
        {{ outcome.label }}
      </span>
    </header>

    <p v-if="proposal.summary" class="act__summary">{{ proposal.summary }}</p>

    <dl v-if="target || changes.length" class="act__details">
      <template v-if="target">
        <dt>{{ t('actionTarget') }}</dt>
        <dd>{{ target }}</dd>
      </template>
      <template v-for="(c, i) in changes" :key="i">
        <dt>{{ c.field || t('actionChanges') }}</dt>
        <dd>
          <template v-if="c.from !== undefined && c.from !== null && c.from !== ''">
            <s class="act__from">{{ text(c.from) }}</s>
            <span class="act__arrow" aria-hidden="true">→</span>
          </template>
          <span class="act__to">{{ text(c.to) }}</span>
        </dd>
      </template>
    </dl>

    <ul v-if="proposal.warnings?.length" class="act__warnings">
      <li v-for="(w, i) in proposal.warnings" :key="i">{{ w }}</li>
    </ul>

    <!-- Natija: bajarilgan bo'lsa platforma nima qaytargani, yiqilgan
         bo'lsa sababi. -->
    <p v-if="result && outcome?.tone === 'ok' && resultText" class="act__result">{{ resultText }}</p>
    <p v-if="result && outcome?.tone === 'bad'" class="act__bad" role="alert">
      {{ result.error || t('actionFailedGeneric') }}
    </p>
    <p v-if="error" class="act__bad" role="alert">{{ error }}</p>

    <footer v-if="!settled" class="act__foot">
      <span class="act__hint">{{ t('actionHint') }}</span>
      <div class="act__buttons">
        <button type="button" class="act__btn act__btn--reject" :disabled="!!busy" @click="run('cancel')">
          {{ busy === 'cancel' ? t('actionRejecting') : t('actionReject') }}
        </button>
        <button type="button" class="act__btn act__btn--confirm" :disabled="!!busy" :aria-busy="busy === 'confirm'" @click="run('confirm')">
          {{ busy === 'confirm' ? t('actionWorking') : t('actionConfirm') }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.act {
  margin: 12px 0 6px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid var(--border-hover);
  background: var(--surface-sunken);
  font-size: 13.5px;
  line-height: 1.45;
  color: var(--text);
}
/* Yakuniy holat rang bilan: yashil - bajarildi, kulrang - rad etildi,
   sariq - muddati tugagan, qizil - yiqildi. */
.act.is-ok {
  border-color: var(--ok-bd);
}
.act.is-bad {
  border-color: var(--bad-bd);
}
.act.is-warn {
  border-color: var(--warn-bd);
}
.act__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.act__icon {
  display: inline-flex;
  color: var(--text-secondary);
}
.act__title {
  font-weight: 600;
}
.act__platform {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 7px;
}
.act__status {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 999px;
  padding: 2px 9px;
}
.act__status.is-ok {
  color: var(--ok-fg);
  background: var(--ok-bg);
  border: 1px solid var(--ok-bd);
}
.act__status.is-bad {
  color: var(--bad-fg);
  background: var(--bad-bg);
  border: 1px solid var(--bad-bd);
}
.act__status.is-warn {
  color: var(--warn-fg);
  background: var(--warn-bg);
  border: 1px solid var(--warn-bd);
}
.act__status.is-muted {
  color: var(--text-secondary);
  background: var(--surface-hover);
  border: 1px solid var(--border);
}
.act__summary {
  margin: 0 0 8px;
}
.act__details {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 3px 12px;
  margin: 0 0 8px;
  font-size: 13px;
}
.act__details dt {
  color: var(--text-secondary);
}
.act__details dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.act__from {
  color: var(--text-muted);
}
.act__arrow {
  margin: 0 6px;
  color: var(--text-muted);
}
.act__to {
  font-weight: 600;
}
.act__warnings {
  margin: 0 0 8px;
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--warn-fg);
}
.act__result {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.act__bad {
  margin: 0 0 8px;
  font-size: 12.5px;
  color: var(--bad-fg);
}
.act__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.act__hint {
  font-size: 11.5px;
  color: var(--text-muted);
  flex: 1;
  min-width: 160px;
}
.act__buttons {
  display: flex;
  gap: 8px;
}
.act__btn {
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid var(--border-hover);
  background: transparent;
  font-family: 'Figtree', sans-serif;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s, filter 0.15s;
}
.act__btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.act__btn--reject {
  color: var(--text-secondary);
}
.act__btn--reject:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text);
}
/* Tasdiqlash - to'ldirilgan: bu javobning yagona haqiqiy "qil" tugmasi. */
.act__btn--confirm {
  background: var(--ink);
  border-color: transparent;
  color: var(--ink-contrast);
}
.act__btn--confirm:hover:not(:disabled) {
  filter: brightness(1.1);
}
</style>
