<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, X } from 'lucide-vue-next'
import { BAR_MS } from '../../composables/useDictation'
import type { DictationState, LevelStream } from '../../composables/useDictation'
import { useTheme } from '../../theme'
import VIconButton from '../../ui/VIconButton.vue'
import { useLayer } from '../../ui/composables/useClickOutside'
import { usePrefersReducedMotion } from '../../ui/composables/useMediaQuery'

/**
 * Ovoz yozilayotgandagi kompozer qatori: chapda "Bekor qilish", o'rtada JONLI
 * to'lqin, o'ngda vaqt va "Tayyor". Yozish maydoni o'rnida, o'sha kartaning
 * ichida turadi (InputDock) - odam ko'zi qayerda bo'lsa, ovoz ham o'sha yerda.
 *
 * To'lqin - HAQIQIY ovoz: har ustun `useDictation` o'lchagan RMS. Soxta
 * (tasodifiy) to'lqin jim xonada ham "eshityapman" deb yolg'on gapirardi, odam
 * esa aynan shunga qarab mikrofon ishlayotganini tekshiradi.
 *
 * Canvas, DOM emas: sekundiga ~14 ustun qo'shiladi va hammasi siljiydi -
 * yuzlab <span> ni har kadrda qayta joylash o'rniga bitta chizish arzon.
 */
const props = defineProps<{
  state: Exclude<DictationState, 'idle'>
  /** Yozuv davomiyligi, soniya. */
  elapsed: number
  levels: LevelStream
}>()

const emit = defineEmits<{ (e: 'cancel'): void; (e: 'done'): void }>()

const { t } = useI18n({ useScope: 'global' })
const reduced = usePrefersReducedMotion()
const { theme } = useTheme()

const rootRef = ref<HTMLElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const doneRef = ref<InstanceType<typeof VIconButton> | null>(null)

const clock = computed(() => {
  const s = Math.max(0, props.elapsed)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})

// --- Klaviatura --------------------------------------------------------------
// Esc - umumiy qatlam steki orqali (DocViewer kabi): ustida menyu yoki dialog
// ochiq bo'lsa, Esc avval o'shani yopadi; stek `preventDefault` qiladi va
// ChatView yon panelni yig'ib yubormaydi. Tashqariga bosish bekor QILMAYDI:
// yozuv paytida suhbatni aylantirish yoki matnni belgilash mumkin bo'lsin.
useLayer(true, {
  elements: () => [rootRef.value],
  onDismiss: (reason) => reason === 'escape' && emit('cancel'),
  closeOnOutside: false,
})

// Enter - "Tayyor". Tugma ustida Enter tugmaning o'ziniki (✕ da - bekor), shuning
// uchun faqat fokus hech qayerda bo'lmasa yoki shu qatorning tugma bo'lmagan
// joyida bo'lsa. Ochiq dialog ichidagi Enter'ga tegmaymiz.
function onDocKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.isComposing || e.defaultPrevented) return
  if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return
  const target = e.target
  const root = rootRef.value
  const free = target === document.body || target === document.documentElement
  const ours = target instanceof Element && !!root?.contains(target) && !target.closest('button, a')
  if (!free && !ours) return
  e.preventDefault()
  if (props.state === 'recording') emit('done')
}

// --- To'lqin ------------------------------------------------------------------
const BAR_W = 3
const GAP = 3
const STEP = BAR_W + GAP
/** Hali yozilmagan joy - xira nuqtalar: qator boshidan to'liq ko'rinadi va
 *  yozilgan sukunatdan (to'liq rangli nuqta) farq qiladi. */
const PLACEHOLDER_ALPHA = 0.28

let ink = '#111110'
let cssW = 0
let cssH = 0
let dpr = 1
let raf = 0
let drawnCount = -1
let drawnSettled = false
let ro: ResizeObserver | null = null

/** Rang tokendan: mavzu almashsa qayta o'qiladi (canvas CSS o'zgaruvchisini o'zi bilmaydi). */
function readInk() {
  const el = canvasRef.value
  if (!el) return
  const value = getComputedStyle(el).getPropertyValue('--ink').trim()
  if (value) ink = value
  redraw()
}

function measure() {
  const el = canvasRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  dpr = window.devicePixelRatio || 1
  cssW = rect.width
  cssH = rect.height
  el.width = Math.max(1, Math.round(cssW * dpr))
  el.height = Math.max(1, Math.round(cssH * dpr))
  redraw()
}

/** Dumaloq uchli ustun, markaz chizig'iga nisbatan simmetrik. Bo'yi eniga teng
 *  bo'lsa - nuqta. `roundRect` ishlatilmaydi: eski Safari/Firefox'da yo'q. */
function pill(g: CanvasRenderingContext2D, x: number, mid: number, h: number) {
  const r = BAR_W / 2
  const half = Math.max(0, h / 2 - r)
  const cx = x + r
  g.beginPath()
  g.arc(cx, mid - half, r, Math.PI, 0)
  g.lineTo(cx + r, mid + half)
  g.arc(cx, mid + half, r, 0, Math.PI)
  g.closePath()
  g.fill()
}

function draw(now: number) {
  const el = canvasRef.value
  const g = el?.getContext('2d')
  if (!el || !g || cssW <= 0 || cssH <= 0) return
  const { bars, pushedAt, count } = props.levels
  const moving = props.state === 'recording' && !reduced.value && count > 0
  // p: oxirgi ustun kelganidan beri o'tgan ulush. Hamma ustun shu ulushda chapga
  // siljiydi - qadam-qadam sakrash o'rniga bir tekis oqim. Harakat
  // kamaytirilganda p = 1: ustunlar joyida almashadi, darajalar baribir haqiqiy.
  const p = moving ? Math.min(1, (now - pushedAt) / BAR_MS) : 1
  const settled = p >= 1
  if (settled && drawnSettled && count === drawnCount) return
  drawnCount = count
  drawnSettled = settled

  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  g.clearRect(0, 0, cssW, cssH)
  g.fillStyle = ink
  const mid = cssH / 2
  const maxH = cssH
  const shift = (1 - p) * STEP
  // Eng yangisi o'ngda; qolgani chapga. Ekrandan chiqqani chizilmaydi.
  for (let k = 0; ; k++) {
    const raw = cssW - BAR_W - k * STEP + shift
    if (raw + BAR_W < 0) break
    if (raw > cssW) continue
    // Qurilma pikseliga tekislanadi - 3 px ustun xira bo'lib ketmasin.
    const x = Math.round(raw * dpr) / dpr
    const i = bars.length - 1 - k
    let h = BAR_W
    if (i >= 0) {
      h = BAR_W + bars[i] * (maxH - BAR_W)
      // Yangi ustun sekin "o'sib" chiqadi (ease-out) - keskin sakramaydi.
      if (k === 0 && moving) h = BAR_W + (h - BAR_W) * (1 - (1 - p) ** 3)
      g.globalAlpha = 1
    } else {
      g.globalAlpha = PLACEHOLDER_ALPHA
    }
    pill(g, x, mid, h)
  }
  g.globalAlpha = 1
}

function redraw() {
  drawnCount = -1
  draw(performance.now())
}

function loop(now: number) {
  raf = 0
  draw(now)
  if (props.state === 'recording' && !document.hidden) raf = requestAnimationFrame(loop)
}

function run() {
  if (raf || props.state !== 'recording' || document.hidden) return
  raf = requestAnimationFrame(loop)
}

function halt() {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

// Yashirin tabda chizish to'xtaydi (yozuv davom etadi); qaytganda - davom.
function onVisibility() {
  if (document.hidden) halt()
  else {
    redraw()
    run()
  }
}

watch(
  () => props.state,
  (state) => {
    // Matnga aylantirilayotganda to'lqin qotadi (oxirgi ko'rinishda, xira).
    if (state !== 'recording') {
      halt()
      redraw()
    } else run()
  },
)
watch(theme, readInk)
watch(reduced, redraw)

onMounted(() => {
  const el = canvasRef.value
  if (el && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(measure)
    ro.observe(el)
  }
  readInk()
  measure()
  run()
  document.addEventListener('visibilitychange', onVisibility)
  document.addEventListener('keydown', onDocKeydown)
})

onBeforeUnmount(() => {
  halt()
  ro?.disconnect()
  ro = null
  document.removeEventListener('visibilitychange', onVisibility)
  document.removeEventListener('keydown', onDocKeydown)
})

/** InputDock uchun: yozuv boshlanganda fokus "Tayyor" ga - Enter/Space darhol ishlasin. */
function focusDone() {
  const el = (doneRef.value as { $el?: unknown } | null)?.$el
  if (el instanceof HTMLElement) el.focus({ preventScroll: true })
}
defineExpose({ focusDone })
</script>

<template>
  <div ref="rootRef" class="dict" :class="`is-${state}`" role="group" :aria-label="t('composer.dictate.recording')">
    <VIconButton class="dict__cancel" :label="t('voiceCancel')" :icon="X" size="sm" @click="emit('cancel')" />
    <div class="dict__wave">
      <canvas ref="canvasRef" class="dict__canvas" aria-hidden="true" />
      <span v-if="state === 'transcribing'" class="dict__status">
        <span class="dict__shimmer">{{ t('composer.dictate.transcribing') }}</span>
      </span>
    </div>
    <span class="dict__time" aria-hidden="true">{{ clock }}</span>
    <VIconButton
      ref="doneRef"
      class="dict__done"
      variant="primary"
      size="sm"
      :label="t('composer.dictate.done')"
      :disabled="state !== 'recording'"
      @click="emit('done')"
    >
      <Check :size="18" :stroke-width="2" aria-hidden="true" />
    </VIconButton>
  </div>
</template>

<style scoped>
.dict {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  cursor: default;
}

/* To'lqin: qator o'rtasi, butun bo'sh joy. Chap chet sekin so'nadi - eski
   ustunlar keskin kesilib ketmaydi, ko'z o'ng tomondagi yangisiga qaraydi. */
.dict__wave {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  min-width: 0;
  height: 32px;
}
/* Mutlaq joylashuv: canvas'ning `width`/`height` atributlari o'ziga xos nisbat
   beradi (300x150) va oddiy `height: 100%` uni yengolmay, canvas kengligining
   yarmicha bo'yga cho'zilib ketardi. `inset: 0` o'lchamni qutining o'ziga bog'laydi. */
.dict__canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 var(--s-8));
  mask-image: linear-gradient(90deg, transparent 0, #000 var(--s-8));
  transition: opacity var(--dur-3) var(--ease-out);
}
.is-transcribing .dict__canvas {
  opacity: 0.22;
}

/* "Matnga aylantirilmoqda…" qotgan to'lqin ustida. Fon - karta sirti: matn
   chiziqni kesib o'tadi, nuqtalar bilan aralashib o'qilmay qolmaydi. */
.dict__status {
  position: absolute;
  max-width: 100%;
  padding: 0 var(--s-2);
  overflow: hidden;
  background: var(--surface);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* ThinkingLoader'dagi yorug'lik: niqob matn bo'ylab yuradi, rang o'zgarmaydi. */
.dict__shimmer {
  -webkit-mask-image: linear-gradient(90deg, #000 0%, #000 35%, rgb(0 0 0 / 0.35) 50%, #000 65%, #000 100%);
  mask-image: linear-gradient(90deg, #000 0%, #000 35%, rgb(0 0 0 / 0.35) 50%, #000 65%, #000 100%);
  -webkit-mask-size: 250% 100%;
  mask-size: 250% 100%;
  animation: dict-shimmer 1.8s linear infinite;
}
@keyframes dict-shimmer {
  from {
    -webkit-mask-position: 100% 0;
    mask-position: 100% 0;
  }
  to {
    -webkit-mask-position: 0% 0;
    mask-position: 0% 0;
  }
}

.dict__time {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
  text-align: end;
}

/* "Tayyor" - yuborish tugmasining joyida va shaklida: 32px dumaloq siyoh. */
.dict__done {
  border-radius: var(--r-full);
}

@media (prefers-reduced-motion: reduce) {
  .dict__shimmer {
    animation: none;
    -webkit-mask-image: none;
    mask-image: none;
  }
}
</style>
