<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Play, Plus, Trash2 } from 'lucide-vue-next'
import { ApiError } from '../../api/http'
import VButton from '../../ui/VButton.vue'
import VDialog from '../../ui/VDialog.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VInput from '../../ui/VInput.vue'
import VJson from '../../ui/VJson.vue'
import VSelect from '../../ui/VSelect.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { runPlayground } from '../api'
import type { PgInput, PgMessage, PgOutput, PgRunResult } from './types'

// Bitta agent bosqichi: kirishi (system prompt, xabarlar, modelga berilgan ma'lumot) tahrirlanadi,
// tanlangan model(lar) bilan qayta ishga tushiriladi, natija asl chiqish bilan yonma-yon.
// Model chaqiruvi PULLIK - tugmadan keyin tasdiq oynasi (server ham `confirm_cost` siz 428 qaytaradi).
// Vosita chaqiruvlari agentda BAJARILMAYDI - faqat ro'yxat bo'lib qaytadi.

const props = defineProps<{
  stage: string
  input: PgInput
  output?: PgOutput | null
  model?: string | null
  models: string[]
}>()

const { t } = useI18n({ useScope: 'global' })

const ROLES = ['system', 'user', 'assistant', 'tool']

const system = ref('')
const messages = ref<PgMessage[]>([])
const extraText = ref('')
const extraError = ref<string | null>(null)
const model = ref<string | null>(null)
const compare = ref<string | null>(null)
const temperature = ref<string | number | null>('')
const maxTokens = ref<string | number | null>('')
const confirmOpen = ref(false)
const running = ref(false)
const runError = ref<string | null>(null)
const results = ref<PgRunResult[]>([])
const costNote = ref('')

function reset() {
  system.value = typeof props.input.system === 'string' ? props.input.system : ''
  messages.value = Array.isArray(props.input.messages)
    ? props.input.messages.map((m) => ({ ...m, role: String(m.role ?? 'user'), content: contentText(m.content) }))
    : []
  extraText.value = props.input.extra === undefined ? '' : JSON.stringify(props.input.extra, null, 2)
  extraError.value = null
  model.value = props.model ?? props.models[0] ?? null
  compare.value = null
  results.value = []
  runError.value = null
}

/** Xabar matni ba'zan bo'laklar ro'yxati (multimodal shakl) - tahrir uchun bitta matn. */
function contentText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value == null) return ''
  return JSON.stringify(value, null, 2)
}

watch(() => [props.stage, props.input], reset, { immediate: true })

const modelOptions = computed(() => props.models.map((m) => ({ value: m, label: m })))
const compareOptions = computed(() => [
  { value: '', label: t('admin.playground.none') },
  ...props.models.filter((m) => m !== model.value).map((m) => ({ value: m, label: m })),
])
const roleOptions = ROLES.map((r) => ({ value: r, label: r }))
const callCount = computed(() => (compare.value ? 2 : 1))

function parseExtra(): { ok: boolean; value?: unknown } {
  const raw = extraText.value.trim()
  if (!raw) return { ok: true, value: undefined }
  try {
    return { ok: true, value: JSON.parse(raw) }
  } catch {
    return { ok: false }
  }
}

watch(extraText, () => {
  extraError.value = parseExtra().ok ? null : t('admin.playground.badJson')
})

function addMessage() {
  messages.value.push({ role: 'user', content: '' })
}

function removeMessage(index: number) {
  messages.value.splice(index, 1)
}

function editedInput(): PgInput {
  const extra = parseExtra()
  const out: PgInput = { ...props.input, system: system.value, messages: messages.value.map((m) => ({ ...m })) }
  if (extra.value === undefined) delete out.extra
  else out.extra = extra.value
  return out
}

const num = (v: string | number | null): number | null => {
  if (v === '' || v === null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

async function run() {
  confirmOpen.value = false
  if (extraError.value) return
  running.value = true
  runError.value = null
  try {
    const res = await runPlayground({
      stage: props.stage,
      input: editedInput(),
      model: model.value,
      compare_model: compare.value || null,
      params: { temperature: num(temperature.value), max_tokens: num(maxTokens.value) },
      confirm_cost: true,
    })
    results.value = res.runs
    costNote.value = res.cost_note
  } catch (e) {
    runError.value = e instanceof ApiError ? e.message : String(e)
  } finally {
    running.value = false
  }
}

function outputText(value: unknown): string | null {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && typeof (value as PgOutput).text === 'string') return (value as PgOutput).text!
  return null
}

defineExpose({ editedInput })
</script>

<template>
  <section class="pse" :aria-label="t('admin.playground.stageAria', { stage })">
    <div class="pse__grid">
      <div class="pse__inputs">
        <VTextarea v-model="system" :label="t('admin.playground.system')" :rows="8" :max-rows="24" />

        <div class="pse__msgs">
          <div class="pse__head">
            <span class="pse__label">{{ t('admin.playground.messages') }} · {{ messages.length }}</span>
            <VButton size="sm" variant="ghost" :icon="Plus" @click="addMessage">{{ t('admin.playground.addMessage') }}</VButton>
          </div>
          <div v-for="(m, i) in messages" :key="i" class="pse__msg">
            <div class="pse__msgbar">
              <VSelect v-model="m.role" :options="roleOptions" size="sm" :aria-label="t('admin.playground.role')" />
              <VIconButton :icon="Trash2" size="sm" :label="t('admin.playground.remove')" @click="removeMessage(i)" />
            </div>
            <VTextarea v-model="m.content" :rows="2" :max-rows="16" :aria-label="`${m.role} ${i + 1}`" />
          </div>
        </div>

        <VTextarea
          v-model="extraText"
          :label="t('admin.playground.extra')"
          :hint="t('admin.playground.extraHint')"
          :error="extraError"
          :rows="4"
          :max-rows="20"
          class="pse__mono"
        />
        <VJson v-if="input.tools" :data="input.tools" :expand-depth="0" :label="t('admin.playground.tools')" :max-height="240" />
      </div>

      <div class="pse__side">
        <VSelect v-model="model" :options="modelOptions" :label="t('admin.playground.model')" />
        <VSelect v-model="compare" :options="compareOptions" :label="t('admin.playground.compareWith')" />
        <div class="pse__row">
          <VInput v-model="temperature" type="number" :label="t('admin.playground.temperature')" placeholder="—" />
          <VInput v-model="maxTokens" type="number" :label="t('admin.playground.maxTokens')" placeholder="—" />
        </div>
        <VButton :icon="Play" :loading="running" :disabled="!!extraError || running" block @click="confirmOpen = true">
          {{ running ? t('admin.playground.running') : t('admin.playground.run') }}
        </VButton>
        <p v-if="runError" class="pse__error" role="alert">{{ runError }}</p>
      </div>
    </div>

    <div v-if="results.length || output" class="pse__results">
      <div v-if="output" class="pse__result">
        <div class="pse__rhead"><strong>{{ t('admin.playground.original') }}</strong> <span>{{ props.model }}</span></div>
        <pre v-if="outputText(output)" class="pse__pre">{{ outputText(output) }}</pre>
        <VJson v-else :data="output" :expand-depth="2" />
      </div>
      <div v-for="(r, i) in results" :key="i" class="pse__result" :class="{ 'is-error': !r.ok }">
        <div class="pse__rhead">
          <strong>{{ r.model || t('admin.playground.defaultModel') }}</strong>
          <span v-if="r.ok">{{ t('admin.playground.stats', { ms: r.ms ?? '—', inp: r.tokens_in ?? '—', out: r.tokens_out ?? '—' }) }}</span>
        </div>
        <p v-if="!r.ok" class="pse__error">{{ r.message }}</p>
        <template v-else>
          <pre v-if="outputText(r.output)" class="pse__pre">{{ outputText(r.output) }}</pre>
          <VJson v-else :data="r.output" :expand-depth="2" />
          <VJson
            v-if="r.tool_calls && r.tool_calls.length"
            :data="r.tool_calls"
            :expand-depth="1"
            :label="t('admin.playground.toolCalls')"
          />
        </template>
      </div>
      <p v-if="costNote" class="pse__note">{{ costNote }}</p>
    </div>

    <VDialog
      v-model:open="confirmOpen"
      :title="t('admin.playground.confirmTitle')"
      :description="t('admin.playground.confirmBody', { n: callCount, models: [model, compare].filter(Boolean).join(', ') || '—' })"
      size="sm"
    >
      <template #footer>
        <VButton variant="ghost" @click="confirmOpen = false">{{ t('admin.playground.cancel') }}</VButton>
        <VButton :icon="Play" @click="run">{{ t('admin.playground.confirm') }}</VButton>
      </template>
    </VDialog>
  </section>
</template>

<style scoped>
.pse { display: grid; gap: var(--s-6); }
.pse__grid { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: var(--s-6); align-items: start; }
.pse__inputs { display: grid; gap: var(--s-4); min-width: 0; }
.pse__side { display: grid; gap: var(--s-3); position: sticky; top: var(--s-4); }
.pse__row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-2); }
.pse__head, .pse__msgbar, .pse__rhead { display: flex; align-items: center; justify-content: space-between; gap: var(--s-2); }
.pse__label { font-size: var(--fs-body-sm); font-weight: 600; color: var(--text-2); }
.pse__msgs { display: grid; gap: var(--s-3); }
.pse__msg { display: grid; gap: var(--s-1_5); padding: var(--s-3); border: 1px solid var(--line); border-radius: var(--r-md); }
.pse__mono :deep(textarea) { font-family: var(--font-mono); font-size: var(--fs-mono); }
.pse__results { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--s-4); }
.pse__result { display: grid; gap: var(--s-2); align-content: start; padding: var(--s-4); border: 1px solid var(--line); border-radius: var(--r-md); min-width: 0; }
.pse__result.is-error { border-color: var(--crit, #c0392b); }
.pse__rhead span { font-size: var(--fs-caption); color: var(--text-3); }
.pse__pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: var(--fs-body-sm); line-height: var(--lh-body-sm); }
.pse__error { margin: 0; color: var(--crit, #c0392b); font-size: var(--fs-body-sm); }
.pse__note { grid-column: 1 / -1; margin: 0; font-size: var(--fs-caption); color: var(--text-3); }
@media (max-width: 900px) {
  .pse__grid { grid-template-columns: 1fr; }
  .pse__side { position: static; }
}
</style>
