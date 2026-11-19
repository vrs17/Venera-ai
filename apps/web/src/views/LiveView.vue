<script setup lang="ts">
/**
 * Jonli ovozli suhbat - llm.brb-tech.uz/barno.
 *
 * Uch sahna, bitta sahifa:
 *   home  - salomlashish (kirgan odamga ismi bilan) va ikki suhbatdosh kartasi; karta bosilsa -
 *           qo'ng'iroq boshlanadi. Mikrofon xatolari shu yerda, "Qayta urinish" bilan;
 *   call  - suhbatdosh nomi, holat va taymer, katta ovoz shari, subtitr, uch tugma
 *           (mikrofon, tugatish, subtitr). Sahifadan chiqish tasdiq so'raydi;
 *   after - rahmat, davomiylik, baho (yulduz) va sabablar, "Yana qo'ng'iroq qilish".
 *
 * HOZIR FAQAT INTERFEYS (2026-11-19): transport - demo (`features/live/transport.ts`), mikrofon
 * esa haqiqiy. Integratsiyada `useLiveCall(createRealTransport)` - sahifa o'zgarmaydi.
 * Sarlavhadagi "Demo" belgisi shu bosqichni ko'rsatib turadi.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Captions, CaptionsOff, Check, Mic, MicOff, Moon, Phone, PhoneOff, Star, Sun, Wifi } from 'lucide-vue-next'
import { useAuth } from '../composables/useAuth'
import { useTheme } from '../theme'
import { secureUrl } from '../api/stt.api'
import BrandSpark from '../components/BrandSpark.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import VButton from '../ui/VButton.vue'
import VIconButton from '../ui/VIconButton.vue'
import VChoiceChips from '../ui/VChoiceChips.vue'
import VCopy from '../ui/VCopy.vue'
import LiveOrb from '../features/live/LiveOrb.vue'
import { PERSONAS } from '../features/live/personas'
import type { LivePersona, OrbMode } from '../features/live/personas'
import { useLiveCall } from '../features/live/useLiveCall'
import type { DemoScript } from '../features/live/transport'

const { t, locale } = useI18n({ useScope: 'global' })
const { isAuthenticated, user } = useAuth()
const { theme, toggle: toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const call = useLiveCall()
const { status, error, phase, muted, elapsed, userLevel, agentLevel, agentCaption, userCaption, captionFinal,
  poorNetwork, noInput, callId } = call

type Stage = 'home' | 'call' | 'after'
const stage = computed<Stage>(() => (status.value === 'idle' ? 'home' : status.value === 'ended' ? 'after' : 'call'))
const live = computed(() => status.value === 'live')

// --- suhbatdosh ----------------------------------------------------------------------

const personaName = (p: LivePersona) => t(`live.persona.${p.id}.name`)
const current = computed(() => call.persona.value)
const name = computed(() => (current.value ? personaName(current.value) : ''))
/** Oxirgi tanlangan - xato kartasidagi "Qayta urinish" va rahmat sahifasidagi "Yana" uchun. */
const lastPersona = ref<LivePersona>(PERSONAS[0])
const hovered = ref<string | null>(null)

function script(p: LivePersona): DemoScript {
  const n = personaName(p)
  return { greeting: t('live.demoGreeting', { name: n }), replies: [t('live.demoReply1'), t('live.demoReply2')] }
}

function startCall(p: LivePersona) {
  lastPersona.value = p
  resetFeedback()
  void call.start(p, script(p), String(locale.value))
}

// --- salomlashish ----------------------------------------------------------------------

/** "MAXMUD JUMANAZAROV" -> "Maxmud": HRM ismlari ko'pincha bosh harflarda keladi. */
function firstName(full: string | undefined): string {
  const first = (full ?? '').trim().split(/\s+/)[0] ?? ''
  if (!first) return ''
  return first === first.toUpperCase() ? first.charAt(0) + first.slice(1).toLowerCase() : first
}

const greeting = computed(() => {
  const hour = new Date().getHours()
  const part = hour >= 5 && hour < 12 ? 'Morning' : hour >= 12 && hour < 18 ? 'Day' : 'Evening'
  const who = isAuthenticated.value ? firstName(user.value?.fullName) : ''
  return who ? t(`live.greeting${part}`, { name: who }) : t(`live.greeting${part}Anon`)
})

// --- qo'ng'iroq sahnasi -------------------------------------------------------------------

const orbMode = computed<OrbMode>(() => {
  if (status.value === 'mic' || status.value === 'connecting') return 'ringing'
  if (muted.value && phase.value === 'listening') return 'muted'
  return phase.value
})

const orbLevel = computed(() => {
  if (phase.value === 'speaking') return agentLevel.value
  if (phase.value === 'listening' && !muted.value) return userLevel.value
  return 0
})

const statusText = computed(() => {
  if (status.value === 'mic') return t('live.micPrompt', { name: name.value })
  if (status.value === 'connecting') return t('live.connecting', { name: name.value })
  if (phase.value === 'thinking') return t('live.thinking')
  if (phase.value === 'speaking') return t('live.speaking', { name: name.value })
  if (muted.value) return t('live.mutedStatus')
  return t('live.listening')
})

function mmss(total: number): string {
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
const clock = computed(() => mmss(elapsed.value))

// Subtitr - odamning tanlovi eslab qolinadi (shu brauzerda).
const CAPTIONS_KEY = 'venera_live_captions'
function readCaptions(): boolean {
  try {
    return localStorage.getItem(CAPTIONS_KEY) !== '0'
  } catch {
    return true
  }
}
const captionsOn = ref(readCaptions())
function toggleCaptions() {
  captionsOn.value = !captionsOn.value
  try {
    localStorage.setItem(CAPTIONS_KEY, captionsOn.value ? '1' : '0')
  } catch {
    /* maxfiy rejim - tanlov shu sahifada baribir ishlaydi */
  }
}
/** Ekran o'quvchiga faqat TUGAGAN gap aytiladi - so'zma-so'z emas. */
const spokenCaption = computed(() => (captionFinal.value ? agentCaption.value : ''))

// --- xato ------------------------------------------------------------------------------

const errorText = computed(() => {
  const n = personaName(lastPersona.value)
  switch (error.value) {
    case 'insecure': return t('live.errInsecure')
    case 'blocked': return t('live.errBlocked')
    case 'denied': return t('live.errDenied')
    case 'no-mic': return t('live.errNoMic')
    case 'mic': return t('live.errMic')
    case 'connect': return t('live.errConnect', { name: n })
    case 'dropped': return t('live.errDropped')
    default: return ''
  }
})
const httpsLink = computed(() => (error.value === 'insecure' ? secureUrl() : ''))

// --- baho -------------------------------------------------------------------------------

const rating = ref(0)
const reasons = ref<string[]>([])
const comment = ref('')
const sent = ref(false)
const GOOD = ['natural', 'fast', 'helpful', 'understood'] as const
const BAD = ['misheard', 'slow', 'interrupted', 'voice', 'wrong'] as const
const reasonOptions = computed(() =>
  (rating.value >= 4 ? GOOD : BAD).map((key) => ({ value: key as string, label: t(`live.chip.${key}`) })),
)
watch(rating, (next, prev) => {
  if ((next >= 4) !== (prev >= 4)) reasons.value = []
})

function resetFeedback() {
  rating.value = 0
  reasons.value = []
  comment.value = ''
  sent.value = false
}

function onStarKey(e: KeyboardEvent) {
  if (e.key === 'ArrowRight' || e.key === 'ArrowUp') { e.preventDefault(); rating.value = Math.min(5, rating.value + 1) }
  if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') { e.preventDefault(); rating.value = Math.max(1, rating.value - 1) }
}

/** Integratsiyada: baho, sabablar va izoh `callId` bilan serverga. Hozir - faqat rahmat. */
function sendFeedback() {
  if (!rating.value) return
  sent.value = true
}

function goHome() {
  resetFeedback()
  call.reset()
}

// --- sahifa -----------------------------------------------------------------------------

onBeforeRouteLeave(() => {
  if (stage.value !== 'call') return true
  if (!window.confirm(t('live.leaveConfirm'))) return false
  call.end()
  return true
})

let previousTitle = ''
onMounted(() => {
  previousTitle = document.title
  document.title = t('live.docTitle')
})
watch(locale, () => { document.title = t('live.docTitle') })
onBeforeUnmount(() => { document.title = previousTitle })

const tint = computed(() => ((current.value ?? lastPersona.value).tone === 'cool' ? 'var(--viz-1)' : 'var(--brand)'))
</script>

<template>
  <div class="live" :data-stage="stage" :style="{ '--tint': stage === 'home' ? 'var(--brand)' : tint }">
    <header class="live__bar">
      <div class="live__brand">
        <RouterLink to="/" class="live__logo">
          <span class="live__spark"><BrandSpark :size="16" /></span>
          <span>Barno</span>
        </RouterLink>
        <span class="live__badge" :title="t('live.demoHint')">{{ t('live.demo') }}</span>
      </div>
      <div class="live__tools">
        <LanguageSwitcher />
        <VIconButton
          :icon="isDark ? Sun : Moon"
          :label="isDark ? t('themeToLight') : t('themeToDark')"
          tooltip-placement="bottom"
          @click="toggleTheme"
        />
        <VButton
          v-if="!isAuthenticated && stage !== 'call'"
          size="sm"
          variant="outline"
          pill
          :to="{ name: 'login', query: { redirect: '/barno' } }"
        >
          {{ t('live.login') }}
        </VButton>
      </div>
    </header>

    <Transition name="stage" mode="out-in">
      <!-- BOSH SAHIFA -->
      <main v-if="stage === 'home'" key="home" class="home">
        <h1 class="home__title">{{ greeting }}</h1>
        <p class="home__sub">{{ t('live.pick') }}</p>

        <div v-if="error" class="home__alert" role="alert">
          <p>
            {{ errorText }}
            <a v-if="httpsLink" class="home__link" :href="httpsLink">{{ httpsLink }}</a>
          </p>
          <VButton v-if="error !== 'insecure' && error !== 'blocked'" size="sm" variant="secondary" @click="startCall(lastPersona)">
            {{ t('live.retry') }}
          </VButton>
        </div>

        <div class="home__grid">
          <button
            v-for="p in PERSONAS"
            :key="p.id"
            type="button"
            class="persona"
            :data-tone="p.tone"
            :aria-label="t('live.callAria', { name: personaName(p) })"
            @click="startCall(p)"
            @pointerenter="hovered = p.id"
            @pointerleave="hovered = null"
            @focus="hovered = p.id"
            @blur="hovered = null"
          >
            <span class="persona__orb">
              <LiveOrb :tone="p.tone" mode="idle" :level="hovered === p.id ? 0.35 : 0" />
            </span>
            <span class="persona__text">
              <span class="persona__name">{{ personaName(p) }}</span>
              <span class="persona__tagline">{{ t(`live.persona.${p.id}.tagline`) }}</span>
            </span>
            <span class="persona__cta" aria-hidden="true">
              <Phone :size="16" :stroke-width="1.9" />
              <span class="persona__cta-text">{{ t('live.call') }}</span>
            </span>
          </button>
        </div>

        <p class="home__note">{{ t('disclaimer') }}</p>
      </main>

      <!-- QO'NG'IROQ -->
      <main v-else-if="stage === 'call'" key="call" class="call">
        <div class="call__head">
          <p class="call__name">{{ name }}</p>
          <p class="call__status">
            <span role="status">{{ statusText }}</span>
            <template v-if="live">
              <span class="call__dot" aria-hidden="true">·</span>
              <time class="call__clock" :datetime="`PT${elapsed}S`">{{ clock }}</time>
            </template>
          </p>
        </div>

        <div class="call__banners" aria-live="polite">
          <p v-if="poorNetwork" class="call__banner">
            <Wifi :size="15" :stroke-width="1.9" aria-hidden="true" />
            {{ t('live.poorNetwork') }}
          </p>
          <p v-if="noInput" class="call__banner">
            <MicOff :size="15" :stroke-width="1.9" aria-hidden="true" />
            {{ t('live.noInput') }}
          </p>
        </div>

        <div class="call__stage">
          <LiveOrb :tone="current?.tone ?? 'brand'" :mode="orbMode" :level="orbLevel" />
        </div>

        <div class="call__captions" :class="{ 'call__captions--hidden': !captionsOn }" aria-hidden="true">
          <p v-if="agentCaption" class="call__caption" :class="{ 'call__caption--past': phase !== 'speaking' }">
            {{ agentCaption }}
          </p>
          <p v-if="userCaption" class="call__caption call__caption--user">
            <span class="call__who">{{ t('live.you') }}:</span> {{ userCaption }}
          </p>
        </div>
        <p class="sr-only" aria-live="polite">{{ captionsOn ? spokenCaption : '' }}</p>

        <div class="call__controls">
          <div class="ctl">
            <button
              type="button"
              class="ctl__btn"
              :class="{ 'ctl__btn--muted': muted }"
              :aria-pressed="muted"
              :aria-label="muted ? t('live.unmuteAria') : t('live.muteAria')"
              :disabled="!live"
              @click="call.toggleMute()"
            >
              <MicOff v-if="muted" :size="24" :stroke-width="1.8" />
              <Mic v-else :size="24" :stroke-width="1.8" />
            </button>
            <span class="ctl__label" aria-hidden="true">{{ muted ? t('live.unmute') : t('live.mute') }}</span>
          </div>
          <div class="ctl">
            <button
              type="button"
              class="ctl__btn ctl__btn--end"
              :aria-label="live ? t('live.end') : t('live.cancel')"
              @click="call.end()"
            >
              <PhoneOff :size="24" :stroke-width="1.8" />
            </button>
            <span class="ctl__label" aria-hidden="true">{{ live ? t('live.end') : t('live.cancel') }}</span>
          </div>
          <div class="ctl">
            <button
              type="button"
              class="ctl__btn ctl__btn--toggle"
              :aria-pressed="captionsOn"
              :aria-label="captionsOn ? t('live.captionsHide') : t('live.captionsShow')"
              @click="toggleCaptions"
            >
              <Captions v-if="captionsOn" :size="24" :stroke-width="1.8" />
              <CaptionsOff v-else :size="24" :stroke-width="1.8" />
            </button>
            <span class="ctl__label" aria-hidden="true">{{ t('live.captions') }}</span>
          </div>
        </div>

        <p class="call__note">{{ t('live.disclaimerAgent', { name }) }}</p>
      </main>

      <!-- RAHMAT -->
      <main v-else key="after" class="after">
        <span class="after__orb"><LiveOrb :tone="current?.tone ?? 'brand'" mode="idle" /></span>
        <h1 class="after__title">{{ t('live.thanks', { name }) }}</h1>
        <p class="after__meta">{{ t('live.duration', { time: mmss(elapsed) }) }}</p>

        <section v-if="!sent" class="after__rate" :aria-label="t('live.rateQuestion')">
          <p class="after__question">{{ t('live.rateQuestion') }}</p>
          <div class="stars" role="radiogroup" :aria-label="t('live.rateQuestion')" @keydown="onStarKey">
            <button
              v-for="n in 5"
              :key="n"
              type="button"
              class="stars__btn"
              role="radio"
              :aria-checked="rating === n"
              :aria-label="t('live.rateStar', { n })"
              :tabindex="rating === n || (rating === 0 && n === 1) ? 0 : -1"
              :class="{ 'stars__btn--on': n <= rating }"
              @click="rating = n"
            >
              <Star :size="28" :stroke-width="1.6" />
            </button>
          </div>

          <template v-if="rating">
            <p class="after__question after__question--sm">{{ rating >= 4 ? t('live.chipsGood') : t('live.chipsBad') }}</p>
            <VChoiceChips
              :model-value="reasons"
              @update:model-value="(v) => (reasons = Array.isArray(v) ? v.map(String) : [])"
              :options="reasonOptions"
              multiple
              size="sm"
              :aria-label="rating >= 4 ? t('live.chipsGood') : t('live.chipsBad')"
              class="after__chips"
            />
            <textarea v-model="comment" class="after__comment" rows="2" maxlength="500" :placeholder="t('live.comment')" />
          </template>
        </section>
        <p v-else class="after__sent" role="status">
          <Check :size="18" :stroke-width="2" aria-hidden="true" />
          {{ t('live.sent') }}
        </p>

        <div class="after__actions">
          <VButton v-if="!sent" variant="primary" pill :disabled="!rating" @click="sendFeedback">{{ t('live.send') }}</VButton>
          <VButton variant="secondary" pill :icon="Phone" @click="startCall(current ?? lastPersona)">{{ t('live.again') }}</VButton>
          <VButton variant="ghost" pill @click="goHome">{{ t('live.home') }}</VButton>
        </div>

        <p v-if="callId" class="after__id">
          <span>{{ t('live.callId', { id: callId }) }}</span>
          <VCopy :text="callId" size="sm" />
        </p>
      </main>
    </Transition>
  </div>
</template>

<style scoped>
/* --- sahifa ------------------------------------------------------------------------- */
.live {
  --tint: var(--brand);
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100dvh;
  color: var(--text);
  background:
    radial-gradient(120% 60% at 50% 105%, color-mix(in srgb, var(--tint) 10%, transparent) 0%, transparent 62%),
    var(--bg);
  transition: background-color var(--dur-3) var(--ease-out);
}

.live__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  height: 56px;
  padding: 0 var(--gutter);
  flex-shrink: 0;
}
.live__brand {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}
.live__logo {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  color: var(--text);
  font-weight: 600;
  font-size: var(--fs-title-3);
  letter-spacing: -0.01em;
  text-decoration: none;
  border-radius: var(--r-sm);
}
.live__logo:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
}
.live__spark {
  display: inline-flex;
  color: var(--brand);
}
.live__badge {
  padding: 2px 8px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-full);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  letter-spacing: 0.02em;
  cursor: default;
}
.live__tools {
  display: flex;
  align-items: center;
  gap: var(--s-1);
}

/* --- sahnalar almashinuvi --------------------------------------------------------- */
.stage-enter-active,
.stage-leave-active {
  transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out);
}
.stage-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.99);
}
.stage-leave-to {
  opacity: 0;
  transform: scale(0.99);
}

/* --- bosh sahifa ------------------------------------------------------------------- */
.home {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-width: 920px;
  margin: 0 auto;
  padding: var(--s-8) var(--gutter) var(--s-10);
  text-align: center;
}
.home__title {
  font-size: var(--fs-display);
  line-height: var(--lh-display);
  font-weight: 600;
  letter-spacing: -0.028em;
  text-wrap: balance;
}
.home__sub {
  margin-top: var(--s-3);
  color: var(--text-2);
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body);
}
.home__alert {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  max-width: 640px;
  margin-top: var(--s-6);
  padding: var(--s-3) var(--s-4);
  border-radius: var(--r-md);
  background: var(--crit-soft);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: left;
}
.home__alert p {
  flex: 1;
}
.home__link {
  display: block;
  margin-top: var(--s-1);
  color: inherit;
  font-weight: 600;
  word-break: break-all;
}
.home__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s-5);
  width: 100%;
  max-width: 760px;
  margin-top: var(--s-10);
}
.home__note {
  margin-top: var(--s-10);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

.persona {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-4);
  padding: var(--s-8) var(--s-6) var(--s-6);
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  color: inherit;
  font: inherit;
  text-align: center;
  cursor: pointer;
  transition:
    border-color var(--dur-2) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
  -webkit-tap-highlight-color: transparent;
}
.persona:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
}
@media (hover: hover) {
  .persona:hover {
    border-color: var(--line-strong);
    box-shadow: var(--e2);
    transform: translateY(-2px);
  }
  .persona:hover .persona__cta {
    background: var(--ink);
    color: var(--on-ink);
  }
}
.persona:active {
  transform: translateY(0) scale(0.99);
}
.persona__orb {
  display: block;
  width: 168px;
  margin: var(--s-2) 0 var(--s-3);
  transition: transform var(--dur-3) var(--ease-out);
}
.persona:hover .persona__orb {
  transform: scale(1.03);
}
.persona__text {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
}
.persona__name {
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  font-weight: 600;
  letter-spacing: -0.012em;
}
.persona__tagline {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.persona__cta {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  height: 40px;
  margin-top: var(--s-2);
  padding: 0 var(--s-5);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 500;
  transition: background-color var(--dur-2) var(--ease-out), color var(--dur-2) var(--ease-out);
}

/* --- qo'ng'iroq -------------------------------------------------------------------- */
.call {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--s-4) var(--gutter) calc(var(--s-6) + env(safe-area-inset-bottom));
  text-align: center;
}
.call__head {
  margin-top: var(--s-2);
}
.call__name {
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.02em;
}
.call__status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  min-height: var(--lh-body);
  margin-top: var(--s-1);
  color: var(--text-2);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.call__dot {
  color: var(--text-4);
}
.call__clock {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--fs-body-sm);
  color: var(--text-3);
}
.call__banners {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  min-height: 0;
  margin-top: var(--s-3);
}
.call__banner {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  max-width: 520px;
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: left;
}
.call__banner svg {
  flex-shrink: 0;
}
.call__stage {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  width: min(72vw, 44vh, 380px);
  min-height: 200px;
  margin: var(--s-6) 0;
}
.call__captions {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: var(--s-2);
  width: 100%;
  max-width: 560px;
  min-height: calc(var(--lh-body-lg) * 3);
  transition: opacity var(--dur-2) var(--ease-out);
}
.call__captions--hidden {
  opacity: 0;
}
.call__caption {
  color: var(--text);
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body-lg);
  text-wrap: balance;
  transition: color var(--dur-3) var(--ease-out);
}
.call__caption--past {
  color: var(--text-3);
}
.call__caption--user {
  color: var(--text-2);
  font-size: var(--fs-body);
}
.call__who {
  color: var(--text-3);
}
.call__controls {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: var(--s-6);
  margin-top: var(--s-6);
}
.ctl {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  width: 88px;
}
.ctl__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--e1);
  cursor: pointer;
  transition:
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
  -webkit-tap-highlight-color: transparent;
}
.ctl__btn:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
}
.ctl__btn:active:not(:disabled) {
  transform: scale(0.95);
}
.ctl__btn:disabled {
  opacity: 0.45;
  cursor: default;
}
@media (hover: hover) {
  .ctl__btn:hover:not(:disabled) {
    background: var(--fill-hover);
  }
}
.ctl__btn--muted.ctl__btn--muted {
  border-color: transparent;
  background: var(--warn-soft);
  color: var(--warn-text);
}
.ctl__btn--end.ctl__btn--end {
  border-color: transparent;
  background: var(--ink);
  color: var(--on-ink);
}
@media (hover: hover) {
  .ctl__btn--end.ctl__btn--end:hover {
    background: var(--ink-hover);
  }
}
.ctl__btn--toggle[aria-pressed='false'] {
  color: var(--text-3);
}
.ctl__label {
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-wrap: balance;
}
.call__note {
  margin-top: var(--s-5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

/* --- rahmat ------------------------------------------------------------------------ */
.after {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-width: 560px;
  margin: 0 auto;
  padding: var(--s-8) var(--gutter) var(--s-10);
  text-align: center;
}
.after__orb {
  display: block;
  width: 88px;
  margin-bottom: var(--s-8);
}
.after__title {
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.02em;
  text-wrap: balance;
}
.after__meta {
  margin-top: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  font-variant-numeric: tabular-nums;
}
.after__rate {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  margin-top: var(--s-8);
}
.after__question {
  color: var(--text-2);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.after__question--sm {
  margin-top: var(--s-5);
  font-size: var(--fs-body-sm);
}
.stars {
  display: flex;
  gap: var(--s-1);
  margin-top: var(--s-3);
}
.stars__btn {
  display: inline-flex;
  padding: var(--s-1);
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--text-4);
  cursor: pointer;
  transition: color var(--dur-1) var(--ease-out), transform var(--dur-1) var(--ease-out);
}
.stars__btn:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}
.stars__btn:active {
  transform: scale(0.92);
}
.stars__btn--on {
  color: var(--warn);
}
.stars__btn--on :deep(svg) {
  fill: currentColor;
}
.after__chips {
  justify-content: center;
  margin-top: var(--s-3);
}
.after__comment {
  width: 100%;
  margin-top: var(--s-4);
  padding: var(--s-3) var(--s-4);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  resize: vertical;
}
.after__comment::placeholder {
  color: var(--text-4);
}
.after__comment:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
  border-color: transparent;
}
.after__sent {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  margin-top: var(--s-8);
  color: var(--good-text);
  font-size: var(--fs-body);
}
.after__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--s-2);
  margin-top: var(--s-8);
}
.after__id {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  margin-top: var(--s-6);
  color: var(--text-4);
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

/* --- telefon ----------------------------------------------------------------------- */
@media (max-width: 640px) {
  .home {
    justify-content: flex-start;
    padding-top: var(--s-10);
  }
  .home__title {
    font-size: var(--fs-title-1);
    line-height: var(--lh-title-1);
  }
  .home__sub {
    font-size: var(--fs-body);
  }
  .home__grid {
    grid-template-columns: 1fr;
    gap: var(--s-3);
    margin-top: var(--s-8);
  }
  /* Kartalar yonma-yon emas, ixcham qator: shar - matn - qo'ng'iroq belgisi. */
  .persona {
    flex-direction: row;
    gap: var(--s-4);
    padding: var(--s-4) var(--s-4) var(--s-4) var(--s-5);
    text-align: left;
  }
  .persona__orb {
    width: 64px;
    margin: 0;
  }
  .persona__text {
    flex: 1;
    min-width: 0;
  }
  .persona__name {
    font-size: var(--fs-title-3);
    line-height: var(--lh-title-3);
  }
  .persona__cta {
    width: 44px;
    height: 44px;
    margin: 0;
    padding: 0;
    justify-content: center;
    background: var(--ink);
    color: var(--on-ink);
  }
  .persona__cta-text {
    display: none;
  }
  .call__name {
    font-size: var(--fs-title-2);
    line-height: var(--lh-title-2);
  }
  .call__controls {
    gap: var(--s-3);
  }
  .call__caption {
    font-size: var(--fs-body);
    line-height: var(--lh-body);
  }
  .call__captions {
    min-height: calc(var(--lh-body) * 3);
  }
}

@media (prefers-reduced-motion: reduce) {
  .persona,
  .persona__orb,
  .ctl__btn,
  .stage-enter-active,
  .stage-leave-active {
    transition: none;
  }
  .persona:hover,
  .persona:hover .persona__orb {
    transform: none;
  }
}
</style>
