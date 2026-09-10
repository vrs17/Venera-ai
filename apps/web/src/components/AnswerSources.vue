<script setup lang="ts">
/**
 * Proof under an answer: cited documents and HRM lookups.
 *
 * WHY THIS EXISTS AT ALL. In a bank an answer without a source is an opinion.
 * The assistant marks documents as [1], [2] and HRM lookups as [T1], [T2] in
 * the text; this turns those markers into the actual document and names the
 * lookup, so someone who does not believe the answer can check it instead of
 * arguing with it.
 *
 * The two kinds are shown differently on purpose. A document can be OPENED —
 * its PDF comes down through our own proxy, since it lives on a host the
 * browser cannot reach. An HRM lookup has nothing to open: it is a call that
 * happened at a moment in time, so it is named, not linked, and the digest
 * says what it returned.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { localizeApiError } from '../api/errors'
import type { AnswerArtifact, AnswerSource } from '../types'
import { downloadFile } from '../api/chat.api'

const props = defineProps<{
  sources?: AnswerSource[]
  artifact?: AnswerArtifact | null
}>()
const { t } = useI18n({ useScope: 'global' })

const docs = computed(() => (props.sources ?? []).filter((s) => s.kind !== 'hrm'))
const calls = computed(() => (props.sources ?? []).filter((s) => s.kind === 'hrm'))

/** Files the artifact actually has. A missing one is `null` — our backend
 *  removes links it could not rewrite rather than showing a dead one. */
const files = computed(() => {
  const a = props.artifact
  if (!a) return []
  return [
    { kind: 'docx' as const, url: a.docx_url, label: 'DOCX' },
    { kind: 'pdf' as const, url: a.pdf_url, label: 'PDF' },
  ].filter((f): f is { kind: 'docx' | 'pdf'; url: string; label: string } => !!f.url)
})

const anything = computed(() => docs.value.length || calls.value.length || files.value.length)

function label(source: AnswerSource): string {
  const marker = source.citation_index != null ? `[${source.citation_index}] ` : ''
  const name = source.title?.trim() || source.doc_id || t('sourceDocument')
  return `${marker}${name}${source.page ? `, ${t('sourcePage', { n: source.page })}` : ''}`
}

/** Downloads run through fetch (the session token), so a failure has to be
 *  shown here — a rejected promise nobody reads would look like a dead
 *  button. */
const failed = ref<string | null>(null)

async function take(url: string, filename: string) {
  failed.value = null
  try {
    await downloadFile(url, filename)
  } catch (err) {
    failed.value = localizeApiError(err, t)
  }
}

/** The marker as it appears IN THE ANSWER TEXT. The service sends it bare
 *  ("T1") while the answer cites it as "[T1]", so the brackets are added
 *  when they are missing - otherwise the reader has to guess that the "T1"
 *  in the list is the "[T1]" in the sentence above it. */
function marker(call: AnswerSource, index: number): string {
  const raw = call.marker?.trim() || `T${index + 1}`
  return raw.startsWith('[') ? raw : `[${raw}]`
}

/** File name for a cited document: its title, or the id as a fallback. */
function docName(source: AnswerSource): string {
  const base = (source.title?.trim() || source.doc_id || 'hujjat').replace(/[^\w.\- ]+/g, '_')
  return base.toLowerCase().endsWith('.pdf') ? base : `${base}.pdf`
}
</script>

<template>
  <div v-if="anything" class="proof">
    <p v-if="failed" class="proof__bad" role="alert">{{ failed }}</p>
    <!-- The application file first: it is the thing the person asked for,
         and a download they might miss under a list of citations. -->
    <div v-if="files.length" class="proof__files">
      <span class="proof__title">{{ artifact?.title?.trim() || t('artifactReady') }}</span>
      <!-- A button, not an <a>: the file needs the session token, which a
           plain link cannot send. -->
      <button
        v-for="file in files"
        :key="file.kind"
        type="button"
        class="proof__file"
        @click="take(file.url, `${(artifact?.title || 'ariza').replace(/[^\w.\- ]+/g, '_')}.${file.kind}`)"
      >
        {{ t('artifactDownload', { format: file.label }) }}
      </button>
    </div>

    <div v-if="docs.length" class="proof__group">
      <span class="proof__title">{{ t('sourcesDocuments') }}</span>
      <ul class="proof__list">
        <li v-for="(source, i) in docs" :key="source.doc_id || i">
          <button
            v-if="source.docUrl"
            type="button"
            class="proof__link"
            @click="take(source.docUrl, docName(source))"
          >
            {{ label(source) }}
          </button>
          <span v-else>{{ label(source) }}</span>
          <span v-if="source.section" class="proof__muted"> · {{ source.section }}</span>
        </li>
      </ul>
    </div>

    <div v-if="calls.length" class="proof__group">
      <span class="proof__title">{{ t('sourcesHrm') }}</span>
      <ul class="proof__list">
        <li v-for="(call, i) in calls" :key="(call.marker || '') + i">
          <span class="proof__marker">{{ marker(call, i) }}</span>
          <code class="proof__tool">{{ call.tool }}</code>
          <span v-if="call.status && call.status !== 'ok'" class="proof__bad"> · {{ call.status }}</span>
          <span v-else-if="call.digest" class="proof__muted"> · {{ call.digest }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.proof {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  font-size: 12.5px;
  line-height: 1.5;
}
.proof__group,
.proof__files {
  margin-top: 8px;
}
.proof__files {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.proof__title {
  display: block;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 3px;
}
.proof__files .proof__title {
  display: inline;
  margin-bottom: 0;
  text-transform: none;
  font-size: 12.5px;
  letter-spacing: normal;
  color: var(--text);
}
.proof__list {
  margin: 0;
  padding-left: 0;
  list-style: none;
}
.proof__list li {
  color: var(--text-secondary);
  padding: 1px 0;
  word-break: break-word;
}
.proof__link {
  font: inherit;
  padding: 0;
  cursor: pointer;
  background: none;
  border: none;
  text-align: left;
  color: var(--text);
  text-decoration: underline;
  text-decoration-color: var(--border-hover);
  text-underline-offset: 2px;
}
.proof__link:hover {
  text-decoration-color: currentColor;
}
.proof__marker {
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  margin-right: 5px;
}
.proof__tool {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: var(--text);
}
.proof__muted {
  color: var(--text-muted);
}
.proof__bad {
  color: var(--bad-fg);
}
.proof__file {
  font: inherit;
  cursor: pointer;
  padding: 3px 10px;
  border-radius: 999px;
  color: var(--text);
  background: var(--surface-hover);
  border: 1px solid var(--border);
}
.proof__file:hover {
  border-color: var(--border-hover);
}
</style>
