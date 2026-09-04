<script setup lang="ts">
// Splash sahifasidagi desktop yuklab olish bloki: Windows (tayyor) + macOS (yaqinda).
//
// Versiya, hajm va fayl nomi /download/version.json dan olinadi — desktop
// ilovaning auto-update manifestidan. Shu sababli yangi .exe serverga qo'yilganda
// sayt o'zi yangi versiyani ko'rsatadi, frontend'ni qayta yig'ish shart emas.
//
// Manifest o'qilmasa (server hali sozlanmagan, tarmoq yo'q) — Windows kartasi
// o'chirilgan holatda qoladi va sabab yoziladi. Splash baribir ochilaveradi.

import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  fetchDesktopRelease,
  formatSize,
  setupUrl,
  type DesktopRelease,
} from '../api/download.api'
import { AppleIcon, DownloadIcon, WindowsIcon } from '../icons'

const { t, locale } = useI18n({ useScope: 'global' })

const release = ref<DesktopRelease | null>(null)
const loading = ref(true)
const controller = new AbortController()

onMounted(async () => {
  release.value = await fetchDesktopRelease(controller.signal)
  loading.value = false
})
// Foydalanuvchi manifest kelgunicha sahifadan ketsa, so'rovni bekor qilamiz.
onUnmounted(() => controller.abort())

const href = computed(() => (release.value ? setupUrl(release.value) : undefined))
const meta = computed(() => {
  if (!release.value) return ''
  const size = formatSize(release.value.setup.size, locale.value)
  const version = t('downloadVersion', { version: release.value.version })
  return size ? `${version} · ${size}` : version
})
</script>

<template>
  <section class="dl" :aria-label="t('downloadTitle')">
    <h2 class="dl__title">{{ t('downloadTitle') }}</h2>
    <p class="dl__sub">{{ t('downloadSub') }}</p>

    <div class="dl__cards">
      <!-- Windows: manifest kelganda haqiqiy <a download>, aks holda o'chirilgan.
           Havolani <a> sifatida qoldiramiz - o'ng tugma "Save link as" ishlaydi,
           yuklanish JS'ga bog'liq bo'lmaydi. -->
      <a
        v-if="href"
        class="dl__card dl__card--ready"
        :href="href"
        download
        :aria-label="`${t('downloadCta')} — Windows, ${meta}`"
      >
        <span class="dl__os"><WindowsIcon :size="20" /></span>
        <span class="dl__body">
          <span class="dl__name">Windows</span>
          <span class="dl__req">{{ t('downloadWindowsReq') }}</span>
        </span>
        <span class="dl__action">
          <DownloadIcon :size="16" />
          <span class="dl__meta">{{ meta }}</span>
        </span>
      </a>

      <div v-else class="dl__card dl__card--off" aria-disabled="true">
        <span class="dl__os"><WindowsIcon :size="20" /></span>
        <span class="dl__body">
          <span class="dl__name">Windows</span>
          <span class="dl__req">{{ t('downloadWindowsReq') }}</span>
        </span>
        <span class="dl__action dl__action--muted">
          {{ loading ? t('downloadChecking') : t('downloadUnavailable') }}
        </span>
      </div>

      <!-- macOS: hali yig'ilmagan. Ataylab <button> emas, <div aria-disabled> -
           bosiladigan narsaga o'xshamasligi kerak. -->
      <div class="dl__card dl__card--off" aria-disabled="true">
        <span class="dl__os"><AppleIcon :size="19" /></span>
        <span class="dl__body">
          <span class="dl__name">macOS</span>
          <span class="dl__req">{{ t('downloadMacReq') }}</span>
        </span>
        <span class="dl__action dl__action--muted">{{ t('comingSoon') }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dl {
  /* Ota element (.splash__content) pointer-events:none - galaktikani kursorga
     javob beradigan qoldirish uchun. Kartalar bosilishi kerak, qaytaramiz. */
  pointer-events: auto;
  margin-top: 42px;
  width: 100%;
  max-width: 480px;
  margin-inline: auto;
}
.dl__title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.dl__sub {
  margin: 0 0 16px;
  font-size: 13px;
  line-height: 1.45;
  color: var(--text-secondary);
}
.dl__cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dl__card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  text-align: left;
  text-decoration: none;
}
.dl__card--ready {
  color: var(--text);
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.1s ease;
}
.dl__card--ready:hover {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  background: var(--surface-hover);
}
.dl__card--ready:active {
  transform: scale(0.995);
}
.dl__card--ready:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent);
}
/* O'chirilgan karta: bor, lekin bosilmaydi. Kontrast pasaytiriladi, yo'qotilmaydi -
   "yaqinda" ni o'qib bo'lishi kerak. */
.dl__card--off {
  color: var(--text-secondary);
  background: var(--surface-sunken);
  border-style: dashed;
}
.dl__os {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 10px;
  background: var(--surface-inset);
  color: var(--text);
}
.dl__card--off .dl__os {
  color: var(--icon-muted);
}
.dl__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.dl__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.dl__card--off .dl__name {
  color: var(--text-secondary);
}
.dl__req {
  font-size: 12px;
  color: var(--text-muted);
}
.dl__action {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: none;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent);
  white-space: nowrap;
}
.dl__action--muted {
  color: var(--text-muted);
  font-weight: 500;
}
.dl__meta {
  font-variant-numeric: tabular-nums;
}
@media (max-width: 520px) {
  .dl {
    margin-top: 32px;
  }
  /* Tor ekranda hajm/versiya matni nomni siqib qo'ymasligi uchun pastga tushadi. */
  .dl__card {
    flex-wrap: wrap;
  }
  .dl__action {
    width: 100%;
    padding-left: 46px;
  }
}
</style>
