<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Trash2 } from 'lucide-vue-next'
import { formatWhen, isoToMs } from '../../time'
import type { ChatSummary } from '../../types'
import { longPress } from '../chat/longPress'
import { haptic } from '../telegram'

/**
 * Suhbatlar ro'yxatidagi qator (56px, chetdan-chetga): bosilsa - ochiladi; CHAPGA
 * surilsa - ostidan qizil "O'chirish" chiqadi (iOS/Telegram odati). Oxirigacha (60%)
 * surib qo'yib yuborilsa - darhol o'chadi: chegaradan o'tilgan lahzada BIR marta
 * tebranadi va "O'chirish" yozuvi qator chetiga yopishib ergashadi - qo'yib
 * yuborishdan oldin nima bo'lishi ko'rinib turadi. O'chirish tasdiqsiz: pastda
 * 8 soniyalik "Bekor qilish" bor (useChatActions).
 *
 * Surish faqat GORIZONTAL harakatda boshlanadi: `touch-action: pan-y` - vertikal
 * aylantirishni brauzer o'zi qiladi, biz faqat yon harakatni olamiz. Birinchi 8px
 * yo'nalishni aniqlaydi; aylantirayotgan odamning qatori qimirlamaydi.
 *
 * Ushlab turish (450 ms) - amallar menyusi (HistorySheet): surish imo-ishorasi
 * tizimniki bilan to'qnashadigan telefonlarda ham yo'l bor.
 *
 * Klaviatura / ekran o'quvchi: "O'chirish" tugmasi DOM'da doim bor - fokus olganda
 * qator o'zi ochiladi.
 */
const props = defineProps<{ chat: ChatSummary; active: boolean; revealed: boolean }>()
const emit = defineEmits<{ open: []; remove: []; reveal: [on: boolean]; menu: [el: HTMLElement]; swipe: [] }>()
const { t, locale } = useI18n({ useScope: 'global' })

const ACTION_W = 96
const COMMIT = 0.6
const offset = ref(0)
const dragging = ref(false)
const rowRef = ref<HTMLElement | null>(null)

let startX = 0
let startY = 0
let base = 0
let axis: 'x' | 'y' | null = null
let pointerId = -1
let lastX = 0
let lastT = 0
let velocity = 0
let moved = false

watch(
  () => props.revealed,
  (on) => {
    if (!dragging.value) offset.value = on ? -ACTION_W : 0
  },
)

function width(): number {
  return rowRef.value?.offsetWidth || 360
}

/** Oxirigacha surish chegarasidan o'tildi - qo'yib yuborilsa o'chadi. */
const committed = computed(() => dragging.value && offset.value < -width() * COMMIT)
watch(committed, (on) => {
  if (on) haptic.impact('medium')
})

const press = longPress((el) => {
  haptic.impact('medium')
  emit('menu', el)
})

function onPointerDown(e: PointerEvent) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  startX = lastX = e.clientX
  startY = e.clientY
  lastT = e.timeStamp
  velocity = 0
  base = offset.value
  axis = null
  moved = false
  pointerId = e.pointerId
  // Ochiq (surilgan) qatorda ushlab turish menyusi kerak emas.
  if (!props.revealed) press.onPointerdown(e)
}

function onPointerMove(e: PointerEvent) {
  press.onPointermove(e)
  if (e.pointerId !== pointerId) return
  const dx = e.clientX - startX
  const dy = e.clientY - startY
  if (!axis) {
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return
    axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
    if (axis === 'x') {
      dragging.value = true
      moved = true
      // Boshqa ochiq qator yopiladi - bir vaqtda faqat bitta "O'chirish" (iOS).
      emit('swipe')
      try {
        rowRef.value?.setPointerCapture(e.pointerId)
      } catch {
        /* eski brauzer */
      }
    }
  }
  if (axis !== 'x') return
  const dt = Math.max(1, e.timeStamp - lastT)
  velocity = (e.clientX - lastX) / dt
  lastX = e.clientX
  lastT = e.timeStamp
  let next = base + dx
  // O'ngga - qarshilik (yopiq qatorni o'ngga tortib bo'lmaydi).
  if (next > 0) next = next * 0.2
  offset.value = next
}

function settle() {
  const w = width()
  const x = offset.value
  if (x < -w * COMMIT) {
    // Oxirigacha surildi - darhol o'chirish (tebranish chegarada bo'ldi).
    offset.value = -w
    emit('remove')
    return
  }
  const open = x < -ACTION_W / 2 || velocity < -0.4
  const close = velocity > 0.4
  const on = open && !close
  offset.value = on ? -ACTION_W : 0
  if (on !== props.revealed) {
    if (on) haptic.select()
    emit('reveal', on)
  }
}

function onPointerUp(e: PointerEvent) {
  press.onPointerup()
  if (e.pointerId !== pointerId) return
  pointerId = -1
  if (axis === 'x') settle()
  dragging.value = false
  axis = null
}

function onClick(e: MouseEvent) {
  // Surishdan yoki ushlab turishdan keyingi `click` - ochish emas.
  if (moved) {
    moved = false
    e.preventDefault()
    return
  }
  press.onClickCapture(e)
  if (e.defaultPrevented) return
  if (props.revealed) {
    emit('reveal', false)
    return
  }
  emit('open')
}

function remove() {
  haptic.impact('medium')
  offset.value = -width()
  emit('remove')
}

onBeforeUnmount(() => {
  pointerId = -1
  press.onPointercancel()
})

const when = computed(() => {
  const ms = isoToMs(props.chat.updated_at)
  const lang = document.documentElement.lang || String(locale.value)
  return ms ? formatWhen(ms, lang) : ''
})
const style = computed(() => ({
  transform: `translate3d(${offset.value}px, 0, 0)`,
  transition: dragging.value ? 'none' : undefined,
}))
/** "O'chirish" maydoni qator bilan birga kengayadi - oxirigacha surishni ko'rsatadi. */
const actionStyle = computed(() => ({ width: `${Math.max(ACTION_W, -offset.value)}px` }))
</script>

<template>
  <li class="hrow" :class="{ 'is-active': active, 'is-revealed': revealed || offset < 0 }">
    <button
      type="button"
      class="hrow__del"
      :class="{ 'is-commit': committed }"
      :style="actionStyle"
      :aria-label="`${t('tg.history.delete')}: ${chat.title}`"
      @focus="emit('reveal', true)"
      @click="remove"
    >
      <span class="hrow__del-label">
        <Trash2 :size="18" :stroke-width="1.75" aria-hidden="true" />
        <span>{{ t('tg.history.delete') }}</span>
      </span>
    </button>
    <button
      ref="rowRef"
      type="button"
      class="hrow__main"
      :class="{ 'is-dragging': dragging }"
      :style="style"
      :aria-current="active ? 'true' : undefined"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @pointerleave="press.onPointerleave"
      @contextmenu="press.onContextmenu"
      @click="onClick"
    >
      <span class="hrow__title">{{ chat.title }}</span>
      <span v-if="when" class="hrow__time">{{ when }}</span>
    </button>
  </li>
</template>

<style scoped>
.hrow {
  position: relative;
  overflow: hidden;
}
.hrow__del {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  overflow: hidden;
  background: var(--crit);
  color: #fff;
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 600;
  opacity: 0;
  transition: opacity var(--dur-1) var(--ease-out);
}
.hrow.is-revealed .hrow__del,
.hrow__del:focus-visible {
  opacity: 1;
}
/* Yozuv 96px qutida: odatda o'ng chetda; chegaradan o'tilganda - qator chetiga
   (qizil maydonning chap chetiga) sirg'anadi va unga ergashadi. */
.hrow__del-label {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  width: 96px;
  transition: right var(--dur-2) var(--ease-out);
}
.hrow__del.is-commit .hrow__del-label {
  right: calc(100% - 96px);
}
.hrow__main {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  min-height: 56px;
  padding: 8px var(--tg-gutter);
  background: var(--surface);
  text-align: left;
  touch-action: pan-y;
  -webkit-user-select: none;
  user-select: none;
  transition:
    transform var(--dur-3) var(--ease-sheet),
    background-color var(--dur-1) var(--ease-out),
    scale 330ms var(--ease-out);
}
/* Alohida kompozit qatlam faqat surish paytida (har qatorda doim bo'lsa - uzun
   ro'yxatda o'rta Android'da xotira va "silkinish"). */
.hrow__main.is-dragging {
  will-change: transform;
}
.hrow__main:active {
  background: var(--fill);
}
.hrow__main.is-pressing {
  scale: 0.985;
  background: var(--fill);
}
.hrow.is-active .hrow__main {
  background: var(--fill);
}
.hrow__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.hrow.is-active .hrow__title {
  font-weight: 600;
}
.hrow__time {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}
</style>
