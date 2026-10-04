<script lang="ts">
import { addDays, fromISODate, startOfMonth, toISODate } from './format'

export type DatePreset = 'today' | '7d' | '30d' | '90d' | 'month' | 'custom'
export type FixedDatePreset = Exclude<DatePreset, 'custom'>

export interface DateRangeValue {
  /** Mahalliy kun, `YYYY-MM-DD` (URL `?from=`). */
  from: string
  /** Mahalliy kun, `YYYY-MM-DD`, shu kun ham kiradi. */
  to: string
  preset?: DatePreset
}

export const DATE_PRESETS: readonly FixedDatePreset[] = ['today', '7d', '30d', '90d', 'month']

const SPAN: Record<'7d' | '30d' | '90d', number> = { '7d': 7, '30d': 30, '90d': 90 }

/** Tayyor oraliq bugungi kunga nisbatan: "7 kun" = bugun va undan oldingi 6 kun. */
export function presetRange(preset: FixedDatePreset, now: Date = new Date()): DateRangeValue {
  const to = toISODate(now)
  if (preset === 'today') return { from: to, to, preset }
  if (preset === 'month') return { from: toISODate(startOfMonth(now)), to, preset }
  return { from: toISODate(addDays(now, -(SPAN[preset] - 1))), to, preset }
}

/** Sanalar tayyor oraliqlardan biriga to'g'ri kelsa - o'sha, aks holda 'custom'. */
export function inferPreset(from: string, to: string, now: Date = new Date()): DatePreset {
  for (const p of DATE_PRESETS) {
    const r = presetRange(p, now)
    if (r.from === from && r.to === to) return p
  }
  return 'custom'
}

/**
 * URL / saqlangan qiymatdan to'g'ri oraliq. Tayyor oraliq sanalari BUGUNGA qayta
 * hisoblanadi (kecha ochilgan "7 kun" havolasi bugun ham "oxirgi 7 kun" bo'lsin);
 * buzuq sanalar - `fallback` oraliq.
 */
export function resolveDateRange(
  v: Partial<DateRangeValue> | null | undefined,
  fallback: FixedDatePreset = '30d',
  now: Date = new Date(),
): DateRangeValue {
  const preset = v?.preset
  if (preset && preset !== 'custom' && DATE_PRESETS.includes(preset)) return presetRange(preset, now)
  const rawFrom = v?.from ?? ''
  const rawTo = v?.to ?? ''
  const a = fromISODate(rawFrom)
  const b = fromISODate(rawTo)
  if (!a || !b) return presetRange(fallback, now)
  const [from, to] = a <= b ? [rawFrom, rawTo] : [rawTo, rawFrom]
  return { from, to, preset: preset === 'custom' ? 'custom' : inferPreset(from, to, now) }
}
</script>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarDays, Check, ChevronDown } from 'lucide-vue-next'
import VButton from './VButton.vue'
import VPopover from './VPopover.vue'
import type { PopoverFocusContext } from './VPopover.vue'
import type { Placement } from './composables/useFloating'
import { useId } from './composables/useId'
import { fmtDate } from './format'

/**
 * Sana oralig'i (spec §3): ixcham chip ("30 kun", "12–28-sen") va popover.
 *
 * Popover: tayyor oraliqlar ro'yxati (o'ngda aniq sanalar kulrangda, tanlanganida
 * qalin ✓), ostida soch tolasi bilan ajratilgan "Boshqa" - ochilsa ikki tabiiy
 * <input type="date"> va "Qo'llash". Tabiiy sana maydoni: telefonda tizim kalendari,
 * ekran o'quvchida to'liq qo'llab-quvvatlash - o'zimiz kalendar yozmaymiz.
 *
 * Klaviatura: ↑ ↓ (aylanib) ro'yxat va "Boshqa" orasida, Home End, Enter / Space -
 * tanlash, Esc - yopish (fokus chip'ga qaytadi). Sichqoncha bilan ochilganda
 * ta'kid yo'q - sichqonchaga ergashadi (VMenu kabi).
 *
 * `preset` berilmasa, sanalardan aniqlanadi (URL'da faqat from/to bo'lsa ham "30 kun").
 */
const props = withDefaults(
  defineProps<{
    modelValue: DateRangeValue
    /** Eng erta sana (`YYYY-MM-DD`), masalan telemetriya saqlanish muddati. */
    min?: string
    /** Eng kech sana; standart - bugun. */
    max?: string
    size?: 'sm' | 'md'
    placement?: Placement
    ariaLabel?: string
    disabled?: boolean
  }>(),
  { size: 'sm', placement: 'bottom-start' },
)

const emit = defineEmits<{
  'update:modelValue': [value: DateRangeValue]
  change: [value: DateRangeValue]
}>()

const { t, locale } = useI18n({ useScope: 'global' })

const id = useId('v-date-range')
const listId = `${id}-list`
const customId = `${id}-custom`
const fromId = `${id}-from`
const toId = `${id}-to`

const open = ref(false)
const pop = ref<InstanceType<typeof VPopover> | null>(null)
const customOpen = ref(false)
const customBtn = ref<HTMLButtonElement | null>(null)
const fromInput = ref<HTMLInputElement | null>(null)
const draftFrom = ref('')
const draftTo = ref('')
// "Bugun" popover ochilgan paytda qayta olinadi: sahifa yarim tundan keyin ham ochiq
// qolsa, tayyor oraliqlar yangi kunga siljisin.
const now = ref(new Date())

const optionEls: (HTMLElement | null)[] = []
function setOptionRef(el: unknown, i: number) {
  optionEls[i] = el instanceof HTMLElement ? el : null
}

/* ---- joriy qiymat ---- */
const preset = computed<DatePreset>(
  () => props.modelValue.preset ?? inferPreset(props.modelValue.from, props.modelValue.to, now.value),
)
const maxDate = computed(() => props.max ?? toISODate(now.value))

const PRESET_KEY: Record<FixedDatePreset, string> = {
  today: 'ui.today',
  '7d': 'ui.last7',
  '30d': 'ui.last30',
  '90d': 'ui.last90',
  month: 'ui.thisMonth',
}

/** "12–28-sen", "28-avg – 3-sen", "18-sen, 2025 – 2-yan, 2026" (til bo'yicha). */
function formatRange(fromIso: string, toIso: string): string {
  const a = fromISODate(fromIso)
  const b = fromISODate(toIso)
  if (!a || !b) return '—'
  const loc = locale.value
  if (a.getTime() === b.getTime()) return fmtDate(a, loc)
  if (a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()) {
    return `${a.getDate()}–${fmtDate(b, loc)}`
  }
  if (a.getFullYear() === b.getFullYear()) return `${fmtDate(a, loc, { year: 'never' })} – ${fmtDate(b, loc)}`
  return `${fmtDate(a, loc, { year: 'always' })} – ${fmtDate(b, loc, { year: 'always' })}`
}

const label = computed(() =>
  preset.value === 'custom'
    ? formatRange(props.modelValue.from, props.modelValue.to)
    : t(PRESET_KEY[preset.value]),
)
const groupLabel = computed(() => props.ariaLabel ?? t('ui.dateRange'))

const rows = computed(() =>
  DATE_PRESETS.map((p) => {
    const r = presetRange(p, now.value)
    return { preset: p, label: t(PRESET_KEY[p]), hint: formatRange(r.from, r.to) }
  }),
)

/* ---- tanlash ---- */
function commit(v: DateRangeValue) {
  const cur = props.modelValue
  if (cur.from === v.from && cur.to === v.to && preset.value === v.preset) return
  emit('update:modelValue', v)
  emit('change', v)
}

function pick(p: FixedDatePreset) {
  commit(presetRange(p, now.value))
  pop.value?.hide()
}

const canApply = computed(() => {
  const a = fromISODate(draftFrom.value)
  const b = fromISODate(draftTo.value)
  return !!a && !!b
})

function applyCustom() {
  if (!canApply.value) return
  let from = draftFrom.value
  let to = draftTo.value
  // Qo'lda yozilgan sana chegaradan chiqsa - chegaraga tortamiz; teskari bo'lsa - almashtiramiz.
  if (from > to) [from, to] = [to, from]
  const hi = maxDate.value
  const lo = props.min
  if (to > hi) to = hi
  if (from > hi) from = hi
  if (lo && from < lo) from = lo
  if (lo && to < lo) to = lo
  commit({ from, to, preset: 'custom' })
  pop.value?.hide()
}

async function toggleCustom(e: MouseEvent) {
  customOpen.value = !customOpen.value
  // Klaviatura bilan ochilganda (detail 0) - darhol birinchi sana maydoniga.
  if (customOpen.value && e.detail === 0) {
    await nextTick()
    fromInput.value?.focus()
  }
}

/* ---- ochilish ---- */
function onOpenChange(on: boolean) {
  if (!on) return
  now.value = new Date()
  draftFrom.value = props.modelValue.from
  draftTo.value = props.modelValue.to
  customOpen.value = preset.value === 'custom'
}

const selectedIndex = computed(() => DATE_PRESETS.indexOf(preset.value as FixedDatePreset))

// Roving tabindex: ro'yxat bitta Tab to'xtashi - tanlangan qatorda.
const focusIndex = ref(0)

function focusOnOpen(ctx: PopoverFocusContext): HTMLElement | null {
  focusIndex.value = Math.max(0, selectedIndex.value)
  if (!ctx.keyboard) return pop.value?.panel ?? null
  if (preset.value === 'custom') return customBtn.value
  return optionEls[focusIndex.value] ?? null
}

/* ---- klaviatura ---- */
// Yopiq chip'da ↓ / ↑ - klaviatura rejimida ochadi (tanlangan qatorga fokus).
function onTriggerKeyDown(e: KeyboardEvent) {
  if (open.value || props.disabled || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return
  e.preventDefault()
  pop.value?.show(true)
}

function ring(): HTMLElement[] {
  const list = optionEls.slice(0, DATE_PRESETS.length).filter((el): el is HTMLElement => !!el)
  if (customBtn.value) list.push(customBtn.value)
  return list
}

function onPanelKeyDown(e: KeyboardEvent) {
  if (e.defaultPrevented || e.isComposing) return
  const target = e.target as HTMLElement | null
  // Sana maydonlari va "Qo'llash" o'z klaviaturasini o'zi boshqaradi.
  if (target?.closest('form')) return
  const items = ring()
  const n = items.length
  if (!n) return
  const idx = items.indexOf(document.activeElement as HTMLElement)
  const go = (i: number) => {
    e.preventDefault()
    items[(i + n) % n]?.focus()
  }
  switch (e.key) {
    case 'ArrowDown':
      return go(idx < 0 ? Math.max(0, selectedIndex.value) : idx + 1)
    case 'ArrowUp':
      return go(idx < 0 ? Math.max(0, selectedIndex.value) : idx - 1)
    case 'Home':
      return go(0)
    case 'End':
      return go(n - 1)
    case 'Enter':
    case ' ': {
      const i = optionEls.indexOf(target)
      if (i >= 0 && i < DATE_PRESETS.length) {
        e.preventDefault()
        pick(DATE_PRESETS[i])
      }
      return
    }
  }
}

/* Sichqoncha ta'kidi = fokus (VMenu kabi): ikki xil ta'kid bir vaqtda bo'lmaydi. */
function onRowPointerMove(e: PointerEvent) {
  if (e.pointerType === 'touch') return
  const el = e.currentTarget as HTMLElement
  if (document.activeElement !== el) el.focus({ preventScroll: true })
}
function onRowPointerLeave(e: PointerEvent) {
  if (e.pointerType === 'touch') return
  if (document.activeElement === e.currentTarget) pop.value?.panel?.focus({ preventScroll: true })
}
</script>

<template>
  <VPopover
    ref="pop"
    v-model:open="open"
    role="dialog"
    :aria-label="groupLabel"
    :placement="placement"
    :offset="6"
    padding="none"
    :width="280"
    :disabled="disabled"
    :auto-focus="focusOnOpen"
    @update:open="onOpenChange"
    @keydown="onPanelKeyDown"
    @trigger-keydown="onTriggerKeyDown"
  >
    <template #trigger>
      <button
        type="button"
        class="v-dr"
        :class="[`v-dr--${size}`, { 'is-open': open }]"
        :aria-label="`${groupLabel}: ${label}`"
        :disabled="disabled"
      >
        <CalendarDays class="v-dr__icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
        <span class="v-dr__label">{{ label }}</span>
        <ChevronDown class="v-dr__chev" :size="14" :stroke-width="1.75" aria-hidden="true" />
      </button>
    </template>

    <div :id="listId" class="v-dr__list" role="listbox" :aria-label="groupLabel">
      <div
        v-for="(row, i) in rows"
        :key="row.preset"
        :ref="(el) => setOptionRef(el, i)"
        class="v-dr__row"
        role="option"
        :aria-selected="preset === row.preset ? 'true' : 'false'"
        :tabindex="i === focusIndex ? 0 : -1"
        @click="pick(row.preset)"
        @focus="focusIndex = i"
        @pointermove="onRowPointerMove"
        @pointerleave="onRowPointerLeave"
      >
        <span class="v-dr__row-label">{{ row.label }}</span>
        <span class="v-dr__row-hint">{{ row.hint }}</span>
        <span class="v-dr__check" aria-hidden="true">
          <Check v-if="preset === row.preset" :size="16" :stroke-width="2.5" />
        </span>
      </div>
    </div>

    <div class="v-dr__foot">
      <button
        ref="customBtn"
        type="button"
        class="v-dr__row v-dr__custom-toggle"
        :aria-expanded="customOpen ? 'true' : 'false'"
        :aria-controls="customId"
        @click="toggleCustom"
        @pointermove="onRowPointerMove"
        @pointerleave="onRowPointerLeave"
      >
        <span class="v-dr__row-label">{{ t('ui.custom') }}</span>
        <ChevronDown class="v-dr__custom-chev" :size="14" :stroke-width="1.75" aria-hidden="true" />
        <span class="v-dr__row-hint">
          <template v-if="preset === 'custom'">{{ formatRange(modelValue.from, modelValue.to) }}</template>
        </span>
        <span class="v-dr__check" aria-hidden="true">
          <Check v-if="preset === 'custom'" :size="16" :stroke-width="2.5" />
        </span>
      </button>

      <div :id="customId" class="v-dr__custom" :class="{ 'is-open': customOpen }">
        <div class="v-dr__custom-clip">
          <form class="v-dr__form" novalidate @submit.prevent="applyCustom">
            <label :for="fromId" class="v-dr__field-label">{{ t('ui.from') }}</label>
            <input
              :id="fromId"
              ref="fromInput"
              v-model="draftFrom"
              class="v-dr__date"
              type="date"
              :min="min"
              :max="draftTo || maxDate"
              required
            />
            <label :for="toId" class="v-dr__field-label">{{ t('ui.to') }}</label>
            <input
              :id="toId"
              v-model="draftTo"
              class="v-dr__date"
              type="date"
              :min="draftFrom || min"
              :max="maxDate"
              required
            />
            <VButton class="v-dr__apply" type="submit" variant="primary" size="sm" :disabled="!canApply">
              {{ t('ui.apply') }}
            </VButton>
          </form>
        </div>
      </div>
    </div>
  </VPopover>
</template>

<style scoped>
/* ---- chip ---- */
.v-dr {
  --dr-h: 32px;
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  max-width: 100%;
  height: var(--dr-h);
  padding: 0 10px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  touch-action: manipulation;
  transition:
    background-color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.v-dr--md {
  --dr-h: 36px;
  padding: 0 var(--s-3);
  font-size: var(--fs-body-sm);
}
@media (pointer: coarse) {
  .v-dr {
    --dr-h: 36px;
  }
}
@media (hover: hover) {
  .v-dr:not(:disabled):hover {
    background: var(--fill-hover);
  }
}
.v-dr.is-open {
  background: var(--fill-hover);
}
.v-dr:not(:disabled):active {
  transform: scale(0.98);
}
.v-dr:focus-visible {
  border-radius: var(--r-full);
}
.v-dr:disabled {
  opacity: 0.5;
  cursor: default;
}
.v-dr__icon {
  flex-shrink: 0;
  color: var(--text-2);
}
.v-dr__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.v-dr__chev {
  flex-shrink: 0;
  margin-right: -2px;
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.is-open .v-dr__chev {
  transform: rotate(180deg);
}

/* ---- ro'yxat ---- */
.v-dr__list {
  padding: var(--s-1_5);
}
.v-dr__row {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  width: 100%;
  min-height: 32px;
  padding: 0 var(--s-2);
  border-radius: var(--r-xs);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: left;
  cursor: pointer;
  outline: none;
  user-select: none;
  -webkit-user-select: none;
}
/* Ta'kid = fokus (sichqonchaga ergashadi). Klaviatura fokusida qo'shimcha halqa kerak
   emas - to'ldirilgan fon yetarli va tizim menyularidagidek. */
.v-dr__row:focus,
.v-dr__row:focus-visible {
  background: var(--fill);
  outline: none;
}
.v-dr__row:active {
  background: var(--fill-hover);
}
@media (pointer: coarse) {
  .v-dr__row {
    min-height: 40px;
  }
}
.v-dr__row-label {
  flex-shrink: 0;
}
.v-dr__row-hint {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--text-3);
  font-size: var(--fs-caption);
  font-variant-numeric: tabular-nums;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.v-dr__check {
  display: inline-flex;
  flex-shrink: 0;
  width: 16px;
  color: var(--text);
}

/* ---- "Boshqa" ---- */
.v-dr__foot {
  padding: var(--s-1_5);
  border-top: 1px solid var(--line);
}
.v-dr__custom-chev {
  flex-shrink: 0;
  margin-left: -2px;
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.v-dr__custom-toggle[aria-expanded='true'] .v-dr__custom-chev {
  transform: rotate(180deg);
}

/* Balandlik animatsiyasi: grid 0fr -> 1fr (JS o'lchashsiz). Yopiq holatda
   `visibility: hidden` - ichidagi maydonlar Tab va ekran o'quvchidan yashirin;
   yopilishda u animatsiya TUGAGACH qo'llanadi. */
.v-dr__custom {
  display: grid;
  grid-template-rows: 0fr;
  visibility: hidden;
  transition:
    grid-template-rows var(--dur-2) var(--ease-out),
    visibility 0s linear var(--dur-2);
}
.v-dr__custom.is-open {
  grid-template-rows: 1fr;
  visibility: visible;
  transition:
    grid-template-rows var(--dur-2) var(--ease-out),
    visibility 0s linear 0s;
}
.v-dr__custom-clip {
  min-height: 0;
  overflow: hidden;
}
.v-dr__form {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  column-gap: var(--s-3);
  row-gap: var(--s-2);
  padding: var(--s-2) var(--s-2) var(--s-1);
}
.v-dr__field-label {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.v-dr__date {
  --dr-ring: color-mix(in srgb, var(--text) 10%, transparent);
  width: 100%;
  min-width: 0;
  height: 32px;
  padding: 0 var(--s-2) 0 10px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: var(--fill);
  color: var(--text);
  font-size: 13px;
  line-height: 18px;
  font-variant-numeric: tabular-nums;
  outline: none;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out),
    box-shadow var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-dr__date:hover:not(:focus) {
    border-color: var(--line-strong);
  }
}
.v-dr__date:focus,
.v-dr__date:focus-visible {
  border-color: var(--ink);
  border-radius: var(--r-sm);
  background: var(--surface);
  box-shadow: 0 0 0 3px var(--dr-ring);
  outline: none;
}
.v-dr__date::-webkit-calendar-picker-indicator {
  opacity: 0.5;
  cursor: pointer;
  transition: opacity var(--dur-1) var(--ease-out);
}
.v-dr__date::-webkit-calendar-picker-indicator:hover {
  opacity: 0.9;
}
.v-dr__date::-webkit-datetime-edit-fields-wrapper {
  padding: 0;
}
/* iOS 16px dan kichik shriftli maydonga fokusda sahifani kattalashtiradi. */
@media (max-width: 767.98px) {
  .v-dr__date {
    font-size: 16px;
  }
}
.v-dr__apply {
  grid-column: 1 / -1;
  justify-self: end;
  margin-top: var(--s-1);
}
</style>
