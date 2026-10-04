<script setup lang="ts">
import { computed } from 'vue'

/**
 * Klaviatura yorlig'i: `<VKbd keys="mod+shift+o" />` → macOS'da ⌘ ⇧ O, boshqalarda Ctrl ⇧ O.
 *
 * `mod` - platformaga qarab ⌘ yoki Ctrl: bitta yozuv hamma joyda to'g'ri ko'rinadi.
 * `tone="inverse"` - siyoh foni ustida (tooltip, toast) ishlatish uchun.
 */
const props = withDefaults(
  defineProps<{
    keys: string | string[]
    tone?: 'default' | 'inverse'
    size?: 'sm' | 'md'
  }>(),
  { tone: 'default', size: 'md' },
)

const isMac =
  typeof navigator !== 'undefined' &&
  /mac|iphone|ipad|ipod/i.test(
    (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ??
      navigator.platform ??
      '',
  )

const MAP: Record<string, [mac: string, other: string]> = {
  mod: ['⌘', 'Ctrl'],
  cmd: ['⌘', 'Ctrl'],
  meta: ['⌘', 'Win'],
  ctrl: ['⌃', 'Ctrl'],
  control: ['⌃', 'Ctrl'],
  alt: ['⌥', 'Alt'],
  option: ['⌥', 'Alt'],
  shift: ['⇧', '⇧'],
  enter: ['↵', 'Enter'],
  return: ['↵', 'Enter'],
  esc: ['Esc', 'Esc'],
  escape: ['Esc', 'Esc'],
  tab: ['⇥', 'Tab'],
  backspace: ['⌫', '⌫'],
  delete: ['⌦', 'Del'],
  space: ['Space', 'Space'],
  up: ['↑', '↑'],
  down: ['↓', '↓'],
  left: ['←', '←'],
  right: ['→', '→'],
  arrowup: ['↑', '↑'],
  arrowdown: ['↓', '↓'],
  arrowleft: ['←', '←'],
  arrowright: ['→', '→'],
}

const parts = computed(() => {
  const list = Array.isArray(props.keys) ? props.keys : props.keys.split('+')
  return list
    .map((k) => k.trim())
    .filter(Boolean)
    .map((k) => {
      const hit = MAP[k.toLowerCase()]
      if (hit) return isMac ? hit[0] : hit[1]
      return k.length === 1 ? k.toUpperCase() : k
    })
})
</script>

<template>
  <kbd class="v-kbd" :class="[`v-kbd--${tone}`, `v-kbd--${size}`]">
    <kbd v-for="(k, i) in parts" :key="i" class="v-kbd__key">{{ k }}</kbd>
  </kbd>
</template>

<style scoped>
.v-kbd {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font: inherit;
  flex-shrink: 0;
}
.v-kbd__key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 var(--s-1_5);
  border-radius: var(--r-xs);
  background: var(--fill);
  /* --text-3 --fill ustida 4.2:1 - 11px yozuv uchun AA yetmaydi. */
  color: var(--text-2);
  font-family: var(--font-sans);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.v-kbd--sm .v-kbd__key {
  min-width: 18px;
  height: 18px;
  padding: 0 var(--s-1);
  font-size: 11px;
}
.v-kbd--inverse .v-kbd__key {
  background: color-mix(in srgb, var(--on-ink) 14%, transparent);
  color: color-mix(in srgb, var(--on-ink) 78%, transparent);
}
</style>
