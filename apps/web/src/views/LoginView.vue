<script setup lang="ts">
// Kirish sahifasi - ikki yo'l (`GET /auth/sso/config` aytadi qaysi biri ochiq):
//
//   1. SSO (Keycloak, brauzer orqali): tugma odamni Keycloak kirish sahifasiga
//      yuboradi (`startSso`). Keycloak qaytarganda server bizni shu sahifaga
//      `?sso=<bir martalik kod>` bilan yo'naltiradi - kod sessiyaga almashtiriladi
//      (`completeSso`). Xato bo'lsa `?sso_error=<sabab>` keladi.
//   2. Zahira hisob (`users.yaml`): login + parol shakli, faqat `localLoginEnabled`.
//
// Parol SSO yo'lida bu sahifadan HECH QACHON o'tmaydi.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { authErrorKind, localizeAuthError } from '../api/errors'
import { ApiError } from '../api/http'
import { redirectTarget } from '../router'
import type { SsoErrorCode } from '../types'
import AuthShell from '../components/AuthShell.vue'
import AuthField from '../components/AuthField.vue'
import AuthButton from '../components/AuthButton.vue'
import AuthError from '../components/AuthError.vue'
import VButton from '../ui/VButton.vue'

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const { login, sso, loadSsoConfig, startSso, completeSso } = useAuth()

const SSO_ERRORS: SsoErrorCode[] = ['denied', 'blocked', 'expired', 'network', 'config', 'failed']

// --- SSO ---
const ssoReady = ref(false)
const ssoBusy = ref<'' | 'redirecting' | 'finishing'>('')
const ssoError = ref<SsoErrorCode | ''>('')
const showSso = computed(() => Boolean(sso.value?.enabled))
const showLocal = computed(() => sso.value?.localLoginEnabled !== false)

function queryString(key: string): string {
  const raw = route.query[key]
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' ? value : ''
}

function ssoErrorOf(raw: string): SsoErrorCode {
  return (SSO_ERRORS as string[]).includes(raw) ? (raw as SsoErrorCode) : 'failed'
}

function signInWithSso() {
  if (ssoBusy.value) return
  ssoError.value = ''
  ssoBusy.value = 'redirecting'
  startSso(redirectTarget(route.query))
}

async function finishSso(code: string) {
  ssoBusy.value = 'finishing'
  try {
    await completeSso(code)
    // `?sso=` manzilda qolmasin (yangilash kodni qayta yubormasin) - replace.
    router.replace(redirectTarget(route.query) ?? '/')
  } catch (err) {
    ssoError.value = err instanceof ApiError ? 'expired' : 'network'
    ssoBusy.value = ''
    router.replace({ name: 'login', query: { ...route.query, sso: undefined } })
  }
}

// --- zahira hisob ---
const username = ref('')
const password = ref('')
const busy = ref(false)

const submitted = ref(false)
const formError = ref('')
// Keycloak "hisob to'liq sozlanmagan": parol to'g'ri, odam CRM saytiga bir marta
// brauzerda kirishi kerak. Havola manzili build vaqtida beriladi (VITE_CRM_URL);
// berilmasa ko'rsatma havolasiz chiqadi.
const setupHelp = ref(false)
const crmUrl = ((import.meta.env.VITE_CRM_URL as string | undefined) ?? '').trim()

const loginField = ref<InstanceType<typeof AuthField> | null>(null)
const passwordField = ref<InstanceType<typeof AuthField> | null>(null)

const valid = computed(() => username.value.trim().length > 0 && password.value.length > 0)
// Errors are computed and only surface once submit was attempted, so they appear
// on submit and clear live as the user fixes the field (no watcher races).
const usernameError = computed(() => (!submitted.value ? '' : username.value.trim() ? '' : t('required')))
const passwordError = computed(() => (!submitted.value ? '' : password.value ? '' : t('required')))

// Server xatosi eskirmasin: odam maydonni tuzata boshlashi bilan yo'qoladi.
watch([username, password], () => {
  formError.value = ''
  setupHelp.value = false
})

// Sozlama so'rovi yiqilgan bo'lsa (API qayta ishga tushayotgan soniyalar) sahifa ochiq
// turganda ham qayta so'raladi - aks holda SSO tugmasi qayta yuklanguncha ko'rinmasdi.
let ssoRetryTimer: number | undefined
function retrySsoConfig(left: number): void {
  if (sso.value || left <= 0) return
  ssoRetryTimer = window.setTimeout(async () => {
    await loadSsoConfig()
    retrySsoConfig(left - 1)
  }, 2000)
}
onBeforeUnmount(() => window.clearTimeout(ssoRetryTimer))

onMounted(async () => {
  await loadSsoConfig()
  ssoReady.value = true
  retrySsoConfig(5)
  const code = queryString('sso')
  if (code) {
    await finishSso(code)
    return
  }
  const failed = queryString('sso_error')
  if (failed) ssoError.value = ssoErrorOf(failed)
  // Faqat sichqonchali qurilmada va parol shakli bo'lsa: telefonda klaviatura
  // o'zi ochilib, sahifani yopmasin.
  if (showLocal.value && !showSso.value && window.matchMedia('(pointer: fine)').matches) loginField.value?.focus()
})

async function submit() {
  submitted.value = true
  formError.value = ''
  setupHelp.value = false
  if (busy.value) return
  if (!valid.value) {
    // Birinchi bo'sh maydonga - odam nimani to'ldirishini qidirib o'tirmasin.
    ;(username.value.trim() ? passwordField : loginField).value?.focus()
    return
  }
  busy.value = true
  try {
    const res = await login(username.value.trim(), password.value)
    const back = redirectTarget(route.query)
    // First login returns passwordChangeRequired; the guard would bounce us
    // there anyway, but routing explicitly avoids a flash of the chat page.
    if (res.passwordChangeRequired) {
      router.push({ name: 'change-password', query: back ? { redirect: back } : undefined })
    } else {
      router.push(back ?? '/')
    }
  } catch (err) {
    formError.value = localizeAuthError(err, t)
    setupHelp.value = authErrorKind(err) === 'accountSetup'
    busy.value = false
  }
}
</script>

<template>
  <AuthShell :title="t('signIn')" :caption="showSso ? t('shell.auth.sso.caption') : t('shell.auth.caption')">
    <div v-if="ssoReady" class="auth-form">
      <!-- SSO tugmasi ko'rinmasa ham (sozlama o'qilmadi) kirish xatosi aytilsin. -->
      <AuthError v-if="!showSso" :message="ssoError ? t(`shell.auth.sso.${ssoError}`) : ''" />
      <template v-if="showSso">
        <VButton
          type="button"
          variant="primary"
          size="lg"
          block
          pill
          :loading="ssoBusy !== ''"
          data-testid="sso-login"
          @click="signInWithSso"
        >
          {{ ssoBusy ? t(`shell.auth.sso.${ssoBusy}`) : t('shell.auth.sso.button') }}
        </VButton>
        <AuthError :message="ssoError ? t(`shell.auth.sso.${ssoError}`) : ''" />
        <div v-if="showLocal" class="auth-form__divider" role="separator">
          <span>{{ t('shell.auth.sso.or') }}</span>
        </div>
      </template>

      <form v-if="showLocal" class="auth-form" novalidate @submit.prevent="submit">
        <div class="auth-form__fields">
          <AuthField
            ref="loginField"
            v-model="username"
            :label="t('loginName')"
            type="text"
            name="username"
            autocomplete="username"
            autocapitalize="none"
            autocorrect="off"
            spellcheck="false"
            :error="usernameError"
          />
          <AuthField
            ref="passwordField"
            v-model="password"
            :label="t('password')"
            type="password"
            name="password"
            autocomplete="current-password"
            :error="passwordError"
          />
        </div>

        <AuthButton :label="t('signIn')" :busy="busy" />

        <AuthError :message="formError">
          <a v-if="setupHelp && crmUrl" :href="crmUrl" target="_blank" rel="noopener noreferrer">
            {{ t('shell.auth.openCrm') }}
          </a>
        </AuthError>
      </form>

      <AuthError v-if="!showSso && !showLocal" :message="t('shell.auth.sso.config')" />
    </div>
  </AuthShell>
</template>

<style scoped>
.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
}
.auth-form__fields {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
}
.auth-form__divider {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.auth-form__divider::before,
.auth-form__divider::after {
  content: '';
  flex: 1;
  border-top: 1px solid var(--line-strong);
}
</style>
