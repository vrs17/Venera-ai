<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { localizeApiError } from '../api/errors'
import { KeyIcon, LockIcon } from '../icons'
import AuthShell from '../components/AuthShell.vue'
import AuthField from '../components/AuthField.vue'
import AuthButton from '../components/AuthButton.vue'
import AuthError from '../components/AuthError.vue'
import PasswordStrength from '../components/PasswordStrength.vue'

// Forced first-login password change: replace the emailed temporary password
// with the user's own. Backend rules: >=8 chars, >=1 letter, >=1 digit, and
// different from the current password.
const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { changePassword, logout } = useAuth()

const current = ref('')
const next = ref('')
const confirm = ref('')
const busy = ref(false)
const submitted = ref(false)
const formError = ref('')
const shell = ref<{ ignite: () => void } | null>(null)

const hasLetter = (s: string) => /[A-Za-z]/.test(s)
const hasDigit = (s: string) => /\d/.test(s)
const newValid = computed(
  () => next.value.length >= 8 && hasLetter(next.value) && hasDigit(next.value) && next.value !== current.value,
)
const valid = computed(() => current.value.length > 0 && newValid.value && confirm.value === next.value)

const currentError = computed(() => (!submitted.value ? '' : current.value ? '' : t('required')))
const newError = computed(() => {
  if (!submitted.value) return ''
  if (!next.value) return t('required')
  if (next.value.length < 8) return t('passwordTooShort')
  if (!hasLetter(next.value) || !hasDigit(next.value)) return t('passwordNeedsLetterDigit')
  if (next.value === current.value) return t('mustDifferFromCurrent')
  return ''
})
const confirmError = computed(() =>
  !submitted.value ? '' : !confirm.value ? t('required') : confirm.value !== next.value ? t('passwordMismatch') : '',
)

async function submit() {
  submitted.value = true
  formError.value = ''
  if (busy.value || !valid.value) return
  busy.value = true
  shell.value?.ignite()
  try {
    await changePassword(current.value, next.value)
    router.push('/')
  } catch (err) {
    formError.value = localizeApiError(err, t)
    busy.value = false
  }
}

// Escape hatch: while a password change is forced, logout is the only other
// allowed action.
async function onSignOut() {
  await logout()
  router.push({ name: 'welcome' })
}
</script>

<template>
  <AuthShell ref="shell" :hero-title="t('authChangeTitle')" :hero-sub="t('authChangeSub')">
    <form class="auth-body" novalidate @submit.prevent="submit">
      <div class="auth-head rise">
        <span class="auth-head__icon" aria-hidden="true"><KeyIcon :size="18" /></span>
        <h2 class="auth-head__title">{{ t('changePassword') }}</h2>
      </div>

      <AuthError :message="formError" />

      <AuthField
        v-model="current"
        :label="t('currentPassword')"
        type="password"
        autocomplete="current-password"
        :icon="LockIcon"
        :error="currentError"
        reveal-delay="0.04s"
      />
      <AuthField
        v-model="next"
        :label="t('newPassword')"
        type="password"
        autocomplete="new-password"
        :icon="LockIcon"
        :error="newError"
        reveal-delay="0.1s"
      />
      <PasswordStrength :password="next" />
      <AuthField
        v-model="confirm"
        :label="t('confirmPassword')"
        type="password"
        autocomplete="new-password"
        :icon="LockIcon"
        :error="confirmError"
        reveal-delay="0.16s"
      />

      <div class="rise" style="animation-delay: 0.2s">
        <AuthButton :label="t('changePassword')" :valid="valid" :busy="busy" />
      </div>

      <p class="auth-foot rise" style="animation-delay: 0.24s">
        <button type="button" class="auth-link auth-link--strong" @click="onSignOut">{{ t('logout') }}</button>
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
.auth-foot {
  margin: 6px 0 0;
  text-align: center;
}
.auth-link {
  font-size: 13px;
  color: var(--link);
  text-decoration: underline;
  background: none;
  border: none;
  cursor: pointer;
  font-family: 'Figtree', sans-serif;
}
.auth-link:hover {
  filter: brightness(1.12);
}
.auth-link--strong {
  font-weight: 600;
}
</style>
