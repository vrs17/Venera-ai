<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowDown, Copy, Flag, RotateCw, RotateCcw, TextSelect } from 'lucide-vue-next'
import { copyText } from '../../clipboard'
import { stopReading } from '../../components/chat/readAloud'
import { useAuth } from '../../composables/useAuth'
import { useChats } from '../../composables/useChats'
import { usePro } from '../../composables/usePro'
import { isoToMs } from '../../time'
import { toast } from '../../ui/useToast'
import { plainText } from '../chat/polish'
import { useTgChat } from '../chat/useTgChat'
import type { TgExchange } from '../chat/useTgChat'
import { sourceItems } from '../chat/sources'
import Composer from '../components/Composer.vue'
import ContextMenu from '../components/ContextMenu.vue'
import type { MenuItem } from '../components/ContextMenu.vue'
import Exchange, { loadMarkdown } from '../components/Exchange.vue'
import HistorySheet from '../components/HistorySheet.vue'
import ReportSheet from '../components/ReportSheet.vue'
import SelectTextSheet from '../components/SelectTextSheet.vue'
import SettingsSheet from '../components/SettingsSheet.vue'
import SourcesSheet from '../components/SourcesSheet.vue'
import TgWelcome from '../components/TgWelcome.vue'
import TopBar from '../components/TopBar.vue'
import { haptic, isForeground, onSettingsButton, setClosingConfirmation } from '../telegram'
import { useTgSession } from '../useTgSession'

/**
 * Asosiy ekran: yuqori panel, suhbat (aylanadi), pastda kompozer. Oynalar (tarix,
 * sozlamalar, manbalar, xabar berish) - pastdan chiqadigan "sheet": telefonda ekran
 * almashmaydi, odam qayerda ekanini yo'qotmaydi, Telegram "Orqaga" ularni yopadi.
 * Xabarni ushlab turish - Telegram'dagi kabi "ko'tarilgan" menyu (ContextMenu).
 *
 * AYLANTIRISH. Chat pastga "yopishadi": odam oxirida tursa, yangi matn (oqim,
 * kech yuklangan markdown, klaviatura ochilishi) uni oxirida ushlab turadi; yuqoriga
 * o'qish uchun chiqqan bo'lsa - tegilmaydi, faqat "oxiriga" tugmasi chiqadi.
 *
 * "JAVOB TAYYOR". 4 soniyadan uzoq kutilgan javob tugaganda (ilova oldingi planda
 * bo'lsa) bitta yumshoq tebranish - odam kutish paytida boshqa yoqqa qaragan bo'ladi;
 * toast'siz, ovozsiz "tayyor" deydi. Manbalar va amallar qatori esa 4px pastdan
 * ko'tarilib chiqadi (Exchange `landed`).
 */
const { t, locale } = useI18n({ useScope: 'global' })
const { user } = useAuth()
const chats = useChats()
const pro = usePro()
const session = useTgSession()
const chat = useTgChat()
const { exchanges, phase, streamingId, historyLoading, historyError } = chat

const userName = computed(() => user.value?.fullName || user.value?.email || '')

/** "Salom, {ism}": HRM ism-familiyani rasmiy tartibda beradi ("Mamajonov Yusufjon") -
 *  familiya qo'shimchasi bilan tugagan birinchi so'z o'tkazib yuboriladi (ChatView kabi). */
const firstName = computed(() => {
  const words = (user.value?.fullName ?? '').trim().split(/\s+/u).filter(Boolean)
  if (!words.length) return user.value?.email?.split('@')[0] ?? ''
  let pick = words.length > 1 && /(ov|ova|ev|eva|ов|ова|ев|ева)$/iu.test(words[0]) ? words[1] : words[0]
  if (pick.length > 1 && pick === pick.toLocaleUpperCase()) pick = pick.charAt(0) + pick.slice(1).toLocaleLowerCase()
  return pick
})

const welcome = computed(() => !historyLoading.value && !historyError.value && exchanges.value.length === 0)
const canStartNew = computed(() => exchanges.value.length > 0 || !!historyError.value || historyLoading.value)

/** "Davom ettirish": oxirgi 7 kundagi eng so'nggi suhbat (hozir ochiq bo'lmagan). */
const RESUME_DAYS = 7
const resume = computed(() => {
  if (!chats.loaded.value) return null
  const c = chats.chats.value.find((x) => x.chat_id !== chats.activeId.value)
  if (!c) return null
  const at = isoToMs(c.updated_at)
  if (at && Date.now() - at > RESUME_DAYS * 86_400_000) return null
  return { id: c.chat_id, title: c.title, at }
})

/* ── Aylantirish ─────────────────────────────────────────────────────────── */
const scroller = ref<HTMLElement | null>(null)
const column = ref<HTMLElement | null>(null)
const atBottom = ref(true)
const scrolled = ref(false)
const NEAR_PX = 56

function measureScroll() {
  const el = scroller.value
  if (!el) return
  const gap = el.scrollHeight - el.scrollTop - el.clientHeight
  atBottom.value = gap < NEAR_PX
  scrolled.value = el.scrollTop > 2 && el.scrollHeight > el.clientHeight + 2
}

function scrollToBottom(smooth = false) {
  const el = scroller.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  atBottom.value = true
}

// Kontent yoki ramka o'lchami o'zgardi (oqim, markdown, klaviatura): oxirida
// turgan bo'lsa - oxirida qoladi. Qaror O'ZGARISHDAN OLDINGI holatga qarab.
let stick = true
let ro: ResizeObserver | null = null
function onScroll() {
  measureScroll()
  stick = atBottom.value
}
function onResize() {
  if (stick) scrollToBottom()
  measureScroll()
}

const showJump = computed(() => !atBottom.value && exchanges.value.length > 0)
function jump() {
  stick = true
  scrollToBottom(true)
}

/* ── Savol ───────────────────────────────────────────────────────────────── */
function send(text: string): boolean {
  const ok = chat.send(text)
  if (ok) {
    stick = true
    void nextTick(() => scrollToBottom(true))
  }
  return ok
}

// Taklif kartasi: yuborish tebranishi shu yerda, BIR marta.
function pickSuggestion(question: string) {
  if (send(question)) haptic.impact('light')
}

function newChat() {
  stopReading()
  chat.newChat()
  reportedKeys.value = new Set()
  landed.value = new Set()
}

async function openFromHistory(id: string) {
  stopReading()
  reportedKeys.value = new Set()
  landed.value = new Set()
  await chat.openHistory(id)
  stick = true
  await nextTick()
  scrollToBottom()
}

// Javob yozilayotganda yoki ovoz yozilayotganda Telegram'ni tasodifan yopish so'raladi.
const dictating = ref(false)
watch(
  () => phase.value === 'sending' || dictating.value,
  (busy) => setClosingConfirmation(busy),
  { immediate: true },
)

/* ── "Javob tayyor" ──────────────────────────────────────────────────────── */
const LONG_WAIT_MS = 4000
const landed = ref<ReadonlySet<string>>(new Set())
let streamStart = 0
watch(streamingId, (now, prev) => {
  if (now) streamStart = performance.now()
  if (!prev || now === prev) return
  const ex = exchanges.value.find((e) => e.id === prev)
  if (!ex) return
  landed.value = new Set([...landed.value, prev])
  if (!ex.error && performance.now() - streamStart > LONG_WAIT_MS && isForeground()) haptic.impact('soft')
})

/* ── Oynalar ─────────────────────────────────────────────────────────────── */
const historyOpen = ref(false)
const settingsOpen = ref(false)
const sourcesOpen = ref(false)
const sourcesFor = ref<string | null>(null)
const sourcesFocus = ref<string | null>(null)
const sourcesList = computed(() => {
  const ex = exchanges.value.find((e) => e.id === sourcesFor.value)
  return sourceItems(ex?.sources, (k, n) => t(k, n ?? {}), String(locale.value) === 'uz')
})
function openSources(ex: TgExchange, marker: string | null) {
  if (!ex.sources?.length) return
  sourcesFor.value = ex.id
  sourcesFocus.value = marker
  sourcesOpen.value = true
}

/* ── Xabar berish ────────────────────────────────────────────────────────── */
const reportOpen = ref(false)
const reportTurnId = ref<string | null>(null)
let reportKey: string | null = null
const reportedKeys = ref<ReadonlySet<string>>(new Set())
const reportChatId = ref<string | null>(null)

function keyOf(ex: TgExchange): string {
  return ex.turnId ?? `ex:${ex.id}`
}
function openReport(ex: TgExchange) {
  reportTurnId.value = ex.turnId ?? null
  reportKey = keyOf(ex)
  reportChatId.value = chat.currentChatId()
  reportOpen.value = true
}
function onReportSent(payload: { turnId: string | null }) {
  const key = payload.turnId ?? reportKey
  if (key) reportedKeys.value = new Set([...reportedKeys.value, key])
}

/* ── Ushlab turish menyusi ───────────────────────────────────────────────── */
const menuOpen = ref(false)
const menuEx = ref<TgExchange | null>(null)
const menuPart = ref<'question' | 'answer'>('answer')
const menuSource = ref<HTMLElement | null>(null)
/** Bosilgan qismning matni: javob bo'lsa - javob (yoki xato), savol bo'lsa - savol. */
const menuText = computed(() => {
  const ex = menuEx.value
  if (!ex) return ''
  if (menuPart.value === 'question') return ex.question.trim()
  return (ex.response?.answer || ex.error || '').trim()
})
const menuItems = computed<MenuItem[]>(() => {
  const ex = menuEx.value
  if (!ex) return []
  const items: MenuItem[] = [{ id: 'copy', label: t('ui.copy'), icon: Copy }]
  if (menuPart.value === 'answer' && ex.response?.answer) items.push({ id: 'select', label: t('tg.chat.selectText'), icon: TextSelect })
  if (ex.question && phase.value === 'idle' && (!!ex.error || !!ex.cancelled)) items.push({ id: 'retry', label: t('retry'), icon: RotateCw })
  if ((ex.response || ex.error) && ex.id !== streamingId.value) items.push({ id: 'report', label: t('report.title'), icon: Flag })
  return items
})
function openMenu(ex: TgExchange, part: 'question' | 'answer', el: HTMLElement) {
  menuEx.value = ex
  menuPart.value = part
  menuSource.value = el
  menuOpen.value = true
}

const selectOpen = ref(false)
const selectText = ref('')

async function onMenuSelect(id: string) {
  const ex = menuEx.value
  if (!ex) return
  if (id === 'copy') {
    if (await copyText(menuText.value)) {
      haptic.notify('success')
      toast.success(menuPart.value === 'answer' ? t('tg.chat.copied') : t('ui.copied'))
    } else {
      haptic.notify('error')
      toast.error(t('chat.copyFailed'))
    }
  } else if (id === 'select') {
    selectText.value = menuSource.value ? plainText(menuSource.value) : menuText.value
    selectOpen.value = true
  } else if (id === 'retry') chat.regenerate(ex.id)
  else if (id === 'report') openReport(ex)
}

/* ── Toast'lar kompozer ustida ───────────────────────────────────────────── */
const composerEl = ref<HTMLElement | null>(null)
let composerRo: ResizeObserver | null = null
function syncToastOffset() {
  const h = composerEl.value?.offsetHeight ?? 0
  document.documentElement.style.setProperty('--tg-toast-bottom', `${h + 8}px`)
}

/* ── Chiqish / qayta ulash ───────────────────────────────────────────────── */
async function onLogout() {
  settingsOpen.value = false
  chat.abort()
  stopReading()
  await session.logout()
}
async function onReconnect() {
  chat.abort()
  stopReading()
  await session.reconnect()
}

let offSettings: () => void = () => {}
onMounted(() => {
  const owner = user.value ? String(user.value.actorId) : null
  if (owner) void chats.load(owner)
  void pro.load()
  offSettings = onSettingsButton(() => (settingsOpen.value = true))

  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(onResize)
    if (scroller.value) ro.observe(scroller.value)
    if (column.value) ro.observe(column.value)
    composerRo = new ResizeObserver(syncToastOffset)
    if (composerEl.value) composerRo.observe(composerEl.value)
  }
  syncToastOffset()
  // Markdown bo'lagi - bo'sh paytda oldindan: birinchi javob formatda chiqsin.
  const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback
  if (idle) idle(() => void loadMarkdown())
  else setTimeout(() => void loadMarkdown(), 1200)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  composerRo?.disconnect()
  offSettings()
  setClosingConfirmation(false)
  chat.abort()
  stopReading()
  document.documentElement.style.removeProperty('--tg-toast-bottom')
})
</script>

<template>
  <div class="chat">
    <TopBar
      :title="chat.title.value"
      :user-name="userName"
      :scrolled="scrolled"
      :can-start-new="canStartNew"
      @history="historyOpen = true"
      @new-chat="newChat"
      @settings="settingsOpen = true"
    />

    <main ref="scroller" class="chat__scroll" @scroll.passive="onScroll">
      <div ref="column" class="chat__col" :class="{ 'is-welcome': welcome }">
        <TgWelcome
          v-if="welcome"
          :name="firstName"
          :dim="dictating"
          :resume="resume"
          @pick="pickSuggestion"
          @resume="openFromHistory"
        />

        <div v-else-if="historyLoading" class="chat__skeleton" aria-hidden="true">
          <span class="tg-skel chat__skel-q" />
          <span class="tg-skel chat__skel-line" style="width: 92%" />
          <span class="tg-skel chat__skel-line" style="width: 84%" />
          <span class="tg-skel chat__skel-line" style="width: 60%" />
          <span class="tg-skel chat__skel-q" />
          <span class="tg-skel chat__skel-line" style="width: 88%" />
          <span class="tg-skel chat__skel-line" style="width: 70%" />
        </div>

        <div v-else-if="historyError" class="chat__failed" role="alert">
          <span class="chat__failed-icon" aria-hidden="true"><RotateCcw :size="22" :stroke-width="1.75" /></span>
          <p class="chat__failed-head">{{ t('historyOpenFailed') }}</p>
          <!-- Texnik sabab ("Request failed (500)") odamga emas - jurnalga; bu yerda nima
               qilish kerakligi. -->
          <p class="chat__failed-why">{{ t('tg.boot.hint') }}</p>
          <button type="button" class="chat__failed-btn" @click="chat.openHistory(chat.currentChatId(), true)">
            <RotateCw :size="16" :stroke-width="2" aria-hidden="true" />
            {{ t('retry') }}
          </button>
        </div>

        <template v-else>
          <Exchange
            v-for="ex in exchanges"
            :key="ex.id"
            :exchange="ex"
            :streaming="ex.id === streamingId"
            :reported="reportedKeys.has(keyOf(ex))"
            :landed="landed.has(ex.id)"
            @cite="openSources(ex, $event)"
            @report="openReport(ex)"
            @menu="(part, el) => openMenu(ex, part, el)"
            @retry="chat.regenerate(ex.id)"
            @reconnect="onReconnect"
          />
        </template>
      </div>
    </main>

    <footer ref="composerEl" class="chat__composer">
      <Transition name="jump">
        <button v-if="showJump" type="button" class="chat__jump" :aria-label="t('chat.jumpToLatest')" @click="jump">
          <ArrowDown :size="20" :stroke-width="2" aria-hidden="true" />
        </button>
      </Transition>
      <Composer :busy="phase === 'sending'" :send="send" @stop="chat.stop" @dictating="dictating = $event" />
    </footer>

    <HistorySheet v-model:open="historyOpen" @select="openFromHistory" @new-chat="newChat" @removed-active="newChat" />
    <SettingsSheet v-model:open="settingsOpen" :user="user" @logout="onLogout" />
    <SourcesSheet v-model:open="sourcesOpen" :items="sourcesList" :focus="sourcesFocus" />
    <ReportSheet v-model:open="reportOpen" :chat-id="reportChatId" :turn-id="reportTurnId" :messages="chat.reportMessages.value" @sent="onReportSent" />
    <ContextMenu
      v-model:open="menuOpen"
      :source="menuSource"
      :items="menuItems"
      :label="t('tg.chat.actions')"
      :align="menuPart === 'question' ? 'end' : 'start'"
      :pad="menuPart === 'answer' ? 10 : 0"
      @select="onMenuSelect"
    />
    <SelectTextSheet v-model:open="selectOpen" :text="selectText" />
  </div>
</template>

<style scoped>
.chat {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}
.chat__scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior-y: contain;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.chat__scroll::-webkit-scrollbar {
  display: none;
}
.chat__col {
  display: flex;
  flex-direction: column;
  gap: var(--s-8);
  min-height: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--s-4) calc(var(--tg-gutter) + var(--tg-safe-right)) var(--s-6) calc(var(--tg-gutter) + var(--tg-safe-left));
}
.chat__col.is-welcome {
  padding-bottom: var(--s-2);
}

.chat__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin-top: auto;
}
.chat__skel-q {
  align-self: flex-end;
  width: 56%;
  height: 40px;
  margin: var(--s-4) 0 var(--s-2);
  border-radius: 20px 20px 6px 20px;
}
.chat__skel-line {
  height: 14px;
}
.chat__failed {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  margin: auto 0;
  padding: 0 var(--s-4);
  text-align: center;
}
.chat__failed-icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-bottom: var(--s-2);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.chat__failed-head {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
}
.chat__failed-why {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.chat__failed-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  min-height: var(--tap);
  margin-top: var(--s-2);
  padding: 0 var(--s-5);
  border-radius: var(--r-full);
  background: var(--ink);
  color: var(--on-ink);
  font-weight: 600;
}

/* Kompozer: suhbat ustida suzib turadi, tepada yumshoq so'nish - matn uning ostiga
   "kirib ketadi", keskin chiziq yo'q. Pastki chekka o'tishsiz: klaviatura ochilganda
   34px uy chizig'i bo'shlig'i ramka bilan BIR kadrda yo'qoladi (layout.ts) - alohida
   animatsiya ikkinchi "siljish" bo'lib ko'rinardi. */
.chat__composer {
  position: relative;
  flex-shrink: 0;
  padding: var(--s-2) calc(var(--tg-chrome) + var(--tg-safe-right)) calc(var(--s-2) + var(--tg-safe-bottom))
    calc(var(--tg-chrome) + var(--tg-safe-left));
  background: var(--bg);
}
.chat__composer::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 100%;
  height: var(--s-6);
  background: linear-gradient(to bottom, transparent, var(--bg));
  pointer-events: none;
}

.chat__jump {
  position: absolute;
  left: 50%;
  bottom: calc(100% + var(--s-2));
  z-index: 1;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin-left: -20px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface);
  color: var(--text-2);
  box-shadow: var(--e2);
}
.chat__jump::after {
  content: '';
  position: absolute;
  inset: -4px;
}
.jump-enter-active,
.jump-leave-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.jump-enter-from,
.jump-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.9);
}
</style>
