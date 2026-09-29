<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { localizeApiError } from '../api/errors'
import { LockIcon, LoginIcon, UserIcon } from '../icons'
import AuthShell from '../components/AuthShell.vue'
import AuthField from '../components/AuthField.vue'
import AuthButton from '../components/AuthButton.vue'
import AuthError from '../components/AuthError.vue'

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { login } = useAuth()

const username = ref('')
const password = ref('')
const busy = ref(false)
const shell = ref<{ ignite: () => void } | null>(null)

const submitted = ref(false)
const formError = ref('')

// Login - HRM/CRM (Keycloak) hisobi, masalan `y.mamajonov`; email emas.
// Zahira hisob (users.yaml) uchun email ham shu maydonga yoziladi.
const valid = computed(() => username.value.trim().length > 0 && password.value.length > 0)
// Errors are computed and only surface once submit was attempted, so they appear
// on submit and clear live as the user fixes the field (no watcher races).
const usernameError = computed(() => (!submitted.value ? '' : username.value.trim() ? '' : t('required')))
const passwordError = computed(() => (!submitted.value ? '' : password.value ? '' : t('required')))

async function submit() {
  submitted.value = true
  formError.value = ''
  if (busy.value || !valid.value) return
  busy.value = true
  shell.value?.ignite()
  try {
    const res = await login(username.value.trim(), password.value)
    // First login returns passwordChangeRequired; the guard would bounce us
    // there anyway, but routing explicitly avoids a flash of the chat page.
    router.push(res.passwordChangeRequired ? { name: 'change-password' } : '/')
  } catch (err) {
    formError.value = localizeApiError(err, t)
    busy.value = false
  }
}
</script>

<template>
  <AuthShell ref="shell" :hero-title="t('authWelcomeBack')" :hero-sub="t('authLoginSub')">
    <form class="auth-body" novalidate @submit.prevent="submit">
      <div class="auth-head rise">
        <span class="auth-head__icon" aria-hidden="true"><LoginIcon :size="18" /></span>
        <h2 class="auth-head__title">{{ t('signIn') }}</h2>
      </div>

      <AuthError :message="formError" />

      <AuthField
        v-model="username"
        :label="t('loginName')"
        type="text"
        autocomplete="username"
        :icon="UserIcon"
        placeholder="y.mamajonov"
        :error="usernameError"
        reveal-delay="0.06s"
      />
      <AuthField
        v-model="password"
        :label="t('password')"
        type="password"
        autocomplete="current-password"
        :icon="LockIcon"
        :error="passwordError"
        reveal-delay="0.12s"
      />

      <div class="rise" style="animation-delay: 0.2s">
        <AuthButton :label="t('signIn')" :valid="valid" :busy="busy" />
      </div>

      <p class="auth-foot rise" style="animation-delay: 0.24s">
        {{ t('noAccount') }}
        <RouterLink to="/register" class="auth-link auth-link--strong">{{ t('createAccount') }}</RouterLink>
      </p>
    </form>
  </AuthShell>
</template>

<style scoped>
.auth-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.auth-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.auth-head__title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.3px;
  color: var(--text);
}
.auth-right {
  display: flex;
  justify-content: flex-end;
  margin-top: -4px;
}
.auth-link {
  font-size: 13px;
  color: var(--link);
  text-decoration: underline;
}
.auth-link:hover {
  filter: brightness(1.12);
}
.auth-link--strong {
  font-weight: 600;
}
.auth-foot {
  margin: 6px 0 0;
  text-align: center;
  font-size: 13.5px;
  color: var(--text-secondary);
}
</style>
