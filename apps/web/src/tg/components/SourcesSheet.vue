<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { Activity, ArrowUpRight, BookOpenText, FileText, Landmark } from 'lucide-vue-next'
import { platformIcon } from '../../components/chat/platforms'
import { localizeApiError } from '../../api/errors'
import VSheet from '../../ui/VSheet.vue'
import { toast } from '../../ui/useToast'
import { openCitedDoc } from '../chat/files'
import type { SourceItem } from '../chat/sources'
import { useTgSheet } from '../sheet'
import { haptic, openLink } from '../telegram'

/**
 * Manbalar oynasi (pastdan). Har karta: raqam (20px doira), nom, bir qator izoh (tur
 * belgisi + sahifa/band, LEX.UZ yoki so'rov natijasi), bo'lsa - hujjatdan parcha.
 *
 * OCHILADIGAN KARTA - BUTUNLAY TUGMA (o'ngda 44px ↗): alohida "Ochish" pill'idan
 * tinchroq va bosish maydoni katta.
 *   hujjat - imzolangan havola tashqi brauzerda (chat/files.ts);
 *   qonun  - LEX.UZ, Telegram'ning `openLink` i bilan (Mini App yopilmaydi);
 *   qo'llanma (Biznes 24/7, Biznes Help) - o'z sahifasi, xuddi qonun kabi;
 *   jonli so'rov - ochiladigan narsa yo'q, faqat nima tekshirilgani (karta - matn).
 *
 * Matndagi [2] yoki qatordagi chip bosilib ochilsa - o'sha manba belgilanadi: fon
 * brend rangida bir marta "chaqnaydi" va oyna ochilib bo'lgach (280 ms) karta
 * o'rtaga silliq aylantiriladi - animatsiya paytida aylantirish "sakraydi".
 */
const props = defineProps<{ items: SourceItem[]; focus: string | null }>()
const open = defineModel<boolean>('open', { default: false })
const { t } = useI18n({ useScope: 'global' })

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
useTgSheet(open, sheet)

const busy = ref<string | null>(null)
const list = ref<HTMLElement | null>(null)
const flash = ref<string | null>(null)

const ICON = { doc: FileText, law: Landmark, guide: BookOpenText, lookup: Activity }

/** So'rov va qo'llanma - platforma belgisi (DWH, Biznes 24/7...), qolgani - tur belgisi. */
function iconOf(item: SourceItem): Component {
  return (item.kind === 'lookup' || item.kind === 'guide') && item.platform ? platformIcon(item.platform) : ICON[item.kind]
}

async function openItem(item: SourceItem) {
  if (busy.value) return
  if (item.kind === 'law' || item.kind === 'guide') {
    if (item.url) openLink(item.url)
    return
  }
  if (item.kind !== 'doc' || !item.source.doc_id) return
  busy.value = item.marker
  try {
    const outcome = await openCitedDoc(item.source.doc_id, item.source.docUrl, item.title)
    if (outcome === 'unsupported') toast.show(t('tg.sources.webOnly'))
  } catch (err) {
    haptic.notify('error')
    toast.error(`${t('tg.sources.failed')}: ${localizeApiError(err, t)}`)
  } finally {
    busy.value = null
  }
}

function canOpen(item: SourceItem): boolean {
  return ((item.kind === 'law' || item.kind === 'guide') && !!item.url) || (item.kind === 'doc' && !!item.source.doc_id)
}

let flashTimer = 0
function onOpened() {
  const focus = props.focus
  if (!focus) return
  void nextTick(() => {
    list.value?.querySelector<HTMLElement>(`[data-marker="${CSS.escape(focus)}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    flash.value = focus
    window.clearTimeout(flashTimer)
    flashTimer = window.setTimeout(() => (flash.value = null), 700)
  })
}
watch(open, (on) => {
  if (!on) flash.value = null
})
</script>

<template>
  <VSheet ref="sheet" v-model:open="open" class="tg-sheet" side="bottom" :title="t('tg.sources.title')" @after-enter="onOpened">
    <ul ref="list" class="srcs">
      <li
        v-for="item in items"
        :key="item.kind + item.marker"
        class="src"
        :class="[`src--${item.kind}`, { 'is-focus': focus === item.marker, 'is-flash': flash === item.marker }]"
        :data-marker="item.marker"
      >
        <component
          :is="canOpen(item) ? 'button' : 'div'"
          :type="canOpen(item) ? 'button' : undefined"
          class="src__card"
          :class="{ 'is-action': canOpen(item) }"
          :aria-busy="busy === item.marker ? 'true' : undefined"
          :aria-label="canOpen(item) ? `${t('tg.sources.open')}: ${item.title}` : undefined"
          @click="canOpen(item) && openItem(item)"
        >
          <span class="src__n" aria-hidden="true">
            <component :is="iconOf(item)" v-if="item.kind === 'lookup'" :size="12" :stroke-width="2" />
            <template v-else>{{ item.badge }}</template>
          </span>
          <span class="src__body">
            <span class="src__title">{{ item.title }}</span>
            <!-- So'rovda izoh qatori YO'Q: "Tizimdan olindi" sarlavhadagi platforma nomini va
                 doiradagi belgini takrorlardi (UX ko'rigi). Faqat so'rov muvaffaqiyatsiz bo'lsa. -->
            <span v-if="item.kind !== 'lookup'" class="src__meta">
              <component :is="iconOf(item)" class="src__kind" :size="14" :stroke-width="1.75" aria-hidden="true" />
              <span>{{ item.meta }}</span>
            </span>
            <span v-else-if="item.failed" class="src__meta is-bad">{{ t('chat.lookupFailed') }}</span>
            <span v-if="item.kind === 'lookup' && item.meta" class="src__digest">{{ item.meta }}</span>
            <span v-if="item.snippet" class="src__snippet">{{ item.snippet }}</span>
          </span>
          <span v-if="canOpen(item)" class="src__go" aria-hidden="true">
            <span v-if="busy === item.marker" class="src__spinner" />
            <ArrowUpRight v-else :size="18" :stroke-width="2" />
          </span>
        </component>
      </li>
    </ul>
  </VSheet>
</template>

<style scoped>
.srcs {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.src {
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  transition:
    border-color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
/* Belgilangan manba: tekis brend foni (chiziq emas - yumaloq kartada "tabassum"
   bo'lib qolardi). */
.src.is-focus {
  border-color: color-mix(in srgb, var(--brand) 35%, transparent);
  background: var(--brand-soft);
}
.src.is-flash {
  animation: src-flash 600ms var(--ease-out);
}
@keyframes src-flash {
  from {
    background: color-mix(in srgb, var(--brand) 22%, transparent);
  }
}
.src__card {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 4px 10px;
  align-items: start;
  width: 100%;
  padding: var(--s-3);
  border-radius: inherit;
  color: inherit;
  text-align: left;
}
.src__card.is-action {
  grid-template-columns: 24px minmax(0, 1fr) 32px;
  padding-right: var(--s-2);
  transition: transform var(--dur-1) var(--ease-out);
}
.src__card.is-action:active {
  transform: scale(0.985);
}
.src__n {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin: 2px 0 0 2px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-size: 0.6875rem;
  line-height: 1;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.src__body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.src__title {
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.src__title::first-letter {
  text-transform: uppercase;
}
.src__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.src__kind {
  flex-shrink: 0;
}
.src--lookup .src__kind {
  color: var(--text-3);
}
.src__meta.is-bad {
  color: var(--crit-text);
}
/* So'rov: sarlavhadan keyin darhol natija (izoh qatori yo'q). */
.src--lookup .src__digest {
  margin-top: 2px;
}
.src__digest {
  margin-top: var(--s-1);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.src__snippet {
  display: -webkit-box;
  margin-top: var(--s-2);
  padding-left: var(--s-3);
  border-left: 2px solid var(--line-strong);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  line-clamp: 4;
}
/* ↗ - ko'rinishi 32px, bosish maydoni butun karta. */
.src__go {
  display: grid;
  place-items: center;
  align-self: center;
  width: 32px;
  height: 32px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text);
}
.src__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--text);
  border-radius: var(--r-full);
  animation: src-spin 0.8s linear infinite;
}
@keyframes src-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .src.is-flash {
    animation: none;
  }
}
</style>
