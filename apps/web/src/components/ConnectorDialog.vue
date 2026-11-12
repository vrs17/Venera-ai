<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { ArrowLeft, CircleAlert, Eye, EyeOff, KeyRound, UserRound, Users } from 'lucide-vue-next'
import { localizeApiError } from '../api/errors'
import { ApiError } from '../api/http'
import { useConnectors } from '../composables/useConnectors'
import type { ConnectorId } from '../composables/useConnectors'
import VButton from '../ui/VButton.vue'
import VDialog from '../ui/VDialog.vue'
import VIconButton from '../ui/VIconButton.vue'
import VInput from '../ui/VInput.vue'
import { fmtTime } from '../ui/format'
import { useId } from '../ui/composables/useId'
import ConnectorList from './ConnectorList.vue'

/**
 * Ulanishlar oynasi (spec §4.3): ulanishlar ro'yxati, kirish shakli va hisob - bitta
 * VDialog ichida uch ko'rinish. Fokus tuzog'i, Esc, sahifa qulfi, fokusni ochgan
 * tugmaga qaytarish va telefonda pastki sheet - VDialog'da.
 *
 * FAQAT HRM (ega qarori, 2026-11-12). HRM hali SSO sessiyasini qabul qilmaydi - odam uni
 * shu yerda login va parol bilan ulaydi, holatini ko'radi, muddati tugasa qayta ulaydi,
 * xohlasa uzadi. CRM bu oynada YO'Q: u BRB-Tech ID bilan kirishda o'zi ulanadi. Yoqish /
 * o'chirish kaliti ham yo'q - ulangan tizim ishlatiladi.
 *
 * Kirish saytning o'zida: parol serverga ketadi (`POST /api/v1/connectors/{id}/connect`),
 * server platformaga kiradi va tokenni O'ZIDA saqlaydi - brauzer uni ko'rmaydi. Parol
 * brauzerda ham saqlanmaydi: ko'rinish almashsa yoki oyna yopilsa - maydon tozalanadi.
 *
 * Uzish ikki bosqichli: g'ildirak -> hisob -> "Uzish" -> "Ha, uzish". Uzilgan hisobni
 * qaytarish uchun yana login va parol kerak - tasodifiy bosish qimmat.
 *
 * `connectorId` berilsa - ro'yxatsiz, to'g'ridan-to'g'ri o'sha tizim uchun ochiladi
 * (masalan, chat "HRM ulanmagan" desa) va ish bitgach o'zi yopiladi.
 */
const props = defineProps<{ connectorId?: ConnectorId | null }>()
const open = defineModel<boolean>('open', { default: false })

const { t } = useI18n({ useScope: 'global' })
const { connectors, load, connect, disconnect } = useConnectors()

type View = 'list' | 'connect' | 'account'
const view = ref<View>('list')
const activeId = ref<ConnectorId>('hrm')
const direct = ref(false)

const ICONS: Record<ConnectorId, Component> = { hrm: Users }
const connector = computed(() => connectors.find((c) => c.id === activeId.value) ?? connectors[0])
const connected = computed(() => connector.value.state === 'connected')
const expired = computed(() => connector.value.state === 'expired')

const formId = useId('cdlg-form')
const login = ref('')
const password = ref('')
const showPassword = ref(false)
const submitted = ref(false)
const busy = ref(false)
const formError = ref('')
const confirming = ref(false)

const loginError = computed(() => (submitted.value && !login.value.trim() ? t('required') : ''))
const passwordError = computed(() => (submitted.value && !password.value ? t('required') : ''))
const valid = computed(() => login.value.trim().length > 0 && password.value.length > 0)
// Qayta kirishda login oldindan to'ldirilgan - odam faqat parol yozadi, fokus ham o'sha yerga.
const loginPrefilled = computed(() => view.value === 'connect' && !!connector.value.login)

const title = computed(() => {
  const name = connector.value.label
  if (view.value === 'list') return t('connectors')
  if (view.value === 'connect') return t('connectTo', { name })
  return confirming.value ? t('disconnectConfirm', { name }) : name
})
const subtitle = computed(() => {
  const name = connector.value.label
  if (view.value === 'connect') return expired.value ? t('connectorExpiredHint', { name }) : t('connectHint', { name })
  if (view.value === 'account') {
    if (confirming.value) return t('composer.reconnectNeedsPassword')
    return connected.value ? t('connectedAs', { login: connector.value.login ?? '' }) : t('connectorExpired')
  }
  return ''
})
const sessionText = computed(() =>
  connected.value && connector.value.expiresAt
    ? t('composer.sessionUntil', { time: fmtTime(connector.value.expiresAt) })
    : '',
)

/* ---- fokus: ko'rinish almashganda odam qayerda ekanini yo'qotmasin ---- */
const listRef = ref<InstanceType<typeof ConnectorList> | null>(null)
const loginRef = ref<InstanceType<typeof VInput> | null>(null)
const passwordRef = ref<InstanceType<typeof VInput> | null>(null)
const headingRef = ref<HTMLElement | null>(null)

function focusRow(id: ConnectorId) {
  const root = listRef.value?.$el as HTMLElement | undefined
  root?.querySelector<HTMLElement>(`[data-connector="${id}"] .clist__controls button`)?.focus()
}

function focusView() {
  if (view.value === 'connect') (loginPrefilled.value ? passwordRef : loginRef).value?.focus()
  // Hisob ko'rinishida sarlavhaga: ekran o'quvchi yangi sarlavhani darhol o'qiydi.
  else if (view.value === 'account') headingRef.value?.focus()
}

function clearForm() {
  password.value = ''
  showPassword.value = false
  submitted.value = false
  formError.value = ''
  confirming.value = false
}

function show(next: View, id?: ConnectorId) {
  if (id) activeId.value = id
  clearForm()
  if (next === 'connect') login.value = connector.value.login ?? ''
  view.value = next
}

function go(next: View, id: ConnectorId) {
  show(next, id)
  void nextTick(focusView)
}

function toList() {
  const id = activeId.value
  show('list')
  void nextTick(() => focusRow(id))
}

/** Ish bitdi: ro'yxatdan kelgan bo'lsa - ro'yxatga (natija o'sha yerda ko'rinadi),
 *  to'g'ridan-to'g'ri ochilgan bo'lsa - oyna yopiladi. */
function done() {
  if (direct.value) open.value = false
  else toList()
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) {
      // Parol va login xotirada qolmasin.
      clearForm()
      login.value = ''
      return
    }
    // Har ochilishda holat serverdan: HRM sessiyasi 10 soatda tugaydi.
    void load()
    direct.value = !!props.connectorId
    if (props.connectorId) {
      const c = connectors.find((x) => x.id === props.connectorId)
      show(c?.state === 'connected' ? 'account' : 'connect', props.connectorId)
    } else show('list')
  },
  { immediate: true },
)

// Holat oyna ochilgandan KEYIN kelsa ham qayta kirish logini to'ldirilsin.
watch(
  () => connector.value.login,
  (value) => {
    if (view.value === 'connect' && value && !login.value) login.value = value
  },
)

async function onSubmit() {
  submitted.value = true
  formError.value = ''
  if (!valid.value || busy.value) return
  busy.value = true
  try {
    await connect(activeId.value, login.value.trim(), password.value)
    password.value = ''
    done()
  } catch (err) {
    // Server xabari bo'lsa - o'sha (tarjima bilan); tarmoq/noma'lum xato bo'lsa umumiy.
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
    await disconnect(activeId.value)
    done()
  } catch (err) {
    formError.value = err instanceof ApiError ? localizeApiError(err, t) : t('composer.disconnectFailed')
    confirming.value = false
  } finally {
    busy.value = false
  }
}

function setConfirming(value: boolean) {
  formError.value = ''
  confirming.value = value
  // Tugma o'rnida boshqasi chiqadi - fokus sarlavhaga (yangi savol o'qiladi).
  void nextTick(() => headingRef.value?.focus())
}

function cancel() {
  if (direct.value) open.value = false
  else toList()
}
</script>

<template>
  <VDialog v-model:open="open" size="sm" :dismissible="!busy">
    <template #header="{ titleId }">
      <div class="cdlg__head">
        <VIconButton
          v-if="view !== 'list' && !direct"
          class="cdlg__back"
          :label="t('composer.back')"
          :icon="ArrowLeft"
          size="sm"
          tooltip-placement="bottom"
          :disabled="busy"
          @click="toList"
        />
        <div class="cdlg__titles">
          <h2 :id="titleId" ref="headingRef" class="cdlg__title" tabindex="-1">{{ title }}</h2>
          <p v-if="subtitle" class="cdlg__sub">{{ subtitle }}</p>
        </div>
      </div>
    </template>

    <ConnectorList
      v-if="view === 'list'"
      ref="listRef"
      @connect="go('connect', $event)"
      @manage="go('account', $event)"
    />

    <form v-else-if="view === 'connect'" :id="formId" class="cdlg__form" novalidate @submit.prevent="onSubmit">
      <p v-if="formError" class="cdlg__error" role="alert">
        <CircleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
        <span>{{ formError }}</span>
      </p>
      <VInput
        ref="loginRef"
        v-model="login"
        :label="t('login')"
        :icon="UserRound"
        size="lg"
        autocomplete="username"
        autocapitalize="off"
        spellcheck="false"
        :error="loginError"
        :data-autofocus="loginPrefilled ? undefined : ''"
      />
      <VInput
        ref="passwordRef"
        v-model="password"
        :label="t('password')"
        :type="showPassword ? 'text' : 'password'"
        :icon="KeyRound"
        size="lg"
        autocomplete="current-password"
        :error="passwordError"
        :data-autofocus="loginPrefilled ? '' : undefined"
      >
        <template #trailing>
          <VIconButton
            :label="showPassword ? t('hidePassword') : t('showPassword')"
            :icon="showPassword ? EyeOff : Eye"
            size="sm"
            :pressed="showPassword"
            @click="showPassword = !showPassword"
          />
        </template>
      </VInput>
    </form>

    <div v-else class="cdlg__account">
      <div class="cdlg__who">
        <span class="cdlg__glyph" aria-hidden="true">
          <component :is="ICONS[connector.id]" :size="18" :stroke-width="1.75" />
        </span>
        <span class="cdlg__who-text">
          <span class="cdlg__login">{{ connector.login || connector.label }}</span>
          <span v-if="sessionText" class="cdlg__meta">{{ sessionText }}</span>
        </span>
      </div>
      <p v-if="formError" class="cdlg__error" role="alert">
        <CircleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
        <span>{{ formError }}</span>
      </p>
    </div>

    <template v-if="view === 'connect'" #footer>
      <VButton variant="ghost" :disabled="busy" @click="cancel">{{ t('cancel') }}</VButton>
      <VButton variant="primary" type="submit" :form="formId" :loading="busy">
        {{ expired ? t('reconnect') : t('connect') }}
      </VButton>
    </template>
    <template v-else-if="view === 'account'" #footer>
      <template v-if="confirming">
        <VButton variant="ghost" :disabled="busy" @click="setConfirming(false)">{{ t('no') }}</VButton>
        <VButton variant="danger" :loading="busy" @click="onDisconnect">{{ t('yesDisconnect') }}</VButton>
      </template>
      <template v-else>
        <VButton variant="danger" @click="setConfirming(true)">{{ t('disconnect') }}</VButton>
        <VButton v-if="expired" variant="primary" @click="go('connect', connector.id)">{{ t('reconnect') }}</VButton>
      </template>
    </template>
  </VDialog>
</template>

<style scoped>
.cdlg__head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
}
.cdlg__back {
  margin: -4px 0 0 -8px;
}
.cdlg__titles {
  flex: 1;
  min-width: 0;
}
.cdlg__title {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
  text-wrap: balance;
  overflow-wrap: anywhere;
}
/* Sarlavhaga fokus faqat ekran o'quvchi uchun (ko'rinish almashdi) - halqa kerak emas. */
.cdlg__title:focus,
.cdlg__title:focus-visible {
  outline: none;
}
.cdlg__sub {
  margin-top: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
  text-wrap: pretty;
}

.cdlg__form {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  padding-top: var(--s-2);
}

.cdlg__account {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
  padding-top: var(--s-2);
}
.cdlg__who {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}
.cdlg__glyph {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.cdlg__who-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.cdlg__login {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.cdlg__meta {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}

.cdlg__error {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.cdlg__error svg {
  flex-shrink: 0;
  margin-top: 2px;
}
</style>
