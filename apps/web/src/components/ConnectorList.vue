<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { Settings, Users } from 'lucide-vue-next'
import { useConnectors } from '../composables/useConnectors'
import type { ConnectorId, ConnectorStatus } from '../composables/useConnectors'
import VBadge from '../ui/VBadge.vue'
import VButton from '../ui/VButton.vue'
import VIconButton from '../ui/VIconButton.vue'
import VSkeleton from '../ui/VSkeleton.vue'

// Ulanish qatori (ulanishlar oynasining ichida; hozir bitta - HRM). Qator = platforma
// belgisi, nomi, bitta jim holat qatori va boshqaruv: ulanmagan yoki muddati tugagan
// bo'lsa - "Ulanish" / "Qayta ulanish"; ulangan yoki muddati tugagan bo'lsa - tishli
// g'ildirak (hisob: sessiya muddati, uzish). Qaysi ko'rinish ochilishi ota komponentning
// ishi: `connect` - kirish shakli, `manage` - hisob.
//
// KALIT YO'Q (ega qarori, 2026-11-12): ulangan tizim ishlatiladi.
const emit = defineEmits<{ connect: [id: ConnectorId]; manage: [id: ConnectorId] }>()
const { t } = useI18n({ useScope: 'global' })
const { connectors, loading, loaded, loadFailed } = useConnectors()

const ICONS: Record<ConnectorId, Component> = { hrm: Users }
const HINTS: Record<ConnectorId, string> = { hrm: 'connectorHrmHint' }

function statusText(c: ConnectorStatus): string {
  if (!c.configured) return t('connectorUnavailable')
  if (c.state === 'connected') return c.login || t('connected')
  if (c.state === 'expired') return t('connectorExpired')
  // Ulanmagan: holat emas, tizim nima berishini aytamiz - "nega ulanay?" savoliga javob.
  return t(HINTS[c.id])
}
function connectLabel(c: ConnectorStatus): string {
  return c.state === 'expired' ? t('reconnect') : t('connectTo', { name: c.label })
}
</script>

<template>
  <div class="clist">
    <ul class="clist__rows" :aria-label="t('connectors')">
      <li
        v-for="c in connectors"
        :key="c.id"
        class="clist__row"
        :class="{ 'is-unavailable': !c.configured }"
        :data-connector="c.id"
      >
        <span class="clist__glyph" aria-hidden="true">
          <component :is="ICONS[c.id]" :size="18" :stroke-width="1.75" />
        </span>
        <span class="clist__text">
          <span class="clist__name">{{ c.label }}</span>
          <VBadge
            v-if="c.configured && c.state !== 'disconnected'"
            class="clist__status"
            dot
            size="sm"
            :tone="c.state === 'connected' ? 'good' : 'warn'"
          >
            <span class="clist__status-text">{{ statusText(c) }}</span>
          </VBadge>
          <span v-else class="clist__hint">{{ statusText(c) }}</span>
        </span>

        <!-- Birinchi yuklash tugaguncha boshqaruv o'rnida jim o'rinbosar: ulangan
             odamga bir lahzaga "Ulanish" tugmasi ko'rinib qolmasin. -->
        <span v-if="!loaded && loading" class="clist__controls" aria-hidden="true">
          <VSkeleton :width="64" :height="28" radius="sm" />
        </span>
        <span v-else-if="c.configured" class="clist__controls">
          <VIconButton
            v-if="c.state !== 'disconnected'"
            data-role="manage"
            :label="`${c.label}: ${t('connectorSettings')}`"
            :icon="Settings"
            size="sm"
            @click="emit('manage', c.id)"
          />
          <VButton
            v-if="c.state !== 'connected'"
            data-role="connect"
            size="sm"
            :variant="c.state === 'expired' ? 'primary' : 'secondary'"
            :aria-label="connectLabel(c)"
            @click="emit('connect', c.id)"
          >
            {{ c.state === 'expired' ? t('reconnect') : t('connect') }}
          </VButton>
        </span>
      </li>
    </ul>
    <p v-if="loadFailed" class="clist__note" role="status">{{ t('connectorsLoadFailed') }}</p>
  </div>
</template>

<style scoped>
.clist__rows {
  margin: 0;
  padding: 0;
  list-style: none;
}
.clist__row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-height: 64px;
  padding: var(--s-3) 0;
}
.clist__row + .clist__row {
  border-top: 1px solid var(--line);
}

.clist__glyph {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}

.clist__text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.clist__name {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.clist__hint {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.clist__status {
  max-width: 100%;
}
.clist__status-text {
  overflow: hidden;
  text-overflow: ellipsis;
}

.clist__controls {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  flex-shrink: 0;
}

.clist__row.is-unavailable .clist__glyph,
.clist__row.is-unavailable .clist__name,
.clist__row.is-unavailable .clist__hint {
  color: var(--text-4);
}

.clist__note {
  margin-top: var(--s-2);
  color: var(--warn-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
</style>
