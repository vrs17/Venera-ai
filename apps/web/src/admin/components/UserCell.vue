<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import VAvatar from '../../ui/VAvatar.vue'

/**
 * Odam: avatar (bosh harflar) + ism, ostida login - jadval katagi, ro'yxat qatori.
 *
 * Props:
 * - `name`  - to'liq ism; bo'sh bo'lsa "Noma'lum" jim rangda.
 * - `login` - ikkinchi qator (login / email). `sub` berilsa - uning o'rniga.
 * - `sub`   - ixtiyoriy ikkinchi qator matni (bo'lim, "Siz" ...).
 * - `size`  - avatar: 24 | 28 (standart) | 32 | 40.
 * - `to`    - ism havola bo'ladi (foydalanuvchi varag'i). Jadval qatori o'zi bosiladigan
 *             bo'lsa `to` bermang - qator ichida ikkinchi nishon kerak emas.
 *
 *   <UserCell :name="turn.userName" :login="turn.userLogin" />
 */
const props = withDefaults(
  defineProps<{
    name?: string | null
    login?: string | null
    sub?: string | null
    size?: 24 | 28 | 32 | 40
    to?: RouteLocationRaw
  }>(),
  { name: null, login: null, sub: null, size: 28 },
)

const { t } = useI18n({ useScope: 'global' })

const display = computed(() => props.name?.trim() || props.login?.trim() || '')
const second = computed(() => props.sub ?? (props.name?.trim() ? props.login : null))
</script>

<template>
  <span class="uc" :class="`uc--${size}`">
    <VAvatar :name="display" :size="size" />
    <span class="uc__text">
      <component
        :is="to ? RouterLink : 'span'"
        :to="to"
        class="uc__name"
        :class="{ 'is-unknown': !display, 'is-link': !!to }"
      >{{ display || t('admin.common.unknownUser') }}</component>
      <span v-if="second" class="uc__sub">{{ second }}</span>
    </span>
  </span>
</template>

<style scoped>
.uc {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
  max-width: 100%;
  vertical-align: middle;
}
/* Katta avatar yonida biroz ko'proq havo. */
.uc--32,
.uc--40 {
  gap: var(--s-3);
}
.uc__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.uc__name,
.uc__sub {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.uc__name {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
.uc__name.is-unknown {
  color: var(--text-3);
  font-weight: 400;
}
.uc__name.is-link {
  text-decoration: underline;
  text-decoration-color: transparent;
  text-underline-offset: 3px;
  transition: text-decoration-color var(--dur-1) var(--ease-out);
}
.uc__name.is-link:hover {
  text-decoration-color: var(--line-strong);
}
.uc__sub {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
</style>
