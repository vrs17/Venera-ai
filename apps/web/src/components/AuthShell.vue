<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Moon, Sun } from 'lucide-vue-next'
import { useTheme } from '../theme'
import VIconButton from '../ui/VIconButton.vue'
import BrandSpark from './BrandSpark.vue'
import LanguageSwitcher from './LanguageSwitcher.vue'

/**
 * Kirish, parol va xush kelibsiz sahifalarining umumiy qobig'i (spec §4.1): yuqorida
 * jim panel (chapda logotip, o'ngda til va mavzu), o'rtada bitta ustun. Karta, soya,
 * bezak yo'q - sahifa foni va bo'sh joy.
 *
 * Ustun ekranning 42% balandligida turadi (aniq o'rtadan biroz yuqori - ko'z tabiiy
 * shu yerga tushadi). Kontent sig'masa sahifa oddiy aylanadi, tepa kesilmaydi.
 *
 * Ildiz elementda kirish animatsiyasi YO'Q: App.vue dagi sahifalar almashinuvi o'zi
 * so'ndiradi, forwards-to'ldirilgan animatsiya esa uni buzardi.
 */
withDefaults(
  defineProps<{
    /** form - 360px (kirish shakllari); wide - 560px (xush kelibsiz). */
    width?: 'form' | 'wide'
    /** Chapdagi logotip. Xush kelibsiz sahifasi o'zi katta nom ko'rsatadi - takrorlamaydi. */
    brand?: boolean
    /** Sahifa sarlavhasi (h1) va uning ostidagi bitta izoh qatori. */
    title?: string
    caption?: string
  }>(),
  { width: 'form', brand: true },
)

defineSlots<{
  default?(): unknown
  footer?(): unknown
}>()

const { t } = useI18n({ useScope: 'global' })
const { theme, toggle } = useTheme()
const isDark = computed(() => theme.value === 'dark')
</script>

<template>
  <div class="shell">
    <header class="shell__bar">
      <div v-if="brand" class="shell__brand">
        <span class="shell__spark"><BrandSpark :size="16" /></span>
        <span>Venera</span>
      </div>
      <span v-else aria-hidden="true" />
      <div class="shell__tools">
        <LanguageSwitcher />
        <VIconButton
          :icon="isDark ? Sun : Moon"
          :label="isDark ? t('themeToLight') : t('themeToDark')"
          tooltip-placement="bottom"
          @click="toggle"
        />
      </div>
    </header>

    <main class="shell__main">
      <div class="shell__col" :class="`shell__col--${width}`">
        <header v-if="title" class="shell__head">
          <h1 class="shell__title">{{ title }}</h1>
          <p v-if="caption" class="shell__caption">{{ caption }}</p>
        </header>
        <slot />
      </div>
    </main>

    <footer v-if="$slots.footer" class="shell__foot">
      <slot name="footer" />
    </footer>
  </div>
</template>

<style scoped>
.shell {
  --shell-pad-l: max(var(--gutter), env(safe-area-inset-left));
  --shell-pad-r: max(var(--gutter), env(safe-area-inset-right));
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--bg);
  color: var(--text);
}

.shell__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  height: calc(64px + env(safe-area-inset-top));
  padding: env(safe-area-inset-top) calc(var(--shell-pad-r) - var(--s-2)) 0 var(--shell-pad-l);
}
.shell__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  font-size: 15px;
  line-height: 20px;
  font-weight: 600;
  letter-spacing: -0.011em;
  color: var(--text);
}
.shell__spark {
  display: inline-flex;
  color: var(--brand);
}
.shell__tools {
  display: flex;
  align-items: center;
  gap: var(--s-1);
}

/* Pastki padding tepadagidan 16dvh ko'p: bo'sh joy markazi 8dvh yuqoriga siljiydi,
   ustun ~42% balandlikda turadi. Klaviatura ochilganda (dvh qisqaradi) farq ham
   o'zi kichrayadi. */
.shell__main {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: var(--s-8) var(--shell-pad-r) calc(var(--s-8) + 16vh) var(--shell-pad-l);
  padding-bottom: calc(var(--s-8) + 16dvh);
}
.shell__col {
  width: 100%;
  min-width: 0;
}
.shell__col--form {
  max-width: 360px;
}
.shell__col--wide {
  max-width: 560px;
}
.shell__head {
  margin-bottom: var(--s-8);
}
.shell__title {
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.022em;
  color: var(--text);
  text-wrap: balance;
}
.shell__caption {
  margin-top: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}

.shell__foot {
  display: flex;
  justify-content: center;
  padding: var(--s-6) var(--shell-pad-r) max(var(--s-8), env(safe-area-inset-bottom)) var(--shell-pad-l);
}

@media (max-width: 767.98px) {
  .shell__main {
    padding-top: var(--s-4);
    padding-bottom: calc(var(--s-8) + 8dvh);
  }
}
</style>
