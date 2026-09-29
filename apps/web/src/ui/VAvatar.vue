<script setup lang="ts">
import { computed, ref, watch } from 'vue'

/**
 * Foydalanuvchi belgisi: rasm bo'lsa rasm, bo'lmasa (yoki yuklanmasa) bosh harflar.
 *
 * Bosh harflar: birinchi ikki so'zning birinchi HARFI. `\p{L}` - kirill, lotin, `Oʻ`
 * hammasi to'g'ri; "(Admin) Aziz" dagi qavs yoki raqam o'tkazib yuboriladi. Bitta so'z
 * (login) bo'lsa - bitta harf.
 *
 * Standart holatda bezak (`aria-hidden`): avatar deyarli doim ism yonida turadi va
 * ekran o'quvchi ismni ikki marta o'qimasin. Yolg'iz tursa - `alt` bering.
 */
const props = withDefaults(
  defineProps<{
    name?: string | null
    src?: string | null
    size?: 24 | 28 | 32 | 40
    alt?: string
  }>(),
  { name: '', src: null, size: 32 },
)

const failed = ref(false)
watch(
  () => props.src,
  () => (failed.value = false),
)

const initials = computed(() => {
  const words = (props.name ?? '').trim().split(/\s+/u).filter(Boolean)
  const letters: string[] = []
  for (const w of words) {
    const letter = w.match(/\p{L}/u)?.[0]
    if (letter) letters.push(letter.toLocaleUpperCase())
    if (letters.length === 2) break
  }
  return letters.join('')
})

const fontSize = computed(() => ({ 24: 10, 28: 11, 32: 12, 40: 14 })[props.size])
</script>

<template>
  <span
    class="v-avatar"
    :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${fontSize}px` }"
    :role="alt ? 'img' : undefined"
    :aria-label="alt || undefined"
    :aria-hidden="alt ? undefined : 'true'"
  >
    <img v-if="src && !failed" :src="src" alt="" loading="lazy" decoding="async" @error="failed = true" />
    <template v-else>{{ initials }}</template>
  </span>
</template>

<style scoped>
.v-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.01em;
  user-select: none;
  /* Rasm oq fonda "erib ketmasin" - ichki soch tolasi. */
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--text) 6%, transparent);
}
.v-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
