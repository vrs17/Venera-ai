import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const routes = [
  {
    path: '/',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/welcome',
    name: 'welcome',
    component: () => import('../views/SplashView.vue'),
    meta: { guestOnly: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { guestOnly: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('../views/RegisterView.vue'),
    meta: { guestOnly: true },
  },
  {
    // Forced first-login password change. Reachable while authenticated even
    // when passwordChangeRequired is true (allowPasswordChangeRequired).
    path: '/change-password',
    name: 'change-password',
    component: () => import('../views/ChangePasswordView.vue'),
    meta: { requiresAuth: true, allowPasswordChangeRequired: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Gate the app. The guard awaits bootstrap() so the first navigation resolves
// only after /auth/me has restored (or rejected) the stored session.
router.beforeEach(async (to) => {
  const { isAuthenticated, passwordChangeRequired, bootstrap } = useAuth()
  await bootstrap()

  // Unauthenticated: protected pages send you to the splash/landing first.
  if (to.meta.requiresAuth && !isAuthenticated.value) return { name: 'welcome' }

  // Forced password change: an authenticated user who must change their password
  // can only reach /change-password (and logout). Everything else bounces there.
  if (isAuthenticated.value && passwordChangeRequired.value && !to.meta.allowPasswordChangeRequired) {
    return { name: 'change-password' }
  }

  // Settled users shouldn't sit on guest pages or the (now-irrelevant) change page.
  if (isAuthenticated.value && !passwordChangeRequired.value) {
    if (to.meta.guestOnly || to.name === 'change-password') return { name: 'chat' }
  }

  return true
})
