<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuth } from '../composables/useAuth'
import { localizeApiError } from '../api/errors'
import { MailIcon, UserIcon, UserPlusIcon } from '../icons'
import AuthShell from '../components/AuthShell.vue'
import AuthField from '../components/AuthField.vue'
import AuthButton from '../components/AuthButton.vue'
import AuthError from '../components/AuthError.vue'

// Signup per the backend contract: collect identity only — the backend
// generates a temporary password and emails it. No password is set here.
const { t } = useI18n({ useScope: 'global' })
const { signup } = useAuth()

const email = ref('')
const fullName = ref('')
const position = ref('')
const department = ref('')
const busy = ref(false)
const submitted = ref(false)
const formError = ref('')
const done = ref(false)
const shell = ref<{ ignite: () => void } | null>(null)

const emailValid = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim()))
const valid = computed(() => emailValid.value && fullName.value.trim().length > 0)
const emailError = computed(() =>
  !submitted.value ? '' : !email.value.trim() ? t('required') : emailValid.value ? '' : t('emailInvalid'),
)
const fullNameError = computed(() => (!submitted.value ? '' : fullName.value.trim() ? '' : t('required')))

async function submit() {
  submitted.value = true
  formError.value = ''
  if (busy.value || !valid.value) return
  busy.value = true
  shell.value?.ignite()
  try {
    await signup({
      email: email.value.trim(),
      fullName: fullName.value.trim(),
      position: position.value.trim() || undefined,
      department: department.value.trim() || undefined,
    })
    done.value = true
  } catch (err) {
    formError.value = localizeApiError(err, t)
    busy.value = false
  }
}
</script>

<template>
  <AuthShell ref="shell" :hero-title="t('authCreateAccount')" :hero-sub="t('authRegisterSub')">
    <!-- Success: account created, temporary password emailed -->
    <div v-if="done" class="auth-body">
      <div class="auth-head rise">
        <span class="auth-head__icon" aria-hidden="true"><MailIcon :size="18" /></span>
        <h2 class="auth-head__title">{{ t('accountCreatedTitle') }}</h2>
      </div>
      <p class="signup-done rise" style="animation-delay: 0.06s">{{ t('accountCreatedBody', { email: email.trim() }) }}</p>
      <div class="rise" style="animation-delay: 0.12s">
        <RouterLink to="/login" class="auth-cta">{{ t('goToSignIn') }}</RouterLink>
      </div>
    </div>

    <!-- Signup form -->
    <form v-else class="auth-body" novalidate @submit.prevent="submit">
      <div class="auth-head rise">
        <span class="auth-head__icon" aria-hidden="true"><UserPlusIcon :size="18" /></span>
        <h2 class="auth-head__title">{{ t('createAccount') }}</h2>
      </div>

      <AuthError :message="formError" />

      <AuthField
        v-model="email"
        :label="t('email')"
        type="email"
        autocomplete="email"
        :icon="MailIcon"
        placeholder="you@venera.uz"
        :error="emailError"
        reveal-delay="0.04s"
      />
      <AuthField
        v-model="fullName"
        :label="t('fullName')"
        autocomplete="name"
        :icon="UserIcon"
        :error="fullNameError"
        reveal-delay="0.08s"
      />
      <div class="auth-grid">
        <AuthField v-model="position" :label="t('position')" autocomplete="organization-title" reveal-delay="0.12s" />
        <AuthField v-model="department" :label="t('department')" autocomplete="organization" reveal-delay="0.16s" />
      </div>

      <div class="rise" style="animation-delay: 0.2s">
        <AuthButton :label="t('createAccount')" :valid="valid" :busy="busy" />
      </div>

      <p class="auth-foot rise" style="animation-delay: 0.24s">
        {{ t('haveAccount') }}
        <RouterLink to="/login" class="auth-link auth-link--strong">{{ t('signIn') }}</RouterLink>
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
.auth-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
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
.signup-done {
  margin: 0;
  font-size: 14.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.auth-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  box-sizing: border-box;
  padding: 12px 18px;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  transition: filter 0.15s;
}
.auth-cta:hover {
  filter: brightness(1.08);
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
@media (max-width: 480px) {
  .auth-grid {
    grid-template-columns: 1fr;
  }
}
</style>
