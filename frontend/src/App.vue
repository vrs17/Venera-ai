<script setup lang="ts">
// Root shell — hosts the router. Each route renders its own full-screen view
// (the splash, the chat app, or the auth pages). RouterView is wrapped in a
// Transition so navigations fade (out-in) instead of hard-cutting.
//
// Cross-tab auth sync: the session token lives in localStorage (shared across
// tabs/windows). The `storage` event fires in OTHER tabs when it changes, so
// logging in or out in one tab is reflected everywhere — no manual refresh, and
// no needless re-login when opening the app in a new window.
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './composables/useAuth'
import { TOKEN_KEY } from './api/http'

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
  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>
</template>

<style>
/* Global page fade between routes. These classes land on each view's ROOT element,
   so the block must stay unscoped (a scoped style wouldn't match the view's scope). */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.25s ease;
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
