<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { Activity, ArrowLeft, Flag, LayoutDashboard, Menu, MessagesSquare, Search, Server, Users } from 'lucide-vue-next'
import VCommandPalette from '../ui/VCommandPalette.vue'
import VIconButton from '../ui/VIconButton.vue'
import VResizeHandle from '../ui/VResizeHandle.vue'
import VSheet from '../ui/VSheet.vue'
import { useId } from '../ui/composables/useId'
import { useIsPhone, useMediaQuery } from '../ui/composables/useMediaQuery'
import { useResizablePanel } from '../ui/composables/useResizablePanel'
import { useCommandPalette } from '../ui/useCommandPalette'
import type { CommandGroup, CommandItem } from '../ui/useCommandPalette'
import { fmtRelative } from '../ui/format'
import { searchAdmin } from './api'
import type { AdminSearch } from './types'
import { useAdminFilters } from './useAdminFilters'
import AdminNav from './components/AdminNav.vue'
import BrandSpark from '../components/BrandSpark.vue'
import { useAdminMe } from './components/useAdminMe'

/**
 * Admin qobig'i (spec §4.5): chap menyu (232px, 64px gacha yig'iladi; ≥1120 da chetidan
 * tortib 200-360px oralig'ida kengaytiriladi), kontent (max 1280, chetlari §1.5
 * bo'yicha), ⌘K buyruqlar palitrasi. Telefonda menyu yuqori paneldagi tugmadan
 * ochiladigan pastki sheet.
 *
 * Tokenlar va asos uslublari global (main.ts) - bu yerda import qilinmaydi.
 */
const { t, locale } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { withFilters } = useAdminFilters()
const { newReports } = useAdminMe({ poll: true })
const palette = useCommandPalette()

const isPhone = useIsPhone()
const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1119.98px)')
const isDesktop = useMediaQuery('(min-width: 1120px)')

/* ---- yig'ilgan menyu: tanlov shu brauzerda eslab qolinadi ---- */

const NAV_KEY = 'venera_admin_nav'
function readCollapsed(): boolean | null {
  try {
    const v = localStorage.getItem(NAV_KEY)
    return v === 'collapsed' ? true : v === 'expanded' ? false : null
  } catch {
    return null
  }
}
const stored = ref<boolean | null>(readCollapsed())
// Planshetda (768-1119) standart - yig'ilgan: kontentga joy kerak.
const collapsed = computed(() => stored.value ?? isTablet.value)
function setCollapsed(value: boolean) {
  stored.value = value
  try {
    localStorage.setItem(NAV_KEY, value ? 'collapsed' : 'expanded')
  } catch {
    /* saqlanmasa ham ishlayveradi */
  }
}
function toggleCollapsed() {
  setCollapsed(!collapsed.value)
}

/* ---- menyu kengligi: chetidan tortiladi (faqat ≥1120), eslab qolinadi ----
   200-360, standart 232 (tokens.css --admin-nav-w), ustun 64 (--admin-rail-w).
   Planshetda tortib bo'lmaydi va menyu standart kenglikda ochiladi. */
const navId = useId('admin-nav')
const nav = useResizablePanel({
  storageKey: 'venera_admin_nav_w',
  min: 200,
  max: 360,
  initial: 232,
  rail: 64,
  collapsed: () => collapsed.value,
  setCollapsed,
  enabled: () => isDesktop.value,
})

/* ---- telefon menyusi ---- */

const navOpen = ref(false)
watch(isPhone, (phone) => {
  if (!phone) navOpen.value = false
})

/* ---- bo'lim almashganda: tepaga va fokus kontentga (ekran o'quvchi yangi sahifani eshitsin) ---- */

const main = ref<HTMLElement | null>(null)
const section = (p: string) => p.split('/').slice(0, 3).join('/')
watch(
  () => route.path,
  async (path, prev) => {
    navOpen.value = false
    // Bir bo'lim ichidagi o'tish (ro'yxat -> varaq, `reports/:id`) - fokus o'z joyida qolsin.
    if (prev === undefined || section(path) === section(prev)) return
    await nextTick()
    main.value?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  },
)

function skipToMain() {
  main.value?.focus()
}

/* ---- ⌘K: sahifalar va qidiruv ---- */

const PAGES = [
  { key: 'overview', path: '/admin', icon: LayoutDashboard },
  { key: 'conversations', path: '/admin/conversations', icon: MessagesSquare },
  { key: 'reports', path: '/admin/reports', icon: Flag },
  { key: 'users', path: '/admin/users', icon: Users },
  { key: 'usage', path: '/admin/usage', icon: Activity },
  { key: 'system', path: '/admin/system', icon: Server },
] as const

palette.registerCommands(
  () => t('admin.palette.pages'),
  (): CommandItem[] => [
    ...PAGES.map((p) => ({
      id: `admin-page:${p.key}`,
      label: t(`admin.nav.${p.key}`),
      sub: t(`admin.page.${p.key}.subtitle`),
      icon: p.icon,
      to: p.path,
      // Joriy filtr (davr, kanal) bilan - menyudagi havolalar kabi davr saqlansin.
      run: () => void router.push(withFilters(p.path)),
    })),
    { id: 'admin-page:chat', label: t('admin.nav.backToChat'), icon: ArrowLeft, to: '/' },
  ],
  { id: 'admin-pages', priority: 10 },
)

// Topilgan band ham joriy davr va kanal bilan ochilsin (sahifalar guruhidagi kabi):
// aks holda odam varag'i yoki xabarlar qutisi standart 30 kunga qaytib qolardi.
// `to` - faqat yangi varaq va "so'nggi" ro'yxati uchun.
function filtered(path: string): Pick<CommandItem, 'to' | 'run'> {
  return { to: path, run: () => void router.push(withFilters(path)) }
}

function toGroups(found: AdminSearch): CommandGroup[] {
  const groups: CommandGroup[] = []
  if (found.users.length) {
    groups.push({
      group: t('admin.palette.users'),
      items: found.users.map((u) => ({
        id: `admin-user:${u.actorId}`,
        label: u.name || u.login || u.email || t('admin.common.unknownUser'),
        sub: u.login ?? u.email ?? undefined,
        icon: Users,
        ...filtered(`/admin/users/${u.actorId}`),
      })),
    })
  }
  if (found.turns.length) {
    groups.push({
      group: t('admin.palette.turns'),
      items: found.turns.map((turn) => ({
        id: `admin-turn:${turn.id}`,
        label: turn.question || turn.id,
        sub: [turn.userName, turn.startedAt ? fmtRelative(turn.startedAt, locale.value) : null]
          .filter(Boolean)
          .join(' · '),
        icon: MessagesSquare,
        ...filtered(`/admin/turns/${encodeURIComponent(turn.id)}`),
      })),
    })
  }
  if (found.reports.length) {
    groups.push({
      group: t('admin.palette.reports'),
      items: found.reports.map((r) => ({
        id: `admin-report:${r.id}`,
        label: r.commentPreview || t(`admin.reason.${r.reason ?? 'none'}`),
        sub: [r.userName, t(`admin.reportStatus.${r.status}`)].filter(Boolean).join(' · '),
        icon: Flag,
        ...filtered(`/admin/reports/${encodeURIComponent(r.id)}`),
      })),
    })
  }
  return groups
}

// Serverdagi qidiruv: bitta harf - shovqin, ikki harfdan boshlab. Xato (tarmoq, bekor
// qilingan so'rov) - shunchaki natija yo'q; sahifalar guruhi baribir ko'rinadi.
palette.register(
  async (query, signal) => {
    const q = query.trim()
    if (q.length < 2) return null
    try {
      const groups = toGroups(await searchAdmin(q, signal))
      return groups.length ? groups : null
    } catch {
      return null
    }
  },
  { id: 'admin-search' },
)
</script>

<template>
  <div class="admin">
    <a class="admin__skip" href="#admin-main" @click.prevent="skipToMain">{{ t('admin.shell.skip') }}</a>

    <!-- telefon: menyu tugmasi, brend, qidiruv -->
    <header v-if="isPhone" class="admin__bar">
      <VIconButton :icon="Menu" :label="t('admin.nav.menu')" :dot="newReports > 0" @click="navOpen = true" />
      <span class="admin__bar-brand">
        <span class="admin__spark" aria-hidden="true"><BrandSpark :size="16" /></span>
        <span class="admin__word">Venera</span>
        <span class="admin__badge">{{ t('admin.title') }}</span>
      </span>
      <VIconButton :icon="Search" :label="t('admin.nav.search')" @click="palette.open()" />
    </header>

    <aside
      v-else
      :id="navId"
      class="admin__side"
      :class="{ 'is-resizing': nav.dragging.value }"
      :style="nav.style.value"
    >
      <div class="admin__side-inner">
        <AdminNav :collapsed="nav.folded.value" @toggle="toggleCollapsed" />
        <!-- Yopishqoq ichki qism ichida: tutqich aylantirganda ham ekran bo'yi turadi. -->
        <VResizeHandle v-if="nav.enabled.value" :panel="nav" :controls="navId" />
      </div>
    </aside>

    <VSheet v-if="isPhone" v-model:open="navOpen" side="left" :aria-label="t('admin.nav.menu')">
      <AdminNav variant="sheet" @navigate="navOpen = false" />
    </VSheet>

    <main id="admin-main" ref="main" class="admin__main" tabindex="-1">
      <div class="admin__content">
        <RouterView />
      </div>
    </main>

    <VCommandPalette :placeholder="t('admin.palette.placeholder')" />
  </div>
</template>

<style scoped>
.admin {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  min-height: 100dvh;
  background: var(--bg);
  color: var(--text);
}

/* Klaviatura uchun "asosiy qismga o'tish" - faqat fokusda ko'rinadi. */
.admin__skip {
  position: fixed;
  top: var(--s-2);
  left: var(--s-2);
  z-index: var(--z-toast);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-sm);
  background: var(--ink);
  color: var(--on-ink);
  font-size: var(--fs-body-sm);
  font-weight: 500;
  transform: translateY(calc(-100% - var(--s-4)));
}
.admin__skip:focus-visible {
  transform: none;
}

/* ---- chap panel ----
   Ustun (fon + chiziq) grid qatori bo'yi - uzun sahifada ham pastgacha davom etadi;
   ichidagi menyu esa yopishqoq (sticky) va ekran balandligida: aylantirganda joyida qoladi.
   Ilgari ustunning o'zi 100dvh edi - sahifa uzun bo'lsa fon ekran tagida uzilib qolardi.
   Kenglik --panel-w dan (useResizablePanel): ochish/yig'ish silliq, tortish paytida esa
   o'tish o'chadi - panel kursorga yopishib yursin. Kesish bu yerda EMAS (AdminNav o'zi
   kesadi): `overflow` yopishqoq ichki qismni buzardi va tutqichni kesib qo'yardi. */
.admin__side {
  z-index: var(--z-sidebar);
  width: var(--panel-w, var(--admin-nav-w));
  border-right: 1px solid var(--line);
  background: var(--bg-subtle);
  transition: width var(--dur-panel) var(--ease-out);
}
.admin__side.is-resizing {
  transition: none;
}
.admin__side-inner {
  position: sticky;
  top: 0;
  height: 100vh;
  height: 100dvh;
}

/* ---- kontent ---- */
.admin__main {
  min-width: 0;
  padding: var(--s-10) var(--gutter) var(--s-16);
}
.admin__main:focus {
  outline: none;
}
.admin__content {
  width: 100%;
  max-width: var(--admin-col);
  margin-inline: auto;
}

/* ---- telefon ---- */
.admin__bar {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  gap: var(--s-2);
  height: 56px;
  padding: 0 var(--s-2);
  border-bottom: 1px solid var(--line);
  background: var(--bg);
}
.admin__bar-brand {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}
.admin__spark {
  display: inline-flex;
  color: var(--brand);
}
.admin__word {
  font-size: var(--fs-body);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.admin__badge {
  padding: 1px var(--s-1_5);
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}

@media (max-width: 767.98px) {
  .admin {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto 1fr;
  }
  .admin__main {
    padding-top: var(--s-6);
    padding-bottom: calc(var(--s-12) + env(safe-area-inset-bottom, 0px));
  }
}
</style>
