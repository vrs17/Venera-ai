<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PanelLeftClose, PanelLeftOpen, Search, SquarePen, X } from 'lucide-vue-next'
import type { AuthUser } from '../types'
import type { ThemePreference } from '../theme'
import VIconButton from '../ui/VIconButton.vue'
import VKbd from '../ui/VKbd.vue'
import VSearchField from '../ui/VSearchField.vue'
import BrandSpark from './BrandSpark.vue'
import ChatHistory from './ChatHistory.vue'
import IdentityBar from './IdentityBar.vue'

/**
 * Chap panel - faqat navigatsiya: logotip, "Yangi suhbat", qidiruv, tarix va pastda
 * hisob (sozlamalar hisob menyusida). Uch ko'rinish:
 *   inline (≥1120)   - 272px, --bg-subtle; yig'ilsa 56px belgilar ustuni;
 *   drawer (<1120)   - ChatView uni VSheet ichida ochadi (fokus tuzog'i, Esc, parda).
 * Yangi suhbat va suhbat ochish drawer'ni yopadi.
 */
const props = withDefaults(
  defineProps<{
    user: AuthUser | null
    mode?: 'inline' | 'drawer'
    /** Faqat inline: 56px belgilar ustuni. */
    collapsed?: boolean
    theme: ThemePreference
    devMode: boolean
    wake: boolean
    wakeSupported: boolean
    wakeDistorted?: boolean
    wakeBlocked?: boolean
    isAdmin?: boolean
  }>(),
  { mode: 'inline', collapsed: false, wakeDistorted: false, wakeBlocked: false, isAdmin: false },
)
const emit = defineEmits<{
  toggleCollapse: []
  newChat: []
  /** Yon paneldagi suhbat tanlandi - ChatView uni ochadi. */
  openChat: [id: string]
  close: []
  setTheme: [theme: ThemePreference]
  toggleDevMode: []
  toggleWake: []
  openDesktop: []
  logout: []
}>()

const { t } = useI18n({ useScope: 'global' })
const query = ref('')
const search = ref<InstanceType<typeof VSearchField> | null>(null)

function onNewChat() {
  emit('newChat')
  emit('close')
}
function onOpenChat(id: string) {
  emit('openChat', id)
  emit('close')
}
// Yig'ish/ochish ikki xil <aside> ni almashtiradi - bosilgan tugma DOM'dan chiqadi va
// fokus <body> ga tushardi. Fokus yo'qolgan bo'lsa, yangi ko'rinishdagi juftiga o'tadi.
const railToggle = ref<InstanceType<typeof VIconButton> | null>(null)
const panelToggle = ref<InstanceType<typeof VIconButton> | null>(null)
async function toggleCollapse() {
  emit('toggleCollapse')
  await nextTick()
  const active = document.activeElement
  if (active && active !== document.body) return
  const next = (railToggle.value ?? panelToggle.value)?.$el as HTMLElement | undefined
  next?.focus({ preventScroll: true })
}
// Yig'iq ustundagi lupa: panel ochiladi va fokus darhol qidiruvga.
async function expandToSearch() {
  emit('toggleCollapse')
  await nextTick()
  search.value?.focus()
}
</script>

<template>
  <aside v-if="mode === 'inline' && props.collapsed" class="sb is-rail" :aria-label="t('chat.navigation')">
    <VIconButton
      ref="railToggle"
      :icon="PanelLeftOpen"
      :label="t('chat.expand')"
      tooltip-placement="right"
      @click="toggleCollapse"
    />
    <VIconButton
      :icon="SquarePen"
      :label="t('newChat')"
      shortcut="mod+shift+o"
      tooltip-placement="right"
      @click="emit('newChat')"
    />
    <VIconButton :icon="Search" :label="t('chat.search')" tooltip-placement="right" @click="expandToSearch" />
    <div class="sb__spacer" />
    <IdentityBar
      compact
      :user="user"
      :theme="theme"
      :dev-mode="devMode"
      :wake="wake"
      :wake-supported="wakeSupported"
      :wake-distorted="wakeDistorted"
      :wake-blocked="wakeBlocked"
      :is-admin="isAdmin"
      @set-theme="emit('setTheme', $event)"
      @toggle-dev-mode="emit('toggleDevMode')"
      @toggle-wake="emit('toggleWake')"
      @open-desktop="emit('openDesktop')"
      @logout="emit('logout')"
    />
  </aside>

  <aside v-else class="sb" :class="{ 'is-drawer': mode === 'drawer' }" :aria-label="t('chat.navigation')">
    <div class="sb__top">
      <span class="sb__brand">
        <span class="sb__spark" aria-hidden="true"><BrandSpark :size="16" /></span>
        <span class="sb__word">Venera</span>
      </span>
      <VIconButton
        v-if="mode === 'inline'"
        ref="panelToggle"
        size="sm"
        :icon="PanelLeftClose"
        :label="t('chat.collapse')"
        tooltip-placement="bottom"
        @click="toggleCollapse"
      />
      <VIconButton v-else size="sm" :icon="X" :label="t('close')" tooltip-placement="bottom" @click="emit('close')" />
    </div>

    <div class="sb__actions">
      <button type="button" class="sb__new" aria-keyshortcuts="Control+Shift+O Meta+Shift+O" @click="onNewChat">
        <SquarePen :size="18" :stroke-width="1.75" aria-hidden="true" />
        <span class="sb__new-label">{{ t('newChat') }}</span>
        <VKbd class="sb__kbd" keys="mod+shift+o" size="sm" aria-hidden="true" />
      </button>
      <VSearchField ref="search" v-model="query" size="sm" :placeholder="t('ui.search')" :aria-label="t('chat.search')" />
    </div>

    <ChatHistory :query="query" @open="onOpenChat" @removed-active="emit('newChat')" />

    <div class="sb__foot">
      <IdentityBar
        :user="user"
        :theme="theme"
        :dev-mode="devMode"
        :wake="wake"
        :wake-supported="wakeSupported"
        :wake-distorted="wakeDistorted"
        :wake-blocked="wakeBlocked"
        :is-admin="isAdmin"
        @set-theme="emit('setTheme', $event)"
        @toggle-dev-mode="emit('toggleDevMode')"
        @toggle-wake="emit('toggleWake')"
        @open-desktop="emit('openDesktop')"
        @logout="emit('logout')"
      />
    </div>
  </aside>
</template>

<style scoped>
.sb {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: var(--sidebar-w);
  height: 100%;
  min-height: 0;
  background: var(--bg-subtle);
  border-right: 1px solid var(--line);
}
.sb.is-drawer {
  width: 100%;
  border-right: 0;
  background: var(--surface);
  /* viewport-fit=cover: drawer ekran chetidan 8px ichkarida (VSheet), iPhone'da esa
     kesik/holat paneli va "home" chizig'i undan kattaroq - logotip va hisob ular
     ostiga kirib qolmasin. */
  padding:
    max(0px, calc(env(safe-area-inset-top, 0px) - var(--s-2))) 0
    max(0px, calc(env(safe-area-inset-bottom, 0px) - var(--s-2)))
    max(0px, calc(env(safe-area-inset-left, 0px) - var(--s-2)));
}

.sb__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  height: 56px;
  padding: 0 var(--s-3) 0 var(--s-4);
}
.sb__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
}
.sb__spark {
  display: inline-flex;
  color: var(--brand);
}
.sb__word {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.011em;
}

.sb__actions {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  flex-shrink: 0;
  padding: var(--s-1) var(--s-2) var(--s-3);
}
.sb__new {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  height: 36px;
  padding: 0 var(--s-2);
  border-radius: var(--r-sm);
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 500;
  text-align: left;
  transition: background-color var(--dur-1) var(--ease-out);
}
.sb__new svg {
  flex-shrink: 0;
  color: var(--text-2);
}
.sb__new-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb__kbd {
  opacity: 0;
  transition: opacity var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .sb__new:hover {
    background: var(--fill);
  }
  .sb__new:hover .sb__kbd {
    opacity: 1;
  }
}
.sb__new:focus-visible .sb__kbd {
  opacity: 1;
}
@media (hover: none) {
  .sb__kbd {
    display: none;
  }
}

.sb__foot {
  flex-shrink: 0;
  padding: var(--s-2);
  border-top: 1px solid var(--line);
}

/* Yig'iq ustun: faqat belgilar, markazda. */
.sb.is-rail {
  align-items: center;
  gap: var(--s-1);
  width: var(--rail-w);
  padding: 10px 0 var(--s-2);
}
.sb__spacer {
  flex: 1;
}
</style>
