<script lang="ts">
import type { InjectionKey, Ref } from 'vue'

/** Alt+bosish: butun shoxni ochish/yopish - buyruq avloddan avlodga uzatiladi. */
const BULK: InjectionKey<Ref<{ v: number; open: boolean }>> = Symbol('vj-bulk')

/**
 * Sir bo'lishi mumkin bo'lgan kalitlar. Faqat SATR qiymat yashiriladi: `total_tokens: 812`
 * - hisob, sir emas.
 */
const SECRET_KEY = /pass(word|wd)?|secret|token|authori[sz]ation|api[-_]?key|cookie|session[-_]?id|private[-_]?key|credential/i
const REDACTED_VALUE = /^(\[?redacted\]?|\*{3,}|•{3,})$/i
const MASK = '••••'

function isSecret(key: string | number | undefined, value: unknown, extra: string[]): boolean {
  if (typeof value !== 'string' || value === '') return false
  if (REDACTED_VALUE.test(value)) return true
  if (key === undefined || typeof key === 'number') return false
  return SECRET_KEY.test(key) || extra.some((k) => k.toLowerCase() === key.toLowerCase())
}

/** Nusxa uchun ham yashirish - bufer orqali sir chiqib ketmasin. */
function redactDeep(value: unknown, extra: string[], key?: string | number, depth = 0): unknown {
  if (depth > 64) return '…'
  if (isSecret(key, value, extra)) return MASK
  if (Array.isArray(value)) return value.map((v, i) => redactDeep(v, extra, i, depth + 1))
  if (value && typeof value === 'object' && !(value instanceof Date)) {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value)) out[k] = redactDeep(v, extra, k, depth + 1)
    return out
  }
  return value
}
</script>

<script setup lang="ts">
import { computed, inject, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRight } from 'lucide-vue-next'
import VCopy from './VCopy.vue'

/**
 * JSON ko'ruvchi (trace dagi xom freymlar, API javoblari).
 *
 * Rang jim: kalitlar --text-3, satrlar --text, raqam/mantiqiy --info-text, null --text-4.
 * 2-darajadan chuqurroq tugunlar yopiq keladi (uzun freym ekranni to'ldirmasin);
 * Alt+bosish - butun shoxni ochadi/yopadi. Uzun satr qisqartiriladi, "yana" bilan ochiladi.
 * Sir kalitlari (parol, token...) `••••` bo'lib ko'rinadi va nusxada ham shunday.
 *
 * Komponent o'zini o'zi chaqiradi: ichki tugunlar uchun `depth`/`name` - ichki proplar.
 */
defineOptions({ name: 'VJson' })

const props = withDefaults(
  defineProps<{
    data: unknown
    /** Shu darajadan boshlab yopiq (ma'lumot ildizi - 0-daraja; 2 = ildiz va bolalari ochiq). */
    expandDepth?: number
    /** Qo'shimcha yashiriladigan kalitlar. */
    redact?: string[]
    /** Satr shundan uzun bo'lsa qisqartiriladi. */
    maxString?: number
    /** Ildizda nusxa tugmasi. */
    copyable?: boolean
    /** Ramkasiz (kartaning ichida). */
    bare?: boolean
    maxHeight?: number | string
    label?: string
    /** @internal */
    depth?: number
    /** @internal */
    name?: string | number
  }>(),
  { expandDepth: 2, redact: () => [], maxString: 160, copyable: true, depth: 0 },
)

const { t } = useI18n({ useScope: 'global' })

const isRoot = computed(() => props.depth === 0)

type Kind = 'object' | 'array' | 'string' | 'number' | 'boolean' | 'null' | 'other'
const kind = computed<Kind>(() => {
  const v = props.data
  if (v === null || v === undefined) return 'null'
  if (Array.isArray(v)) return 'array'
  if (v instanceof Date) return 'string'
  if (typeof v === 'object') return 'object'
  if (typeof v === 'string') return 'string'
  if (typeof v === 'number' || typeof v === 'bigint') return 'number'
  if (typeof v === 'boolean') return 'boolean'
  return 'other'
})

const entries = computed<[string | number, unknown][]>(() => {
  const v = props.data
  if (Array.isArray(v)) return v.map((x, i) => [i, x])
  if (kind.value === 'object') return Object.entries(v as Record<string, unknown>)
  return []
})

const isBranch = computed(() => (kind.value === 'object' || kind.value === 'array') && entries.value.length > 0)
const braces = computed(() => (kind.value === 'array' ? ['[', ']'] : ['{', '}']))

/* ---- ochiq/yopiq ---- */
const parentBulk = inject(BULK, null)
const inherited = parentBulk && parentBulk.value.v > 0 ? parentBulk.value.open : null
// Ma'lumotning ildizi depth=1 da (0 - ramka). Daraja L = depth - 1; L < expandDepth ochiq.
const open = ref(inherited ?? props.depth <= props.expandDepth)
const bulk = ref({ v: inherited === null ? 0 : 1, open: inherited ?? false })
provide(BULK, bulk)

if (parentBulk) {
  watch(
    () => parentBulk.value.v,
    () => {
      open.value = parentBulk.value.open
      bulk.value = { v: bulk.value.v + 1, open: parentBulk.value.open }
    },
  )
}

function onToggle(e: MouseEvent) {
  open.value = !open.value
  if (e.altKey) bulk.value = { v: bulk.value.v + 1, open: open.value }
}

/* ---- barg (leaf) qiymati ---- */
const secret = computed(() => isSecret(props.name, props.data, props.redact))

const fullText = computed(() => {
  const v = props.data
  if (v === undefined) return 'undefined'
  if (v === null) return 'null'
  if (v instanceof Date) return v.toISOString()
  if (typeof v === 'string') return v
  return String(v)
})

const expanded = ref(false)
const long = computed(() => kind.value === 'string' && fullText.value.length > props.maxString)
const shownText = computed(() => (long.value && !expanded.value ? fullText.value.slice(0, props.maxString).trimEnd() + '…' : fullText.value))

/* ---- nusxa ---- */
function serialized(): string {
  const clean = redactDeep(props.data, props.redact)
  if (typeof clean === 'string') return clean
  try {
    return JSON.stringify(clean, null, 2) ?? String(clean)
  } catch {
    return String(clean)
  }
}

const isIndex = computed(() => typeof props.name === 'number')
</script>

<template>
  <div v-if="isRoot" class="vj" :class="{ 'is-bare': bare, 'has-copy': copyable }" role="group" :aria-label="label">
    <div
      class="vj-scroll"
      :style="maxHeight !== undefined ? { maxHeight: typeof maxHeight === 'number' ? `${maxHeight}px` : maxHeight } : undefined"
    >
      <VJson
        :data="data"
        :expand-depth="expandDepth"
        :redact="redact"
        :max-string="maxString"
        :depth="1"
        :copyable="false"
      />
    </div>
    <div v-if="copyable" class="vj-copy">
      <VCopy :text="serialized" size="sm" tooltip-placement="left" />
    </div>
  </div>

  <!-- ichki tugun -->
  <div v-else class="vj-node">
    <template v-if="isBranch">
      <button type="button" class="vj-row vj-toggle" :aria-expanded="open" @click="onToggle">
        <ChevronRight class="vj-chev" :size="12" :stroke-width="2" aria-hidden="true" />
        <template v-if="name !== undefined">
          <span class="vj-key" :class="{ 'is-index': isIndex }">{{ name }}</span><span class="vj-punct">:</span>
        </template>
        <span class="vj-punct">{{ braces[0] }}</span>
        <template v-if="!open">
          <span class="vj-ellipsis">…</span><span class="vj-punct">{{ braces[1] }}</span>
          <span class="vj-count">{{ entries.length }}</span>
        </template>
      </button>
      <ul v-if="open" class="vj-children" role="list">
        <li v-for="[k, v] in entries" :key="k">
          <VJson
            :data="v"
            :name="k"
            :depth="depth + 1"
            :expand-depth="expandDepth"
            :redact="redact"
            :max-string="maxString"
            :copyable="false"
          />
        </li>
      </ul>
      <div v-if="open" class="vj-row vj-close"><span class="vj-punct">{{ braces[1] }}</span></div>
    </template>

    <div v-else class="vj-row vj-leaf">
      <template v-if="name !== undefined">
        <span class="vj-key" :class="{ 'is-index': isIndex }">{{ name }}</span><span class="vj-punct">:</span>
      </template>
      <span v-if="kind === 'object' || kind === 'array'" class="vj-punct">{{ braces[0] }}{{ braces[1] }}</span>
      <span v-else-if="secret" class="vj-val is-secret" :title="t('ui.redacted')">
        <span aria-hidden="true">••••</span><span class="sr-only">{{ t('ui.redacted') }}</span>
      </span>
      <span v-else class="vj-val" :class="`is-${kind}`">
        <template v-if="kind === 'string'">"{{ shownText }}"</template>
        <template v-else>{{ fullText }}</template>
        <button v-if="long" type="button" class="vj-more" @click="expanded = !expanded">
          {{ expanded ? t('ui.less') : t('ui.more') }}
        </button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.vj {
  position: relative;
  min-width: 0;
  background: var(--bg-subtle);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
  font-weight: 450;
  letter-spacing: 0;
  color: var(--text);
}
.vj.is-bare {
  background: none;
  border: 0;
  border-radius: 0;
}
.vj-scroll {
  overflow: auto;
  overscroll-behavior: contain;
  padding: var(--s-3) var(--s-3) var(--s-3) var(--s-2);
}
.vj.has-copy .vj-scroll {
  padding-right: 44px;
}
.vj.is-bare .vj-scroll {
  padding: 0;
}
.vj.is-bare.has-copy .vj-scroll {
  padding-right: 40px;
}
/* Nusxa tugmasi aylantirishda ham joyida (ramka burchagida). */
.vj-copy {
  position: absolute;
  top: var(--s-1_5);
  right: var(--s-1_5);
  z-index: 1;
}
.vj.is-bare .vj-copy {
  top: -6px;
  right: 0;
}
.vj-copy :deep(.v-icon-btn) {
  color: var(--text-3);
}

.vj-node {
  min-width: 0;
}
.vj-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  column-gap: var(--s-1_5);
  min-height: 20px;
  padding: 1px 0 1px var(--s-4);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.vj-toggle {
  position: relative;
  width: 100%;
  margin: 0;
  border-radius: 4px;
  font: inherit;
  color: inherit;
  text-align: start;
  cursor: pointer;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .vj-toggle:hover {
    background: var(--fill);
  }
}
.vj-toggle:focus-visible {
  outline-offset: 0;
}
.vj-chev {
  position: absolute;
  left: 2px;
  top: 4px;
  color: var(--text-3);
  transition: transform var(--dur-1) var(--ease-out);
}
.vj-toggle[aria-expanded='true'] .vj-chev {
  transform: rotate(90deg);
}

/* Ichki daraja: 16px surilish + jim yo'naltiruvchi chiziq. */
.vj-children {
  margin: 0 0 0 7px;
  padding: 0;
  list-style: none;
  border-left: 1px solid var(--line);
}
.vj-children > li {
  padding-left: 9px;
}

.vj-key {
  color: var(--text-3);
}
.vj-key.is-index {
  color: var(--text-4);
}
.vj-punct {
  color: var(--text-4);
}
.vj-key + .vj-punct {
  margin-left: -6px;
}
.vj-ellipsis {
  margin: 0 -4px;
  color: var(--text-3);
}
.vj-count {
  color: var(--text-4);
  font-size: 11px;
}

.vj-val {
  min-width: 0;
}
.vj-val.is-string {
  color: var(--text);
}
.vj-val.is-number,
.vj-val.is-boolean {
  color: var(--info-text);
}
.vj-val.is-null,
.vj-val.is-other {
  color: var(--text-4);
}
/* Yashirilgan sir - "yo'q" (null) emas, ma'lumot bor: o'qiladigan kulrang. */
.vj-val.is-secret {
  color: var(--text-3);
  letter-spacing: 0.08em;
  cursor: default;
}
.vj-more {
  margin-left: var(--s-1_5);
  padding: 0 var(--s-1);
  border-radius: 4px;
  font-family: var(--font-sans);
  font-size: var(--fs-caption);
  font-weight: 500;
  color: var(--text-2);
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
}
@media (hover: hover) {
  .vj-more:hover {
    color: var(--text);
    text-decoration-color: currentColor;
  }
}
</style>
