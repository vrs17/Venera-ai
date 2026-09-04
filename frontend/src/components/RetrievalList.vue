<script setup lang="ts">
import type { RetrievalStage } from '../types'

defineProps<{ retrieval: RetrievalStage }>()
</script>

<template>
  <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
    <template v-if="retrieval.results && retrieval.results.length > 0">
      <div
        v-for="(c, i) in retrieval.results"
        :key="c.chunkId || i"
        :style="{
          background: 'var(--surface-sunken)',
          border: '1px solid var(--border-faint)',
          borderRadius: '12px',
          padding: '10px 12px',
          fontSize: '13px',
          color: 'var(--text)',
          lineHeight: 1.55,
        }"
      >
        <div :style="{ display: 'flex', gap: '10px', fontSize: '11.5px', color: 'var(--text-secondary)', marginBottom: '6px' }">
          <span :style="{ fontWeight: 600, color: 'var(--text)' }">#{{ c.rank ?? i + 1 }}</span>
          <span v-if="c.chunkId">{{ c.chunkId }}</span>
          <span v-if="typeof c.vectorScore === 'number'">vec {{ c.vectorScore.toFixed(3) }}</span>
          <span v-if="typeof c.rerankScore === 'number'">rerank {{ c.rerankScore.toFixed(3) }}</span>
        </div>
        <div :style="{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }">{{ c.text }}</div>
      </div>
    </template>
    <div v-else :style="{ fontSize: '13px', color: 'var(--text-secondary)' }">No chunks returned.</div>
  </div>
</template>
