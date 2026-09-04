<script setup lang="ts">
import { computed } from 'vue'
import type { Phase } from '../types'

/**
 * Static warm under-light behind the answer dock while a request is in flight.
 * The *motion* of "AI is answering" lives in the conic current orbiting the
 * input box rim (see BorderCurrent in InputDock); this is just the soft pool it
 * sits in, fading in/out with the request. Pure gradient, pointer-events none.
 */
const props = defineProps<{ phase: Phase }>()
const active = computed(() => props.phase === 'sending')
</script>

<template>
  <div
    aria-hidden="true"
    :style="{
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      height: '220px',
      pointerEvents: 'none',
      overflow: 'hidden',
      zIndex: 6,
      opacity: active ? 1 : 0,
      transition: 'opacity 0.8s ease',
      background:
        'radial-gradient(ellipse 110% 100% at 50% 100%, rgba(232,51,26,0.16), rgba(255,107,61,0.07) 36%, transparent 66%)',
    }"
  />
</template>
