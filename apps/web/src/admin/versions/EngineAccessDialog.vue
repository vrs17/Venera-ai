<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, SearchX } from 'lucide-vue-next'
import VButton from '../../ui/VButton.vue'
import VChoiceChips from '../../ui/VChoiceChips.vue'
import type { ChoiceOption } from '../../ui/VChoiceChips.vue'
import VDialog from '../../ui/VDialog.vue'
import VSearchField from '../../ui/VSearchField.vue'
import VSegmented from '../../ui/VSegmented.vue'
import type { SegmentedOption } from '../../ui/VSegmented.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { useId } from '../../ui/composables/useId'
import { useIsPhone } from '../../ui/composables/useMediaQuery'
import { useToast } from '../../ui/useToast'
import { listUsers, putEngineAccess } from '../api'
import type { AdminUser, EngineAccessRow } from '../types'
import UserCell from '../components/UserCell.vue'
import { userActionError } from '../users/userErrors'
import { engineLabel } from './engineText'

/** Oynada tanlangan odam - jadval qatori, foydalanuvchi varag'i yoki qidiruv natijasi. */
export interface AccessPerson {
  actorId: number
  name: string | null
  login: string | null
}

/**
 * Alohida ruxsat muharriri - "Versiyalar" sahifasida ham, foydalanuvchi varag'ida ham
 * AYNI oyna: bir xil maydonlar, bir xil tekshiruv, bir xil xato matnlari.
 *
 * Maydonlar (kam so'z, bitta ustun - telefonda pastki sheet bo'ladi):
 *   Odam       - `person` berilmasa qidiruv (ism/login, 2 harfdan), natijalar shu yerning
 *                o'zida ro'yxat: popover emas - pastki sheet ichida suzuvchi qatlam
 *                klaviatura ostida qolib ketardi;
 *   Versiyalar - VChoiceChips (bir nechta), kamida bitta;
 *   Standart   - faqat ikki va undan ko'p versiya berilsa (bittasi o'zi standart);
 *   Izoh       - ixtiyoriy.
 *
 * Qidiruvda topilgan odamga allaqachon ruxsat berilgan bo'lsa (`existing`), uning joriy
 * qiymatlari yuklanadi - "qo'shish" jimgina eski ruxsatni bosib ketmasin.
 *
 * Props:
 * - `open`      - v-model:open.
 * - `person`    - qat'iy odam (tahrirlash, varaqdan); `null` - qidiruv.
 * - `initial`   - joriy ruxsat (tahrirlashda).
 * - `engines`   - katalog kalitlari.
 * - `preferred` - yangi ruxsatda standart qaysi bo'lsin (odatda "hamma uchun" versiya).
 * - `existing`  - sahifadagi ruxsatlar ro'yxati (qidiruvda topilgan odamni tanish uchun).
 * Emits: `saved(row)` - server qaytargan qator.
 */
const props = withDefaults(
  defineProps<{
    person?: AccessPerson | null
    initial?: { engines: string[]; defaultEngine: string | null; note?: string | null } | null
    engines: string[]
    preferred?: string | null
    existing?: readonly EngineAccessRow[]
  }>(),
  { person: null, initial: null, preferred: null, existing: () => [] },
)

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ saved: [row: EngineAccessRow] }>()

const { t, te } = useI18n({ useScope: 'global' })
const tr = (key: string) => t(key)
const label = (id: string) => engineLabel(id, t, te)
const toast = useToast()
const uid = useId('ead')
// Telefonda (pastki sheet) standart tanlovi to'liq enda - teng, katta nishonlar.
const isPhone = useIsPhone()

const NOTE_MAX = 500

/* ---------------------------------------------------------------- holat */

const chosen = ref<AccessPerson | null>(null)
const allowed = ref<string[]>([])
const defaultEngine = ref<string | null>(null)
const note = ref('')
const saving = ref(false)
const error = ref<string | null>(null)
const query = ref('')
/** `null` - hali qidirilmagan (ishora ko'rinadi), `[]` - topilmadi. */
const results = ref<AdminUser[] | null>(null)
const searching = ref(false)

const who = computed<AccessPerson | null>(() => props.person ?? chosen.value)
const editing = computed(() => !!props.person && !!props.initial)
const title = computed(() =>
  editing.value && who.value
    ? t('admin.versions.editorEdit', { name: who.value.name || who.value.login || `#${who.value.actorId}` })
    : t('admin.versions.editorAdd'),
)

/** Katalog tartibida (v1, v2) - chip'lar va so'rov bir xil tartibda. */
function ordered(list: readonly string[]): string[] {
  const known = props.engines.filter((id) => list.includes(id))
  const extra = list.filter((id) => !props.engines.includes(id))
  return [...known, ...extra]
}

/** Standart: avval saqlangani, keyin "hamma uchun" versiya, keyin birinchisi. */
function pickDefault(list: string[], wanted: string | null | undefined): string | null {
  if (!list.length) return null
  if (wanted && list.includes(wanted)) return wanted
  if (props.preferred && list.includes(props.preferred)) return props.preferred
  return list[0]
}

function fill(from: { engines: string[]; defaultEngine: string | null; note?: string | null } | null) {
  const list = ordered(from?.engines?.length ? from.engines : props.engines)
  allowed.value = list
  defaultEngine.value = pickDefault(list, from?.defaultEngine)
  note.value = from?.note ?? ''
}

// Har ochilishda toza: oldingi odamning qoralamasi keyingisiga o'tmasin.
watch(open, (now) => {
  if (!now) return
  chosen.value = null
  query.value = ''
  results.value = null
  error.value = null
  saving.value = false
  fill(props.initial)
})

// Versiyadan biri olib tashlansa - standart ham ro'yxat ichida qolsin.
watch(allowed, (list) => {
  if (!defaultEngine.value || !list.includes(defaultEngine.value)) defaultEngine.value = pickDefault(list, null)
})

/* ---------------------------------------------------------------- odam qidiruvi */

let searchSeq = 0
let controller: AbortController | null = null

async function search(q: string) {
  const text = q.trim()
  controller?.abort()
  if (text.length < 2) {
    searchSeq++
    results.value = null
    searching.value = false
    return
  }
  const id = ++searchSeq
  const ctrl = new AbortController()
  controller = ctrl
  searching.value = true
  try {
    const list = await listUsers({ q: text }, ctrl.signal)
    if (id !== searchSeq) return
    // Faqat haqiqiy hisoblar: tarixda qolgan (o'chirilgan) odamga ruxsat berib bo'lmaydi.
    results.value = list.items.filter((u) => u.source !== 'telemetry').slice(0, 8)
  } catch {
    if (id === searchSeq) results.value = []
  } finally {
    if (id === searchSeq) searching.value = false
  }
}

function choosePerson(u: AdminUser) {
  chosen.value = { actorId: u.actorId, name: u.name, login: u.login ?? u.email }
  error.value = null
  const had = props.existing.find((r) => r.actorId === u.actorId)
  fill(had ? { engines: had.engines, defaultEngine: had.defaultEngine, note: had.note } : null)
}

function changePerson() {
  chosen.value = null
}

/* ---------------------------------------------------------------- versiyalar */

const engineOptions = computed<ChoiceOption<string>[]>(() =>
  ordered([...props.engines, ...allowed.value.filter((id) => !props.engines.includes(id))]).map((id) => ({
    value: id,
    label: label(id),
  })),
)
const defaultOptions = computed<SegmentedOption<string>[]>(() => allowed.value.map((id) => ({ value: id, label: id })))

function onAllowed(v: string | string[] | null) {
  const list = Array.isArray(v) ? v : v ? [v] : []
  // Kamida bitta: oxirgisini olib tashlab bo'lmaydi (bo'sh ruxsat - "olib tashlash", u alohida tugma).
  if (!list.length) return
  allowed.value = ordered(list)
}

/* ---------------------------------------------------------------- saqlash */

const canSave = computed(() => !!who.value && allowed.value.length > 0 && !saving.value)

async function save() {
  const person = who.value
  if (!person || !allowed.value.length || saving.value) return
  saving.value = true
  error.value = null
  try {
    const row = await putEngineAccess(person.actorId, {
      engines: allowed.value,
      // Bitta versiya - u o'zi standart; serverga aniq yuboramiz (ro'yxat bilan zid bo'lmasin).
      defaultEngine: allowed.value.length > 1 ? defaultEngine.value : allowed.value[0],
      note: note.value.trim() || null,
    })
    toast.show({ message: t('admin.versions.accessSaved'), tone: 'good', id: 'admin-engine-access' })
    emit('saved', row)
    open.value = false
  } catch (err) {
    // Oyna ochiq qoladi: sabab shu yerda, qayta urinish qo'l ostida.
    error.value = userActionError(err, tr)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <VDialog v-model:open="open" size="md" :title="title" :dismissible="!saving">
    <div class="ead">
      <!-- odam -->
      <section class="ead-field" :aria-labelledby="`${uid}-person`">
        <h3 :id="`${uid}-person`" class="ead-label">{{ t('admin.versions.person') }}</h3>
        <div v-if="who" class="ead-person">
          <UserCell :name="who.name" :login="who.login" :size="32" />
          <VButton v-if="!person" variant="ghost" size="sm" @click="changePerson">
            {{ t('admin.versions.edit') }}
          </VButton>
        </div>
        <template v-else>
          <VSearchField
            v-model="query"
            :placeholder="t('admin.versions.personSearch')"
            :aria-label="t('admin.versions.personSearch')"
            :loading="searching"
            autofocus
            @search="search"
          />
          <p v-if="results === null" class="ead-hint">{{ t('admin.versions.personHint') }}</p>
          <p v-else-if="!results.length && !searching" class="ead-hint ead-hint--none">
            <SearchX :size="14" :stroke-width="1.75" aria-hidden="true" />
            {{ t('admin.versions.personNone') }}
          </p>
          <ul v-else class="ead-results" :aria-labelledby="`${uid}-person`">
            <li v-for="u in results" :key="u.actorId">
              <button type="button" class="ead-result" @click="choosePerson(u)">
                <UserCell :name="u.name" :login="u.login ?? u.email" :sub="u.department" />
                <span v-if="existing.some((r) => r.actorId === u.actorId)" class="ead-result__has">
                  {{ t('admin.versions.access') }}
                </span>
              </button>
            </li>
          </ul>
        </template>
      </section>

      <!-- versiyalar -->
      <section class="ead-field" :aria-labelledby="`${uid}-engines`">
        <h3 :id="`${uid}-engines`" class="ead-label">{{ t('admin.versions.allowed') }}</h3>
        <VChoiceChips
          multiple
          :options="engineOptions"
          :model-value="allowed"
          :aria-label="t('admin.versions.allowed')"
          @update:model-value="onAllowed"
        />
        <p class="ead-hint">{{ t('admin.versions.allowedHint') }}</p>
      </section>

      <!-- standart: faqat tanlash uchun kamida ikkitasi bo'lsa -->
      <section v-if="allowed.length > 1" class="ead-field" :aria-labelledby="`${uid}-default`">
        <h3 :id="`${uid}-default`" class="ead-label">{{ t('admin.versions.defaultEngine') }}</h3>
        <VSegmented
          class="ead-seg"
          :block="isPhone"
          :options="defaultOptions"
          :model-value="defaultEngine"
          size="sm"
          :aria-label="t('admin.versions.defaultEngine')"
          @update:model-value="(v: string) => (defaultEngine = v)"
        />
      </section>

      <!-- izoh -->
      <section class="ead-field" :aria-labelledby="`${uid}-note`">
        <h3 :id="`${uid}-note`" class="ead-label">{{ t('admin.versions.note') }}</h3>
        <VTextarea
          v-model="note"
          :rows="2"
          :max-rows="5"
          :maxlength="NOTE_MAX"
          :placeholder="t('admin.versions.notePlaceholder')"
          :aria-labelledby="`${uid}-note`"
        />
      </section>

      <p v-if="error" class="ead-err" role="alert">
        <CircleAlert :size="14" :stroke-width="1.75" aria-hidden="true" />
        {{ error }}
      </p>
    </div>

    <template #footer="{ close }">
      <VButton variant="ghost" :disabled="saving" @click="close">{{ t('ui.cancel') }}</VButton>
      <VButton variant="primary" :loading="saving" :disabled="!canSave && !saving" @click="save">
        {{ t('ui.save') }}
      </VButton>
    </template>
  </VDialog>
</template>

<style scoped>
.ead {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
}
.ead-field {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  min-width: 0;
}
.ead-label {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
.ead-seg:not(.v-seg--block) {
  align-self: flex-start;
}
.ead-hint {
  display: flex;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

.ead-person {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  min-width: 0;
  min-height: 48px;
  padding: var(--s-2) var(--s-2) var(--s-2) var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
}

/* Natijalar - oynaning o'zida (popover emas): telefonda pastki sheet ichida ham
   barmoq ostida, klaviatura ularni yopmaydi. 8 tagacha, keyin ichida aylanadi. */
.ead-results {
  display: flex;
  flex-direction: column;
  max-height: 264px;
  margin: 0;
  padding: var(--s-1);
  overflow-y: auto;
  overscroll-behavior: contain;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  list-style: none;
}
.ead-result {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  width: 100%;
  min-height: 48px;
  padding: var(--s-1_5) var(--s-2);
  border-radius: var(--r-sm);
  text-align: start;
  transition: background-color var(--dur-1) var(--ease-out);
}
.ead-result:hover,
.ead-result:focus-visible {
  background: var(--fill-hover);
}
.ead-result:focus-visible {
  outline-offset: -2px;
}
.ead-result__has {
  flex: none;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

.ead-err {
  display: flex;
  align-items: flex-start;
  gap: var(--s-1_5);
  color: var(--crit-text);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.ead-err > svg {
  flex: none;
  margin-top: 1px;
}

@media (pointer: coarse) {
  .ead-result {
    min-height: 56px;
  }
}
</style>
