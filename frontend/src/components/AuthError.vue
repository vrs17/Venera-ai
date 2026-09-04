<script setup lang="ts">
import { ShieldIcon } from '../icons'

/** Form-level error banner — shows validation or (once the API is wired) server
 *  errors such as "Invalid email or password". Hidden when message is empty. */
defineProps<{ message: string }>()
</script>

<template>
  <div v-if="message" class="auth-error" role="alert">
    <ShieldIcon :size="15" stroke="currentColor" />
    <span>{{ message }}</span>
  </div>
</template>

<style scoped>
.auth-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
  color: var(--bad-fg);
  background: var(--bad-bg);
  border: 1px solid var(--bad-bd);
}
</style>
