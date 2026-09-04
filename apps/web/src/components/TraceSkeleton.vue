<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * In-flight loader: a skeleton of the trace card. Honest about state — it
 * previews the gate rows the pipeline is about to fill rather than faking
 * per-stage progress (the backend returns the whole result at once). The
 * skeleton bars sweep with a small per-row stagger.
 */
const { t } = useI18n({ useScope: 'global' })
const GATES = ['Guard', 'Intent', 'Orchestrator', 'Access']
</script>

<template>
  <div :style="{ display: 'flex', gap: '12px', margin: '14px 0', alignItems: 'flex-start' }">
    <div
      :style="{
        width: '28px',
        height: '28px',
        borderRadius: '50%',
        background: 'var(--ink)',
        color: 'var(--ink-contrast)',
        fontSize: '13px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        marginTop: '2px',
      }"
    >
      ✦
    </div>
    <div :style="{ flex: 1, minWidth: 0 }">
      <div
        :style="{
          display: 'inline-block',
          fontSize: '12px',
          fontWeight: 600,
          color: 'var(--text-secondary)',
          background: 'var(--surface-hover)',
          border: '1px solid var(--border)',
          borderRadius: '999px',
          padding: '4px 12px',
          marginBottom: '10px',
        }"
      >
        {{ t('processing') }}
      </div>
      <div
        :style="{
          position: 'relative',
          background: 'var(--surface-sunken)',
          border: '1px solid var(--border)',
          borderRadius: '14px',
          overflow: 'hidden',
        }"
      >
        <!-- Same faint spine as the resolved trace, so it morphs cleanly. -->
        <div
          aria-hidden="true"
          :style="{
            position: 'absolute',
            left: '19px',
            top: '14px',
            bottom: '14px',
            width: '2px',
            background: 'var(--border)',
            borderRadius: '2px',
            zIndex: 0,
          }"
        />
        <div
          v-for="(g, i) in GATES"
          :key="g"
          :style="{
            position: 'relative',
            zIndex: 1,
            borderTop: i === 0 ? 'none' : '1px solid var(--border-faint)',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '12px 16px',
          }"
        >
          <span :style="{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--border-hover)', flexShrink: 0 }" />
          <span :style="{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text)', width: '110px', flexShrink: 0 }">{{ g }}</span>
          <span class="skeleton" :style="{ height: '9px', flex: 1, marginRight: '8px', animationDelay: `${i * 0.15}s` }" />
          <span class="skeleton" :style="{ height: '9px', width: '34px', flexShrink: 0, animationDelay: `${i * 0.15}s` }" />
        </div>
      </div>
    </div>
  </div>
</template>
