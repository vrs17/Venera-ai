<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Download, FlaskConical, Save, Search, Trash2, Wand2 } from 'lucide-vue-next'
import { ApiError } from '../../api/http'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VCard from '../../ui/VCard.vue'
import VCheckbox from '../../ui/VCheckbox.vue'
import VDialog from '../../ui/VDialog.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VInput from '../../ui/VInput.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VTabs from '../../ui/VTabs.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { useToast } from '../../ui/useToast'
import {
  buildPlaygroundPrompt,
  deletePlaygroundCase,
  exportPlaygroundCases,
  getPlaygroundStatus,
  getPlaygroundTurn,
  listPlaygroundCases,
  savePlaygroundCase,
} from '../api'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import RelTime from '../components/RelTime.vue'
import { useAdminQuery } from '../components/useAdminQuery'
import StageEditor from '../playground/StageEditor.vue'
import type { PgCase, PgInput, PgStage, PgTurn } from '../playground/types'

// "Agent playground" (ega, 2026-10-15): agent nega shunday javob berganini topish uchun har
// bosqichning AYNAN modelga ketgan kirishi va chiqishi; bittasini tahrirlab qayta ishga tushirish,
// modelni almashtirish va ikki modelni yonma-yon solishtirish; holatni regressiya sinoviga saqlash.
//
// Uch rejim:
//   turn  - haqiqiy savol (`?turn=<id>`, savol sahifasidagi "Playground'da ochish" tugmasi);
//           bosqichlar agent saqlagan yozuvdan (`/debug/turns`, egasi ruxsat berganda yoqiladi);
//   fresh - yangi savol: agent bosqich kirishini yig'adi (model chaqirilmaydi), keyin tahrir + ishga tushirish;
//   cases - saqlangan sinovlar va eksport (`run_inproc` to'plami shaklida).

type Mode = 'turn' | 'fresh' | 'cases'

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const toast = useToast()

const status = useAdminQuery((_p: null, signal: AbortSignal) => getPlaygroundStatus(signal), { params: null })
const models = computed(() => status.data.value?.models ?? [])

const mode = ref<Mode>(typeof route.query.turn === 'string' ? 'turn' : 'fresh')
const tabs = computed(() => [
  { value: 'turn' as Mode, label: t('admin.playground.modeTurn') },
  { value: 'fresh' as Mode, label: t('admin.playground.modeFresh') },
  { value: 'cases' as Mode, label: t('admin.playground.modeCases') },
])

/* ---------------------------------------------------------------- haqiqiy savol */

const turnId = ref(typeof route.query.turn === 'string' ? route.query.turn : '')
const turn = ref<PgTurn | null>(null)
const turnLoading = ref(false)
const turnError = ref<string | null>(null)
const stageId = ref<string | null>(null)
const stages = computed<PgStage[]>(() => turn.value?.capture?.stages ?? [])
const stage = computed(() => stages.value.find((s) => s.id === stageId.value) ?? stages.value[0] ?? null)

async function openTurn() {
  const id = turnId.value.trim()
  if (!id) return
  turnLoading.value = true
  turnError.value = null
  try {
    turn.value = await getPlaygroundTurn(id)
    stageId.value = turn.value.capture?.stages[0]?.id ?? null
    if (route.query.turn !== id) void router.replace({ query: { ...route.query, turn: id } })
  } catch (e) {
    turn.value = null
    turnError.value = e instanceof ApiError ? e.message : String(e)
  } finally {
    turnLoading.value = false
  }
}

watch(
  () => route.query.turn,
  (value) => {
    if (typeof value === 'string' && value && value !== turn.value?.turn.id) {
      turnId.value = value
      mode.value = 'turn'
      void openTurn()
    }
  },
  { immediate: true },
)

/* ---------------------------------------------------------------- yangi savol */

const PLATFORMS = ['hrm', 'crm', 'dwh', 'biznes247', 'superapp', 'biznes247_kb']
const freshQuestion = ref('')
const freshStage = ref('agent')
const freshPlatforms = ref<string[]>(['hrm', 'crm'])
const freshInput = ref<PgInput | null>(null)
const freshLoading = ref(false)
const freshError = ref<string | null>(null)

function togglePlatform(p: string, on: boolean) {
  freshPlatforms.value = on ? [...new Set([...freshPlatforms.value, p])] : freshPlatforms.value.filter((x) => x !== p)
}

async function buildFresh() {
  if (!freshQuestion.value.trim() || !freshStage.value.trim()) return
  freshLoading.value = true
  freshError.value = null
  try {
    const res = await buildPlaygroundPrompt({
      stage: freshStage.value.trim(),
      question: freshQuestion.value.trim(),
      platforms: freshPlatforms.value,
    })
    freshInput.value = res.input
  } catch (e) {
    freshInput.value = null
    freshError.value = e instanceof ApiError ? e.message : String(e)
  } finally {
    freshLoading.value = false
  }
}

/* ---------------------------------------------------------------- sinovlar */

const cases = useAdminQuery((_p: null, signal: AbortSignal) => listPlaygroundCases(signal), { params: null })
const caseOpen = ref(false)
const caseTitle = ref('')
const caseDialog = ref('')
const caseExpect = ref('')
const caseOwner = ref(false)
const caseSaving = ref(false)
const caseError = ref<string | null>(null)

function openCaseDialog() {
  const question = mode.value === 'turn' ? turn.value?.turn.question ?? '' : freshQuestion.value
  caseTitle.value = question.slice(0, 80)
  caseDialog.value = question
  caseExpect.value = ''
  caseOwner.value = false
  caseError.value = null
  caseOpen.value = true
}

const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean)

async function saveCase() {
  caseSaving.value = true
  caseError.value = null
  try {
    await savePlaygroundCase({
      title: caseTitle.value.trim() || t('admin.playground.untitled'),
      dialog: lines(caseDialog.value),
      expect: lines(caseExpect.value),
      turn_id: mode.value === 'turn' ? turn.value?.turn.id ?? null : null,
      stage: mode.value === 'turn' ? stage.value?.name ?? null : freshStage.value || null,
      needs: caseOwner.value ? 'owner' : 'none',
    })
    caseOpen.value = false
    toast.show({ message: t('admin.playground.saved'), tone: 'good' })
    cases.refresh()
  } catch (e) {
    caseError.value = e instanceof ApiError ? e.message : String(e)
  } finally {
    caseSaving.value = false
  }
}

async function removeCase(item: PgCase) {
  try {
    await deletePlaygroundCase(item.id)
    toast.show({ message: t('admin.playground.deleted'), tone: 'good' })
    cases.refresh()
  } catch (e) {
    toast.show({ message: e instanceof ApiError ? e.message : String(e), tone: 'crit' })
  }
}

async function downloadCases() {
  const data = await exportPlaygroundCases()
  const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `barno-playground-cases-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

const canSave = computed(() =>
  mode.value === 'turn' ? !!turn.value : !!freshQuestion.value.trim(),
)
</script>

<template>
  <div class="pg" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.playground.title')"
      :subtitle="t('admin.page.playground.subtitle')"
      :refreshing="status.loading.value"
      @refresh="status.refresh"
    >
      <template #actions>
        <VButton v-if="mode !== 'cases'" variant="secondary" :icon="Save" :disabled="!canSave" @click="openCaseDialog">
          {{ t('admin.playground.saveCase') }}
        </VButton>
      </template>
    </AdminPageHeader>

    <VCard v-if="status.data.value && !status.data.value.available" class="pg__notice" role="status">
      <strong>{{ t('admin.playground.unavailable') }}</strong>
      <p>{{ status.data.value.message }}</p>
    </VCard>
    <div v-else-if="models.length" class="pg__models">
      <span>{{ t('admin.playground.models') }}</span>
      <VBadge v-for="m in models" :key="m" tone="neutral">{{ m }}</VBadge>
    </div>

    <VTabs v-model="mode" :tabs="tabs" :aria-label="t('admin.page.playground.title')">
      <template #default="{ value }">
        <!-- haqiqiy savol -->
        <section v-if="value === 'turn'" class="pg__section">
          <form class="pg__picker" @submit.prevent="openTurn">
            <VInput v-model="turnId" :label="t('admin.playground.turnId')" :icon="Search" clearable />
            <VButton type="submit" :loading="turnLoading" :disabled="!turnId">{{ t('admin.playground.open') }}</VButton>
          </form>
          <p class="pg__hint">{{ t('admin.playground.turnHint') }}</p>
          <AdminError v-if="turnError" :message="turnError" @retry="openTurn" />
          <VSkeleton v-else-if="turnLoading" :lines="6" />
          <template v-else-if="turn">
            <VCard class="pg__turn">
              <div class="pg__turnmeta">
                <VBadge v-if="turn.turn.route" tone="info">{{ turn.turn.route }}</VBadge>
                <VBadge v-if="turn.turn.engine" tone="neutral">{{ turn.turn.engine }}</VBadge>
                <RelTime :value="turn.turn.started_at * 1000" />
                <span v-if="turn.turn.user_login">{{ turn.turn.user_login }}</span>
              </div>
              <p class="pg__q"><strong>{{ t('admin.playground.question') }}:</strong> {{ turn.turn.question }}</p>
              <p class="pg__a"><strong>{{ t('admin.playground.answer') }}:</strong> {{ turn.turn.answer }}</p>
            </VCard>
            <VCard v-if="turn.problem" class="pg__notice" role="status">
              <strong>{{ t('admin.playground.problem') }}</strong>
              <p>{{ turn.problem.message }}</p>
            </VCard>
            <div v-else-if="stages.length" class="pg__stages">
              <nav class="pg__stagelist" :aria-label="t('admin.playground.stages')">
                <button
                  v-for="s in stages"
                  :key="s.id"
                  type="button"
                  class="pg__stagebtn"
                  :class="{ 'is-active': stage?.id === s.id }"
                  :aria-current="stage?.id === s.id ? 'step' : undefined"
                  @click="stageId = s.id"
                >
                  <span class="pg__stagename">{{ s.name }}</span>
                  <span class="pg__stagemeta">
                    {{ s.model || '—' }} · {{ s.ms ?? '—' }} ms · {{ s.tokens_in ?? '—' }}/{{ s.tokens_out ?? '—' }}
                  </span>
                </button>
              </nav>
              <StageEditor
                v-if="stage"
                :key="stage.id"
                :stage="stage.name"
                :input="stage.input"
                :output="stage.output"
                :model="stage.model"
                :models="models"
              />
            </div>
            <VEmpty v-else :icon="FlaskConical" :title="t('admin.playground.noStages')" />
          </template>
        </section>

        <!-- yangi savol -->
        <section v-else-if="value === 'fresh'" class="pg__section">
          <form class="pg__fresh" @submit.prevent="buildFresh">
            <VTextarea v-model="freshQuestion" :label="t('admin.playground.question')" :rows="2" :max-rows="6" />
            <div class="pg__freshrow">
              <VInput v-model="freshStage" :label="t('admin.playground.stage')" :hint="t('admin.playground.stageHint')" />
              <fieldset class="pg__platforms">
                <legend>{{ t('admin.playground.platforms') }}</legend>
                <VCheckbox
                  v-for="p in PLATFORMS"
                  :key="p"
                  :model-value="freshPlatforms.includes(p)"
                  :label="p"
                  @update:model-value="(on: boolean | unknown[]) => togglePlatform(p, on === true)"
                />
              </fieldset>
            </div>
            <VButton type="submit" :icon="Wand2" :loading="freshLoading" :disabled="!freshQuestion.trim()">
              {{ t('admin.playground.build') }}
            </VButton>
          </form>
          <AdminError v-if="freshError" :message="freshError" @retry="buildFresh" />
          <StageEditor
            v-else-if="freshInput"
            :stage="freshStage"
            :input="freshInput"
            :models="models"
            :model="status.data.value?.default_model ?? null"
          />
        </section>

        <!-- sinovlar -->
        <section v-else class="pg__section">
          <div class="pg__caseshead">
            <span>{{ t('admin.playground.cases') }} · {{ cases.data.value?.items.length ?? 0 }}</span>
            <VButton variant="secondary" :icon="Download" :disabled="!cases.data.value?.items.length" @click="downloadCases">
              {{ t('admin.playground.export') }}
            </VButton>
          </div>
          <AdminError v-if="cases.errorText.value" :message="cases.errorText.value" @retry="cases.refresh" />
          <VEmpty
            v-else-if="cases.data.value && !cases.data.value.items.length"
            :icon="FlaskConical"
            :title="t('admin.playground.noCases')"
          />
          <ul v-else class="pg__cases">
            <li v-for="c in cases.data.value?.items ?? []" :key="c.id" class="pg__case">
              <div class="pg__casehead">
                <strong>{{ c.title }}</strong>
                <VIconButton :icon="Trash2" size="sm" :label="t('admin.playground.delete')" @click="removeCase(c)" />
              </div>
              <div class="pg__turnmeta">
                <VBadge tone="neutral">{{ c.area }}</VBadge>
                <VBadge v-if="c.stage" tone="info">{{ c.stage }}</VBadge>
                <VBadge v-if="c.needs === 'owner'" tone="warn">{{ t('admin.playground.caseNeeds') }}</VBadge>
                <RelTime :value="c.created_at * 1000" />
              </div>
              <ol class="pg__dialog">
                <li v-for="(q, i) in c.dialog" :key="i">{{ q }}</li>
              </ol>
              <ul class="pg__expect">
                <li v-for="(e, i) in c.expect" :key="i">{{ e }}</li>
              </ul>
            </li>
          </ul>
        </section>
      </template>
    </VTabs>

    <VDialog v-model:open="caseOpen" :title="t('admin.playground.saveCase')" size="md">
      <form class="pg__caseform" @submit.prevent="saveCase">
        <VInput v-model="caseTitle" :label="t('admin.playground.caseTitle')" />
        <VTextarea v-model="caseDialog" :label="t('admin.playground.caseDialog')" :rows="3" :max-rows="10" />
        <VTextarea
          v-model="caseExpect"
          :label="t('admin.playground.caseExpect')"
          :hint="t('admin.playground.caseExpectHint')"
          :rows="3"
          :max-rows="10"
        />
        <VCheckbox v-model="caseOwner" :label="t('admin.playground.caseNeeds')" />
        <p v-if="caseError" class="pg__error" role="alert">{{ caseError }}</p>
      </form>
      <template #footer>
        <VButton variant="ghost" @click="caseOpen = false">{{ t('admin.playground.cancel') }}</VButton>
        <VButton
          :icon="Save"
          :loading="caseSaving"
          :disabled="!lines(caseDialog).length || !lines(caseExpect).length"
          @click="saveCase"
        >
          {{ t('admin.playground.save') }}
        </VButton>
      </template>
    </VDialog>
  </div>
</template>

<style scoped>
.pg { display: grid; gap: var(--s-6); min-width: 0; }
.pg__section { display: grid; gap: var(--s-4); padding-top: var(--s-4); min-width: 0; }
.pg__notice { display: grid; gap: var(--s-1); }
.pg__notice p { margin: 0; color: var(--text-2); }
.pg__models { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2); font-size: var(--fs-body-sm); color: var(--text-3); }
.pg__picker { display: flex; align-items: flex-end; gap: var(--s-2); max-width: 560px; }
.pg__picker > :first-child { flex: 1; }
.pg__hint { margin: 0; font-size: var(--fs-caption); color: var(--text-3); }
.pg__turn { display: grid; gap: var(--s-2); }
.pg__turnmeta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2); font-size: var(--fs-caption); color: var(--text-3); }
.pg__q, .pg__a { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.pg__a { color: var(--text-2); }
.pg__stages { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: var(--s-6); align-items: start; }
.pg__stagelist { display: grid; gap: var(--s-1); position: sticky; top: var(--s-4); }
.pg__stagebtn { display: grid; gap: 2px; text-align: left; padding: var(--s-2) var(--s-3); border: 1px solid var(--line); border-radius: var(--r-md); background: var(--bg); color: var(--text); cursor: pointer; }
.pg__stagebtn.is-active { border-color: var(--brand, var(--text)); background: var(--bg-subtle); }
.pg__stagename { font-weight: 600; font-size: var(--fs-body-sm); }
.pg__stagemeta { font-size: var(--fs-caption); color: var(--text-3); overflow-wrap: anywhere; }
.pg__fresh { display: grid; gap: var(--s-3); }
.pg__freshrow { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: var(--s-4); align-items: start; }
.pg__platforms { display: flex; flex-wrap: wrap; gap: var(--s-3); margin: 0; padding: 0; border: 0; }
.pg__platforms legend { font-size: var(--fs-body-sm); font-weight: 600; color: var(--text-2); margin-bottom: var(--s-1_5); }
.pg__caseshead, .pg__casehead { display: flex; align-items: center; justify-content: space-between; gap: var(--s-2); }
.pg__cases { display: grid; gap: var(--s-3); margin: 0; padding: 0; list-style: none; }
.pg__case { display: grid; gap: var(--s-2); padding: var(--s-4); border: 1px solid var(--line); border-radius: var(--r-md); }
.pg__dialog, .pg__expect { margin: 0; padding-left: 20px; font-size: var(--fs-body-sm); }
.pg__expect { color: var(--text-2); }
.pg__caseform { display: grid; gap: var(--s-3); }
.pg__error { margin: 0; color: var(--crit, #c0392b); font-size: var(--fs-body-sm); }
@media (max-width: 900px) {
  .pg__stages, .pg__freshrow { grid-template-columns: 1fr; }
  .pg__stagelist { position: static; }
}
</style>
