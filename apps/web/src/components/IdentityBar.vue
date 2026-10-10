<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, ChevronsUpDown, Ear, Globe, LogOut, Monitor, MonitorDown, Moon, Shield, Sun, SunMoon } from 'lucide-vue-next'
import type { AuthUser } from '../types'
import type { ThemePreference } from '../theme'
import { LOCALES, setLocale } from '../i18n'
import type { Locale } from '../i18n'
import VAvatar from '../ui/VAvatar.vue'
import VMenu from '../ui/VMenu.vue'
import VMenuItem from '../ui/VMenuItem.vue'
import VTooltip from '../ui/VTooltip.vue'

/**
 * Hisob va sozlamalar - yon panel pastidagi YAGONA kirish nuqtasi (yig'iq panelda -
 * avatar). Menyu: kim kirgan (faqat o'qish - kimlik sessiyadan, bu yerda hech narsa
 * tahrirlanmaydi), mavzu va til (segmentli tanlov), "Xotira" (Barno nimani eslab qolgani,
 * 2026-10-10), "Salom Venera",
 * admin panel (faqat ADMIN), desktop ilova, chiqish.
 *
 * VMenu ustida: klaviatura (↑ ↓, harf, Enter), Esc - preventDefault bilan (ChatView
 * yon panelni yig'ib yubormaydi), fokus trigger'ga qaytadi. Mavzu/til/kalitlar
 * tanlanganda menyu ochiq qoladi - natija shu yerning o'zida ko'rinsin.
 *
 * Trigger ikkala holatda BITTA tugma: panel yig'ilayotganda avatar joyida qoladi,
 * ism va belgi so'nadi va kesiladi (ilgari ikki xil tugma almashardi - panel animatsiyasi
 * o'rtasida avatar sakrardi, fokusdagi tugma esa DOM'dan chiqib ketardi). Qator
 * kengligi ota beradigan `--sb-row-w` dan (ochiq panel bo'yicha) - ism qayta
 * qisqarmaydi; berilmasa (drawer) - tugma kengligi.
 */
const props = withDefaults(
  defineProps<{
    user: AuthUser | null
    /** Yig'iq panel: faqat avatar. */
    compact?: boolean
    /** Saqlangan tanlov (yorug' / qorong'i / tizim), yechilgan mavzu emas. */
    theme: ThemePreference
    wake: boolean
    wakeSupported: boolean
    wakeDistorted?: boolean
    wakeBlocked?: boolean
    isAdmin?: boolean
  }>(),
  { compact: false, wakeDistorted: false, wakeBlocked: false, isAdmin: false },
)
const emit = defineEmits<{
  setTheme: [theme: ThemePreference]
  toggleWake: []
  openDesktop: []
  openMemory: []
  logout: []
}>()

const { t, locale } = useI18n({ useScope: 'global' })

const name = computed(() => props.user?.fullName?.trim() || props.user?.email || '—')

// 'system' - OS mavzusiga ergashadi (theme.ts OS o'zgarishini o'zi kuzatadi).
const themeOptions = computed<{ value: ThemePreference; label: string; icon: Component }[]>(() => [
  { value: 'light', label: t('ui.light'), icon: Sun },
  { value: 'dark', label: t('ui.dark'), icon: Moon },
  { value: 'system', label: t('ui.system'), icon: Monitor },
])

/** Til segmentidagi qisqa yozuv; to'liq nom - tooltip va ekran o'quvchida. */
const SHORT: Record<Locale, string> = { uz: 'Oʻz', 'uz-Cyrl': 'Ўз', ru: 'Ру', en: 'En' }
</script>

<template>
  <VMenu
    :placement="compact ? 'right-end' : 'top-start'"
    :min-width="compact ? 264 : 248"
    :aria-label="t('chat.account')"
  >
    <template #trigger>
      <!-- VPopover `data-v-contents` o'ramalaridan o'tib, tugmaning o'zini trigger qiladi. -->
      <VTooltip :text="name" placement="right" :disabled="!compact" :describe="false">
        <button type="button" class="acct" :class="{ 'is-compact': compact }" :aria-label="compact ? name : undefined">
          <span class="acct__row">
            <VAvatar :name="name" :size="28" />
            <span class="acct__name">{{ name }}</span>
            <ChevronsUpDown class="acct__chev" :size="16" :stroke-width="1.75" aria-hidden="true" />
          </span>
        </button>
      </VTooltip>
    </template>

    <div class="acct-head" role="presentation">
      <VAvatar :name="name" :size="32" />
      <div class="acct-head__text">
        <p class="acct-head__name">{{ name }}</p>
        <p v-if="user?.email && user.email !== name" class="acct-head__sub">{{ user.email }}</p>
        <p v-if="user?.department" class="acct-head__sub">{{ user.department }}</p>
      </div>
    </div>
    <VMenuItem kind="separator" />

    <div class="acct-seg-row" role="presentation">
      <span class="acct-seg-row__label">
        <SunMoon :size="16" :stroke-width="1.75" aria-hidden="true" />{{ t('ui.theme') }}
      </span>
      <div class="acct-seg" role="group" :aria-label="t('ui.theme')">
        <VTooltip v-for="opt in themeOptions" :key="opt.value" :text="opt.label" :describe="false">
          <VMenuItem
            kind="radio"
            :icon="opt.icon"
            :checked="theme === opt.value"
            :text-value="opt.label"
            :close-on-select="false"
            @select="emit('setTheme', opt.value)"
          >
            <span class="sr-only">{{ opt.label }}</span>
          </VMenuItem>
        </VTooltip>
      </div>
    </div>
    <div class="acct-seg-row" role="presentation">
      <span class="acct-seg-row__label">
        <Globe :size="16" :stroke-width="1.75" aria-hidden="true" />{{ t('ui.language') }}
      </span>
      <div class="acct-seg" role="group" :aria-label="t('ui.language')">
        <VTooltip v-for="l in LOCALES" :key="l.code" :text="l.label" :describe="false">
          <VMenuItem
            kind="radio"
            :checked="locale === l.code"
            :text-value="l.label"
            :lang="l.htmlLang"
            :close-on-select="false"
            @select="setLocale(l.code)"
          >
            <span aria-hidden="true">{{ SHORT[l.code] }}</span>
            <span class="sr-only">{{ l.label }}</span>
          </VMenuItem>
        </VTooltip>
      </div>
    </div>
    <VMenuItem kind="separator" />

    <!-- Xotira - oyna ChatView'da (menyu yopiladi, oyna qoladi). -->
    <VMenuItem :icon="Brain" @select="emit('openMemory')">{{ t('assistant.memory.open') }}</VMenuItem>
    <!-- "Salom Venera" faqat uyg'otish so'zi bor tillarda: boshqasida kalit hech narsa qilmasdi. -->
    <VMenuItem v-if="wakeSupported" kind="checkbox" :icon="Ear" :checked="wake" @select="emit('toggleWake')">
      {{ t('wakeWord') }}
    </VMenuItem>
    <!-- Mikrofon muammosini faqat foydalanuvchi tuzata oladi - jim turmaymiz. -->
    <p v-if="wakeSupported && wake && wakeBlocked" class="acct-note" role="status">{{ t('chat.micBlocked') }}</p>
    <p v-else-if="wakeSupported && wake && wakeDistorted" class="acct-note" role="status">{{ t('wakeWordDistorted') }}</p>
    <VMenuItem kind="separator" />

    <VMenuItem v-if="isAdmin" :icon="Shield" to="/admin">{{ t('chat.adminPanel') }}</VMenuItem>
    <VMenuItem :icon="MonitorDown" @select="emit('openDesktop')">{{ t('chat.desktopApp') }}</VMenuItem>
    <VMenuItem kind="separator" />
    <VMenuItem :icon="LogOut" @select="emit('logout')">{{ t('logout') }}</VMenuItem>
  </VMenu>
</template>

<style scoped>
.acct {
  display: flex;
  align-items: center;
  width: 100%;
  height: 48px;
  padding: 0;
  overflow: hidden;
  border-radius: var(--r-md);
  text-align: left;
  transition: background-color var(--dur-1) var(--ease-out);
}
/* Avatar markazi = belgilar ustuni markazi (8 + 6 + 14 = 28px): yig'iq ustunda ham shu joyda. */
.acct__row {
  display: flex;
  align-items: center;
  gap: var(--s-1_5);
  flex: none;
  width: var(--sb-row-w, 100%);
  height: 100%;
  padding: 0 var(--s-2) 0 var(--s-1_5);
}
@media (hover: hover) {
  .acct:hover {
    background: var(--fill);
  }
}
.acct[aria-expanded='true'] {
  background: var(--fill);
}
.acct__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.acct__chev {
  flex-shrink: 0;
  color: var(--text-3);
}
.acct__name,
.acct__chev {
  transition: opacity var(--dur-1) var(--ease-out);
}
/* Yig'iq ustun: faqat avatar. Ism faqat shaffof (yashirilmaydi) - nom aria-label'da ham bor. */
.acct.is-compact .acct__name,
.acct.is-compact .acct__chev {
  opacity: 0;
}

.acct-head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-2) var(--s-2) var(--s-2);
}
.acct-head__text {
  min-width: 0;
}
.acct-head__name {
  overflow: hidden;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.acct-head__sub {
  overflow: hidden;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Mavzu / til: menyu ichidagi segmentli tanlov. Har segment - haqiqiy menuitemradio
   (↑ ↓ bilan yetiladi), ko'rinishi - VSegmented kabi: tanlangani siyohda. */
.acct-seg-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  min-height: 36px;
  padding: var(--s-0_5) 0 var(--s-0_5) var(--s-2);
}
.acct-seg-row__label {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  white-space: nowrap;
}
.acct-seg-row__label svg {
  flex-shrink: 0;
  color: var(--text-2);
}
.acct-seg {
  display: inline-flex;
  flex-shrink: 0;
  gap: 2px;
  padding: 2px;
  border-radius: var(--r-sm);
  background: var(--fill);
}
.acct-seg :deep(.v-menu-item.v-menu-item) {
  justify-content: center;
  gap: 0;
  min-width: 32px;
  min-height: 28px;
  height: 28px;
  padding: 0 var(--s-2);
  border-radius: var(--r-xs);
  color: var(--text-2);
  font-size: var(--fs-caption);
  font-weight: 500;
}
.acct-seg :deep(.v-menu-item .v-menu-item__label) {
  flex: 0 0 auto;
}
.acct-seg :deep(.v-menu-item .v-menu-item__check) {
  display: none;
}
.acct-seg :deep(.v-menu-item .v-menu-item__icon) {
  color: inherit;
}
.acct-seg :deep(.v-menu-item.v-menu-item:focus) {
  background: var(--fill-hover);
  color: var(--text);
}
.acct-seg :deep(.v-menu-item.v-menu-item[aria-checked='true']) {
  background: var(--ink);
  color: var(--on-ink);
}
.acct-seg :deep(.v-menu-item.v-menu-item[aria-checked='true']:focus-visible) {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}

.acct-note {
  margin: 0 var(--s-2) var(--s-1);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-sm);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  max-width: 280px;
}
</style>
