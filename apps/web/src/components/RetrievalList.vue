<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { RetrievalStage } from '../types'

/** Topilgan parchalar (dasturchi izi): o'rin, kalit, vektor va rerank bahosi (3 xona,
 *  faqat son bo'lsa), matn. */
defineProps<{ retrieval: RetrievalStage }>()
const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <ol v-if="retrieval.results && retrieval.results.length > 0" class="chunks">
    <li v-for="(c, i) in retrieval.results" :key="c.chunkId || i" class="chunk">
      <div class="chunk__meta">
        <span class="chunk__rank">#{{ c.rank ?? i + 1 }}</span>
        <span v-if="c.chunkId">{{ c.chunkId }}</span>
        <span v-if="typeof c.vectorScore === 'number'">vec {{ c.vectorScore.toFixed(3) }}</span>
        <span v-if="typeof c.rerankScore === 'number'">rerank {{ c.rerankScore.toFixed(3) }}</span>
      </div>
      <p class="chunk__text">{{ c.text }}</p>
    </li>
  </ol>
  <p v-else class="chunks__empty">{{ t('chat.noChunks') }}</p>
</template>

<style scoped>
.chunks {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.chunk {
  padding: var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.chunk__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-1) var(--s-3);
  margin-bottom: var(--s-1_5);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
}
.chunk__rank {
  color: var(--text);
  font-weight: 600;
}
.chunk__text {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.chunks__empty {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}
</style>
