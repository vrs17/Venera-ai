<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpen, ExternalLink, FileSearch, Scale } from 'lucide-vue-next'
import { lawSite, lookupLabel } from '../../components/chat/sources'
import { useDocViewer } from '../../composables/useDocViewer'
import VEmpty from '../../ui/VEmpty.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VMeter from '../../ui/charts/VMeter.vue'
import { fmtNumber } from '../../ui/format'
import type { TurnSource } from '../types'
import StatusDot from '../components/StatusDot.vue'
import { platformIcon, platformName } from '../../components/chat/platforms'
import { fromTurnSource, isExternalSource, isGuideKind, isToolSource, turnLawUrl } from './answerSources'

/**
 * "Manbalar" yorlig'i: topilgan hujjat parchalari (nom, kalit, sahifa, moslik bali,
 * parcha matni, hujjatni ochish) va platforma chaqiruvlari (vosita, holat, natija).
 * Tartib - javobdagi `[n]` tartibi (server `idx` bo'yicha beradi).
 *
 * Qonun moddasi (`kind: "law"`, v2) hujjatlar qatorida (raqamlash umumiy), lekin
 * ko'ruvchida emas - LEX.UZ da yangi oynada ochiladi; havola faqat `https://` bo'lsa.
 */
const props = defineProps<{ sources: TurnSource[] }>()

const { t, locale } = useI18n({ useScope: 'global' })
const { open } = useDocViewer()

const docs = computed(() => props.sources.filter((s) => !isToolSource(s.kind)))
const tools = computed(() => props.sources.filter((s) => isToolSource(s.kind)))

// Qayta saralash (rerank) bali 1 dan oshishi mumkin - shkala eng kattasiga moslashadi.
const scoreMax = computed(() => Math.max(1, ...docs.value.map((s) => (typeof s.score === 'number' ? s.score : 0))))
const scoreText = (v: number) => fmtNumber(v, locale.value, { digits: 3 })

const expanded = ref(new Set<number>())
const LONG = 220
function toggle(idx: number) {
  const next = new Set(expanded.value)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  expanded.value = next
}

function openDoc(s: TurnSource) {
  open(fromTurnSource(s))
}

const toolName = (s: TurnSource) => lookupLabel(fromTurnSource(s), s.ref ?? '', t)

/** Qonun / qo'llanma qatori uchun: havola (yoki null) va izoh ("LEX.UZ · qonunchilik" yoki
 *  platforma nomi - "Biznes 24/7 qo'llanmalari"). */
function law(s: TurnSource): { url: string | null; caption: string } {
  const url = turnLawUrl(s)
  if (isGuideKind(s.kind)) return { url, caption: platformName(s.kind, t) }
  return { url, caption: t('chat.lawCaption', { site: lawSite(url) }) }
}

// Vosita holati ba'zan so'z (`ok`/`error`), ba'zan HTTP kodi (`200`, `502`) bo'lib keladi.
function toolStatus(s: TurnSource): { status: string; label?: string } | null {
  const raw = s.status?.trim()
  if (!raw) return null
  if (/^\d{3}$/.test(raw)) {
    return Number(raw) < 400 ? { status: 'ok' } : { status: 'error', label: `${t('admin.status.error')} · ${raw}` }
  }
  return { status: raw }
}
</script>

<template>
  <div class="ts">
    <VEmpty v-if="!sources.length" compact :icon="FileSearch" :title="t('admin.trace.noSources')" />

    <section v-if="docs.length" class="ts-group" :aria-label="t('admin.trace.docs')">
      <h3 v-if="tools.length" class="ts-heading">{{ t('admin.trace.docs') }}</h3>
      <ol class="ts-list">
        <li v-for="s in docs" :key="s.idx" class="ts-item">
          <span class="ts-cite" aria-hidden="true">{{ s.citation ?? s.idx + 1 }}</span>
          <div class="ts-main">
            <p class="ts-title">{{ s.title || s.ref || t('sourceDocument') }}</p>
            <template v-if="isExternalSource(s.kind)">
              <p class="ts-meta ts-law">
                <!-- Qo'llanma - platforma belgisi (kitob, qutqaruv halqasi), qonun - tarozi. -->
                <component :is="isGuideKind(s.kind) ? platformIcon(s.kind) : Scale" :size="13" :stroke-width="1.75" aria-hidden="true" />
                <span>{{ law(s).caption }}</span>
              </p>
              <p v-if="s.ref" class="ts-meta t-mono">{{ s.ref }}</p>
            </template>
            <p v-else-if="s.ref || s.page" class="ts-meta">
              <span v-if="s.ref" class="t-mono">{{ s.ref }}</span>
              <span v-if="s.ref && s.page" aria-hidden="true"> · </span>
              <span v-if="s.page">{{ t('sourcePage', { n: s.page }) }}</span>
            </p>
            <div v-if="typeof s.score === 'number'" class="ts-score">
              <VMeter
                class="ts-meter"
                :value="s.score"
                :max="scoreMax"
                size="sm"
                :label="t('admin.trace.score')"
                :value-text="scoreText(s.score)"
              />
              <span class="ts-score-v">{{ scoreText(s.score) }}</span>
            </div>
            <template v-if="s.snippet">
              <p class="ts-snippet" :class="{ 'is-open': expanded.has(s.idx) }">{{ s.snippet }}</p>
              <button
                v-if="s.snippet.length > LONG"
                type="button"
                class="ts-more"
                :aria-expanded="expanded.has(s.idx)"
                @click="toggle(s.idx)"
              >
                {{ expanded.has(s.idx) ? t('ui.less') : t('ui.more') }}
              </button>
            </template>
          </div>
          <!-- Qonun: LEX.UZ (yangi oyna, rel=noopener noreferrer - VIconButton qo'yadi). -->
          <VIconButton
            v-if="isExternalSource(s.kind) && law(s).url"
            class="ts-open"
            :icon="ExternalLink"
            size="sm"
            :href="law(s).url ?? undefined"
            target="_blank"
            :label="t('chat.lawOpen')"
          />
          <VIconButton
            v-else-if="s.ref && !isExternalSource(s.kind)"
            class="ts-open"
            :icon="BookOpen"
            size="sm"
            :label="t('admin.trace.openDoc')"
            @click="openDoc(s)"
          />
        </li>
      </ol>
    </section>

    <section v-if="tools.length" class="ts-group" :aria-label="t('sourcesLookups')">
      <h3 class="ts-heading">{{ t('sourcesLookups') }}</h3>
      <ol class="ts-list">
        <li v-for="s in tools" :key="s.idx" class="ts-item">
          <span class="ts-cite is-tool" aria-hidden="true">{{ s.citation != null ? `T${s.citation}` : 'T' }}</span>
          <div class="ts-main">
            <p class="ts-title">{{ toolName(s) }}</p>
            <p v-if="s.ref" class="ts-meta t-mono">{{ s.ref }}</p>
            <p v-if="s.digest" class="ts-digest">{{ s.digest }}</p>
          </div>
          <StatusDot
            v-if="toolStatus(s)"
            class="ts-status"
            :status="toolStatus(s)?.status"
            :label="toolStatus(s)?.label"
          />
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.ts {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
}
.ts-group {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.ts-heading {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.ts-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.ts-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--s-3);
  align-items: start;
  padding: var(--s-3) 0;
  border-bottom: 1px solid var(--line);
}
.ts-item:first-child {
  padding-top: 0;
}
.ts-item:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

/* Javobdagi chip bilan bir xil ko'rinish - "[1]" qaysi parcha ekani darhol tanilsin. */
.ts-cite {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  height: 20px;
  margin-top: 1px;
  padding: 0 5px;
  border-radius: var(--r-xs);
  background: var(--fill);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
}

.ts-main {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
}
.ts-title {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.ts-meta {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  overflow-wrap: anywhere;
}
.ts-law {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
}
.ts-law svg {
  flex-shrink: 0;
}
.ts-score {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin-top: var(--s-1);
}
.ts-meter {
  flex: 0 1 120px;
}
/* Ball - son, identifikator emas: Inter tabular ("0,94" mono'da "0 , 94" bo'lib qolardi). */
.ts-score-v {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.ts-snippet,
.ts-digest {
  margin-top: var(--s-1);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
  white-space: pre-line;
}
.ts-snippet:not(.is-open) {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}
.ts-more {
  align-self: flex-start;
  padding: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
}
@media (hover: hover) {
  .ts-more:hover {
    color: var(--text);
  }
}
.ts-open {
  margin-top: -6px;
  color: var(--text-3);
}
.ts-status {
  margin-top: 2px;
}
</style>
