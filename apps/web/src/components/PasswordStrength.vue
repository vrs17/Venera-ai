<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Yangi parol ostidagi ingichka 4 bo'lakli chiziq + bitta izoh (spec §4.1).
 *
 * Baholash backend QOIDALARIGA bog'langan (≥8 belgi, harf va raqam, joriy paroldan
 * farqli - ChangePasswordView bilan bir xil). Qoida bajarilmaguncha chiziq qizil va
 * bitta bo'lak, izoh esa AYNAN yetishmayotgan qoidani aytadi - avvalgidek "O'rtacha"
 * deb turib, keyin rad etilmaydi. Qoidalar bajarilgach 12+ belgi va katta-kichik
 * harf / belgi "kuchli" tomonga suradi.
 *
 * Izoh `aria-live=polite`: ekran o'quvchi yozish davomida holatni eshitadi. Maydon
 * xatosi ko'rinib turganda (`quiet`) izoh yashiriladi - bir gap ikki marta chiqmasin.
 */
const props = defineProps<{
  password: string
  /** Joriy parol - "farqli bo'lsin" qoidasi uchun. */
  current?: string
  /** Izoh elementi id si - maydonning `aria-describedby` si uchun. */
  id?: string
  quiet?: boolean
}>()

const { t } = useI18n({ useScope: 'global' })

const missing = computed<string | null>(() => {
  const p = props.password
  if (p.length < 8) return t('passwordTooShort')
  if (!/[A-Za-z]/.test(p) || !/\d/.test(p)) return t('passwordNeedsLetterDigit')
  if (props.current && p === props.current) return t('mustDifferFromCurrent')
  return null
})

const bonus = computed(() => {
  const p = props.password
  let s = 0
  if (p.length >= 12) s++
  if (/[^A-Za-z0-9]/.test(p) || (/[a-z]/.test(p) && /[A-Z]/.test(p))) s++
  return s
})

const level = computed<'weak' | 'medium' | 'strong'>(() =>
  missing.value ? 'weak' : bonus.value > 0 ? 'strong' : 'medium',
)
// Qoidalar bajarilsa - kamida 2 bo'lak, har bir qo'shimcha +1.
const filled = computed(() => (missing.value ? 1 : 2 + bonus.value))
const caption = computed(
  () => missing.value ?? (level.value === 'strong' ? t('passwordStrong') : t('passwordMedium')),
)
</script>

<template>
  <div v-if="password" class="pw" :class="`pw--${level}`">
    <div class="pw__bar" aria-hidden="true">
      <span v-for="i in 4" :key="i" class="pw__seg" :class="{ 'is-on': i <= filled }" />
    </div>
    <p v-if="!quiet" :id="id" class="pw__caption" aria-live="polite">{{ caption }}</p>
  </div>
</template>

<style scoped>
.pw {
  --pw-color: var(--crit);
  display: flex;
  flex-direction: column;
  gap: var(--s-1_5);
}
.pw--medium {
  --pw-color: var(--warn);
}
.pw--strong {
  --pw-color: var(--good);
}
.pw__bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--s-1);
}
.pw__seg {
  height: 3px;
  border-radius: var(--r-full);
  background: var(--fill-hover);
  transition: background-color var(--dur-2) var(--ease-out);
}
.pw__seg.is-on {
  background: var(--pw-color);
}
.pw__caption {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.pw--medium .pw__caption {
  color: var(--warn-text);
}
.pw--strong .pw__caption {
  color: var(--good-text);
}
</style>
