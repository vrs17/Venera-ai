<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Component } from 'vue'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import VSpinner from './VSpinner.vue'
import VTooltip from './VTooltip.vue'
import type { Placement } from './composables/useFloating'

/**
 * Faqat belgidan iborat tugma. `label` MAJBURIY: u ham aria-label, ham tooltip matni
 * (spec §2: har bir belgili boshqaruvda ikkalasi bir xil).
 *
 * O'chiq holat `disabled` atributi bilan EMAS, `aria-disabled` bilan: o'chiq tugmada
 * brauzer sichqoncha hodisalarini yubormaydi, demak tooltip ham chiqmaydi - "Xabar
 * berish" nega o'chiqligini foydalanuvchi bilolmay qoladi.
 *
 * `active` - vizual tanlangan holat (--fill fon); `pressed` berilsa u toggle tugma
 * sifatida `aria-pressed` ham oladi.
 *
 * Tugma komponentning ILDIZI (tooltip unga `target` orqali ulanadi, o'rab olmaydi):
 * chaqiruvchining `class` va scoped uslublari to'g'ridan-to'g'ri tugmaga tushadi.
 */

const props = withDefaults(
  defineProps<{
    label: string
    icon?: Component
    size?: 'sm' | 'md' | 'lg'
    variant?: 'ghost' | 'secondary' | 'outline' | 'primary'
    active?: boolean
    pressed?: boolean
    disabled?: boolean
    loading?: boolean
    /** Kichik brend nuqtasi ("yangi"). */
    dot?: boolean
    shortcut?: string | string[]
    tooltip?: boolean
    tooltipPlacement?: Placement
    type?: 'button' | 'submit' | 'reset'
    to?: RouteLocationRaw
    href?: string
    target?: string
  }>(),
  { size: 'md', variant: 'ghost', type: 'button', tooltip: true, tooltipPlacement: 'top', pressed: undefined },
)

const emit = defineEmits<{ click: [e: MouseEvent] }>()

// `component :is` RouterLink bo'lsa ref komponent instansiyasini beradi - elementini olamiz.
const el = ref<HTMLElement | null>(null)
function setEl(r: unknown) {
  if (r instanceof HTMLElement) el.value = r
  else {
    const inner = (r as { $el?: unknown } | null)?.$el
    el.value = inner instanceof HTMLElement ? inner : null
  }
}

const iconSize = computed(() => ({ sm: 16, md: 18, lg: 20 })[props.size])
const blocked = computed(() => props.disabled || props.loading)
const isOn = computed(() => props.active || props.pressed === true)

const tag = computed(() => {
  if (props.to && !props.disabled) return RouterLink
  if (props.href && !props.disabled) return 'a'
  return 'button'
})

const linkAttrs = computed(() => {
  if (tag.value === 'button') return { type: props.type }
  const rel = props.target === '_blank' ? 'noopener noreferrer' : undefined
  return props.to ? { to: props.to, target: props.target, rel } : { href: props.href, target: props.target, rel }
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
    :ref="setEl"
    v-bind="linkAttrs"
    class="v-icon-btn"
    :class="[`v-icon-btn--${size}`, `v-icon-btn--${variant}`, { 'is-active': isOn, 'is-loading': loading }]"
    :aria-label="label"
    :aria-pressed="pressed === undefined ? undefined : pressed ? 'true' : 'false'"
    :aria-disabled="blocked ? 'true' : undefined"
    :aria-busy="loading ? 'true' : undefined"
    @click="onClick"
  >
    <VSpinner v-if="loading" :size="iconSize - 2" />
    <slot v-else><component :is="icon" :size="iconSize" :stroke-width="1.75" aria-hidden="true" /></slot>
    <span v-if="dot" class="v-icon-btn__dot" aria-hidden="true" />
    <VTooltip
      :target="el"
      :text="label"
      :shortcut="shortcut"
      :placement="tooltipPlacement"
      :disabled="!tooltip"
      :describe="false"
    />
  </component>
</template>

<style scoped>
.v-icon-btn {
  --ib-size: 36px;
  position: relative;
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--ib-size);
  height: var(--ib-size);
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  touch-action: manipulation;
  -webkit-user-select: none;
  user-select: none;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
/* Burchak VButton bilan bir xil o'lchamda bir xil: 32 - r-sm, 36/40 - r-md. Yonma-yon
   turgan tugma va belgili tugma "bir oiladan" ko'rinsin. */
.v-icon-btn--sm { --ib-size: 32px; }
.v-icon-btn--md {
  --ib-size: 36px;
  border-radius: var(--r-md);
}
.v-icon-btn--lg {
  --ib-size: 40px;
  border-radius: var(--r-md);
}
/* Sensorli ekranda bosish maydoni kamida 40px - ko'rinish va tartib o'zgarmaydi. */
@media (pointer: coarse) {
  .v-icon-btn--sm::after,
  .v-icon-btn--md::after {
    content: '';
    position: absolute;
    inset: calc((40px - var(--ib-size)) / -2);
  }
}

.v-icon-btn--secondary {
  background: var(--fill);
  color: var(--text);
}
.v-icon-btn--outline {
  border-color: var(--line-strong);
  color: var(--text);
}
.v-icon-btn--primary {
  background: var(--ink);
  color: var(--on-ink);
}

@media (hover: hover) {
  .v-icon-btn:not([aria-disabled='true']):hover {
    background: var(--fill);
    color: var(--text);
  }
  .v-icon-btn--secondary:not([aria-disabled='true']):hover,
  .v-icon-btn--outline:not([aria-disabled='true']):hover {
    background: var(--fill-hover);
  }
  .v-icon-btn--primary:not([aria-disabled='true']):hover {
    background: var(--ink-hover);
    color: var(--on-ink);
  }
}
.v-icon-btn:not([aria-disabled='true']):active {
  transform: scale(0.94);
}

.v-icon-btn.is-active {
  background: var(--fill);
  color: var(--text);
}
@media (hover: hover) {
  .v-icon-btn.is-active:not([aria-disabled='true']):hover {
    background: var(--fill-hover);
  }
}

.v-icon-btn[aria-disabled='true']:not(.is-loading) {
  cursor: default;
  color: var(--text-4);
}
.v-icon-btn--primary[aria-disabled='true']:not(.is-loading) {
  background: var(--fill);
}
.v-icon-btn.is-loading {
  cursor: progress;
}

.v-icon-btn__dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 7px;
  height: 7px;
  border-radius: var(--r-full);
  background: var(--brand);
  /* Belgi ustida "kesilgan" ko'rinish - fon bilan halqa. Tugma kartada yoki yon
     panelda tursa, ota `--icon-btn-ring: var(--surface)` / `var(--bg-subtle)` beradi. */
  box-shadow: 0 0 0 2px var(--icon-btn-ring, var(--bg));
}
</style>
