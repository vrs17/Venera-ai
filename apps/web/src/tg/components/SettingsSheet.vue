<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, ChevronRight, CircleCheck, CircleDashed, Clock, LogOut, Users, Volume2 } from 'lucide-vue-next'
import { listConnectors } from '../../api/connectors.api'
import { LOCALES, setLocale } from '../../i18n'
import type { Locale } from '../../i18n'
import type { AuthUser, ConnectorStatus } from '../../types'
import VAvatar from '../../ui/VAvatar.vue'
import VSheet from '../../ui/VSheet.vue'
import VSwitch from '../../ui/VSwitch.vue'
import { usePrefs } from '../prefs'
import MemorySheet from './MemorySheet.vue'
import { useTgSheet } from '../sheet'
import { haptic, nativePopup } from '../telegram'

/**
 * Sozlamalar (avatar bosilganda). iOS "guruhlangan ro'yxat" ko'rinishi: oyna foni
 * kulrang, kartalar oq, har biri bir qator:
 *
 *   - kim kirgan (ism, login, lavozim);
 *   - til - 4 tugma (bir bosishda); tor ekranda yoki katta shriftda 2x2 ga o'tadi
 *     (umumiy VSegmented bitta qatorda qisqartirib yuborardi: "Oʻz…"); ostida izoh:
 *     mavzu Telegram'ga ergashadi (tanlov YO'Q - Mini App Telegram ichida yashaydi);
 *   - javobni ovoz bilan o'qish - default O'CHIQ;
 *   - "Xotira" (2026-10-10) - Barno nimani eslab qolgani; alohida oyna (MemorySheet);
 *   - ulanishlar - HRM qatori, FAQAT HOLAT (ega qarori, 2026-11-12): HRM veb ilovada
 *     login va parol bilan ulanadi ("+" -> Ulanishlar), bu yerda parol so'ralmaydi -
 *     ostidagi izoh shuni aytadi. CRM ko'rsatilmaydi: u BRB-Tech ID bilan kirishda
 *     o'zi ulanadi. Kalit yo'q - ulangan tizim ishlatiladi;
 *   - chiqish - alohida kartada oddiy qizil matnli qator (katta qizil "plita" emas);
 *     oqibati ("keyingi safar parol so'raladi") tasdiq oynasida - Telegram'ning o'z
 *     `showPopup` i qizil "Chiqish" tugmasi bilan, bo'lmasa sahifa ichidagisi.
 */
const props = defineProps<{ user: AuthUser | null }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ logout: [] }>()
const { t, locale } = useI18n({ useScope: 'global' })
const { readAloud } = usePrefs()

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
const confirmSheet = ref<InstanceType<typeof VSheet> | null>(null)
const confirming = ref(false)
useTgSheet(open, sheet)
useTgSheet(confirming, confirmSheet)

function pickLang(value: Locale) {
  if (value === locale.value) return
  haptic.select()
  setLocale(value)
}

const readAloudModel = computed({
  get: () => readAloud.value,
  set: (on: boolean) => {
    haptic.select()
    readAloud.value = on
  },
})

/* ── Xotira ── */
const memoryOpen = ref(false)
function openMemory() {
  haptic.select()
  memoryOpen.value = true
}

/* ── HRM ulanishi - faqat holat ── */
const hrm = ref<ConnectorStatus | null>(null)
const hrmFailed = ref(false)
watch(open, async (on) => {
  if (!on) {
    confirming.value = false
    memoryOpen.value = false
    return
  }
  try {
    hrm.value = (await listConnectors()).connectors.find((c) => c.id === 'hrm') ?? null
    // Javobda HRM yo'q - holat noma'lum: bo'sh karta emas, "yuklanmadi".
    hrmFailed.value = !hrm.value
  } catch {
    hrmFailed.value = true
  }
})

const hrmState = computed<{ label: string; tone: 'good' | 'warn' | 'muted' }>(() => {
  const c = hrm.value
  if (!c || !c.configured) return { label: t('tg.settings.unavailable'), tone: 'muted' }
  if (c.state === 'connected') return { label: t('tg.settings.connected'), tone: 'good' }
  if (c.state === 'expired') return { label: t('tg.settings.expired'), tone: 'warn' }
  return { label: t('tg.settings.notConnected'), tone: 'muted' }
})

const login = computed(() => props.user?.email ?? '')
const role = computed(() => [props.user?.position, props.user?.department].filter(Boolean).join(' · '))

async function askLogout() {
  const native = nativePopup({
    title: t('tg.settings.logoutConfirm'),
    message: t('tg.settings.logoutMessage'),
    buttons: [
      { id: 'out', type: 'destructive', text: t('tg.settings.logout') },
      { type: 'cancel' },
    ],
  })
  if (native) {
    if ((await native) === 'out') emit('logout')
    return
  }
  confirming.value = true
}
function confirmLogout() {
  confirming.value = false
  emit('logout')
}
</script>

<template>
  <VSheet ref="sheet" v-model:open="open" class="tg-sheet tg-sheet--grouped" side="bottom" :title="t('tg.settings.title')">
    <div class="set">
      <section class="set__card set__me">
        <VAvatar :name="user?.fullName || login" :size="40" />
        <div class="set__me-text">
          <p class="set__name">{{ user?.fullName || login }}</p>
          <p class="set__sub">{{ login }}</p>
          <p v-if="role" class="set__sub">{{ role }}</p>
        </div>
      </section>

      <section class="set__group">
        <h3 :id="'set-lang'" class="set__label">{{ t('language') }}</h3>
        <div class="lang" role="radiogroup" aria-labelledby="set-lang">
          <button
            v-for="l in LOCALES"
            :key="l.code"
            type="button"
            role="radio"
            class="lang__opt"
            :class="{ 'is-on': locale === l.code }"
            :aria-checked="locale === l.code ? 'true' : 'false'"
            :lang="l.htmlLang"
            @click="pickLang(l.code)"
          >
            {{ l.label }}
          </button>
        </div>
        <p class="set__caption">{{ t('tg.settings.themeNote') }}</p>
      </section>

      <section class="set__card">
        <div class="set__row set__row--switch">
          <span class="set__icon" aria-hidden="true"><Volume2 :size="18" :stroke-width="1.75" /></span>
          <VSwitch
            v-model="readAloudModel"
            class="set__switch"
            label-first
            :label="t('tg.settings.readAloud')"
            :description="t('tg.settings.readAloudHint')"
          />
        </div>
      </section>

      <!-- Xotira: Barno nimani eslab qolgan - alohida oyna. -->
      <section class="set__card">
        <button type="button" class="set__row set__nav" @click="openMemory">
          <span class="set__icon" aria-hidden="true"><Brain :size="18" :stroke-width="1.75" /></span>
          <span class="set__row-text">
            <span class="set__row-title">{{ t('assistant.memory.title') }}</span>
            <span class="set__row-sub">{{ t('assistant.memory.openHint') }}</span>
          </span>
          <ChevronRight class="set__chev" :size="18" :stroke-width="1.75" aria-hidden="true" />
        </button>
      </section>

      <section class="set__group">
        <h3 class="set__label">{{ t('tg.settings.connections') }}</h3>
        <div class="set__card">
          <div v-if="hrm" class="set__row">
            <span class="set__icon" aria-hidden="true"><Users :size="18" :stroke-width="1.75" /></span>
            <div class="set__row-text">
              <p class="set__row-title">{{ hrm.label || 'HRM' }}</p>
              <p v-if="hrm.login" class="set__row-sub">{{ hrm.login }}</p>
            </div>
            <span class="set__state" :class="`is-${hrmState.tone}`">
              <CircleCheck v-if="hrmState.tone === 'good'" :size="14" :stroke-width="2" aria-hidden="true" />
              <Clock v-else-if="hrmState.tone === 'warn'" :size="14" :stroke-width="2" aria-hidden="true" />
              <CircleDashed v-else :size="14" :stroke-width="2" aria-hidden="true" />
              {{ hrmState.label }}
            </span>
          </div>
          <p v-else-if="hrmFailed" class="set__row set__row-sub">{{ t('connectorsLoadFailed') }}</p>
          <div v-else class="set__row" aria-hidden="true">
            <span class="tg-skel set__skel" />
          </div>
        </div>
        <p class="set__caption">{{ t('tg.settings.hrmViaWeb') }}</p>
      </section>

      <section class="set__card">
        <button type="button" class="set__row set__logout" @click="askLogout">
          <LogOut :size="20" :stroke-width="1.75" aria-hidden="true" />
          <span>{{ t('tg.settings.logout') }}</span>
        </button>
      </section>
    </div>
  </VSheet>

  <MemorySheet v-model:open="memoryOpen" />

  <!-- Sahifa ichidagi tasdiq (Telegram'ning showPopup i yo'q bo'lsa). ✕ yo'q -
       "Bekor qilish" tugmasi bor. -->
  <VSheet
    ref="confirmSheet"
    v-model:open="confirming"
    class="tg-sheet"
    side="bottom"
    role="alertdialog"
    hide-close
    :title="t('tg.settings.logoutConfirm')"
    :description="t('tg.settings.logoutMessage')"
  >
    <div class="confirm">
      <button type="button" class="confirm__btn confirm__btn--danger" @click="confirmLogout">{{ t('tg.settings.logout') }}</button>
      <button type="button" class="confirm__btn" @click="confirming = false">{{ t('ui.cancel') }}</button>
    </div>
  </VSheet>
</template>

<style scoped>
.set {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
  padding-bottom: var(--s-2);
}
.set__card {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: var(--surface);
  overflow: hidden;
}
.set__me {
  flex-direction: row;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-3) var(--s-4);
}
.set__me-text {
  min-width: 0;
}
.set__name {
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.set__sub {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.set__group {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.set__label {
  padding-left: var(--s-4);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.set__caption {
  padding: 0 var(--s-4);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

/* Til: 4 radio-tugma. Joy yetsa bir qatorda, bo'lmasa (320px, 200% shrift) 2x2 -
   so'z hech qachon "Oʻz…" bo'lib qisqarmaydi. */
.lang {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(max(4.5rem, 22%), 1fr));
  gap: 4px;
  padding: 4px;
  border-radius: 14px;
  background: var(--fill);
}
.lang__opt {
  min-height: 44px;
  padding: 4px var(--s-2);
  border-radius: 10px;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  transition:
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out);
}
.lang__opt.is-on {
  background: var(--surface);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--e1);
}
.lang__opt:active:not(.is-on) {
  background: color-mix(in srgb, var(--surface) 50%, transparent);
}

.set__row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-height: 56px;
  padding: var(--s-2) var(--s-4);
}
.set__row + .set__row {
  border-top: 1px solid var(--line);
}
.set__switch {
  flex: 1;
  min-width: 0;
}
.set__row--switch :deep(.v-switch) {
  --sw-w: 51px;
  --sw-h: 31px;
  align-items: center;
}
.set__row--switch :deep(.v-switch__track) {
  margin-top: 0;
}
.set__row--switch :deep(.v-switch__label) {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.set__row--switch :deep(.v-switch__desc) {
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.set__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--fill);
  color: var(--text-2);
}
.set__row-text {
  flex: 1;
  min-width: 0;
}
.set__row-title {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 500;
}
.set__row-sub {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.set__state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 3px var(--s-2);
  border-radius: var(--r-full);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 600;
  background: var(--fill);
  color: var(--text-3);
}
.set__state.is-good {
  background: var(--good-soft);
  color: var(--good-text);
}
.set__state.is-warn {
  background: var(--warn-soft);
  color: var(--warn-text);
}
.set__skel {
  width: 60%;
  height: 14px;
}
/* Xotira qatori - butun qator tugma (iOS "navigatsiya" qatori: o'ngda ›). */
.set__nav {
  width: 100%;
  text-align: left;
}
.set__nav:active {
  background: var(--fill);
}
.set__nav .set__row-title,
.set__nav .set__row-sub {
  display: block;
}
.set__chev {
  flex-shrink: 0;
  color: var(--text-4);
}
.set__logout {
  width: 100%;
  color: var(--crit-text);
  font-size: var(--fs-body);
  font-weight: 500;
  text-align: left;
}
.set__logout:active {
  background: var(--fill);
}

/* Qorong'i mavzu (iOS kabi): oyna foni eng to'q, kartalar bir pog'ona ochroq -
   --bg-subtle va --surface qorong'ida deyarli bir xil, kartalar "erib" ketardi. */
html[data-theme='dark'] .set__card,
html[data-theme='dark'] .lang {
  background: var(--fill);
}
html[data-theme='dark'] .set__icon,
html[data-theme='dark'] .lang__opt.is-on {
  background: var(--fill-hover);
}
html[data-theme='dark'] .lang__opt.is-on {
  box-shadow: none;
}

.confirm {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  padding-top: var(--s-2);
}
.confirm__btn {
  min-height: 52px;
  border-radius: 14px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body);
  font-weight: 600;
}
.confirm__btn--danger {
  background: var(--crit);
  color: #fff;
}
.confirm__btn:active {
  transform: scale(0.98);
}
</style>
