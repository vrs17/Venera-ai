<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VBadge from '../../ui/VBadge.vue'

/**
 * Yo'nalish nishoni: savolga qaysi tomon javob bergani (hujjatlar, HRM, CRM, jonli
 * ma'lumot, aralash, aniqlashtirish). Hammasi neytral - yo'nalish holat emas, uni
 * rang bilan "yaxshi/yomon" deb bo'lmaydi; yo'nalishsiz (xato, bekor) savol - jim matn.
 *
 * Props:
 * - `route` - backend qiymati (`rules | hrm | crm | live | both | clarify`); null/'' -
 *             "Yo'nalishsiz". Noma'lum qiymat o'zicha ko'rsatiladi.
 * - `size`  - 'sm' | 'md' (VBadge bilan bir xil).
 *
 *   <RouteBadge :route="turn.route" size="sm" />
 */
const props = withDefaults(
  defineProps<{
    route: string | null | undefined
    size?: 'sm' | 'md'
  }>(),
  { size: 'md' },
)

const { t, te } = useI18n({ useScope: 'global' })

const label = computed(() => {
  const r = props.route || 'none'
  const key = `admin.route.${r}`
  return te(key) ? t(key) : r
})
</script>

<template>
  <span v-if="!route" class="rb-none" :class="`rb-none--${size}`">{{ label }}</span>
  <VBadge v-else tone="neutral" :size="size">{{ label }}</VBadge>
</template>

<style scoped>
.rb-none {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  white-space: nowrap;
}
.rb-none--sm {
  font-size: 11.5px;
}
</style>
