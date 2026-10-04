<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search } from 'lucide-vue-next'
import VInput from './VInput.vue'
import VKbd from './VKbd.vue'
import VSpinner from './VSpinner.vue'
import { FILTER_BAR_KEY } from './VFilterBar.vue'
import { ariaShortcut, isEditableTarget, matchesShortcut } from './useCommandPalette'

/**
 * Qidiruv maydoni: lupa belgisi, × tozalash, ixtiyoriy yorliq ishorasi (`/` yoki ⌘K).
 *
 * Ikki xil natija:
 * - `v-model` - har bir harfda (maydon "jonli" qolsin);
 * - `search` - 250 ms tinchlikdan keyin, qirqilgan (trim) matn bilan; bir xil so'rov
 *   ikki marta yuborilmaydi. Tozalanganda - darhol, Enter - darhol (kutmasdan).
 *
 * `shortcut` berilsa, maydon bo'sh va fokussiz turganda o'ng tomonda VKbd ko'rinadi va
 * yorliq sahifaning istalgan joyidan maydonga fokus beradi (`/` - faqat matn
 * yozilmayotganda). Ochiq modal oyna ortidagi maydon "o'g'irlanmaydi".
 *
 * VFilterBar ichida o'lcham avtomatik `sm` (32px) - chip'lar bilan bir chiziqda.
 */
const props = withDefaults(
  defineProps<{
    placeholder?: string
    ariaLabel?: string
    /** Yorliq: '/', 'mod+k'... `null` - yo'q. */
    shortcut?: string | string[] | null
    /** Yorliq global tinglansinmi (false - faqat ishora ko'rsatiladi). */
    hotkey?: boolean
    /** `search` hodisasi kechikishi, ms. */
    debounce?: number
    size?: 'sm' | 'md' | 'lg'
    loading?: boolean
    disabled?: boolean
    autofocus?: boolean
  }>(),
  { shortcut: null, hotkey: true, debounce: 250, size: undefined },
)

const model = defineModel<string>({ default: '' })

const emit = defineEmits<{
  search: [query: string]
  clear: []
}>()

const { t } = useI18n({ useScope: 'global' })
const bar = inject(FILTER_BAR_KEY, null)

const field = ref<InstanceType<typeof VInput> | null>(null)
const focused = ref(false)

const inputSize = computed(() => props.size ?? (bar ? bar.size : 'md'))
const iconSize = computed(() => (inputSize.value === 'lg' ? 18 : 16))
const showKbd = computed(() => !!props.shortcut && !focused.value && !model.value && !props.disabled)
const keyshortcuts = computed(() => (props.shortcut ? ariaShortcut(props.shortcut) : undefined))

function inputEl(): HTMLInputElement | null {
  return (field.value?.el as HTMLInputElement | null | undefined) ?? null
}

/* ---- kechiktirilgan `search` ---- */
let timer: ReturnType<typeof setTimeout> | undefined
let lastSent = model.value.trim()
// Oxirgi marta O'ZIMIZ yozgan qiymat: ota komponent qiymatni tashqaridan almashtirsa
// (URL'dan tiklash, "Hammasini tozalash") - `search` chiqarmaymiz, u o'zi yuklaydi.
let typed = model.value

function fire(force = false) {
  clearTimeout(timer)
  timer = undefined
  const q = model.value.trim()
  if (!force && q === lastSent) return
  lastSent = q
  emit('search', q)
}

function onUpdate(v: string | number | null) {
  const s = v === null || v === undefined ? '' : String(v)
  typed = s
  model.value = s
  clearTimeout(timer)
  if (!s.trim()) fire()
  else timer = setTimeout(() => fire(), props.debounce)
}

watch(model, (v) => {
  if (v === typed) return
  typed = v
  clearTimeout(timer)
  timer = undefined
  lastSent = v.trim()
})

function onKeyDown(e: KeyboardEvent) {
  if (e.isComposing) return
  if (e.key === 'Enter') {
    fire(true)
    return
  }
  // Bo'sh maydonda Esc - fokusdan chiqish (sahifa yorliqlari yana ishlasin). Qiymat
  // bo'lsa Esc ni VInput o'zi ishlatadi (tozalaydi). preventDefault QILMAYMIZ: maydon
  // dialog ichida bo'lsa, Esc dialogni ham yopishi kerak.
  if (e.key === 'Escape' && !model.value) inputEl()?.blur()
}

function onClear() {
  emit('clear')
}

/* ---- global yorliq ---- */
function onGlobalKeyDown(e: KeyboardEvent) {
  if (!props.shortcut || !props.hotkey || props.disabled || e.defaultPrevented || e.isComposing) return
  if (!matchesShortcut(e, props.shortcut)) return
  const el = inputEl()
  if (!el || el.getClientRects().length === 0) return
  if (document.activeElement === el) return
  const plain = !e.ctrlKey && !e.metaKey && !e.altKey
  if (plain && isEditableTarget(e.target)) return
  // Ochiq modal oyna ortidagi maydonga fokus bermaymiz (fokus tuzog'i baribir qaytaradi).
  const modals = document.querySelectorAll('[aria-modal="true"]')
  const top = modals[modals.length - 1]
  if (top && !top.contains(el)) return
  e.preventDefault()
  el.focus()
  el.select()
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeyDown)
  if (props.autofocus) inputEl()?.focus({ preventScroll: true })
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeyDown)
  clearTimeout(timer)
})

defineExpose({
  // `options` - masalan `preventScroll`: maydon hali ochilayotgan (kesilgan) panelda
  // turganda fokus panelni yon tomonga aylantirib yubormasin.
  focus: (options?: FocusOptions) => inputEl()?.focus(options),
  blur: () => inputEl()?.blur(),
  select: () => inputEl()?.select(),
  /** Kutilayotgan `search` ni darhol yuborish. */
  flush: () => fire(true),
})
</script>

<template>
  <VInput
    ref="field"
    class="v-search"
    type="search"
    :model-value="model"
    :size="inputSize"
    :placeholder="placeholder ?? t('ui.search')"
    :aria-label="ariaLabel ?? placeholder ?? t('ui.search')"
    :aria-keyshortcuts="keyshortcuts"
    :disabled="disabled"
    clearable
    autocomplete="off"
    autocorrect="off"
    autocapitalize="off"
    spellcheck="false"
    enterkeyhint="search"
    @update:model-value="onUpdate"
    @clear="onClear"
    @keydown="onKeyDown"
    @focus="focused = true"
    @blur="focused = false"
  >
    <template #leading>
      <span class="v-search__icon">
        <VSpinner v-if="loading" :size="iconSize - 2" />
        <Search v-else :size="iconSize" :stroke-width="1.75" aria-hidden="true" />
      </span>
    </template>
    <template v-if="showKbd && shortcut" #trailing>
      <VKbd class="v-search__kbd" :keys="shortcut" size="sm" aria-hidden="true" />
    </template>
  </VInput>
</template>

<style scoped>
.v-search__icon {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  color: var(--text-3);
}
.v-search__kbd {
  margin-right: 2px;
  pointer-events: none;
}
/* Sensorli ekranda klaviatura ishorasi ma'nosiz. */
@media (hover: none) {
  .v-search__kbd {
    display: none;
  }
}
</style>
