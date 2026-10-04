<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, Send } from 'lucide-vue-next'
import { ApiError } from '../../api/http'
import { createReport, REPORT_COMMENT_MAX, REPORT_REASONS } from '../../features/report/report.api'
import type { ReportMessage, ReportReason } from '../../features/report/report.api'
import VChoiceChips from '../../ui/VChoiceChips.vue'
import type { ChoiceOption } from '../../ui/VChoiceChips.vue'
import VSheet from '../../ui/VSheet.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { toast } from '../../ui/useToast'
import { useTgSheet } from '../sheet'
import { haptic } from '../telegram'

/**
 * "Xabar berish" - web'dagi `ReportDialog` bilan AYNI oqim (sabab chiplari, ixtiyoriy
 * izoh, butun suhbat ilova qilinadi, `turnId` - aynan shu javob), lekin pastki oyna
 * sifatida: chiplar va yuborish tugmasi bosh barmoq zonasida, tugma to'liq kenglikda.
 *
 * Sabab ham, izoh ham ixtiyoriy: bosishning o'zi foydali signal. Yuborish paytida oyna
 * yopilmaydi; xatoda izoh saqlanadi; boshqa javob uchun ochilsa - tozalanadi.
 */
const props = defineProps<{ chatId: string | null; turnId: string | null; messages: ReportMessage[] }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ sent: [payload: { id: string; turnId: string | null }] }>()
const { t } = useI18n({ useScope: 'global' })

const reason = ref<ReportReason | null>(null)
const comment = ref('')
const sending = ref(false)
const error = ref('')
let aborter: AbortController | null = null

const sheet = ref<InstanceType<typeof VSheet> | null>(null)
useTgSheet(open, sheet, { close: () => close(), canClose: () => !sending.value })

const reasonOptions = computed<ChoiceOption<ReportReason>[]>(() =>
  REPORT_REASONS.map((value) => ({ value, label: t(`report.reason.${value}`) })),
)
watch(reason, (r) => r && haptic.select())

let lastTarget: string | null = null
watch(
  open,
  (on) => {
    if (!on) return
    const key = `${props.chatId ?? ''}|${props.turnId ?? ''}`
    if (key !== lastTarget) {
      reason.value = null
      comment.value = ''
    }
    error.value = ''
    lastTarget = key
  },
  { immediate: true },
)

function close() {
  if (sending.value) return
  open.value = false
}

async function send() {
  if (sending.value) return
  sending.value = true
  error.value = ''
  aborter = new AbortController()
  const turnId = props.turnId
  try {
    const created = await createReport(
      { chatId: props.chatId, turnId, reason: reason.value, comment: comment.value, messages: props.messages },
      aborter.signal,
    )
    haptic.notify('success')
    toast.success(t('report.sent'))
    emit('sent', { id: created.id, turnId })
    reason.value = null
    comment.value = ''
    lastTarget = null
    sending.value = false
    open.value = false
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    haptic.notify('error')
    error.value = err instanceof ApiError && (err.status === 429 || /\(429\)/.test(err.message)) ? t('report.tooMany') : t('report.error')
  } finally {
    sending.value = false
    aborter = null
  }
}

onBeforeUnmount(() => aborter?.abort())
</script>

<template>
  <VSheet
    ref="sheet"
    v-model:open="open"
    class="tg-sheet"
    side="bottom"
    :title="turnId ? t('report.reportAnswer') : t('report.title')"
    :description="t('report.subtitle')"
    :dismissible="!sending"
  >
    <div class="rep">
      <VChoiceChips v-model="reason" class="rep__chips" :options="reasonOptions" :aria-label="t('report.reasonLabel')" />
      <VTextarea
        v-model="comment"
        :aria-label="t('report.commentLabel')"
        :placeholder="t('report.placeholder')"
        :rows="3"
        :max-rows="6"
        :maxlength="REPORT_COMMENT_MAX"
        :counter-from="1800"
        enterkeyhint="enter"
      />
      <p v-if="error" class="rep__error" role="alert">
        <CircleAlert :size="16" :stroke-width="2" aria-hidden="true" />
        <span>{{ error }}</span>
      </p>
      <button type="button" class="rep__send" :aria-busy="sending ? 'true' : undefined" :disabled="sending" @click="send">
        <span v-if="sending" class="rep__spinner" aria-hidden="true" />
        <Send v-else :size="18" :stroke-width="2" aria-hidden="true" />
        {{ t('report.send') }}
      </button>
    </div>
  </VSheet>
</template>

<style scoped>
.rep {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  padding-top: var(--s-1);
}
/* Chiplar 44px - barmoq uchun; tor ekranda keyingi qatorga o'tadi. */
.rep__chips :deep(button) {
  min-height: 44px;
  padding: 0 var(--s-4);
  font-size: var(--fs-body-sm);
}
.rep__error {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.rep__error svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.rep__send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  min-height: 52px;
  border-radius: 14px;
  background: var(--ink);
  color: var(--on-ink);
  font-size: var(--fs-body);
  font-weight: 600;
  transition: transform var(--dur-1) var(--ease-out);
}
.rep__send:active:not(:disabled) {
  transform: scale(0.98);
}
.rep__send:disabled {
  opacity: 0.8;
}
.rep__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid color-mix(in srgb, var(--on-ink) 35%, transparent);
  border-top-color: var(--on-ink);
  border-radius: var(--r-full);
  animation: rep-spin 0.8s linear infinite;
}
@keyframes rep-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
