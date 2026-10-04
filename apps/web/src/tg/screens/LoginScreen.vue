<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, Eye, EyeOff, ExternalLink } from 'lucide-vue-next'
import { authErrorKind, localizeAuthError } from '../../api/errors'
import BrandSpark from '../../components/BrandSpark.vue'
import { haptic, mainButton, openLink } from '../telegram'
import { useTgSession } from '../useTgSession'

/**
 * Birinchi ochilish: HRM / CRM (Keycloak) login va paroli - BIR MARTA. Kirgach
 * Telegram hisobi shu hisobga ulanadi va keyingi ochilishlar avtomatik (useTgSession).
 *
 * "Kirish" - Telegram'ning O'Z pastki tugmasi (MainButton): u klaviatura ustida
 * turadi va Telegram foydalanuvchisiga tanish. Telegram'dan tashqarida (stub) -
 * sahifa ichidagi tugma, ayni o'sha joyda.
 *
 * Maydonlar 52px, matn 16px (iOS kattalashtirmaydi), `autocomplete` - parol menejeri
 * to'ldira olsin, `enterkeyhint` - klaviaturadagi tugma "Keyingi" / "Kirish".
 *
 * JOYLASHUV TEPAGA BOG'LANGAN (markazda emas): xato chiqqanda yoki klaviatura
 * ochilganda forma "sakramaydi" - faqat pastdagi izoh joyini beradi. Xato esa
 * balandligi 0 dan silliq ochiladi (grid 0fr -> 1fr), qo'shni maydonlar siljimaydi.
 *
 * "Hisob to'liq sozlanmagan" (Keycloak): xato matnining o'zi yo'l-yo'riq beradi;
 * VITE_CRM_URL build'da berilgan bo'lsa - qo'shimcha "CRM ni ochish" havolasi.
 */
const props = withDefaults(defineProps<{ fromBrand?: boolean }>(), { fromBrand: false })
const { t } = useI18n({ useScope: 'global' })
const { login, lastLogin } = useTgSession()

// "Qayta ulash" dan kelgan bo'lsa - login tayyor, faqat parol.
const username = ref(lastLogin.value)
const password = ref('')
const reveal = ref(false)
const busy = ref(false)
const error = ref('')
const setupHelp = ref(false)
const crmUrl = ((import.meta.env.VITE_CRM_URL as string | undefined) ?? '').trim()

const userEl = ref<HTMLInputElement | null>(null)
const passEl = ref<HTMLInputElement | null>(null)

const valid = computed(() => username.value.trim().length > 0 && password.value.length > 0)

// Eski xato odam tuzata boshlashi bilan yo'qoladi.
watch([username, password], () => {
  error.value = ''
  setupHelp.value = false
})

async function submit() {
  if (busy.value) return
  if (!valid.value) {
    error.value = t('tg.login.required')
    haptic.notify('error')
    ;(username.value.trim() ? passEl : userEl).value?.focus()
    return
  }
  busy.value = true
  error.value = ''
  setupHelp.value = false
  try {
    const res = await login(username.value.trim(), password.value)
    if (res.passwordChangeRequired) {
      error.value = t('tg.login.passwordChange')
      haptic.notify('warning')
      return
    }
    haptic.notify('success')
    // Klaviatura yopilsin - chat ekrani to'liq bo'yda ochilsin.
    ;(document.activeElement as HTMLElement | null)?.blur?.()
  } catch (err) {
    error.value = localizeAuthError(err, t)
    setupHelp.value = authErrorKind(err) === 'accountSetup'
    haptic.notify('error')
  } finally {
    busy.value = false
  }
}

function onUserEnter() {
  passEl.value?.focus()
}

// --- Telegram MainButton ------------------------------------------------------
let offMain: (() => void) | null = null
watch(
  [busy, () => t('tg.login.submit')],
  () => mainButton.set({ text: busy.value ? t('tg.login.busy') : t('tg.login.submit'), progress: busy.value }),
)
onMounted(() => {
  if (lastLogin.value) passEl.value?.focus({ preventScroll: true })
  if (!mainButton.native) return
  offMain = mainButton.onClick(() => void submit())
  mainButton.set({ text: t('tg.login.submit'), visible: true, active: true, progress: false })
})
onBeforeUnmount(() => {
  offMain?.()
  mainButton.set({ visible: false, progress: false })
})
</script>

<template>
  <main class="login" :class="{ 'is-from-brand': props.fromBrand }">
    <form class="login__inner" novalidate @submit.prevent="submit">
      <div class="login__brand">
        <span class="login__spark"><BrandSpark :size="36" /></span>
        <h1 class="login__title">Venera</h1>
        <p class="login__lead">{{ t('tg.login.lead') }}</p>
      </div>

      <div class="login__fields">
        <label class="field">
          <span class="field__label">{{ t('tg.login.username') }}</span>
          <input
            ref="userEl"
            v-model="username"
            class="field__input"
            name="username"
            type="text"
            inputmode="text"
            autocomplete="username"
            autocapitalize="none"
            autocorrect="off"
            spellcheck="false"
            enterkeyhint="next"
            :placeholder="t('tg.login.usernamePlaceholder')"
            :aria-invalid="error && !username.trim() ? 'true' : undefined"
            @keydown.enter.prevent="onUserEnter"
          />
        </label>
        <label class="field">
          <span class="field__label">{{ t('tg.login.password') }}</span>
          <span class="field__wrap">
            <input
              ref="passEl"
              v-model="password"
              class="field__input field__input--pass"
              name="password"
              :type="reveal ? 'text' : 'password'"
              autocomplete="current-password"
              autocapitalize="none"
              autocorrect="off"
              spellcheck="false"
              enterkeyhint="go"
              :aria-invalid="error && !password ? 'true' : undefined"
            />
            <button
              type="button"
              class="field__eye"
              :aria-label="reveal ? t('hidePassword') : t('showPassword')"
              :aria-pressed="reveal ? 'true' : 'false'"
              @click="reveal = !reveal"
            >
              <EyeOff v-if="reveal" :size="20" :stroke-width="1.75" aria-hidden="true" />
              <Eye v-else :size="20" :stroke-width="1.75" aria-hidden="true" />
            </button>
          </span>
        </label>

        <!-- Doim DOM'da: balandligi 0 <-> o'z bo'yi (grid satri), ya'ni chiqqanda
             forma "sakramaydi", pastdagi izoh silliq suriladi. -->
        <div class="login__err" :class="{ 'is-shown': !!error }">
          <div class="login__err-clip">
            <div class="login__error" role="alert">
              <template v-if="error">
                <CircleAlert class="login__error-icon" :size="18" :stroke-width="2" aria-hidden="true" />
                <div>
                  <p>{{ error }}</p>
                  <button v-if="setupHelp && crmUrl" type="button" class="login__link" @click="openLink(crmUrl)">
                    {{ t('shell.auth.openCrm') }}
                    <ExternalLink :size="14" :stroke-width="2" aria-hidden="true" />
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- Telegram'dan tashqarida: MainButton yo'q - ayni o'sha joy va ko'rinishda. -->
        <button v-if="!mainButton.native" type="submit" class="login__submit" :aria-busy="busy ? 'true' : undefined">
          <span v-if="busy" class="login__spinner" aria-hidden="true" />
          {{ busy ? t('tg.login.busy') : t('tg.login.submit') }}
        </button>
        <!-- Enter "Kirish" bo'lsin (klaviaturadagi "go"): ko'rinmas submit. -->
        <button v-else type="submit" class="sr-only" tabindex="-1">{{ t('tg.login.submit') }}</button>
      </div>

      <p class="login__foot">{{ t('tg.login.footnote') }}</p>
    </form>
  </main>
</template>

<style scoped>
.login {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior-y: contain;
  padding: calc(var(--tg-safe-top) + var(--s-6)) calc(var(--s-6) + var(--tg-safe-right)) calc(var(--tg-safe-bottom) + var(--s-5))
    calc(var(--s-6) + var(--tg-safe-left));
}
/* Brend boot ekranidan kelganda (App.vue) butun ekran so'nib kirmaydi: belgi o'sha
   joyda turibdi, faqat forma ostidan ko'tariladi. */
.login.is-from-brand.tg-screen-enter-from {
  opacity: 1;
}
/* Tepaga bog'langan: belgi BootScreen'dagi bilan bir koordinatada; izoh ekran pastida
   (margin-top: auto), klaviatura ochilsa - forma aylanadi, kesilmaydi. */
.login__inner {
  display: flex;
  flex: 1 0 auto;
  flex-direction: column;
  gap: var(--s-8);
  width: 100%;
  max-width: 400px;
  margin: clamp(24px, 10vh, 88px) auto 0;
}

.login__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.login__spark {
  display: grid;
  place-items: center;
  width: 72px;
  height: 72px;
  margin-bottom: var(--s-4);
  border-radius: 24px;
  background: var(--brand-soft);
  color: var(--brand);
  animation: login-spark 600ms var(--ease-sheet) both;
}
.is-from-brand .login__spark {
  animation: none;
}
@keyframes login-spark {
  from {
    opacity: 0;
    transform: scale(0.6) rotate(-30deg);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.is-from-brand .login__title,
.is-from-brand .login__lead,
.is-from-brand .login__fields,
.is-from-brand .login__foot {
  animation: login-rise var(--dur-3) var(--ease-sheet) both;
}
.is-from-brand .login__lead {
  animation-delay: 30ms;
}
.is-from-brand .login__fields {
  animation-delay: 60ms;
}
.is-from-brand .login__foot {
  animation-delay: 90ms;
}
@keyframes login-rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}
.login__title {
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.022em;
}
.login__lead {
  margin-top: var(--s-2);
  max-width: 34ch;
  color: var(--text-3);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  text-wrap: balance;
}

.login__fields {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--s-1_5);
}
.field__label {
  padding-left: var(--s-1);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.field__wrap {
  position: relative;
  display: block;
}
.field__input {
  width: 100%;
  /* 200% matnda ham glif maydonga sig'adi (16px * 2 * 1.5 + ichki joy). */
  min-height: max(52px, calc(1.5em + 22px));
  padding: 0 var(--s-4);
  border: 1px solid transparent;
  border-radius: 14px;
  background: var(--fill);
  color: var(--text);
  font-size: 16px;
  line-height: 1.5;
  outline: none;
  transition:
    border-color var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out);
  -webkit-appearance: none;
  appearance: none;
}
.field__input--pass {
  padding-right: 52px;
}
.field__input:focus {
  border-color: var(--line-strong);
  background: var(--surface);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ink) 8%, transparent);
}
.field__input[aria-invalid='true'] {
  border-color: color-mix(in srgb, var(--crit) 60%, transparent);
}
.field__eye {
  position: absolute;
  top: 50%;
  right: 4px;
  display: grid;
  place-items: center;
  width: var(--tap);
  height: var(--tap);
  border-radius: var(--r-full);
  color: var(--text-3);
  transform: translateY(-50%);
}
.field__eye:active {
  background: var(--fill-hover);
}

/* Xato bloki: yopiq - 0 balandlik va 0 oraliq (manfiy margin flex `gap` ni yeydi). */
.login__err {
  display: grid;
  grid-template-rows: 0fr;
  margin-top: calc(var(--s-3) * -1);
  transition: grid-template-rows var(--dur-2) var(--ease-out);
}
.login__err.is-shown {
  grid-template-rows: 1fr;
}
.login__err-clip {
  min-height: 0;
  overflow: hidden;
}
.login__error {
  display: flex;
  gap: var(--s-2);
  margin-top: var(--s-3);
  padding: var(--s-3);
  border-radius: 14px;
  background: var(--crit-soft);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  opacity: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.login__err.is-shown .login__error {
  opacity: 1;
}
.login__error:empty {
  padding: 0;
}
.login__error-icon {
  flex-shrink: 0;
  margin-top: 1px;
}
.login__link {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  min-height: var(--tap);
  margin: var(--s-1) 0 calc(var(--s-3) * -1);
  color: inherit;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.login__submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  min-height: max(52px, calc(1.5em + 22px));
  margin-top: var(--s-2);
  border-radius: 14px;
  background: var(--ink);
  color: var(--on-ink);
  font-size: var(--fs-body-lg);
  font-weight: 600;
  transition: transform var(--dur-1) var(--ease-out);
}
.login__submit:active {
  transform: scale(0.98);
}
.login__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid color-mix(in srgb, var(--on-ink) 35%, transparent);
  border-top-color: var(--on-ink);
  border-radius: var(--r-full);
  animation: login-spin 0.8s linear infinite;
}
@keyframes login-spin {
  to {
    transform: rotate(360deg);
  }
}

.login__foot {
  margin-top: auto;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-align: center;
}

@media (prefers-reduced-motion: reduce) {
  .login__spark,
  .is-from-brand .login__title,
  .is-from-brand .login__lead,
  .is-from-brand .login__fields,
  .is-from-brand .login__foot {
    animation: none;
  }
}
</style>
