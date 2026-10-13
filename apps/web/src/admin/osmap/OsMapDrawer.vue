<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, X } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VCopy from '../../ui/VCopy.vue'
import VIconButton from '../../ui/VIconButton.vue'
import { KINDS, kindOf } from './kinds'
import ProbePanel from './ProbePanel.vue'
import type { OsCode, OsEdge, OsFlow, OsNode } from './types'

/**
 * O'ngdagi varaq: tanlangan qadam, chiziq yoki "oqim haqida".
 *
 * Qadam: izoh, ichki oqim tugmasi, model, promptlar (koddan so'zma-so'z + nusxa),
 * "qanday ishlaydi", "Sinab ko'rish" (qadamda `probe` bo'lsa - `ProbePanel`), "qanday
 * sinash" yo'riqnomasi, kalitlar, ulanishlar va kod parchalari (asosiy qator yoritilgan).
 * Chiziq: qayerdan-qayerga, qachon, nima olib o'tadi, kod. Oqim: sonlar, nima oqim bilan
 * keladi (jadval) va tekshiruv izohlari.
 *
 * Emits: `close`, `select-node`, `select-edge`, `open-flow`.
 */
const props = defineProps<{
  flows: OsFlow[]
  flow: OsFlow
  selection: { type: 'node' | 'edge' | 'flow'; id: string }
}>()
const emit = defineEmits<{
  close: []
  'select-node': [id: string]
  'select-edge': [id: string]
  'open-flow': [id: string]
}>()
const { t } = useI18n({ useScope: 'global' })

const edgeId = (e: OsEdge, i: number) => e.id || `${props.flow.id}#e${i}`
const edges = computed(() => props.flow.edges.map((e, i) => ({ ...e, id: edgeId(e, i) })))

/** Barcha oqimlardagi qadamlar - ulanishdagi narigi qadam nomi uchun. */
const nodeById = computed(() => {
  const map = new Map<string, OsNode>()
  for (const f of props.flows) for (const n of f.nodes) map.set(n.id, n)
  return map
})

const node = computed(() => (props.selection.type === 'node' ? props.flow.nodes.find((n) => n.id === props.selection.id) ?? null : null))
const edge = computed(() => (props.selection.type === 'edge' ? edges.value.find((e) => e.id === props.selection.id) ?? null : null))
const ins = computed(() => (node.value ? edges.value.filter((e) => e.to === node.value!.id) : []))
const outs = computed(() => (node.value ? edges.value.filter((e) => e.from === node.value!.id) : []))
const subflow = computed(() => (node.value?.subflow ? props.flows.find((f) => f.id === node.value!.subflow) ?? null : null))

const kind = computed(() => KINDS[kindOf(node.value?.kind)])
const kindName = computed(() => t(`admin.osmap.kind.${kindOf(node.value?.kind)}`))

/** "Qanday ishlaydi": qatorlarga bo'lingan bo'lsa - ro'yxat, aks holda bitta paragraf. */
const detailParts = computed(() =>
  String(node.value?.details || '')
    .split(/\n+/)
    .map((x) => x.replace(/^[-•*]\s*/, '').trim())
    .filter(Boolean),
)

function codeLines(c: OsCode): { n: number; text: string; hl: boolean }[] {
  if (!c.snippet) return []
  return c.snippet.split('\n').map((text, i) => ({ n: (c.snip_start || 1) + i, text, hl: (c.snip_start || 1) + i === c.line }))
}
const lineCount = (text: string) => (text ? text.split('\n').length : 0)
/** Tugma bitta qatorda qoladi (VButton) - uzun oqim nomi varaqni kengaytirib yubormasin. */
const short = (text: string) => (text.length > 40 ? `${text.slice(0, 39).trimEnd()}…` : text)

/* ---- oqim haqida ---- */
const llmNodes = computed(() => props.flow.nodes.filter((n) => n.kind === 'llm'))
const promptCount = computed(() => props.flow.nodes.reduce((a, n) => a + (n.prompts?.length || 0), 0))
const shortPath = (c: OsCode) => `${c.path.split('/').slice(-2).join('/')}:${c.line}`
</script>

<template>
  <aside class="od" :aria-label="node?.label || edge?.label || flow.title">
    <!-- ======================================== qadam -->
    <template v-if="node">
      <header class="od__head">
        <div class="od__titles">
          <span class="od__kind" :style="{ color: kind.color }">{{ kindName }}</span>
          <h2 class="od__title">{{ node.label }}</h2>
          <span class="od__id">{{ node.id }}</span>
        </div>
        <VIconButton :icon="X" size="sm" :label="t('admin.osmap.close')" @click="emit('close')" />
      </header>
      <div class="od__body">
        <p class="od__p">{{ node.summary }}</p>

        <div v-if="subflow">
          <VButton class="od__open" size="sm" variant="primary" :icon-end="ArrowRight" :title="subflow.title" @click="emit('open-flow', subflow.id)">
            {{ t('admin.osmap.openFlow', { name: short(subflow.title) }) }}
          </VButton>
        </div>

        <section v-if="node.model" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.model') }}</h4>
          <span class="od__model">{{ node.model }}</span>
        </section>

        <section v-if="node.prompts?.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.prompts') }} ({{ node.prompts.length }})</h4>
          <details v-for="(p, i) in node.prompts" :key="i" class="od__blk" :open="i === 0">
            <summary>
              <b>{{ p.title }}</b>
              <span>{{ p.host }}:{{ p.path }}:{{ p.start }}-{{ p.end }}</span>
            </summary>
            <div class="od__blk-tools">
              <span>
                {{ t('admin.osmap.promptMeta', { lines: lineCount(p.text), chars: p.text.length.toLocaleString() }) }}
                <template v-if="p.redacted"> · {{ t('admin.osmap.redacted') }}</template>
              </span>
              <VCopy :text="p.text" :label="t('admin.osmap.copy')" />
            </div>
            <pre class="od__code">{{ p.text }}</pre>
          </details>
        </section>

        <section v-if="detailParts.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.how') }}</h4>
          <p v-if="detailParts.length === 1" class="od__p">{{ detailParts[0] }}</p>
          <ul v-else class="od__list">
            <li v-for="(part, i) in detailParts" :key="i">{{ part }}</li>
          </ul>
        </section>

        <section v-if="node.probe" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.run') }}</h4>
          <ProbePanel :key="`${node.id}:${node.probe}`" :probe="node.probe" />
        </section>

        <section v-if="node.test_hook" class="od__sec">
          <h4 class="od__h">
            {{ t('admin.osmap.sec.test') }}
            <VBadge :tone="node.test_hook.safe_to_run_in_prod ? 'good' : 'warn'" size="sm">
              {{ node.test_hook.safe_to_run_in_prod ? t('admin.osmap.hook.safe') : t('admin.osmap.hook.unsafe') }}
            </VBadge>
          </h4>
          <dl class="od__kv">
            <dt>{{ t('admin.osmap.hook.run') }}</dt>
            <dd><span class="od__chip">{{ node.test_hook.callable }}</span></dd>
            <dt>{{ t('admin.osmap.hook.input') }}</dt>
            <dd>{{ node.test_hook.inputs }}</dd>
            <dt>{{ t('admin.osmap.hook.output') }}</dt>
            <dd>{{ node.test_hook.outputs }}</dd>
            <dt>{{ t('admin.osmap.hook.side') }}</dt>
            <dd>{{ node.test_hook.side_effects }}</dd>
          </dl>
        </section>

        <section v-if="node.flags?.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.flags') }}</h4>
          <div class="od__chips">
            <span v-for="f in node.flags" :key="f" class="od__chip">{{ f }}</span>
          </div>
        </section>

        <section v-if="ins.length || outs.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.connections') }}</h4>
          <div class="od__conn">
            <button v-for="e in ins" :key="e.id" type="button" @click="emit('select-edge', e.id)">
              <b>← {{ nodeById.get(e.from)?.label || e.from }}</b>
              <span>{{ e.label }}{{ e.condition ? ` · ${e.condition}` : '' }}</span>
            </button>
            <button v-for="e in outs" :key="e.id" type="button" @click="emit('select-edge', e.id)">
              <b>→ {{ nodeById.get(e.to)?.label || e.to }}</b>
              <span>{{ e.label }}{{ e.condition ? ` · ${e.condition}` : '' }}</span>
            </button>
          </div>
        </section>

        <section v-if="node.code?.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.code') }} ({{ node.code.length }})</h4>
          <details v-for="(c, i) in node.code" :key="i" class="od__blk">
            <summary>
              <b>{{ c.symbol || 'code' }}</b>
              <span>{{ c.host }}:{{ c.path }}:{{ c.line }}</span>
            </summary>
            <pre class="od__code"><template v-if="c.snippet"><span v-for="l in codeLines(c)" :key="l.n" class="od__ln" :class="{ 'is-hl': l.hl }"><span class="od__lnn">{{ l.n }}</span>{{ l.text || ' ' }}</span></template><template v-else>{{ t('admin.osmap.noSnippet') }}</template></pre>
          </details>
        </section>
      </div>
    </template>

    <!-- ======================================== chiziq -->
    <template v-else-if="edge">
      <header class="od__head">
        <div class="od__titles">
          <span class="od__kind od__kind--edge">{{ t('admin.osmap.connection') }}</span>
          <h2 class="od__title">{{ edge.label || t('admin.osmap.connection') }}</h2>
          <span class="od__id">{{ edge.from }} → {{ edge.to }}</span>
        </div>
        <VIconButton :icon="X" size="sm" :label="t('admin.osmap.close')" @click="emit('close')" />
      </header>
      <div class="od__body">
        <div class="od__conn">
          <button type="button" @click="emit('select-node', edge.from)">
            <b>{{ t('admin.osmap.fromNode', { name: nodeById.get(edge.from)?.label || edge.from }) }}</b>
            <span>{{ nodeById.get(edge.from)?.summary }}</span>
          </button>
          <button type="button" @click="emit('select-node', edge.to)">
            <b>{{ t('admin.osmap.toNode', { name: nodeById.get(edge.to)?.label || edge.to }) }}</b>
            <span>{{ nodeById.get(edge.to)?.summary }}</span>
          </button>
        </div>
        <section class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.details') }}</h4>
          <dl class="od__kv">
            <dt>{{ t('admin.osmap.when') }}</dt>
            <dd>{{ edge.condition || t('admin.osmap.always') }}</dd>
            <dt>{{ t('admin.osmap.carries') }}</dt>
            <dd>{{ edge.payload || '—' }}</dd>
          </dl>
        </section>
        <section v-if="edge.code?.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.code') }} ({{ edge.code.length }})</h4>
          <details v-for="(c, i) in edge.code" :key="i" class="od__blk" :open="i === 0">
            <summary>
              <b>{{ c.symbol || 'code' }}</b>
              <span>{{ c.host }}:{{ c.path }}:{{ c.line }}</span>
            </summary>
            <pre class="od__code"><template v-if="c.snippet"><span v-for="l in codeLines(c)" :key="l.n" class="od__ln" :class="{ 'is-hl': l.hl }"><span class="od__lnn">{{ l.n }}</span>{{ l.text || ' ' }}</span></template><template v-else>{{ t('admin.osmap.noSnippet') }}</template></pre>
          </details>
        </section>
      </div>
    </template>

    <!-- ======================================== oqim haqida -->
    <template v-else>
      <header class="od__head">
        <div class="od__titles">
          <span class="od__kind od__kind--flow">{{ t('admin.osmap.flowWord') }}</span>
          <h2 class="od__title">{{ flow.title }}</h2>
          <span class="od__id">{{ flow.id }}</span>
        </div>
        <VIconButton :icon="X" size="sm" :label="t('admin.osmap.close')" @click="emit('close')" />
      </header>
      <div class="od__body">
        <p v-if="flow.summary" class="od__p">{{ flow.summary }}</p>
        <section class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.numbers') }}</h4>
          <dl class="od__kv">
            <dt>{{ t('admin.osmap.steps') }}</dt>
            <dd>{{ flow.nodes.length }}</dd>
            <dt>{{ t('admin.osmap.sec.connections') }}</dt>
            <dd>{{ flow.edges.length }}</dd>
            <dt>{{ t('admin.osmap.llmCalls') }}</dt>
            <dd>
              {{ llmNodes.length }}<template v-if="llmNodes.length"> · {{ llmNodes.map((n) => n.label).join(', ') }}</template>
            </dd>
            <dt>{{ t('admin.osmap.sec.prompts') }}</dt>
            <dd>{{ promptCount }}</dd>
            <template v-if="flow.repo_state">
              <dt>{{ t('admin.osmap.codeAt') }}</dt>
              <dd>{{ flow.repo_state }}</dd>
            </template>
          </dl>
        </section>
        <section v-if="flow.streaming?.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.streams') }}</h4>
          <div class="od__scroll">
            <table class="od__table">
              <thead>
                <tr>
                  <th>{{ t('admin.osmap.segment') }}</th>
                  <th>{{ t('admin.osmap.streamsCol') }}</th>
                  <th>{{ t('admin.osmap.howCol') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in flow.streaming" :key="i">
                  <td>{{ row.segment }}</td>
                  <td :class="row.streams ? 'is-yes' : 'is-no'">{{ row.streams ? t('admin.osmap.yes') : t('admin.osmap.no') }}</td>
                  <td>
                    {{ row.how }}
                    <span v-if="row.code?.[0]" class="od__chip od__chip--block">{{ shortPath(row.code[0]) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section v-if="flow.gaps?.length" class="od__sec">
          <h4 class="od__h">{{ t('admin.osmap.sec.notes') }}</h4>
          <ul class="od__list od__list--gaps">
            <li v-for="(g, i) in flow.gaps" :key="i">{{ g }}</li>
          </ul>
        </section>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.od {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 6;
  display: flex;
  flex-direction: column;
  width: min(500px, 100%);
  border-left: 1px solid var(--line);
  background: var(--surface);
  box-shadow: var(--e2);
}
.od__head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--line);
}
.od__titles {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.od__kind {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.od__kind--edge {
  color: var(--info-text);
}
.od__kind--flow {
  color: var(--brand);
}
.od__title {
  margin: 2px 0 0;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}
.od__id {
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 11.5px;
  overflow-wrap: anywhere;
}
.od__body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 0;
  padding: 14px 16px 40px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.od__open {
  max-width: 100%;
}
.od__p {
  margin: 0;
  font-size: 14px;
  line-height: 1.55;
}
.od__sec {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.od__h {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.od__list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding-left: 18px;
  font-size: 13.5px;
  line-height: 1.5;
}
.od__list--gaps {
  color: var(--text-2);
}
.od__model {
  align-self: flex-start;
  padding: 4px 8px;
  border-radius: var(--r-sm);
  background: var(--brand-soft);
  color: var(--brand);
  font-family: var(--font-mono);
  font-size: 12.5px;
  overflow-wrap: anywhere;
}
.od__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.od__chip {
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: var(--fill);
  font-family: var(--font-mono);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.od__chip--block {
  display: inline-block;
  margin-top: 4px;
}
.od__blk {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.od__blk > summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  padding: 9px 12px;
  cursor: pointer;
}
.od__blk > summary b {
  font-size: 13px;
  font-weight: 600;
}
.od__blk > summary span {
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 11.5px;
  overflow-wrap: anywhere;
}
.od__blk-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 12px 8px;
  color: var(--text-3);
  font-size: 12px;
}
.od__code {
  max-height: 460px;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  border-top: 1px solid var(--line);
  border-radius: 0 0 var(--r-md) var(--r-md);
  background: var(--bg-subtle);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
/* Har qator - alohida blok: asosiy qator butun eni bo'ylab yoritiladi. */
.od__ln {
  display: block;
}
.od__ln.is-hl {
  background: color-mix(in srgb, var(--brand) 14%, transparent);
}
.od__lnn {
  display: inline-block;
  min-width: 3.2em;
  color: var(--text-4);
  user-select: none;
}
.od__conn {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.od__conn button {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--bg-subtle);
  text-align: start;
  cursor: pointer;
}
.od__conn button:hover {
  border-color: var(--line-strong);
  background: var(--fill-hover);
}
.od__conn b {
  font-size: 13px;
  font-weight: 600;
}
.od__conn span {
  color: var(--text-3);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.od__kv {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 6px 10px;
  margin: 0;
  font-size: 13px;
}
.od__kv dt {
  color: var(--text-3);
}
.od__kv dd {
  margin: 0;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.od__scroll {
  overflow-x: auto;
}
.od__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.od__table th,
.od__table td {
  padding: 6px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}
.od__table th {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.od__table .is-yes {
  color: var(--good-text);
  font-weight: 600;
}
.od__table .is-no {
  color: var(--text-3);
  font-weight: 600;
}
</style>
