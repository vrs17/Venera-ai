<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagesSquare, PencilLine, RotateCw, Search, SquarePen, Trash2, X } from 'lucide-vue-next'
import { useChatActions } from '../../components/chat/chatActions'
import { useChats } from '../../composables/useChats'
import type { MsgKey } from '../../i18n'
import type { ChatSummary } from '../../types'
import VSheet from '../../ui/VSheet.vue'
import { useTgSheet } from '../sheet'
import ContextMenu from './ContextMenu.vue'
import type { MenuItem } from './ContextMenu.vue'
import HistoryRow from './HistoryRow.vue'
import RenameSheet from './RenameSheet.vue'

/**
 * Suhbatlar tarixi - to'liq bo'yli pastki oyna. Sarlavhada faqat nom va ✕; tepada
 * qidiruv, ostida kunlar bo'yicha guruhlar (Bugun, Kecha, Oxirgi 7 kun, Oldingilar -
 * web'dagi `ChatHistory.vue` bilan bir xil qoidalar). "Yangi suhbat" - PASTDA, bosh
 * barmoq ostida yopishqoq keng tugma (yuqori o'ng burchak - eng qiyin yetiladigan joy;
 * yuqori panelda qalam tugmasi ham bor).
 *
 * Qator bosilsa - ochiladi va oyna yopiladi; chapga surilsa - "O'chirish" (8 s "Bekor
 * qilish" bilan, umumiy useChatActions). Android'ning imo-ishora navigatsiyasida
 * o'ng chetdan surish tizim "Orqaga" si bo'lib ketadi - shuning uchun imo-ishorasiz
 * yo'l ham bor: qatorni USHLAB TURISH -> "Nomini o'zgartirish" / "O'chirish".
 *
 * Yopish: tutqich yoki ro'yxat tepasidan pastga tortish, Telegram "Orqaga", pardaga
 * bosish yoki ✕. Ochiq paytda ortdagi ilova kichrayadi (iOS "karta" chuqurligi).
 */
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ select: [id: string]; newChat: []; removedActive: [] }>()
const { t } = useI18n({ useScope: 'global' })
const { chats, activeId, loading, loaded, loadFailed, reload } = useChats()
const { deleteChat } = useChatActions()

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
useTgSheet(open, sheet, { depth: true })

const query = ref('')
const revealed = ref<string | null>(null)

// Oyna yopilganda surilgan qator va qidiruv tozalanadi - keyingi ochilish toza.
watch(open, (on) => {
  if (on) {
    if (!loaded.value && !loading.value) void reload()
    return
  }
  revealed.value = null
  query.value = ''
})

const APOSTROPHES = /[‘’ʻʼ`´]/g
function norm(s: string): string {
  return s.toLocaleLowerCase().replace(APOSTROPHES, "'")
}

const visible = computed(() => {
  const q = norm(query.value.trim())
  return q ? chats.value.filter((c) => norm(c.title).includes(q)) : chats.value
})

type GroupKey = 'today' | 'yesterday' | 'week' | 'older'
const GROUP_LABEL: Record<GroupKey, MsgKey> = {
  today: 'historyToday',
  yesterday: 'historyYesterday',
  week: 'historyWeek',
  older: 'historyOlder',
}
const groups = computed(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000
  const buckets: Record<GroupKey, ChatSummary[]> = { today: [], yesterday: [], week: [], older: [] }
  for (const chat of visible.value) {
    const at = chat.updated_at ? Date.parse(chat.updated_at) : NaN
    const key: GroupKey = !Number.isFinite(at)
      ? 'older'
      : at >= today
        ? 'today'
        : at >= today - day
          ? 'yesterday'
          : at >= today - 6 * day
            ? 'week'
            : 'older'
    buckets[key].push(chat)
  }
  return (Object.keys(buckets) as GroupKey[]).map((key) => ({ key, items: buckets[key] })).filter((g) => g.items.length)
})

function select(id: string) {
  emit('select', id)
  open.value = false
}

function startNew() {
  emit('newChat')
  open.value = false
}

function remove(chat: ChatSummary) {
  revealed.value = null
  void deleteChat(chat.chat_id, () => emit('removedActive'))
}

function onReveal(id: string, on: boolean) {
  revealed.value = on ? id : revealed.value === id ? null : revealed.value
}

/* ── Ushlab turish menyusi ── */
const menuOpen = ref(false)
const menuChat = ref<ChatSummary | null>(null)
const menuSource = ref<HTMLElement | null>(null)
const menuItems = computed<MenuItem[]>(() => [
  { id: 'rename', label: t('tg.history.rename'), icon: PencilLine },
  { id: 'delete', label: t('tg.history.delete'), icon: Trash2, tone: 'crit' },
])
function onMenu(chat: ChatSummary, el: HTMLElement) {
  revealed.value = null
  menuChat.value = chat
  menuSource.value = el
  menuOpen.value = true
}
const renameOpen = ref(false)
function onMenuSelect(id: string) {
  const chat = menuChat.value
  if (!chat) return
  if (id === 'rename') renameOpen.value = true
  else if (id === 'delete') remove(chat)
}
</script>

<template>
  <VSheet
    ref="sheet"
    v-model:open="open"
    class="tg-sheet tg-sheet--full"
    side="bottom"
    padding="none"
    :title="t('historyHeading')"
  >
    <div class="hist">
      <label class="hsearch">
        <Search class="hsearch__icon" :size="18" :stroke-width="1.75" aria-hidden="true" />
        <input
          v-model="query"
          class="hsearch__input"
          type="search"
          enterkeyhint="search"
          autocomplete="off"
          :placeholder="t('tg.history.search')"
          :aria-label="t('tg.history.search')"
        />
        <button v-if="query" type="button" class="hsearch__clear" :aria-label="t('ui.clear')" @click="query = ''">
          <X :size="16" :stroke-width="2" aria-hidden="true" />
        </button>
      </label>

      <div v-if="loading && !loaded" class="hist__skeleton" aria-hidden="true">
        <span class="tg-skel hist__skel-label" />
        <span v-for="i in 6" :key="i" class="tg-skel hist__skel-row" :style="{ width: `${92 - (i % 3) * 14}%` }" />
      </div>
      <p v-if="loading && !loaded" class="sr-only" role="status">{{ t('loading') }}</p>

      <div v-else-if="loadFailed && !chats.length" class="hist__note" role="alert">
        <p>{{ t('historyLoadFailed') }}</p>
        <button type="button" class="hist__retry" @click="reload">
          <RotateCw :size="16" :stroke-width="2" aria-hidden="true" />
          {{ t('retry') }}
        </button>
      </div>
      <div v-else-if="loaded && !chats.length" class="hist__empty">
        <span class="hist__empty-icon" aria-hidden="true"><MessagesSquare :size="24" :stroke-width="1.75" /></span>
        <p class="hist__empty-title">{{ t('tg.history.empty') }}</p>
        <p class="hist__empty-hint">{{ t('tg.history.emptyHint') }}</p>
      </div>
      <p v-else-if="query.trim() && !visible.length" class="hist__note">{{ t('ui.noResults') }}</p>

      <section v-for="group in groups" :key="group.key" class="hgroup">
        <h3 class="hgroup__label">{{ t(GROUP_LABEL[group.key]) }}</h3>
        <TransitionGroup tag="ul" name="hrow" class="hgroup__list">
          <HistoryRow
            v-for="chat in group.items"
            :key="chat.chat_id"
            :chat="chat"
            :active="chat.chat_id === activeId"
            :revealed="revealed === chat.chat_id"
            @open="select(chat.chat_id)"
            @remove="remove(chat)"
            @reveal="onReveal(chat.chat_id, $event)"
            @menu="onMenu(chat, $event)"
            @swipe="revealed !== chat.chat_id && (revealed = null)"
          />
        </TransitionGroup>
      </section>

      <!-- Bosh barmoq ostida: pastga yopishgan keng tugma; ro'yxat uning ostidan
           so'nib o'tadi. -->
      <div class="hist__foot">
        <button type="button" class="hist__new" @click="startNew">
          <SquarePen :size="18" :stroke-width="2" aria-hidden="true" />
          {{ t('tg.top.newChat') }}
        </button>
      </div>
    </div>
  </VSheet>

  <ContextMenu
    v-model:open="menuOpen"
    :source="menuSource"
    :items="menuItems"
    :label="t('tg.history.actions')"
    @select="onMenuSelect"
  />
  <RenameSheet v-model:open="renameOpen" :chat-id="menuChat?.chat_id ?? null" :title="menuChat?.title ?? ''" />
</template>

<style scoped>
/* Matn chekkasi 16px: konteyner 8px + qator ichida 8px (qator foni esa chetdan-chetga). */
.hist {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-height: 100%;
  padding: 0 8px;
}
.hsearch {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-height: 44px;
  margin: 0 -8px;
  padding: 4px var(--tg-gutter) 8px;
  background: var(--surface);
}
.hsearch__icon {
  position: absolute;
  left: calc(var(--tg-gutter) + 12px);
  color: var(--text-3);
  pointer-events: none;
}
.hsearch__input {
  flex: 1;
  min-width: 0;
  height: max(44px, calc(1.5em + 18px));
  padding: 0 44px 0 42px;
  border: 0;
  border-radius: 12px;
  background: var(--fill);
  color: var(--text);
  font-size: 16px;
  outline: none;
  -webkit-appearance: none;
  appearance: none;
}
.hsearch__input::-webkit-search-cancel-button {
  display: none;
}
.hsearch__input:focus {
  box-shadow: 0 0 0 2px var(--line-strong);
}
.hsearch__clear {
  position: absolute;
  right: var(--tg-gutter);
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--r-full);
  color: var(--text-3);
}

.hgroup__label {
  padding: 0 8px var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
/* Qatorlar chetdan-chetga (surilganda qizil "O'chirish" ekran chetidan chiqadi). */
.hgroup__list {
  display: flex;
  flex-direction: column;
  margin: 0 -8px;
  padding: 0;
  list-style: none;
}

.hist__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  padding: var(--s-2) 8px;
}
.hist__skel-label {
  width: 64px;
  height: 10px;
}
.hist__skel-row {
  height: 16px;
}
.hist__note {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-10) var(--s-4);
  color: var(--text-3);
  text-align: center;
}
.hist__retry {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  min-height: var(--tap);
  padding: 0 var(--s-4);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text);
  font-weight: 600;
}
.hist__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-1);
  padding: var(--s-12, 48px) var(--s-4) var(--s-6);
  text-align: center;
}
.hist__empty-icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-bottom: var(--s-2);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.hist__empty-title {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
}
.hist__empty-hint {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

/* Pastki yopishqoq tugma: ro'yxat tagidan so'nib o'tadi (gradient), uy chizig'i
   ustida. Ro'yxat qisqa bo'lsa ham oyna pastida (margin-top: auto). */
.hist__foot {
  position: sticky;
  bottom: 0;
  z-index: 2;
  margin: auto -8px 0;
  padding: var(--s-2) var(--tg-gutter) calc(var(--s-2) + var(--tg-safe-bottom));
  background: linear-gradient(transparent, var(--surface) 24%);
}
.hist__new {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  width: 100%;
  min-height: 48px;
  border-radius: 14px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body);
  font-weight: 600;
  transition:
    transform var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out);
}
.hist__new:active {
  transform: scale(0.98);
  background: var(--fill-hover);
}

/* O'chirilgan qator yig'iladi, qolganlari silliq joyiga tushadi. */
.hrow-leave-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    max-height var(--dur-3) var(--ease-sheet);
  max-height: 72px;
}
.hrow-leave-to {
  opacity: 0;
  max-height: 0;
}
.hrow-enter-active {
  transition: opacity var(--dur-2) var(--ease-out);
}
.hrow-enter-from {
  opacity: 0;
}
.hrow-move {
  transition: transform var(--dur-3) var(--ease-sheet);
}
</style>
