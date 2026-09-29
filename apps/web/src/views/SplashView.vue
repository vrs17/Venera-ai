<script setup lang="ts">
import { computed } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '../composables/useAuth'
import { redirectTarget } from '../router'
import AuthShell from '../components/AuthShell.vue'
import DesktopDownload from '../components/DesktopDownload.vue'
import VButton from '../ui/VButton.vue'

// Birinchi tashrif sahifasi (spec §4.2): jim, bo'sh joy ko'p. Bitta urg'u - CSS
// "Venera" shari; WebGL yulduzlar, kursor effekti va suzuvchi sayyora yo'q.
const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const { isAuthenticated } = useAuth()

// "Boshlash" darhol o'tadi - sun'iy kechikish yo'q. Chuqur havoladan kelgan bo'lsa
// (?redirect=/admin/...), manzil kirish sahifasiga uzatiladi.
const start = computed<RouteLocationRaw>(() => {
  if (isAuthenticated.value) return '/'
  const back = redirectTarget(route.query)
  return back ? { name: 'login', query: { redirect: back } } : { name: 'login' }
})
</script>

<template>
  <AuthShell width="wide" :brand="false">
    <section class="welcome" aria-labelledby="welcome-title">
      <div class="welcome__orb" aria-hidden="true" />
      <h1 id="welcome-title" class="welcome__title">Venera</h1>
      <p class="welcome__sub">{{ t('splashSub') }}</p>
      <VButton :to="start" variant="primary" size="lg" pill class="welcome__cta">{{ t('getStarted') }}</VButton>
    </section>

    <template #footer>
      <DesktopDownload variant="compact" />
    </template>
  </AuthShell>
</template>

<style scoped>
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

/* Venera shari: faqat CSS - ikki radial gradient (brend ranglari) va yumshoq halo.
   Ikkalasi psevdo-element: halo (::before) sharning (::after) OSTIDA chiziladi.
   12s "nafas" - sahifadagi yagona sokin harakat; kamaytirilgan harakatda to'xtaydi. */
.welcome__orb {
  position: relative;
  width: 96px;
  height: 96px;
  margin-bottom: var(--s-10);
}
.welcome__orb::before,
.welcome__orb::after {
  content: '';
  position: absolute;
  border-radius: var(--r-full);
}
.welcome__orb::before {
  inset: -28px;
  background: radial-gradient(circle, color-mix(in srgb, var(--brand) 20%, transparent) 0%, transparent 68%);
  animation: orb-halo 12s ease-in-out infinite;
}
.welcome__orb::after {
  inset: 0;
  background:
    radial-gradient(circle at 34% 28%, var(--brand-2) 0%, transparent 58%),
    radial-gradient(circle at 50% 50%, var(--brand) 62%, color-mix(in srgb, var(--brand) 86%, var(--serious-text)) 100%);
  box-shadow: 0 12px 32px -10px color-mix(in srgb, var(--brand) 55%, transparent);
  animation: orb-breathe 12s ease-in-out infinite;
}
@keyframes orb-breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.035);
  }
}
@keyframes orb-halo {
  0%,
  100% {
    opacity: 0.6;
    transform: scale(0.94);
  }
  50% {
    opacity: 1;
    transform: scale(1.06);
  }
}

.welcome__title {
  color: var(--text);
  font-size: var(--fs-display);
  line-height: var(--lh-display);
  font-weight: 600;
  letter-spacing: -0.028em;
}
.welcome__sub {
  max-width: 420px;
  margin-top: var(--s-3);
  color: var(--text-2);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  text-wrap: balance;
}
.welcome__cta {
  min-width: 168px;
  margin-top: var(--s-8);
}

@media (prefers-reduced-motion: reduce) {
  .welcome__orb::before,
  .welcome__orb::after {
    animation: none;
  }
}
</style>
