// Real session auth backed by the Venera AI backend (see backend-integration
// contract). Module-level refs make this a singleton — every useAuth() call
// shares one reactive source. The opaque session token lives in localStorage
// (managed by api/http.ts, shared across tabs); this module owns the in-memory `user`.

import { computed, ref } from 'vue'
import * as authApi from '../api/auth.api'
import { clearToken, clientChannel, getToken, setToken } from '../api/http'
import type { AuthUser, ChangePasswordResponse, LoginResponse, SignupRequest, SignupResponse, SsoConfig } from '../types'

const user = ref<AuthUser | null>(null)
const initialized = ref(false)
const loading = ref(false)
// Kirish sahifasi qaysi yo'llarni ko'rsatishi (`GET /auth/sso/config`). Bir marta
// so'raladi; server javob bermasa parol shakli ko'rsatiladi (eski xulq).
const sso = ref<SsoConfig | null>(null)
const SSO_FALLBACK: SsoConfig = { enabled: false, localLoginEnabled: true, startPath: '/api/v1/auth/sso/start' }

export function useAuth() {
  const isAuthenticated = computed(() => user.value !== null)
  const passwordChangeRequired = computed(() => Boolean(user.value?.passwordChangeRequired))
  const isEmployee = computed(
    () => Boolean(user.value?.roles?.includes('EMPLOYEE')) || user.value?.actorType === 'EMPLOYEE',
  )

  // Restore the session from the stored token on first app load. Idempotent —
  // only the first call hits the network; the router guard awaits it before the
  // first navigation resolves.
  async function bootstrap(): Promise<void> {
    if (initialized.value) return
    const token = getToken()
    if (!token) {
      user.value = null
      initialized.value = true
      return
    }
    try {
      user.value = await authApi.me()
    } catch {
      // Invalid/expired token — drop it and stay logged out.
      clearToken()
      user.value = null
    } finally {
      initialized.value = true
    }
  }

  // Reconcile the in-memory user with the token in storage. Used by the
  // cross-tab sync (App.vue): when another tab logs in or out, the `storage`
  // event fires and we re-evaluate without a full reload. Unlike bootstrap(),
  // this ignores the `initialized` latch so it always re-checks.
  async function syncFromStorage(): Promise<void> {
    const token = getToken()
    if (!token) {
      user.value = null
      return
    }
    if (!user.value) {
      try {
        user.value = await authApi.me()
      } catch {
        clearToken()
        user.value = null
      }
    }
  }

  async function login(username: string, password: string): Promise<LoginResponse> {
    loading.value = true
    try {
      const res = await authApi.login({ username, password })
      setToken(res.token)
      user.value = res.user
      initialized.value = true
      return res
    } finally {
      loading.value = false
    }
  }

  /** Kirish sahifasi uchun sozlama: SSO yoqilganmi, parol shakli bormi. */
  async function loadSsoConfig(): Promise<SsoConfig> {
    if (sso.value) return sso.value
    try {
      sso.value = await authApi.ssoConfig()
    } catch {
      sso.value = SSO_FALLBACK
    }
    return sso.value
  }

  /** Brauzerni Keycloak kirish sahifasiga yuboradi. Sahifa shu yerda tugaydi:
   *  qaytganda LoginView `?sso=<kod>` ni ko'rib `completeSso` ni chaqiradi. */
  function startSso(returnTo: string | null): void {
    const cfg = sso.value
    if (!cfg?.enabled) return
    window.location.assign(authApi.ssoStartUrl(cfg.startPath, returnTo, clientChannel()))
  }

  /** Callback bergan bir martalik kod -> sessiya (token + user). */
  async function completeSso(code: string): Promise<LoginResponse> {
    loading.value = true
    try {
      const res = await authApi.ssoExchange(code)
      setToken(res.token)
      user.value = res.user
      initialized.value = true
      return res
    } finally {
      loading.value = false
    }
  }

  /** Create an account. No token/auto-login per the contract — the backend
   *  emails a temporary password and the user signs in afterwards. */
  function signup(data: SignupRequest): Promise<SignupResponse> {
    return authApi.signup(data)
  }

  async function changePassword(currentPassword: string, newPassword: string): Promise<ChangePasswordResponse> {
    loading.value = true
    try {
      const res = await authApi.changePassword({ currentPassword, newPassword })
      user.value = res.user
      return res
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    let ssoLogoutUrl: string | null | undefined
    try {
      ssoLogoutUrl = (await authApi.logout()).ssoLogoutUrl
    } catch {
      // Even if the server call fails, clear the local session.
    } finally {
      clearToken()
      user.value = null
    }
    // SSO bilan kirilgan bo'lsa Keycloak sessiyasi ham yopilsin - aks holda
    // "Kirish" tugmasi odamni so'ramasdan qaytadan kiritadi (umumiy kompyuter).
    if (ssoLogoutUrl) window.location.assign(ssoLogoutUrl)
  }

  return {
    user,
    initialized,
    loading,
    sso,
    isAuthenticated,
    passwordChangeRequired,
    isEmployee,
    bootstrap,
    syncFromStorage,
    login,
    loadSsoConfig,
    startSso,
    completeSso,
    signup,
    changePassword,
    logout,
  }
}
