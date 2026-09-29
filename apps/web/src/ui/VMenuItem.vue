<script lang="ts">
import type { InjectionKey } from 'vue'

// Kalit shu faylda (VMenu'da emas): VMenu bu faylni import qiladi - aylanma import bo'lmasin.
export interface MenuContext {
  /** Menyuni yopish; standart holatda fokus trigger'ga qaytadi. */
  close: (restoreFocus?: boolean) => void
  /** Sichqoncha qatordan chiqdi - ta'kidni olib tashlash (fokus panelga). */
  clearHighlight: () => void
}
export const MENU_KEY: InjectionKey<MenuContext> = Symbol('v-menu')
</script>

<script setup lang="ts">
import { computed, inject } from 'vue'
import type { Component } from 'vue'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import { Check } from 'lucide-vue-next'
import VKbd from './VKbd.vue'

/**
 * Menyu bandi. `kind`:
 *   item (standart) | checkbox | radio - bosiladigan qatorlar;
 *   separator - soch tolasi; label - bo'lim sarlavhasi (kulrang, kichik).
 *
 * `select` hodisasi bekor qilinadigan CustomEvent: `e.preventDefault()` chaqirilsa menyu
 * ochiq qoladi. (Native click'ning defaultPrevented'iga tayanmaymiz - RouterLink uni
 * har doim bekor qiladi.) Checkbox bandlar standart holatda menyuni yopmaydi - filtrda
 * bir nechtasini ketma-ket belgilash qulay.
 */
const props = withDefaults(
  defineProps<{
    kind?: 'item' | 'checkbox' | 'radio' | 'separator' | 'label'
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
    /** Harf bilan qidirish uchun matn (yorliq murakkab bo'lsa). */
    textValue?: string
  }>(),
  { kind: 'item', closeOnSelect: undefined },
)

const emit = defineEmits<{ select: [e: Event] }>()
const menu = inject(MENU_KEY, null)

const isRow = computed(() => props.kind === 'item' || props.kind === 'checkbox' || props.kind === 'radio')
const role = computed(() =>
  props.kind === 'checkbox' ? 'menuitemcheckbox' : props.kind === 'radio' ? 'menuitemradio' : 'menuitem',
)
const tag = computed(() => {
  if (props.disabled) return 'div'
  if (props.to) return RouterLink
  if (props.href) return 'a'
  return 'div'
})
const linkAttrs = computed(() => {
  if (props.disabled) return {}
  const rel = props.target === '_blank' ? 'noopener noreferrer' : undefined
  if (props.to) return { to: props.to, target: props.target, rel }
  if (props.href) return { href: props.href, target: props.target, rel }
  return {}
})

function onClick(e: MouseEvent) {
  if (props.disabled) {
    e.preventDefault()
    return
  }
  const ev = new CustomEvent('select', { cancelable: true })
  emit('select', ev)
  const shouldClose = props.closeOnSelect ?? props.kind !== 'checkbox'
  if (!ev.defaultPrevented && shouldClose) menu?.close(true)
}

function onPointerMove(e: PointerEvent) {
  if (e.pointerType === 'touch' || props.disabled) return
  const el = e.currentTarget as HTMLElement
  if (document.activeElement !== el) el.focus({ preventScroll: true })
}

function onPointerLeave(e: PointerEvent) {
  if (e.pointerType === 'touch') return
  if (document.activeElement === e.currentTarget) menu?.clearHighlight()
}
</script>

<template>
  <div v-if="kind === 'separator'" class="v-menu-sep" role="separator" />
  <div v-else-if="kind === 'label'" class="v-menu-label" role="presentation"><slot /></div>
  <component
    :is="tag"
    v-else-if="isRow"
    v-bind="linkAttrs"
    class="v-menu-item"
    :class="{ 'is-danger': danger, 'is-disabled': disabled }"
    :role="role"
    :aria-checked="kind === 'item' ? undefined : checked ? 'true' : 'false'"
    :aria-disabled="disabled ? 'true' : undefined"
    :data-text-value="textValue"
    data-v-menu-item
    tabindex="-1"
    @click="onClick"
    @pointermove="onPointerMove"
    @pointerleave="onPointerLeave"
  >
    <span v-if="icon || $slots.icon" class="v-menu-item__icon" aria-hidden="true">
      <slot name="icon"><component :is="icon" :size="16" :stroke-width="1.75" /></slot>
    </span>
    <span class="v-menu-item__label"><slot /></span>
    <span v-if="hint" class="v-menu-item__hint">{{ hint }}</span>
    <VKbd v-if="shortcut" :keys="shortcut" size="sm" class="v-menu-item__kbd" />
    <span v-if="kind !== 'item'" class="v-menu-item__check" aria-hidden="true">
      <Check v-if="checked" :size="16" :stroke-width="2" />
    </span>
  </component>
</template>

<style scoped>
.v-menu-item {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-height: 32px;
  padding: 0 var(--s-2);
  border-radius: var(--r-xs);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-decoration: none;
  cursor: pointer;
  outline: none;
  user-select: none;
  -webkit-user-select: none;
  scroll-margin: var(--s-1_5);
}
/* Ta'kid = fokus (u sichqonchaga ergashadi) - ikki xil ta'kid bir vaqtda bo'lmaydi. */
.v-menu-item:focus,
.v-menu-item:focus-visible {
  background: var(--fill);
  outline: none;
}
.v-menu-item:active:not(.is-disabled) {
  background: var(--fill-hover);
}
/* Barmoq uchun kattaroq qator. */
@media (pointer: coarse) {
  .v-menu-item {
    min-height: 40px;
  }
}
.v-menu-item.is-danger {
  color: var(--crit-text);
}
.v-menu-item.is-danger:focus {
  background: var(--crit-soft);
}
.v-menu-item.is-disabled {
  color: var(--text-4);
  cursor: default;
}
.v-menu-item.is-disabled:focus {
  background: transparent;
}

.v-menu-item__icon {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--text-2);
}
.v-menu-item:focus .v-menu-item__icon {
  color: var(--text);
}
.is-danger .v-menu-item__icon,
.is-danger:focus .v-menu-item__icon {
  color: inherit;
}
.is-disabled .v-menu-item__icon {
  color: inherit;
}
.v-menu-item__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.v-menu-item__hint {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
}
.v-menu-item__kbd {
  margin-left: var(--s-2);
}
.v-menu-item__check {
  display: inline-flex;
  flex-shrink: 0;
  width: 16px;
  margin-left: var(--s-1);
  color: var(--text);
}

.v-menu-sep {
  height: 1px;
  margin: var(--s-1_5) calc(var(--s-1_5) * -1);
  background: var(--line);
}
.v-menu-label {
  padding: var(--s-2) var(--s-2) var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  user-select: none;
}
.v-menu-label:first-child {
  padding-top: var(--s-1);
}
</style>
