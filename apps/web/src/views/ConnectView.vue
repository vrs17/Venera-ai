<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { ApiError } from '../api/http'
import { localizeApiError } from '../api/errors'
import {
  approveConnect,
  connectRequest,
  connectedApps,
  denyConnect,
  disconnectApp,
  type ConnectRequest,
  type ConnectedApp,
} from '../api/connector.api'
import AuthShell from '../components/AuthShell.vue'
import AuthError from '../components/AuthError.vue'
import VButton from '../ui/VButton.vue'

/**
 * Barno konnektori (Claude / ChatGPT) - `/connect`.
 *
 * `?request=<kalit>` bilan - ROZILIK: Claude yoki ChatGPT "Barno'ni ulash" bosganda server
 * (`/oauth/authorize`) shu yerga yuboradi. Kirmagan odam avval kirish sahifasiga (BRB-Tech ID
 * yoki login + parol), keyin shu yerga qaytadi. Hech narsa o'z-o'zidan ULANMAYDI: sahifa
 * qaysi ilova, qaysi Barno hisobi va qaysi ma'lumot ekanini yozadi, odam modulni belgilab
 * "Ruxsat berish" ni bosadi (egasining qarori: har kim o'zi yoqadi).
 *
 * `request` siz - "ULANGAN ILOVALAR": ruxsatlar ro'yxati va "Uzish" (hisob menyusidan).
 */
const { t, te, locale } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { user } = useAuth()

const requestId = computed(() => {
  const raw = Array.isArray(route.query.request) ? route.query.request[0] : route.query.request
  return typeof raw === 'string' ? raw : ''
})

type Phase = 'loading' | 'consent' | 'leaving' | 'gone' | 'off' | 'apps'
const phase = ref<Phase>('loading')
const pending = ref<ConnectRequest | null>(null)
const chosen = ref<string[]>([])
const apps = ref<ConnectedApp[]>([])
const enabled = ref(true)
const busy = ref('')
const error = ref('')

const account = computed(() => user.value?.fullName || user.value?.email || '')
const login = computed(() => user.value?.email || '')
const client = computed(() => pending.value?.client || '')

/** Qamrov nomi: `plaud.read` -> `shell.connector.scopes.plaud_read` (kalitda nuqta - yo'l ajratgichi). */
function scopeLabel(id: string): string {
  const key = `shell.connector.scopes.${id.replace(/\./g, '_')}`
  return te(key) ? t(key) : id
}

function when(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(locale.value, { day: 'numeric', month: 'long', year: 'numeric' })
}

function isDisabled(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && err.message === 'connector_disabled'
}

function isGone(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 422)
}

async function loadApps() {
  try {
    const found = await connectedApps()
    apps.value = found.apps
    enabled.value = found.enabled
  } catch (err) {
    error.value = localizeApiError(err, t)
  }
  phase.value = 'apps'
}

onMounted(async () => {
  if (!requestId.value) {
    await loadApps()
    return
  }
  try {
    pending.value = await connectRequest(requestId.value)
    chosen.value = pending.value.scopes.map((s) => s.id)
    phase.value = 'consent'
  } catch (err) {
    if (isDisabled(err)) phase.value = 'off'
    else if (isGone(err)) phase.value = 'gone'
    else {
      error.value = localizeApiError(err, t)
      phase.value = 'gone'
    }
  }
})

/** Ilovaga qaytish - server bergan manzil (kod yoki `access_denied` bilan). */
function leave(target: string) {
  phase.value = 'leaving'
  window.location.assign(target)
}

async function allow() {
  if (busy.value || !pending.value || chosen.value.length === 0) return
  busy.value = 'allow'
  error.value = ''
  try {
    leave((await approveConnect(pending.value.id, chosen.value)).redirect)
  } catch (err) {
    if (isDisabled(err)) phase.value = 'off'
    else if (isGone(err)) phase.value = 'gone'
    else error.value = localizeApiError(err, t)
  } finally {
    busy.value = ''
  }
}

async function deny() {
  if (busy.value || !pending.value) return
  busy.value = 'deny'
  error.value = ''
  try {
    leave((await denyConnect(pending.value.id)).redirect)
  } catch (err) {
    if (isGone(err)) phase.value = 'gone'
    else error.value = localizeApiError(err, t)
  } finally {
    busy.value = ''
  }
}

async function disconnect(app: ConnectedApp) {
  if (busy.value) return
  busy.value = app.id
  error.value = ''
  try {
    await disconnectApp(app.id)
    apps.value = apps.value.filter((a) => a.id !== app.id)
  } catch (err) {
    if (isGone(err)) apps.value = apps.value.filter((a) => a.id !== app.id)
    else error.value = localizeApiError(err, t)
  } finally {
    busy.value = ''
  }
}

function home() {
  router.push('/')
}
</script>

<template>
  <AuthShell
    :title="phase === 'apps' ? t('shell.connector.appsTitle') : t('shell.connector.title', { client: client || 'Claude / ChatGPT' })"
    :caption="phase === 'consent' ? t('shell.connector.caption', { client }) : ''"
  >
    <div class="connect" data-testid="connect">
      <p v-if="phase === 'loading' || phase === 'leaving'" class="connect__text" role="status">
        {{ phase === 'loading' ? t('shell.link.loading') : t('shell.connector.leaving', { client }) }}
      </p>

      <template v-else-if="phase === 'consent' && pending">
        <dl class="connect__who">
          <div>
            <dt>{{ t('shell.connector.app') }}</dt>
            <dd>
              {{ pending.client }}
              <span class="connect__sub">{{ pending.host }}</span>
            </dd>
          </div>
          <div>
            <dt>{{ t('shell.link.barnoAccount') }}</dt>
            <dd>
              {{ account }}
              <span v-if="login && login !== account" class="connect__sub">{{ login }}</span>
            </dd>
          </div>
        </dl>

        <fieldset class="connect__scopes">
          <legend>{{ t('shell.connector.access') }}</legend>
          <label v-for="s in pending.scopes" :key="s.id" class="connect__scope">
            <input v-model="chosen" type="checkbox" :value="s.id" :data-testid="`scope-${s.id}`" />
            <span>{{ scopeLabel(s.id) }}</span>
          </label>
        </fieldset>

        <p class="connect__warn">{{ t('shell.connector.warning', { client: pending.client }) }}</p>
        <AuthError :message="error" />
        <VButton
          type="button"
          variant="primary"
          size="lg"
          block
          pill
          :loading="busy === 'allow'"
          :disabled="chosen.length === 0 || !!busy"
          data-testid="connect-allow"
          @click="allow"
        >
          {{ t('shell.connector.allow') }}
        </VButton>
        <VButton type="button" variant="ghost" size="lg" block pill :loading="busy === 'deny'" :disabled="!!busy" @click="deny">
          {{ t('shell.connector.deny') }}
        </VButton>
        <p class="connect__legal">
          {{ t('shell.connector.agree') }}
          <a href="/connector/terms" target="_blank" rel="noopener">{{ t('shell.connector.terms') }}</a>
          ·
          <a href="/privacy" target="_blank" rel="noopener">{{ t('shell.connector.privacy') }}</a>
        </p>
      </template>

      <template v-else-if="phase === 'apps'">
        <p class="connect__text">{{ t('shell.connector.appsCaption') }}</p>
        <ul v-if="apps.length" class="connect__apps">
          <li v-for="app in apps" :key="app.id" class="connect__app">
            <div>
              <strong>{{ app.client }}</strong>
              <span class="connect__sub">{{ app.scopes.map(scopeLabel).join(', ') }}</span>
              <span class="connect__sub">
                {{ t('shell.connector.since', { date: when(app.createdAt) }) }} ·
                {{ t('shell.connector.lastUsed', { date: when(app.lastUsedAt) }) }}
              </span>
            </div>
            <VButton type="button" variant="secondary" size="sm" pill :loading="busy === app.id" :disabled="!!busy" @click="disconnect(app)">
              {{ t('shell.connector.disconnect') }}
            </VButton>
          </li>
        </ul>
        <p v-else class="connect__warn">{{ enabled ? t('shell.connector.empty') : t('shell.connector.off') }}</p>
        <AuthError :message="error" />
        <VButton type="button" variant="ghost" size="lg" block pill @click="home">{{ t('shell.link.openBarno') }}</VButton>
      </template>

      <template v-else>
        <p class="connect__text" role="alert">
          {{ phase === 'off' ? t('shell.connector.off') : t('shell.connector.gone') }}
        </p>
        <AuthError :message="error" />
        <VButton type="button" variant="secondary" size="lg" block pill @click="home">{{ t('shell.link.openBarno') }}</VButton>
      </template>
    </div>
  </AuthShell>
</template>

<style scoped>
.connect {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
}
.connect__text {
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.5;
}
.connect__who {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.connect__who dt,
.connect__scopes legend {
  font-size: var(--fs-body-sm);
  color: var(--text-3);
}
.connect__who dd {
  margin: 2px 0 0;
  font-size: var(--fs-body);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.connect__sub {
  display: block;
  font-weight: 400;
  font-size: var(--fs-body-sm);
  color: var(--text-3);
}
.connect__scopes {
  margin: 0;
  padding: 0;
  border: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.connect__scope {
  display: flex;
  gap: var(--s-2);
  align-items: flex-start;
  font-size: var(--fs-body);
  line-height: 1.4;
}
.connect__scope input {
  margin-top: 3px;
}
.connect__warn {
  margin: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  color: var(--text-3);
}
.connect__legal {
  margin: 0;
  text-align: center;
  font-size: var(--fs-caption);
  color: var(--text-3);
}
.connect__legal a {
  color: inherit;
  text-decoration: underline;
}
.connect__apps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.connect__app {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s-3);
}
</style>
