<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Brain, RefreshCw, Trash2 } from 'lucide-vue-next'
import type { MemoryItem } from '../api/assistant.api'
import { memoryOriginKey, useAssistantMemory } from '../composables/useAssistantMemory'
import VButton from '../ui/VButton.vue'
import VCheckbox from '../ui/VCheckbox.vue'
import VDialog from '../ui/VDialog.vue'
import VIconButton from '../ui/VIconButton.vue'
import VSkeleton from '../ui/VSkeleton.vue'
import { fmtDate } from '../ui/format'
import { toast } from '../ui/useToast'
import { uzApostrophes } from '../tg/chat/polish'
import { forgetAllHint } from './memoryCopy'

/**
 * "Xotira" (web): Barno foydalanuvchi haqida nimani eslab qolgani - hisob menyusidan.
 *
 * Ro'yxat: har band - Barno saqlagan gap, ostida kelib chiqishi ("Siz eslab qolishni
 * so'ragansiz" / "Savollaringizdan o'rganilgan" / "CRM vazifalaringizdan o'rganilgan") va
 * sanasi (bo'lsa). Bitta bandni unutish - qatorning o'zida tasdiq (Bekor / Unutish):
 * alohida oyna ochilmaydi, lekin tasodifiy bitta bosish ham o'chirmaydi. Qaytarish yo'q -
 * yordamchida "tiklash" yo'li yo'q, shuning uchun "bekor qilish" toast'i ham yo'q.
 *
 * "Hammasini unutish" - KUCHLI tasdiq: alohida ko'rinish (nima o'chishi, nechta, suhbatlar
 * qolishi, qaytarib bo'lmasligi) va "Tushundim" belgisisiz tugma bosilmaydi.
 *
 * Bo'sh holat - Barno nimani eslab qolishini va chatda qanday aytishni o'rgatadi
 * ("Eslab qol: ...", "... ni unut"). Namunalar - IQTIBOS (qo'shtirnoq, xira), tugma yoki
 * chip EMAS: pill ko'rinishida odam ularni bosardi va hech narsa bo'lmasdi (UX ko'rigi).
 *
 * Holat har ochilishda serverdan (chatda yangi narsa eslab qolingan bo'lishi mumkin);
 * yopilganda matnlar xotiradan tozalanadi.
 */
const open = defineModel<boolean>('open', { default: false })
const { t, locale } = useI18n({ useScope: 'global' })
const memory = useAssistantMemory()
const { items, status, removing, clearing } = memory

type View = 'list' | 'forgetAll'
const view = ref<View>('list')
const confirmId = ref<string | null>(null)
const ack = ref(false)
const headingRef = ref<HTMLElement | null>(null)
const listRef = ref<HTMLElement | null>(null)

watch(
  open,
  (on) => {
    view.value = 'list'
    confirmId.value = null
    ack.value = false
    if (on) void memory.load()
    else memory.reset()
  },
  { immediate: true },
)

const title = computed(() => (view.value === 'forgetAll' ? t('assistant.memory.forgetAllTitle') : t('assistant.memory.title')))
const subtitle = computed(() => (view.value === 'forgetAll' ? forgetAllHint(items.value, t) : t('assistant.memory.lead')))

/** Band matni interfeys tutuq belgilarida (Mini App va javob matni bilan bir xil): yonida
 *  "ʻ" li UI matni turganda "ro'yxat" ASCII belgisi bilan chiqmasin. */
const uzLatin = computed(() => String(locale.value) === 'uz')
const textOf = (item: MemoryItem) => (uzLatin.value ? uzApostrophes(item.text) : item.text)

function errorText(): string {
  return t(`assistant.errors.${memory.error.value === 'notFound' || !memory.error.value ? 'generic' : memory.error.value}`)
}

function originOf(item: MemoryItem): string {
  return t(`assistant.memory.${memoryOriginKey(item)}`)
}
function dateOf(item: MemoryItem): string {
  const at = item.updated_at ?? item.created_at
  return at ? fmtDate(at, locale.value) : ''
}

function askForget(item: MemoryItem) {
  confirmId.value = item.id
  // Xavfli tugma emas, "Bekor qilish" ga - Enter tasodifan o'chirib yubormasin.
  void nextTick(() => listRef.value?.querySelector<HTMLElement>(`[data-id="${CSS.escape(item.id)}"] [data-role="keep"]`)?.focus())
}
function keep(item: MemoryItem) {
  confirmId.value = null
  void nextTick(() => listRef.value?.querySelector<HTMLElement>(`[data-id="${CSS.escape(item.id)}"] [data-role="forget"]`)?.focus())
}

async function forget(item: MemoryItem) {
  const index = items.value.findIndex((m) => m.id === item.id)
  const result = await memory.remove(item.id)
  if (result !== true) {
    toast.error(`${t('assistant.memory.forgetFailed')}. ${t(`assistant.errors.${result === 'notFound' ? 'generic' : result}`)}`)
    return
  }
  confirmId.value = null
  toast.show(t('assistant.memory.forgotten'))
  // Fokus keyingi bandning "Unutish" tugmasiga (bo'lmasa - sarlavhaga): klaviatura bilan
  // ishlayotgan odam ro'yxatdagi joyini yo'qotmasin.
  await nextTick()
  const next = items.value[Math.min(index, items.value.length - 1)]
  const el = next ? listRef.value?.querySelector<HTMLElement>(`[data-id="${CSS.escape(next.id)}"] [data-role="forget"]`) : null
  ;(el ?? headingRef.value)?.focus()
}

function toForgetAll() {
  confirmId.value = null
  ack.value = false
  view.value = 'forgetAll'
  void nextTick(() => headingRef.value?.focus())
}
function backToList() {
  view.value = 'list'
  ack.value = false
  void nextTick(() => headingRef.value?.focus())
}
async function forgetAll() {
  if (!ack.value) return
  const result = await memory.forgetAll()
  if (result !== true) {
    toast.error(`${t('assistant.memory.forgetAllFailed')}. ${t(`assistant.errors.${result === 'notFound' ? 'generic' : result}`)}`)
    return
  }
  toast.show(t('assistant.memory.forgotAll'))
  backToList()
}
</script>

<template>
  <VDialog v-model:open="open" size="md" :dismissible="!clearing">
    <template #header="{ titleId }">
      <div class="mem__head">
        <VIconButton
          v-if="view === 'forgetAll'"
          class="mem__back"
          :label="t('composer.back')"
          :icon="ArrowLeft"
          size="sm"
          tooltip-placement="bottom"
          :disabled="clearing"
          @click="backToList"
        />
        <div class="mem__titles">
          <h2 :id="titleId" ref="headingRef" class="mem__title" tabindex="-1">{{ title }}</h2>
          <p class="mem__sub">{{ subtitle }}</p>
        </div>
      </div>
    </template>

    <!-- Hammasini unutish: kuchli tasdiq -->
    <div v-if="view === 'forgetAll'" class="mem__wipe">
      <VCheckbox v-model="ack" :label="t('assistant.memory.forgetAllAck')" />
    </div>

    <!-- Yuklanmoqda -->
    <ul v-else-if="status === 'loading' || status === 'idle'" class="mem__list" aria-hidden="true">
      <li v-for="n in 3" :key="n" class="mem__row">
        <span class="mem__body">
          <VSkeleton :width="'85%'" :height="14" />
          <VSkeleton :width="'45%'" :height="10" />
        </span>
      </li>
    </ul>

    <!-- Xato -->
    <div v-else-if="status === 'error'" class="mem__error" role="alert">
      <p class="mem__error-title">{{ t('assistant.memory.loadFailed') }}</p>
      <p class="mem__error-text">{{ errorText() }}</p>
      <VButton size="sm" variant="secondary" :icon="RefreshCw" @click="memory.load()">{{ t('assistant.memory.retry') }}</VButton>
    </div>

    <!-- Bo'sh: Barno nimani eslab qoladi va qanday aytiladi -->
    <div v-else-if="!items.length" class="mem__empty">
      <span class="mem__empty-icon" aria-hidden="true"><Brain :size="22" :stroke-width="1.75" /></span>
      <p class="mem__empty-title">{{ t('assistant.memory.emptyTitle') }}</p>
      <p class="mem__empty-text">{{ t('assistant.memory.emptyBody') }}</p>
      <ul class="mem__examples">
        <li><q>{{ t('assistant.memory.exampleRemember') }}</q></li>
        <li><q>{{ t('assistant.memory.exampleForget') }}</q></li>
      </ul>
    </div>

    <!-- Ro'yxat -->
    <template v-else>
      <ul ref="listRef" class="mem__list" :aria-label="t('assistant.memory.title')">
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
              <span>{{ originOf(item) }}</span>
              <template v-if="dateOf(item)">
                <span aria-hidden="true">·</span>
                <span>{{ dateOf(item) }}</span>
              </template>
            </span>
            <span v-if="confirmId === item.id" class="mem__confirm" role="group" :aria-label="t('assistant.memory.forgetConfirm')">
              <span class="mem__confirm-text">
                <strong>{{ t('assistant.memory.forgetConfirm') }}</strong>
                {{ t('assistant.memory.forgetConfirmHint') }}
              </span>
              <span class="mem__confirm-actions">
                <VButton size="sm" variant="ghost" data-role="keep" :disabled="removing === item.id" @click="keep(item)">
                  {{ t('ui.cancel') }}
                </VButton>
                <VButton size="sm" variant="danger" :loading="removing === item.id" @click="forget(item)">
                  {{ t('assistant.memory.forget') }}
                </VButton>
              </span>
            </span>
          </span>
          <VIconButton
            v-if="confirmId !== item.id"
            class="mem__forget"
            data-role="forget"
            :icon="Trash2"
            size="sm"
            :label="t('assistant.memory.forgetAria', { text: item.text })"
            :disabled="!!removing || clearing"
            @click="askForget(item)"
          />
        </li>
      </ul>
      <p class="mem__tip">{{ t('assistant.memory.tip') }}</p>
    </template>

    <template v-if="view === 'forgetAll'" #footer>
      <VButton variant="ghost" :disabled="clearing" @click="backToList">{{ t('ui.cancel') }}</VButton>
      <VButton variant="danger" :disabled="!ack" :loading="clearing" @click="forgetAll">{{ t('assistant.memory.forgetAllYes') }}</VButton>
    </template>
    <template v-else-if="status === 'ready' && items.length" #footer>
      <VButton class="mem__wipe-btn" variant="ghost" :icon="Trash2" :disabled="!!removing" @click="toForgetAll">
        {{ t('assistant.memory.forgetAll') }}
      </VButton>
      <VButton variant="secondary" @click="open = false">{{ t('close') }}</VButton>
    </template>
  </VDialog>
</template>

<style scoped>
.mem__head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
}
.mem__back {
  margin: -4px 0 0 -8px;
}
.mem__titles {
  flex: 1;
  min-width: 0;
}
.mem__title {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
  text-wrap: balance;
}
.mem__title:focus,
.mem__title:focus-visible {
  outline: none;
}
.mem__sub {
  margin-top: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}

.mem__list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.mem__row {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
  padding: var(--s-3) 0;
}
.mem__row + .mem__row {
  border-top: 1px solid var(--line);
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
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
  transition: color var(--dur-1) var(--ease-out);
}
.mem__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.mem__forget {
  flex-shrink: 0;
  margin-top: -4px;
  color: var(--text-3);
}

/* Qator ichidagi tasdiq - kichik och-qizil quti: alohida oyna emas, lekin ko'zdan qochmaydi. */
.mem__confirm {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-2) var(--s-3);
  margin-top: var(--s-2);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-md);
  background: var(--crit-soft);
}
.mem__confirm-text {
  flex: 1 1 220px;
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.mem__confirm-text strong {
  display: block;
  color: var(--crit-text);
  font-weight: 600;
}
.mem__confirm-actions {
  display: flex;
  gap: var(--s-2);
  flex-shrink: 0;
}

.mem__tip {
  margin-top: var(--s-3);
  padding-top: var(--s-3);
  border-top: 1px solid var(--line);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

.mem__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-6) var(--s-2) var(--s-4);
  text-align: center;
}
.mem__empty-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  margin-bottom: var(--s-1);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.mem__empty-title {
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 600;
}
.mem__empty-text {
  max-width: 400px;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}
.mem__examples {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-1_5);
  margin: var(--s-2) 0 0;
  padding: 0;
  list-style: none;
}
/* Namuna - oddiy iqtibos: fonsiz, belgisiz, kursiv va xira - bosiladigan narsaga o'xshamasin. */
.mem__examples li {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-style: italic;
}
.mem__examples q {
  quotes: '«' '»';
}

.mem__error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-2);
  padding: var(--s-4) 0;
}
.mem__error-title {
  color: var(--text);
  font-size: var(--fs-body-sm);
  font-weight: 600;
}
.mem__error-text {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

.mem__wipe {
  padding: var(--s-3);
  border-radius: var(--r-md);
  background: var(--crit-soft);
}

/* "Hammasini unutish" - xavfli, lekin asosiy emas: qizil matn, chapda. */
.mem__wipe-btn {
  margin-right: auto;
  color: var(--crit-text);
}
</style>
