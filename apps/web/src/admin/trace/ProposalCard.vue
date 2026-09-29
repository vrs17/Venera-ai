<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { TriangleAlert } from 'lucide-vue-next'
import VCard from '../../ui/VCard.vue'
import StatusDot from '../components/StatusDot.vue'
import type { StatusTone } from '../components/StatusDot.vue'

/**
 * Yordamchi taklif qilgan yozish amali (HRM/CRM) - FAQAT o'qish uchun xulosa: nima,
 * qaysi obyekt, qanday o'zgarish, ogohlantirishlar va hozirgi holati. Taklif kaliti
 * izga yozilmaydi (`recorder._on_proposal`) - shu sababli bu yerdan tasdiqlab bo'lmaydi.
 */
const props = defineProps<{
  payload: unknown
  status: string | null
}>()

const { t } = useI18n({ useScope: 'global' })

const p = computed<Record<string, unknown>>(() =>
  props.payload && typeof props.payload === 'object' && !Array.isArray(props.payload)
    ? (props.payload as Record<string, unknown>)
    : {},
)

/** Har qanday qiymat -> bitta o'qiladigan qator (obyekt - "kalit: qiymat"). */
function plain(v: unknown, depth = 0): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (depth > 1) return '…'
  if (Array.isArray(v)) return v.map((x) => plain(x, depth + 1)).join(', ')
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>
    // `{field, from, to}` - o'zgarishning odatiy shakli: "maydon: eski → yangi".
    if ('from' in o || 'to' in o) {
      const head = typeof o.field === 'string' ? `${o.field}: ` : ''
      return `${head}${plain(o.from, depth + 1)} → ${plain(o.to, depth + 1)}`
    }
    return Object.entries(o)
      .map(([k, x]) => `${k}: ${plain(x, depth + 1)}`)
      .join(', ')
  }
  return String(v)
}

const operation = computed(() => {
  const parts = [p.value.connector, p.value.operation].filter((x): x is string => typeof x === 'string' && !!x)
  return parts.map((x, i) => (i === 0 && parts.length > 1 ? x.toUpperCase() : x)).join(' · ')
})

const summary = computed(() => (typeof p.value.summary === 'string' ? p.value.summary : ''))

const changes = computed<[string, string][]>(() => {
  const c = p.value.changes
  if (c === undefined || c === null) return []
  if (Array.isArray(c)) return c.map((x, i) => [String(i + 1), plain(x)])
  if (typeof c === 'object') return Object.entries(c as Record<string, unknown>).map(([k, v]) => [k, plain(v)])
  return [['', plain(c)]]
})

const target = computed(() => (p.value.target === undefined ? '' : plain(p.value.target)))

const warnings = computed<string[]>(() => {
  const w = p.value.warnings
  if (!w) return []
  return (Array.isArray(w) ? w : [w]).map((x) => plain(x)).filter((x) => x && x !== '—')
})

const STATUS: Record<string, { tone: StatusTone; key: string }> = {
  pending: { tone: 'info', key: 'admin.trace.pending' },
  executed: { tone: 'good', key: 'actionDone' },
  failed: { tone: 'crit', key: 'actionFailed' },
  cancelled: { tone: 'neutral', key: 'actionCancelled' },
  expired: { tone: 'neutral', key: 'actionExpired' },
}
const status = computed(() => (props.status ? STATUS[props.status] : undefined))
</script>

<template>
  <VCard :title="t('admin.trace.proposal')" :heading-level="2">
    <template v-if="status" #actions>
      <StatusDot :status="status ? props.status : null" :tone="status.tone" :label="t(status.key)" />
    </template>
    <div class="pc">
      <p v-if="summary" class="pc-summary">{{ summary }}</p>
      <p v-if="operation" class="pc-op t-mono">{{ operation }}</p>
      <dl v-if="target || changes.length" class="pc-dl">
        <div v-if="target" class="pc-row">
          <dt>{{ t('actionTarget') }}</dt>
          <dd>{{ target }}</dd>
        </div>
        <div v-for="[k, v] in changes" :key="k" class="pc-row">
          <dt>{{ k && !/^\d+$/.test(k) ? k : t('actionChanges') }}</dt>
          <dd>{{ v }}</dd>
        </div>
      </dl>
      <div v-if="warnings.length" class="pc-warn" role="note">
        <TriangleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
        <ul>
          <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
        </ul>
      </div>
    </div>
  </VCard>
</template>

<style scoped>
.pc {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.pc-summary {
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.pc-op {
  color: var(--text-2);
}
.pc-dl {
  display: grid;
  gap: var(--s-2);
  margin: 0;
}
.pc-row {
  display: grid;
  grid-template-columns: minmax(96px, 32%) minmax(0, 1fr);
  gap: var(--s-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.pc-row dt {
  color: var(--text-3);
  overflow-wrap: anywhere;
}
.pc-row dd {
  margin: 0;
  color: var(--text);
  overflow-wrap: anywhere;
}
.pc-warn {
  display: flex;
  gap: var(--s-2);
  padding: var(--s-3);
  border-radius: var(--r-md);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.pc-warn svg {
  flex: none;
  margin-top: 2px;
}
.pc-warn ul {
  display: grid;
  gap: var(--s-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
