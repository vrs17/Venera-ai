<script lang="ts">
import type { Component } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

export interface MenuItemEntry {
  kind?: 'item' | 'checkbox' | 'radio'
  label: string
  icon?: Component
  shortcut?: string | string[]
  hint?: string
  danger?: boolean
  disabled?: boolean
  checked?: boolean
  to?: RouteLocationRaw
  href?: string
  target?: string
  closeOnSelect?: boolean
  onSelect?: (e: Event) => void
}
export type MenuEntry = MenuItemEntry | { kind: 'separator' } | { kind: 'label'; label: string }
</script>

<script setup lang="ts">
import { onBeforeUnmount, provide, ref } from 'vue'
import VPopover from './VPopover.vue'
import VMenuItem, { MENU_KEY } from './VMenuItem.vue'
import type { PopoverFocusContext } from './VPopover.vue'
import type { FloatingAnchor, Placement } from './composables/useFloating'

/**
 * Harakatlar menyusi (⋯, akkaunt, filtr chip'i). VPopover ustiga qurilgan.
 *
 * Klaviatura (WAI menu naqshi):
 * - trigger'da ↓ / Enter / Space - ochadi va birinchi bandga; ↑ - oxirgisiga;
 * - ichida ↑ ↓ (aylanib), Home / End, harf terish - shu harf bilan boshlanuvchi bandga,
 *   Enter / Space - tanlash, Esc - yopish (fokus trigger'ga), Tab - yopish.
 * Sichqoncha bilan ochilganda fokus panelga tushadi (birinchi band ta'kidlanmaydi) -
 * xuddi tizim menyularidagidek. Ta'kid sichqonchaga ergashadi.
 *
 * Bandlar: slot orqali <VMenuItem> yoki `items` massivi (ma'lumotdan quriladigan menyu).
 */
const props = withDefaults(
  defineProps<{
    items?: MenuEntry[]
    placement?: Placement
    offset?: number
    width?: number | string
    minWidth?: number
    anchor?: FloatingAnchor | null
    ariaLabel?: string
    disabled?: boolean
  }>(),
  { placement: 'bottom-start', offset: 6, minWidth: 200, anchor: null },
)

const open = defineModel<boolean>('open', { default: false })

defineSlots<{
  trigger?(props: { open: boolean; toggle: () => void }): unknown
  default?(): unknown
}>()

const pop = ref<InstanceType<typeof VPopover> | null>(null)
// Trigger'dagi strelka qaysi bandga fokus berishni aytadi.
let intent: 'first' | 'last' | null = null

function panelEl(): HTMLElement | null {
  return (pop.value?.panel as HTMLElement | null | undefined) ?? null
}

function itemEls(): HTMLElement[] {
  const panel = panelEl()
  if (!panel) return []
  return Array.from(panel.querySelectorAll<HTMLElement>('[data-v-menu-item]:not([aria-disabled="true"])'))
}

function focusOnOpen(ctx: PopoverFocusContext): HTMLElement | null {
  const list = itemEls()
  const want = intent ?? (ctx.keyboard ? 'first' : null)
  intent = null
  if (want === 'first') return list[0] ?? null
  if (want === 'last') return list[list.length - 1] ?? null
  return panelEl()
}

function close(restoreFocus = true) {
  pop.value?.hide(restoreFocus)
}

provide(MENU_KEY, {
  close,
  clearHighlight: () => panelEl()?.focus({ preventScroll: true }),
})

function onTriggerKeyDown(e: KeyboardEvent) {
  if (props.disabled) return
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    intent = e.key === 'ArrowDown' ? 'first' : 'last'
    if (open.value) {
      const list = itemEls()
      ;(intent === 'first' ? list[0] : list[list.length - 1])?.focus()
      intent = null
    } else open.value = true
  }
}

/* ---- harf bilan qidirish ---- */
let buffer = ''
let bufferTimer: ReturnType<typeof setTimeout> | undefined

function textOf(el: HTMLElement): string {
  return (el.dataset.textValue ?? el.querySelector('.v-menu-item__label')?.textContent ?? el.textContent ?? '')
    .trim()
    .toLocaleLowerCase()
}

function typeahead(ch: string) {
  clearTimeout(bufferTimer)
  buffer += ch.toLocaleLowerCase()
  bufferTimer = setTimeout(() => (buffer = ''), 500)
  const list = itemEls()
  if (!list.length) return
  const current = list.indexOf(document.activeElement as HTMLElement)
  // "aaa" - bir xil harf takrorlansa, shu harfli bandlar orasida aylanamiz.
  const same = [...buffer].every((c) => c === buffer[0])
  const query = same ? buffer[0] : buffer
  const start = same ? current + 1 : Math.max(current, 0)
  for (let k = 0; k < list.length; k++) {
    const el = list[(start + k) % list.length]
    if (textOf(el).startsWith(query)) {
      el.focus()
      return
    }
  }
}

function onKeyDown(e: KeyboardEvent) {
  if (e.defaultPrevented || e.isComposing) return
  const list = itemEls()
  const idx = list.indexOf(document.activeElement as HTMLElement)
  const n = list.length
  const go = (i: number) => {
    e.preventDefault()
    list[i]?.focus()
  }
  switch (e.key) {
    case 'ArrowDown':
      if (n) go(idx < 0 ? 0 : (idx + 1) % n)
      return
    case 'ArrowUp':
      if (n) go(idx < 0 ? n - 1 : (idx - 1 + n) % n)
      return
    case 'Home':
    case 'PageUp':
      if (n) go(0)
      return
    case 'End':
    case 'PageDown':
      if (n) go(n - 1)
      return
    case 'Tab': {
      // WAI: Tab menyuni yopadi VA fokusni keyingi elementga o'tkazadi. Fokusni shu
      // zahoti trigger'ga qaytaramiz - brauzerning Tab amali undan davom etadi
      // (aks holda foydalanuvchi ikki marta Tab bosishi kerak edi).
      const back = (props.anchor instanceof HTMLElement ? props.anchor : null) ?? pop.value?.triggerEl ?? null
      if (back?.isConnected) {
        back.focus({ preventScroll: true })
        close(false)
      } else {
        e.preventDefault()
        close(true)
      }
      return
    }
    case 'Enter':
    case ' ':
      if (e.key === ' ' && buffer) break
      if (idx >= 0) {
        e.preventDefault()
        list[idx].click()
      }
      return
  }
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    typeahead(e.key)
  }
}

onBeforeUnmount(() => clearTimeout(bufferTimer))

defineExpose({ close, panel: panelEl })
</script>

<template>
  <VPopover
    ref="pop"
    v-model:open="open"
    :anchor="anchor"
    role="menu"
    :aria-label="ariaLabel"
    padding="sm"
    :placement="placement"
    :offset="offset"
    :width="width"
    :disabled="disabled"
    :auto-focus="focusOnOpen"
    :style="{ minWidth: `${minWidth}px`, maxWidth: 'min(320px, calc(100vw - 16px))' }"
    @keydown="onKeyDown"
    @trigger-keydown="onTriggerKeyDown"
  >
    <template v-if="$slots.trigger" #trigger="p">
      <slot name="trigger" v-bind="p" />
    </template>
    <template v-for="(entry, i) in items ?? []" :key="i">
      <VMenuItem v-if="entry.kind === 'separator'" kind="separator" />
      <VMenuItem v-else-if="entry.kind === 'label'" kind="label">{{ entry.label }}</VMenuItem>
      <VMenuItem
        v-else
        :kind="entry.kind"
        :icon="entry.icon"
        :shortcut="entry.shortcut"
        :hint="entry.hint"
        :danger="entry.danger"
        :disabled="entry.disabled"
        :checked="entry.checked"
        :to="entry.to"
        :href="entry.href"
        :target="entry.target"
        :close-on-select="entry.closeOnSelect"
        @select="entry.onSelect?.($event)"
      >
        {{ entry.label }}
      </VMenuItem>
    </template>
    <slot />
  </VPopover>
</template>
