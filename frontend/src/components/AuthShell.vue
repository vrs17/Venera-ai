<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { applyTheme, getInitialTheme } from '../theme'
import { MoonIcon, SunIcon } from '../icons'
import LanguageSwitcher from './LanguageSwitcher.vue'
import AuthAurora from './AuthAurora.vue'

defineProps<{ heroTitle: string; heroSub: string }>()

const { t } = useI18n({ useScope: 'global' })

// The auth pages own theme state the same way ChatView does; applyTheme persists
// to localStorage so the chat picks up the same theme after sign-in.
const theme = ref(getInitialTheme())
watch(theme, (v) => applyTheme(v), { immediate: true })
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

// Ignition bloom — views call ignite() on a successful step.
const igniting = ref(false)
let ignitionTimer: ReturnType<typeof setTimeout> | undefined
function ignite() {
  igniting.value = false
  // next tick so the animation re-triggers even on rapid successive calls
  requestAnimationFrame(() => {
    igniting.value = true
    clearTimeout(ignitionTimer)
    ignitionTimer = setTimeout(() => {
      igniting.value = false
    }, 760)
  })
}
onBeforeUnmount(() => clearTimeout(ignitionTimer))

defineExpose({ ignite })
</script>

<template>
  <div class="auth-root">
    <!-- Brand hero -->
    <section class="auth-hero">
      <AuthAurora />
      <div class="auth-hero__content">
        <div class="auth-hero__brand">
          Venera
          <span class="auth-hero__spark-sm" aria-hidden="true">✦</span>
        </div>

        <div class="auth-hero__center">
          <div class="auth-hero__mark">
            <span class="hero-spark" :class="{ 'is-igniting': igniting }" aria-hidden="true">✦</span>
            <span v-if="igniting" class="ignition-ring" />
          </div>
          <h1 class="auth-hero__title">{{ heroTitle }}</h1>
          <p class="auth-hero__sub">{{ heroSub }}</p>
        </div>

        <div class="auth-hero__legal">© Venera</div>
      </div>
    </section>

    <!-- Form -->
    <section class="auth-form">
      <div class="glass auth-card">
        <slot />
      </div>
    </section>

    <!-- Theme + language, fixed top-right on every breakpoint -->
    <div class="auth-controls">
      <LanguageSwitcher />
      <button
        class="glass glass-hover auth-theme-btn"
        :title="theme === 'dark' ? t('themeToLight') : t('themeToDark')"
        :aria-label="t('toggleTheme')"
        @click="toggleTheme"
      >
        <SunIcon v-if="theme === 'dark'" />
        <MoonIcon v-else />
      </button>
    </div>
  </div>
</template>

<style scoped>
.auth-root {
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
  display: flex;
  /* No fadeUp animation here: a forwards-filling animation holds opacity at 1
     and would block the App-level route crossfade (mode=out-in) from ever
     finishing its leave. The route transition supplies the entrance instead. */
}

.auth-hero {
  position: relative;
  overflow: hidden;
  flex: 1.08 1 0;
  display: flex;
  border-right: 1px solid var(--border-faint);
}
.auth-hero__content {
  position: relative;
  z-index: 1;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: 48px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.auth-hero__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.auth-hero__spark-sm {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
}
.auth-hero__center {
  max-width: 460px;
}
.auth-hero__mark {
  position: relative;
  display: inline-flex;
  width: 56px;
  height: 56px;
  align-items: center;
  justify-content: center;
  margin-bottom: 6px;
}
.hero-spark {
  font-size: 56px;
  line-height: 1;
  color: var(--accent);
}
.hero-spark.is-igniting {
  animation: sparkBloom 0.72s ease;
}
.ignition-ring {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  border: 2px solid var(--accent);
  pointer-events: none;
  animation: ignitionRing 0.72s ease-out forwards;
}
.auth-hero__title {
  font-size: 46px;
  font-weight: 600;
  letter-spacing: -0.5px;
  margin: 14px 0 10px;
  background-image: var(--greeting-grad);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: shimmer 7s linear infinite;
}
.auth-hero__sub {
  margin: 0;
  font-size: 16px;
  line-height: 1.5;
  color: var(--text-secondary);
  max-width: 380px;
}
.auth-hero__legal {
  font-size: 12px;
  color: var(--text-muted);
}

.auth-form {
  flex: 1 1 0;
  position: relative;
  display: flex;
  /* Scroll the form column (not the whole page) when a tall card exceeds the
     viewport; margin:auto on the card centers it when there's room and lets it
     scroll from the top when there isn't (avoids the flex-centering clip). */
  overflow-y: auto;
  padding: 40px;
  box-sizing: border-box;
}
.auth-card {
  position: relative;
  margin: auto;
  width: 100%;
  max-width: 420px;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 24px;
  box-shadow: var(--glass-shadow);
  padding: 40px;
  box-sizing: border-box;
  overflow: hidden;
}

.auth-controls {
  position: absolute;
  top: 14px;
  right: 16px;
  z-index: 50;
  display: flex;
  align-items: center;
  gap: 10px;
}
.auth-theme-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 50%;
  cursor: pointer;
  box-shadow: var(--glass-shadow);
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

@media (prefers-reduced-motion: reduce) {
  .auth-hero__title {
    animation: none !important;
  }
}

@media (max-width: 880px) {
  .auth-root {
    flex-direction: column;
  }
  .auth-hero {
    flex: none;
    height: 184px;
    border-right: none;
    border-bottom: 1px solid var(--border-faint);
  }
  .auth-hero__content {
    padding: 22px 24px;
    justify-content: center;
    gap: 6px;
  }
  .auth-hero__legal {
    display: none;
  }
  .auth-hero__mark {
    display: none;
  }
  .auth-hero__center {
    margin-top: 8px;
  }
  .auth-hero__title {
    font-size: 30px;
    margin: 6px 0 4px;
  }
  .auth-hero__sub {
    font-size: 14px;
  }
  .auth-form {
    flex: 1 1 auto;
    align-items: flex-start;
    padding: 22px 16px 36px;
  }
  .auth-card {
    margin: 0 auto;
    max-width: 440px;
    padding: 28px 22px;
  }
}
</style>
