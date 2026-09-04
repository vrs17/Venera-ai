<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AuthUser } from '../types'
import { ChevronDownIcon, LogOutIcon } from '../icons'

// Read-only account widget for the sidebar. Identity comes from the auth session
// (no client-side editing — the backend owns it), so this just shows who's
// signed in and offers Log out. Opens an upward dropdown with a few details.
defineProps<{ user: AuthUser | null }>()
const emit = defineEmits<{ logout: [] }>()

const { t } = useI18n({ useScope: 'global' })
const open = ref(false)
const wrapRef = ref<HTMLDivElement | null>(null)

function onDocDown(e: MouseEvent) {
  if (wrapRef.value && !wrapRef.value.contains(e.target as Node)) open.value = false
}
watch(open, (isOpen) => {
  if (isOpen) document.addEventListener('mousedown', onDocDown)
  else document.removeEventListener('mousedown', onDocDown)
})
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocDown))

function onLogout() {
  open.value = false
  emit('logout')
}
</script>

<template>
  <div ref="wrapRef" class="sb-id-wrap" @keydown.esc="open = false">
    <button
      class="sb-id"
      :title="user?.email || ''"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="open = !open"
    >
      <span class="sb-id__avatar">{{ (user?.email?.[0] || '?').toUpperCase() }}</span>
      <span class="sb-id__text">
        <span class="sb-id__email">{{ user?.fullName || user?.email || '—' }}</span>
        <span v-if="user?.actorType" class="sb-id__actor">{{ user.actorType }}</span>
      </span>
      <ChevronDownIcon
        :size="12"
        :style="{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', marginLeft: 'auto', flexShrink: 0 }"
      />
    </button>

    <div v-if="open" class="glass sb-id__menu">
      <div class="sb-id__head">
        <span class="sb-id__head-name">{{ user?.fullName || '—' }}</span>
        <span class="sb-id__head-email">{{ user?.email }}</span>
      </div>
      <dl v-if="user?.actorType || user?.department" class="sb-id__details">
        <div v-if="user?.actorType" class="sb-id__detail">
          <dt>{{ t('actorType') }}</dt>
          <dd>{{ user.actorType }}</dd>
        </div>
        <div v-if="user?.department" class="sb-id__detail">
          <dt>{{ t('department') }}</dt>
          <dd>{{ user.department }}</dd>
        </div>
      </dl>
      <button type="button" class="id-logout" @click="onLogout">
        <LogOutIcon :size="15" />
        <span>{{ t('logout') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.sb-id-wrap {
  position: relative;
}
.sb-id {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border-radius: 12px;
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  text-align: left;
  font-family: 'Figtree', sans-serif;
  color: var(--text);
  transition: background 0.15s, border-color 0.15s;
}
.sb-id:hover {
  background: var(--surface-hover);
}
.sb-id__avatar {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--avatar-bg);
  color: var(--avatar-fg);
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.sb-id__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.25;
}
.sb-id__email {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-id__actor {
  font-size: 11px;
  color: var(--text-secondary);
}
/* Upward dropdown (the account row sits at the bottom of the sidebar). */
.sb-id__menu {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  right: 0;
  padding: 14px;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  box-shadow: var(--menu-shadow);
  z-index: 40;
  animation: fadeUp 0.2s ease both;
}
.sb-id__head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
}
.sb-id__head-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.sb-id__head-email {
  font-size: 12.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-id__details {
  margin: 0 0 4px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sb-id__detail {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
}
.sb-id__detail dt {
  color: var(--text-muted);
  margin: 0;
}
.sb-id__detail dd {
  color: var(--text);
  margin: 0;
  font-weight: 500;
  text-align: right;
}
.id-logout {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin-top: 12px;
  padding: 12px 2px 0;
  border: none;
  border-top: 1px solid var(--border);
  background: none;
  color: var(--text-secondary);
  font-family: 'Figtree', sans-serif;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s;
}
.id-logout:hover {
  color: var(--text);
}
</style>
