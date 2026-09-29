<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { clamp, cssColor, useElementSize, type TooltipRow } from './scale'

/**
 * Grafik o'qish kartochkasi: bitta tooltip, shu x dagi HAMMA qatorlar.
 * Qiymat oldinda (qalin), nom ortidan (ikkinchi darajali) - o'quvchi qatorni biladi,
 * unga raqam kerak. Matn faqat `{{ }}` orqali (nomlar API dan keladi - v-html yo'q).
 *
 * Ekran o'quvchi uchun `aria-hidden`: grafik o'zi jonli hududda o'qib beradi,
 * ikki marta eshitilmasin.
 */
const props = withDefaults(
  defineProps<{
    visible: boolean
    /** Ota konteyner ichidagi langar nuqta (px). */
    x: number
    y: number
    /** Konteyner kengligi/balandligi - tooltip chetdan chiqmasin. */
    boundsWidth: number
    boundsHeight?: number
    /**
     * Chap chegara (ota koordinatasida, odatda 0). Manfiy - tooltip langar konteyneridan
     * chapga chiqa oladi: sharsharada yo'lak tor (telefon), tooltip nomlar ustuni ustiga
     * surilmasa sahifadan o'ngga toshib ketardi.
     */
    boundsLeft?: number
    title?: string
    /** Sarlavha ostidagi izoh (o'raladi): masalan tor ekranda yashirilgan bosqich matni. */
    note?: string
    rows: TooltipRow[]
    /** side - langarning o'ng/chap yonida; above - tepasida markazda. */
    placement?: 'side' | 'above'
    offset?: number
  }>(),
  { placement: 'side', offset: 12, boundsHeight: 0, boundsLeft: 0, title: '', note: '' },
)

const el = ref<HTMLElement | null>(null)
const { width: w, height: h } = useElementSize(el)

const pos = computed(() => {
  const tw = w.value
  const th = h.value
  const minLeft = props.boundsLeft
  if (props.placement === 'above') {
    const left = clamp(props.x - tw / 2, minLeft, Math.max(minLeft, props.boundsWidth - tw))
    let top = props.y - props.offset - th
    if (top < 0) top = props.y + props.offset
    return { left, top }
  }
  const right = props.x + props.offset
  const left = right + tw <= props.boundsWidth ? right : Math.max(minLeft, props.x - props.offset - tw)
  const top = props.boundsHeight > 0 ? clamp(props.y, 0, Math.max(0, props.boundsHeight - th)) : props.y
  return { left, top }
})

// Yangi paydo bo'lganda joyiga "sirg'anib" kelmasin - birinchi kadr animatsiyasiz.
const instant = ref(true)
watch(
  () => props.visible,
  async (on) => {
    if (!on) {
      instant.value = true
      return
    }
    await nextTick()
    requestAnimationFrame(() => (instant.value = false))
  },
)
</script>

<template>
  <div
    ref="el"
    class="vct"
    :class="{ 'is-on': visible, 'is-instant': instant }"
    :style="{ transform: `translate3d(${Math.round(pos.left)}px, ${Math.round(pos.top)}px, 0)` }"
    aria-hidden="true"
  >
    <p v-if="title" class="vct-title">{{ title }}</p>
    <p v-if="note" class="vct-note">{{ note }}</p>
    <div v-if="rows.length" class="vct-rows">
      <template v-for="r in rows" :key="r.key">
        <span class="vct-mark" :class="`is-${r.mark ?? 'line'}`" :style="{ '--c': cssColor(r.color) }" />
        <span class="vct-value">{{ r.value }}</span>
        <span class="vct-label">{{ r.label }}</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.vct {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 5;
  min-width: 128px;
  max-width: 280px;
  padding: var(--s-2) 10px 9px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  box-shadow: var(--e2);
  pointer-events: none;
  opacity: 0;
  visibility: hidden;
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s linear var(--dur-1),
    transform var(--dur-1) var(--ease-out);
}
.vct.is-on {
  opacity: 1;
  visibility: visible;
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s,
    transform var(--dur-1) var(--ease-out);
}
.vct.is-instant {
  transition:
    opacity var(--dur-1) var(--ease-out),
    visibility 0s;
}
.vct-title {
  margin-bottom: var(--s-1_5);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.vct-note {
  margin: calc(var(--s-1) * -1) 0 var(--s-1_5);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.vct-rows {
  display: grid;
  grid-template-columns: 12px auto minmax(0, 1fr);
  align-items: center;
  column-gap: var(--s-2);
  row-gap: var(--s-1);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.vct-value {
  justify-self: end;
  font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.vct-label {
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Qator kaliti - qisqa chiziq (qutisiz): tooltip zichligida to'ldirilgan quti
   ma'lumot og'irligidagi siyoh bo'lib qoladi. */
.vct-mark {
  justify-self: center;
  width: 12px;
  height: 2px;
  border-radius: 1px;
  background: var(--c);
}
.vct-mark.is-dashed {
  background: none;
  border-top: 2px dashed var(--c);
  height: 0;
  border-radius: 0;
}
.vct-mark.is-rect {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.vct-mark.is-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.vct-mark.is-none {
  background: none;
}
</style>
