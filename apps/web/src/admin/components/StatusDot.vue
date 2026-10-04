<script lang="ts">
export type StatusTone = 'good' | 'warn' | 'crit' | 'info' | 'brand' | 'neutral'

/**
 * Ma'lum holatlar -> rang ohangi va i18n kaliti. Uch oila bitta joyda:
 * savol (ok/error/running/cancelled), xizmat salomatligi (healthy/degraded/down/unknown/off),
 * xabar (new/reviewing/resolved/dismissed). `new` - brend "yangi" nuqtasi (spec §0.4).
 */
const KNOWN: Record<string, { tone: StatusTone; key: string }> = {
  ok: { tone: 'good', key: 'admin.status.ok' },
  error: { tone: 'crit', key: 'admin.status.error' },
  running: { tone: 'info', key: 'admin.status.running' },
  cancelled: { tone: 'neutral', key: 'admin.status.cancelled' },
  healthy: { tone: 'good', key: 'admin.system.healthy' },
  degraded: { tone: 'warn', key: 'admin.system.degraded' },
  down: { tone: 'crit', key: 'admin.system.down' },
  unknown: { tone: 'neutral', key: 'admin.system.unknown' },
  off: { tone: 'neutral', key: 'ui.off' },
  new: { tone: 'brand', key: 'admin.reportStatus.new' },
  reviewing: { tone: 'info', key: 'admin.reportStatus.reviewing' },
  resolved: { tone: 'good', key: 'admin.reportStatus.resolved' },
  dismissed: { tone: 'neutral', key: 'admin.reportStatus.dismissed' },
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VBadge from '../../ui/VBadge.vue'
import VTooltip from '../../ui/VTooltip.vue'

/**
 * Holat: rangli nuqta + nom. Rang HECH QACHON yolg'iz emas (spec §1.3) - nom yoki
 * ko'rinadi, yoki (`hideLabel`) tooltip va ekran o'quvchi matnida turadi.
 *
 * Props:
 * - `status`    - ma'lum qiymatlar: ok | error | running | cancelled | healthy | degraded |
 *                 down | unknown | off | new | reviewing | resolved | dismissed.
 *                 Boshqasi - neytral nuqta va qiymatning o'zi.
 * - `label`     - nomni almashtirish (masalan "Ishlamayapti: uz").
 * - `tone`      - rangni majburlash.
 * - `hideLabel` - zich jadval ustuni: faqat nuqta, nom tooltipda.
 *
 *   <StatusDot :status="turn.status" />          <StatusDot status="degraded" :label="…" />
 */
const props = defineProps<{
  status: string | null | undefined
  label?: string
  tone?: StatusTone
  hideLabel?: boolean
}>()

const { t } = useI18n({ useScope: 'global' })

const known = computed(() => (props.status ? KNOWN[props.status] : undefined))
const toneValue = computed<StatusTone>(() => props.tone ?? known.value?.tone ?? 'neutral')
const text = computed(() => props.label ?? (known.value ? t(known.value.key) : props.status || '—'))
</script>

<template>
  <VTooltip v-if="hideLabel" :text="text">
    <span class="sd sd--solo">
      <VBadge dot :tone="toneValue" size="sm"><span class="sr-only">{{ text }}</span></VBadge>
    </span>
  </VTooltip>
  <VBadge v-else class="sd" dot :tone="toneValue">{{ text }}</VBadge>
</template>

<style scoped>
.sd {
  max-width: 100%;
}
.sd--solo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
}
</style>
