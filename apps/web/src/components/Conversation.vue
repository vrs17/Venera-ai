<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowDown } from 'lucide-vue-next'
import { LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { formatFull, formatWhen } from '../time'
import VIconButton from '../ui/VIconButton.vue'
import VTooltip from '../ui/VTooltip.vue'
import type { ChatExchange } from './chat/types'
import PipelineResult from './PipelineResult.vue'
import CopyButton from './CopyButton.vue'

/**
 * Suhbat ustuni: savol - o'ngda yumshoq pufak, javob - pufaksiz, ustun kengligida.
 *
 * AYLANTIRISH. Pastda turgan odam uchun yangi matn o'zi ko'rinadi (javob yozilayotganda
 * ham). Yuqoriga chiqib o'qiyotgan odamni har token'da pastga "tortib ketmaymiz" - buning
 * o'rniga "Oxiriga o'tish" tugmasi chiqadi. Eski suhbat ochilganda - darhol oxiriga,
 * butun tarix bo'ylab silliq aylanmasdan.
 */
const props = withDefaults(
  defineProps<{
    exchanges: ChatExchange[]
    /** Odam versiyani tanlay oladi - javoblarda qaysi versiya javob bergani ko'rinsin. */
    showEngine?: boolean
    busy?: boolean
    /** Hozir yozilayotgan javob. */
    streamingId?: string | null
    /** Xabar berilgan javoblar: `turnId`, u bo'lmasa `ex:<id>`. */
    reportedKeys?: ReadonlySet<string>
    canTrace?: boolean
    /** Suhbat kaliti - almashsa, keyingi chizishda darhol oxiriga. */
    chatKey?: string
  }>(),
  { showEngine: false, busy: false, streamingId: null, reportedKeys: () => new Set<string>(), canTrace: false, chatKey: '' },
)
const emit = defineEmits<{ regenerate: [id: string]; report: [id: string]; scrolled: [away: boolean] }>()
const { t, locale } = useI18n({ useScope: 'global' })

// Vaqt yozuvi UI tilida: `Intl` ga BCP-47 kodi kerak (`uz-Latn`), i18n kodi emas.
const lang = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale))?.htmlLang ?? 'uz-Latn')
function iso(ms: number): string {
  return new Date(ms).toISOString()
}
function reportKey(ex: ChatExchange): string {
  return ex.turnId ?? `ex:${ex.id}`
}

const scroller = ref<HTMLElement | null>(null)
const column = ref<HTMLElement | null>(null)
/** Pastdan shuncha px ichida bo'lsa - "pastda" hisoblanadi va kuzatib boriladi. */
const STICK = 80
const atBottom = ref(true)
let follow = true
let jumpNext = true

function distance(el: HTMLElement): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight
}
function toBottom(behavior: ScrollBehavior = 'auto') {
  const el = scroller.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior })
}
function onScroll() {
  const el = scroller.value
  if (!el) return
  atBottom.value = distance(el) < STICK
  follow = atBottom.value
  emit('scrolled', el.scrollTop > 2)
}

watch(
  () => props.chatKey,
  () => {
    jumpNext = true
  },
)
watch(
  () => props.exchanges,
  async (list, prev) => {
    await nextTick()
    if (jumpNext || !prev?.length) {
      jumpNext = false
      follow = true
      toBottom()
      return
    }
    // Odam yangi savol yubordi - uni ko'rsin (qayerda turganidan qat'i nazar).
    if (list.length > prev.length) {
      follow = true
      toBottom('smooth')
      return
    }
    if (follow) toBottom()
  },
)

// Javob matni kadrga bir marta chiziladi, manbalar ochiladi... - balandlik o'zgarsa,
// pastda turgan odam uchun pastda qolamiz.
let ro: ResizeObserver | null = null
onMounted(() => {
  // Tarixdan ochilgan suhbat ma'lumot bilan birga chiziladi - darhol oxiriga.
  toBottom()
  jumpNext = false
  if (typeof ResizeObserver === 'undefined' || !column.value) return
  ro = new ResizeObserver(() => {
    if (follow) toBottom()
    else if (scroller.value) atBottom.value = distance(scroller.value) < STICK
  })
  ro.observe(column.value)
})
onBeforeUnmount(() => ro?.disconnect())

function jumpToLatest() {
  follow = true
  toBottom('smooth')
}

/* ---- ekran o'quvchi: javob tugaganda bitta qisqa xabar ---- */
const announce = ref('')
watch(
  () => props.streamingId,
  (now, before) => {
    if (!before || now === before) return
    const ex = props.exchanges.find((e) => e.id === before)
    if (!ex?.response || ex.error) return
    announce.value = ''
    void nextTick(() => (announce.value = t('chat.answerReady')))
  },
)
</script>

<template>
  <div class="conv">
    <div ref="scroller" class="conv__scroll" @scroll.passive="onScroll">
      <section ref="column" class="conv__col" :aria-label="t('chat.thread')">
        <article v-for="(ex, i) in exchanges" :key="ex.id" class="turn">
          <!-- Tarixdan kelgan javob savolsiz bo'lishi mumkin (eski yozuv) - bo'sh
               pufak ko'rsatilmaydi. -->
          <div v-if="ex.question" class="turn__user">
            <div class="turn__bubble">{{ ex.question }}</div>
            <div class="turn__tools">
              <VTooltip v-if="ex.askedAt" :text="formatFull(ex.askedAt, lang)">
                <time class="turn__time" :datetime="iso(ex.askedAt)">{{ formatWhen(ex.askedAt, lang) }}</time>
              </VTooltip>
              <CopyButton :text="ex.question" :aria-label="t('copyPrompt')" />
            </div>
          </div>
          <PipelineResult
            :exchange="ex"
            :show-engine="showEngine"
            :busy="busy"
            :streaming="ex.id === streamingId"
            :latest="i === exchanges.length - 1"
            :reported="reportedKeys.has(reportKey(ex))"
            :can-trace="canTrace"
            @regenerate="emit('regenerate', ex.id)"
            @report="emit('report', ex.id)"
          />
        </article>
      </section>
    </div>

    <Transition name="conv-jump">
      <VIconButton
        v-if="!atBottom"
        class="conv__jump"
        variant="outline"
        :icon="ArrowDown"
        :label="t('chat.jumpToLatest')"
        @click="jumpToLatest"
      />
    </Transition>

    <p class="sr-only" role="status">{{ announce }}</p>
  </div>
</template>

<style scoped>
.conv {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.conv__scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.conv__col {
  max-width: calc(var(--chat-col) + 2 * var(--gutter));
  margin: 0 auto;
  padding: var(--s-6) var(--gutter) var(--s-8);
}

.turn + .turn {
  margin-top: var(--s-8);
}
.turn__user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  margin-bottom: var(--s-2);
}
.turn__bubble {
  max-width: min(85%, 560px);
  padding: 10px var(--s-4);
  border-radius: 20px 20px 6px 20px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.turn__tools {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  margin-top: var(--s-1);
  margin-right: calc(var(--s-1) * -1);
}
.turn__time {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  cursor: default;
}
/* Sichqonchali qurilmada vaqt va nusxa - faqat pufak ustida; sensorli ekranda doim. */
@media (hover: hover) {
  .turn__tools {
    opacity: 0;
    transition: opacity var(--dur-2) var(--ease-out);
  }
  .turn__user:hover .turn__tools,
  .turn__user:focus-within .turn__tools {
    opacity: 1;
  }
}

.conv__jump {
  position: absolute;
  left: 50%;
  bottom: var(--s-3);
  z-index: var(--z-sticky);
  translate: -50% 0;
  border-radius: var(--r-full);
  background: var(--surface);
  box-shadow: var(--e2);
}
.conv-jump-enter-active,
.conv-jump-leave-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}
.conv-jump-enter-from,
.conv-jump-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
