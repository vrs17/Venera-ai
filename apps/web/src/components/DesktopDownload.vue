<script setup lang="ts">
// Desktop ilovani yuklab olish: Windows va macOS.
//
// Versiya, hajm va fayl nomi /download/version.json dan olinadi — desktop
// ilovaning auto-update manifestidan. Shu sababli yangi .exe/.dmg serverga
// qo'yilganda sayt o'zi yangi versiyani ko'rsatadi, frontend'ni qayta yig'ish
// shart emas.
//
// Kartalar ATAYLAB ma'lumotdan quriladi, qo'lda takrorlanmaydi: platforma
// qo'shilganda (masalan Linux) faqat PLATFORMS ro'yxatiga bir qator qo'shiladi.
//
// Manifest o'qilmasa yoki platforma uchun fayl bo'lmasa — o'sha karta
// o'chirilgan holatda qoladi va sabab yoziladi. Sahifa baribir ochilaveradi.
//
// Ikki ko'rinish, ma'lumot bitta:
//   full    - sarlavha, izoh va kartalar ro'yxati (chatdagi "Desktop ilova" oynasi);
//   compact - xush kelibsiz sahifasi ostidagi jim qator: yorliq + ikki kichik plitka.

import { onMounted, onUnmounted, ref, computed, useId } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download } from 'lucide-vue-next'
import {
  assetFor,
  detectPlatform,
  fetchDesktopRelease,
  formatSize,
  setupUrl,
  type DesktopRelease,
  type DesktopSetup,
  type PlatformKey,
} from '../api/download.api'
// Brend belgilari lucide'da yo'q - eski to'plamdan.
import { AppleIcon, WindowsIcon } from '../icons'
import VTooltip from '../ui/VTooltip.vue'

withDefaults(defineProps<{ variant?: 'full' | 'compact' }>(), { variant: 'full' })

const { t, locale } = useI18n({ useScope: 'global' })
const titleId = useId()

const release = ref<DesktopRelease | null>(null)
const loading = ref(true)
const controller = new AbortController()

onMounted(async () => {
  release.value = await fetchDesktopRelease(controller.signal)
  loading.value = false
})
// Foydalanuvchi manifest kelgunicha sahifadan ketsa, so'rovni bekor qilamiz.
onUnmounted(() => controller.abort())

const PLATFORMS: { key: PlatformKey; name: string; icon: Component; reqKey: string }[] = [
  { key: 'windows', name: 'Windows', icon: WindowsIcon, reqKey: 'downloadWindowsReq' },
  { key: 'macos', name: 'macOS', icon: AppleIcon, reqKey: 'downloadMacReq' },
]

// Foydalanuvchining OS'i birinchi turadi. Aniqlanmasa tartib o'zgarmaydi —
// ikkala karta baribir ko'rinadi, ya'ni noto'g'ri taxmin hech narsani to'smaydi.
const detected = detectPlatform()

interface Card {
  key: PlatformKey
  name: string
  icon: Component
  req: string
  asset: DesktopSetup | null
  href: string | undefined
  meta: string
}

const cards = computed<Card[]>(() => {
  const built = PLATFORMS.map((platform): Card => {
    const asset = release.value ? assetFor(release.value, platform.key) : null
    let req = t(platform.reqKey)
    // min_os manifestdan keladi — "macOS 11.0+" tarjima talab qilmaydi
    // (faqat atoqli ot va raqam), shuning uchun alohida kalit ochilmadi.
    if (asset?.min_os) req = `macOS ${asset.min_os}+ · ${req}`

    let meta = ''
    if (asset && release.value) {
      const size = formatSize(asset.size, locale.value)
      const version = t('downloadVersion', { version: release.value.version })
      meta = size ? `${version} · ${size}` : version
    }

    return {
      key: platform.key,
      name: platform.name,
      icon: platform.icon,
      req,
      asset,
      href: asset ? setupUrl(asset) : undefined,
      meta,
    }
  })

  if (!detected) return built
  return [...built].sort((a, b) => Number(b.key === detected) - Number(a.key === detected))
})

// Uch xil sabab, uch xil matn: hali tekshirilmoqda / manifest o'qilmadi /
// manifest keldi-yu bu platforma unda yo'q.
const offStatus = computed(() =>
  loading.value ? t('downloadChecking') : release.value ? t('comingSoon') : t('downloadUnavailable'),
)
</script>

<template>
  <!-- Fayli bor platforma: haqiqiy <a download>. Havolani ATAYLAB <a> sifatida
       qoldiramiz - o'ng tugma "Save link as" ishlaydi va yuklanish JS'ga bog'liq
       bo'lmaydi. Fayli yo'q platforma: <button> emas, <div aria-disabled> -
       bosiladigan narsaga o'xshamasligi kerak. -->
  <section v-if="variant === 'compact'" class="dlc" :aria-labelledby="titleId">
    <h2 :id="titleId" class="dlc__label">{{ t('shell.desktop.title') }}</h2>
    <div class="dlc__tiles">
      <template v-for="card in cards" :key="card.key">
        <VTooltip :text="card.req" placement="top">
          <a
            v-if="card.href"
            class="dlc__tile"
            :href="card.href"
            download
            :aria-label="`${t('downloadCta')} — ${card.name}, ${card.meta}`"
          >
            <component :is="card.icon" class="dlc__os" :size="15" aria-hidden="true" />
            <span class="dlc__name">{{ card.name }}</span>
            <span class="dlc__meta">{{ card.meta }}</span>
            <Download class="dlc__dl" :size="14" :stroke-width="1.75" aria-hidden="true" />
          </a>
          <div v-else class="dlc__tile dlc__tile--off" aria-disabled="true">
            <component :is="card.icon" class="dlc__os" :size="15" aria-hidden="true" />
            <span class="dlc__name">{{ card.name }}</span>
            <span class="dlc__meta">{{ offStatus }}</span>
          </div>
        </VTooltip>
      </template>
    </div>
  </section>

  <section v-else class="dl" :aria-labelledby="titleId">
    <h2 :id="titleId" class="dl__title">{{ t('downloadTitle') }}</h2>
    <p class="dl__sub">{{ t('downloadSub') }}</p>

    <div class="dl__cards">
      <template v-for="card in cards" :key="card.key">
        <a
          v-if="card.href"
          class="dl__card dl__card--ready"
          :href="card.href"
          download
          :aria-label="`${t('downloadCta')} — ${card.name}, ${card.meta}`"
        >
          <span class="dl__os"><component :is="card.icon" :size="card.key === 'macos' ? 17 : 18" /></span>
          <span class="dl__body">
            <span class="dl__name">{{ card.name }}</span>
            <span class="dl__req">{{ card.req }}</span>
          </span>
          <span class="dl__action">
            <span class="dl__meta">{{ card.meta }}</span>
            <Download :size="16" :stroke-width="1.75" aria-hidden="true" />
          </span>
        </a>

        <div v-else class="dl__card dl__card--off" aria-disabled="true">
          <span class="dl__os"><component :is="card.icon" :size="card.key === 'macos' ? 17 : 18" /></span>
          <span class="dl__body">
            <span class="dl__name">{{ card.name }}</span>
            <span class="dl__req">{{ card.req }}</span>
          </span>
          <span class="dl__action dl__action--muted">{{ offStatus }}</span>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
/* ---------- compact: xush kelibsiz sahifasi ostidagi jim qator ---------- */
.dlc {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--s-2) var(--s-4);
  min-width: 0;
}
.dlc__label {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.dlc__tiles {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--s-2);
  min-width: 0;
}
.dlc__tile {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  height: 36px;
  padding: 0 var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  color: var(--text);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
  text-decoration: none;
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  a.dlc__tile:hover {
    background: var(--fill);
    border-color: var(--line-strong);
  }
}
a.dlc__tile:active {
  background: var(--fill-hover);
}
.dlc__os {
  flex-shrink: 0;
  color: var(--text-2);
}
.dlc__meta {
  color: var(--text-3);
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}
.dlc__dl {
  flex-shrink: 0;
  color: var(--text-2);
}
.dlc__tile--off {
  color: var(--text-3);
  cursor: default;
}
.dlc__tile--off .dlc__os {
  color: var(--text-4);
}
/* Telefon/planshetda desktop o'rnatuvchisi befoyda - qator ko'rsatilmaydi. */
@media (max-width: 1119.98px) and (pointer: coarse) {
  .dlc {
    display: none;
  }
}

/* ---------- full: chatdagi "Desktop ilova" oynasi ---------- */
.dl {
  width: 100%;
  min-width: 0;
}
.dl__title {
  color: var(--text);
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.dl__sub {
  margin-top: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.dl__cards {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  margin-top: var(--s-5);
}
.dl__card {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-height: 60px;
  padding: var(--s-3) var(--s-4) var(--s-3) var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  color: var(--text);
  text-align: left;
  text-decoration: none;
}
.dl__card--ready {
  transition:
    background-color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .dl__card--ready:hover {
    background: var(--fill);
    border-color: var(--line-strong);
  }
}
.dl__card--ready:active {
  background: var(--fill-hover);
}
.dl__os {
  display: grid;
  place-items: center;
  flex: none;
  width: 36px;
  height: 36px;
  border-radius: var(--r-md);
  background: var(--fill);
  color: var(--text);
}
.dl__body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.dl__name {
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 600;
}
.dl__req {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.dl__action {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  flex: none;
  color: var(--text);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  white-space: nowrap;
}
.dl__meta {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
/* O'chirilgan karta: bor, lekin bosilmaydi. Kontrast pasaytiriladi, yo'qotilmaydi -
   "yaqinda" ni o'qib bo'lishi kerak. */
.dl__card--off {
  color: var(--text-3);
}
.dl__card--off .dl__os {
  color: var(--text-4);
}
.dl__card--off .dl__name {
  color: var(--text-2);
}
.dl__action--muted {
  color: var(--text-3);
  font-weight: 400;
}
@media (max-width: 519.98px) {
  /* Tor ekranda hajm/versiya matni nomni siqib qo'ymasligi uchun pastga tushadi. */
  .dl__card {
    flex-wrap: wrap;
  }
  .dl__action {
    width: 100%;
    padding-left: calc(36px + var(--s-3));
  }
}
</style>
