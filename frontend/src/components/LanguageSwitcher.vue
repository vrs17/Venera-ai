<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { LOCALES, setLocale } from '../i18n'
import type { Locale } from '../i18n'
import { ChevronDownIcon, GlobeIcon } from '../icons'

/**
 * Compact language picker for the header. Mirrors IdentityBar's glass-pill +
 * dropdown pattern (click-outside to close); selecting a locale flips the whole
 * UI via the i18n locale.
 */
const { locale, t } = useI18n({ useScope: 'global' })
const open = ref(false)
const wrapRef = ref<HTMLDivElement | null>(null)

const current = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale)) ?? LOCALES[0])

function onDocDown(e: MouseEvent) {
  if (wrapRef.value && !wrapRef.value.contains(e.target as Node)) open.value = false
}
watch(open, (isOpen) => {
  if (isOpen) document.addEventListener('mousedown', onDocDown)
  else document.removeEventListener('mousedown', onDocDown)
})
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocDown))

function choose(code: Locale) {
  setLocale(code)
  open.value = false
}
</script>

<template>
  <div ref="wrapRef" :style="{ position: 'relative' }">
    <button
      class="glass glass-hover"
      :title="t('language')"
      :aria-label="t('language')"
      :style="{
        fontFamily: 'Figtree, sans-serif',
        display: 'flex',
        alignItems: 'center',
        gap: '7px',
        height: '36px',
        fontSize: '13.5px',
        fontWeight: 600,
        color: 'var(--text)',
        background: 'var(--glass-bg)',
        border: '1px solid var(--glass-border)',
        borderRadius: '999px',
        padding: '0 12px',
        cursor: 'pointer',
        boxShadow: 'var(--glass-shadow)',
        transition: 'border-color 0.2s, background 0.2s',
      }"
      @click="open = !open"
    >
      <span :style="{ color: 'var(--text-secondary)', display: 'inline-flex' }">
        <GlobeIcon />
      </span>
      <span>{{ current.label }}</span>
      <ChevronDownIcon :style="{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }" />
    </button>

    <div
      v-if="open"
      class="glass"
      :style="{
        position: 'absolute',
        top: '44px',
        right: 0,
        minWidth: '150px',
        background: 'var(--glass-bg)',
        border: '1px solid var(--glass-border)',
        borderRadius: '14px',
        padding: '6px',
        boxShadow: 'var(--menu-shadow)',
        zIndex: 40,
        animation: 'fadeUp 0.2s ease both',
      }"
    >
      <button
        v-for="l in LOCALES"
        :key="l.code"
        class="menu-item"
        :style="{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          fontFamily: 'Figtree, sans-serif',
          fontSize: '13.5px',
          fontWeight: l.code === locale ? 700 : 500,
          color: l.code === locale ? 'var(--text)' : 'var(--text-secondary)',
          background: 'transparent',
          border: 'none',
          borderRadius: '9px',
          padding: '8px 10px',
          cursor: 'pointer',
          textAlign: 'left',
        }"
        @click="choose(l.code)"
      >
        {{ l.label }}
        <span
          v-if="l.code === locale"
          aria-hidden="true"
          :style="{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--ink)',
            flexShrink: 0,
          }"
        />
      </button>
    </div>
  </div>
</template>
