<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Component } from 'vue'
import { useLayer } from '../../ui/composables/useClickOutside'
import { useFocusTrap } from '../../ui/composables/useFocusTrap'
import { useBackButton } from '../backStack'

/**
 * Telegram uslubidagi "ko'tarilgan" kontekst menyusi (uzoq bosish).
 *
 * Bosilgan xabar (yoki tarix qatori) JOYIDAN ko'tariladi: biroz kattalashadi (1.02) va
 * xiralashtirilgan parda ustida turadi, menyu esa aynan uning ostida. Odam qaysi
 * xabar ustida amal qilayotganini ko'rib turadi - pastdan chiqadigan oyna va undagi
 * "matn boshi" emas, xabarning o'zi. Har Telegram foydalanuvchisi bu imo-ishorani
 * biladi.
 *
 * QANDAY: asl elementning nusxasi (cloneNode - scoped uslub atributlari bilan birga)
 * `position: fixed` qatlamga asl koordinatasida qo'yiladi va FLIP bilan nishon joyiga
 * suriladi; asl element shu vaqt ko'rinmaydi (`tg-lift-src`). Uzun javob - ekranga
 * sig'adigan qismi (ko'rinib turgan joyidan), pastda so'nish bilan. Pastda joy
 * yetmasa - nusxa yuqoriga suriladi, menyu doim to'liq ko'rinadi.
 *
 * Parda: `backdrop-filter: blur(12px)`; Android'da (o'rta telefonlarda blur qimmat) va
 * blur yo'q brauzerda - oddiy 40% qoraytirish.
 *
 * Yopish: pardaga bosish, Telegram "Orqaga", Esc. Menyu `role="menu"`, strelkalar bilan
 * yuriladi, fokus birinchi bandga tushadi va yopilganda qaytadi (useFocusTrap).
 */
export interface MenuItem {
  id: string
  label: string
  icon: Component
  tone?: 'crit'
}

const props = withDefaults(
  defineProps<{
    source: HTMLElement | null
    items: MenuItem[]
    label: string
    /** Menyu nusxaning qaysi chetiga tekislanadi: o'ng (savol pufakchasi) yoki chap. */
    align?: 'start' | 'end'
    /** Nusxa atrofidagi karta chekkasi (javob matni pufakchasiz - unga fon kerak). */
    pad?: number
  }>(),
  { align: 'start', pad: 0 },
)
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ select: [id: string] }>()

const GAP = 8
const EDGE = 8
const ITEM_H = 48
const MENU_W = 248

const innerEl = ref<HTMLElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)

interface Geo {
  top: number
  left: number
  width: number
  height: number
  offset: number
  fromY: number
  clipped: boolean
  menuTop: number
  menuLeft: number
  menuWidth: number
  origin: string
}
const geo = ref<Geo | null>(null)
let lifted: HTMLElement | null = null

/** CSS o'zgaruvchisining px qiymati (xavfsiz zona `max(env(), var())` - faqat brauzer
 *  hisoblay oladi, shuning uchun o'lchov elementi orqali). */
function cssPx(name: string): number {
  const probe = document.createElement('div')
  probe.style.cssText = `position:fixed;visibility:hidden;height:var(${name});`
  document.body.appendChild(probe)
  const px = probe.getBoundingClientRect().height
  probe.remove()
  return px || 0
}

function measure(menuH: number): Geo | null {
  const src = props.source
  if (!src) return null
  // Element hali "siqilgan" (is-pressing, scale .985) bo'lishi mumkin: o'lcham -
  // transformsiz (offset*), joy - ko'rinadigan qutining markazidan.
  const box = src.getBoundingClientRect()
  const w = src.offsetWidth || box.width
  const h = src.offsetHeight || box.height
  const cx = box.left + box.width / 2
  const cy = box.top + box.height / 2
  const rect = { left: cx - w / 2, top: cy - h / 2, right: cx + w / 2, width: w, height: h }
  const vv = window.visualViewport
  const vTop = vv?.offsetTop ?? 0
  const vH = vv?.height ?? window.innerHeight
  const vW = vv?.width ?? window.innerWidth
  const minTop = vTop + cssPx('--tg-safe-top') + EDGE
  const maxBottom = vTop + vH - cssPx('--tg-safe-bottom') - EDGE
  const pad = props.pad

  const boxTop = rect.top - pad
  const boxH = rect.height + pad * 2
  const room = Math.max(96, maxBottom - minTop - menuH - GAP)
  const height = Math.min(boxH, room)
  const clipped = boxH > height + 1
  // Uzun javob: ko'rinib turgan qismidan boshlab (tepasi ekrandan chiqib ketgan bo'lsa).
  const offset = clipped ? Math.min(Math.max(0, minTop - boxTop), boxH - height) : 0
  const top = Math.min(Math.max(boxTop + offset, minTop), maxBottom - menuH - GAP - height)
  const menuWidth = Math.min(MENU_W, vW - EDGE * 2)
  const menuLeft =
    props.align === 'end'
      ? Math.min(Math.max(rect.right - menuWidth, EDGE), vW - EDGE - menuWidth)
      : Math.min(Math.max(rect.left, EDGE), vW - EDGE - menuWidth)
  return {
    top,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height,
    offset,
    fromY: boxTop + offset - top,
    clipped,
    menuTop: top + height + GAP,
    menuLeft,
    menuWidth,
    origin: props.align === 'end' ? 'top right' : 'top left',
  }
}

function close() {
  open.value = false
}

/* Menyu barmoq HALI bosilib turganda ochiladi (uzoq bosish). Ostida boshqa qatlam
   ochiq bo'lsa (tarix oynasi), qatlamlar tizimi barmoq ko'tarilishini (pointerup)
   "menyudan tashqariga bosish" deb o'qib, menyuni darhol yopardi - shu imo-ishoraning
   o'z pointerup'i qatlamlarga yetib bormaydi (window capture - document'dan oldin). */
function swallowPointerUp(e: PointerEvent) {
  e.stopPropagation()
}
function armSwallow(on: boolean) {
  window.removeEventListener('pointerup', swallowPointerUp, true)
  if (on) window.addEventListener('pointerup', swallowPointerUp, { capture: true, once: true })
}
onBeforeUnmount(() => armSwallow(false))

// `pre` - koordinata panel chizilishidan OLDIN tayyor (birinchi kadrdayoq to'g'ri joy).
watch(open, (on) => {
  if (on) geo.value = measure(props.items.length * ITEM_H + 8)
  armSwallow(on)
})

// Chizilgach: nusxa qo'yiladi, asl element yashiriladi, haqiqiy menyu bo'yi bilan
// koordinata aniqlanadi (katta shriftda band 48px dan baland).
watch(
  () => (open.value ? innerEl.value : null),
  async (inner) => {
    if (!inner || !props.source) return
    const clone = props.source.cloneNode(true) as HTMLElement
    clone.classList.remove('is-pressing', 'tg-lift-src')
    clone.removeAttribute('id')
    clone.style.margin = '0'
    // Pufakchaning "paydo bo'lish" animatsiyasi nusxada qayta o'ynamasin.
    clone.style.animation = 'none'
    clone.style.width = `${props.source.offsetWidth}px`
    clone.style.transform = 'none'
    clone.setAttribute('aria-hidden', 'true')
    clone.setAttribute('inert', '')
    inner.replaceChildren(clone)
    // Oldingi menyu yopilish animatsiyasi tugamay yangisi ochilsa - eski manba qaytadi.
    if (lifted && lifted !== props.source) lifted.classList.remove('tg-lift-src')
    lifted = props.source
    lifted.classList.add('tg-lift-src')
    await nextTick()
    const real = menuEl.value?.offsetHeight
    if (real && Math.abs(real - (props.items.length * ITEM_H + 8)) > 2) geo.value = measure(real)
  },
  { flush: 'post' },
)

function restore() {
  // Yopilish animatsiyasi tugaguncha yangi menyu ochilgan bo'lsa - uning manbasiga tegilmaydi.
  if (open.value) return
  lifted?.classList.remove('tg-lift-src')
  lifted = null
}
onBeforeUnmount(() => {
  lifted?.classList.remove('tg-lift-src')
  lifted = null
})

const layer = useLayer(open, {
  kind: 'dialog',
  modal: true,
  elements: () => [menuEl.value],
  onDismiss: () => close(),
})
useFocusTrap(menuEl, open, {
  initialFocus: () => menuEl.value?.querySelector<HTMLElement>('[role="menuitem"]') ?? menuEl.value,
  allowOutside: (node) => layer.contains(node),
})
useBackButton(open, close)

function pick(id: string) {
  close()
  emit('select', id)
}

function onMenuKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return
  const items = [...(menuEl.value?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
  if (!items.length) return
  e.preventDefault()
  const i = items.indexOf(document.activeElement as HTMLElement)
  const next =
    e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
  items[next]?.focus()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="ctx" @after-leave="restore">
      <div v-if="open && geo" class="ctx" :style="{ zIndex: layer.zIndex.value }">
        <div class="ctx__scrim" aria-hidden="true" />
        <div
          class="ctx__lift"
          :class="{ 'is-clipped': geo.clipped, 'has-pad': pad > 0 }"
          :style="{
            top: `${geo.top}px`,
            left: `${geo.left}px`,
            width: `${geo.width}px`,
            height: `${geo.height}px`,
            '--from-y': `${geo.fromY}px`,
            '--pad': `${pad}px`,
          }"
          aria-hidden="true"
        >
          <div ref="innerEl" class="ctx__inner" :style="{ transform: `translateY(${-geo.offset}px)` }" />
        </div>
        <ul
          ref="menuEl"
          class="ctx__menu"
          role="menu"
          :aria-label="label"
          tabindex="-1"
          :style="{ top: `${geo.menuTop}px`, left: `${geo.menuLeft}px`, width: `${geo.menuWidth}px`, transformOrigin: geo.origin }"
          @keydown="onMenuKey"
        >
          <li v-for="item in items" :key="item.id" role="none">
            <button type="button" role="menuitem" class="ctx__item" :class="item.tone ? `is-${item.tone}` : ''" @click="pick(item.id)">
              <span>{{ item.label }}</span>
              <component :is="item.icon" :size="20" :stroke-width="1.75" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ctx {
  position: fixed;
  inset: 0;
}
.ctx__scrim {
  position: absolute;
  inset: 0;
  background: rgb(0 0 0 / 0.16);
  -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px);
}
html[data-theme='dark'] .ctx__scrim {
  background: rgb(0 0 0 / 0.36);
}
/* O'rta Android'da blur har kadrda qimmat; blur'siz brauzerda - oddiy parda. */
html[data-tg-platform='android'] .ctx__scrim {
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
  background: rgb(0 0 0 / 0.4);
}
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .ctx__scrim {
    background: rgb(0 0 0 / 0.4);
  }
}

/* Ko'tarilgan nusxa: o'z joyidan (--from-y) nishon joyiga, 1.02 ga. */
.ctx__lift {
  position: absolute;
  overflow: hidden;
  transform: scale(1.02);
  transform-origin: 50% 50%;
  pointer-events: none;
}
.ctx__lift.has-pad {
  border-radius: 16px;
  background: var(--bg);
  box-shadow: var(--e3);
}
.ctx__inner {
  padding: var(--pad);
}
.ctx__lift.is-clipped {
  -webkit-mask-image: linear-gradient(#000 calc(100% - 40px), transparent);
  mask-image: linear-gradient(#000 calc(100% - 40px), transparent);
}

.ctx__menu {
  position: absolute;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  border-radius: 14px;
  background: var(--surface);
  box-shadow: var(--e3);
  overflow: hidden;
  outline: none;
}
.ctx__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  width: 100%;
  min-height: 48px;
  padding: 10px var(--s-4);
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 500;
  text-align: left;
}
.ctx__item:active,
.ctx__item:focus-visible {
  background: var(--fill);
  outline: none;
}
.ctx__item svg {
  flex-shrink: 0;
  color: var(--text-2);
}
.ctx__item.is-crit,
.ctx__item.is-crit svg {
  color: var(--crit-text);
}
li + li .ctx__item {
  border-top: 1px solid var(--line);
}

/* Kirish: parda so'nib kiradi, nusxa joyidan ko'tariladi (prujinali), menyu
   tekislangan burchagidan "ochiladi". Chiqish - teskari, qisqaroq. */
.ctx-enter-active .ctx__scrim {
  transition: opacity var(--dur-3) var(--ease-out);
}
.ctx-enter-active .ctx__lift {
  transition: transform var(--dur-3) var(--ease-sheet);
}
.ctx-enter-active .ctx__menu {
  transition:
    opacity var(--dur-2) var(--ease-out) 40ms,
    transform var(--dur-3) var(--ease-sheet) 40ms;
}
.ctx-leave-active .ctx__scrim,
.ctx-leave-active .ctx__menu {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.ctx-leave-active .ctx__lift {
  transition: transform var(--dur-2) var(--ease-out);
}
.ctx-enter-from .ctx__scrim,
.ctx-leave-to .ctx__scrim {
  opacity: 0;
}
.ctx-enter-from .ctx__lift,
.ctx-leave-to .ctx__lift {
  transform: translateY(var(--from-y)) scale(1);
}
.ctx-enter-from .ctx__menu,
.ctx-leave-to .ctx__menu {
  opacity: 0;
  transform: scale(0.9);
}
@media (prefers-reduced-motion: reduce) {
  .ctx__lift {
    transform: none;
  }
  .ctx-enter-from .ctx__lift,
  .ctx-leave-to .ctx__lift {
    transform: none;
  }
}
</style>
