<script setup lang="ts">
// Yon paneldagi suhbatlar ro'yxati: kunlar bo'yicha guruhlangan qatorlar, ⋯ menyuda
// nomini o'zgartirish (qatorning o'zida) va o'chirish (8 s "Bekor qilish" bilan).
// Holat `composables/useChats.ts` da; bu komponent faqat ko'rsatadi va ochish / faol
// suhbat o'chirilganini yuqoriga (ChatView) xabar qiladi.
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Ellipsis, Pencil, Trash2 } from 'lucide-vue-next'
import { useChats } from '../composables/useChats'
import type { MsgKey } from '../i18n'
import type { ChatSummary } from '../types'
import VIconButton from '../ui/VIconButton.vue'
import VMenu from '../ui/VMenu.vue'
import type { MenuEntry } from '../ui/VMenu.vue'
import VSkeleton from '../ui/VSkeleton.vue'
import { normalizeSearch } from '../ui/useCommandPalette'
import { useChatActions } from './chat/chatActions'

const props = withDefaults(defineProps<{ query?: string }>(), { query: '' })
const emit = defineEmits<{
  open: [id: string]
  /** Hozir ochiq turgan suhbat o'chirildi - ekran yangi suhbatga o'tsin. */
  removedActive: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { chats, activeId, loading, loaded, loadFailed, reload } = useChats()
const { renameChat, deleteChat } = useChatActions()

// Qidiruv - yuklangan nomlar bo'yicha, brauzerda (server qidiruvi keyin).
const visible = computed(() => {
  const q = normalizeSearch(props.query.trim())
  if (!q) return chats.value
  return chats.value.filter((c) => normalizeSearch(c.title).includes(q))
})

// Kunlar bo'yicha: bugun, kecha, oxirgi 7 kun, oldingilar. Ro'yxat allaqachon oxirgi
// faollik bo'yicha tartiblangan, guruhlash faqat ko'z uchun. Sanasi yo'q - "oldingilar".
type GroupKey = 'today' | 'yesterday' | 'week' | 'older'
const GROUP_LABEL: Record<GroupKey, MsgKey> = {
  today: 'historyToday',
  yesterday: 'historyYesterday',
  week: 'historyWeek',
  older: 'historyOlder',
}
const groups = computed(() => {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000
  const buckets: Record<GroupKey, ChatSummary[]> = { today: [], yesterday: [], week: [], older: [] }
  for (const chat of visible.value) {
    const at = chat.updated_at ? Date.parse(chat.updated_at) : NaN
    const key: GroupKey = !Number.isFinite(at)
      ? 'older'
      : at >= startOfToday
        ? 'today'
        : at >= startOfToday - day
          ? 'yesterday'
          : at >= startOfToday - 6 * day
            ? 'week'
            : 'older'
    buckets[key].push(chat)
  }
  return (Object.keys(buckets) as GroupKey[])
    .map((key) => ({ key, items: buckets[key] }))
    .filter((group) => group.items.length > 0)
})

const list = ref<HTMLElement | null>(null)
function focusRow(id: string | null) {
  if (!id) return
  list.value?.querySelector<HTMLElement>(`.hist__open[data-id="${CSS.escape(id)}"]`)?.focus()
}

// Nomini o'zgartirish - qatorning o'zida. Enter saqlaydi, Esc bekor qiladi (ChatView
// Esc'ni ko'rmasin - preventDefault), fokus ketsa saqlanadi. Bo'sh nom = bekor.
const editingId = ref<string | null>(null)
const draft = ref('')
let inputEl: HTMLInputElement | null = null
function bindInput(el: unknown) {
  // v-for ichidagi ref massiv bo'lib qoladi; funksiya ref bilan bitta element.
  inputEl = (el as HTMLInputElement | null) ?? null
}
async function startRename(chat: ChatSummary) {
  editingId.value = chat.chat_id
  draft.value = chat.title
  await nextTick()
  inputEl?.focus()
  inputEl?.select()
}
function cancelRename(id: string) {
  editingId.value = null
  void nextTick(() => focusRow(id))
}
async function commitRename(id: string, refocus: boolean) {
  // Enter dan keyin blur ham keladi - ikkinchisi bo'sh o'tadi.
  if (editingId.value !== id) return
  editingId.value = null
  if (refocus) void nextTick(() => focusRow(id))
  await renameChat(id, draft.value)
}

function remove(chat: ChatSummary) {
  // Qator yo'qoladi - fokus qo'shni qatorga o'tsin, <body> ga tushib qolmasin.
  const ids = visible.value.map((c) => c.chat_id)
  const at = ids.indexOf(chat.chat_id)
  const neighbour = ids[at + 1] ?? ids[at - 1] ?? null
  void deleteChat(chat.chat_id, () => emit('removedActive'))
  setTimeout(() => focusRow(neighbour), 0)
}

function menuFor(chat: ChatSummary): MenuEntry[] {
  return [
    // Menyu yopilib, fokus o'z joyiga qaytgandan KEYIN tahrirga o'tamiz.
    { label: t('renameChat'), icon: Pencil, onSelect: () => setTimeout(() => void startRename(chat), 0) },
    { label: t('deleteChat'), icon: Trash2, danger: true, onSelect: () => remove(chat) },
  ]
}

/** ↑ / ↓ / Home / End - qatorlar orasida yurish. */
function onRowKey(e: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
  const rows = Array.from(list.value?.querySelectorAll<HTMLElement>('.hist__open') ?? [])
  const i = rows.indexOf(e.currentTarget as HTMLElement)
  if (i < 0 || !rows.length) return
  e.preventDefault()
  const next =
    e.key === 'Home' ? 0 : e.key === 'End' ? rows.length - 1 : e.key === 'ArrowDown' ? Math.min(i + 1, rows.length - 1) : Math.max(i - 1, 0)
  rows[next]?.focus()
}
</script>

<template>
  <nav class="hist" :aria-label="t('historyHeading')">
    <div ref="list" class="hist__list">
      <div v-if="loading && !loaded" class="hist__skeleton" aria-hidden="true">
        <VSkeleton v-for="w in ['72%', '56%', '84%', '64%', '48%']" :key="w" :width="w" :height="12" />
      </div>
      <p v-if="loading && !loaded" class="sr-only" role="status">{{ t('loading') }}</p>

      <p v-if="loadFailed" class="hist__note">
        {{ t('historyLoadFailed') }}
        <button class="hist__link" type="button" @click="reload">{{ t('retry') }}</button>
      </p>
      <p v-else-if="loaded && chats.length === 0" class="hist__note">{{ t('historyEmpty') }}</p>
      <p v-else-if="query.trim() && visible.length === 0" class="hist__note">{{ t('ui.noResults') }}</p>

      <section v-for="group in groups" :key="group.key" class="hist__group">
        <h2 class="hist__label">{{ t(GROUP_LABEL[group.key]) }}</h2>
        <ul class="hist__rows">
          <li
            v-for="chat in group.items"
            :key="chat.chat_id"
            class="hist__row"
            :class="{ 'is-active': chat.chat_id === activeId, 'is-editing': editingId === chat.chat_id }"
          >
            <input
              v-if="editingId === chat.chat_id"
              :ref="bindInput"
              v-model="draft"
              class="hist__input"
              type="text"
              maxlength="80"
              :aria-label="t('renameChat')"
              @keydown.enter.prevent="commitRename(chat.chat_id, true)"
              @keydown.esc.prevent="cancelRename(chat.chat_id)"
              @blur="commitRename(chat.chat_id, false)"
            />
            <template v-else>
              <button
                class="hist__open"
                type="button"
                :data-id="chat.chat_id"
                :title="chat.title"
                :aria-current="chat.chat_id === activeId ? 'page' : undefined"
                @click="emit('open', chat.chat_id)"
                @keydown="onRowKey"
              >
                {{ chat.title }}
              </button>
              <VMenu placement="bottom-end" :items="menuFor(chat)" :aria-label="chat.title" :min-width="180">
                <template #trigger>
                  <VIconButton class="hist__more" size="sm" :icon="Ellipsis" :label="t('ui.moreActions')" />
                </template>
              </VMenu>
            </template>
          </li>
        </ul>
      </section>
    </div>
  </nav>
</template>

<style scoped>
.hist {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.hist__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 var(--s-2) var(--s-4);
}
.hist__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  padding: var(--s-4) var(--s-2);
}
.hist__note {
  margin: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.hist__link {
  color: var(--text);
  font-weight: 500;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
}
.hist__group + .hist__group {
  margin-top: var(--s-4);
}
.hist__label {
  padding: var(--s-2) var(--s-2) var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.hist__rows {
  margin: 0;
  padding: 0;
  list-style: none;
}
.hist__row {
  position: relative;
  display: flex;
  align-items: center;
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .hist__row:hover {
    background: var(--fill);
  }
}
.hist__row.is-active {
  background: var(--fill);
}
.hist__open {
  flex: 1;
  min-width: 0;
  height: 36px;
  padding: 0 40px 0 var(--s-2);
  border-radius: var(--r-sm);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: 36px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hist__row.is-active .hist__open,
.hist__row:hover .hist__open {
  color: var(--text);
}
.hist__open:focus-visible {
  outline-offset: -2px;
}
.hist__more {
  position: absolute;
  right: 2px;
  top: 50%;
  translate: 0 -50%;
}
/* ⋯ - sichqonchali qurilmada faqat qator ustida / fokusda / menyu ochiq bo'lsa;
   sensorli ekranda doim (aks holda unga yetib bo'lmasdi). */
@media (hover: hover) {
  .hist__more {
    opacity: 0;
    transition: opacity var(--dur-1) var(--ease-out);
  }
  .hist__row:hover .hist__more,
  .hist__row:focus-within .hist__more,
  .hist__more[aria-expanded='true'] {
    opacity: 1;
  }
}
@media (pointer: coarse) {
  .hist__open {
    height: 44px;
    line-height: 44px;
  }
}
.hist__input {
  flex: 1;
  min-width: 0;
  height: 36px;
  padding: 0 var(--s-2);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-body-sm);
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--text) 10%, transparent);
}
</style>
