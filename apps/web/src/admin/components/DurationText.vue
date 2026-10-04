<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VTooltip from '../../ui/VTooltip.vue'
import { fmtMs, fmtNumber } from '../../ui/format'

/**
 * Davomiylik: "840 ms", "1,2 s" - Inter, tabular raqamlar (ustunda tekis turadi).
 * Mono EMAS: JetBrains Mono'da o'nlik vergul va bo'shliq ham raqam kengligida, "1,8 s"
 * "1 , 8  s" bo'lib sochilib ketadi. Mono faqat identifikatorlar (so'rov ID, hujjat ID,
 * amal nomi) va JSON uchun.
 * 1 soniyadan uzun qiymat yaxlitlanadi, shuning uchun aniq millisekund tooltipda.
 *
 * Props:
 * - `ms`    - millisekund; null - "—".
 * - `muted` - ikkinchi darajali (text-3), masalan "TTFT / jami" dagi jami.
 * - `exact` - aniq qiymat tooltipi (standart: ha, faqat >= 1 s da chiqadi).
 *
 *   <DurationText :ms="turn.ttftMs" /> <DurationText :ms="turn.totalMs" muted />
 */
const props = withDefaults(
  defineProps<{
    ms: number | null | undefined
    muted?: boolean
    exact?: boolean
  }>(),
  { exact: true },
)

const { locale } = useI18n({ useScope: 'global' })

const valid = computed(() => typeof props.ms === 'number' && Number.isFinite(props.ms))
const text = computed(() => fmtMs(props.ms, locale.value))
const exactText = computed(() =>
  props.exact && valid.value && (props.ms as number) >= 1000 ? `${fmtNumber(Math.round(props.ms as number), locale.value)} ms` : '',
)
</script>

<template>
  <VTooltip v-if="exactText" :text="exactText">
    <span class="dt" :class="{ 'is-muted': muted }">{{ text }}</span>
  </VTooltip>
  <span v-else class="dt" :class="{ 'is-muted': muted, 'is-empty': !valid }">{{ text }}</span>
</template>

<style scoped>
.dt {
  font-variant-numeric: tabular-nums;
  color: var(--text);
  white-space: nowrap;
}
.dt.is-muted {
  color: var(--text-3);
}
.dt.is-empty {
  color: var(--text-4);
}
</style>
