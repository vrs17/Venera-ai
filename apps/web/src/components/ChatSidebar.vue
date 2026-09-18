<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AuthUser } from '../types'
import type { Theme } from '../theme'
import { LOCALES, setLocale } from '../i18n'
import type { Locale } from '../i18n'
import { ChevronDownIcon, CodeIcon, EarIcon, GlobeIcon, HistoryIcon, MoonIcon, PanelLeftIcon, PlusIcon, SunIcon } from '../icons'
import ChatHistory from './ChatHistory.vue'
import IdentityBar from './IdentityBar.vue'

const props = defineProps<{
  user: AuthUser | null
  theme: Theme
  open: boolean
  collapsed: boolean
  devMode: boolean
  /** "Salom Venera" tinglash yoqilgan. */
  wake: boolean
  /** Mikrofon ochiq va tinglayapti - foydalanuvchi buni KO'RISHI kerak. */
  wakeActive: boolean
  /** Joriy tilda uyg'otish so'zi bor (hozircha faqat o'zbek). */
  wakeSupported: boolean
  /** Server oxirgi parchani buzilgan deb topdi (nutq darvoza bilan kesilgan).
   *  Buni faqat foydalanuvchi tuzata oladi - shuning uchun ko'rsatiladi. */
  wakeDistorted: boolean
}>()
const emit = defineEmits<{
  toggleTheme: []
  toggleDevMode: []
  toggleWake: []
  newChat: []
  /** Yon paneldagi suhbat tanlandi - ChatView uni ochadi. */
  openChat: [id: string]
  close: []
  toggleCollapse: []
  logout: []
}>()

const { t, locale } = useI18n({ useScope: 'global' })
const currentLang = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale)) ?? LOCALES[0])
// Collapse only applies on desktop; the mobile sidebar is the full off-canvas panel.
const mq = window.matchMedia('(max-width: 768px)')
const isMobile = ref(mq.matches)
function syncMq() {
  isMobile.value = mq.matches
}
onMounted(() => {
  syncMq()
  mq.addEventListener('change', syncMq)
  window.addEventListener('resize', syncMq)
})

const compact = computed(() => props.collapsed && !isMobile.value)

// Language menu opens upward (the row sits low in the sidebar).
const langOpen = ref(false)
const langRef = ref<HTMLElement | null>(null)
function onDocDown(e: MouseEvent) {
  if (langRef.value && !langRef.value.contains(e.target as Node)) langOpen.value = false
}
watch(langOpen, (o) => {
  if (o) document.addEventListener('mousedown', onDocDown)
  else document.removeEventListener('mousedown', onDocDown)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocDown)
  mq.removeEventListener('change', syncMq)
  window.removeEventListener('resize', syncMq)
})

function chooseLang(code: Locale) {
  setLocale(code)
  langOpen.value = false
}
function onNewChat() {
  emit('newChat')
  emit('close')
}
function onOpenChat(id: string) {
  emit('openChat', id)
  emit('close')
}
// Collapsed: expand the rail, then reveal the language menu.
function expandToLang() {
  emit('toggleCollapse')
  langOpen.value = true
}
</script>

<template>
  <aside class="sidebar" :class="{ 'is-open': open, 'is-collapsed': compact }">
    <div class="sidebar__top">
      <button class="sidebar__toggle" :aria-label="t('menu')" :title="t('menu')" @click="emit('toggleCollapse')">
        <PanelLeftIcon :size="18" />
      </button>
      <span v-if="!compact" class="sidebar__brand">
        Venera
        <span class="sidebar__spark" aria-hidden="true">✦</span>
      </span>
    </div>

    <button class="sidebar__new" :title="t('newChat')" @click="onNewChat">
      <PlusIcon :size="15" />
      <span v-if="!compact">{{ t('newChat') }}</span>
    </button>

    <!-- Suhbatlar tarixi. Yig'ilgan panelda ro'yxatga joy yo'q - belgi
         panelni ochadi. -->
    <ChatHistory v-if="!compact" @open="onOpenChat" @removed-active="emit('newChat')" />
    <template v-else>
      <button class="sidebar__row sidebar__row--history" :title="t('historyHeading')" @click="emit('toggleCollapse')">
        <HistoryIcon :size="16" />
      </button>
      <div class="sidebar__spacer" />
    </template>

    <div class="sidebar__config">
      <!-- Developer mode -->
      <button
        class="sidebar__row sidebar__row--switch"
        :class="{ 'is-on': devMode }"
        :title="t('developerMode')"
        role="switch"
        :aria-checked="devMode"
        @click="emit('toggleDevMode')"
      >
        <CodeIcon :size="16" />
        <span v-if="!compact" class="sidebar__row-label">{{ t('developerMode') }}</span>
        <span v-if="!compact" class="sidebar__switch" aria-hidden="true"><span class="sidebar__switch-knob" /></span>
      </button>

      <!-- "Salom Venera". Faqat uyg'otish so'zi bor tillarda ko'rinadi -
           boshqa tilda tugma bosilsa hech narsa qilmasdi. -->
      <button
        v-if="wakeSupported"
        class="sidebar__row sidebar__row--switch"
        :class="{ 'is-on': wake }"
        :title="t('wakeWordHint')"
        role="switch"
        :aria-checked="wake"
        @click="emit('toggleWake')"
      >
        <EarIcon :size="16" />
        <span v-if="!compact" class="sidebar__row-label">{{ t('wakeWord') }}</span>
        <span
          v-if="!compact && wakeActive"
          class="sidebar__live"
          :title="t('wakeWordActive')"
          aria-hidden="true"
        />
        <span v-if="!compact" class="sidebar__switch" aria-hidden="true"><span class="sidebar__switch-knob" /></span>
      </button>
      <!-- Yozuv buzilgan: "uyg'onmadi" ning sababi so'zda emas, mikrofon
           zanjirida. Bu holatda jim turish foydalanuvchini "aniq aytmadim"
           deb o'ylashga majbur qilardi - aslida u hech narsa qila olmasdi. -->
      <p v-if="wakeSupported && wake && wakeDistorted && !compact" class="sidebar__notice" role="status">
        {{ t('wakeWordDistorted') }}
      </p>

      <!-- Theme -->
      <button class="sidebar__row" :title="theme === 'dark' ? t('light') : t('dark')" @click="emit('toggleTheme')">
        <SunIcon v-if="theme === 'dark'" :size="17" />
        <MoonIcon v-else :size="17" />
        <span v-if="!compact" class="sidebar__row-label">{{ theme === 'dark' ? t('light') : t('dark') }}</span>
      </button>

      <!-- Language -->
      <div v-if="!compact" ref="langRef" class="sidebar__lang" @keydown.esc="langOpen = false">
        <button class="sidebar__row" :aria-expanded="langOpen" aria-haspopup="menu" @click="langOpen = !langOpen">
          <GlobeIcon :size="16" />
          <span class="sidebar__row-label">{{ currentLang.label }}</span>
          <ChevronDownIcon
            :size="10"
            :style="{ transform: langOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', marginLeft: 'auto', flexShrink: 0 }"
          />
        </button>
        <div v-if="langOpen" class="sidebar__menu glass">
          <button
            v-for="l in LOCALES"
            :key="l.code"
            class="sidebar__menu-item"
            :class="{ 'is-active': l.code === locale }"
            @click="chooseLang(l.code)"
          >
            <span>{{ l.label }}</span>
            <span v-if="l.code === locale" class="sidebar__dot" aria-hidden="true" />
          </button>
        </div>
      </div>
      <button v-else class="sidebar__row" :title="currentLang.label" @click="expandToLang">
        <GlobeIcon :size="16" />
      </button>

      <!-- Account -->
      <IdentityBar v-if="!compact" :user="user" @logout="emit('logout')" />
      <button v-else class="sidebar__row sidebar__row--avatar" :title="user?.email || ''" @click="emit('toggleCollapse')">
        <span class="sidebar__avatar">{{ (user?.email?.[0] || '?').toUpperCase() }}</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 264px;
  flex-shrink: 0;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  background: var(--surface-sunken);
  border-right: 1px solid var(--border);
  position: relative;
  z-index: 20;
  transition: width 0.2s ease;
}
.sidebar__top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.sidebar__toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.sidebar__toggle:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
}
.sidebar__spark {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
}
.sidebar__new {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
  font-weight: 600;
  font-family: 'Figtree', sans-serif;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  transition: background 0.15s, border-color 0.15s;
}
.sidebar__new:hover {
  background: var(--surface-hover);
  border-color: var(--border-hover);
}
.sidebar__nav {
  margin-top: 4px;
}
.sidebar__spacer {
  flex: 1;
}
.sidebar__row--history {
  margin-top: 10px;
}
.sidebar__config {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.sidebar__row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13.5px;
  font-weight: 500;
  font-family: 'Figtree', sans-serif;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  transition: background 0.15s, color 0.15s;
}
.sidebar__row:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.sidebar__row-label {
  white-space: nowrap;
}
/* Uyg'otish yozuvi buzilgani haqida eslatma - qator ostida, kichik. */
.sidebar__notice {
  margin: -2px 8px 6px 8px;
  padding: 6px 8px;
  font-size: 12px;
  line-height: 1.35;
  color: var(--text);
  opacity: 0.85;
  border-left: 2px solid var(--border-hover);
  border-radius: 0 6px 6px 0;
  background: var(--surface-hover);
}
/* Developer-mode pill switch. */
.sidebar__row--switch.is-on {
  color: var(--text);
}
.sidebar__switch {
  margin-left: auto;
  flex-shrink: 0;
  width: 34px;
  height: 19px;
  border-radius: 999px;
  background: var(--surface-hover);
  border: 1px solid var(--border-hover);
  position: relative;
  transition: background 0.2s, border-color 0.2s;
}
.sidebar__row--switch.is-on .sidebar__switch {
  background: var(--ink);
  border-color: transparent;
}
.sidebar__switch-knob {
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
.sidebar__row--switch.is-on .sidebar__switch-knob {
  transform: translateX(15px);
}
/* Collapsed rail: no track visible, so signal the active mode by tinting the icon. */
.sidebar.is-collapsed .sidebar__row--switch.is-on {
  color: var(--ink);
}
.sidebar__avatar {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--avatar-bg);
  color: var(--avatar-fg);
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.sidebar__lang {
  position: relative;
}
.sidebar__menu {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  right: 0;
  padding: 6px;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 12px;
  box-shadow: var(--menu-shadow);
  z-index: 40;
  animation: fadeUp 0.2s ease both;
}
.sidebar__menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--text-secondary);
  font-family: 'Figtree', sans-serif;
  font-size: 13.5px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
}
.sidebar__menu-item:hover {
  background: var(--surface-hover);
}
.sidebar__menu-item.is-active {
  color: var(--text);
  font-weight: 700;
}
.sidebar__dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--ink);
}

/* Collapsed rail: icon-only, centred. */
.sidebar.is-collapsed {
  width: 64px;
  padding: 18px 10px;
}
.sidebar.is-collapsed .sidebar__top,
.sidebar.is-collapsed .sidebar__new,
.sidebar.is-collapsed .sidebar__row {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

/* Mobile: off-canvas slide-in panel (always full width, never collapsed). */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    transform: translateX(-100%);
    transition: transform 0.28s ease;
    box-shadow: var(--menu-shadow);
  }
  .sidebar.is-open {
    transform: translateX(0);
  }
  .sidebar__toggle {
    display: none;
  }
}
/* Mikrofon ochiq. Qizil - yozuv indikatorining umumiy tili, lekin yolg'iz
   qizil nuqta xato belgisiga o'xshab ketadi: halqa uni "efirda" ma'nosiga
   yaqinlashtiradi. Yorliq ICHIDA emas, yonida turadi - u yerda `nowrap`
   uni harflarga yopishtirib qo'yardi.
   Nomi `__dot` EMAS: u til tanlovidagi belgi uchun band. */
.sidebar__live {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  margin-left: -4px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
  animation: sidebar-live 1.8s ease-in-out infinite;
}
@keyframes sidebar-live {
  0%, 100% { opacity: 0.35; }
  50%      { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .sidebar__live { animation: none; opacity: 1; }
}
</style>
