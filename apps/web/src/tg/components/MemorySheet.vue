<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, RefreshCw, Trash2 } from 'lucide-vue-next'
import type { MemoryItem } from '../../api/assistant.api'
import { memoryOriginKey, useAssistantMemory } from '../../composables/useAssistantMemory'
import VCheckbox from '../../ui/VCheckbox.vue'
import VSheet from '../../ui/VSheet.vue'
import { fmtDate } from '../../ui/format'
import { toast } from '../../ui/useToast'
import { uzApostrophes } from '../chat/polish'
import { forgetAllHint } from '../../components/memoryCopy'
import { useTgSheet } from '../sheet'
import { haptic } from '../telegram'

/**
 * "Xotira" (Mini App, sozlamalardan): Barno foydalanuvchi haqida nimani eslab qolgani.
 * Web'dagi MemoryDialog bilan bir xil mantiq (`useAssistantMemory`), ko'rinishi - iOS
 * guruhlangan ro'yxati (sozlamalar oynasi kabi).
 *
 *   - band: Barno saqlagan gap, ostida kelib chiqishi va sanasi; o'ngda savat (44px);
 *   - savat bosilsa - qatorning O'ZIDA tasdiq ("Barno buni unutsinmi?" Bekor / Unutish):
 *     bitta tasodifiy bosish o'chirmaydi, qaytarish yo'q (yordamchida tiklash yo'li yo'q);
 *   - "Hammasini unutish" - alohida pastki oynada KUCHLI tasdiq: nechta narsa o'chishi,
 *     suhbatlar qolishi, qaytarib bo'lmasligi va "Tushundim" belgisisiz tugma o'chiq.
 *     Telegram'ning `showPopup` i bu yerda yo'q - unda belgilash katakchasi bo'lmaydi;
 *   - bo'sh holat: Barno nimani eslab qolishi va chatda qanday aytish ("Eslab qol: ...").
 *     Namunalar - qo'shtirnoqli xira iqtibos, pufakcha EMAS: chatdagi xabarga o'xshasa odam
 *     ularni bosardi va hech narsa bo'lmasdi (UX ko'rigi, 2026-10-10).
 *
 * Har ochilishda serverdan; yopilganda matnlar xotiradan tozalanadi.
 */
const open = defineModel<boolean>('open', { default: false })
const { t, locale } = useI18n({ useScope: 'global' })
const memory = useAssistantMemory()
const { items, status, removing, clearing } = memory

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
const wipeSheet = ref<InstanceType<typeof VSheet> | null>(null)
const wiping = ref(false)
const ack = ref(false)
const confirmId = ref<string | null>(null)
const listRef = ref<HTMLElement | null>(null)
useTgSheet(open, sheet)
useTgSheet(wiping, wipeSheet, { canClose: () => !clearing.value })

watch(open, (on) => {
  confirmId.value = null
  wiping.value = false
  if (on) void memory.load()
  else memory.reset()
})
watch(wiping, (on) => {
  if (on) ack.value = false
})

const uzLatin = computed(() => String(locale.value) === 'uz')
/** Band matni ham interfeys tutuq belgilarida (javob matni bilan bir xil). */
const textOf = (item: MemoryItem) => (uzLatin.value ? uzApostrophes(item.text) : item.text)
const originOf = (item: MemoryItem) => t(`assistant.memory.${memoryOriginKey(item)}`)
function dateOf(item: MemoryItem): string {
  const at = item.updated_at ?? item.created_at
  return at ? fmtDate(at, locale.value) : ''
}
const errorText = computed(() => {
  const kind = memory.error.value
  return t(`assistant.errors.${!kind || kind === 'notFound' ? 'generic' : kind}`)
})

function askForget(item: MemoryItem) {
  haptic.select()
  confirmId.value = item.id
  void nextTick(() => listRef.value?.querySelector<HTMLElement>(`[data-id="${CSS.escape(item.id)}"] [data-role="keep"]`)?.focus())
}

async function forget(item: MemoryItem) {
  const result = await memory.remove(item.id)
  if (result !== true) {
    haptic.notify('error')
    toast.error(`${t('assistant.memory.forgetFailed')}. ${t(`assistant.errors.${result === 'notFound' ? 'generic' : result}`)}`)
    return
  }
  haptic.notify('success')
  confirmId.value = null
  toast.show(t('assistant.memory.forgotten'))
}

async function forgetAll() {
  if (!ack.value || clearing.value) return
  const result = await memory.forgetAll()
  if (result !== true) {
    haptic.notify('error')
    toast.error(`${t('assistant.memory.forgetAllFailed')}. ${t(`assistant.errors.${result === 'notFound' ? 'generic' : result}`)}`)
    return
  }
  haptic.notify('success')
  wiping.value = false
  toast.show(t('assistant.memory.forgotAll'))
}
</script>

<template>
  <VSheet ref="sheet" v-model:open="open" class="tg-sheet tg-sheet--grouped" side="bottom" :title="t('assistant.memory.title')">
    <div class="mem">
      <p class="mem__lead">{{ t('assistant.memory.lead') }}</p>

      <!-- Yuklanmoqda -->
      <section v-if="status === 'loading' || status === 'idle'" class="mem__card" aria-hidden="true">
        <div v-for="n in 3" :key="n" class="mem__row">
          <span class="mem__body">
            <span class="tg-skel mem__skel" />
            <span class="tg-skel mem__skel mem__skel--short" />
          </span>
        </div>
      </section>

      <!-- Xato -->
      <section v-else-if="status === 'error'" class="mem__card mem__error" role="alert">
        <p class="mem__error-title">{{ t('assistant.memory.loadFailed') }}</p>
        <p class="mem__error-text">{{ errorText }}</p>
        <button type="button" class="mem__retry" @click="memory.load()">
          <RefreshCw :size="16" :stroke-width="1.75" aria-hidden="true" />
          {{ t('assistant.memory.retry') }}
        </button>
      </section>

      <!-- Bo'sh -->
      <section v-else-if="!items.length" class="mem__empty">
        <span class="mem__empty-icon" aria-hidden="true"><Brain :size="24" :stroke-width="1.75" /></span>
        <p class="mem__empty-title">{{ t('assistant.memory.emptyTitle') }}</p>
        <p class="mem__empty-text">{{ t('assistant.memory.emptyBody') }}</p>
        <!-- Namuna - oddiy iqtibos (bosiladigan narsaga o'xshamasin). -->
        <p class="mem__example"><q>{{ t('assistant.memory.exampleRemember') }}</q></p>
        <p class="mem__example"><q>{{ t('assistant.memory.exampleForget') }}</q></p>
      </section>

      <!-- Ro'yxat -->
      <template v-else>
        <ul ref="listRef" class="mem__card mem__list" :aria-label="t('assistant.memory.title')">
          <li
            v-for="item in items"
            :key="item.id"
            class="mem__row"
            :class="{ 'is-confirming': confirmId === item.id }"
            :data-id="item.id"
            :aria-busy="removing === item.id ? 'true' : undefined"
          >
            <span class="mem__body">
              <span class="mem__text">{{ textOf(item) }}</span>
              <span class="mem__meta">
                {{ originOf(item) }}<template v-if="dateOf(item)"> · {{ dateOf(item) }}</template>
              </span>
              <span v-if="confirmId === item.id" class="mem__confirm" role="group" :aria-label="t('assistant.memory.forgetConfirm')">
                <span class="mem__confirm-q">{{ t('assistant.memory.forgetConfirm') }}</span>
                <span class="mem__confirm-hint">{{ t('assistant.memory.forgetConfirmHint') }}</span>
                <span class="mem__confirm-actions">
                  <button type="button" class="mem__btn" data-role="keep" :disabled="removing === item.id" @click="confirmId = null">
                    {{ t('ui.cancel') }}
                  </button>
                  <button
                    type="button"
                    class="mem__btn mem__btn--danger"
                    :disabled="removing === item.id"
                    :aria-busy="removing === item.id ? 'true' : undefined"
                    @click="forget(item)"
                  >
                    <span v-if="removing === item.id" class="mem__spinner" aria-hidden="true" />
                    {{ removing === item.id ? t('assistant.memory.forgetting') : t('assistant.memory.forget') }}
                  </button>
                </span>
              </span>
            </span>
            <button
              v-if="confirmId !== item.id"
              type="button"
              class="mem__trash"
              :aria-label="t('assistant.memory.forgetAria', { text: item.text })"
              :disabled="!!removing || clearing"
              @click="askForget(item)"
            >
              <Trash2 :size="18" :stroke-width="1.75" aria-hidden="true" />
            </button>
          </li>
        </ul>
        <p class="mem__caption">{{ t('assistant.memory.tip') }}</p>

        <section class="mem__card">
          <button type="button" class="mem__wipe" :disabled="!!removing" @click="wiping = true">
            <Trash2 :size="20" :stroke-width="1.75" aria-hidden="true" />
            <span>{{ t('assistant.memory.forgetAll') }}</span>
          </button>
        </section>
      </template>
    </div>
  </VSheet>

  <!-- "Hammasini unutish" - kuchli tasdiq. ✕ yo'q: "Bekor qilish" tugmasi bor. -->
  <VSheet
    ref="wipeSheet"
    v-model:open="wiping"
    class="tg-sheet"
    side="bottom"
    role="alertdialog"
    hide-close
    :dismissible="!clearing"
    :title="t('assistant.memory.forgetAllTitle')"
    :description="forgetAllHint(items, t)"
  >
    <div class="wipe">
      <div class="wipe__ack">
        <VCheckbox v-model="ack" :label="t('assistant.memory.forgetAllAck')" />
      </div>
      <button type="button" class="wipe__btn wipe__btn--danger" :disabled="!ack || clearing" @click="forgetAll">
        <span v-if="clearing" class="mem__spinner" aria-hidden="true" />
        {{ t('assistant.memory.forgetAllYes') }}
      </button>
      <button type="button" class="wipe__btn" :disabled="clearing" @click="wiping = false">{{ t('ui.cancel') }}</button>
    </div>
  </VSheet>
</template>

<style scoped>
.mem {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  padding-bottom: var(--s-2);
}
.mem__lead,
.mem__caption {
  padding: 0 var(--s-4);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-wrap: pretty;
}
.mem__card {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  border-radius: 14px;
  background: var(--surface);
  overflow: hidden;
  list-style: none;
}
.mem__row {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  min-height: 56px;
  padding: var(--s-3) var(--s-2) var(--s-3) var(--s-4);
}
.mem__row + .mem__row {
  border-top: 1px solid var(--line);
}
.mem__row.is-confirming {
  padding-right: var(--s-4);
}
.mem__row[aria-busy='true'] .mem__text {
  color: var(--text-3);
}
.mem__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}
.mem__text {
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  overflow-wrap: anywhere;
}
.mem__meta {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.mem__trash {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  margin: -10px 0 -10px 0;
  border-radius: var(--r-full);
  color: var(--text-3);
}
.mem__trash:active {
  background: var(--fill);
}
.mem__trash:disabled {
  opacity: 0.4;
}

.mem__confirm {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--s-2);
  padding: var(--s-3);
  border-radius: 12px;
  background: var(--crit-soft);
}
.mem__confirm-q {
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
.mem__confirm-hint {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.mem__confirm-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-2);
  margin-top: var(--s-2);
}
.mem__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-1_5);
  min-height: 44px;
  border-radius: 12px;
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 600;
}
.mem__btn--danger {
  background: var(--crit);
  color: #fff;
}
.mem__btn:active:not(:disabled) {
  transform: scale(0.98);
}
.mem__btn:disabled {
  opacity: 0.7;
}

.mem__wipe {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  min-height: 52px;
  padding: var(--s-2) var(--s-4);
  color: var(--crit-text);
  font-size: var(--fs-body);
  font-weight: 500;
  text-align: left;
}
.mem__wipe:active {
  background: var(--fill);
}
.mem__wipe:disabled {
  opacity: 0.5;
}

.mem__skel {
  width: 80%;
  height: 14px;
}
.mem__skel--short {
  width: 45%;
  height: 10px;
}

.mem__error {
  align-items: flex-start;
  gap: var(--s-1);
  padding: var(--s-4);
}
.mem__error-title {
  font-size: var(--fs-body);
  font-weight: 600;
}
.mem__error-text {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.mem__retry {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  min-height: 44px;
  margin-top: var(--s-1);
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 600;
}

.mem__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-5) var(--s-4) var(--s-4);
  border-radius: 14px;
  background: var(--surface);
  text-align: center;
}
.mem__empty-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  margin-bottom: var(--s-1);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.mem__empty-title {
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body);
  font-weight: 600;
}
.mem__empty-text {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}
/* Namuna - fonsiz, kursiv, xira iqtibos: tugma yoki xabar pufakchasiga o'xshamasin. */
.mem__example {
  max-width: 100%;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-style: italic;
}
.mem__example q {
  quotes: '«' '»';
}

.mem__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: mem-spin 0.8s linear infinite;
}
@keyframes mem-spin {
  to { transform: rotate(360deg); }
}

/* Qorong'i mavzu: kartalar fondan bir pog'ona ochroq (SettingsSheet bilan bir xil). */
html[data-theme='dark'] .mem__card,
html[data-theme='dark'] .mem__empty {
  background: var(--fill);
}
html[data-theme='dark'] .mem__empty-icon,
html[data-theme='dark'] .mem__btn:not(.mem__btn--danger) {
  background: var(--fill-hover);
}

.wipe {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  padding-top: var(--s-2);
}
.wipe__ack {
  padding: var(--s-3);
  border-radius: 14px;
  background: var(--crit-soft);
}
.wipe__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  min-height: 52px;
  border-radius: 14px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body);
  font-weight: 600;
}
.wipe__btn--danger {
  background: var(--crit);
  color: #fff;
}
.wipe__btn--danger:disabled {
  opacity: 0.45;
}
.wipe__btn:active:not(:disabled) {
  transform: scale(0.98);
}
</style>
