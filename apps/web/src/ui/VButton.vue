<script setup lang="ts">
import { computed, useSlots } from 'vue'
import type { Component } from 'vue'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import VSpinner from './VSpinner.vue'

/**
 * Tugma. Variantlar (spec §3):
 *   primary   - siyoh fon (bitta ekranda bittadan ko'p bo'lmasin);
 *   secondary - --fill fon (standart);
 *   ghost     - shaffof, hover'da --fill;
 *   outline   - soch tolasi chegara;
 *   danger    - qizil matn yumshoq qizil fonda (qizil TO'LIQ fon hech qachon).
 *
 * `loading`: spinner chap belgi o'rnini egallaydi; belgi bo'lmasa - markazda paydo
 * bo'ladi, matn esa `visibility: hidden` bilan joyida qoladi - tugma kengligi
 * sakramaydi. Yuklanish paytida `disabled` atributi QO'YILMAYDI (fokus yo'qolmasin),
 * o'rniga `aria-disabled` va bosish bloklanadi.
 *
 * `to` → RouterLink, `href` → <a>, aks holda <button>.
 */
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    type?: 'button' | 'submit' | 'reset'
    loading?: boolean
    disabled?: boolean
    block?: boolean
    /** To'liq yumaloq (auth sahifasidagi katta asosiy tugma). */
    pill?: boolean
    icon?: Component
    iconEnd?: Component
    to?: RouteLocationRaw
    href?: string
    target?: string
    rel?: string
  }>(),
  { variant: 'secondary', size: 'md', type: 'button' },
)

const emit = defineEmits<{ click: [e: MouseEvent] }>()
const slots = useSlots()

const isLink = computed(() => !!props.to || !!props.href)
const tag = computed(() => {
  if (props.disabled && isLink.value) return 'a'
  if (props.to) return RouterLink
  if (props.href) return 'a'
  return 'button'
})
const hasLeading = computed(() => !!props.icon || !!slots.icon)
const hasTrailing = computed(() => !!props.iconEnd || !!slots.iconEnd)
const iconSize = computed(() => (props.size === 'lg' ? 18 : 16))
const blocked = computed(() => props.disabled || props.loading)

const attrs = computed(() => {
  if (!isLink.value) {
    return {
      type: props.type,
      disabled: props.disabled || undefined,
      'aria-disabled': props.loading ? 'true' : undefined,
    }
  }
  if (props.disabled) {
    // O'chiq havola: href yo'q, Tab bilan ham yetib bo'lmaydi.
    return { role: 'link', 'aria-disabled': 'true', tabindex: -1 }
  }
  const rel = props.rel ?? (props.target === '_blank' ? 'noopener noreferrer' : undefined)
  return props.to
    ? { to: props.to, target: props.target, rel }
    : { href: props.href, target: props.target, rel, 'aria-disabled': props.loading ? 'true' : undefined }
})

function onClick(e: MouseEvent) {
  if (blocked.value) {
    e.preventDefault()
    e.stopPropagation()
    return
  }
  emit('click', e)
}
</script>

<template>
  <component
    :is="tag"
    class="v-btn"
    :class="[
      `v-btn--${variant}`,
      `v-btn--${size}`,
      {
        'v-btn--block': block,
        'v-btn--pill': pill,
        'v-btn--loading': loading,
        'v-btn--lead': hasLeading,
        'v-btn--trail': hasTrailing,
        'v-btn--overlay': loading && !hasLeading,
      },
    ]"
    v-bind="attrs"
    :aria-busy="loading ? 'true' : undefined"
    @click="onClick"
  >
    <span v-if="hasLeading" class="v-btn__icon" aria-hidden="true">
      <VSpinner v-if="loading" :size="iconSize" />
      <slot v-else name="icon"><component :is="icon" :size="iconSize" :stroke-width="1.75" /></slot>
    </span>
    <span class="v-btn__label"><slot /></span>
    <span v-if="hasTrailing" class="v-btn__icon v-btn__icon--end" aria-hidden="true">
      <slot name="iconEnd"><component :is="iconEnd" :size="iconSize" :stroke-width="1.75" /></slot>
    </span>
    <span v-if="loading && !hasLeading" class="v-btn__spinner" aria-hidden="true">
      <VSpinner :size="iconSize" />
    </span>
  </component>
</template>

<style scoped>
.v-btn {
  --btn-h: 36px;
  --btn-px: 14px;
  --btn-bg: var(--fill);
  --btn-bg-hover: var(--fill-hover);
  --btn-fg: var(--text);
  --btn-border: transparent;
  --btn-border-hover: var(--btn-border);

  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-1_5);
  height: var(--btn-h);
  min-width: 0;
  padding: 0 var(--btn-px);
  border: 1px solid var(--btn-border);
  border-radius: var(--r-md);
  background: var(--btn-bg);
  color: var(--btn-fg);
  font-family: var(--font-sans);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  letter-spacing: -0.006em;
  white-space: nowrap;
  text-decoration: none;
  vertical-align: middle;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  touch-action: manipulation;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out),
    opacity var(--dur-1) var(--ease-out);
}

/* --- o'lchamlar --- */
.v-btn--sm {
  --btn-h: 32px;
  --btn-px: 12px;
  font-size: 13px;
  border-radius: var(--r-sm);
}
.v-btn--md {
  --btn-h: 36px;
  --btn-px: 14px;
}
.v-btn--lg {
  --btn-h: 44px;
  --btn-px: 20px;
  gap: var(--s-2);
  font-size: var(--fs-body);
}
/* Belgili tomonda optik jihatdan kamroq bo'shliq - matn markazda "turgandek" ko'rinadi. */
.v-btn--lead { padding-left: calc(var(--btn-px) - 2px); }
.v-btn--trail { padding-right: calc(var(--btn-px) - 2px); }
.v-btn--pill { border-radius: var(--r-full); }
/* Sensorli ekranda kichik tugmaning bosish maydoni ko'rinmas holda kattalashadi
   (tartib o'zgarmaydi). */
@media (pointer: coarse) {
  .v-btn--sm::after {
    content: '';
    position: absolute;
    inset: -4px -2px;
  }
}
.v-btn--block {
  display: flex;
  width: 100%;
}

/* --- variantlar --- */
.v-btn--primary {
  --btn-bg: var(--ink);
  --btn-bg-hover: var(--ink-hover);
  --btn-fg: var(--on-ink);
}
.v-btn--secondary {
  --btn-bg: var(--fill);
  --btn-bg-hover: var(--fill-hover);
  --btn-fg: var(--text);
}
.v-btn--ghost {
  --btn-bg: transparent;
  --btn-bg-hover: var(--fill);
  --btn-fg: var(--text);
}
.v-btn--outline {
  --btn-bg: transparent;
  --btn-bg-hover: var(--fill);
  --btn-fg: var(--text);
  --btn-border: var(--line-strong);
  --btn-border-hover: var(--line-strong);
}
.v-btn--danger {
  --btn-bg: var(--crit-soft);
  --btn-bg-hover: color-mix(in srgb, var(--crit) 16%, var(--crit-soft));
  --btn-fg: var(--crit-text);
}

@media (hover: hover) {
  .v-btn:not(:disabled):not([aria-disabled='true']):hover {
    background: var(--btn-bg-hover);
    border-color: var(--btn-border-hover);
  }
}
/* Bosilganda sezilar-sezilmas "cho'kish" - taktil javob. */
.v-btn:not(:disabled):not([aria-disabled='true']):active {
  transform: scale(0.98);
}

/* --- o'chiq --- */
.v-btn:disabled,
.v-btn[aria-disabled='true']:not(.v-btn--loading) {
  cursor: default;
  color: var(--text-4);
}
.v-btn--primary:disabled,
.v-btn--secondary:disabled,
.v-btn--danger:disabled,
.v-btn--primary[aria-disabled='true']:not(.v-btn--loading),
.v-btn--danger[aria-disabled='true']:not(.v-btn--loading) {
  background: var(--fill);
}
.v-btn--outline:disabled {
  border-color: var(--line);
}
.v-btn--loading {
  cursor: progress;
}

/* --- ichki qismlar --- */
.v-btn__icon {
  display: inline-flex;
  flex-shrink: 0;
}
.v-btn__label {
  display: inline-block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.v-btn__label:empty {
  display: none;
}
.v-btn--overlay .v-btn__label,
.v-btn--overlay .v-btn__icon--end {
  visibility: hidden;
}
.v-btn__spinner {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
}
</style>
