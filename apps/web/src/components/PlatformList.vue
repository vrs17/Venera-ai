<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw } from 'lucide-vue-next'
import type { Platform } from '../api/assistant.api'
import { useConnectors } from '../composables/useConnectors'
import type { usePlatforms } from '../composables/usePlatforms'
import VButton from '../ui/VButton.vue'
import VSkeleton from '../ui/VSkeleton.vue'
import VSwitch from '../ui/VSwitch.vue'
import { toast } from '../ui/useToast'
import { loginIssue, platformIcon, platformName, platformPurpose } from './chat/platforms'
import type { LoginIssue } from './chat/platforms'

/**
 * "Manbalar" - Barno javob berishda foydalanadigan platformalar (HRM, CRM, DWH, Biznes 24/7,
 * Superapp, qo'llanmalar, Biznes Help) va har birining kaliti. Ulanishlar oynasida, HRM/CRM
 * hisoblari ostida.
 *
 * Qator: belgi, nom, BIR qator vazifa ("Davomat, ta'til, ...") va kalit. Server o'chirgan
 * platforma (`available: false`) - kulrang, kalit bosilmaydi, "Hozircha mavjud emas".
 * Login kerak bo'lgan platforma (HRM/CRM) yoqiq, lekin hisob ulanmagan bo'lsa - ogohlantirish:
 * kalit yoqiq turib ham Barno undan foydalana olmaydi.
 *
 * BITTA KALIT (2026-10-10, UX ko'rigi): HRM/CRM uchun avval ikkita kalit bor edi - bu
 * yerdagisi (yordamchida) va hisob ko'rinishidagi "Chatda ishlatish" (bizda, token). Endi
 * platforma kaliti asosiy: uni YOQISH token kalitini ham yoqadi; token kaliti o'chiq qolgan
 * bo'lsa (eski holat) - "Chatda ishlatish o'chiq" ogohlantirishi va "Yoqish" tugmasi.
 * Hisob ko'rinishidagi eski kalit platformalar ko'ringanda yashiriladi (ConnectorDialog).
 *
 * Holat ota komponentda (`usePlatforms`): oyna ko'rinishlari almashganda (ro'yxat -> kirish
 * shakli -> ro'yxat) ro'yxat qayta yuklanib "sakramasin".
 */
const props = defineProps<{ store: ReturnType<typeof usePlatforms> }>()
const { t } = useI18n({ useScope: 'global' })
const { connectors, loaded: connectorsLoaded, toggle: toggleConnector } = useConnectors()

const platforms = computed(() => props.store.platforms.value)
const status = computed(() => props.store.status.value)

const nameOf = (p: Platform) => platformName(p.id, t, p.name)
const purposeOf = (p: Platform) => platformPurpose(p.id, t, p.description)
const connectorOf = (p: Platform) => connectors.find((x) => x.id === p.id)

/** Yoqiq, lekin Barno hisobdan foydalana olmaydi (ulanmagan yoki "Chatda ishlatish" o'chiq). */
function issueOf(p: Platform): LoginIssue {
  return connectorsLoaded.value ? loginIssue(p, connectorOf(p)) : null
}

/** Token kalitini yoqadi (hisob ulangan, lekin chatda o'chiq bo'lsa). */
const enabling = ref<string | null>(null)
async function enableForChat(p: Platform) {
  const c = connectorOf(p)
  if (!c || c.state !== 'connected' || c.enabled || enabling.value) return
  enabling.value = p.id
  try {
    if (!(await toggleConnector(c.id))) toast.error(t('assistant.platforms.toggleFailed', { name: nameOf(p) }))
  } finally {
    enabling.value = null
  }
}

async function onToggle(p: Platform) {
  if (props.store.pending.has(p.id)) return
  const turningOn = !p.user_enabled
  if (!(await props.store.toggle(p.id))) {
    toast.error(t('assistant.platforms.toggleFailed', { name: nameOf(p) }))
    return
  }
  // Bitta kalit: platformani yoqqan odam Barno undan foydalanishini kutadi - token kaliti
  // ham yoqiladi (o'chirish esa tokenga tegmaydi: platforma kaliti o'zi yetarli).
  if (turningOn) await enableForChat(p)
}
</script>

<template>
  <section class="plist" :aria-labelledby="'plist-title'">
    <div class="plist__head">
      <h3 id="plist-title" class="plist__title">{{ t('assistant.platforms.title') }}</h3>
      <p class="plist__lead">{{ t('assistant.platforms.lead') }}</p>
    </div>

    <ul v-if="status === 'loading'" class="plist__rows" aria-hidden="true">
      <li v-for="n in 4" :key="n" class="plist__row">
        <VSkeleton :width="40" :height="40" radius="full" />
        <span class="plist__text">
          <VSkeleton :width="96" :height="12" />
          <VSkeleton :width="180" :height="10" />
        </span>
        <VSkeleton :width="36" :height="20" radius="full" />
      </li>
    </ul>

    <div v-else-if="status === 'error'" class="plist__error" role="status">
      <span>{{ t('assistant.platforms.loadFailed') }}</span>
      <VButton size="sm" variant="ghost" :icon="RefreshCw" @click="store.load()">{{ t('assistant.platforms.retry') }}</VButton>
    </div>

    <p v-else-if="!platforms.length" class="plist__empty">{{ t('assistant.platforms.empty') }}</p>

    <ul v-else class="plist__rows">
      <li
        v-for="p in platforms"
        :key="p.id"
        class="plist__row"
        :class="{ 'is-unavailable': !p.available }"
        :data-platform="p.id"
      >
        <span class="plist__glyph" aria-hidden="true">
          <component :is="platformIcon(p.id)" :size="18" :stroke-width="1.75" />
        </span>
        <span class="plist__text">
          <span class="plist__name">{{ nameOf(p) }}</span>
          <span class="plist__hint">{{ purposeOf(p) }}</span>
          <span v-if="!p.available" class="plist__state">{{ t('assistant.platforms.unavailable') }}</span>
          <span v-else-if="issueOf(p) === 'missing'" class="plist__state is-warn">{{ t('assistant.platforms.needsLogin') }}</span>
          <span v-else-if="issueOf(p) === 'offForChat'" class="plist__state is-warn">
            {{ t('assistant.platforms.offForChat') }}
            <button
              type="button"
              class="plist__fix"
              :disabled="enabling === p.id"
              :aria-label="`${nameOf(p)}: ${t('composer.useInChat')} - ${t('assistant.platforms.turnOn')}`"
              @click="enableForChat(p)"
            >
              {{ t('assistant.platforms.turnOn') }}
            </button>
          </span>
        </span>
        <VSwitch
          class="plist__switch"
          :model-value="p.available && p.user_enabled"
          :disabled="!p.available"
          :aria-label="nameOf(p)"
          :aria-busy="store.pending.has(p.id) ? 'true' : undefined"
          @update:model-value="onToggle(p)"
        />
      </li>
    </ul>
  </section>
</template>

<style scoped>
.plist {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.plist__title {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
.plist__lead {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-wrap: pretty;
}
.plist__rows {
  margin: 0;
  padding: 0;
  list-style: none;
}
.plist__row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-height: 60px;
  padding: var(--s-2) 0;
}
.plist__row + .plist__row {
  border-top: 1px solid var(--line);
}
.plist__glyph {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.plist__text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.plist__name {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.plist__hint,
.plist__state {
  max-width: 100%;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  text-wrap: pretty;
}
.plist__state {
  font-weight: 500;
}
.plist__state.is-warn {
  color: var(--warn-text);
}
.plist__switch {
  flex-shrink: 0;
}
/* Barmoq uchun kalitning bosish maydoni kattaroq - ko'rinishi o'zgarmaydi. */
@media (pointer: coarse) {
  .plist__switch :deep(.v-switch__track)::after {
    content: '';
    position: absolute;
    inset: -12px -6px;
  }
}
/* Server o'chirgan platforma: nom, izoh VA holat bir xil xira - holat nomdan to'qroq
   ko'rinmasin (Mini App'da ham holat izoh qatorida, xira). */
.plist__row.is-unavailable .plist__glyph,
.plist__row.is-unavailable .plist__name,
.plist__row.is-unavailable .plist__hint,
.plist__row.is-unavailable .plist__state {
  color: var(--text-4);
  font-weight: 400;
}
.plist__fix {
  margin-left: var(--s-1);
  padding: 0;
  border: 0;
  background: none;
  color: var(--text);
  font: inherit;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.plist__fix:disabled {
  opacity: 0.5;
  cursor: default;
}
.plist__empty {
  padding: var(--s-3) 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.plist__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  padding: var(--s-3) 0;
  color: var(--warn-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
</style>
