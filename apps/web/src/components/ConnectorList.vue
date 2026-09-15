<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { FunctionalComponent } from 'vue'
import { useConnectors } from '../composables/useConnectors'
import type { ConnectorId, ConnectorStatus } from '../composables/useConnectors'
import { BoardIcon, PlusIcon, UsersIcon } from '../icons'

// HRM / CRM qatorlari. Ulanmagan yoki muddati tugagan qatorda "+" (ulanish
// oynasini ochadi), ulanganida kalit (chatda ishlatish / ishlatmaslik).
// Ikki joyda chiqadi - desktopda yon panelda, mobilda "Ulanishlar" qatori
// ostida - shuning uchun alohida komponent. Oynani ochish ota komponentning
// ishi (`open`).
const emit = defineEmits<{ open: [id: ConnectorId] }>()
const { t } = useI18n({ useScope: 'global' })
const { connectors, loadFailed, toggle } = useConnectors()

const ICONS: Record<ConnectorId, FunctionalComponent<{ size?: number }>> = { hrm: UsersIcon, crm: BoardIcon }
const HINTS = { hrm: 'connectorHrmHint', crm: 'connectorCrmHint' } as const

function hint(c: ConnectorStatus): string {
  if (!c.configured) return t('connectorUnavailable')
  if (c.state === 'connected') return c.login || t('connected')
  if (c.state === 'expired') return t('connectorExpired')
  return t(HINTS[c.id])
}
function title(c: ConnectorStatus): string {
  if (c.state === 'connected') return t('connectedAs', { login: c.login ?? '' })
  if (c.state === 'expired') return t('reconnect')
  return t('connectTo', { name: c.label })
}
</script>

<template>
  <div class="clist" role="group" :aria-label="t('connectors')">
    <div
      v-for="c in connectors"
      :key="c.id"
      class="clist__row"
      :class="{ 'is-on': c.state === 'connected' && c.enabled, 'is-unavailable': !c.configured }"
    >
      <!-- Nom + izoh: bosilsa ulanish (ulangan bo'lsa - hisob) oynasi ochiladi. -->
      <button type="button" class="clist__main" :title="title(c)" :disabled="!c.configured" @click="emit('open', c.id)">
        <span class="clist__icon"><component :is="ICONS[c.id]" :size="16" /></span>
        <span class="clist__text">
          <span class="clist__name">{{ c.label }}</span>
          <span class="clist__hint">
            <span v-if="c.configured && c.state !== 'disconnected'" class="clist__dot" :class="`is-${c.state}`" aria-hidden="true" />
            {{ hint(c) }}
          </span>
        </span>
      </button>

      <!-- Ulangan: kalit. Aks holda "+" - ulanish yoki qayta ulanish. -->
      <button
        v-if="c.state === 'connected'"
        type="button"
        class="clist__switch"
        role="switch"
        :aria-checked="c.enabled"
        :aria-label="c.label"
        @click="toggle(c.id)"
      >
        <span class="clist__knob" aria-hidden="true" />
      </button>
      <button
        v-else
        type="button"
        class="clist__connect"
        :title="c.state === 'expired' ? t('reconnect') : t('connect')"
        :aria-label="title(c)"
        :disabled="!c.configured"
        @click="emit('open', c.id)"
      >
        <PlusIcon :size="14" />
      </button>
    </div>
    <p v-if="loadFailed" class="clist__note" role="status">{{ t('connectorsLoadFailed') }}</p>
  </div>
</template>

<style scoped>
.clist {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.clist__row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-right: 10px;
  border-radius: 10px;
  color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
}
.clist__row:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.clist__row.is-on {
  color: var(--text);
}
.clist__row.is-unavailable {
  opacity: 0.55;
}
.clist__row.is-unavailable:hover {
  background: transparent;
  color: var(--text-secondary);
}
.clist__main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: inherit;
  font-family: 'Figtree', sans-serif;
  text-align: left;
  cursor: pointer;
}
.clist__main:disabled {
  cursor: not-allowed;
}
.clist__icon {
  display: inline-flex;
  flex-shrink: 0;
}
.clist__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.25;
}
.clist__name {
  font-size: 13.5px;
  font-weight: 600;
}
.clist__hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}
/* Yashil - ulangan, sariq - muddati tugagan (qayta kirish kerak). */
.clist__dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok-fg);
}
.clist__dot.is-expired {
  background: var(--warn-fg);
}
/* "+" - ulanish. Kalit bilan bir xil balandlikda, qator sakramasin. */
.clist__connect {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--border-hover);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.clist__connect:hover:not(:disabled) {
  background: var(--ink);
  border-color: transparent;
  color: var(--ink-contrast);
}
.clist__connect:disabled {
  cursor: not-allowed;
}
/* Yon paneldagi kalit bilan bir xil o'lcham va ranglar - ilova bitta tilda
   gaplashsin. Tugma, chunki o'zi bosiladi (nom alohida tugma). */
.clist__switch {
  flex-shrink: 0;
  box-sizing: content-box;
  width: 34px;
  height: 19px;
  padding: 0;
  border-radius: 999px;
  background: var(--surface-hover);
  border: 1px solid var(--border-hover);
  position: relative;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}
.clist__row.is-on .clist__switch {
  background: var(--ink);
  border-color: transparent;
}
.clist__knob {
  position: absolute;
  top: 1.5px;
  left: 1.5px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  transition: transform 0.22s var(--spring);
}
.clist__row.is-on .clist__knob {
  transform: translateX(15px);
}
.clist__note {
  margin: 4px 10px 2px;
  font-size: 11.5px;
  color: var(--warn-fg);
}
</style>
