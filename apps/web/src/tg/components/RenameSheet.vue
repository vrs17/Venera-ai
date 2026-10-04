<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatActions } from '../../components/chat/chatActions'
import VSheet from '../../ui/VSheet.vue'
import { useTgSheet } from '../sheet'
import { haptic } from '../telegram'

/**
 * Suhbat nomini o'zgartirish (tarix qatorini uzoq bosib -> "Nomini o'zgartirish").
 * Bitta maydon va bitta katta tugma; maydon ochilganda fokusda (klaviatura darhol),
 * matn belgilangan - yangi nom eskisining ustiga yoziladi. Saqlash umumiy
 * `useChatActions().renameChat` orqali (optimistik, xatoda toast).
 */
const props = defineProps<{ chatId: string | null; title: string }>()
const open = defineModel<boolean>('open', { default: false })
const { t } = useI18n({ useScope: 'global' })
const { renameChat } = useChatActions()

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
useTgSheet(open, sheet)

const value = ref('')
const input = ref<HTMLInputElement | null>(null)
watch(open, (on) => {
  if (on) value.value = props.title
})
const changed = computed(() => value.value.trim().length > 0 && value.value.trim() !== props.title.trim())

function onEnter() {
  input.value?.select()
}

async function save() {
  if (!props.chatId || !changed.value) {
    open.value = false
    return
  }
  const id = props.chatId
  const title = value.value.trim()
  open.value = false
  haptic.notify('success')
  await renameChat(id, title)
}
</script>

<template>
  <VSheet
    ref="sheet"
    v-model:open="open"
    class="tg-sheet"
    side="bottom"
    :title="t('tg.history.rename')"
    initial-focus=".ren__input"
    @after-enter="onEnter"
  >
    <form class="ren" @submit.prevent="save">
      <input
        ref="input"
        v-model="value"
        class="ren__input"
        type="text"
        maxlength="120"
        enterkeyhint="done"
        autocomplete="off"
        :aria-label="t('tg.history.renameTitle')"
      />
      <button type="submit" class="ren__save" :disabled="!changed">{{ t('tg.history.save') }}</button>
    </form>
  </VSheet>
</template>

<style scoped>
.ren {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  padding-top: var(--s-1);
}
.ren__input {
  width: 100%;
  min-height: max(52px, calc(1.5em + 22px));
  padding: 0 var(--s-4);
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--surface);
  color: var(--text);
  line-height: 1.5;
  outline: none;
  -webkit-appearance: none;
  appearance: none;
}
.ren__input:focus {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ink) 8%, transparent);
}
.ren__save {
  min-height: 52px;
  border-radius: 14px;
  background: var(--ink);
  color: var(--on-ink);
  font-size: var(--fs-body);
  font-weight: 600;
  transition:
    transform var(--dur-1) var(--ease-out),
    opacity var(--dur-1) var(--ease-out);
}
.ren__save:disabled {
  opacity: 0.4;
}
.ren__save:active:not(:disabled) {
  transform: scale(0.98);
}
</style>
