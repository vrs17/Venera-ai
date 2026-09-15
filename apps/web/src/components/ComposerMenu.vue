<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConnectors } from '../composables/useConnectors'
import type { ConnectorId } from '../composables/useConnectors'
import { ChevronRightIcon, ImageIcon, PlugIcon } from '../icons'
import ConnectorDialog from './ConnectorDialog.vue'
import ConnectorList from './ConnectorList.vue'

/**
 * "+" tugmasining menyusi. Kirish maydoni ustida, yuqoriga ochiladi.
 *
 * Nega dock ichida emas: dock `.glass` (contain: paint) - undan tashqariga
 * chiqqan hamma narsa kesiladi. Shuning uchun menyu dockning yonida, uning
 * o'rami ichida turadi. "Tashqariga bosildi" tekshiruvi `anchor` (+ tugma)ni
 * ham menyuning bir qismi deb hisoblaydi - aks holda tugmaning o'zi menyuni
 * yopib, keyin darhol qayta ochardi.
 */
const props = defineProps<{ anchor: HTMLElement | null }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n({ useScope: 'global' })
// Har ochilishda holat serverdan yangilanadi: HRM sessiyasi 10 soatda
// tugaydi, CRM refresh rad etilishi mumkin - ro'yxat buni ko'rsatishi kerak.
const { load } = useConnectors()
const rootRef = ref<HTMLDivElement | null>(null)
const subOpen = ref(false)
// Qaysi tizimning ulanish oynasi ochiq. Oyna <body>ga teleport qilingan, ya'ni
// DOM'da menyudan tashqarida - shuning uchun u ochiqligida "tashqariga
// bosildi" tekshiruvi o'chib turadi, Escape esa avval oynani yopadi.
const dialogId = ref<ConnectorId | null>(null)

// Mobilda yon panel ekrandan chiqib ketadi - ro'yxat qator ostida ochiladi.
const mq = window.matchMedia('(max-width: 768px)')
const isMobile = ref(mq.matches)
function syncMq() {
  isMobile.value = mq.matches
}

function onDocDown(e: MouseEvent) {
  if (dialogId.value) return
  const target = e.target as Node
  if (rootRef.value?.contains(target) || props.anchor?.contains(target)) return
  emit('close')
}
// ChatView Escape'ni window'da tinglaydi va `defaultPrevented` bo'lsa o'tkazib
// yuboradi - shuning uchun preventDefault, yo'qsa menyu bilan birga yon panel
// ham yig'ilardi.
function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.isComposing) return
  e.preventDefault()
  if (dialogId.value) dialogId.value = null
  else emit('close')
}

onMounted(() => {
  void load()
  document.addEventListener('mousedown', onDocDown)
  document.addEventListener('keydown', onKeyDown)
  mq.addEventListener('change', syncMq)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('keydown', onKeyDown)
  mq.removeEventListener('change', syncMq)
})

// Desktopda sichqoncha qatorga kelsa yon panel ochiladi (bosish shart emas);
// boshqa qatorga o'tsa yopiladi. Mobilda faqat bosish.
function onConnectorsHover() {
  if (!isMobile.value) subOpen.value = true
}
function onOtherHover() {
  if (!isMobile.value) subOpen.value = false
}
</script>

<template>
  <div ref="rootRef" class="cmenu" role="menu" :aria-label="t('attach')">
    <div class="cmenu__panel glass">
      <!-- Rasm: yuklash hali yo'q, shuning uchun kulrang va bosilmaydi. -->
      <button
        type="button"
        class="cmenu__item is-disabled"
        role="menuitem"
        aria-disabled="true"
        :title="t('comingSoon')"
        @mouseenter="onOtherHover"
      >
        <ImageIcon :size="16" />
        <span class="cmenu__label">{{ t('addImage') }}</span>
        <span class="cmenu__hint">{{ t('comingSoon') }}</span>
      </button>

      <button
        type="button"
        class="cmenu__item"
        :class="{ 'is-active': subOpen }"
        role="menuitem"
        aria-haspopup="menu"
        :aria-expanded="subOpen"
        @click="subOpen = !subOpen"
        @mouseenter="onConnectorsHover"
      >
        <PlugIcon :size="16" />
        <span class="cmenu__label">{{ t('connectors') }}</span>
        <ChevronRightIcon class="cmenu__chev" :class="{ 'is-down': isMobile && subOpen }" :size="11" />
      </button>

      <ConnectorList v-if="isMobile && subOpen" class="cmenu__inline" @open="dialogId = $event" />
    </div>

    <div v-if="!isMobile && subOpen" class="cmenu__panel cmenu__fly glass" role="menu" :aria-label="t('connectors')">
      <ConnectorList @open="dialogId = $event" />
    </div>

    <ConnectorDialog v-if="dialogId" :connector-id="dialogId" @close="dialogId = null" />
  </div>
</template>

<style scoped>
.cmenu {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  display: flex;
  align-items: flex-end;
  gap: 6px;
  z-index: 40;
  pointer-events: auto;
}
.cmenu__panel {
  box-sizing: border-box;
  min-width: 224px;
  padding: 6px;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  box-shadow: var(--menu-shadow);
  animation: fadeUp 0.2s ease both;
}
.cmenu__fly {
  min-width: 250px;
}
.cmenu__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  font-family: 'Figtree', sans-serif;
  font-size: 13.5px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s;
}
.cmenu__item:hover,
.cmenu__item.is-active {
  background: var(--surface-hover);
}
.cmenu__item.is-disabled {
  color: var(--text-secondary);
  cursor: not-allowed;
  opacity: 0.6;
}
.cmenu__item.is-disabled:hover {
  background: transparent;
}
.cmenu__label {
  flex: 1;
  white-space: nowrap;
}
.cmenu__hint {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.cmenu__chev {
  flex-shrink: 0;
  color: var(--text-secondary);
  transition: transform 0.2s;
}
.cmenu__chev.is-down {
  transform: rotate(90deg);
}
.cmenu__inline {
  margin-top: 2px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
</style>
