<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  Activity,
  ArrowLeft,
  ChevronsUpDown,
  Flag,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Server,
  Sun,
  Users,
} from 'lucide-vue-next'
import BrandSpark from '../../components/BrandSpark.vue'
import VAvatar from '../../ui/VAvatar.vue'
import VBadge from '../../ui/VBadge.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VKbd from '../../ui/VKbd.vue'
import VMenu from '../../ui/VMenu.vue'
import VMenuItem from '../../ui/VMenuItem.vue'
import VTooltip from '../../ui/VTooltip.vue'
import { useCommandPalette } from '../../ui/useCommandPalette'
import { useAuth } from '../../composables/useAuth'
import { useChats } from '../../composables/useChats'
import { LOCALES, setLocale } from '../../i18n'
import type { Locale } from '../../i18n'
import { useTheme } from '../../theme'
import { useAdminFilters } from '../useAdminFilters'
import { useAdminMe } from './useAdminMe'

/**
 * Admin menyusi - chap panel (232px, yig'ilganda 64px belgilar) va telefondagi
 * pastki sheet ichidagi aynan shu ro'yxat. Bitta komponent: ikkala joyda bandlar,
 * nishon va hisob menyusi bir xil ishlaydi.
 *
 * Props:
 * - `variant`   - 'rail' (chap panel) | 'sheet' (telefon: katta nishonlar, yig'ish yo'q).
 * - `collapsed` - faqat 'rail': belgilar + tooltip.
 * Emits: `toggle` (yig'ish/yoyish), `navigate` (band tanlandi - sheet yopilsin).
 *
 * Havolalar global filtrni (`?preset=&channel=`) o'zi bilan olib o'tadi - sahifadan
 * sahifaga o'tganda tanlangan davr yo'qolmaydi.
 */
const props = withDefaults(
  defineProps<{
    variant?: 'rail' | 'sheet'
    collapsed?: boolean
  }>(),
  { variant: 'rail' },
)
const emit = defineEmits<{ toggle: []; navigate: [] }>()

const { t, locale } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { withFilters } = useAdminFilters()
const { newReports } = useAdminMe()
const { user, logout } = useAuth()
const palette = useCommandPalette()

const mini = computed(() => props.variant === 'rail' && props.collapsed)

type NavKey = 'overview' | 'conversations' | 'reports' | 'users' | 'usage' | 'system'
interface NavItem {
  key: NavKey
  path: string
  icon: Component
  /** Qaysi yo'llarda "faol" (masalan, savol izi - Suhbatlar bo'limi). */
  match: (path: string) => boolean
}

const under = (...prefixes: string[]) => (path: string) => prefixes.some((p) => path === p || path.startsWith(`${p}/`))

const items: NavItem[] = [
  { key: 'overview', path: '/admin', icon: LayoutDashboard, match: (p) => p === '/admin' || p === '/admin/' },
  {
    key: 'conversations',
    path: '/admin/conversations',
    icon: MessagesSquare,
    match: under('/admin/conversations', '/admin/turns'),
  },
  { key: 'reports', path: '/admin/reports', icon: Flag, match: under('/admin/reports') },
  { key: 'users', path: '/admin/users', icon: Users, match: under('/admin/users') },
  { key: 'usage', path: '/admin/usage', icon: Activity, match: under('/admin/usage') },
  { key: 'system', path: '/admin/system', icon: Server, match: under('/admin/system') },
]

const countText = computed(() => (newReports.value > 99 ? '99+' : String(newReports.value)))
function tipFor(item: NavItem): string {
  const label = t(`admin.nav.${item.key}`)
  return item.key === 'reports' && newReports.value > 0 ? `${label} · ${countText.value}` : label
}

/* ---- hisob menyusi: mavzu, til, chiqish (chat bilan bir xil yordamchilar) ---- */

// Tanlov (yorug' / qorong'i / tizim) - chat bilan bitta manba, boshqa tabga ham ergashadi.
const { preference: theme, setPreference: pickTheme } = useTheme()
function pickLocale(code: Locale) {
  setLocale(code)
}

const displayName = computed(() => user.value?.fullName?.trim() || user.value?.email || '')

async function signOut() {
  // Keyingi odam oldingisining "so'nggi" qidiruvlarini va suhbatlar ro'yxatini ko'rmasin.
  palette.clearRecents()
  useChats().reset()
  await logout()
  await router.push({ name: 'welcome' })
}
</script>

<template>
  <nav class="an" :class="[`an--${variant}`, { 'is-mini': mini }]" :aria-label="t('admin.title')">
    <!-- brend + yig'ish -->
    <div class="an__brand">
      <VTooltip v-if="mini" :text="t('admin.nav.expand')" placement="right" :describe="false">
        <button type="button" class="an__spark-btn" :aria-label="t('admin.nav.expand')" @click="emit('toggle')">
          <span class="an__spark" aria-hidden="true"><BrandSpark :size="16" /></span>
          <PanelLeftOpen class="an__spark-alt" :size="20" :stroke-width="1.75" aria-hidden="true" />
        </button>
      </VTooltip>
      <template v-else>
        <span class="an__spark" aria-hidden="true"><BrandSpark :size="16" /></span>
        <span class="an__word">Venera</span>
        <span class="an__badge">{{ t('admin.title') }}</span>
        <VIconButton
          v-if="variant === 'rail'"
          class="an__collapse"
          :icon="PanelLeftClose"
          :label="t('admin.nav.collapse')"
          size="sm"
          tooltip-placement="right"
          @click="emit('toggle')"
        />
      </template>
    </div>

    <!-- qidiruv (⌘K). Telefonda u yuqori paneldagi belgida - sheet yopilayotganda fokus
         qaytishi palitra maydonidan fokusni tortib olmasin. -->
    <VTooltip
      v-if="variant === 'rail'"
      :text="t('admin.nav.search')"
      shortcut="mod+k"
      placement="right"
      :disabled="!mini"
      :describe="false"
    >
      <button type="button" class="an__link an__search" aria-keyshortcuts="Control+K Meta+K" @click="palette.open()">
        <span class="an__icon"><Search :size="20" :stroke-width="1.75" aria-hidden="true" /></span>
        <span class="an__label" :class="{ 'sr-only': mini }">{{ t('admin.nav.search') }}</span>
        <VKbd v-if="!mini" class="an__kbd" keys="mod+k" size="sm" />
      </button>
    </VTooltip>

    <ul class="an__list">
      <li v-for="item in items" :key="item.key">
        <VTooltip :text="tipFor(item)" placement="right" :disabled="!mini" :describe="false">
          <RouterLink
            :to="withFilters(item.path)"
            class="an__link"
            :class="{ 'is-active': item.match(route.path) }"
            :aria-current="item.match(route.path) ? 'page' : undefined"
            @click="emit('navigate')"
          >
            <span class="an__icon">
              <component :is="item.icon" :size="20" :stroke-width="1.75" aria-hidden="true" />
              <span v-if="item.key === 'reports' && newReports > 0 && mini" class="an__dot" aria-hidden="true" />
            </span>
            <span class="an__label" :class="{ 'sr-only': mini }">{{ t(`admin.nav.${item.key}`) }}</span>
            <template v-if="item.key === 'reports' && newReports > 0">
              <VBadge v-if="!mini" class="an__count" tone="brand" size="sm" aria-hidden="true">{{ countText }}</VBadge>
              <span class="sr-only">, {{ t('admin.shell.newReports', { n: newReports }) }}</span>
            </template>
          </RouterLink>
        </VTooltip>
      </li>
    </ul>

    <div class="an__foot">
      <VTooltip :text="t('admin.nav.backToChat')" placement="right" :disabled="!mini" :describe="false">
        <RouterLink to="/" class="an__link">
          <span class="an__icon"><ArrowLeft :size="20" :stroke-width="1.75" aria-hidden="true" /></span>
          <span class="an__label" :class="{ 'sr-only': mini }">{{ t('admin.nav.backToChat') }}</span>
        </RouterLink>
      </VTooltip>

      <VMenu :placement="mini ? 'right-end' : 'top-start'" :min-width="232" :aria-label="t('admin.nav.account')">
        <template #trigger>
          <!-- VPopover `data-v-contents` o'ramalaridan o'tib, tugmaning o'zini trigger qiladi. -->
          <VTooltip :text="displayName" placement="right" :disabled="!mini" :describe="false">
            <button
              type="button"
              class="an__account"
              :aria-label="mini ? `${t('admin.nav.account')}: ${displayName}` : undefined"
            >
              <VAvatar :name="displayName" :size="28" />
              <span v-if="!mini" class="an__who">
                <span class="an__who-name">{{ displayName }}</span>
                <span v-if="user?.email && user.email !== displayName" class="an__who-sub">{{ user.email }}</span>
              </span>
              <ChevronsUpDown v-if="!mini" class="an__chev" :size="16" :stroke-width="1.75" aria-hidden="true" />
            </button>
          </VTooltip>
        </template>
        <VMenuItem kind="label">{{ t('ui.theme') }}</VMenuItem>
        <VMenuItem kind="radio" :icon="Sun" :checked="theme === 'light'" @select="pickTheme('light')">
          {{ t('ui.light') }}
        </VMenuItem>
        <VMenuItem kind="radio" :icon="Moon" :checked="theme === 'dark'" @select="pickTheme('dark')">
          {{ t('ui.dark') }}
        </VMenuItem>
        <VMenuItem kind="radio" :icon="Monitor" :checked="theme === 'system'" @select="pickTheme('system')">
          {{ t('ui.system') }}
        </VMenuItem>
        <VMenuItem kind="separator" />
        <VMenuItem kind="label">{{ t('ui.language') }}</VMenuItem>
        <VMenuItem
          v-for="l in LOCALES"
          :key="l.code"
          kind="radio"
          :checked="locale === l.code"
          :text-value="l.label"
          @select="pickLocale(l.code)"
        >
          <span :lang="l.htmlLang">{{ l.label }}</span>
        </VMenuItem>
        <VMenuItem kind="separator" />
        <VMenuItem :icon="LogOut" @select="signOut">{{ t('admin.nav.signOut') }}</VMenuItem>
      </VMenu>
    </div>
  </nav>
</template>

<style scoped>
.an {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  height: 100%;
  min-height: 0;
  padding: var(--s-4) var(--s-3);
  overflow-x: hidden;
  overflow-y: auto;
}
.an--sheet {
  padding: 0;
  overflow: visible;
}

/* ---- brend ---- */
.an__brand {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  height: 36px;
  margin-bottom: var(--s-4);
  padding: 0 var(--s-1) 0 var(--s-2);
}
.an__spark {
  display: inline-flex;
  flex: none;
  justify-content: center;
  width: 20px;
  color: var(--brand);
}
.an__word {
  font-size: var(--fs-body);
  font-weight: 600;
  letter-spacing: -0.011em;
  white-space: nowrap;
}
.an__badge {
  padding: 1px var(--s-1_5);
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  white-space: nowrap;
}
.an__collapse {
  margin-left: auto;
  color: var(--text-3);
}

/* Yig'ilgan panel: uchqun tugmasi, ustiga kelinganda "yoyish" belgisiga aylanadi. */
.an__spark-btn {
  position: relative;
  display: grid;
  place-items: center;
  width: 40px;
  height: 36px;
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease-out);
}
.an__spark-btn > * {
  grid-area: 1 / 1;
  transition: opacity var(--dur-1) var(--ease-out);
}
.an__spark-alt {
  opacity: 0;
  color: var(--text-2);
}
.an__spark-btn:hover,
.an__spark-btn:focus-visible {
  background: var(--fill-hover);
}
.an__spark-btn:hover .an__spark,
.an__spark-btn:focus-visible .an__spark {
  opacity: 0;
}
.an__spark-btn:hover .an__spark-alt,
.an__spark-btn:focus-visible .an__spark-alt {
  opacity: 1;
}

/* ---- bandlar ---- */
.an__list {
  display: flex;
  flex-direction: column;
  gap: var(--s-0_5);
  margin: var(--s-2) 0 0;
  padding: 0;
  list-style: none;
}
.an__link {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  height: 36px;
  padding: 0 var(--s-2);
  border-radius: var(--r-sm);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  text-align: start;
  white-space: nowrap;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
.an__link:hover {
  background: var(--fill-hover);
  color: var(--text);
}
.an__link.is-active {
  background: var(--fill);
  color: var(--text);
}
.an__link:focus-visible {
  outline-offset: -2px;
}
.an__icon {
  position: relative;
  display: inline-flex;
  flex: none;
}
.an__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.an__kbd {
  flex: none;
  opacity: 0.8;
}
.an__count {
  flex: none;
}
/* Yig'ilgan panelda yangi xabarlar - belgi burchagida brend nuqtasi. */
.an__dot {
  position: absolute;
  top: -2px;
  right: -3px;
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
  background: var(--brand);
  box-shadow: 0 0 0 2px var(--bg-subtle);
}

/* ---- pastki qism ---- */
.an__foot {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  margin-top: auto;
  padding-top: var(--s-4);
}
.an__account {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  width: 100%;
  min-height: 44px;
  padding: var(--s-1_5) var(--s-2) var(--s-1_5) var(--s-1_5);
  border-radius: var(--r-md);
  text-align: start;
  transition: background-color var(--dur-1) var(--ease-out);
}
.an__account:hover,
.an__account[aria-expanded='true'] {
  background: var(--fill-hover);
}
.an__account:focus-visible {
  outline-offset: -2px;
}
.an__who {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.an__who-name,
.an__who-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.an__who-name {
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.an__who-sub {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.an__chev {
  flex: none;
  color: var(--text-3);
}

/* ---- yig'ilgan (64px) ---- */
.is-mini {
  align-items: center;
  padding-inline: var(--s-3);
}
.is-mini .an__brand {
  justify-content: center;
  padding: 0;
}
.is-mini .an__link {
  justify-content: center;
  width: 40px;
  padding: 0;
}
.is-mini .an__list,
.is-mini .an__foot {
  align-items: center;
}
.is-mini .an__account {
  justify-content: center;
  width: 40px;
  min-height: 40px;
  padding: 0;
}

/* ---- telefon sheet: barmoq uchun kattaroq nishonlar ---- */
.an--sheet .an__brand {
  height: 40px;
  margin-bottom: var(--s-3);
}
.an--sheet .an__link {
  height: 44px;
  font-size: var(--fs-body);
}
.an--sheet .an__foot {
  padding-top: var(--s-6);
}
</style>
