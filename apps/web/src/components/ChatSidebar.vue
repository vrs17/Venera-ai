<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { PanelLeftClose, PanelLeftOpen, Search, SquarePen, X } from 'lucide-vue-next'
import type { AuthUser } from '../types'
import type { ThemePreference } from '../theme'
import VIconButton from '../ui/VIconButton.vue'
import VKbd from '../ui/VKbd.vue'
import VResizeHandle from '../ui/VResizeHandle.vue'
import VSearchField from '../ui/VSearchField.vue'
import VTooltip from '../ui/VTooltip.vue'
import { useId } from '../ui/composables/useId'
import type { ResizablePanel } from '../ui/composables/useResizablePanel'
import BrandSpark from './BrandSpark.vue'
import ChatHistory from './ChatHistory.vue'
import IdentityBar from './IdentityBar.vue'

/**
 * Chap panel - faqat navigatsiya: logotip, "Yangi suhbat", qidiruv, tarix va pastda
 * hisob (sozlamalar hisob menyusida). Ikki rejim:
 *   inline (≥1120)   - sahifada; kenglik `resize` dan (tortib o'zgartiriladi, eslab
 *                      qolinadi), yig'ilsa 56px belgilar ustuni;
 *   drawer (<1120)   - ChatView uni VSheet ichida ochadi (fokus tuzog'i, Esc, parda).
 * Yangi suhbat va suhbat ochish drawer'ni yopadi.
 *
 * Ochiq panel va ustun - BITTA <aside>: kenglik silliq o'zgaradi, belgilar (yangi
 * suhbat, qidiruv, avatar) ikkala holatda bir xil x da turadi, yozuvlar esa so'nib,
 * torayayotgan panel tomonidan kesiladi. Ilgari ikki xil <aside> almashardi - panel
 * "sakrardi" va bosilgan tugma DOM'dan chiqib, fokus <body> ga tushardi.
 */
const props = withDefaults(
  defineProps<{
    user: AuthUser | null
    mode?: 'inline' | 'drawer'
    /** Faqat inline: 56px belgilar ustuni (tortish paytida - yig'ilish chegarasidan o'tilgan). */
    collapsed?: boolean
    /** Faqat inline: kenglik boshqaruvi (ChatView'dagi `useResizablePanel`). */
    resize?: ResizablePanel | null
    theme: ThemePreference
    wake: boolean
    wakeSupported: boolean
    wakeDistorted?: boolean
    wakeBlocked?: boolean
    isAdmin?: boolean
  }>(),
  { mode: 'inline', collapsed: false, resize: null, wakeDistorted: false, wakeBlocked: false, isAdmin: false },
)
const emit = defineEmits<{
  toggleCollapse: []
  newChat: []
  /** Yon paneldagi suhbat tanlandi - ChatView uni ochadi. */
  openChat: [id: string]
  close: []
  setTheme: [theme: ThemePreference]
  toggleWake: []
  openDesktop: []
  openMemory: []
  logout: []
}>()

const { t } = useI18n({ useScope: 'global' })
const query = ref('')
const search = ref<InstanceType<typeof VSearchField> | null>(null)
const aside = ref<HTMLElement | null>(null)
const toggle = ref<InstanceType<typeof VIconButton> | null>(null)
const panelId = useId('sb')

const inline = computed(() => props.mode === 'inline')
const folded = computed(() => inline.value && props.collapsed)

// Kenglik `resize` dan; u berilmasa (masalan, katalogda) - tokenlardagi qiymatlar.
const panelStyle = computed(() => {
  if (!inline.value) return undefined
  return (
    props.resize?.style.value ?? {
      '--panel-w': props.collapsed ? 'var(--rail-w)' : 'var(--sidebar-w)',
      '--panel-content-w': 'var(--sidebar-w)',
    }
  )
})

function onNewChat() {
  emit('newChat')
  emit('close')
}
function onOpenChat(id: string) {
  emit('openChat', id)
  emit('close')
}

// Yig'ilganda tarix va qidiruv `inert` bo'ladi. Fokus ularning ichida bo'lsa (masalan,
// tarix qatorida Esc bosildi), u <body> ga tushib qolardi - DOM yangilanishidan OLDIN
// (watch standart 'pre') joyida qoladigan yig'ish tugmasiga o'tkaziladi.
watch(folded, (now) => {
  if (!now) return
  const active = document.activeElement
  if (!(active instanceof HTMLElement) || !aside.value?.contains(active) || !active.closest('.sb__block')) return
  ;(toggle.value?.$el as HTMLElement | undefined)?.focus({ preventScroll: true })
})

// Yig'iq ustundagi lupa: panel ochiladi va fokus darhol qidiruvga. `preventScroll` -
// maydon hali ochilayotgan panelda kesilgan holda turibdi, brauzer uni "ko'rsataman"
// deb panel ichini yon tomonga surib qo'ymasin.
async function expandToSearch() {
  emit('toggleCollapse')
  await nextTick()
  search.value?.focus({ preventScroll: true })
}
</script>

<template>
  <aside
    :id="panelId"
    ref="aside"
    class="sb"
    :class="{
      'is-inline': inline,
      'is-drawer': !inline,
      'is-folded': folded,
      'is-resizing': !!resize?.dragging.value,
    }"
    :style="panelStyle"
    :aria-label="t('chat.navigation')"
  >
    <div class="sb__clip">
      <div class="sb__top">
        <span class="sb__brand sb__block">
          <span class="sb__spark" aria-hidden="true"><BrandSpark :size="16" /></span>
          <span class="sb__word">Barno</span>
        </span>
        <!-- Bitta tugma ikkala holatda: panel o'ng chetiga yopishgan, yig'ilganda chet
             bilan birga ustun markaziga suriladi. Element almashmaydi - fokus saqlanadi. -->
        <VIconButton
          v-if="inline"
          ref="toggle"
          class="sb__toggle"
          :icon="folded ? PanelLeftOpen : PanelLeftClose"
          :label="folded ? t('chat.expand') : t('chat.collapse')"
          :tooltip-placement="folded ? 'right' : 'bottom'"
          @click="emit('toggleCollapse')"
        />
        <VIconButton
          v-else
          class="sb__toggle"
          size="sm"
          :icon="X"
          :label="t('close')"
          tooltip-placement="bottom"
          @click="emit('close')"
        />
      </div>

      <div class="sb__actions">
        <VTooltip
          :text="t('newChat')"
          shortcut="mod+shift+o"
          placement="right"
          :disabled="!folded"
          :describe="false"
        >
          <button type="button" class="sb__new" aria-keyshortcuts="Control+Shift+O Meta+Shift+O" @click="onNewChat">
            <span class="sb__row">
              <span class="sb__ico"><SquarePen :size="18" :stroke-width="1.75" aria-hidden="true" /></span>
              <span class="sb__label sb__new-label">{{ t('newChat') }}</span>
              <VKbd class="sb__kbd" keys="mod+shift+o" size="sm" aria-hidden="true" />
            </span>
          </button>
        </VTooltip>

        <!-- Qidiruv: ochiq panelda maydon, ustunda - aynan maydondagi lupa o'rnida
             turgan tugma (ikkalasi bir joyda almashinadi, belgi siljimaydi). -->
        <div class="sb__search">
          <div class="sb__search-field sb__block" :inert="folded">
            <VSearchField
              ref="search"
              v-model="query"
              size="sm"
              :placeholder="t('ui.search')"
              :aria-label="t('chat.search')"
            />
          </div>
          <span v-if="inline" class="sb__search-rail sb__rail-only" :inert="!folded">
            <VIconButton
              size="sm"
              :icon="Search"
              :label="t('chat.search')"
              tooltip-placement="right"
              @click="expandToSearch"
            />
          </span>
        </div>
      </div>

      <div class="sb__hist sb__block" :inert="folded">
        <ChatHistory :query="query" @open="onOpenChat" @removed-active="emit('newChat')" />
      </div>

      <div class="sb__foot">
        <IdentityBar
          :compact="folded"
          :user="user"
          :theme="theme"
          :wake="wake"
          :wake-supported="wakeSupported"
          :wake-distorted="wakeDistorted"
          :wake-blocked="wakeBlocked"
          :is-admin="isAdmin"
          @set-theme="emit('setTheme', $event)"
          @toggle-wake="emit('toggleWake')"
          @open-desktop="emit('openDesktop')"
          @open-memory="emit('openMemory')"
          @logout="emit('logout')"
        />
      </div>
    </div>

    <!-- Kesuvchi o'ramadan TASHQARIDA: tutqich chegaraning ustida, yarmi panel tashqarisida. -->
    <VResizeHandle v-if="inline && resize?.enabled.value" :panel="resize" :controls="panelId" />
  </aside>
</template>

<style scoped>
.sb {
  position: relative;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  height: 100%;
  min-height: 0;
  background: var(--bg-subtle);
  border-right: 1px solid var(--line);
}
/* Sahifadagi panel: kenglik --panel-w dan (yig'iq bo'lsa - ustun), ochish/yig'ish silliq.
   Tortish paytida o'tish o'chadi - panel kursorga yopishib yursin, orqada qolmasin.
   --sb-inner-w - ichki kenglik OCHIQ panel bo'yicha (1px - o'ng chegara), --sb-row-w -
   bitta qator mazmuni. Ikkalasi yig'ilish animatsiyasida o'zgarmaydi: yozuvlar qayta
   joylashmaydi, faqat kesiladi. */
.sb.is-inline {
  --sb-inner-w: calc(var(--panel-content-w) - 1px);
  --sb-row-w: calc(var(--sb-inner-w) - 2 * var(--s-2));
  width: var(--panel-w);
  transition: width var(--dur-panel) var(--ease-out);
}
.sb.is-inline.is-resizing {
  transition: none;
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
/* Kesish shu ichki o'ramada: tutqich (VResizeHandle) panel chetidan tashqariga chiqib
   turadi va kesilmasligi kerak. `clip` aylantiriladigan quti emas - kesilgan maydonga
   fokus berilganda panel ichi yon tomonga surilib qolmaydi (`hidden` - eski brauzerlar). */
.sb__clip {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  overflow: clip;
}

.sb__top {
  position: relative;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  height: 56px;
  /* Uchqun markazi = belgilar ustuni markazi (28px): pastdagi belgilar bilan bir chiziqda. */
  padding: 0 var(--s-5);
}
.sb__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--s-3);
  white-space: nowrap;
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
/* O'ng chetga yopishgan: yig'ilganda chet bilan birga suriladi va boshqa belgilar bilan
   bir ustunda (markazi 28px) to'xtaydi. -1px - o'ng chegara (u kesilgan qutidan tashqarida). */
.sb__toggle {
  position: absolute;
  top: calc((var(--rail-w) - 36px) / 2);
  right: calc((var(--rail-w) - 36px) / 2 - 1px);
}
.sb.is-drawer .sb__toggle {
  top: var(--s-3);
  right: var(--s-3);
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
  width: 100%;
  height: 36px;
  padding: 0;
  overflow: hidden;
  border-radius: var(--r-sm);
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 500;
  text-align: left;
  transition: background-color var(--dur-1) var(--ease-out);
}
/* Tugma panel bilan torayadi (foni ustunda 40px katak bo'lib qoladi), ichidagi qator esa
   ochiq panel kengligida - belgi joyida, yozuv kesiladi. */
.sb__row {
  display: flex;
  align-items: center;
  flex: none;
  width: var(--sb-row-w, 100%);
  height: 100%;
  padding-right: var(--s-2);
}
/* Belgi katagi = ustun kengligi minus chetlar: markazi har doim 28px da. */
.sb__ico {
  display: grid;
  place-items: center;
  flex: none;
  width: calc(var(--rail-w) - 2 * var(--s-2));
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
  flex: none;
  margin-left: var(--s-2);
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

.sb__search {
  position: relative;
}
.sb__search-field {
  width: var(--sb-row-w, 100%);
}
/* Maydondagi lupa - belgilar ustunida: 8 + 1 (chegara) + 10 (ichki chet) + 9 = 28px.
   VInput uni 2px chapga suradi (`margin-left: -2px`) - bu yerda yo'q, aks holda ustun
   tugmasiga almashganda lupa siljib ko'rinardi. Ustun tugmasi (sm, 32px): 8 + 4 + 16. */
.sb__search-field :deep(.v-input__lead) {
  margin-left: 0;
}
.sb__search-rail {
  position: absolute;
  top: 50%;
  left: var(--s-1);
  translate: 0 -50%;
}

.sb__hist {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  width: var(--sb-inner-w, 100%);
}

.sb__foot {
  flex-shrink: 0;
  padding: var(--s-2);
  border-top: 1px solid var(--line);
  transition: border-color var(--dur-1) var(--ease-out);
}

/* ---- yig'ish / ochish ----
   Yozuvlar tez (--dur-1) so'nadi: kenglik animatsiyasi (--dur-panel) tugashini kutmaydi.
   `sb__block` - butun bo'lak (logotip, qidiruv maydoni, tarix): so'ngach
   `visibility: hidden` - Tab va ekran o'quvchi uni ko'rmaydi (shablonda yana `inert`).
   `sb__label` - tugma ichidagi yozuv: faqat shaffof, chunki u tugmaning NOMI va
   ustunda ham o'qilishi kerak. `sb__rail-only` - aksincha, faqat ustunda. */
.sb__block,
.sb.is-folded .sb__rail-only {
  opacity: 1;
  visibility: visible;
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s;
}
.sb.is-folded .sb__block,
.sb__rail-only {
  opacity: 0;
  visibility: hidden;
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s linear var(--dur-1);
}
.sb__label {
  transition: opacity var(--dur-1) var(--ease-out);
}
.sb.is-folded .sb__label,
.sb.is-folded .sb__new .sb__kbd {
  opacity: 0;
}
.sb.is-folded .sb__foot {
  border-top-color: transparent;
}
</style>
