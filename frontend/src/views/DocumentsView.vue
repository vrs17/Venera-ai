<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { downloadDocument, generateDocument, getTemplate, listTemplates } from '../api/documents.api'
import { localizeApiError } from '../api/errors'
import type {
  DocumentGenerationResponse,
  DocumentTemplate,
  DocumentTemplateField,
  DocumentTemplateSummary,
} from '../types'
import { ArrowLeftIcon, CheckIcon, DownloadIcon, FileTextIcon } from '../icons'
import AmbientBackground from '../components/AmbientBackground.vue'
import AuthError from '../components/AuthError.vue'

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
// Dev-only: import.meta.env.DEV is true under `npm run dev` and statically false
// in production builds, so the sample-fill testing aid (button + handler) is
// dead-code-eliminated from the shipped bundle.
const isDev = import.meta.env.DEV

const templates = ref<DocumentTemplateSummary[]>([])
const loadingList = ref(true)
const listError = ref('')

const selected = ref<string | null>(null)
const template = ref<DocumentTemplate | null>(null)
const loadingTemplate = ref(false)

const values = ref<Record<string, string>>({})
const submitted = ref(false)
const generating = ref(false)
const formError = ref('')
const result = ref<DocumentGenerationResponse | null>(null)
const downloading = ref(false)

onMounted(loadTemplates)

async function loadTemplates() {
  loadingList.value = true
  listError.value = ''
  try {
    templates.value = await listTemplates()
  } catch (err) {
    listError.value = localizeApiError(err, t)
  } finally {
    loadingList.value = false
  }
}

// Fields grouped by their `group` heading, preserving first-seen order.
const groups = computed(() => {
  const tpl = template.value
  if (!tpl) return []
  const map = new Map<string, DocumentTemplateField[]>()
  for (const f of tpl.fields) {
    const g = f.group || ''
    if (!map.has(g)) map.set(g, [])
    map.get(g)!.push(f)
  }
  return [...map.entries()].map(([name, fields]) => ({ name, fields }))
})

async function selectTemplate(type: string) {
  if (selected.value === type) return
  selected.value = type
  template.value = null
  result.value = null
  submitted.value = false
  formError.value = ''
  values.value = {}
  loadingTemplate.value = true
  try {
    const tpl = await getTemplate(type)
    template.value = tpl
    const init: Record<string, string> = {}
    for (const f of tpl.fields) init[f.name] = ''
    values.value = init
  } catch (err) {
    formError.value = localizeApiError(err, t)
  } finally {
    loadingTemplate.value = false
  }
}

const missingSet = computed(() => new Set(result.value?.missingFields ?? []))

// Field values are always treated as strings (the contract is Record<string,
// string>). Critically, <input type="number"> makes Vue store a NUMBER, so we
// must coerce before any string op — calling .trim() on a number throws and was
// silently aborting generate().
function fieldValue(name: string): string {
  return String(values.value[name] ?? '').trim()
}

function fieldInvalid(f: DocumentTemplateField): boolean {
  // A backend-flagged missing field clears its highlight as soon as it's filled.
  if (missingSet.value.has(f.name) && !fieldValue(f.name)) return true
  return submitted.value && f.required && !fieldValue(f.name)
}

// Required fields still empty — drives validation AND the "fill these" message.
const missingRequired = computed(() => {
  const tpl = template.value
  if (!tpl) return []
  return tpl.fields.filter((f) => f.required && !fieldValue(f.name))
})
const clientValid = computed(() => missingRequired.value.length === 0)

function inputType(type: string): string {
  if (type === 'date' || type === 'number' || type === 'email') return type
  return 'text'
}

// Convenience for testing: fill every field with its example (or a type default).
function exampleFor(f: DocumentTemplateField): string {
  if (f.type === 'date') return '2026-01-01'
  if (f.type === 'number') return '1'
  if (f.type === 'email') return 'namuna@venera.uz'
  return 'Namuna'
}
function autofillExample() {
  const tpl = template.value
  if (!tpl) return
  const next: Record<string, string> = {}
  for (const f of tpl.fields) next[f.name] = f.example?.trim() || f.placeholder?.trim() || exampleFor(f)
  values.value = next
  submitted.value = false
  result.value = null
  formError.value = ''
}

async function generate() {
  if (!template.value || generating.value) return
  submitted.value = true
  formError.value = ''
  // Don't fail silently — name the empty required fields and jump to the first.
  if (!clientValid.value) {
    formError.value = t('fillRequired', { fields: missingRequired.value.map((f) => f.label).join(', ') })
    await nextTick()
    document.querySelector('.docs__field.is-invalid')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  generating.value = true
  result.value = null
  try {
    const fields: Record<string, string> = {}
    for (const f of template.value.fields) {
      const v = fieldValue(f.name)
      if (v) fields[f.name] = v
    }
    result.value = await generateDocument({ documentType: template.value.documentType, fields })
  } catch (err) {
    formError.value = localizeApiError(err, t)
  } finally {
    generating.value = false
  }
}

async function download() {
  const url = result.value?.downloadUrl
  if (!url) return
  downloading.value = true
  formError.value = ''
  try {
    await downloadDocument(url, `${result.value?.documentType || 'document'}.docx`)
  } catch (err) {
    formError.value = localizeApiError(err, t)
  } finally {
    downloading.value = false
  }
}

const isReady = computed(() => result.value?.status === 'READY')
</script>

<template>
  <div class="docs">
    <AmbientBackground />

    <header class="docs__bar">
      <button class="docs__back" :title="t('backToChat')" :aria-label="t('backToChat')" @click="router.push('/')">
        <ArrowLeftIcon :size="18" />
      </button>
      <span class="docs__title"><FileTextIcon :size="18" /> {{ t('documents') }}</span>
    </header>

    <div class="docs__scroll">
      <div class="docs__inner">
        <!-- Template list -->
        <AuthError :message="listError" />
        <div v-if="loadingList" class="docs__muted">{{ t('loading') }}</div>
        <div v-else-if="!templates.length && !listError" class="docs__muted">{{ t('noTemplates') }}</div>
        <div v-else class="docs__grid">
          <button
            v-for="tpl in templates"
            :key="tpl.documentType"
            class="docs__card"
            :class="{ 'is-selected': selected === tpl.documentType }"
            @click="selectTemplate(tpl.documentType)"
          >
            <span class="docs__card-title">{{ tpl.title }}</span>
            <span class="docs__card-desc">{{ tpl.description }}</span>
            <span class="docs__card-meta">{{
              t('fieldCounts', { required: tpl.requiredFieldCount, optional: tpl.optionalFieldCount })
            }}</span>
          </button>
        </div>

        <!-- Selected template form -->
        <div v-if="loadingTemplate" class="docs__muted docs__section">{{ t('loading') }}</div>
        <form v-else-if="template" class="docs__form docs__section" novalidate @submit.prevent="generate">
          <h2 class="docs__form-title">{{ template.title }}</h2>
          <p v-if="template.description" class="docs__form-desc">{{ template.description }}</p>

          <AuthError :message="formError" />

          <div v-for="g in groups" :key="g.name" class="docs__group">
            <h3 v-if="g.name" class="docs__group-title">{{ g.name }}</h3>
            <div class="docs__fields">
              <label v-for="f in g.fields" :key="f.name" class="docs__field" :class="{ 'is-invalid': fieldInvalid(f) }">
                <span class="docs__label">
                  {{ f.label }}
                  <span v-if="f.required" class="docs__req" aria-hidden="true">*</span>
                </span>
                <textarea
                  v-if="f.type === 'textarea'"
                  v-model="values[f.name]"
                  class="docs__input docs__textarea input-focus"
                  rows="3"
                  :required="f.required"
                  :aria-invalid="fieldInvalid(f) || undefined"
                  :placeholder="f.placeholder || f.example || ''"
                />
                <input
                  v-else
                  v-model="values[f.name]"
                  class="docs__input input-focus"
                  :type="inputType(f.type)"
                  :required="f.required"
                  :aria-invalid="fieldInvalid(f) || undefined"
                  :placeholder="f.placeholder || f.example || ''"
                />
              </label>
            </div>
          </div>

          <!-- Result banner -->
          <div v-if="result && !isReady && result.message" class="docs__result docs__result--warn">
            {{ result.message }}
          </div>

          <div class="docs__actions">
            <!-- Temporary testing aid — dev builds only (see isDev). -->
            <button
              v-if="isDev"
              type="button"
              class="docs__btn docs__btn--ghost docs__btn--dev"
              @click="autofillExample"
            >
              {{ t('autofillExample') }}
            </button>
            <button type="submit" class="docs__btn docs__btn--primary" :disabled="generating">
              {{ generating ? t('generating') : t('generate') }}
            </button>
          </div>

          <!-- Generated preview + download -->
          <div v-if="result && isReady" class="docs__output">
            <div class="docs__output-head">
              <span class="docs__output-title"><CheckIcon :size="16" stroke="currentColor" /> {{ result.message || t('generatedPreview') }}</span>
              <button
                v-if="result.downloadUrl"
                type="button"
                class="docs__btn docs__btn--primary"
                :disabled="downloading"
                @click="download"
              >
                <DownloadIcon :size="15" />
                {{ downloading ? t('downloading') : t('downloadDocx') }}
              </button>
            </div>
            <pre v-if="result.generatedText" class="docs__preview">{{ result.generatedText }}</pre>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.docs {
  position: relative;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-family: 'Figtree', sans-serif;
  display: flex;
  flex-direction: column;
}
.docs__bar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-sunken);
}
.docs__back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.docs__back:hover {
  background: var(--surface-hover);
  color: var(--text);
  border-color: var(--border-hover);
}
.docs__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.docs__scroll {
  position: relative;
  z-index: 1;
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
.docs__inner {
  max-width: 820px;
  margin: 0 auto;
}
.docs__muted {
  color: var(--text-secondary);
  font-size: 14px;
  padding: 8px 2px;
}
.docs__section {
  margin-top: 22px;
}
.docs__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.docs__card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface);
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}
.docs__card:hover {
  border-color: var(--border-hover);
  background: var(--surface-hover);
}
.docs__card.is-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.docs__card-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
}
.docs__card-desc {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.docs__card-meta {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-top: 2px;
}
.docs__form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 22px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background: var(--surface);
}
.docs__form-title {
  margin: 0;
  font-size: 19px;
  font-weight: 600;
  color: var(--text);
}
.docs__form-desc {
  margin: -8px 0 0;
  font-size: 13.5px;
  line-height: 1.5;
  color: var(--text-secondary);
}
.docs__group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.docs__group-title {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
}
.docs__fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.docs__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.docs__label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
}
.docs__req {
  color: var(--text-muted);
}
.docs__input {
  width: 100%;
  box-sizing: border-box;
  font-family: inherit;
  font-size: 14px;
  color: var(--text);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 9px 11px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.docs__textarea {
  resize: vertical;
  min-height: 64px;
}
.docs__field.is-invalid .docs__input {
  border-color: var(--bad-fg);
}
.docs__actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
/* Dev-only sample-fill button sits on the left; Generate stays on the right. */
.docs__btn--dev {
  margin-right: auto;
}
.docs__btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  border-radius: 999px;
  padding: 10px 20px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: filter 0.15s, opacity 0.15s;
}
.docs__btn--primary {
  background: var(--accent);
  color: var(--accent-contrast);
}
.docs__btn--primary:hover {
  filter: brightness(1.08);
}
.docs__btn--ghost {
  background: var(--surface);
  color: var(--text-secondary);
  border-color: var(--border);
}
.docs__btn--ghost:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.docs__btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.docs__result {
  font-size: 13.5px;
  line-height: 1.5;
  border-radius: 12px;
  padding: 10px 12px;
}
.docs__result--warn {
  color: var(--warn-fg);
  background: var(--warn-bg);
  border: 1px solid var(--warn-bd);
}
.docs__output {
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-top: 1px solid var(--border);
  padding-top: 16px;
}
.docs__output-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.docs__output-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ok-fg);
}
.docs__preview {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Figtree', sans-serif;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  max-height: 420px;
  overflow: auto;
}
@media (max-width: 560px) {
  .docs__fields {
    grid-template-columns: 1fr;
  }
}
</style>
