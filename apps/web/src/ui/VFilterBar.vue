<script lang="ts">
import type { InjectionKey } from 'vue'

export interface FilterBarEntry {
  /** Filtr hozir qiymatga egami (reaktiv o'qiladi). */
  active: () => boolean
  /** Filtrni bo'shatish ("Hammasini tozalash" uchun). */
  clear: () => void
}

export interface FilterBarContext {
  register: (entry: FilterBarEntry) => () => void
  /** Qator ichidagi boshqaruvlar balandligi: qidiruv maydoni chip'lar bilan bir chiziqda. */
  size: 'sm'
}

// Kalit shu faylda: VFilterChip va VSearchField uni import qiladi, bu fayl esa ularni
// import qilmaydi - aylanma bog'liqlik yo'q.
export const FILTER_BAR_KEY: InjectionKey<FilterBarContext> = Symbol('v-filter-bar')
</script>

<script setup lang="ts">
import { computed, nextTick, provide, ref, shallowReactive } from 'vue'
import { useI18n } from 'vue-i18n'
import VButton from './VButton.vue'
import { getTabbables } from './composables/useFocusTrap'

/**
 * Filtrlar qatori (spec §3): chapdan bitta qator - qidiruv, keyin filtr chip'lari,
 * biror filtr faol bo'lsa "Hammasini tozalash". Tor ekranda chiroyli o'raladi:
 * telefonda qidiruv alohida to'liq qatorda, chip'lar uning ostida.
 *
 *   <VFilterBar :active="!!q" @clear="q = ''">
 *     <template #search><VSearchField v-model="q" @search="load" /></template>
 *     <VFilterChip v-model="channel" :label="t('admin.channel')" :options="channels" />
 *     <VFilterChip v-model="reported" :label="t('admin.reported')" toggle />
 *     <template #end>{{ total }}</template>
 *   </VFilterBar>
 *
 * Chip'lar qatorga O'ZI ro'yxatdan o'tadi (provide/inject) - qator qaysi filtr faolligini
 * biladi va "tozalash"da har birini bo'shatadi. Qidiruv matni kabi chip bo'lmagan
 * holatni `active` prop bilan bildiring va `@clear` da o'zingiz tozalang.
 */
const props = defineProps<{
  /** Chip'dan tashqari faol holat (masalan, qidiruv matni). */
  active?: boolean
  ariaLabel?: string
  /** "Hammasini tozalash" o'rniga boshqa yozuv. */
  clearLabel?: string
}>()

const emit = defineEmits<{ clear: [] }>()

defineSlots<{
  search?(): unknown
  default?(): unknown
  end?(): unknown
}>()

const { t } = useI18n({ useScope: 'global' })
const root = ref<HTMLElement | null>(null)

const entries = shallowReactive(new Set<FilterBarEntry>())

provide(FILTER_BAR_KEY, {
  size: 'sm',
  register(entry) {
    entries.add(entry)
    return () => entries.delete(entry)
  },
})

const anyActive = computed(() => {
  if (props.active) return true
  for (const e of entries) if (e.active()) return true
  return false
})

async function clearAll() {
  for (const e of entries) if (e.active()) e.clear()
  emit('clear')
  // Tugma yo'qoladi - fokus <body> ga tushib qolmasin: qatorning boshiga qaytaramiz.
  await nextTick()
  const first = getTabbables(root.value)[0]
  first?.focus({ preventScroll: true })
}
</script>

<template>
  <div ref="root" class="v-fbar" role="group" :aria-label="ariaLabel ?? t('ui.filters')">
    <div v-if="$slots.search" class="v-fbar__search"><slot name="search" /></div>
    <slot />
    <Transition name="v-fbar-clear">
      <VButton v-if="anyActive" class="v-fbar__clear" variant="ghost" size="sm" @click="clearAll">
        {{ clearLabel ?? t('ui.clearAll') }}
      </VButton>
    </Transition>
    <div v-if="$slots.end" class="v-fbar__end"><slot name="end" /></div>
  </div>
</template>

<style scoped>
.v-fbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}

.v-fbar__search {
  flex: 0 1 280px;
  min-width: min(100%, 200px);
}
.v-fbar__search > :slotted(*) {
  width: 100%;
}

/* Jim tugma: matn --text-2, hover'da --fill. */
.v-fbar__clear {
  --btn-fg: var(--text-2);
  --btn-px: 10px;
}
@media (hover: hover) {
  .v-fbar__clear:hover {
    --btn-fg: var(--text);
  }
}

.v-fbar__end {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin-left: auto;
  color: var(--text-3);
  font-size: 13px;
  line-height: 18px;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 767.98px) {
  .v-fbar__search {
    flex-basis: 100%;
  }
}

.v-fbar-clear-enter-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.v-fbar-clear-leave-active {
  transition: opacity var(--dur-1) var(--ease-out);
}
.v-fbar-clear-enter-from {
  opacity: 0;
  transform: translateX(-4px);
}
.v-fbar-clear-leave-to {
  opacity: 0;
}
</style>
