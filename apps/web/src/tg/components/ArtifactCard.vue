<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, FileCheck2 } from 'lucide-vue-next'
import { localizeApiError } from '../../api/errors'
import type { AnswerArtifact } from '../../types'
import { toast } from '../../ui/useToast'
import { saveArtifact } from '../chat/files'
import { uzApostrophes } from '../chat/polish'
import { haptic } from '../telegram'

/**
 * Tayyorlangan ariza (DOCX / PDF). Fayl Telegram'ning o'z yuklab olgichi bilan
 * saqlanadi - imzolangan 10 daqiqalik havola orqali (chat/files.ts). Havolasi yo'q tur
 * ko'rsatilmaydi: o'lik tugmadan yo'q tugma yaxshi.
 */
const props = defineProps<{ artifact: AnswerArtifact }>()
const { t, locale } = useI18n({ useScope: 'global' })

const KINDS = [
  ['docx', 'DOCX'],
  ['pdf', 'PDF'],
] as const

// Ko'rinadigan nom - o'zbek lotinida tutuq belgilari interfeys bilan bir xil;
// fayl nomi (saveArtifact) esa xizmat bergan holicha.
const rawName = computed(() => String(props.artifact.title || 'ariza').trim() || 'ariza')
const name = computed(() => (String(locale.value) === 'uz' ? uzApostrophes(rawName.value) : rawName.value))
const files = computed(() =>
  KINDS.filter(([kind]) => {
    const url = props.artifact[`${kind}_url`]
    return typeof url === 'string' && url
  }),
)
const busy = ref<string | null>(null)

async function save(kind: 'docx' | 'pdf') {
  const path = props.artifact[`${kind}_url`]
  if (!path || busy.value) return
  busy.value = kind
  try {
    await saveArtifact(path, rawName.value)
  } catch (err) {
    haptic.notify('error')
    toast.error(`${t('tg.artifact.failed')}: ${localizeApiError(err, t)}`)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <section v-if="files.length" class="art">
    <div class="art__head">
      <span class="art__icon" aria-hidden="true"><FileCheck2 :size="18" :stroke-width="1.75" /></span>
      <div class="art__titles">
        <p class="art__eyebrow">{{ t('artifactReady') }}</p>
        <p class="art__name">{{ name }}</p>
      </div>
    </div>
    <div class="art__buttons">
      <button
        v-for="[kind, label] in files"
        :key="kind"
        type="button"
        class="art__btn"
        :aria-busy="busy === kind ? 'true' : undefined"
        @click="save(kind)"
      >
        <Download :size="16" :stroke-width="2" aria-hidden="true" />
        {{ busy === kind ? t('tg.artifact.preparing') : label }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.art {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin: var(--s-3) 0 var(--s-1);
  padding: var(--s-3);
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--bg-subtle);
}
.art__head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}
.art__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: var(--good-soft);
  color: var(--good-text);
}
.art__titles {
  min-width: 0;
}
.art__eyebrow {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.art__name {
  font-size: var(--fs-body);
  line-height: var(--lh-body-sm);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.art__buttons {
  display: grid;
  grid-auto-columns: 1fr;
  grid-auto-flow: column;
  gap: var(--s-2);
}
.art__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-1_5);
  min-height: var(--tap);
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  font-size: var(--fs-body-sm);
  font-weight: 600;
  transition: transform var(--dur-1) var(--ease-out);
}
.art__btn:active {
  transform: scale(0.97);
}
</style>
