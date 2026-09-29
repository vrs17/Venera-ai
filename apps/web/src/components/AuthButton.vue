<script setup lang="ts">
import VButton from '../ui/VButton.vue'

/**
 * Kirish shakllarining asosiy tugmasi: siyoh rangli, to'liq yumaloq, 44px (spec §3).
 * Faqat `busy` paytida bloklanadi - noto'g'ri to'ldirilgan shaklni ham yuborish
 * mumkin, xatolar aynan shu bosishda ko'rinadi. Yuklanishda spinner chiqadi, kenglik
 * sakramaydi, fokus yo'qolmaydi (VButton `aria-disabled` + `aria-busy` qo'yadi).
 */
defineProps<{
  label: string
  /** @deprecated Eski "glint" effekti uchun edi - endi e'tiborsiz. */
  valid?: boolean
  busy?: boolean
}>()
</script>

<template>
  <VButton type="submit" variant="primary" size="lg" block pill :loading="busy">{{ label }}</VButton>
</template>
