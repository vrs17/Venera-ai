<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * A glowing segment that wanders left/right along the BOTTOM edge of the input
 * box while a request is in flight. It eases toward a new random target at a new
 * random rate each time it arrives, so the motion (and where it slows) is
 * genuinely random. Driven by a rAF loop started on mount and torn down on
 * unmount; the position rides on the `--x` custom property so re-renders never
 * reset it. The parent gates this with v-if="busy", so mount/unmount = start/stop.
 */
const SEG_FRAC = 0.28 // segment width as a fraction of the bottom edge

const trackRef = ref<HTMLDivElement | null>(null)
let ro: ResizeObserver | null = null
let raf = 0

onMounted(() => {
  const node = trackRef.value
  if (!node) return
  let trackW = node.clientWidth
  ro = new ResizeObserver(() => {
    trackW = node.clientWidth
  })
  ro.observe(node)

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    node.style.setProperty('--x', `${trackW * (1 - SEG_FRAC) * 0.5}px`)
    return
  }

  let last = 0
  let pos = Math.random() // 0..1 along the bottom edge
  let target = Math.random()
  let rate = 2.4 + Math.random() * 5 // approach rate (eases into each target)

  const tick = (t: number) => {
    if (!last) last = t
    const dt = Math.min((t - last) / 1000, 0.05)
    last = t
    pos += (target - pos) * Math.min(rate * dt, 1)
    if (Math.abs(target - pos) < 0.012) {
      // arrived → pick a new random spot and a new random pace
      target = Math.random()
      rate = 2.4 + Math.random() * 5
    }
    const x = Math.max(0, Math.min(1, pos)) * trackW * (1 - SEG_FRAC)
    node.style.setProperty('--x', `${x.toFixed(1)}px`)
    raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  cancelAnimationFrame(raf)
})
</script>

<template>
  <div
    ref="trackRef"
    aria-hidden="true"
    :style="{ position: 'absolute', left: '24px', right: '24px', bottom: 0, height: '2px', pointerEvents: 'none', zIndex: 1 }"
  >
    <div
      :style="{
        position: 'absolute',
        top: 0,
        bottom: 0,
        left: 0,
        width: `${SEG_FRAC * 100}%`,
        transform: 'translateX(var(--x, 0px))',
        borderRadius: '2px',
        background: 'linear-gradient(90deg, transparent, var(--ink) 35%, var(--ink) 65%, transparent)',
        boxShadow: '0 0 8px 1px rgba(0,0,0,0.18)',
      }"
    />
  </div>
</template>
