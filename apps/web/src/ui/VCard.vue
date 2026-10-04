<script setup lang="ts">
import { computed, useSlots } from 'vue'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'

/**
 * Karta: sirt + soch tolasi + katta burchak. Sarlavha (ixtiyoriy) - title-3.
 *
 * `to` / `href` berilsa - butun karta havola bo'ladi va avtomatik `interactive`
 * (hover'da e1 soya va biroz to'qroq chegara).
 */
const props = withDefaults(
  defineProps<{
    title?: string
    description?: string
    /** Sarlavha darajasi - sahifa tuzilishiga mos (standart h3). */
    headingLevel?: 2 | 3 | 4
    padding?: 'none' | 'sm' | 'md' | 'lg'
    interactive?: boolean
    to?: RouteLocationRaw
    href?: string
    as?: string
  }>(),
  { padding: 'md', as: 'div', headingLevel: 3 },
)

const slots = useSlots()
const tag = computed(() => (props.to ? RouterLink : props.href ? 'a' : props.as))
const linkAttrs = computed(() => (props.to ? { to: props.to } : props.href ? { href: props.href } : {}))
const isInteractive = computed(() => props.interactive || !!props.to || !!props.href)
const hasHeader = computed(() => !!props.title || !!props.description || !!slots.header || !!slots.actions)
</script>

<template>
  <component
    :is="tag"
    class="v-card"
    :class="[`v-card--${padding}`, { 'v-card--interactive': isInteractive }]"
    v-bind="linkAttrs"
  >
    <header v-if="hasHeader" class="v-card__head">
      <slot name="header">
        <div class="v-card__titles">
          <component :is="`h${headingLevel}`" v-if="title" class="v-card__title">{{ title }}</component>
          <p v-if="description" class="v-card__desc">{{ description }}</p>
        </div>
      </slot>
      <div v-if="$slots.actions" class="v-card__actions"><slot name="actions" /></div>
    </header>
    <slot />
    <footer v-if="$slots.footer" class="v-card__foot"><slot name="footer" /></footer>
  </component>
</template>

<style scoped>
.v-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  color: inherit;
  text-align: left;
  transition:
    box-shadow var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.v-card--none { padding: 0; }
.v-card--sm { padding: var(--s-4); }
.v-card--md { padding: var(--s-5); }
.v-card--lg { padding: var(--s-6); }
@media (max-width: 767.98px) {
  .v-card--lg { padding: var(--s-5); }
}

.v-card--interactive {
  cursor: pointer;
}
@media (hover: hover) {
  .v-card--interactive:hover {
    border-color: var(--line-strong);
    box-shadow: var(--e1);
  }
}
.v-card--interactive:active {
  transform: scale(0.995);
}
.v-card:focus-visible {
  border-radius: var(--r-lg);
}

.v-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  margin-bottom: var(--s-4);
}
.v-card--none > .v-card__head {
  padding: var(--s-5) var(--s-5) 0;
}
.v-card__titles {
  min-width: 0;
}
.v-card__title {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.v-card__desc {
  margin-top: 2px;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.v-card__actions {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  flex-shrink: 0;
  margin: -4px -6px -4px 0;
}
.v-card__foot {
  margin-top: var(--s-4);
  padding-top: var(--s-4);
  border-top: 1px solid var(--line);
}
</style>
