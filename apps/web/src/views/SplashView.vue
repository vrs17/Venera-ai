<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import Galaxy from '../components/Galaxy.vue'
// Venus disc, pre-cropped to a transparent circle so it composites over the
// starfield instead of sitting on it as a black square.
import planetUrl from '../assets/venera-planet.webp'
import DesktopDownload from '../components/DesktopDownload.vue'

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()

// "Boshlash" gives a tactile press (the button dips) + a soft light-red glow that
// spreads out from behind the button, then navigates after a short beat instead of
// jumping abruptly. The glow + dip are CSS-driven off `activating` (no manual DOM).
const activating = ref(false)
let navTimer: ReturnType<typeof setTimeout> | undefined
function startGetStarted() {
  if (activating.value) return
  activating.value = true
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  navTimer = window.setTimeout(() => router.push('/login'), reduce ? 160 : 520)
}
onUnmounted(() => clearTimeout(navTimer))
</script>

<template>
  <div class="splash dark-zone">
    <!-- Cursor-interactive starfield. .splash__galaxy is pointer-events:none (never
         blocks the CTA/controls); Galaxy listens on window so it reacts everywhere. -->
    <div class="splash__galaxy" aria-hidden="true">
      <Galaxy
        :mouse-interaction="true"
        :mouse-repulsion="true"
        :density="1"
        :glow-intensity="0.15"
        :saturation="0"
        :star-speed="0.3"
        :speed="1"
        :twinkle-intensity="0.3"
        :rotation-speed="0.05"
        :repulsion-strength="2"
        :transparent="true"
      />
    </div>

    <div class="splash__controls">
      <LanguageSwitcher />
    </div>

    <!-- Venus, the planet the product is named after, anchored low on the right.
         Its own clipping layer so the disc can sit close to the edge without ever
         widening the page, and so it stacks between the starfield and the copy. -->
    <div class="splash__planet-layer" aria-hidden="true">
      <div class="splash__planet">
        <span class="splash__planet-glow" />
        <img
          class="splash__planet-img"
          :src="planetUrl"
          alt=""
          width="512"
          height="512"
          decoding="async"
          fetchpriority="high"
        />
      </div>
    </div>

    <div class="splash__content">
      <div class="splash__brand">
        Venera
        <span class="splash__spark" aria-hidden="true">✦</span>
      </div>
      <h1 class="splash__title">{{ t('splashTagline') }}</h1>
      <p class="splash__sub">{{ t('splashSub') }}</p>
      <div class="splash__cta-wrap">
        <span class="splash__cta-glow" :class="{ 'is-on': activating }" aria-hidden="true" />
        <button
          class="splash__cta"
          :class="{ 'is-activating': activating }"
          @click="startGetStarted"
        >
          <span class="splash__cta-label">{{ t('getStarted') }}</span>
        </button>
      </div>

      <DesktopDownload />
    </div>
  </div>
</template>

<style scoped>
/* min-height (height emas) + overflow:hidden olib tashlandi: yuklab olish bloki
   qo'shilgach kontent past ekranda 100vh dan oshadi va `height` uni kesib
   tashlardi. Galaktika o'zining .splash__galaxy konteynerida allaqachon
   qirqiladi, shuning uchun bu yerda clip kerak emas. */
.splash {
  position: relative;
  min-height: 100vh;
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 56px 0;
}
.splash__galaxy {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  /* Always-dark hero: a neutral black radial (no blue/indigo). White stars read
     clearly on black; the splash subtree is forced dark via .dark-zone. */
  background: radial-gradient(ellipse 90% 80% at 50% 42%, #181818, #0d0d0d 60%, #000000);
}
.splash__controls {
  position: absolute;
  top: 14px;
  right: 16px;
  z-index: 50;
  display: flex;
  align-items: center;
  gap: 10px;
}
.splash__content {
  position: relative;
  z-index: 2;
  text-align: center;
  padding: 24px;
  max-width: 640px;
  /* Let the fluid react to the cursor even over the copy; CTA re-enables clicks. */
  pointer-events: none;
  animation: fadeUp 0.6s ease both;
}
/* Clipping layer for the planet. Own stacking level: above the starfield (0),
   below the copy (2). overflow:hidden means the disc can sit hard against the
   right edge without ever adding a horizontal scrollbar — .splash itself must
   stay unclipped so tall content can grow past 100vh. */
.splash__planet-layer {
  position: absolute;
  inset: 0;
  z-index: 1;
  overflow: hidden;
  pointer-events: none;
}
/* Venus, parked on the right at mid-height and drifting slowly up toward the
   centre. `top: 50%` + the -50% in every keyframe keeps it vertically centred at
   any size, so the base transform and the animated one never fight. The drift is
   bounded (alternate, no fill) so the disc always stays fully on screen. */
.splash__planet {
  position: absolute;
  right: clamp(12px, 5vw, 96px);
  top: 50%;
  display: inline-flex;
  transform: translate(0, -50%);
  will-change: transform;
  animation: planetDrift 30s ease-in-out infinite alternate;
}
.splash__planet-img {
  position: relative;
  z-index: 1;
  display: block;
  width: clamp(190px, 21vw, 300px);
  height: auto;
  aspect-ratio: 1;
  border-radius: 50%;
  filter: drop-shadow(0 0 28px rgba(226, 148, 62, 0.32));
}
/* Sits behind the disc and bleeds past it, so the planet lights the space
   around itself instead of ending on a hard edge. */
.splash__planet-glow {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 200%;
  height: 200%;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(
    circle,
    rgba(232, 156, 68, 0.26) 0%,
    rgba(232, 156, 68, 0.1) 40%,
    transparent 68%
  );
}
/* Right-of-centre -> up and in toward the centre, then back. Deliberately small
   offsets: enough to read as motion over half a minute, never enough to push the
   disc off an edge or park it behind the headline. */
@keyframes planetDrift {
  0% {
    transform: translate(0, -50%);
  }
  100% {
    transform: translate(-7vw, calc(-50% - 13vh));
  }
}
.splash__brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 22px;
}
.splash__spark {
  font-weight: 700;
  color: var(--accent);
}
.splash__title {
  margin: 0 0 14px;
  font-size: 56px;
  font-weight: 600;
  letter-spacing: -1px;
  background-image: var(--greeting-grad);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: shimmer 7s linear infinite;
}
.splash__sub {
  margin: 0 auto 32px;
  max-width: 440px;
  font-size: 18px;
  line-height: 1.5;
  color: var(--text-secondary);
}
/* Wrapper has NO overflow clip, so the press glow can bloom OUT past the button. */
.splash__cta-wrap {
  position: relative;
  display: inline-flex;
}
/* Soft light-red glow that spreads from behind the button on press. */
.splash__cta-glow {
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 60%, transparent);
  filter: blur(14px);
  opacity: 0;
  pointer-events: none;
}
.splash__cta-glow.is-on {
  animation: ctaGlowSpread 0.62s ease-out;
}
@keyframes ctaGlowSpread {
  0% {
    transform: scale(0.6);
    opacity: 0;
  }
  35% {
    opacity: 0.9;
  }
  100% {
    transform: scale(1.5);
    opacity: 0;
  }
}
/* Enterprise outlined button: white surface, red label + hair-thin red border,
   clean elevation, and a faint red state-layer on hover/press (the "effect of red"
   without a heavy red fill). White is hardcoded since the splash hero is always dark. */
.splash__cta {
  pointer-events: auto;
  position: relative;
  z-index: 1;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in srgb, var(--accent) 42%, transparent);
  border-radius: 999px;
  padding: 13px 30px;
  font-size: 15px;
  font-weight: 600;
  font-family: 'Figtree', sans-serif;
  letter-spacing: 0.2px;
  color: var(--accent);
  background: #fff;
  cursor: pointer;
  transition: transform 0.1s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1), 0 1px 3px 1px rgba(0, 0, 0, 0.06);
}
.splash__cta::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--accent);
  opacity: 0;
  transition: opacity 0.2s ease;
  pointer-events: none;
}
.splash__cta-label {
  position: relative;
  z-index: 1;
}
.splash__cta:hover {
  border-color: color-mix(in srgb, var(--accent) 70%, transparent);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12), 0 2px 6px 2px rgba(0, 0, 0, 0.08);
}
.splash__cta:hover::before {
  opacity: 0.06;
}
.splash__cta:active::before {
  opacity: 0.1;
}
.splash__cta:active {
  transform: scale(0.98);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}
.splash__cta:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent);
}
/* Click feedback: hold the pressed dip; the red glow (.splash__cta-glow.is-on)
   blooms from behind. The button itself stays white. */
.splash__cta.is-activating {
  transform: scale(0.98);
  cursor: default;
}
@media (max-width: 768px) {
  .splash__title {
    font-size: 38px;
  }
  .splash__sub {
    font-size: 16px;
  }
  /* Narrow screens: the copy and the download cards run the full width, so the
     disc sits directly behind them. Keep it whole and in place, but ease it back
     and shorten the drift so it reads as depth rather than competing with text. */
  .splash__planet {
    right: clamp(4px, 2vw, 16px);
    opacity: 0.5;
    animation-name: planetDriftNarrow;
  }
  .splash__planet-img {
    width: clamp(150px, 34vw, 200px);
  }
}
@keyframes planetDriftNarrow {
  0% {
    transform: translate(0, -50%);
  }
  100% {
    transform: translate(-3vw, calc(-50% - 7vh));
  }
}
@media (prefers-reduced-motion: reduce) {
  .splash__title,
  .splash__content,
  .splash__cta-glow,
  .splash__planet {
    animation: none !important;
  }
}
</style>
