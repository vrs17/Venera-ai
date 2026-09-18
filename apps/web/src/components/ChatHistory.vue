<script setup lang="ts">
// Yon paneldagi suhbatlar ro'yxati: kunlar bo'yicha guruhlangan qatorlar,
// qatorning o'zida nomini o'zgartirish, o'chirish va "Bekor qilish".
// Holat `composables/useChats.ts` da; bu komponent faqat ko'rsatadi va
// ochish/faol suhbat o'chirilganini yuqoriga (ChatView) xabar qiladi.
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { localizeApiError } from '../api/errors'
import { useChats } from '../composables/useChats'
import type { MsgKey } from '../i18n'
import { PencilIcon, TrashIcon, XIcon } from '../icons'
import type { ChatSummary } from '../types'

const emit = defineEmits<{
  open: [id: string]
  /** Hozir ochiq turgan suhbat o'chirildi - ekran yangi suhbatga o'tsin. */
  removedActive: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { chats, activeId, loading, loaded, loadFailed, lastDeleted, reload, rename, remove, undoDelete, dismissUndo } =
  useChats()

// Kunlar bo'yicha: bugun, kecha, oxirgi 7 kun, oldingilar. Ro'yxat allaqachon
// oxirgi faollik bo'yicha tartiblangan, guruhlash faqat ko'z uchun.
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
  for (const chat of chats.value) {
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

// Qisqa xato - qatorlar ostida, o'zi yo'qoladi.
const notice = ref<string | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | null = null
function flash(message: string) {
  notice.value = message
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => (notice.value = null), 5000)
}

// Nomini o'zgartirish - qatorning o'zida. Enter saqlaydi, Esc bekor qiladi,
// fokus ketsa saqlanadi. Bo'sh nom = bekor (server ham rad etardi).
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
function cancelRename() {
  editingId.value = null
}
async function commitRename(id: string) {
  // Enter dan keyin blur ham keladi - ikkinchisi bo'sh o'tadi.
  if (editingId.value !== id) return
  editingId.value = null
  try {
    await rename(id, draft.value)
  } catch (err) {
    flash(localizeApiError(err, t))
  }
}

async function onRemove(chat: ChatSummary) {
  const wasActive = chat.chat_id === activeId.value
  try {
    await remove(chat.chat_id)
  } catch (err) {
    flash(localizeApiError(err, t))
    return
  }
  if (wasActive) emit('removedActive')
}

async function onUndo() {
  try {
    await undoDelete()
  } catch (err) {
    flash(localizeApiError(err, t))
  }
}
</script>

<template>
  <nav class="hist" :aria-label="t('historyHeading')">
    <div class="hist__list">
      <p v-if="loading && !loaded" class="hist__note">{{ t('loading') }}</p>
      <p v-else-if="loadFailed && chats.length === 0" class="hist__note">
        {{ t('historyLoadFailed') }}
        <button class="hist__link" type="button" @click="reload">{{ t('retry') }}</button>
      </p>
      <p v-else-if="loaded && chats.length === 0" class="hist__note">{{ t('historyEmpty') }}</p>

      <template v-for="group in groups" :key="group.key">
        <div class="hist__label">{{ t(GROUP_LABEL[group.key]) }}</div>
        <div
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
            @keydown.enter.prevent="commitRename(chat.chat_id)"
            @keydown.esc.prevent="cancelRename"
            @blur="commitRename(chat.chat_id)"
          />
          <template v-else>
            <button class="hist__open" type="button" :title="chat.title" @click="emit('open', chat.chat_id)">
              {{ chat.title }}
            </button>
            <span class="hist__tools">
              <button
                class="hist__tool"
                type="button"
                :aria-label="t('renameChat')"
                :title="t('renameChat')"
                @click.stop="startRename(chat)"
              >
                <PencilIcon :size="13" stroke="currentColor" />
              </button>
              <button
                class="hist__tool hist__tool--danger"
                type="button"
                :aria-label="t('deleteChat')"
                :title="t('deleteChat')"
                @click.stop="onRemove(chat)"
              >
                <TrashIcon :size="13" />
              </button>
            </span>
          </template>
        </div>
      </template>
    </div>

    <!-- O'chirildi, lekin yo'qolmadi: bir necha soniya qaytarish mumkin. -->
    <div v-if="lastDeleted" class="hist__undo" role="status">
      <span class="hist__undo-text">{{ t('chatDeleted') }}</span>
      <button class="hist__link" type="button" @click="onUndo">{{ t('undo') }}</button>
      <button class="hist__tool" type="button" :aria-label="t('close')" @click="dismissUndo">
        <XIcon :size="12" />
      </button>
    </div>
    <p v-if="notice" class="hist__notice" role="alert">{{ notice }}</p>
  </nav>
</template>

<style scoped>
.hist {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  margin-top: 14px;
}
.hist__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  /* Chap tomonda qatorlar chetiga, o'ngda scrollbar uchun joy. */
  margin: 0 -6px 0 -4px;
  padding: 0 6px 6px 4px;
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar) transparent;
}
.hist__note {
  margin: 6px 8px;
  font-size: 12.5px;
  line-height: 1.4;
  color: var(--text-muted);
}
.hist__label {
  margin: 12px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.hist__label:first-child {
  margin-top: 2px;
}
.hist__row {
  position: relative;
  display: flex;
  align-items: center;
  border-radius: 10px;
  color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
}
.hist__row:hover,
.hist__row:focus-within {
  background: var(--surface-hover);
  color: var(--text);
}
.hist__row.is-active {
  background: var(--surface);
  color: var(--text);
  box-shadow: inset 0 0 0 1px var(--border);
}
.hist__open {
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border: none;
  background: transparent;
  color: inherit;
  font-family: 'Figtree', sans-serif;
  font-size: 13.5px;
  font-weight: 500;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}
.hist__tools {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  padding-right: 4px;
}
.hist__tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--icon-muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.hist__tool:hover {
  background: var(--surface);
  color: var(--text);
}
.hist__tool--danger:hover {
  color: var(--bad-fg);
}
/* Sichqonchali qurilmalarda tugmalar faqat qator ustida ko'rinadi; sensorli
   ekranlarda (hover yo'q) doim turadi - aks holda ularga yetib bo'lmasdi. */
@media (hover: hover) {
  .hist__tools {
    opacity: 0;
    transition: opacity 0.15s;
  }
  .hist__row:hover .hist__tools,
  .hist__row:focus-within .hist__tools {
    opacity: 1;
  }
}
.hist__input {
  flex: 1;
  min-width: 0;
  margin: 2px 4px;
  padding: 6px 6px;
  border: 1px solid var(--border-hover);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-family: 'Figtree', sans-serif;
  font-size: 13.5px;
  font-weight: 500;
  outline: none;
}
.hist__input:focus {
  border-color: var(--accent);
}
.hist__undo {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding: 8px 6px 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  font-size: 12.5px;
  color: var(--text-secondary);
  animation: fadeUp 0.2s ease both;
}
.hist__undo-text {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hist__link {
  padding: 2px 4px;
  border: none;
  background: transparent;
  color: var(--link);
  font-family: 'Figtree', sans-serif;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.hist__link:hover {
  text-decoration: underline;
}
.hist__notice {
  margin: 6px 8px 0;
  padding: 6px 8px;
  font-size: 12px;
  line-height: 1.35;
  color: var(--bad-fg);
  background: var(--bad-bg);
  border: 1px solid var(--bad-bd);
  border-radius: 8px;
}
</style>
