import { createRouter, createWebHistory } from 'vue-router'
import type { LocationQuery, RouteRecordRaw } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { loadAdminMessages } from '../i18n'

// Marshrut `meta` maydonlari turlangan: xato yozilgan kalit jimgina `undefined`
// bo'lib, himoyani o'chirib qo'ymasin.
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    guestOnly?: boolean
    allowPasswordChangeRequired?: boolean
    /** Kirmagan odam xush kelibsiz sahifasiga emas, TO'G'RI kirish sahifasiga yuboriladi. */
    loginDirect?: boolean
    /** Shu rol bo'lmasa `/` ga qaytariladi. Ota marshrutda berilsa bolalarga ham tegadi. */
    requiresRole?: string
  }
}

// Admin panel - alohida lazy bo'lak: oddiy foydalanuvchi uning kodini umuman yuklamaydi.
// `reports/:id` va `users/:id` ro'yxat sahifasining o'zi (split ko'rinish / yon varaq):
// bir xil komponent qayta yaratilmaydi, ro'yxat va aylantirish holati saqlanadi.
const adminRoutes: RouteRecordRaw = {
  path: '/admin',
  // Admin matnlari alohida bo'lak - panel ulardan oldin chizilmasin.
  component: () => loadAdminMessages().then(() => import('../admin/AdminLayout.vue')),
  meta: { requiresAuth: true, requiresRole: 'ADMIN' },
  children: [
    { path: '', name: 'admin-overview', component: () => import('../admin/pages/OverviewPage.vue') },
    {
      path: 'conversations',
      name: 'admin-conversations',
      component: () => import('../admin/pages/ConversationsPage.vue'),
    },
    { path: 'turns/:id', name: 'admin-turn', component: () => import('../admin/pages/TurnPage.vue'), props: true },
    { path: 'reports', name: 'admin-reports', component: () => import('../admin/pages/ReportsPage.vue') },
    {
      path: 'reports/:id',
      name: 'admin-report',
      component: () => import('../admin/pages/ReportsPage.vue'),
      props: true,
    },
    { path: 'users', name: 'admin-users', component: () => import('../admin/pages/UsersPage.vue') },
    { path: 'users/:id', name: 'admin-user', component: () => import('../admin/pages/UsersPage.vue'), props: true },
    { path: 'usage', name: 'admin-usage', component: () => import('../admin/pages/UsagePage.vue') },
    { path: 'versions', name: 'admin-versions', component: () => import('../admin/pages/VersionsPage.vue') },
    { path: 'migration', name: 'admin-migration', component: () => import('../admin/pages/MigrationPage.vue') },
    { path: 'system', name: 'admin-system', component: () => import('../admin/pages/SystemPage.vue') },
    // Tizim xaritasi: butun Barno AI OS kanvasda + qadamni jonli sinash. Alohida (lazy)
    // bo'lak - kanvas va sinov kodi faqat shu sahifa ochilganda yuklanadi.
    { path: 'os-map', name: 'admin-osmap', component: () => import('../admin/pages/OsMapPage.vue') },
    // Agent playground: agent bosqichlarining aniq kirishi, tahrirlab qayta ishga tushirish va
    // modellarni solishtirish (`?turn=<id>` - savol sahifasidagi "Playground'da ochish").
    { path: 'playground', name: 'admin-playground', component: () => import('../admin/pages/PlaygroundPage.vue') },
  ],
}

// Dizayn kutubxonasi galereyasi - faqat `vite dev` da. Production build'da bu shart
// `false` bo'ladi va KitView bo'lagi umuman yaratilmaydi.
const devRoutes: RouteRecordRaw[] = import.meta.env.DEV
  ? [{ path: '/_kit', name: 'kit', component: () => loadAdminMessages().then(() => import('../views/dev/KitView.vue')) }]
  : []

const routes: RouteRecordRaw[] = [
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
  // Ro'yxatdan o'tish yopiq: hisoblar HRM/CRM (SSO) dan keladi. Eski havolalar
  // o'lik sahifaga emas, kirishga olib boradi.
  { path: '/register', name: 'register', redirect: { name: 'login' } },
  {
    // Forced first-login password change. Reachable while authenticated even
    // when passwordChangeRequired is true (allowPasswordChangeRequired).
    path: '/change-password',
    name: 'change-password',
    component: () => import('../views/ChangePasswordView.vue'),
    meta: { requiresAuth: true, allowPasswordChangeRequired: true },
  },
  {
    // Slack'dagi «Connect Barno AI account» tugmasi shu yerni ochadi (`?t=<chipta>`): kirmagan odam
    // avval kirish sahifasiga (BRB-Tech ID yoki login + parol), keyin shu tasdiq sahifasiga qaytadi.
    path: '/link/slack',
    name: 'slack-link',
    component: () => import('../views/SlackLinkView.vue'),
    meta: { requiresAuth: true, loginDirect: true },
  },
  adminRoutes,
  ...devRoutes,
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

/** Kirishdan keyin qaytiladigan manzil (`?redirect=`), yaroqsiz bo'lsa `null`.
 *  Faqat ilova ichidagi yo'l: `//host/...` ochiq yo'naltirish bo'lardi, mehmon
 *  sahifalari (/login, /welcome) va /change-password esa aylanma. */
export function redirectTarget(query: LocationQuery): string | null {
  const raw = Array.isArray(query.redirect) ? query.redirect[0] : query.redirect
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return null
  const target = router.resolve(raw)
  if (target.meta.guestOnly || target.name === 'change-password') return null
  return target.fullPath
}

// Gate the app. The guard awaits bootstrap() so the first navigation resolves
// only after /auth/me has restored (or rejected) the stored session.
router.beforeEach(async (to) => {
  const { isAuthenticated, passwordChangeRequired, bootstrap, user } = useAuth()
  await bootstrap()

  // Unauthenticated: protected pages send you to the splash/landing first. Chuqur
  // havola (masalan /admin/turns/42) yo'qolmasin - kirishdan keyin shu yerga qaytiladi.
  if (to.meta.requiresAuth && !isAuthenticated.value) {
    if (to.meta.loginDirect) return { name: 'login', query: { redirect: to.fullPath } }
    return to.fullPath === '/' ? { name: 'welcome' } : { name: 'welcome', query: { redirect: to.fullPath } }
  }

  // Forced password change: an authenticated user who must change their password
  // can only reach /change-password (and logout). Everything else bounces there.
  if (isAuthenticated.value && passwordChangeRequired.value && !to.meta.allowPasswordChangeRequired) {
    // Slack ulash havolasi yo'qolmasin: parol almashtirilgach shu sahifaga qaytiladi.
    return to.meta.loginDirect
      ? { name: 'change-password', query: { redirect: to.fullPath } }
      : { name: 'change-password' }
  }

  // Settled users shouldn't sit on guest pages or the (now-irrelevant) change page.
  if (isAuthenticated.value && !passwordChangeRequired.value) {
    if (to.meta.guestOnly || to.name === 'change-password') return redirectTarget(to.query) ?? { name: 'chat' }
  }

  // Rol talab qilinadigan bo'lim (admin panel). `to.meta` - ota va bola marshrutlar
  // meta'sining birlashmasi, shuning uchun `/admin/*` ning hammasi himoyalangan.
  // Bu faqat UX: haqiqiy himoya serverda (`require_roles`, 403) - bu yerda esa
  // ruxsati yo'q odam bo'sh sahifa va xatolar o'rniga chatga qaytadi.
  const role = to.meta.requiresRole
  if (role) {
    const want = role.toUpperCase()
    const roles = user.value?.roles ?? []
    if (!roles.some((r) => r.toUpperCase() === want)) return { path: '/' }
  }

  return true
})
