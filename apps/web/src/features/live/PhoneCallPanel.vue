<script setup lang="ts">
/**
 * Telefon raqamiga qo'ng'iroq - `/barno` bosh sahifasida (brauzerda). Kimga ko'rinishini SERVER aytadi
 * (`status.allowed`: ADMIN roli yoki `TELEPHONY_LOGINS`); javob kelguncha va ruxsat bo'lmasa panel chizilmaydi.
 *
 * Barno raqamga bankning telefon tizimi (FreePBX) orqali qo'ng'iroq qiladi (`api/telephony.api.ts`). Raqam
 * yuborilgach holat so'rab turiladi: avval har 3 s, 2 daqiqadan keyin har 10 s, ko'pi bilan 15 daqiqa - FreePBX
 * natijasi (javob bermadi / band / gaplashdi...) kelguncha. Har qo'ng'iroq - haqiqiy odamga haqiqiy qo'ng'iroq va
 * pullik daqiqalar, shuning uchun bosishdan oldin tasdiq so'raladi.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Phone } from 'lucide-vue-next'
import VButton from '../../ui/VButton.vue'
import VInput from '../../ui/VInput.vue'
import VSpinner from '../../ui/VSpinner.vue'
import { ApiError } from '../../api/http'
import { getPhoneCall, placePhoneCall, recentPhoneCalls, telephonyStatus } from '../../api/telephony.api'
import type { PhoneCall, TelephonyStatus } from '../../api/telephony.api'

const { t } = useI18n({ useScope: 'global' })

type Tone = 'progress' | 'good' | 'warn' | 'bad' | 'neutral'
const FINAL = new Set(['failed', 'completed', 'rejected'])
const FAST_MS = 3_000
const SLOW_MS = 10_000
const FAST_FOR_MS = 120_000
const POLL_FOR_MS = 15 * 60_000

const status = ref<TelephonyStatus | null>(null)
const digits = ref('')
const touched = ref(false)
const sending = ref(false)
const current = ref<PhoneCall | null>(null)
const errorText = ref('')
const recent = ref<PhoneCall[]>([])
let timer: ReturnType<typeof setTimeout> | undefined
let pollStarted = 0
let alive = true

const valid = computed(() => /^[1-9][0-9]{8}$/.test(digits.value))
const ready = computed(() => Boolean(status.value?.enabled && status.value?.configured))
const inProgress = computed(() => Boolean(current.value && !FINAL.has(current.value.status) && current.value.status !== 'unknown'))
const offText = computed(() => {
  if (!status.value) return ''
  if (!status.value.enabled) return t('live.phone.off')
  if (!status.value.configured) return t('live.phone.notConfigured')
  return ''
})
const inputError = computed(() => (touched.value && digits.value && !valid.value ? t('live.phone.invalid') : null))

/** `901234567` -> `90 123 45 67`. */
function format(d: string): string {
  return [d.slice(0, 2), d.slice(2, 5), d.slice(5, 7), d.slice(7, 9)].filter(Boolean).join(' ')
}

/** Ko'rinadigan qiymat formatlangan; ichkarida faqat 9 raqam (+998 bilan yopishtirilsa ham). */
const display = computed({
  get: () => format(digits.value),
  set: (value: string | number | null) => {
    let d = String(value ?? '').replace(/\D/g, '')
    if (d.length > 9 && d.startsWith('998')) d = d.slice(3)
    digits.value = d.slice(0, 9)
  },
})

function mmss(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function hhmm(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function reasonText(call: PhoneCall): string {
  const detail = call.detail || ''
  const known: Record<string, string> = {
    disabled: 'disabled', barno_max: 'barno_max', trunk: 'trunk', lock: 'lock', not_configured: 'unavailable',
    pbx_unavailable: 'unavailable', gateway_unavailable: 'unavailable', cert_mismatch: 'cert',
  }
  if (known[detail]) return t(`live.phone.reason.${known[detail]}`)
  if (detail.startsWith('connect_failed') || detail.startsWith('send_failed')) return t('live.phone.reason.connect')
  if (call.httpStatus === 422) return t('live.phone.reason.invalid')
  if (call.httpStatus === 409) return t('live.phone.reason.duplicate')
  return t('live.phone.reason.other', { code: call.httpStatus ?? '—' })
}

function describe(call: PhoneCall): { tone: Tone; text: string } {
  switch (call.status) {
    case 'placing':
      return { tone: 'progress', text: t('live.phone.status.placing') }
    case 'queued':
      return { tone: 'progress', text: t('live.phone.status.queued') }
    case 'rejected':
      return { tone: 'bad', text: t('live.phone.status.rejected', { reason: reasonText(call) }) }
    case 'unknown':
      return {
        tone: 'warn',
        // no_response - so'rov ketdi, javob kelmadi; retrying / retry_failed:* - xuddi shu call_id bilan bir marta
        // qayta yuborilmoqda yoki u ham javobsiz qoldi (server: `retry_unknown`).
        text: /^(no_response|retrying|retry_failed)/.test(call.detail)
          ? t('live.phone.status.unknownNoResponse')
          : t('live.phone.status.unknownNoResult'),
      }
    case 'failed':
      return { tone: 'bad', text: t(`live.phone.outcome.${call.outcome || 'failed'}`) }
    case 'completed':
      if (call.outcome === 'talked') return { tone: 'good', text: t('live.phone.outcome.talked', { time: mmss(call.talkSec ?? 0) }) }
      if (call.outcome === 'gateway_failed') return { tone: 'warn', text: t('live.phone.outcome.gateway_failed') }
      return { tone: 'neutral', text: t('live.phone.outcome.ended') }
    default:
      return { tone: 'neutral', text: call.status }
  }
}

const currentView = computed(() => (current.value ? describe(current.value) : null))
const cost = computed(() => {
  const value = current.value?.bridge?.costUsd
  return typeof value === 'number' ? t('live.phone.cost', { cost: value.toFixed(2) }) : ''
})

async function loadStatus() {
  try {
    status.value = await telephonyStatus()
  } catch {
    status.value = null
  }
}

async function loadRecent() {
  try {
    recent.value = await recentPhoneCalls(5)
  } catch {
    /* ro'yxat - qo'shimcha; xato bo'lsa eski ko'rinish qoladi */
  }
}

function stopPolling() {
  if (timer !== undefined) clearTimeout(timer)
  timer = undefined
}

function schedule() {
  const call = current.value
  const age = Date.now() - pollStarted
  if (!alive || !call || FINAL.has(call.status) || age > POLL_FOR_MS) {
    void loadRecent()
    void loadStatus()
    return
  }
  timer = setTimeout(async () => {
    try {
      current.value = await getPhoneCall(call.callId)
    } catch {
      /* keyingi urinishda */
    }
    schedule()
  }, age < FAST_FOR_MS ? FAST_MS : SLOW_MS)
}

async function placeCall() {
  touched.value = true
  if (!valid.value || sending.value || inProgress.value || !ready.value) return
  if (!window.confirm(t('live.phone.confirm', { phone: format(digits.value) }))) return
  sending.value = true
  errorText.value = ''
  current.value = null
  stopPolling()
  try {
    current.value = await placePhoneCall(digits.value)
    pollStarted = Date.now()
    schedule()
  } catch (e) {
    const code = e instanceof ApiError ? e.status : undefined
    if (code === 429) errorText.value = t('live.phone.errLimit')
    else if (code === 422) errorText.value = t('live.phone.invalid')
    else if (code === 503) {
      errorText.value = t('live.phone.errOff')
      void loadStatus()
    } else errorText.value = t('live.phone.errGeneric')
  } finally {
    sending.value = false
  }
  void loadRecent()
}

function newCall() {
  stopPolling()
  current.value = null
  errorText.value = ''
  digits.value = ''
  touched.value = false
}

onMounted(async () => {
  await loadStatus()
  if (status.value?.allowed) void loadRecent()
})
onBeforeUnmount(() => {
  alive = false
  stopPolling()
})
</script>

<template>
  <section v-if="status?.allowed" class="phone" aria-labelledby="phone-title">
    <header class="phone__head">
      <span class="phone__icon" aria-hidden="true"><Phone :size="18" :stroke-width="1.9" /></span>
      <div class="phone__heading">
        <h2 id="phone-title" class="phone__title">{{ t('live.phone.title') }}</h2>
        <p class="phone__sub">{{ t('live.phone.sub') }}</p>
      </div>
      <span class="phone__badge">{{ t('live.phone.badge') }}</span>
    </header>

    <p v-if="offText" class="phone__off">{{ offText }}</p>

    <form class="phone__form" novalidate @submit.prevent="placeCall">
      <VInput
        v-model="display"
        class="phone__input"
        :label="t('live.phone.label')"
        :placeholder="t('live.phone.placeholder')"
        :error="inputError"
        :disabled="!ready || sending || inProgress"
        inputmode="tel"
        autocomplete="tel-national"
        maxlength="24"
        @blur="touched = true"
      >
        <template #leading><span class="phone__prefix">+998</span></template>
      </VInput>
      <VButton
        type="submit"
        variant="primary"
        class="phone__submit"
        :icon="Phone"
        :loading="sending"
        :disabled="!ready || inProgress"
      >
        {{ inProgress ? t('live.phone.calling') : t('live.phone.call') }}
      </VButton>
    </form>
    <p v-if="status && ready" class="phone__meta">
      {{ t('live.phone.used', { used: status.used24h, cap: status.dailyCap }) }}
    </p>

    <p v-if="errorText" class="phone__result" data-tone="bad" role="alert">{{ errorText }}</p>
    <div v-if="current && currentView" class="phone__result" :data-tone="currentView.tone" role="status" aria-live="polite">
      <VSpinner v-if="inProgress" :size="14" />
      <span class="phone__text">{{ currentView.text }}</span>
      <span v-if="cost" class="phone__cost">{{ cost }}</span>
      <VButton v-if="!inProgress" size="sm" variant="ghost" @click="newCall">{{ t('live.phone.newCall') }}</VButton>
    </div>

    <div v-if="recent.length" class="phone__recent">
      <h3 class="phone__recent-title">{{ t('live.phone.recent') }}</h3>
      <ul class="phone__list">
        <li v-for="item in recent" :key="item.callId" class="phone__row">
          <time class="phone__time" :datetime="new Date(item.createdAt * 1000).toISOString()">{{ hhmm(item.createdAt) }}</time>
          <span class="phone__number">+998 {{ format(item.phone) }}</span>
          <span class="phone__state" :data-tone="describe(item).tone">{{ describe(item).text }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.phone {
  width: 100%;
  max-width: 560px;
  margin-top: var(--s-10);
  padding: var(--s-5);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  text-align: left;
}
.phone__head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
}
.phone__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.phone__heading {
  flex: 1;
  min-width: 0;
}
.phone__title {
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body-lg);
  font-weight: 600;
}
.phone__sub {
  margin-top: 2px;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.phone__badge {
  flex-shrink: 0;
  padding: 2px var(--s-2);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  white-space: nowrap;
}
.phone__off {
  margin-top: var(--s-4);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.phone__form {
  display: flex;
  align-items: flex-end;
  gap: var(--s-2);
  margin-top: var(--s-4);
}
.phone__input {
  flex: 1;
  min-width: 0;
}
.phone__prefix {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.phone__submit {
  flex-shrink: 0;
}
.phone__meta {
  margin-top: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.phone__result {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2);
  margin-top: var(--s-4);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.phone__result[data-tone='good'] {
  background: var(--good-soft);
  color: var(--good-text);
}
.phone__result[data-tone='warn'] {
  background: var(--warn-soft);
  color: var(--warn-text);
}
.phone__result[data-tone='bad'] {
  background: var(--crit-soft);
  color: var(--crit-text);
}
.phone__text {
  flex: 1;
  min-width: 12ch;
}
.phone__cost {
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
}
.phone__recent {
  margin-top: var(--s-5);
  padding-top: var(--s-4);
  border-top: 1px solid var(--line);
}
.phone__recent-title {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.phone__list {
  margin: var(--s-2) 0 0;
  padding: 0;
  list-style: none;
}
.phone__row {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: baseline;
  gap: var(--s-3);
  padding: 6px 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.phone__time,
.phone__number {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text-2);
  white-space: nowrap;
}
.phone__time {
  color: var(--text-3);
}
.phone__state {
  min-width: 0;
  color: var(--text-2);
}
.phone__state[data-tone='good'] {
  color: var(--good-text);
}
.phone__state[data-tone='bad'] {
  color: var(--crit-text);
}
.phone__state[data-tone='warn'] {
  color: var(--warn-text);
}

@media (max-width: 640px) {
  .phone {
    margin-top: var(--s-8);
    padding: var(--s-4);
  }
  .phone__badge {
    display: none;
  }
  .phone__form {
    flex-direction: column;
    align-items: stretch;
  }
  .phone__row {
    grid-template-columns: auto 1fr;
  }
  .phone__state {
    grid-column: 1 / -1;
  }
}
</style>
