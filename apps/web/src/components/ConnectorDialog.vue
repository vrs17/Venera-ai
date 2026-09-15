<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FunctionalComponent } from 'vue'
import { localizeApiError } from '../api/errors'
import { ApiError } from '../api/http'
import { useConnectors } from '../composables/useConnectors'
import type { ConnectorId } from '../composables/useConnectors'
import { BoardIcon, KeyIcon, UserIcon, UsersIcon, XIcon } from '../icons'
import AuthButton from './AuthButton.vue'
import AuthError from './AuthError.vue'
import AuthField from './AuthField.vue'

/**
 * Ulanish oynasi: login + parol, saytning o'zida (tashqi sahifaga yubormaydi).
 * Parol serverga ketadi (`POST /api/v1/connectors/{id}/connect`), server
 * platformaga kiradi va tokenni O'ZIDA saqlaydi - brauzer uni ko'rmaydi.
 * Ulangan tizim uchun esa hisob ko'rsatiladi va "Uzish" tugmasi bor; muddati
 * tugagan bo'lsa (HRM 10 soat, CRM refresh rad etilgan) yana kirish shakli,
 * login to'ldirilgan holda.
 *
 * <body>ga teleport qilinadi: menyu `.glass` (contain: paint) ichida, oyna esa
 * butun ekranni qoplashi kerak. Fon (backdrop) bosilsa yoki Escape bosilsa
 * `close` chiqadi - Escape'ni ota komponent (ComposerMenu) tutadi, chunki
 * u allaqachon document'ni tinglaydi va oyna ochiqligini biladi.
 */
const props = defineProps<{ connectorId: ConnectorId }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n({ useScope: 'global' })
const { connectors, connect, disconnect } = useConnectors()
const connector = computed(() => connectors.find((c) => c.id === props.connectorId) ?? connectors[0])

const ICONS: Record<ConnectorId, FunctionalComponent<{ size?: number }>> = { hrm: UsersIcon, crm: BoardIcon }

const connected = computed(() => connector.value.state === 'connected')
const expired = computed(() => connector.value.state === 'expired')

const titleId = useId()
const cardRef = ref<HTMLFormElement | null>(null)
// Qayta kirishda login oldindan to'ldirilgan - odam faqat parol yozadi.
const login = ref(connector.value.login ?? '')
const password = ref('')
const submitted = ref(false)
const busy = ref(false)
const formError = ref('')
// Uzish ikki bosqichli: "Uzish" -> "Haqiqatan ham?" (ha / yo'q). Uzilgan
// hisobni qaytarish uchun yana login va parol kerak - tasodifiy bosish
// qimmat, shuning uchun tasdiq.
const confirming = ref(false)

const loginError = computed(() => (submitted.value && !login.value.trim() ? t('required') : ''))
const passwordError = computed(() => (submitted.value && !password.value ? t('required') : ''))
const valid = computed(() => login.value.trim().length > 0 && password.value.length > 0)

// Fokus: ochilganda birinchi maydonga, yopilganda - oynani ochgan tugmaga.
let opener: Element | null = null
onMounted(() => {
  opener = document.activeElement
  cardRef.value?.querySelector<HTMLElement>('input, button')?.focus()
})
onBeforeUnmount(() => {
  if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
})

async function onSubmit() {
  submitted.value = true
  formError.value = ''
  if (!valid.value || busy.value) return
  busy.value = true
  try {
    await connect(props.connectorId, login.value.trim(), password.value)
    emit('close')
  } catch (err) {
    // Server xabari bo'lsa - o'sha (tarjima bilan); tarmoq/noma'lum xato
    // bo'lsa umumiy "ulanib bo'lmadi".
    formError.value = err instanceof ApiError ? localizeApiError(err, t) : t('connectFailed')
  } finally {
    busy.value = false
  }
}

async function onDisconnect() {
  if (busy.value) return
  busy.value = true
  formError.value = ''
  try {
    await disconnect(props.connectorId)
    emit('close')
  } catch (err) {
    formError.value = err instanceof ApiError ? localizeApiError(err, t) : t('connectFailed')
    confirming.value = false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <!-- Fon: faqat o'ziga bosilganda yopadi (kartada boshlangan sudrash
         tashqarida tugasa - yopilmaydi, shuning uchun mousedown.self). -->
    <div class="cdlg" @mousedown.self="emit('close')">
      <form
        ref="cardRef"
        class="cdlg__card"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        novalidate
        @submit.prevent="onSubmit"
      >
        <button type="button" class="cdlg__close" :title="t('close')" :aria-label="t('close')" @click="emit('close')">
          <XIcon :size="16" />
        </button>

        <div class="cdlg__head">
          <span class="cdlg__badge" aria-hidden="true"><component :is="ICONS[connector.id]" :size="18" /></span>
          <div class="cdlg__head-text">
            <h2 :id="titleId" class="cdlg__title">
              <template v-if="confirming">{{ t('disconnectConfirm', { name: connector.label }) }}</template>
              <template v-else>{{ connected ? connector.label : t('connectTo', { name: connector.label }) }}</template>
            </h2>
            <p class="cdlg__sub">
              <template v-if="confirming">{{ t('disconnectConfirmHint', { name: connector.label }) }}</template>
              <template v-else-if="connected">{{ t('connectedAs', { login: connector.login ?? '' }) }}</template>
              <template v-else-if="expired">{{ t('connectorExpiredHint', { name: connector.label }) }}</template>
              <template v-else>{{ t('connectHint', { name: connector.label }) }}</template>
            </p>
          </div>
        </div>

        <template v-if="!connected">
          <div v-if="formError" class="cdlg__error"><AuthError :message="formError" /></div>
          <AuthField
            v-model="login"
            :label="t('login')"
            autocomplete="username"
            :icon="UserIcon"
            :error="loginError"
          />
          <AuthField
            v-model="password"
            :label="t('password')"
            type="password"
            autocomplete="current-password"
            :icon="KeyIcon"
            :error="passwordError"
          />
          <div class="cdlg__actions">
            <button type="button" class="cdlg__secondary" @click="emit('close')">{{ t('cancel') }}</button>
            <div class="cdlg__primary">
              <AuthButton :label="busy ? t('connecting') : expired ? t('reconnect') : t('connect')" :valid="valid" :busy="busy" />
            </div>
          </div>
        </template>

        <!-- Ulangan: yopish / uzish; uzishda ikkinchi qadam - tasdiq. -->
        <template v-else>
          <div v-if="formError" class="cdlg__error"><AuthError :message="formError" /></div>
          <div v-if="confirming" class="cdlg__actions">
            <button type="button" class="cdlg__secondary" :disabled="busy" @click="confirming = false">{{ t('no') }}</button>
            <button type="button" class="cdlg__danger is-filled" :disabled="busy" :aria-busy="busy" @click="onDisconnect">
              {{ busy ? t('disconnecting') : t('yesDisconnect') }}
            </button>
          </div>
          <div v-else class="cdlg__actions">
            <button type="button" class="cdlg__secondary" @click="emit('close')">{{ t('close') }}</button>
            <button type="button" class="cdlg__danger" @click="confirming = true">{{ t('disconnect') }}</button>
          </div>
        </template>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.cdlg {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.45);
  -webkit-backdrop-filter: blur(3px);
  backdrop-filter: blur(3px);
  animation: cdlgFade 0.18s ease both;
}
.cdlg__card {
  position: relative;
  width: min(400px, 100%);
  box-sizing: border-box;
  margin: 0;
  padding: 22px;
  border-radius: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--menu-shadow);
  color: var(--text);
  font-family: 'Figtree', sans-serif;
  animation: fadeUp 0.28s var(--spring) both;
}
.cdlg__close {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.cdlg__close:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.cdlg__head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 18px;
  padding-right: 30px;
}
.cdlg__badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: var(--ink);
  color: var(--ink-contrast);
}
.cdlg__head-text {
  min-width: 0;
}
.cdlg__title {
  margin: 0 0 3px;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--text-strong);
}
.cdlg__sub {
  margin: 0;
  font-size: 13px;
  line-height: 1.4;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
.cdlg__error {
  margin-bottom: 12px;
}
.cdlg__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
}
.cdlg__primary {
  flex: 1;
  max-width: 200px;
}
.cdlg__secondary,
.cdlg__danger {
  padding: 11px 16px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  font-family: 'Figtree', sans-serif;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.cdlg__secondary {
  color: var(--text-secondary);
}
.cdlg__secondary:hover {
  background: var(--surface-hover);
  border-color: var(--border-hover);
  color: var(--text);
}
/* Uzish: qizil faqat sichqoncha ustida - oyna ochilishi bilan "xavf"
   baqirmasin. */
.cdlg__danger {
  color: var(--bad-fg);
}
.cdlg__danger:hover {
  background: var(--bad-bg);
  border-color: var(--bad-bd);
}
/* Tasdiq qadamida "Ha, uzish" to'ldirilgan: bu yerda qizil endi "ehtiyot
   bo'l" emas, "shuni qilyapsan" degan aniq tugma. */
.cdlg__danger.is-filled {
  background: var(--bad-fg);
  border-color: transparent;
  color: #fff;
}
.cdlg__danger.is-filled:hover {
  filter: brightness(1.08);
}
.cdlg__secondary:disabled,
.cdlg__danger:disabled {
  opacity: 0.6;
  cursor: default;
}
@keyframes cdlgFade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .cdlg,
  .cdlg__card {
    animation: none !important;
  }
}
</style>
