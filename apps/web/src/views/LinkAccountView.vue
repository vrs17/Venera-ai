<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { ApiError } from '../api/http'
import { localizeApiError } from '../api/errors'
import { confirmSlackLink, slackLinkInfo } from '../api/slack.api'
import { confirmTelegramLink, telegramLinkInfo } from '../api/telegramLink.api'
import AuthShell from '../components/AuthShell.vue'
import AuthError from '../components/AuthError.vue'
import VButton from '../ui/VButton.vue'

/**
 * Slack yoki Telegram hisobini Barno hisobiga ulash - TASDIQ sahifasi
 * (`/link/slack?t=<chipta>`, `/link/telegram?t=<chipta>`).
 *
 * Slack'dagi «Connect Barno AI account» tugmasi va Telegram Mini App'dagi «BRB-Tech ID bilan
 * kirish» shu yerni brauzerda ochadi. Odam kirmagan bo'lsa marshrut qo'riqchisi avval kirish
 * sahifasiga yuboradi (BRB-Tech ID yoki login + parol) va kirgach shu manzilga qaytaradi.
 *
 * Kirishning o'zi hech narsani ULAMAYDI: havolani birovga yuborish mumkin, va hamkasb uni
 * ochib tasdiqsiz ulansa, yuboruvchining Slack/Telegram'i hamkasbning hisobiga bog'lanib
 * qolardi. Shuning uchun sahifa KIM ulanayotganini yozadi va faqat tugma bosilganda ulaydi.
 */
const props = defineProps<{ kind: 'slack' | 'telegram' }>()
const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { user } = useAuth()

const ticket = computed(() => {
  const raw = Array.isArray(route.query.t) ? route.query.t[0] : route.query.t
  return typeof raw === 'string' ? raw : ''
})

/** Ikkala kanal uchun bir xil ko'rinish: tashqi hisob (ism, @username) va Barno hisobi. */
interface LinkInfo {
  who: string | null
  handle: string | null
  accountName: string
  accountLogin: string
}

async function loadInfo(value: string): Promise<LinkInfo> {
  if (props.kind === 'telegram') {
    const found = await telegramLinkInfo(value)
    return {
      who: found.telegramName,
      handle: found.telegramUsername ? `@${found.telegramUsername}` : null,
      accountName: found.accountName,
      accountLogin: found.accountLogin,
    }
  }
  const found = await slackLinkInfo(value)
  return { who: found.slackName, handle: null, accountName: found.accountName, accountLogin: found.accountLogin }
}

function confirmLink(value: string): Promise<unknown> {
  return props.kind === 'telegram' ? confirmTelegramLink(value) : confirmSlackLink(value)
}

/** Kanal matni: `shell.slack.*` yoki `shell.telegram.*`. */
function tk(key: string): string {
  return t(`shell.${props.kind}.${key}`)
}

const phase = ref<'loading' | 'ready' | 'done' | 'gone'>('loading')
const info = ref<LinkInfo | null>(null)
const busy = ref(false)
const error = ref('')

const account = computed(() => info.value?.accountName || user.value?.fullName || user.value?.email || '')
const login = computed(() => info.value?.accountLogin || user.value?.email || '')

function isGone(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 422)
}

onMounted(async () => {
  if (!ticket.value) {
    phase.value = 'gone'
    return
  }
  try {
    info.value = await loadInfo(ticket.value)
    phase.value = 'ready'
  } catch (err) {
    if (isGone(err)) phase.value = 'gone'
    else {
      error.value = localizeApiError(err, t)
      phase.value = 'ready'
    }
  }
})

async function connect() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await confirmLink(ticket.value)
    phase.value = 'done'
  } catch (err) {
    if (isGone(err)) phase.value = 'gone'
    else error.value = localizeApiError(err, t)
  } finally {
    busy.value = false
  }
}

function cancel() {
  router.push('/')
}
</script>

<template>
  <AuthShell :title="tk('title')" :caption="phase === 'ready' ? tk('caption') : ''">
    <div class="slack-link" :data-testid="`${kind}-link`">
      <p v-if="phase === 'loading'" class="slack-link__text">{{ t('shell.link.loading') }}</p>

      <template v-else-if="phase === 'ready'">
        <dl class="slack-link__who">
          <div>
            <dt>{{ tk('account') }}</dt>
            <dd>
              {{ info?.who || info?.handle || tk('unknown') }}
              <span v-if="info?.who && info?.handle" class="slack-link__login">{{ info.handle }}</span>
            </dd>
          </div>
          <div>
            <dt>{{ t('shell.link.barnoAccount') }}</dt>
            <dd>
              {{ account }}
              <span v-if="login && login !== account" class="slack-link__login">{{ login }}</span>
            </dd>
          </div>
        </dl>
        <p class="slack-link__warn">{{ tk('warning') }}</p>
        <AuthError :message="error" />
        <VButton
          type="button"
          variant="primary"
          size="lg"
          block
          pill
          :loading="busy"
          :disabled="!info"
          :data-testid="`${kind}-link-confirm`"
          @click="connect"
        >
          {{ t('shell.link.confirm') }}
        </VButton>
        <VButton type="button" variant="ghost" size="lg" block pill :disabled="busy" @click="cancel">
          {{ t('shell.link.cancel') }}
        </VButton>
      </template>

      <template v-else-if="phase === 'done'">
        <p class="slack-link__text" role="status">{{ tk('done') }}</p>
        <VButton type="button" variant="secondary" size="lg" block pill @click="cancel">
          {{ t('shell.link.openBarno') }}
        </VButton>
      </template>

      <template v-else>
        <p class="slack-link__text" role="alert">{{ tk('gone') }}</p>
        <VButton type="button" variant="secondary" size="lg" block pill @click="cancel">
          {{ t('shell.link.openBarno') }}
        </VButton>
      </template>
    </div>
  </AuthShell>
</template>

<style scoped>
.slack-link {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
}
.slack-link__text {
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.5;
}
.slack-link__who {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.slack-link__who dt {
  font-size: var(--fs-body-sm);
  color: var(--text-3);
}
.slack-link__who dd {
  margin: 2px 0 0;
  font-size: var(--fs-body);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.slack-link__login {
  display: block;
  font-weight: 400;
  font-size: var(--fs-body-sm);
  color: var(--text-3);
}
.slack-link__warn {
  margin: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  color: var(--text-3);
}
</style>
