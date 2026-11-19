<script setup lang="ts">
/**
 * Jonli suhbatning ovoz shari - <canvas> da, har kadrda.
 *
 * Splash sahifasidagi CSS shari (`SplashView.vue`) bilan bir oila: o'sha brend gradienti
 * (yuqori-chapda och, o'rtada asosiy, chetda to'q) va yumshoq halo. Farqi - u tirik:
 *   * idle      - sokin nafas (bosh sahifadagi kartalar);
 *   * ringing   - bog'lanish: tashqariga "qo'ng'iroq" halqalari;
 *   * listening - odam gapirsa (`level` - mikrofon) shar biroz kattalashadi, halqalar chiqadi;
 *   * thinking  - shar atrofida aylanuvchi yoy;
 *   * speaking  - agent ovozi (`level` - agent balandligi): shakl to'lqinlanadi, ichi jonlanadi;
 *   * muted     - xira parda.
 *
 * Ranglar TOKENLARDAN o'qiladi (`--brand`, `--brand-2`, `--viz-1`, `--bg`) va mavzu
 * almashsa (`<html data-theme>`) qayta o'qiladi - och va qorong'i mavzu o'zidan ishlaydi.
 * Kanvas o'rovchidan 1.6 marta katta (`inset: -30%`): halo va halqalar kesilmaydi, joy esa
 * faqat shar o'lchamida egallanadi. Blur va blend rejimlari yo'q - oddiy noutbukda ham yengil.
 * `prefers-reduced-motion` da shar deyarli qimirlamaydi (faqat ovoz balandligi bilan o'lchami).
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { OrbMode, OrbTone } from './personas'

const props = withDefaults(
  defineProps<{
    tone?: OrbTone
    mode?: OrbMode
    /** 0..1 - ovoz balandligi (mikrofon yoki agent). */
    level?: number
    /** CSS px. Berilmasa - ota kengligi (kvadrat). */
    size?: number
  }>(),
  { tone: 'brand', mode: 'idle', level: 0 },
)

type RGB = [number, number, number]
interface Palette { light: RGB; base: RGB; deep: RGB; accent: RGB; veil: RGB }
interface Ring { born: number; strength: number }

const canvas = ref<HTMLCanvasElement | null>(null)

let ctx: CanvasRenderingContext2D | null = null
let palette: Palette | null = null
let frame = 0
let last = 0
let time = 0
let lvl = 0
let energy = 0.12
let lastRing = -10
let rings: Ring[] = []
let reduced = false
let resizeObs: ResizeObserver | null = null
let themeObs: MutationObserver | null = null
let motionQuery: MediaQueryList | null = null

const ENERGY: Record<OrbMode, number> = {
  idle: 0.14, ringing: 0.32, listening: 0.22, thinking: 0.3, speaking: 0.42, muted: 0.06,
}

// --- ranglar ------------------------------------------------------------------------

function parseColor(value: string, fallback: RGB): RGB {
  const v = value.trim()
  if (v.startsWith('#')) {
    const hex = v.length === 4 ? v.slice(1).split('').map((c) => c + c).join('') : v.slice(1, 7)
    const n = Number.parseInt(hex, 16)
    if (Number.isFinite(n) && hex.length === 6) return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const m = v.match(/rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i)
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : fallback
}

const mix = (a: RGB, b: RGB, t: number): RGB =>
  [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]

const rgba = (c: RGB, a: number) =>
  `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${Math.max(0, Math.min(1, a)).toFixed(3)})`

function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement)
  const token = (name: string, fallback: RGB) => parseColor(css.getPropertyValue(name), fallback)
  const veil = token('--bg', [255, 255, 255])
  if (props.tone === 'cool') {
    const base = token('--viz-1', [42, 120, 214])
    const light = mix(base, [159, 211, 255], 0.55)
    return { base, light, deep: mix(base, [11, 29, 69], 0.45), accent: mix(light, [216, 251, 255], 0.5), veil }
  }
  const base = token('--brand', [238, 90, 36])
  const light = token('--brand-2', [245, 158, 66])
  return { base, light, deep: mix(base, [90, 26, 0], 0.42), accent: mix(light, [255, 244, 230], 0.55), veil }
}

// --- o'lcham ------------------------------------------------------------------------

function resize() {
  const el = canvas.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const dpr = Math.min(rect.width > 600 ? 1.75 : 2, window.devicePixelRatio || 1)
  const w = Math.max(1, Math.round(rect.width * dpr))
  const h = Math.max(1, Math.round(rect.height * dpr))
  if (el.width !== w || el.height !== h) { el.width = w; el.height = h }
}

// --- chizish ------------------------------------------------------------------------

function blobPath(cx: number, cy: number, r: number, amp: number, t: number): Path2D {
  const path = new Path2D()
  const n = 96
  const pts: [number, number][] = []
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2
    const d = amp === 0
      ? 0
      : Math.sin(3 * a + t * 1.3) * 0.5 + Math.sin(5 * a - t * 1.7 + 1.3) * 0.3 + Math.sin(2 * a + t * 0.7 + 2.1) * 0.2
    const rr = r * (1 + amp * d)
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr])
  }
  // Silliq yopiq egri: har nuqta - boshqaruv, o'rtalar - egri ustida.
  const mid = (p: [number, number], q: [number, number]): [number, number] => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2]
  const start = mid(pts[n - 1], pts[0])
  path.moveTo(start[0], start[1])
  for (let i = 0; i < n; i++) {
    const p = pts[i]
    const m = mid(p, pts[(i + 1) % n])
    path.quadraticCurveTo(p[0], p[1], m[0], m[1])
  }
  path.closePath()
  return path
}

function softSpot(c: CanvasRenderingContext2D, x: number, y: number, r: number, color: RGB, alpha: number) {
  const g = c.createRadialGradient(x, y, 0, x, y, r)
  g.addColorStop(0, rgba(color, alpha))
  g.addColorStop(1, rgba(color, 0))
  c.fillStyle = g
  c.beginPath()
  c.arc(x, y, r, 0, Math.PI * 2)
  c.fill()
}

function draw() {
  const el = canvas.value
  if (!ctx || !el || !palette) return
  const c = ctx
  const p = palette
  const W = el.width
  const H = el.height
  const cx = W / 2
  const cy = H / 2
  // Kanvas = o'rovchi x 1.6; shar tanasi o'rovchining ~82% i.
  const R0 = (Math.min(W, H) / 1.6) * 0.41
  const mode = props.mode
  const t = time

  const breathe = reduced ? 0 : Math.sin(t * 1.5) * 0.014
  const ringPulse = mode === 'ringing' && !reduced ? Math.pow(Math.sin(t * 3.1), 2) * 0.035 : 0
  const grow = mode === 'speaking' ? 0.1 : mode === 'listening' ? 0.07 : 0.03
  const R = R0 * (1 + breathe + ringPulse + lvl * grow)

  c.clearRect(0, 0, W, H)

  // Halo.
  const haloR = R * (1.85 + lvl * 0.3)
  const halo = c.createRadialGradient(cx, cy, R * 0.55, cx, cy, haloR)
  halo.addColorStop(0, rgba(p.base, 0.26 * (0.55 + energy)))
  halo.addColorStop(0.55, rgba(p.base, 0.09 * (0.55 + energy)))
  halo.addColorStop(1, rgba(p.base, 0))
  c.fillStyle = halo
  c.beginPath()
  c.arc(cx, cy, haloR, 0, Math.PI * 2)
  c.fill()

  // Halqalar: bog'lanishda - bir maromda, suhbatda - ovoz cho'qqilarida.
  if (!reduced) {
    if (mode === 'ringing' && t - lastRing > 1.15) { rings.push({ born: t, strength: 0.9 }); lastRing = t }
    if ((mode === 'listening' || mode === 'speaking') && lvl > 0.24 && t - lastRing > 0.42) {
      rings.push({ born: t, strength: Math.min(1, 0.45 + lvl) })
      lastRing = t
    }
  }
  rings = rings.filter((ring) => t - ring.born < 1.8)
  for (const ring of rings) {
    const q = (t - ring.born) / 1.8
    const eased = 1 - Math.pow(1 - q, 3)
    c.strokeStyle = rgba(p.base, Math.pow(1 - q, 2) * 0.42 * ring.strength)
    c.lineWidth = Math.max(1, R * 0.012)
    c.beginPath()
    c.arc(cx, cy, R * (1.02 + 0.6 * eased), 0, Math.PI * 2)
    c.stroke()
  }

  // Tana.
  const amp = reduced ? 0 : mode === 'speaking' ? 0.01 + 0.052 * lvl : mode === 'listening' ? 0.01 + 0.028 * lvl : 0.009
  const body = blobPath(cx, cy, R, amp, t)
  const fill = c.createRadialGradient(cx - R * 0.32, cy - R * 0.38, R * 0.05, cx, cy, R * 1.05)
  fill.addColorStop(0, rgba(p.light, 1))
  fill.addColorStop(0.55, rgba(p.base, 1))
  fill.addColorStop(1, rgba(p.deep, 1))
  c.save()
  c.shadowColor = rgba(p.base, 0.35 + 0.25 * lvl)
  c.shadowBlur = R * (0.18 + 0.22 * lvl)
  c.shadowOffsetY = R * 0.06
  c.fillStyle = fill
  c.fill(body)
  c.restore()

  // Ichki "aurora": uch yumshoq dog' sekin aylanadi; agent gapirganda jonlanadi.
  c.save()
  c.clip(body)
  const live = 0.55 + 0.75 * energy + (mode === 'speaking' ? 0.5 * lvl : 0)
  const speed = reduced ? 0 : 0.32 + energy * 0.6
  softSpot(c, cx + R * 0.42 * Math.sin(t * speed + 0.4), cy + R * 0.36 * Math.cos(t * speed * 1.3 + 1.1),
    R * (0.62 + 0.2 * lvl), p.accent, 0.42 * live)
  softSpot(c, cx + R * 0.48 * Math.sin(t * speed * 0.8 + 2.6), cy + R * 0.44 * Math.cos(t * speed * 1.1 + 3.3),
    R * (0.7 + 0.15 * lvl), p.light, 0.32 * live)
  softSpot(c, cx + R * 0.5 * Math.sin(t * speed * 1.2 + 4.4), cy + R * 0.5 * Math.cos(t * speed * 0.9 + 0.2),
    R * 0.75, p.deep, 0.34 * live)
  // Ko'zgu yaltirog'i - hajm beradi.
  softSpot(c, cx - R * 0.36, cy - R * 0.42, R * 0.55, [255, 255, 255], 0.34)
  if (mode === 'muted') {
    c.fillStyle = rgba(p.veil, 0.42)
    c.fill(body)
  }
  c.restore()

  // O'ylash: shar atrofida aylanuvchi yoy (dumi so'nib boradi).
  if (mode === 'thinking') {
    const start = reduced ? -Math.PI / 2 : t * 3.6
    const span = 1.35
    const radius = R * 1.14
    const steps = 18
    c.lineCap = 'round'
    c.lineWidth = Math.max(1.5, R * 0.03)
    for (let i = 0; i < steps; i++) {
      const a0 = start - (span * i) / steps
      const a1 = start - (span * (i + 1)) / steps
      c.strokeStyle = rgba(p.base, 0.75 * Math.pow(1 - i / steps, 1.6))
      c.beginPath()
      c.arc(cx, cy, radius, a1, a0)
      c.stroke()
    }
  }
}

function loop(now: number) {
  frame = requestAnimationFrame(loop)
  const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016)
  last = now
  time += dt
  const target = Math.max(0, Math.min(1, props.level))
  lvl += (target - lvl) * (1 - Math.exp(-dt * (target > lvl ? 16 : 5)))
  energy += (ENERGY[props.mode] - energy) * (1 - Math.exp(-dt * 3))
  draw()
}

function onMotionChange() {
  reduced = !!motionQuery?.matches
}

onMounted(() => {
  const el = canvas.value
  if (!el) return
  ctx = el.getContext('2d')
  palette = readPalette()
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  onMotionChange()
  motionQuery.addEventListener('change', onMotionChange)
  resize()
  resizeObs = new ResizeObserver(resize)
  resizeObs.observe(el)
  themeObs = new MutationObserver(() => { palette = readPalette() })
  themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  frame = requestAnimationFrame(loop)
})

watch(() => props.tone, () => { palette = readPalette() })
watch(() => props.mode, (mode) => { if (mode !== 'ringing') lastRing = time })

onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  resizeObs?.disconnect()
  themeObs?.disconnect()
  motionQuery?.removeEventListener('change', onMotionChange)
  ctx = null
})
</script>

<template>
  <div class="orb" :style="size ? { width: `${size}px`, height: `${size}px` } : undefined" aria-hidden="true">
    <canvas ref="canvas" class="orb__canvas" />
  </div>
</template>

<style scoped>
.orb {
  position: relative;
  width: 100%;
  aspect-ratio: 1 / 1;
  flex-shrink: 0;
}
/* `max-width: none` MAJBURIY: umumiy reset (`base.css`) kanvasni ota kengligi bilan cheklaydi -
   kenglik 100% da qolib, balandlik 160% bo'lardi va shar chapga siljib, kichrayib chiqardi. */
.orb__canvas {
  position: absolute;
  top: -30%;
  left: -30%;
  width: 160%;
  height: 160%;
  max-width: none;
  max-height: none;
  pointer-events: none;
}
</style>
