<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { authErrorKind, localizeAuthError } from '../api/errors'
import { redirectTarget } from '../router'
import AuthShell from '../components/AuthShell.vue'
import AuthField from '../components/AuthField.vue'
import AuthButton from '../components/AuthButton.vue'
import AuthError from '../components/AuthError.vue'

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const route = useRoute()
const { login } = useAuth()

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

// Login - HRM/CRM (Keycloak) hisobi, masalan `y.mamajonov`; email emas.
// Zahira hisob (users.yaml) uchun email ham shu maydonga yoziladi.
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

onMounted(() => {
  // Faqat sichqonchali qurilmada: telefonda klaviatura o'zi ochilib, sahifani yopmasin.
  if (window.matchMedia('(pointer: fine)').matches) loginField.value?.focus()
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
  <AuthShell :title="t('signIn')" :caption="t('shell.auth.caption')">
    <form class="auth-form" novalidate @submit.prevent="submit">
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
</style>
