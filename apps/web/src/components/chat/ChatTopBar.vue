<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, Ear, Ellipsis, Flag, Menu, Trash2 } from 'lucide-vue-next'
import VIconButton from '../../ui/VIconButton.vue'
import VMenu from '../../ui/VMenu.vue'
import type { MenuEntry } from '../../ui/VMenu.vue'

/**
 * Chat ustidagi 56px panel: chapda (telefon/planshetda menyu tugmasi va) suhbat nomi -
 * bosilsa shu yerning o'zida qayta nomlanadi; o'ngda "Xabar berish" (butun suhbat) va ⋯
 * (nusxa, o'chirish). Chegara chizig'i faqat suhbat aylantirilganda paydo bo'ladi.
 *
 * Mikrofon yoqiq ("Salom Venera" tinglayapti) bo'lsa - kichik quloq belgisi: mikrofon
 * ochiqligi DOIM ko'rinishi kerak (yon panel yopiq bo'lsa ham). Bosilsa - o'chadi.
 */
const props = withDefaults(
  defineProps<{
    title: string
    /** Suhbat serverda bor (ro'yxatda) - nomini o'zgartirish va o'chirish mumkin. */
    canRename?: boolean
    showMenuButton?: boolean
    /** Suhbatda kamida bitta savol bor - o'ng tomondagi amallar ko'rinadi. */
    hasChat?: boolean
    /** Kamida bitta yordamchi javobi bor (xato bilan tugagani ham - odamlar aynan
     *  yiqilgan javob haqida xabar bermoqchi bo'ladi). */
    canReport?: boolean
    reported?: boolean
    /** ⋯ menyu (telefonda yo'q - spec §4.3: menyu + nom + xabar). */
    showMore?: boolean
    scrolled?: boolean
    micLive?: boolean
    micDistorted?: boolean
  }>(),
  {
    canRename: false,
    showMenuButton: false,
    hasChat: false,
    canReport: false,
    reported: false,
    showMore: true,
    scrolled: false,
    micLive: false,
    micDistorted: false,
  },
)
const emit = defineEmits<{
  openMenu: []
  rename: [title: string]
  report: []
  copyChat: []
  deleteChat: []
  micOff: []
}>()

const { t } = useI18n({ useScope: 'global' })

// Qayta nomlash - yon paneldagi bilan bir xil qoidalar: Enter saqlaydi, Esc bekor
// qiladi (preventDefault - ChatView Esc'ni ko'rmasin), fokus ketsa saqlanadi.
const editing = ref(false)
const draft = ref('')
const input = ref<HTMLInputElement | null>(null)
const titleBtn = ref<HTMLButtonElement | null>(null)

async function startRename() {
  if (!props.canRename) return
  draft.value = props.title
  editing.value = true
  await nextTick()
  input.value?.focus()
  input.value?.select()
}
function finish(save: boolean, refocus: boolean) {
  if (!editing.value) return
  editing.value = false
  if (save) emit('rename', draft.value)
  if (refocus) void nextTick(() => titleBtn.value?.focus())
}

const reportLabel = computed(() => {
  if (!props.canReport) return t('report.unavailable')
  return props.reported ? t('report.reportedTooltip') : t('report.reportConversation')
})

const moreItems = computed<MenuEntry[]>(() => [
  { label: t('chat.copyChat'), icon: Copy, onSelect: () => emit('copyChat') },
  ...(props.canRename
    ? [{ label: t('deleteChat'), icon: Trash2, danger: true, onSelect: () => emit('deleteChat') } as MenuEntry]
    : []),
])
</script>

<template>
  <header class="top" :class="{ 'is-scrolled': scrolled }">
    <div class="top__start">
      <VIconButton v-if="showMenuButton" :icon="Menu" :label="t('menu')" tooltip-placement="bottom" @click="emit('openMenu')" />
      <input
        v-if="editing"
        ref="input"
        v-model="draft"
        class="top__input"
        type="text"
        maxlength="80"
        :aria-label="t('renameChat')"
        @keydown.enter.prevent="finish(true, true)"
        @keydown.esc.prevent="finish(false, true)"
        @blur="finish(true, false)"
      />
      <button
        v-else-if="title && canRename"
        ref="titleBtn"
        type="button"
        class="top__title is-button"
        :title="t('renameChat')"
        @click="startRename"
      >
        {{ title }}
      </button>
      <h1 v-else-if="title" class="top__title">{{ title }}</h1>
    </div>

    <div class="top__end">
      <VIconButton
        v-if="micLive"
        class="top__mic"
        :class="{ 'is-distorted': micDistorted }"
        :icon="Ear"
        :label="micDistorted ? t('chat.micDistorted') : t('chat.micLive')"
        :pressed="true"
        dot
        tooltip-placement="bottom"
        @click="emit('micOff')"
      />
      <template v-if="hasChat">
        <VIconButton
          class="top__flag"
          :class="{ 'is-reported': reported }"
          :label="reportLabel"
          :disabled="!canReport"
          tooltip-placement="bottom"
          @click="emit('report')"
        >
          <Flag :size="18" :stroke-width="1.75" :fill="reported ? 'currentColor' : 'none'" aria-hidden="true" />
        </VIconButton>
        <VMenu v-if="showMore" placement="bottom-end" :items="moreItems" :aria-label="t('ui.moreActions')">
          <template #trigger>
            <VIconButton :icon="Ellipsis" :label="t('ui.moreActions')" tooltip-placement="bottom" />
          </template>
        </VMenu>
      </template>
    </div>
  </header>
</template>

<style scoped>
.top {
  position: relative;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  flex-shrink: 0;
  height: 56px;
  padding: 0 var(--s-3) 0 var(--s-4);
  border-bottom: 1px solid transparent;
  background: var(--bg);
  transition: border-color var(--dur-2) var(--ease-out);
}
.top.is-scrolled {
  border-bottom-color: var(--line);
}
.top__start,
.top__end {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  min-width: 0;
}
.top__start {
  flex: 1;
}
.top__end {
  flex-shrink: 0;
}
.top__title {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  padding: var(--s-1) var(--s-2);
  border-radius: var(--r-sm);
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.top__title.is-button {
  text-align: left;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .top__title.is-button:hover {
    background: var(--fill);
  }
}
.top__input {
  flex: 1;
  min-width: 0;
  max-width: 480px;
  height: 36px;
  padding: 0 var(--s-2);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-body);
  font-weight: 500;
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--text) 10%, transparent);
}
.top__flag.is-reported {
  background: var(--brand-soft);
  color: var(--brand);
}
/* Mikrofon ochiq: brend nuqtasi - "efirda"; yozuv buzilgan bo'lsa - ogohlantirish rangi. */
.top__mic.is-distorted :deep(.v-icon-btn__dot) {
  background: var(--warn);
}
@media (max-width: 767.98px) {
  .top {
    padding: 0 var(--s-2);
  }
}
</style>
