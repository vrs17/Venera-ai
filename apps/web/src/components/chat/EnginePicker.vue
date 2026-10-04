<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VMenu from '../../ui/VMenu.vue'
import VMenuItem from '../../ui/VMenuItem.vue'
import VSheet from '../../ui/VSheet.vue'
import { useIsPhone } from '../../ui/composables/useMediaQuery'
import { useEngines } from '../../composables/useEngines'

/**
 * Kompozerdagi "v2 ▾" - yordamchi versiyasini tanlash. FAQAT odamga admin bir nechta
 * versiya bergan bo'lsa chiziladi (`useEngines().selectable`); qolganlar uchun hech narsa
 * yo'q - tanlab bo'lmaydigan narsa ko'rsatilmaydi.
 *
 * Kompakt tabletka: yonidagi "Pro" kalitidek jim, matnda faqat versiya kaliti ("v2") -
 * nomi va tavsifi menyuda. Ikki ko'rinish, bitta tanlov:
 *   - sichqonchali ekran: VMenu (klaviatura, Esc, fokus qaytishi - hammasi VMenu'da);
 *   - telefon: pastki sheet - katta qatorlar barmoq ostida, tavsif to'liq o'qiladi
 *     (menyu popover'i 360px ekranda tor va klaviatura ustida qolib ketardi).
 *
 * Tanlov darhol saqlanadi (odamga bog'langan) va KEYINGI savoldan ishlaydi; "Pro"
 * kaliti tanlovga ergashadi (ChatView byudjetni shu versiya bo'yicha qayta so'raydi).
 */
const { t, te } = useI18n({ useScope: 'global' })
const engines = useEngines()
const isPhone = useIsPhone()

const sheetOpen = ref(false)
const announcement = ref('')

const current = computed(() => engines.selected.value ?? '')

/** "Barqaror" / "Yangi"; noma'lum versiya - nomsiz (faqat kaliti ko'rinadi). */
function nameOf(id: string): string {
  const key = `chat.engines.${id}`
  return te(key) ? t(key) : ''
}
function descOf(id: string): string {
  const key = `chat.engines.${id}Desc`
  return te(key) ? t(key) : ''
}
const pillLabel = computed(() => {
  const name = nameOf(current.value)
  return t('chat.engines.pill', { v: name ? `${current.value} · ${name}` : current.value })
})

function choose(id: string) {
  if (id === current.value) return
  engines.select(id)
  // Ekran o'quvchiga: tugma matni o'zgardi, lekin fokus menyudan qaytayotganda buni
  // aytmaydi. Bo'shatib qayta yoziladi - bir xil gap ketma-ket ham o'qilsin.
  const name = nameOf(id)
  announcement.value = ''
  void nextTick(() => {
    announcement.value = t('chat.engines.switched', { v: name ? `${id} · ${name}` : id })
  })
}

function chooseFromSheet(id: string) {
  choose(id)
  sheetOpen.value = false
}
</script>

<template>
  <template v-if="engines.selectable.value">
    <!-- Telefon: tugma sheet'ni ochadi. -->
    <button
      v-if="isPhone"
      type="button"
      class="ep__pill"
      :class="{ 'is-open': sheetOpen }"
      aria-haspopup="dialog"
      :aria-expanded="sheetOpen ? 'true' : 'false'"
      :aria-label="pillLabel"
      @click="sheetOpen = true"
    >
      <span class="ep__pill-text">{{ current }}</span>
      <ChevronDown class="ep__chev" :size="14" :stroke-width="2" aria-hidden="true" />
    </button>

    <VMenu v-else placement="top-start" :offset="8" :min-width="300" :aria-label="t('chat.engines.label')">
      <template #trigger="{ open }">
        <button type="button" class="ep__pill" :class="{ 'is-open': open }" :aria-label="pillLabel">
          <span class="ep__pill-text">{{ current }}</span>
          <ChevronDown class="ep__chev" :size="14" :stroke-width="2" aria-hidden="true" />
        </button>
      </template>
      <VMenuItem kind="label">{{ t('chat.engines.label') }}</VMenuItem>
      <VMenuItem
        v-for="e in engines.options.value"
        :key="e.id"
        kind="radio"
        :checked="e.id === current"
        :text-value="`${e.id} ${nameOf(e.id)}`"
        @select="choose(e.id)"
      >
        <span class="ep__item">
          <span class="ep__head">
            <span class="ep__id">{{ e.id }}</span>
            <span v-if="nameOf(e.id)" class="ep__name">{{ nameOf(e.id) }}</span>
            <VBadge v-if="e.pro" class="ep__badge" size="sm">{{ t('pro.label') }}</VBadge>
          </span>
          <span v-if="descOf(e.id)" class="ep__desc">{{ descOf(e.id) }}</span>
        </span>
      </VMenuItem>
    </VMenu>

    <VSheet
      v-if="isPhone"
      v-model:open="sheetOpen"
      side="bottom"
      :title="t('chat.engines.label')"
    >
      <div class="ep__list" role="radiogroup" :aria-label="t('chat.engines.label')">
        <button
          v-for="e in engines.options.value"
          :key="e.id"
          type="button"
          role="radio"
          class="ep__row"
          :class="{ 'is-on': e.id === current }"
          :aria-checked="e.id === current ? 'true' : 'false'"
          @click="chooseFromSheet(e.id)"
        >
          <span class="ep__item">
            <span class="ep__head">
              <span class="ep__id">{{ e.id }}</span>
              <span v-if="nameOf(e.id)" class="ep__name">{{ nameOf(e.id) }}</span>
              <VBadge v-if="e.pro" class="ep__badge" size="sm">{{ t('pro.label') }}</VBadge>
            </span>
            <span v-if="descOf(e.id)" class="ep__desc">{{ descOf(e.id) }}</span>
          </span>
          <span class="ep__check" aria-hidden="true">
            <Check v-if="e.id === current" :size="18" :stroke-width="2" />
          </span>
        </button>
      </div>
    </VSheet>

    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>
  </template>
</template>

<style scoped>
/* Tabletka - "Pro" kaliti bilan bir oila: 32px, jim matn, hover'da --fill. Ochiq
   menyuda --fill fon qoladi (qayerdan ochilgani ko'rinsin). */
.ep__pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 32px;
  padding: 0 var(--s-2) 0 var(--s-3);
  border-radius: var(--r-full);
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  touch-action: manipulation;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .ep__pill:hover {
    background: var(--fill);
    color: var(--text);
  }
}
.ep__pill:active {
  transform: scale(0.97);
}
.ep__pill.is-open {
  background: var(--fill);
  color: var(--text);
}
.ep__pill-text {
  font-variant-numeric: tabular-nums;
}
.ep__chev {
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
/* Menyu yuqoriga ochiladi - strelka ham o'sha tomonga buriladi. */
.ep__pill.is-open .ep__chev {
  transform: rotate(180deg);
}

/* ---- menyu bandi: nom + bitta qator tavsif ----
   VMenuItem yorlig'i bitta qatorli (ellipsis); bu yerda ikki qator kerak, shuning uchun
   ichki bloklar o'z `white-space` ini qaytaradi. */
.ep__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--s-1_5) 0;
  white-space: normal;
}
.ep__head {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}
.ep__id {
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.ep__name {
  color: var(--text);
  font-weight: 500;
}
/* Chiziqli belgi: tanlangan qator foni (--fill) bilan oddiy belgi foni bir xil - ichida
   yo'qolib qolardi. Ota sinf bilan: VBadge o'z o'zgaruvchisini o'sha elementda beradi. */
.ep__head .ep__badge {
  --badge-bg: transparent;
  flex: none;
  box-shadow: inset 0 0 0 1px var(--line-strong);
}
.ep__desc {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

/* ---- telefon: pastki sheet qatorlari ----
   56px+ balandlik (barmoq), butun qator bosiladi, belgi o'ngda - tizim tanlovlaridek. */
.ep__list {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
.ep__row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  min-height: 60px;
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  text-align: start;
  touch-action: manipulation;
  transition: background-color var(--dur-1) var(--ease-out);
}
.ep__row:active {
  background: var(--fill-hover);
}
.ep__row.is-on {
  background: var(--fill);
}
.ep__row .ep__item {
  flex: 1;
  padding: 0;
}
.ep__row .ep__name {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.ep__row .ep__desc {
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.ep__check {
  display: inline-flex;
  flex: none;
  width: 18px;
  color: var(--text);
}
</style>
