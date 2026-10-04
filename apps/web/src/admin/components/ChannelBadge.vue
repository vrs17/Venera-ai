<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VTooltip from '../../ui/VTooltip.vue'
import { channelColor, channelIcon } from './channel'

/**
 * Kanal: belgi + nom, belgining burchagida kanalning DOIMIY rang nuqtasi (grafiklardagi
 * rang bilan bir xil - `--ch-*`). Rang yolg'iz kelmaydi: yonida belgi va nom bor.
 *
 * Props:
 * - `channel`  - web | miniapp | bot | desktop | api | system; null/'' - "—".
 * - `iconOnly` - faqat belgi (jadvalda "ishlatilgan kanallar" qatori); nom tooltip va
 *                ekran o'quvchi matnida qoladi.
 * - `size`     - 'sm' (12px matn, 14px belgi) | 'md' (14px matn, 16px belgi, standart).
 *
 *   <ChannelBadge :channel="turn.channel" />
 *   <ChannelBadge v-for="c in user.channels" :key="c" :channel="c" icon-only />
 */
const props = withDefaults(
  defineProps<{
    channel: string | null | undefined
    iconOnly?: boolean
    size?: 'sm' | 'md'
  }>(),
  { size: 'md' },
)

const { t, te } = useI18n({ useScope: 'global' })

const label = computed(() => {
  const c = props.channel
  if (!c) return ''
  const key = `admin.channel.${c}`
  return te(key) ? t(key) : c
})
const icon = computed(() => channelIcon(props.channel))
const color = computed(() => `var(${channelColor(props.channel)})`)
const iconSize = computed(() => (props.size === 'sm' ? 14 : 16))
</script>

<template>
  <span v-if="!channel" class="chb chb--none" :class="`chb--${size}`">—</span>
  <VTooltip v-else-if="iconOnly" :text="label">
    <span class="chb chb--icon" :class="`chb--${size}`">
      <span class="chb__mark" :style="{ '--c': color }" aria-hidden="true">
        <component :is="icon" :size="iconSize" :stroke-width="1.75" />
        <span class="chb__dot" />
      </span>
      <span class="sr-only">{{ label }}</span>
    </span>
  </VTooltip>
  <span v-else class="chb" :class="`chb--${size}`">
    <span class="chb__mark" :style="{ '--c': color }" aria-hidden="true">
      <component :is="icon" :size="iconSize" :stroke-width="1.75" />
      <span class="chb__dot" />
    </span>
    <span class="chb__label">{{ label }}</span>
  </span>
</template>

<style scoped>
.chb {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  max-width: 100%;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  white-space: nowrap;
  vertical-align: middle;
}
.chb--sm {
  gap: var(--s-1_5);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.chb--none {
  color: var(--text-4);
}
.chb--icon {
  gap: 0;
}

.chb__mark {
  position: relative;
  display: inline-flex;
  flex: none;
  color: var(--text-3);
}
/* Rang nuqtasi belgi burchagida, sirt rangidagi halqa bilan - belgini "yemaydi". */
.chb__dot {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 7px;
  height: 7px;
  border-radius: var(--r-full);
  background: var(--c);
  box-shadow: 0 0 0 1.5px var(--surface);
}
.chb--sm .chb__dot {
  width: 6px;
  height: 6px;
}

.chb__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
