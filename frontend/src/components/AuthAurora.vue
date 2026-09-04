<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * Living aurora for the auth hero: a few large radial orbs that drift on a rAF
 * loop, each easing toward a new random position/scale at a new random rate
 * once it arrives — the same wandering algorithm as the chat's BottomCurrent.
 * Never static, never busy; freezes to a calm composition under reduced-motion.
 * Decorative only: aria-hidden, pointer-events none.
 */
type Orb = { el: HTMLElement; x: number; y: number; s: number; tx: number; ty: number; ts: number; rate: number }

const root = ref<HTMLDivElement | null>(null)
let raf = 0

function rand(min: number, max: number) {
  return min + Math.random() * (max - min)
}

onMounted(() => {
  const container = root.value
  if (!container) return
  const els = Array.from(container.querySelectorAll<HTMLElement>('[data-orb]'))

  const orbs: Orb[] = els.map((el) => ({
    el,
    x: Math.random(),
    y: Math.random(),
    s: rand(0.9, 1.4),
    tx: Math.random(),
    ty: Math.random(),
    ts: rand(0.9, 1.4),
    rate: rand(0.12, 0.32),
  }))

  const apply = (o: Orb) => {
    o.el.style.transform = `translate(${(o.x * 56 - 28).toFixed(2)}%, ${(o.y * 56 - 28).toFixed(2)}%) scale(${o.s.toFixed(3)})`
  }

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    orbs.forEach(apply)
    return
  }

  let last = 0
  const tick = (t: number) => {
    if (!last) last = t
    const dt = Math.min((t - last) / 1000, 0.05)
    last = t
    for (const o of orbs) {
      const k = Math.min(o.rate * dt * 3, 1)
      o.x += (o.tx - o.x) * k
      o.y += (o.ty - o.y) * k
      o.s += (o.ts - o.s) * k
      if (Math.abs(o.tx - o.x) < 0.01 && Math.abs(o.ty - o.y) < 0.01) {
        o.tx = Math.random()
        o.ty = Math.random()
        o.ts = rand(0.85, 1.45)
        o.rate = rand(0.12, 0.32)
      }
      apply(o)
    }
    raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
})

onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <div ref="root" aria-hidden="true" :style="{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }">
    <div
      data-orb
      :style="{
        position: 'absolute',
        left: '6%',
        top: '14%',
        width: '60%',
        height: '60%',
        willChange: 'transform',
        background:
          'radial-gradient(ellipse 50% 50% at 50% 50%, rgba(232,51,26,0.18), rgba(255,107,61,0.07) 42%, transparent 70%)',
      }"
    />
    <div
      data-orb
      :style="{
        position: 'absolute',
        left: '34%',
        top: '40%',
        width: '70%',
        height: '70%',
        willChange: 'transform',
        background: 'var(--glow-base)',
      }"
    />
    <div
      data-orb
      :style="{
        position: 'absolute',
        left: '22%',
        top: '-6%',
        width: '52%',
        height: '52%',
        willChange: 'transform',
        background:
          'radial-gradient(ellipse 50% 50% at 50% 50%, rgba(255,107,61,0.14), rgba(232,51,26,0.05) 48%, transparent 72%)',
      }"
    />
  </div>
</template>
