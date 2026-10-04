<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert } from 'lucide-vue-next'
import { ApiError } from '../../api/http'
import VButton from '../../ui/VButton.vue'
import VChoiceChips from '../../ui/VChoiceChips.vue'
import VDialog from '../../ui/VDialog.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { useToast } from '../../ui/useToast'
import type { ChoiceOption } from '../../ui/VChoiceChips.vue'
import { createReport, REPORT_COMMENT_MAX, REPORT_REASONS } from './report.api'
import type { ReportMessage, ReportReason } from './report.api'

/**
 * "Xabar berish" oynasi (spec §4.4). Butun suhbat jamoaga ketadi; `turnId` berilsa -
 * aynan shu javob belgilanadi (suhbatning qolgani baribir ilova qilinadi).
 *
 * Sabab ham, izoh ham ixtiyoriy: tugmani bosishning o'zi foydali signal - odamni
 * majburlasak, u shunchaki yopib ketadi.
 *
 * Yuborish paytida oyna yopilmaydi (Esc, tashqariga bosish, ×) - aks holda so'rov
 * natijasi ko'rinmay qolardi. Xatoda yozilgan izoh SAQLANADI; boshqa javob uchun
 * qayta ochilganda esa hammasi tozalanadi (eski izoh boshqa javobga tushmasin).
 */
const props = defineProps<{
  open: boolean
  chatId: string | null
  turnId?: string | null
  messages: ReportMessage[]
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  sent: [payload: { id: string; turnId: string | null }]
}>()

const { t } = useI18n({ useScope: 'global' })
const toast = useToast()

// Hisoblagich faqat oxiriga yaqinlashganda (spec: 1800 dan keyin).
const COUNTER_FROM = 1800

const reason = ref<ReportReason | null>(null)
const comment = ref('')
const sending = ref(false)
const error = ref('')
let aborter: AbortController | null = null

const reasonOptions = computed<ChoiceOption<ReportReason>[]>(() =>
  REPORT_REASONS.map((value) => ({ value, label: t(`report.reason.${value}`) })),
)

// Qaysi suhbat/javob uchun ochilgan - nishon o'zgarsa qoralama tozalanadi.
let lastTarget: string | null = null
function targetKey(): string {
  return `${props.chatId ?? ''}|${props.turnId ?? ''}`
}
function reset() {
  reason.value = null
  comment.value = ''
  error.value = ''
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    const key = targetKey()
    if (key !== lastTarget) reset()
    else error.value = ''
    lastTarget = key
  },
  { immediate: true },
)

function setOpen(value: boolean) {
  // Yuborilayotganda yopish taqiqlangan (VDialog ham `dismissible=false` oladi).
  if (!value && sending.value) return
  emit('update:open', value)
}

function errorText(err: unknown): string {
  // 429: soatiga 20 tadan ko'p. Envelope bo'lmasa (proksi sahifasi) status matnda qoladi.
  if (err instanceof ApiError && (err.status === 429 || /\(429\)/.test(err.message))) return t('report.tooMany')
  return t('report.error')
}

async function send() {
  if (sending.value) return
  sending.value = true
  error.value = ''
  aborter = new AbortController()
  const turnId = props.turnId ?? null
  try {
    const created = await createReport(
      {
        chatId: props.chatId,
        turnId,
        reason: reason.value,
        comment: comment.value,
        messages: props.messages,
      },
      aborter.signal,
    )
    sending.value = false
    toast.success(t('report.sent'))
    emit('sent', { id: created.id, turnId })
    // Yuborildi - keyingi ochilish toza boshlansin (hatto shu javob uchun bo'lsa ham).
    reset()
    lastTarget = null
    emit('update:open', false)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    error.value = errorText(err)
  } finally {
    sending.value = false
    aborter = null
  }
}

// Ctrl/⌘ + Enter - izoh maydonidan chiqmasdan yuborish.
function onCommentKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.isComposing) {
    e.preventDefault()
    void send()
  }
}

onBeforeUnmount(() => aborter?.abort())
</script>

<template>
  <VDialog
    :open="open"
    size="sm"
    :title="t('report.title')"
    :description="t('report.subtitle')"
    :dismissible="!sending"
    @update:open="setOpen"
  >
    <div class="report">
      <VChoiceChips v-model="reason" :options="reasonOptions" size="sm" :aria-label="t('report.reasonLabel')" />
      <VTextarea
        v-model="comment"
        class="report__comment"
        :aria-label="t('report.commentLabel')"
        :placeholder="t('report.placeholder')"
        :rows="4"
        :max-rows="8"
        :maxlength="REPORT_COMMENT_MAX"
        :counter-from="COUNTER_FROM"
        @keydown="onCommentKeyDown"
      />
      <p v-if="error" class="report__error" role="alert">
        <CircleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
        <span>{{ error }}</span>
      </p>
    </div>

    <template #footer>
      <VButton variant="ghost" :disabled="sending" @click="setOpen(false)">{{ t('report.cancel') }}</VButton>
      <VButton variant="primary" :loading="sending" @click="send">{{ t('report.send') }}</VButton>
    </template>
  </VDialog>
</template>

<style scoped>
.report {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  padding-top: var(--s-2);
}
.report__error {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.report__error svg {
  flex-shrink: 0;
  margin-top: 2px;
}
</style>
