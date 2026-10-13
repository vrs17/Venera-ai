<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Play } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VCopy from '../../ui/VCopy.vue'
import VJson from '../../ui/VJson.vue'

/**
 * Sinov natijasi - turiga qarab o'qiladigan ko'rinish (matn bosqichlari, transkript,
 * prompt...). Backend shakli (`admin_probe.py`) o'zgarsa ham sahifa yiqilmasin: hamma
 * maydon xavfsiz o'qiladi, oxirida esa to'liq javob (`VJson`) doim bor.
 *
 * Props: `kind` (sinov turi), `result` (javobning `result` maydoni), `stage0` (brauzer
 * `prepareSpeech` natijasi, TTS uchun). Emits: `play` (kutish ovozi kaliti).
 */
const props = defineProps<{
  kind: string
  result: unknown
  stage0?: { text: string; shortened: boolean; ms: number } | null
}>()
const emit = defineEmits<{ play: [clip: string] }>()
const { t } = useI18n({ useScope: 'global' })

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : {})
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const str = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v))
const yes = (v: unknown) => (v === true ? t('admin.osmap.yes') : v === false ? t('admin.osmap.no') : str(v) || '—')

const r = computed(() => rec(props.result))
const error = computed(() => str(r.value.error))

/* ---- STT ---- */
const sttFacts = computed(() => {
  const fw = rec(r.value.forwarded)
  return [
    [t('admin.osmap.probe.provider'), str(r.value.provider)],
    [t('admin.osmap.probe.fallback'), yes(r.value.fallbackUsed)],
    ['backend', [str(r.value.backend), str(r.value.model)].filter(Boolean).join(' · ') || '—'],
    [t('admin.osmap.probe.forwarded'), `${str(fw.filename)} · ${str(fw.contentType)} · ${str(fw.bytes)} B`],
    [t('admin.osmap.probe.language'), str(r.value.language) || '—'],
    [t('admin.osmap.probe.duration'), r.value.durationSec != null ? `${str(r.value.durationSec)} s` : '—'],
    ['lowConfidence', yes(r.value.lowConfidence)],
    ['truncated', yes(r.value.truncated)],
  ]
})

/* ---- TTS bosqichlari ---- */
interface Stage {
  stage: string
  text: string
  changed: boolean
  extra: Rec
}
const stages = computed<Stage[]>(() => {
  const out: Stage[] = []
  if (props.stage0) {
    out.push({
      stage: t('admin.osmap.probe.stage0'),
      text: props.stage0.text,
      changed: true,
      extra: props.stage0.shortened ? { shortened: true } : {},
    })
  }
  for (const raw of list(r.value.stages)) {
    const s = rec(raw)
    const { stage, text, changed, ...extra } = s
    out.push({ stage: str(stage), text: str(text), changed: changed === true, extra })
  }
  return out
})

/* ---- uyg'otish ---- */
const words = computed(() => list(r.value.words).map(rec))

/* ---- kutish ---- */
const clips = computed(() => list(r.value.clips).map(rec))
const label = computed(() => rec(r.value.label))

/* ---- sog'lik ---- */
const services = computed(() => list(r.value.services).map(rec))
const warnings = computed(() => list(r.value.warnings).map(str))

/* ---- miya ---- */
const calls = computed(() => list(r.value.calls).map(rec))
const sent = computed(() => list(r.value.telegramWouldSend).map(str))
const fired = (v: unknown) => Object.entries(rec(v))
</script>

<template>
  <div class="pr">
    <p v-if="error" class="pr__err">{{ error }}</p>

    <!-- STT -->
    <template v-if="kind === 'stt' && !error">
      <blockquote class="pr__quote">{{ str(r.text) || '—' }}</blockquote>
      <dl class="pr__kv">
        <template v-for="[k, v] in sttFacts" :key="k">
          <dt>{{ k }}</dt>
          <dd>{{ v }}</dd>
        </template>
      </dl>
    </template>

    <!-- TTS: brauzer + server bosqichlari -->
    <ol v-else-if="(kind === 'tts-text' || kind === 'tts-speak') && stages.length" class="pr__stages">
      <li v-for="(s, i) in stages" :key="i" class="pr__stage" :class="{ 'is-final': i === stages.length - 1 }">
        <div class="pr__stage-head">
          <span class="pr__mono">{{ i === 0 && stage0 ? s.stage : `${i}. ${s.stage}` }}</span>
          <VBadge :tone="s.changed ? 'brand' : 'neutral'" size="sm">
            {{ s.changed ? t('admin.osmap.probe.changed') : t('admin.osmap.probe.same') }}
          </VBadge>
          <span v-for="(v, k) in s.extra" :key="k" class="pr__chip">{{ k }}: {{ str(v) }}</span>
        </div>
        <pre v-if="s.changed || i === stages.length - 1" class="pr__pre">{{ s.text }}</pre>
      </li>
    </ol>

    <!-- uyg'otish -->
    <template v-else-if="kind === 'wake'">
      <p class="pr__line">
        <VBadge :tone="r.matched ? 'good' : 'neutral'" size="sm" dot>
          {{ r.matched ? t('admin.osmap.probe.wakeYes') : t('admin.osmap.probe.wakeNo') }}
        </VBadge>
        <span>{{ str(r.reason) }}</span>
      </p>
      <dl class="pr__kv">
        <dt>heard</dt>
        <dd class="pr__mono">{{ str(r.heard) || '—' }}</dd>
        <dt>latin</dt>
        <dd class="pr__mono">{{ str(r.latin) || '—' }}</dd>
      </dl>
      <div v-if="words.length" class="pr__scroll">
        <table class="pr__table">
          <thead>
            <tr>
              <th>{{ t('admin.osmap.probe.word') }}</th>
              <th>barno</th>
              <th>venera</th>
              <th>{{ t('admin.osmap.probe.greeting') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(w, i) in words" :key="i">
              <td class="pr__mono">{{ str(w.word) }}<span v-if="w.latin !== w.word"> → {{ str(w.latin) }}</span></td>
              <td :class="{ 'is-yes': w.isBarno }">{{ str(w.distanceBarno) }}</td>
              <td :class="{ 'is-yes': w.isVenera }">{{ str(w.distanceVenera) }}</td>
              <td :class="{ 'is-yes': w.greeting }">{{ yes(w.greeting) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- kutish ovozi -->
    <template v-else-if="kind === 'hold'">
      <p class="pr__line">
        <span class="pr__chip">{{ str(label.topic) }} | {{ str(label.tone) }}</span>
        <span class="pr__muted">{{ t('admin.osmap.probe.source') }}: {{ str(r.source) }} · mode: {{ str(r.mode) }}</span>
      </p>
      <ol class="pr__clips">
        <li v-for="c in clips" :key="str(c.clip)">
          <div class="pr__line">
            <span class="pr__mono">#{{ str(c.at) }} {{ str(c.stage) }} · {{ str(c.afterMs) }} ms</span>
            <VBadge :tone="c.ready ? 'good' : 'warn'" size="sm">
              {{ c.ready ? t('admin.osmap.probe.ready') : t('admin.osmap.probe.notReady') }}
            </VBadge>
            <VButton v-if="c.ready" size="sm" variant="ghost" :icon="Play" @click="emit('play', str(c.clip))">
              {{ t('admin.osmap.probe.play') }}
            </VButton>
          </div>
          <p class="pr__text">{{ str(c.text) }}</p>
          <span class="pr__muted pr__mono">{{ str(c.url) }}</span>
        </li>
      </ol>
    </template>

    <!-- niqob -->
    <template v-else-if="kind === 'mask'">
      <h6 class="pr__h">{{ t('admin.osmap.probe.masked') }}</h6>
      <pre class="pr__pre">{{ str(r.masked) }}</pre>
      <p class="pr__line">
        <span v-for="[k, n] in fired(r.fired)" :key="k" class="pr__chip">{{ k }} × {{ str(n) }}</span>
      </p>
      <h6 class="pr__h">{{ t('admin.osmap.probe.secretsOnly') }}</h6>
      <pre class="pr__pre">{{ str(rec(r.secretsOnly).masked) }}</pre>
    </template>

    <!-- sog'lik -->
    <template v-else-if="kind === 'health'">
      <div class="pr__scroll">
        <table class="pr__table">
          <tbody>
            <tr v-for="s in services" :key="str(s.name)">
              <td class="pr__mono">{{ str(s.name) }}</td>
              <td :class="{ 'is-yes': s.status === 'ok', 'is-bad': s.status !== 'ok' && s.status !== 'off' }">{{ str(s.status) }}</td>
              <td class="pr__num">{{ str(s.ms) }} ms</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ul v-if="warnings.length" class="pr__warn">
        <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
      </ul>
    </template>

    <!-- agent -->
    <template v-else-if="kind === 'agent'">
      <dl class="pr__kv">
        <dt>enabled</dt>
        <dd>{{ yes(r.enabled) }}</dd>
        <dt>usable</dt>
        <dd>{{ yes(r.usable) }}{{ r.reason ? ` (${str(r.reason)})` : '' }}</dd>
      </dl>
      <VJson v-if="r.capabilities" :data="r.capabilities" label="capabilities" :expand-depth="1" />
      <VJson v-if="r.limits" :data="r.limits" label="limits" :expand-depth="1" />
    </template>

    <!-- miya -->
    <template v-else-if="kind === 'brain'">
      <p class="pr__line">
        <span class="pr__chip">route: {{ str(rec(r.route).effective) }}</span>
        <span v-if="rec(r.route).reason" class="pr__muted">{{ str(rec(r.route).reason) }}</span>
        <span v-if="r.model" class="pr__chip">{{ str(r.model) }}</span>
        <span v-if="r.skipped" class="pr__chip">skipped: {{ str(r.skipped) }}</span>
      </p>
      <template v-if="r.question">
        <h6 class="pr__h">{{ t('admin.osmap.probe.question') }}</h6>
        <pre class="pr__pre">{{ str(r.question) }}</pre>
      </template>
      <details v-for="(c, i) in calls" :key="i" class="pr__call" :open="i === 0">
        <summary>
          <b>{{ str(c.op) }}</b>
          <span class="pr__muted">
            num_predict {{ str(c.num_predict) || '—' }} · temperature {{ str(c.temperature) || '—' }}
            {{ c.format ? `· ${str(c.format)}` : '' }}{{ c.ms != null ? ` · ${str(c.ms)} ms` : '' }}
          </span>
        </summary>
        <div class="pr__call-body">
          <div class="pr__line">
            <h6 class="pr__h">{{ t('admin.osmap.probe.system') }}</h6>
            <VCopy :text="str(c.system)" />
          </div>
          <pre class="pr__pre">{{ str(c.system) }}</pre>
          <div class="pr__line">
            <h6 class="pr__h">{{ t('admin.osmap.probe.user') }}</h6>
            <VCopy :text="str(c.user)" />
          </div>
          <pre class="pr__pre">{{ str(c.user) }}</pre>
          <template v-if="c.output != null">
            <h6 class="pr__h">{{ t('admin.osmap.probe.output') }}</h6>
            <pre class="pr__pre">{{ str(c.output) }}</pre>
          </template>
        </div>
      </details>
      <template v-if="sent.length">
        <h6 class="pr__h">{{ t('admin.osmap.probe.telegram') }}</h6>
        <pre v-for="(m, i) in sent" :key="i" class="pr__pre">{{ m }}</pre>
      </template>
      <VJson v-if="r.events" :data="r.events" label="events" :expand-depth="1" />
      <VJson v-if="r.request" :data="r.request" label="request" :expand-depth="2" />
      <VJson v-if="r.agentRequest" :data="r.agentRequest" :label="t('admin.osmap.probe.agentRequest')" :expand-depth="1" />
    </template>

    <details class="pr__raw">
      <summary>{{ t('admin.osmap.probe.raw') }}</summary>
      <VJson :data="result" bare :expand-depth="1" />
    </details>
  </div>
</template>

<style scoped>
.pr {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  font-size: 13px;
}
.pr__err {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--r-sm);
  background: var(--crit-soft);
  color: var(--crit-text);
}
.pr__quote {
  margin: 0;
  padding: 8px 12px;
  border-left: 3px solid var(--brand);
  background: var(--surface);
  font-size: 14px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.pr__kv {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 4px 12px;
  margin: 0;
}
.pr__kv dt {
  color: var(--text-3);
}
.pr__kv dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.pr__mono {
  font-family: var(--font-mono);
  font-size: 12px;
}
.pr__muted {
  color: var(--text-3);
  font-size: 12px;
}
.pr__line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
}
.pr__chip {
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: var(--surface);
  font-family: var(--font-mono);
  font-size: 11.5px;
  overflow-wrap: anywhere;
}
.pr__pre {
  max-height: 360px;
  margin: 0;
  padding: 8px 10px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.pr__stages,
.pr__clips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.pr__stage {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pr__stage.is-final .pr__pre {
  border-color: var(--brand);
}
.pr__stage-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.pr__text {
  margin: 2px 0;
}
.pr__h {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.pr__scroll {
  overflow-x: auto;
}
.pr__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.pr__table th,
.pr__table td {
  padding: 4px 6px;
  border-bottom: 1px solid var(--line);
  text-align: left;
}
.pr__table th {
  color: var(--text-3);
  font-weight: 600;
}
.pr__table .is-yes {
  color: var(--good-text);
  font-weight: 600;
}
.pr__table .is-bad {
  color: var(--crit-text);
  font-weight: 600;
}
.pr__num {
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.pr__warn {
  margin: 0;
  padding-left: 18px;
  color: var(--warn-text);
}
.pr__call {
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface);
}
.pr__call > summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
}
.pr__call-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0 10px 10px;
}
.pr__raw > summary {
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
}
</style>
