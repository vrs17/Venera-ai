<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckIcon, CopyIcon } from '../icons'
import { copyText } from '../clipboard'

/**
 * Reusable copy control. Used both in the answer action bar (with a text label)
 * and on the user's prompt bubble (icon-only). Shows a brief check + "Copied"
 * confirmation, then reverts. `ariaLabel` is the accessible name when no visible
 * label is rendered.
 */
const props = defineProps<{ text: string; label?: string; ariaLabel?: string; size?: number }>()

const { t } = useI18n({ useScope: 'global' })
const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

async function onCopy() {
  const ok = await copyText(props.text)
  if (!ok) return
  copied.value = true
  clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1600)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <button
    type="button"
    class="msg-action"
    :class="{ 'is-copied': copied }"
    :title="copied ? t('copied') : ariaLabel ?? label ?? t('copy')"
    :aria-label="copied ? t('copied') : ariaLabel ?? label ?? t('copy')"
    @click="onCopy"
  >
    <CheckIcon v-if="copied" :size="size ?? 15" stroke="currentColor" />
    <CopyIcon v-else :size="size ?? 15" />
    <span v-if="label">{{ copied ? t('copied') : label }}</span>
  </button>
</template>
