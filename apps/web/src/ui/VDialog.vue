<script setup lang="ts">
import VSheet from './VSheet.vue'
import type { SheetCloseReason } from './VSheet.vue'

/**
 * Markaziy modal oyna: 440 (sm) / 560 (md) / 720 (lg), 24px burchak, e3 soya.
 *
 * O'zi hech narsa chizmaydi - VSheet'ni `side="center"` bilan ishlatadi: fokus
 * tuzog'i, Esc, tashqariga bosish, sahifa qulfi, fokusni qaytarish va telefonda
 * pastki sheet (tortib yopish tutqichi bilan) - hammasi bitta joyda.
 *
 * Ochilganda fokus: `[data-autofocus]` / `autofocus` elementiga, bo'lmasa tanadagi
 * birinchi boshqaruvga (sarlavhadagi × ga emas). Telefonda - panelning o'ziga.
 *
 *   <VDialog v-model:open="show" :title="t('report.title')" :description="...">
 *     ...
 *     <template #footer>
 *       <VButton variant="ghost" @click="show = false">...</VButton>
 *       <VButton variant="primary" :loading="sending" @click="send">...</VButton>
 *     </template>
 *   </VDialog>
 */
withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg'
    title?: string
    description?: string
    ariaLabel?: string
    /** false - hech qanday yo'l bilan yopilmaydi (so'rov ketayotganda). */
    dismissible?: boolean
    closeOnEscape?: boolean
    closeOnOutside?: boolean
    hideClose?: boolean
    initialFocus?: string | (() => HTMLElement | null | undefined)
    padding?: 'none' | 'md'
    /** Tasdiqlash ("Bloklash?") - ekran o'quvchi darhol o'qiydi. */
    alert?: boolean
  }>(),
  {
    size: 'sm',
    dismissible: true,
    closeOnEscape: true,
    closeOnOutside: true,
    initialFocus: 'auto',
    padding: 'md',
  },
)

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{
  close: [reason: SheetCloseReason]
  'after-enter': []
  'after-leave': []
}>()

defineSlots<{
  header?(props: { titleId: string; close: () => void }): unknown
  default?(props: { close: () => void }): unknown
  footer?(props: { close: () => void }): unknown
}>()
</script>

<template>
  <VSheet
    v-model:open="open"
    side="center"
    layer="dialog"
    :role="alert ? 'alertdialog' : 'dialog'"
    :size="size"
    :title="title"
    :description="description"
    :aria-label="ariaLabel"
    :dismissible="dismissible"
    :close-on-escape="closeOnEscape"
    :close-on-outside="closeOnOutside"
    :hide-close="hideClose"
    :initial-focus="initialFocus"
    :padding="padding"
    @close="emit('close', $event)"
    @after-enter="emit('after-enter')"
    @after-leave="emit('after-leave')"
  >
    <template v-if="$slots.header" #header="p">
      <slot name="header" v-bind="p" />
    </template>
    <template #default="p">
      <slot v-bind="p" />
    </template>
    <template v-if="$slots.footer" #footer="p">
      <slot name="footer" v-bind="p" />
    </template>
  </VSheet>
</template>
