<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, CircleCheck, X } from 'lucide-vue-next'
import { LAYER_IGNORE_ATTR } from './composables/useClickOutside'
import { useToast } from './useToast'
import type { ToastItem } from './useToast'

/**
 * Bildirishnomalar joyi (VToastHost): pastki markazda, siyoh fonida bir qator matn
 * va ixtiyoriy bitta harakat ("Qaytarish"). App.vue da BIR marta o'rnatiladi:
 *
 *   <VToastHost />            // chiqarish:  const { show } = useToast(); show('Yuborildi')
 *
 * - `aria-live="polite"` ro'yxat doim DOM'da - yangi toast ekran o'quvchida o'qiladi.
 * - Sichqoncha ustida yoki ichida fokus bo'lsa - vaqt to'xtaydi.
 * - Qatlam tizimi uni "tashqi" deb hisoblamaydi: toast'ga bosish ochiq dialog yoki
 *   menyuni yopmaydi, fokus tuzog'i ham uni ushlamaydi.
 * - Chat kabi pastida kompozer bor sahifalar `--toast-offset` o'zgaruvchisi bilan
 *   toast'ni yuqoriroq ko'tarishi mumkin.
 */
defineOptions({ name: 'VToastHost' })

const { t } = useI18n({ useScope: 'global' })
const { toasts, dismiss, pause, resume } = useToast()

function runAction(item: ToastItem) {
  item.action?.onClick()
  dismiss(item.id)
}

function onFocusOut(e: FocusEvent) {
  const host = e.currentTarget as HTMLElement
  if (!(e.relatedTarget instanceof Node) || !host.contains(e.relatedTarget)) resume('focus')
}

onBeforeUnmount(() => {
  resume('hover')
  resume('focus')
})

const ignoreAttr = { [LAYER_IGNORE_ATTR]: '' }
</script>

<template>
  <Teleport to="body">
    <section
      class="v-toast-host"
      :aria-label="t('ui.notifications')"
      v-bind="ignoreAttr"
      @pointerenter="pause('hover')"
      @pointerleave="resume('hover')"
      @focusin="pause('focus')"
      @focusout="onFocusOut"
    >
      <TransitionGroup tag="ol" name="v-toast" class="v-toast-list" aria-live="polite" aria-relevant="additions text">
        <li v-for="item in toasts" :key="item.id" class="v-toast-slot">
          <div class="v-toast-clip">
            <div class="v-toast" :class="`v-toast--${item.tone}`">
              <CircleCheck v-if="item.tone === 'good'" class="v-toast__icon" :size="16" :stroke-width="2" aria-hidden="true" />
              <CircleAlert v-else-if="item.tone === 'crit'" class="v-toast__icon" :size="16" :stroke-width="2" aria-hidden="true" />
              <span class="v-toast__msg">{{ item.message }}</span>
              <button v-if="item.action" type="button" class="v-toast__action" @click="runAction(item)">
                {{ item.action.label }}
              </button>
              <button type="button" class="v-toast__close" :aria-label="t('ui.close')" @click="dismiss(item.id)">
                <X :size="14" :stroke-width="2" aria-hidden="true" />
              </button>
            </div>
          </div>
        </li>
      </TransitionGroup>
    </section>
  </Teleport>
</template>

<style scoped>
.v-toast-host {
  position: fixed;
  left: 50%;
  bottom: calc(var(--toast-offset, var(--s-6)) + env(safe-area-inset-bottom, 0px));
  z-index: var(--z-toast);
  width: max-content;
  max-width: min(440px, calc(100vw - var(--s-8)));
  transform: translateX(-50%);
  pointer-events: none;
}
@media (max-width: 767.98px) {
  .v-toast-host {
    left: var(--s-4);
    right: var(--s-4);
    width: auto;
    max-width: none;
    transform: none;
  }
}
.v-toast-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0;
  padding: 0;
  list-style: none;
}
/* Har bir qator grid: yo'qolayotganda balandligi 1fr → 0fr ga silliq yig'iladi va
   qolganlari o'z joyiga "sirg'anib" tushadi (absolute joylashuvsiz). */
.v-toast-slot {
  display: grid;
  grid-template-rows: 1fr;
  width: 100%;
}
.v-toast-clip {
  display: flex;
  justify-content: center;
  min-height: 0;
  padding-top: var(--s-2);
}
/* Kesish faqat animatsiya paytida - tinch holatda soya to'liq ko'rinadi. */
.v-toast-enter-active .v-toast-clip,
.v-toast-leave-active .v-toast-clip {
  overflow: hidden;
}
.v-toast {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  max-width: 100%;
  min-height: 44px;
  padding: var(--s-2) var(--s-2) var(--s-2) var(--s-4);
  border-radius: var(--r-md);
  background: var(--ink);
  color: var(--on-ink);
  box-shadow: var(--e2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  pointer-events: auto;
}
@media (max-width: 767.98px) {
  .v-toast {
    width: 100%;
  }
}
.v-toast__icon {
  flex-shrink: 0;
  margin-left: -2px;
}
.v-toast--good .v-toast__icon {
  color: var(--good);
}
.v-toast--crit .v-toast__icon {
  color: var(--crit);
}
.v-toast__msg {
  flex: 1;
  min-width: 0;
  padding: 2px var(--s-1) 2px 0;
  text-wrap: pretty;
}
.v-toast__action {
  flex-shrink: 0;
  height: 28px;
  padding: 0 10px;
  border-radius: var(--r-sm);
  background: color-mix(in srgb, var(--on-ink) 12%, transparent);
  color: var(--on-ink);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-toast__action:hover {
    background: color-mix(in srgb, var(--on-ink) 20%, transparent);
  }
}
.v-toast__close {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  color: color-mix(in srgb, var(--on-ink) 56%, transparent);
  transition:
    color var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out),
    opacity var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .v-toast__close:hover {
    color: var(--on-ink);
    background: color-mix(in srgb, var(--on-ink) 12%, transparent);
  }
}
/* Sichqonchali qurilmada × faqat hover/fokusda - toast "bir qator" bo'lib qoladi. */
@media (hover: hover) {
  .v-toast:not(:hover):not(:focus-within) .v-toast__close {
    opacity: 0;
  }
}
.v-toast :focus-visible {
  outline-color: var(--on-ink);
}

/* ---- kirish / chiqish ---- */
.v-toast-enter-active {
  transition:
    grid-template-rows var(--dur-3) var(--ease-sheet),
    opacity var(--dur-2) var(--ease-out);
}
.v-toast-enter-active .v-toast {
  transition: transform var(--dur-3) var(--ease-sheet);
}
.v-toast-leave-active {
  transition:
    grid-template-rows var(--dur-2) var(--ease-out),
    opacity var(--dur-1) var(--ease-out);
}
.v-toast-leave-active .v-toast {
  transition: transform var(--dur-2) var(--ease-out);
}
.v-toast-enter-from,
.v-toast-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}
.v-toast-enter-from .v-toast {
  transform: translateY(12px) scale(0.98);
}
.v-toast-leave-to .v-toast {
  transform: scale(0.96);
}
</style>
