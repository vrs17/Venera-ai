<script setup lang="ts">
import { computed, onMounted, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { LogOut } from 'lucide-vue-next'
import { useAuth } from '../composables/useAuth'
import { localizeAuthError } from '../api/errors'
import { redirectTarget } from '../router'
import AuthShell from '../components/AuthShell.vue'
import AuthField from '../components/AuthField.vue'
import AuthButton from '../components/AuthButton.vue'
import AuthError from '../components/AuthError.vue'
import PasswordStrength from '../components/PasswordStrength.vue'
import VButton from '../ui/VButton.vue'

// Forced first-login password change: replace the emailed temporary password
// with the user's own. Backend rules: >=8 chars, >=1 letter, >=1 digit, and
// different from the current password.
const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const { user, changePassword, logout } = useAuth()

const current = ref('')
const next = ref('')
const confirm = ref('')
const busy = ref(false)
const submitted = ref(false)
const formError = ref('')

const currentField = ref<InstanceType<typeof AuthField> | null>(null)
const nextField = ref<InstanceType<typeof AuthField> | null>(null)
const confirmField = ref<InstanceType<typeof AuthField> | null>(null)
const strengthId = useId()

// Qaysi hisob - parol menejeri uchun yashirin maydon va pastdagi "kim sifatida" qatori.
const account = computed(() => user.value?.email || user.value?.fullName || '')

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

watch([current, next, confirm], () => {
  formError.value = ''
})

onMounted(() => {
  if (window.matchMedia('(pointer: fine)').matches) currentField.value?.focus()
})

async function submit() {
  submitted.value = true
  formError.value = ''
  if (busy.value) return
  if (!valid.value) {
    const first = currentError.value ? currentField : newError.value ? nextField : confirmField
    first.value?.focus()
    return
  }
  busy.value = true
  try {
    await changePassword(current.value, next.value)
    router.push(redirectTarget(route.query) ?? '/')
  } catch (err) {
    formError.value = localizeAuthError(err, t)
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
  <AuthShell :title="t('authChangeTitle')" :caption="t('authChangeSub')">
    <form class="auth-form" novalidate @submit.prevent="submit">
      <!-- Parol menejeri QAYSI hisob paroli yangilanayotganini bilsin. -->
      <input
        class="sr-only"
        type="text"
        name="username"
        autocomplete="username"
        :value="account"
        readonly
        tabindex="-1"
        aria-hidden="true"
      />

      <div class="auth-form__fields">
        <AuthField
          ref="currentField"
          v-model="current"
          :label="t('currentPassword')"
          type="password"
          name="current-password"
          autocomplete="current-password"
          :error="currentError"
        />
        <div class="auth-form__new">
          <AuthField
            ref="nextField"
            v-model="next"
            :label="t('newPassword')"
            type="password"
            name="new-password"
            autocomplete="new-password"
            :error="newError"
            :aria-describedby="next && !newError ? strengthId : undefined"
          />
          <PasswordStrength :id="strengthId" :password="next" :current="current" :quiet="!!newError" />
        </div>
        <AuthField
          ref="confirmField"
          v-model="confirm"
          :label="t('confirmPassword')"
          type="password"
          name="confirm-password"
          autocomplete="new-password"
          :error="confirmError"
        />
      </div>

      <AuthButton :label="t('ui.save')" :busy="busy" />

      <AuthError :message="formError" />
    </form>

    <div class="auth-account">
      <span v-if="account" class="auth-account__who">{{ account }}</span>
      <VButton variant="ghost" size="sm" :icon="LogOut" @click="onSignOut">{{ t('logout') }}</VButton>
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
.auth-form__new {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
/* "Kim sifatida" va chiqish - shakl ostida jim qator; majburiy o'zgartirishdan
   yagona chiqish yo'li shu. */
.auth-account {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  margin-top: var(--s-8);
  padding-top: var(--s-5);
  border-top: 1px solid var(--line);
  min-width: 0;
}
.auth-account__who {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
</style>
