<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import VSkeleton from '../../ui/VSkeleton.vue'
import type { AuditEntry } from '../types'
import RelTime from '../components/RelTime.vue'
import { auditDetail, auditLabel } from './auditText'

/**
 * Foydalanuvchi varag'idagi "O'zgarishlar": shu odamga oid admin amallari (kim, qachon,
 * nima). Jadval emas - tor varaqda ikki qatorli ro'yxat o'qilishi osonroq.
 *
 * Props:
 * - `entries` - null - hali yuklanmoqda (skelet).
 */
defineProps<{
  entries: AuditEntry[] | null
  labelledby?: string
}>()

const { t, te } = useI18n({ useScope: 'global' })
const tr = (key: string) => t(key)
const has = (key: string) => te(key)
const detailOf = (e: AuditEntry) => auditDetail(e, tr, has)
const labelOf = (e: AuditEntry) => auditLabel(e.action, tr, has)
</script>

<template>
  <ul v-if="entries === null" class="ua" aria-hidden="true">
    <li v-for="i in 2" :key="i" class="ua-item">
      <VSkeleton :width="`${[44, 36][i - 1]}%`" :height="12" />
      <VSkeleton :width="`${[28, 32][i - 1]}%`" :height="10" />
    </li>
  </ul>

  <p v-else-if="!entries.length" class="ua-none">{{ t('admin.empty.audit') }}</p>

  <ul v-else class="ua" :aria-labelledby="labelledby">
    <li v-for="e in entries" :key="e.id" class="ua-item">
      <p class="ua-what">
        <span class="ua-action">{{ labelOf(e) }}</span>
        <span v-if="detailOf(e)" class="ua-detail">{{ detailOf(e) }}</span>
      </p>
      <p class="ua-who">
        <span class="ua-admin">{{ e.adminName || t('admin.common.unknownUser') }}</span>
        <span aria-hidden="true">·</span>
        <RelTime :value="e.createdAt" />
      </p>
    </li>
  </ul>
</template>

<style scoped>
.ua {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  margin: 0;
  padding: 0;
  list-style: none;
}
.ua-item {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
}
.ua-what {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
  min-width: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.ua-action {
  flex: none;
  color: var(--text);
  font-weight: 500;
}
.ua-detail {
  min-width: 0;
  overflow: hidden;
  color: var(--text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ua-who {
  display: flex;
  align-items: center;
  gap: var(--s-1_5);
  min-width: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.ua-admin {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ua-none {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
</style>
