<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { Activity, ArrowLeft, ChevronsUpDown, Flag, GitBranch, LayoutDashboard, LogOut, MessagesSquare, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Search, Server, Sun, Users, Workflow } from 'lucide-vue-next'
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
 * Ochiq va yig'iq holat - BITTA tartib: belgilar ikkalasida bir xil x da (64px ustun
 * markazida), yozuvlar so'nib, torayayotgan panel tomonidan kesiladi. Har band ichidagi
 * qator ochiq panel kengligida (`--an-row-w`, AdminLayout beradigan --panel-content-w
 * dan) - yig'ilish animatsiyasida yozuvlar qayta qisqarib "titramaydi".
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

// Yig'ish va yoyish - ikki xil tugma (o'ngdagi "yig'ish" va yig'iq ustundagi uchqun):
// bosilgani yashirinadi (`inert` / disabled) va fokus <body> ga tushardi. Fokus shu
// tugmalardan birida bo'lsa - yangi holatdagi juftiga o'tadi.
const sparkBtn = ref<HTMLButtonElement | null>(null)
const collapseBtn = ref<InstanceType<typeof VIconButton> | null>(null)
async function toggle() {
  const active = document.activeElement
  const collapseEl = collapseBtn.value?.$el as HTMLElement | undefined
  const hadFocus = !!active && (active === sparkBtn.value || active === collapseEl)
  emit('toggle')
  await nextTick()
  if (!hadFocus) return
  const next = mini.value ? sparkBtn.value : (collapseBtn.value?.$el as HTMLElement | undefined)
  next?.focus({ preventScroll: true })
}

type NavKey = 'overview' | 'conversations' | 'reports' | 'users' | 'usage' | 'versions' | 'migration' | 'system'
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
  // Yordamchi versiyalari - "Foydalanish" va "Tizim" orasida: sozlama, lekin kundalik.
  { key: 'versions', path: '/admin/versions', icon: GitBranch, match: under('/admin/versions') },
  // AI ishlarini agentga ko'chirish: funksiya holati va taqqoslash natijalari.
  { key: 'migration', path: '/admin/migration', icon: Workflow, match: under('/admin/migration') },
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
    <!-- brend + yig'ish. Uchqun hamma holatda shu joyda; yig'iq ustunda u "yoyish" tugmasi
         (ustiga kelinganda belgisi almashadi), ochiq panelda - oddiy logotip. -->
    <div class="an__brand">
      <VTooltip :text="t('admin.nav.expand')" placement="right" :disabled="!mini" :describe="false">
        <button
          ref="sparkBtn"
          type="button"
          class="an__spark-btn"
          :disabled="!mini"
          :aria-hidden="mini ? undefined : 'true'"
          :aria-label="t('admin.nav.expand')"
          @click="toggle"
        >
          <span class="an__spark" aria-hidden="true"><BrandSpark :size="16" /></span>
          <PanelLeftOpen class="an__spark-alt" :size="20" :stroke-width="1.75" aria-hidden="true" />
        </button>
      </VTooltip>
      <span class="an__title an__fade">
        <span class="an__word">Barno</span>
        <span class="an__badge">{{ t('admin.title') }}</span>
      </span>
      <span v-if="variant === 'rail'" class="an__collapse an__block" :inert="mini">
        <VIconButton
          ref="collapseBtn"
          class="an__collapse-btn"
          :icon="PanelLeftClose"
          :label="t('admin.nav.collapse')"
          size="sm"
          tooltip-placement="right"
          @click="toggle"
        />
      </span>
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
        <span class="an__row">
          <span class="an__icon"><Search :size="20" :stroke-width="1.75" aria-hidden="true" /></span>
          <span class="an__label an__fade">{{ t('admin.nav.search') }}</span>
          <VKbd class="an__kbd an__fade" keys="mod+k" size="sm" aria-hidden="true" />
        </span>
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
            <span class="an__row">
              <span class="an__icon">
                <component :is="item.icon" :size="20" :stroke-width="1.75" aria-hidden="true" />
                <span v-if="item.key === 'reports' && newReports > 0" class="an__dot" aria-hidden="true" />
              </span>
              <span class="an__label an__fade">{{ t(`admin.nav.${item.key}`) }}</span>
              <template v-if="item.key === 'reports' && newReports > 0">
                <VBadge class="an__count an__fade" tone="brand" size="sm" aria-hidden="true">{{ countText }}</VBadge>
                <span class="sr-only">, {{ t('admin.shell.newReports', { n: newReports }) }}</span>
              </template>
            </span>
          </RouterLink>
        </VTooltip>
      </li>
    </ul>

    <div class="an__foot">
      <VTooltip :text="t('admin.nav.backToChat')" placement="right" :disabled="!mini" :describe="false">
        <RouterLink to="/" class="an__link">
          <span class="an__row">
            <span class="an__icon"><ArrowLeft :size="20" :stroke-width="1.75" aria-hidden="true" /></span>
            <span class="an__label an__fade">{{ t('admin.nav.backToChat') }}</span>
          </span>
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
              <span class="an__row an__row--account">
                <VAvatar :name="displayName" :size="28" />
                <span class="an__who an__fade">
                  <span class="an__who-name">{{ displayName }}</span>
                  <span v-if="user?.email && user.email !== displayName" class="an__who-sub">{{ user.email }}</span>
                </span>
                <ChevronsUpDown class="an__chev an__fade" :size="16" :stroke-width="1.75" aria-hidden="true" />
              </span>
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
  /* Belgi 64px ustunning aynan markazida: (64 - 2·12 - 20) / 2 = 10px ichki chet. */
  --an-ico-pad: calc((var(--admin-rail-w) - 2 * var(--s-3) - 20px) / 2);
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  height: 100%;
  min-height: 0;
  padding: var(--s-4) var(--s-3);
  overflow-x: hidden;
  overflow-y: auto;
}
/* Chap panel: qator mazmuni OCHIQ panel kengligida (AdminLayout --panel-content-w beradi;
   tortish paytida u ham o'zgaradi; 1px - panelning o'ng chegarasi). Panel torayganda
   bandlar (fon) u bilan torayadi, qator esa joyida qolib kesiladi. */
.an--rail {
  --an-row-w: calc(var(--panel-content-w, var(--admin-nav-w)) - 1px - 2 * var(--s-3));
}
.an--sheet {
  padding: 0;
  overflow: visible;
}

/* ---- brend ---- */
.an__brand {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s-0_5);
  height: 36px;
  margin-bottom: var(--s-4);
  white-space: nowrap;
}
.an__spark {
  display: inline-flex;
  color: var(--brand);
}
/* Nom + "Admin" nishoni. Tor panelda (200px) nishon o'ngdagi yig'ish tugmasi ostiga
   kirib qolardi. Endi u sig'masa keyingi qatorga o'tadi va bitta qator balandligidagi
   quti uni kesadi (flex-wrap) - px chegara ham, JS ham kerak emas, har tilda nishonning
   o'z kengligi bo'yicha. */
.an__title {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  /* 8px - ilgarigi 2px (brend oralig'i) + 6px (nishon chap cheti) bilan bir xil. */
  column-gap: var(--s-2);
  min-width: 0;
  height: var(--lh-body);
  overflow: hidden;
  overflow: clip;
}
/* Chap panelda kenglik OCHIQ panel bo'yicha (qatorlardagi --an-row-w kabi): uchqun
   katagi va yig'ish tugmasi joyi (32px + o'ng chet 4px + 4px oraliq) ayirilgan. Panel
   bilan torayganda nishon yig'ilish animatsiyasi o'rtasida "sakrab" yo'qolmasin - u
   faqat tortib toraytirilganda (ochiq kenglik o'zgarganda) yashirinadi. */
.an--rail .an__title {
  flex: none;
  width: calc(var(--an-row-w) - (var(--admin-rail-w) - 2 * var(--s-3)) - var(--s-0_5) - 32px - 2 * var(--s-1));
}
.an__word {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.an__badge {
  padding: 1px var(--s-1_5);
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
/* O'ng chetga yopishgan: panel torayganda chet bilan birga suriladi va so'nadi. */
.an__collapse {
  position: absolute;
  top: 50%;
  right: var(--s-1);
  translate: 0 -50%;
}
.an__collapse-btn {
  color: var(--text-3);
}

/* Uchqun - ustun kengligidagi katak, markazi bandlar belgilari bilan bir chiziqda.
   Yig'iq panelda tugma: ustiga kelinganda "yoyish" belgisiga aylanadi. */
.an__spark-btn {
  position: relative;
  display: grid;
  place-items: center;
  flex: none;
  width: calc(var(--admin-rail-w) - 2 * var(--s-3));
  height: 36px;
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease-out);
}
.an__spark-btn:disabled {
  cursor: default;
}
.an__spark-btn > * {
  grid-area: 1 / 1;
  transition: opacity var(--dur-1) var(--ease-out);
}
.an__spark-alt {
  opacity: 0;
  color: var(--text-2);
}
.an__spark-btn:not(:disabled):hover,
.an__spark-btn:not(:disabled):focus-visible {
  background: var(--fill-hover);
}
.an__spark-btn:not(:disabled):hover .an__spark,
.an__spark-btn:not(:disabled):focus-visible .an__spark {
  opacity: 0;
}
.an__spark-btn:not(:disabled):hover .an__spark-alt,
.an__spark-btn:not(:disabled):focus-visible .an__spark-alt {
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
  width: 100%;
  height: 36px;
  padding: 0;
  overflow: hidden;
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
.an__row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  flex: none;
  width: var(--an-row-w, 100%);
  height: 100%;
  padding: 0 var(--s-2) 0 var(--an-ico-pad);
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
/* Yig'ilgan panelda yangi xabarlar - belgi burchagida brend nuqtasi (ochiqda - nishon). */
.an__dot {
  position: absolute;
  top: -2px;
  right: -3px;
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
  background: var(--brand);
  box-shadow: 0 0 0 2px var(--bg-subtle);
  opacity: 0;
  transition: opacity var(--dur-1) var(--ease-out);
}
.is-mini .an__dot {
  opacity: 1;
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
  width: 100%;
  min-height: 44px;
  padding: 0;
  overflow: hidden;
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
/* Avatar markazi ham ustun markazida: 12 + 6 + 14 = 32px. */
.an__row--account {
  gap: var(--s-2);
  height: auto;
  padding: var(--s-1_5) var(--s-2) var(--s-1_5) var(--s-1_5);
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

/* ---- yig'ish / ochish ----
   Yozuvlar tez (--dur-1) so'nadi - kenglik animatsiyasi (--dur-panel) tugashini kutmaydi.
   `an__fade` - band ichidagi yozuv: faqat shaffof (bandning nomi, ekran o'quvchi uni
   ustunda ham o'qiydi). `an__block` - alohida tugma (yig'ish): so'ngach yashirinadi,
   shablonda esa `inert` - Tab unga tushmaydi. */
.an__fade {
  transition: opacity var(--dur-1) var(--ease-out);
}
.is-mini .an__fade {
  opacity: 0;
}
.an__block {
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s;
}
.is-mini .an__block {
  opacity: 0;
  visibility: hidden;
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s linear var(--dur-1);
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
