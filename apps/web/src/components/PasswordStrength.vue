<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ password: string }>()
const { t } = useI18n({ useScope: 'global' })

// 0–4 score from length + character variety.
const score = computed(() => {
  const p = props.password
  if (!p) return 0
  let s = 0
  if (p.length >= 8) s++
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) s++
  if (/\d/.test(p)) s++
  if (/[^A-Za-z0-9]/.test(p)) s++
  return s
})

const pct = computed(() => `${(score.value / 4) * 100}%`)
const label = computed(() => (score.value <= 1 ? t('passwordWeak') : score.value <= 3 ? t('passwordMedium') : t('passwordStrong')))
const labelColor = computed(() => (score.value <= 1 ? 'var(--bad-fg)' : score.value <= 3 ? 'var(--warn-fg)' : 'var(--ok-fg)'))
</script>

<template>
  <div v-if="password" class="pw">
    <div class="pw__track">
      <div class="pw__bar" :style="{ width: pct }" />
    </div>
    <span class="pw__label" :style="{ color: labelColor }">{{ label }}</span>
  </div>
</template>

<style scoped>
.pw {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.pw__track {
  flex: 1;
  height: 4px;
  border-radius: 999px;
  background: var(--surface-hover);
  overflow: hidden;
}
.pw__bar {
  height: 100%;
  border-radius: 999px;
  background: var(--ink);
  transition: width 0.3s var(--spring);
}
.pw__label {
  font-size: 11.5px;
  font-weight: 600;
  flex-shrink: 0;
}
</style>
