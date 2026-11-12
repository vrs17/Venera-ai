<script setup lang="ts">
/**
 * Javob ostidagi dalil: tayyorlangan fayl, iqtibos qilingan hujjatlar va jonli
 * so'rovlar (HRM, CRM).
 *
 * NEGA KERAK. Bankda manbasiz javob - bu fikr. Yordamchi matnda hujjatni [1], [2],
 * so'rovni [T1] deb belgilaydi; bu yerda o'sha belgilar haqiqiy hujjat va so'rovga
 * aylanadi - javobga ishonmagan odam bahslashish o'rniga tekshira oladi.
 *
 * Ko'rinish jim: fayl - alohida karta (odam aynan shuni so'ragan), manbalar esa bitta
 * yig'iq qator ("3 manba"), bosilsa ro'yxat ochiladi. Hujjat OCHILADI (chat yonidagi
 * ko'ruvchida, iqtibos sahifasida); so'rovda ochiladigan narsa yo'q - u vaqtning bir
 * lahzasidagi chaqiruv, shuning uchun nomi va qisqa natijasi ko'rsatiladi. Qonun
 * moddasi (v2, `kind: "law"`) - LEX.UZ ga tashqi havola, yangi oynada.
 *
 * PLATFORMALAR (2026-10-10): so'rov qatorida "T1" o'rniga platforma belgisi (HRM, CRM) va
 * nomi (`components/chat/platforms.ts`). Eski javobdagi notanish tizim - umumiy belgi va
 * nom bilan (2026-11-12 da namoyish manbalari olib tashlangan).
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ChevronDown, CircleAlert, Download, FileText, Scale } from 'lucide-vue-next'
import { localizeApiError } from '../api/errors'
import type { AnswerArtifact, AnswerSource } from '../types'
import { downloadFile } from '../api/chat.api'
import { useDocViewer } from '../composables/useDocViewer'
import VButton from '../ui/VButton.vue'
import { useId } from '../ui/composables/useId'
import { isLaw, isLookup, lawSite, lawTitle, lawUrl, lookupMarker, lookupTitle } from './chat/sources'
import { platformIcon, platformOfSource } from './chat/platforms'

const props = defineProps<{
  sources?: AnswerSource[]
  artifact?: AnswerArtifact | null
}>()
const { t } = useI18n({ useScope: 'global' })
const { open: openDoc } = useDocViewer()
const listId = useId('answer-sources')

// Hujjatlar va qonun moddalari BITTA ro'yxatda: ular matnda bitta raqamlashni
// bo'lishadi (`[1]` - ichki qoida, `[2]` - Mehnat kodeksi moddasi).
const docs = computed(() => (props.sources ?? []).filter((s) => !isLookup(s)))
const calls = computed(() => (props.sources ?? []).filter(isLookup))
const count = computed(() => docs.value.length + calls.value.length)

/** Fayl havolalari. Backend qayta yoza olmagan havola `null` bo'lib keladi - o'lik
 *  tugma ko'rsatilmaydi. */
const files = computed(() => {
  const a = props.artifact
  if (!a) return []
  return [
    { kind: 'docx' as const, url: a.docx_url, label: 'DOCX' },
    { kind: 'pdf' as const, url: a.pdf_url, label: 'PDF' },
  ].filter((f): f is { kind: 'docx' | 'pdf'; url: string; label: string } => !!f.url)
})

/** Yig'iq qatordagi kichik doirachalar - birinchi uchtasi. Hujjat - raqami (matndagi ¹ bilan
 *  bir xil); so'rov - PLATFORMA BELGISI: "T1" matnda ko'rinmaydi, demak odamga hech narsa
 *  demaydi (UX ko'rigi, 2026-10-10). */
const preview = computed(() => [
  ...docs.value.map((s, i) => ({ key: `d${i}`, text: String(s.citation_index ?? i + 1), icon: null })),
  ...calls.value.map((s, i) => ({ key: `t${i}`, text: '', icon: platformIcon(platformOfSource(s)) })),
].slice(0, 3))

const open = ref(false)

function docName(source: AnswerSource): string {
  return source.title?.trim() || source.doc_id || t('sourceDocument')
}
function docMeta(source: AnswerSource): string {
  return [source.page ? t('sourcePage', { n: source.page }) : '', source.section?.trim() ?? '']
    .filter(Boolean)
    .join(' · ')
}
/** Qonun moddasi qatori: havola (faqat `https://`) va izoh ("LEX.UZ · qonunchilik"). */
function lawRow(source: AnswerSource): { url: string | null; caption: string } {
  const url = lawUrl(source)
  return { url, caption: t('chat.lawCaption', { site: lawSite(url) }) }
}

/** Parcha matni - xizmat yuborsa (hozircha ixtiyoriy maydon). */
function snippet(source: AnswerSource): string {
  const raw = (source as AnswerSource & { snippet?: unknown; text?: unknown }).snippet
    ?? (source as AnswerSource & { text?: unknown }).text
  return typeof raw === 'string' ? raw.trim() : ''
}

/** Yuklab olish sessiya tokeni bilan (fetch) - xato shu yerda ko'rinishi shart,
 *  aks holda tugma "o'lik" bo'lib tuyuladi. */
const failed = ref<string | null>(null)
const busy = ref<string | null>(null)

async function take(kind: string, url: string) {
  failed.value = null
  busy.value = kind
  const name = `${(props.artifact?.title || 'ariza').replace(/[^\w.\- ]+/g, '_')}.${kind}`
  try {
    await downloadFile(url, name)
  } catch (err) {
    failed.value = localizeApiError(err, t)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div v-if="count || files.length || failed" class="proof">
    <p v-if="failed" class="proof__error" role="alert">
      <CircleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
      <span>{{ failed }}</span>
    </p>

    <!-- Fayl birinchi: odam aynan shuni so'ragan, iqtiboslar ostida yo'qolib qolmasin. -->
    <div v-if="files.length" class="proof__file">
      <span class="proof__file-icon" aria-hidden="true"><FileText :size="18" :stroke-width="1.75" /></span>
      <span class="proof__file-title">{{ artifact?.title?.trim() || t('artifactReady') }}</span>
      <span class="proof__file-actions">
        <!-- Tugma, havola emas: faylga sessiya tokeni kerak, oddiy <a> uni yubora olmaydi. -->
        <VButton
          v-for="file in files"
          :key="file.kind"
          size="sm"
          variant="secondary"
          :icon="Download"
          :loading="busy === file.kind"
          :aria-label="t('artifactDownload', { format: file.label })"
          @click="take(file.kind, file.url)"
        >
          {{ file.label }}
        </VButton>
      </span>
    </div>

    <template v-if="count">
      <button
        type="button"
        class="proof__toggle"
        :aria-expanded="open ? 'true' : 'false'"
        :aria-controls="listId"
        @click="open = !open"
      >
        <span class="proof__stack" aria-hidden="true">
          <span v-for="m in preview" :key="m.key" class="proof__mini">
            <component :is="m.icon" v-if="m.icon" :size="11" :stroke-width="2" />
            <template v-else>{{ m.text }}</template>
          </span>
        </span>
        <span>{{ t('chat.sourceCount', { n: count }, count) }}</span>
        <ChevronDown class="proof__chev" :class="{ 'is-open': open }" :size="16" :stroke-width="1.75" aria-hidden="true" />
      </button>

      <div v-show="open" :id="listId" class="proof__panel">
        <ul v-if="docs.length" class="proof__list" :aria-label="t('sourcesDocuments')">
          <li v-for="(source, i) in docs" :key="`${source.doc_id ?? source.url ?? ''}-${source.citation_index ?? i}`">
            <!-- Qonun moddasi: ko'ruvchida EMAS, LEX.UZ da (yangi oynada) - `/doc/...` faqat
                 `doc_id` uchun. Havola faqat `https://` bo'lsa; aks holda oddiy matn. -->
            <template v-if="isLaw(source)">
              <a
                v-if="lawRow(source).url"
                class="proof__item is-link"
                :href="lawRow(source).url ?? undefined"
                target="_blank"
                rel="noopener noreferrer"
                :title="t('chat.lawOpen')"
              >
                <span class="proof__num">{{ source.citation_index ?? i + 1 }}</span>
                <span class="proof__body">
                  <span class="proof__name">{{ lawTitle(source, t('sourceDocument')) }}</span>
                  <span class="proof__meta">
                    <Scale class="proof__law-icon" :size="13" :stroke-width="1.75" aria-hidden="true" />{{ lawRow(source).caption }}
                  </span>
                </span>
                <ArrowUpRight class="proof__ext" :size="16" :stroke-width="1.75" aria-hidden="true" />
                <span class="sr-only">({{ t('chat.lawOpen') }})</span>
              </a>
              <div v-else class="proof__item">
                <span class="proof__num">{{ source.citation_index ?? i + 1 }}</span>
                <span class="proof__body">
                  <span class="proof__name">{{ lawTitle(source, t('sourceDocument')) }}</span>
                  <span class="proof__meta">
                    <Scale class="proof__law-icon" :size="13" :stroke-width="1.75" aria-hidden="true" />{{ lawRow(source).caption }}
                  </span>
                </span>
              </div>
            </template>
            <!-- Ko'ruvchini iqtibos sahifasida ochadi; yuklab olish - ko'ruvchi panelida. -->
            <button
              v-else-if="source.docUrl"
              type="button"
              class="proof__item is-link"
              :title="t('sourceOpen')"
              @click="openDoc(source)"
            >
              <span class="proof__num">{{ source.citation_index ?? i + 1 }}</span>
              <span class="proof__body">
                <span class="proof__name">{{ docName(source) }}</span>
                <span v-if="docMeta(source)" class="proof__meta">{{ docMeta(source) }}</span>
                <span v-if="snippet(source)" class="proof__snippet">{{ snippet(source) }}</span>
              </span>
            </button>
            <div v-else class="proof__item">
              <span class="proof__num">{{ source.citation_index ?? i + 1 }}</span>
              <span class="proof__body">
                <span class="proof__name">{{ docName(source) }}</span>
                <span v-if="docMeta(source)" class="proof__meta">{{ docMeta(source) }}</span>
                <span v-if="snippet(source)" class="proof__snippet">{{ snippet(source) }}</span>
              </span>
            </div>
          </li>
        </ul>
        <ul v-if="calls.length" class="proof__list" :aria-label="t('sourcesLookups')">
          <li v-for="(call, i) in calls" :key="lookupMarker(call, i)">
            <div class="proof__item">
              <!-- "T1" matnda ko'rinmaydi - raqam o'rnida platforma belgisi (qaysi tizimdan). -->
              <span class="proof__num proof__num--icon" :title="lookupMarker(call, i)">
                <component :is="platformIcon(platformOfSource(call))" :size="13" :stroke-width="1.75" aria-hidden="true" />
              </span>
              <span class="proof__body">
                <span class="proof__name">{{ lookupTitle(call, t) }}</span>
                <span v-if="call.status && call.status !== 'ok'" class="proof__meta is-bad">
                  <span class="proof__dot" aria-hidden="true" />{{ t('chat.lookupFailed') }} · {{ call.status }}
                </span>
                <span v-else-if="call.digest" class="proof__meta">{{ call.digest }}</span>
              </span>
            </div>
          </li>
        </ul>
      </div>
    </template>
  </div>
</template>

<style scoped>
.proof {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-3);
  margin-top: var(--s-4);
}

.proof__error {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.proof__error svg {
  flex-shrink: 0;
  margin-top: 2px;
}

/* Fayl kartasi */
.proof__file {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s-3);
  width: 100%;
  max-width: 480px;
  padding: var(--s-3) var(--s-3) var(--s-3) var(--s-4);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
.proof__file-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: var(--r-md);
  background: var(--fill);
  color: var(--text-2);
}
.proof__file-title {
  flex: 1 1 140px;
  min-width: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.proof__file-actions {
  display: flex;
  gap: var(--s-2);
}

/* Yig'iq manbalar qatori */
.proof__toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  height: 32px;
  padding: 0 var(--s-2) 0 var(--s-1_5);
  margin-left: calc(var(--s-1_5) * -1);
  border-radius: var(--r-sm);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .proof__toggle:hover {
    background: var(--fill);
    color: var(--text);
  }
}
.proof__stack {
  display: inline-flex;
}
.proof__mini {
  display: inline-grid;
  place-items: center;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  border: 2px solid var(--bg);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1;
}
.proof__mini + .proof__mini {
  margin-left: -6px;
}
.proof__chev {
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.proof__chev.is-open {
  transform: rotate(180deg);
}

.proof__panel {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  width: 100%;
}
.proof__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.proof__item {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
  width: 100%;
  padding: var(--s-2) var(--s-2);
  margin-left: calc(var(--s-2) * -1);
  border-radius: var(--r-md);
  text-align: left;
  color: var(--text);
}
.proof__item.is-link {
  cursor: pointer;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .proof__item.is-link:hover {
    background: var(--fill);
  }
}
.proof__num {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  min-width: 22px;
  height: 20px;
  margin-top: 1px;
  padding: 0 5px;
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1;
}
.proof__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.proof__name {
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.proof__meta {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  overflow-wrap: anywhere;
}
/* So'rov qatori: raqam o'rnida platforma belgisi. */
.proof__num--icon {
  padding: 0;
  color: var(--text-3);
}
.proof__meta.is-bad {
  color: var(--crit-text);
}
/* Qonun: tarozi belgisi izoh boshida, tashqi havola belgisi qator oxirida (yangi oyna). */
.proof__law-icon {
  flex-shrink: 0;
}
.proof__ext {
  flex-shrink: 0;
  margin-left: auto;
  margin-top: 2px;
  color: var(--text-3);
}
.proof__dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: var(--r-full);
  background: var(--crit);
}
.proof__snippet {
  display: -webkit-box;
  margin-top: 2px;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: 18px;
}
</style>
