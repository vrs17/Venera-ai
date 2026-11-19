<script setup lang="ts">
/**
 * Maxfiylik siyosati - llm.brb-tech.uz/privacy (2026-11-19). Google Play talab qiladigan OCHIQ sahifa:
 * kirishsiz ochiladi (router'da `meta` yo'q), JavaScript'dan boshqa hech narsaga bog'liq emas.
 * Matn - `features/privacy/policy.ts` (uz, ru, en); til - global UI tilidan, sahifada almashtiriladi.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import BrandSpark from '../components/BrandSpark.vue'
import { POLICY, UPDATED, policyLang, type PolicyLang } from '../features/privacy/policy'

const { locale } = useI18n({ useScope: 'global' })
const lang = ref<PolicyLang>(policyLang(locale.value))
const text = computed(() => POLICY[lang.value])
const LANGS: { id: PolicyLang; label: string }[] = [
  { id: 'uz', label: "O'zbekcha" },
  { id: 'ru', label: 'Русский' },
  { id: 'en', label: 'English' },
]

onMounted(() => {
  document.title = text.value.title
})

function pick(id: PolicyLang): void {
  lang.value = id
  document.title = POLICY[id].title
}
</script>

<template>
  <main class="privacy" :lang="lang">
    <header class="privacy__head">
      <span class="privacy__brand"><BrandSpark :size="22" /> Barno AI</span>
      <nav class="privacy__langs" aria-label="Til / Язык / Language">
        <button
          v-for="l in LANGS"
          :key="l.id"
          type="button"
          class="privacy__lang"
          :class="{ 'privacy__lang--on': l.id === lang }"
          :aria-pressed="l.id === lang"
          @click="pick(l.id)"
        >
          {{ l.label }}
        </button>
      </nav>
    </header>
    <article class="privacy__body">
      <h1>{{ text.title }}</h1>
      <p class="privacy__updated">{{ text.updatedLabel }}: {{ UPDATED }}</p>
      <p>{{ text.intro }}</p>
      <section v-for="s in text.sections" :key="s.title">
        <h2>{{ s.title }}</h2>
        <p v-for="(p, i) in s.paragraphs" :key="i">{{ p }}</p>
      </section>
    </article>
  </main>
</template>

<style scoped>
.privacy {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  padding: 24px 16px 64px;
}
.privacy__head {
  max-width: 760px;
  margin: 0 auto 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.privacy__brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 18px;
  color: var(--text);
}
.privacy__brand :deep(svg) {
  color: var(--brand);
}
.privacy__langs {
  display: flex;
  gap: 6px;
}
.privacy__lang {
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--text-2);
  border-radius: 999px;
  padding: 6px 12px;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}
.privacy__lang--on {
  border-color: var(--brand);
  color: var(--text);
}
.privacy__body {
  max-width: 760px;
  margin: 0 auto;
  line-height: 1.6;
  font-size: 16px;
}
.privacy__body h1 {
  font-size: 28px;
  line-height: 1.25;
  margin: 0 0 8px;
}
.privacy__body h2 {
  font-size: 19px;
  margin: 28px 0 8px;
}
.privacy__body p {
  margin: 0 0 12px;
  color: var(--text-2);
}
.privacy__updated {
  font-size: 14px;
  color: var(--text-3);
}
</style>
