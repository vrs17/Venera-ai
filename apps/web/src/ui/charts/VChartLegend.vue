<script setup lang="ts">
import { cssColor, type LegendItem } from './scale'

/**
 * Grafik afsonasi (legend). Ikki va undan ko'p qatorda DOIM bor - rangga tayanib
 * qolmaslik uchun ishonchli nom kanali. Belgi grafikdagi shaklni takrorlaydi:
 * maydon/ustun - kvadratcha, chiziq - chiziqcha, mo'ljal - uzuq chiziq.
 *
 * `toggleable` - bosilganda qator yashiriladi (rang o'zgarmaydi: rang ob'ektga
 * bog'langan). Sichqoncha ustiga kelganda `highlight` - grafik boshqalarini xiralashtiradi.
 * Matn hech qachon qator rangida emas - faqat matn tokenlari.
 */
withDefaults(
  defineProps<{
    items: LegendItem[]
    toggleable?: boolean
    /** inline - bir qatorda oqadi; list - ustun, qiymat va ulush o'ngda. */
    layout?: 'inline' | 'list'
  }>(),
  { layout: 'inline' },
)

const emit = defineEmits<{
  toggle: [key: string]
  highlight: [key: string | null]
}>()
</script>

<template>
  <ul class="vcl" :class="`is-${layout}`" role="list">
    <li
      v-for="it in items"
      :key="it.key"
      class="vcl-item"
      :class="{ 'is-hidden': it.hidden }"
      @pointerenter="emit('highlight', it.key)"
      @pointerleave="emit('highlight', null)"
    >
      <component
        :is="toggleable ? 'button' : 'span'"
        class="vcl-key"
        :type="toggleable ? 'button' : undefined"
        :aria-pressed="toggleable ? !it.hidden : undefined"
        @click="toggleable && emit('toggle', it.key)"
        @focus="emit('highlight', it.key)"
        @blur="emit('highlight', null)"
      >
        <span class="vcl-mark" :class="`is-${it.mark ?? 'rect'}`" :style="{ '--c': cssColor(it.color) }" aria-hidden="true" />
        <span class="vcl-label">{{ it.label }}</span>
      </component>
      <span v-if="it.value !== undefined" class="vcl-value">{{ it.value }}</span>
      <span v-if="it.share !== undefined" class="vcl-share">{{ it.share }}</span>
    </li>
  </ul>
</template>

<style scoped>
.vcl {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.vcl.is-inline {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-1_5) var(--s-4);
  min-width: 0;
}
.vcl.is-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  column-gap: var(--s-4);
}

.vcl-item {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  transition: opacity var(--dur-1) var(--ease-out);
}
.is-list .vcl-item {
  display: grid;
  grid-template-columns: subgrid;
  grid-column: 1 / -1;
  align-items: center;
  min-height: 32px;
  border-top: 1px solid var(--line);
}
.is-list .vcl-item:first-child {
  border-top: 0;
}

.vcl-key {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  color: var(--text-2);
  font: inherit;
  text-align: start;
}
button.vcl-key {
  margin: calc(var(--s-1) * -1) calc(var(--s-1_5) * -1);
  padding: var(--s-1) var(--s-1_5);
  border-radius: var(--r-xs);
  transition: background-color var(--dur-1) var(--ease-out), color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  button.vcl-key:hover {
    background: var(--fill);
    color: var(--text);
  }
}
.is-list .vcl-key {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 400;
}

.vcl-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vcl-value {
  justify-self: end;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.is-list .vcl-value {
  font-size: var(--fs-body-sm);
  font-weight: 500;
}
.vcl-share {
  justify-self: end;
  min-width: 3.5em;
  text-align: end;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.is-inline .vcl-value,
.is-inline .vcl-share {
  margin-inline-start: -2px;
}

.vcl-mark {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--c);
  transition: background-color var(--dur-1) var(--ease-out), box-shadow var(--dur-1) var(--ease-out);
}
.vcl-mark.is-line {
  width: 12px;
  height: 2px;
  border-radius: 1px;
}
.vcl-mark.is-dashed {
  width: 12px;
  height: 0;
  border-radius: 0;
  background: none;
  border-top: 2px dashed var(--c);
}
.vcl-mark.is-dot {
  border-radius: 50%;
}

/* Yashirilgan qator: bo'sh belgi + xira nom - "o'chiq" holat rangsiz ham o'qiladi. */
.is-hidden .vcl-key {
  color: var(--text-4);
}
.is-hidden .vcl-mark {
  background: transparent;
  box-shadow: inset 0 0 0 1.5px var(--c);
}
.is-hidden .vcl-mark.is-line,
.is-hidden .vcl-mark.is-dashed {
  background: var(--c);
  box-shadow: none;
  opacity: 0.35;
}
.is-hidden .vcl-mark.is-dashed {
  background: none;
}
</style>
