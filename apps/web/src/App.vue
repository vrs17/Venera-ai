<script setup lang="ts">
// Root shell — hosts the router. Each route renders its own full-screen view
// (the splash, the chat app, or the auth pages). RouterView is wrapped in a
// Transition so navigations cross-fade instead of hard-cutting.
//
// Cross-tab auth sync: the session token lives in localStorage (shared across
// tabs/windows). The `storage` event fires in OTHER tabs when it changes, so
// logging in or out in one tab is reflected everywhere — no manual refresh, and
// no needless re-login when opening the app in a new window.
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './composables/useAuth'
import { TOKEN_KEY } from './api/http'
// To'g'ridan-to'g'ri fayldan: `./ui` indeksi butun kutubxonani asosiy bo'lakka tortmasin.
import VToastHost from './ui/VToast.vue'

const router = useRouter()
const route = useRoute()
const { isAuthenticated, passwordChangeRequired, syncFromStorage } = useAuth()

async function onStorage(e: StorageEvent) {
  // e.key is null when localStorage.clear() ran; otherwise react only to the token.
  if (e.key !== null && e.key !== TOKEN_KEY) return
  await syncFromStorage()
  if (!isAuthenticated.value) {
    if (route.meta.requiresAuth) router.push({ name: 'welcome' })
  } else if (passwordChangeRequired.value) {
    if (route.name !== 'change-password') router.push({ name: 'change-password' })
  } else if (route.meta.guestOnly) {
    router.push({ name: 'chat' })
  }
}
onMounted(() => window.addEventListener('storage', onStorage))
onBeforeUnmount(() => window.removeEventListener('storage', onStorage))
</script>

<template>
  <!-- `mode` yo'q (bir vaqtda): eski sahifa yangisining USTIDA so'nadi, orada bo'sh
       "nafas" bo'lmaydi. Har bir sahifa bitta ildiz element bo'lishi shart. -->
  <RouterView v-slot="{ Component }">
    <Transition name="page">
      <component :is="Component" />
    </Transition>
  </RouterView>
  <!-- Bildirishnomalar joyi - butun ilovada BIR marta. -->
  <VToastHost />
</template>

<style>
/* Global page fade between routes. These classes land on each view's ROOT element,
   so the block must stay unscoped (a scoped style wouldn't match the view's scope). */
.page-enter-active,
.page-leave-active {
  transition: opacity 140ms var(--ease-out);
}
/* Chiqayotgan sahifa oqimdan olinadi va yangisining ustida qoladi: ikkala sahifa
   bir-birining ostiga tushib, bir lahza sakramasin. `!important` - sahifa ildizidagi
   scoped `position: relative` (sinf + atribut, kuchliroq) buni bosib ketmasin; sinf
   atigi 140ms yashaydi. */
.page-leave-active {
  position: fixed !important;
  inset: 0 !important;
  z-index: 1 !important;
  overflow: hidden !important;
  pointer-events: none;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .page-enter-active,
  .page-leave-active {
    transition: none;
  }
}
</style>
