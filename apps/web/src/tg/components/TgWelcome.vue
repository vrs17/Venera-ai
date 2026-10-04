<script lang="ts">
// Kirish animatsiyasi SESSIYADA BIR MARTA: har "Yangi suhbat" da qayta o'ynasa, u
// bezak emas, kutish bo'lib qoladi.
let entrancePlayed = false
</script>

<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarDays, ChevronRight, Clock3, History, ListChecks, Scale } from 'lucide-vue-next'
import BrandSpark from '../../components/BrandSpark.vue'
import { formatWhen } from '../../time'
import { SUGGESTIONS } from '../i18n'
import type { SuggestionKey } from '../i18n'

/**
 * Yangi suhbat: salomlashuv va 2x2 taklif kartalari - BOSH BARMOQ ZONASIDA, ya'ni
 * ekranning pastida, kompozerning ustida. Telefonni bir qo'lda ushlagan odam ekran
 * tepasiga yetmaydi; kartalar yuqorida tursa, ularni bosish uchun ikkinchi qo'l kerak.
 *
 * KARTALAR GORIZONTAL (belgi chapda, matn o'ngda, 64px): 320px ekranda ham (iPhone SE,
 * "Display Zoom", Android "katta shrift") ikki ustun sig'adi va to'rt karta bosh barmoq
 * zonasidan chiqib ketmaydi. Matn kattalashtirilsa (200%) - o'zi bir ustunga o'tadi,
 * karta bo'yi matn bilan o'sadi (bo'sh "teshik" yo'q).
 *
 * "DAVOM ETTIRISH" - kartalar ustida bitta jim qator: oxirgi suhbat nomi va vaqti.
 * Tarixni ochishning eng ko'p sababi - kechagi suhbatni davom ettirish; endi u ekran
 * pastida, bir bosishda (yuqori chap burchakka cho'zilmasdan).
 *
 * Salomlashuv kun vaqtiga qarab ("Xayrli tong"), qo'shimcha element qo'shmasdan.
 * Kartada QISQA nom (2-3 so'z) va tizim belgisi; yuboriladigan savol to'liqroq
 * (`tg.suggest.*.q`) - odam nima so'ralganini ekranda ko'radi.
 *
 * `dim` - ovoz yozilmoqda: kartalar xiralashadi va bosilmaydi (tasodifiy tegish
 * yozuv o'rtasida savol yubormasin).
 */
const props = defineProps<{
  name: string
  dim?: boolean
  resume?: { id: string; title: string; at: number | null } | null
}>()
const emit = defineEmits<{ pick: [question: string]; resume: [id: string] }>()
const { t, locale } = useI18n({ useScope: 'global' })

const animate = !entrancePlayed
entrancePlayed = true

const ICONS: Record<SuggestionKey, Component> = {
  leave: CalendarDays,
  late: Clock3,
  tasks: ListChecks,
  probation: Scale,
}

function partOfDay(hour: number): 'morning' | 'day' | 'evening' {
  if (hour >= 5 && hour < 11) return 'morning'
  if (hour >= 11 && hour < 17) return 'day'
  return 'evening'
}
const hello = computed(() => {
  const part = partOfDay(new Date().getHours())
  return props.name ? t(`tg.welcome.${part}`, { name: props.name }) : t(`tg.welcome.${part}Anon`)
})

const resumeWhen = computed(() => {
  const at = props.resume?.at
  if (!at) return ''
  return formatWhen(at, document.documentElement.lang || String(locale.value))
})

function pick(key: SuggestionKey) {
  emit('pick', t(`tg.suggest.${key}.q`))
}
</script>

<template>
  <section class="welcome" :class="{ 'is-anim': animate, 'is-dim': dim }" :aria-disabled="dim ? 'true' : undefined">
    <div class="welcome__hero">
      <span class="welcome__spark" aria-hidden="true"><BrandSpark :size="22" /></span>
      <h2 class="welcome__hello">{{ hello }}</h2>
      <p class="welcome__lead">{{ t('tg.welcome.lead') }}</p>
    </div>

    <button
      v-if="resume"
      type="button"
      class="resume"
      :aria-label="t('tg.welcome.resume', { title: resume.title })"
      @click="emit('resume', resume.id)"
    >
      <History class="resume__icon" :size="16" :stroke-width="1.75" aria-hidden="true" />
      <span class="resume__title">{{ resume.title }}</span>
      <span v-if="resumeWhen" class="resume__when">{{ resumeWhen }}</span>
      <ChevronRight class="resume__chev" :size="16" :stroke-width="2" aria-hidden="true" />
    </button>

    <ul class="welcome__grid">
      <li v-for="(key, i) in SUGGESTIONS" :key="key" :style="{ '--i': i }">
        <button type="button" class="card" @click="pick(key)">
          <span class="card__icon" aria-hidden="true"><component :is="ICONS[key]" :size="16" :stroke-width="1.75" /></span>
          <span class="card__text">
            <span class="card__label">{{ t(`tg.suggest.${key}.label`) }}</span>
            <span class="card__hint">{{ t(`tg.suggest.${key}.hint`) }}</span>
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.welcome {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
  margin-top: auto;
  padding: var(--s-6) 0 var(--s-2);
  transition: opacity var(--dur-2) var(--ease-out);
}
.welcome.is-dim {
  opacity: 0.4;
  pointer-events: none;
}
.welcome__hero {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 0 var(--s-1);
}
.welcome__spark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin-bottom: var(--s-3);
  border-radius: 14px;
  background: var(--brand-soft);
  color: var(--brand);
}
.welcome__hello {
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.022em;
  text-wrap: balance;
}
.welcome__lead {
  margin-top: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-body-lg);
  line-height: var(--lh-body);
}

/* Davom ettirish - jim qator: chegara, fon yo'q; bosilganda to'ladi. */
.resume {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-height: var(--tap);
  margin-bottom: calc(var(--s-5) * -1 + var(--s-2));
  padding: var(--s-1) var(--s-2) var(--s-1) var(--s-3);
  border: 1px solid var(--line);
  border-radius: 14px;
  color: var(--text-2);
  text-align: left;
  transition:
    background-color var(--dur-1) var(--ease-out),
    transform var(--dur-1) var(--ease-out);
}
.resume:active {
  background: var(--fill);
  transform: scale(0.98);
}
.resume__icon,
.resume__chev {
  flex-shrink: 0;
  color: var(--text-3);
}
.resume__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  color: var(--text);
}
.resume__when {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}

/* 2 ustun 280px kontentgacha (2 x 132 + 8); 200% matnda - bir ustun. */
.welcome__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 8.25rem), 1fr));
  gap: var(--s-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.welcome__grid li {
  display: flex;
  container-type: inline-size;
}
.card {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 64px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--bg-subtle);
  text-align: left;
  transition:
    transform var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out);
}
.card:active {
  transform: scale(0.97);
  background: var(--fill);
}
.card__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 9px;
  background: var(--surface);
  color: var(--text-2);
  box-shadow: var(--e1);
}
.card__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.card__label {
  /* So'z o'rtasidan faqat sig'masa bo'linadi; bo'linsa - tizim lug'ati bilan
     defis qo'yib (iOS/Android `lang` bo'yicha), "kechikdim|mi" emas. */
  overflow-wrap: break-word;
  -webkit-hyphens: auto;
  hyphens: auto;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
  color: var(--text);
}
.card__hint {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
/* Qorong'i mavzuda --bg-subtle fonga deyarli qo'shilib ketadi - karta ko'tarilgan
   sirt rangida. */
html[data-theme='dark'] .card {
  background: var(--surface);
}

/* Karta tor bo'lsa (320px ekran, "Display Zoom", 130% shrift) belgi joyini matnga
   beradi: ikki ustun saqlanadi va "kechikdimmi?" so'zi bo'linmaydi (belgi - bezak,
   tizim nomi ostida yozilgan). Chegara rem'da - shrift kattalashsa u ham o'sadi.
   Container query'siz eski WebView uchun - ekran kengligi bo'yicha zaxira. */
@container (max-width: calc(6rem + 60px)) {
  .card__icon {
    display: none;
  }
}
@media (max-width: 359.98px) {
  .card__icon {
    display: none;
  }
  .card {
    padding: 10px 12px;
  }
}

/* Past ekran (klaviatura, kichik telefon): belgi yashirinadi, salom kichrayadi -
   kartalar bosh barmoq zonasida qoladi. */
@media (max-height: 640px) {
  .welcome__spark {
    display: none;
  }
  .welcome__hello {
    font-size: 1.375rem;
    line-height: 1.75rem;
  }
  .welcome {
    padding-top: var(--s-3);
  }
}

/* Kirish: 280 ms, 30 ms qadam, 6px - va faqat sessiyadagi birinchi ochilishda. */
.is-anim .welcome__spark,
.is-anim .welcome__hello,
.is-anim .welcome__lead,
.is-anim .resume,
.is-anim .welcome__grid li {
  animation: welcome-in var(--dur-3) var(--ease-sheet) backwards;
}
.is-anim .welcome__hello {
  animation-delay: 30ms;
}
.is-anim .welcome__lead {
  animation-delay: 60ms;
}
.is-anim .resume {
  animation-delay: 90ms;
}
.is-anim .welcome__grid li {
  animation-delay: calc(90ms + var(--i) * 30ms);
}
@keyframes welcome-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .is-anim .welcome__spark,
  .is-anim .welcome__hello,
  .is-anim .welcome__lead,
  .is-anim .resume,
  .is-anim .welcome__grid li {
    animation: none;
  }
}
</style>
