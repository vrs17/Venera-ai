<script setup lang="ts">
import VLineChart from './VLineChart.vue'
import type { ChartView, XYChartProps } from './scale'

/**
 * Maydon grafigi (1-4 qator, `stacked` bilan ustma-ust - masalan kanallar bo'yicha
 * faollik). Barcha mantiq VLineChart da: bu yerda faqat 10% yuvilgan maydon yoqiladi,
 * shunda ikkala grafik kursor, tooltip va klaviatura bo'yicha aynan bir xil ishlaydi.
 */
// Boolean proplar yo'q bo'lsa Vue ularni `false` qiladi - `true` standartlarini shu
// yerda ham takrorlaymiz, aks holda v-bind ularni VLineChart da o'chirib yuboradi.
const props = withDefaults(defineProps<XYChartProps & { stacked?: boolean }>(), {
  endLabels: true,
  tableToggle: true,
})
const view = defineModel<ChartView>('view', { default: 'chart' })
</script>

<template>
  <VLineChart v-bind="props" v-model:view="view" area />
</template>
