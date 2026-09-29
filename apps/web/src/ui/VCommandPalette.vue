<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { CornerDownLeft, History, Search, X } from 'lucide-vue-next'
import VKbd from './VKbd.vue'
import VSpinner from './VSpinner.vue'
import { useLayer } from './composables/useClickOutside'
import { useFocusTrap, useScrollLock } from './composables/useFocusTrap'
import { useId } from './composables/useId'
import { usePrefersReducedMotion } from './composables/useMediaQuery'
import { matchesShortcut, normalizeSearch, useCommandPalette } from './useCommandPalette'
import type { CommandGroup, CommandItem, CommandProviderResult } from './useCommandPalette'

/**
 * Buyruqlar palitrasi (spec §3, ⌘K / Ctrl K). Ilovada BIR marta o'rnatiladi (admin
 * qobig'ida); manbalarni sahifalar `useCommandPalette().register(...)` bilan ulaydi.
 *
 * Tuzilishi: yuqoridan 20vh da markaziy oyna, katta qidiruv maydoni, guruhlangan
 * natijalar, pastda klaviatura ishoralari. Bo'sh so'rovda - "So'nggilar".
 *
 * ARIA: maydon - `combobox`, natijalar - `listbox` (guruhlar `group`), faol qator
 * `aria-activedescendant` bilan: fokus doim maydonda qoladi, yozishni to'xtatmay
 * ↑ ↓ bilan yurish mumkin. Natijalar soni `status` orqali (kechikib) e'lon qilinadi.
 *
 * Klaviatura: ↑ ↓ (va Ctrl N / Ctrl P), PageUp PageDown, Enter - bajarish,
 * ⌘/Ctrl Enter - havolani yangi varaqda, Esc - yopish, bo'sh so'rovda Delete -
 * tanlangan "so'nggi"ni o'chirish.
 *
 * Sekin manba butun ro'yxatni ushlab turmasin: hamma javob kutiladi, lekin ko'pi
 * bilan 250 ms - keyin kelganlari birin-ketin qo'shiladi. Yangi so'rov natijasi
 * kelguncha eski natija xira holda turadi (ro'yxat "sakramaydi").
 */
const props = withDefaults(
  defineProps<{
    placeholder?: string
    /** Har bir guruhda eng ko'p qator. */
    maxPerGroup?: number
    maxRecents?: number
    /** Yozish to'xtagandan keyin manbalarni so'rash kechikishi, ms. */
    debounce?: number
  }>(),
  { maxPerGroup: 8, maxRecents: 5, debounce: 120 },
)

interface Row {
  key: string
  index: number
  item: CommandItem
  /** Asl guruh nomi ("so'nggi"ga yozish uchun). */
  group: string
  recent: boolean
}
interface Section {
  key: string
  labelId: string
  label: string
  rows: Row[]
}

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const palette = useCommandPalette()
const reduced = usePrefersReducedMotion()

const host = palette.claimHost()
onBeforeUnmount(host.release)
const isOpen = computed(() => palette.isOpen.value && host.isHost())

const id = useId('v-cmdk')
const listId = `${id}-list`
const optionId = (i: number) => `${id}-opt-${i}`

const panel = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const body = ref<HTMLElement | null>(null)

// Ro'yxat bo'shlig'iga bosilsa fokus panelning o'ziga o'tadi - yozish to'xtamasin,
// maydonga qaytaramiz (`focus` ko'pirmaydi: faqat panelning o'zi uchun ishlaydi).
function onPanelFocus(e: FocusEvent) {
  if (e.target === panel.value) input.value?.focus({ preventScroll: true })
}

const query = ref('')
/** Ko'rsatilayotgan natijalar qaysi so'rovniki (belgilash shu bo'yicha). */
const shownQuery = ref('')
const sections = shallowRef<Section[]>([])
const pending = ref(0)
const settled = ref(true)
/** Ko'rsatilgan natija eski so'rovniki - yangisi hali kelmagan. */
const stale = ref(false)
const activeKey = ref<string | null>(null)
// Foydalanuvchi o'zi qator tanlaganmi: kechikib kelgan natija ta'kidni tortib olmasin.
let userMoved = false
// Natija kelmasdan Enter bosilsa (tez yozib, darhol Enter) - eski ro'yxatdagi qator
// emas, yangi so'rovning birinchi natijasi bajarilsin.
let queuedEnter: { newTab: boolean } | null = null

const flat = computed(() => sections.value.flatMap((s) => s.rows))
const activeIndex = computed(() => flat.value.findIndex((r) => r.key === activeKey.value))
const activeId = computed(() => (activeIndex.value >= 0 ? optionId(activeIndex.value) : undefined))
const hasQuery = computed(() => query.value.trim() !== '')
const showEmpty = computed(() => settled.value && !stale.value && hasQuery.value && flat.value.length === 0)
const showBody = computed(() => flat.value.length > 0 || showEmpty.value)

/* ---------------------------------------------------------------- qidiruv */

let gen = 0
let controller: AbortController | null = null
let results = new Map<string, CommandGroup[]>()
let lastSearched: string | null = null
let debounceTimer: ReturnType<typeof setTimeout> | undefined
let progressiveTimer: ReturnType<typeof setTimeout> | undefined

function toGroups(r: CommandProviderResult): CommandGroup[] {
  if (!r) return []
  const list = Array.isArray(r) ? r : [r]
  return list.filter((g) => !!g && typeof g.group === 'string' && Array.isArray(g.items) && g.items.length > 0)
}

function search(q: string) {
  clearTimeout(debounceTimer)
  clearTimeout(progressiveTimer)
  controller?.abort()
  const my = ++gen
  const ctrl = new AbortController()
  controller = ctrl
  lastSearched = q
  results = new Map()
  userMoved = false
  const list = palette.providers.value
  pending.value = list.length
  settled.value = list.length === 0
  stale.value = true
  if (!list.length) {
    rebuild(q)
    flushQueuedEnter()
    return
  }
  progressiveTimer = setTimeout(() => {
    if (my === gen && stale.value) rebuild(q)
  }, 250)
  for (const p of list) {
    let out: CommandProviderResult | Promise<CommandProviderResult>
    try {
      out = p.fn(q, ctrl.signal)
    } catch (err) {
      console.warn('[command-palette]', p.id, err)
      out = null
    }
    Promise.resolve(out)
      .then((res) => {
        if (my === gen) results.set(p.id, toGroups(res))
      })
      .catch((err: unknown) => {
        if (my === gen && !ctrl.signal.aborted) console.warn('[command-palette]', p.id, err)
      })
      .finally(() => {
        if (my !== gen) return
        pending.value -= 1
        if (pending.value <= 0) {
          settled.value = true
          clearTimeout(progressiveTimer)
          rebuild(q)
          flushQueuedEnter()
        } else if (!stale.value) rebuild(q)
      })
  }
}

function rebuild(q: string) {
  const out: Section[] = []
  const empty = !q.trim()
  const seen = new Set<string>()
  let index = 0

  if (empty) {
    const rows: Row[] = []
    for (const r of palette.recents.value) {
      if (rows.length >= props.maxRecents) break
      const item = palette.resolveRecent(r)
      if (!item) continue
      rows.push({ key: `recent:${r.id}`, index: 0, item, group: r.group, recent: true })
      seen.add(r.id)
    }
    if (rows.length) out.push({ key: 'recent', labelId: `${id}-g-recent`, label: t('ui.recent'), rows })
  }

  const byName = new Map<string, Section>()
  for (const p of palette.providers.value) {
    for (const g of results.get(p.id) ?? []) {
      let sec = byName.get(g.group)
      if (!sec) {
        sec = { key: `g:${g.group}`, labelId: `${id}-g-${byName.size}`, label: g.group, rows: [] }
        byName.set(g.group, sec)
        out.push(sec)
      }
      for (const item of g.items) {
        if (sec.rows.length >= props.maxPerGroup) break
        // Bo'sh so'rovda "so'nggi"da turgan band pastda qaytarilmaydi.
        if (empty && seen.has(item.id)) continue
        if (sec.rows.some((r) => r.item.id === item.id)) continue
        sec.rows.push({ key: `${sec.key}:${item.id}`, index: 0, item, group: g.group, recent: false })
      }
    }
  }

  const final = out.filter((s) => s.rows.length > 0)
  for (const s of final) for (const r of s.rows) r.index = index++
  palette.remember(final.flatMap((s) => s.rows.filter((r) => !r.recent).map((r) => r.item)))

  sections.value = final
  shownQuery.value = q
  stale.value = false

  const keys = final.flatMap((s) => s.rows.map((r) => r.key))
  if (!userMoved || !activeKey.value || !keys.includes(activeKey.value)) {
    activeKey.value = keys[0] ?? null
    userMoved = false
    void nextTick(() => {
      if (body.value) body.value.scrollTop = 0
    })
  }
}

function flushQueuedEnter() {
  const queued = queuedEnter
  queuedEnter = null
  if (!queued || !isOpen.value) return
  const row = flat.value[activeIndex.value]
  if (row) void run(row, queued.newTab)
}

watch(query, (q) => {
  queuedEnter = null
  if (!isOpen.value || q === lastSearched) return
  clearTimeout(debounceTimer)
  if (!q.trim()) search(q)
  else debounceTimer = setTimeout(() => search(q), props.debounce)
})

// Palitra ochiq turganda manba qo'shilsa/uzilsa (sahifa almashdi) - qayta so'raymiz.
watch(
  () => palette.providers.value,
  () => {
    if (isOpen.value) search(query.value)
  },
)

/* ---------------------------------------------------------------- ochish / yopish */

function reset() {
  gen++
  controller?.abort()
  controller = null
  clearTimeout(debounceTimer)
  clearTimeout(progressiveTimer)
  pending.value = 0
  settled.value = true
  lastSearched = null
  queuedEnter = null
}

function close() {
  palette.close()
}

const layer = useLayer(isOpen, {
  kind: 'dialog',
  modal: true,
  elements: () => [panel.value],
  onDismiss: close,
})
useFocusTrap(panel, isOpen, {
  initialFocus: () => input.value,
  allowOutside: (node) => layer.contains(node),
})
useScrollLock(isOpen)

const duration = computed(() => (reduced.value ? 0 : { enter: 180, leave: 120 }))

/* ---------------------------------------------------------------- bajarish */

async function run(row: Row, newTab = false) {
  const item = row.item
  palette.addRecent(item, row.group)
  close()
  // Yopilish tugasin: fokus o'z joyiga qaytadi, keyin amal (u dialog ochishi mumkin).
  await nextTick()
  try {
    if (newTab && (item.to || item.href)) {
      const url = item.to ? router.resolve(item.to).href : item.href
      if (url) window.open(url, '_blank', 'noopener')
      return
    }
    if (item.run) await item.run()
    else if (item.to) await router.push(item.to)
    else if (item.href) window.location.assign(item.href)
  } catch (err) {
    console.error('[command-palette]', err)
  }
}

/* ---------------------------------------------------------------- klaviatura */

function setActive(i: number, scroll = true) {
  const row = flat.value[i]
  if (!row) return
  activeKey.value = row.key
  userMoved = true
  if (!scroll) return
  void nextTick(() => {
    // Birinchi qatorda guruh sarlavhasi ham ko'rinsin.
    if (i === 0 && body.value) body.value.scrollTop = 0
    else document.getElementById(optionId(i))?.scrollIntoView({ block: 'nearest' })
  })
}

function move(delta: number, wrap = true) {
  const n = flat.value.length
  if (!n) return
  const cur = activeIndex.value
  let next: number
  if (cur < 0) next = delta > 0 ? 0 : n - 1
  else if (wrap) next = (((cur + delta) % n) + n) % n
  else next = Math.min(n - 1, Math.max(0, cur + delta))
  setActive(next)
}

function onKeyDown(e: KeyboardEvent) {
  if (e.isComposing) return
  const ctrlOnly = e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      move(1)
      return
    case 'ArrowUp':
      e.preventDefault()
      move(-1)
      return
    case 'PageDown':
      e.preventDefault()
      move(5, false)
      return
    case 'PageUp':
      e.preventDefault()
      move(-5, false)
      return
    case 'Enter': {
      e.preventDefault()
      const newTab = e.metaKey || e.ctrlKey
      if (query.value !== shownQuery.value) {
        queuedEnter = { newTab }
        if (query.value !== lastSearched) search(query.value)
        return
      }
      const row = flat.value[activeIndex.value]
      if (row) void run(row, newTab)
      return
    }
    case 'Delete':
      removeActiveRecent(e)
      return
    case 'Backspace':
      if (matchesShortcut(e, 'mod+backspace')) removeActiveRecent(e)
      return
  }
  if (ctrlOnly && (e.code === 'KeyN' || e.code === 'KeyP')) {
    e.preventDefault()
    move(e.code === 'KeyN' ? 1 : -1)
  }
}

function removeActiveRecent(e: KeyboardEvent) {
  if (hasQuery.value) return
  const row = flat.value[activeIndex.value]
  if (!row?.recent) return
  e.preventDefault()
  const i = activeIndex.value
  palette.removeRecent(row.item.id)
  rebuild(shownQuery.value)
  setActive(Math.min(i, flat.value.length - 1))
}

/* sichqoncha: faqat haqiqiy harakatda (klaviatura aylantirganda kursor ostidagi qator
   ta'kidni "o'g'irlamasin" - brauzer aylantirishdan keyin soxta hodisa yuboradi) */
let lastPointer = { x: -1, y: -1 }
function onRowPointerMove(row: Row, e: PointerEvent) {
  if (e.clientX === lastPointer.x && e.clientY === lastPointer.y) return
  lastPointer = { x: e.clientX, y: e.clientY }
  if (activeKey.value !== row.key) setActive(row.index, false)
}

/* ---------------------------------------------------------------- belgilash */

interface Segment {
  text: string
  hit: boolean
}

function highlight(label: string): Segment[] {
  const tokens = normalizeSearch(shownQuery.value)
    .split(/\s+/)
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
  const norm = normalizeSearch(label)
  // Kichik harfga o'tkazish uzunlikni o'zgartirsa (kamdan-kam belgilar) - belgilamaymiz.
  if (!tokens.length || norm.length !== label.length) return [{ text: label, hit: false }]
  const marks: boolean[] = new Array(label.length).fill(false)
  for (const tok of tokens) {
    let from = 0
    while (from <= norm.length - tok.length) {
      const i = norm.indexOf(tok, from)
      if (i < 0) break
      if (!marks.slice(i, i + tok.length).some(Boolean)) {
        marks.fill(true, i, i + tok.length)
        break
      }
      from = i + 1
    }
  }
  const out: Segment[] = []
  for (let i = 0; i < label.length; i++) {
    const last = out[out.length - 1]
    if (last && last.hit === marks[i]) last.text += label[i]
    else out.push({ text: label[i], hit: marks[i] })
  }
  return out
}

/* ---------------------------------------------------------------- ekran o'quvchi */

const status = ref('')
let statusTimer: ReturnType<typeof setTimeout> | undefined
function announce(text: string, delay = 0) {
  clearTimeout(statusTimer)
  if (!delay) status.value = text
  else statusTimer = setTimeout(() => (status.value = text), delay)
}
// Har harfda e'lon qilinsa ekran o'quvchi "shovqin" qiladi - yozish to'xtagach bir marta.
watch([settled, stale, () => flat.value.length, shownQuery], () => {
  if (!isOpen.value || !settled.value || stale.value || !shownQuery.value.trim()) return
  const n = flat.value.length
  announce(n ? t('ui.resultCount', { n }, n) : t('ui.noResults'), 500)
})

onBeforeUnmount(() => {
  reset()
  clearTimeout(statusTimer)
})

// Oxirida va `immediate`: palitra o'rnatilmasdan oldin `open()` chaqirilgan bo'lsa ham
// qidiruv boshlansin (yuqoridagi barcha holat allaqachon e'lon qilingan).
watch(
  isOpen,
  (on) => {
    reset()
    if (on) {
      sections.value = []
      activeKey.value = null
      query.value = palette.initialQuery.value
      search(query.value)
    } else announce('')
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="v-cmdk" :duration="duration">
      <div v-if="isOpen" class="v-cmdk-root" :style="{ zIndex: layer.zIndex.value }">
        <div class="v-cmdk-scrim" aria-hidden="true" />
        <div
          ref="panel"
          class="v-cmdk"
          role="dialog"
          aria-modal="true"
          :aria-label="t('ui.commandPalette')"
          tabindex="-1"
          @focus="onPanelFocus"
        >
          <div class="v-cmdk__head">
            <span class="v-cmdk__lead" aria-hidden="true">
              <VSpinner v-if="pending > 0 && stale" :size="16" />
              <Search v-else :size="18" :stroke-width="1.75" />
            </span>
            <input
              ref="input"
              v-model="query"
              class="v-cmdk__input"
              type="text"
              role="combobox"
              aria-autocomplete="list"
              :aria-expanded="flat.length > 0 ? 'true' : 'false'"
              :aria-controls="flat.length > 0 ? listId : undefined"
              :aria-activedescendant="activeId"
              :aria-label="placeholder ?? t('ui.commandPlaceholder')"
              :placeholder="placeholder ?? t('ui.commandPlaceholder')"
              autocomplete="off"
              autocorrect="off"
              autocapitalize="off"
              spellcheck="false"
              enterkeyhint="go"
              @keydown="onKeyDown"
            />
            <button type="button" class="v-cmdk__close" :aria-label="t('ui.close')" @click="close">
              <VKbd class="v-cmdk__close-kbd" keys="esc" size="sm" aria-hidden="true" />
              <X class="v-cmdk__close-x" :size="18" :stroke-width="1.75" aria-hidden="true" />
            </button>
          </div>

          <div v-if="showBody" ref="body" class="v-cmdk__body" :class="{ 'is-stale': stale && pending > 0 }">
            <div v-if="flat.length" :id="listId" class="v-cmdk__list" role="listbox" :aria-label="t('ui.commandPalette')">
              <div
                v-for="sec in sections"
                :key="sec.key"
                class="v-cmdk__group"
                role="group"
                :aria-labelledby="sec.labelId"
              >
                <div :id="sec.labelId" class="v-cmdk__group-label" role="presentation">{{ sec.label }}</div>
                <div
                  v-for="row in sec.rows"
                  :id="optionId(row.index)"
                  :key="row.key"
                  class="v-cmdk__item"
                  :class="{ 'is-active': row.key === activeKey }"
                  role="option"
                  :aria-selected="row.key === activeKey ? 'true' : 'false'"
                  @pointermove="onRowPointerMove(row, $event)"
                  @pointerdown.prevent
                  @click="run(row, $event.metaKey || $event.ctrlKey)"
                >
                  <span class="v-cmdk__icon" aria-hidden="true">
                    <History v-if="row.recent" :size="16" :stroke-width="1.75" />
                    <component :is="row.item.icon" v-else-if="row.item.icon" :size="18" :stroke-width="1.75" />
                  </span>
                  <span class="v-cmdk__text">
                    <span class="v-cmdk__label">
                      <template v-for="(seg, i) in highlight(row.item.label)" :key="i">
                        <mark v-if="seg.hit" class="v-cmdk__mark">{{ seg.text }}</mark>
                        <template v-else>{{ seg.text }}</template>
                      </template>
                    </span>
                    <span v-if="row.item.sub" class="v-cmdk__sub">{{ row.item.sub }}</span>
                  </span>
                  <span v-if="row.item.hint" class="v-cmdk__hint">{{ row.item.hint }}</span>
                  <VKbd v-if="row.item.shortcut" class="v-cmdk__kbd" :keys="row.item.shortcut" size="sm" />
                  <CornerDownLeft class="v-cmdk__enter" :size="14" :stroke-width="1.75" aria-hidden="true" />
                </div>
              </div>
            </div>
            <p v-else-if="showEmpty" class="v-cmdk__empty">{{ t('ui.noResults') }}</p>
          </div>

          <footer class="v-cmdk__foot" aria-hidden="true">
            <span class="v-cmdk__tip"><VKbd :keys="['up', 'down']" size="sm" />{{ t('ui.navigate') }}</span>
            <span class="v-cmdk__tip"><VKbd keys="enter" size="sm" />{{ t('ui.open') }}</span>
            <span class="v-cmdk__tip"><VKbd keys="esc" size="sm" />{{ t('ui.close') }}</span>
          </footer>

          <div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ status }}</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.v-cmdk-root {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 20vh var(--s-4) var(--s-4);
}
.v-cmdk-scrim {
  position: absolute;
  inset: 0;
  background: var(--overlay);
}

/* Burchak --r-lg (16): ichki qatorlar --r-sm (8) + 8px ichki bo'shliq - konsentrik. */
.v-cmdk {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 640px;
  max-height: min(560px, calc(80vh - var(--s-4)));
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--e3);
  color: var(--text);
  overflow: hidden;
  outline: none;
}
.v-cmdk:focus-visible {
  outline: none;
}

/* ---- qidiruv qatori ---- */
.v-cmdk__head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  flex-shrink: 0;
  height: 56px;
  padding: 0 var(--s-3) 0 var(--s-5);
}
.v-cmdk__lead {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  color: var(--text-3);
}
.v-cmdk__input {
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: var(--fs-body-lg);
  letter-spacing: -0.011em;
  outline: none;
}
.v-cmdk__input:focus-visible {
  outline: none;
}
.v-cmdk__input::placeholder {
  color: var(--text-4);
  opacity: 1;
}
.v-cmdk__close {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  min-width: 32px;
  height: 32px;
  padding: 0 var(--s-1);
  border-radius: var(--r-sm);
  color: var(--text-3);
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-cmdk__close:hover {
    background: var(--fill);
    color: var(--text);
  }
}
.v-cmdk__close:focus-visible {
  border-radius: var(--r-sm);
}
.v-cmdk__close-x {
  display: none;
}

/* ---- natijalar ---- */
.v-cmdk__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--s-2);
  overflow-y: auto;
  overscroll-behavior: contain;
  border-top: 1px solid var(--line);
  transition: opacity var(--dur-1) var(--ease-out);
}
.v-cmdk__body.is-stale {
  opacity: 0.55;
}
.v-cmdk__group + .v-cmdk__group {
  margin-top: var(--s-2);
}
.v-cmdk__group-label {
  padding: var(--s-2) var(--s-3) var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  user-select: none;
}
.v-cmdk__item {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-height: 40px;
  padding: 0 var(--s-3);
  border-radius: var(--r-sm);
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  scroll-margin: var(--s-2);
}
.v-cmdk__item.is-active {
  background: var(--fill);
}
.v-cmdk__icon {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  color: var(--text-3);
  transition: color var(--dur-1) var(--ease-out);
}
.is-active .v-cmdk__icon {
  color: var(--text);
}
.v-cmdk__text {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
/* Joy yetmasa avval izoh qisqaradi, keyin nom. */
.v-cmdk__label,
.v-cmdk__sub {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.v-cmdk__label {
  flex: 0 1 auto;
}
.v-cmdk__sub {
  flex: 0 100 auto;
  color: var(--text-3);
  font-size: 13px;
}
.v-cmdk__mark {
  background: none;
  color: inherit;
  font-weight: 600;
}
.v-cmdk__hint {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}
.v-cmdk__kbd {
  flex-shrink: 0;
}
.v-cmdk__enter {
  flex-shrink: 0;
  color: var(--text-3);
  opacity: 0;
  transition: opacity var(--dur-1) var(--ease-out);
}
.is-active .v-cmdk__enter {
  opacity: 1;
}
.v-cmdk__empty {
  padding: var(--s-10) var(--s-4);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: center;
}

/* ---- klaviatura ishoralari ---- */
.v-cmdk__foot {
  display: flex;
  align-items: center;
  gap: var(--s-5);
  flex-shrink: 0;
  height: 40px;
  padding: 0 var(--s-5);
  border-top: 1px solid var(--line);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  user-select: none;
}
.v-cmdk__tip {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  white-space: nowrap;
}

/* Sensorli ekran: klaviatura ishoralari yo'q, "Esc" o'rniga ×, oyna tepada. */
@media (hover: none) {
  .v-cmdk__foot,
  .v-cmdk__enter {
    display: none;
  }
  .v-cmdk__close-kbd {
    display: none;
  }
  .v-cmdk__close-x {
    display: block;
  }
}
@media (max-width: 767.98px) {
  .v-cmdk-root {
    padding: var(--s-2) var(--s-2) 0;
  }
  .v-cmdk {
    max-height: min(560px, 72vh);
    max-height: min(560px, 72dvh);
  }
  .v-cmdk__head {
    padding-left: var(--s-4);
  }
  /* iOS 16px dan kichik shriftli maydonga fokusda sahifani kattalashtiradi. */
  .v-cmdk__input {
    font-size: 16px;
  }
}

/* ---- animatsiya ---- */
.v-cmdk-enter-active .v-cmdk-scrim {
  transition: opacity var(--dur-2) var(--ease-out);
}
.v-cmdk-leave-active .v-cmdk-scrim {
  transition: opacity var(--dur-1) var(--ease-out);
}
.v-cmdk-enter-from .v-cmdk-scrim,
.v-cmdk-leave-to .v-cmdk-scrim {
  opacity: 0;
}
.v-cmdk-enter-active .v-cmdk {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.v-cmdk-leave-active .v-cmdk {
  transition:
    opacity var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.v-cmdk-enter-from .v-cmdk,
.v-cmdk-leave-to .v-cmdk {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}
</style>
