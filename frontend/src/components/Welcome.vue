<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ActorType } from '../types'
import type { Locale } from '../i18n'
import { CalendarChipIcon, CardChipIcon, CodeChipIcon, DocChipIcon } from '../icons'
import { chipsFor } from '../i18n'

const props = defineProps<{ name: string; actorType: ActorType }>()
const emit = defineEmits<{ chip: [text: string] }>()

const { t, locale } = useI18n({ useScope: 'global' })
const CHIP_ICONS = [CodeChipIcon, DocChipIcon, CardChipIcon, CalendarChipIcon]
const chips = computed(() => chipsFor(locale.value as Locale, props.actorType))
</script>

<template>
  <div
    data-screen-label="Welcome"
    :style="{
      display: 'flex',
      position: 'absolute',
      inset: 0,
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '16px',
      paddingBottom: '130px',
    }"
  >
    <div
      class="greeting"
      :style="{
        position: 'relative',
        zIndex: 1,
        fontSize: '44px',
        fontWeight: 600,
        letterSpacing: '-0.5px',
        textAlign: 'center',
        backgroundImage: 'var(--greeting-grad)',
        backgroundSize: '200% auto',
        WebkitBackgroundClip: 'text',
        backgroundClip: 'text',
        color: 'transparent',
        animation: 'shimmer 7s linear infinite',
      }"
    >
      {{ t('hello', { name }) }}
    </div>
    <div :style="{ position: 'relative', zIndex: 1, fontSize: '18px', color: 'var(--text-secondary)', marginTop: '-4px' }">
      {{ t('helpToday') }}
    </div>

    <div
      :style="{
        position: 'relative',
        zIndex: 1,
        display: 'flex',
        gap: '12px',
        marginTop: '26px',
        flexWrap: 'wrap',
        justifyContent: 'center',
        maxWidth: '760px',
        padding: '0 24px',
        transform: 'translateZ(0)',
        isolation: 'isolate',
      }"
    >
      <button
        v-for="(label, i) in chips"
        :key="label"
        class="chip glass glint"
        :style="{
          fontFamily: 'Figtree, sans-serif',
          width: '168px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          gap: '10px',
          background: 'var(--glass-bg)',
          border: '1px solid var(--glass-border)',
          borderRadius: '16px',
          padding: '16px',
          cursor: 'pointer',
          textAlign: 'left',
          boxShadow: 'var(--glass-shadow)',
        }"
        @click="emit('chip', label)"
      >
        <component :is="CHIP_ICONS[i % CHIP_ICONS.length]" />
        <span :style="{ fontSize: '14px', fontWeight: 500, color: 'var(--text-secondary)', lineHeight: 1.4 }">{{
          label
        }}</span>
      </button>
    </div>
  </div>
</template>
