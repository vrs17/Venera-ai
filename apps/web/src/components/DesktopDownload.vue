<script setup lang="ts">
// Splash sahifasidagi desktop yuklab olish bloki: Windows va macOS.
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
// o'chirilgan holatda qoladi va sabab yoziladi. Splash baribir ochilaveradi.

import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
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

const PLATFORMS: { key: PlatformKey; name: string; icon: unknown; reqKey: string }[] = [
  { key: 'windows', name: 'Windows', icon: WindowsIcon, reqKey: 'downloadWindowsReq' },
  { key: 'macos', name: 'macOS', icon: AppleIcon, reqKey: 'downloadMacReq' },
]

// Foydalanuvchining OS'i birinchi turadi. Aniqlanmasa tartib o'zgarmaydi —
// ikkala karta baribir ko'rinadi, ya'ni noto'g'ri taxmin hech narsani to'smaydi.
const detected = detectPlatform()

interface Card {
  key: PlatformKey
  name: string
  icon: unknown
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
</script>

<template>
  <section class="dl" :aria-label="t('downloadTitle')">
    <h2 class="dl__title">{{ t('downloadTitle') }}</h2>
    <p class="dl__sub">{{ t('downloadSub') }}</p>

    <div class="dl__cards">
      <!-- Fayli bor platforma: haqiqiy <a download>. Havolani ATAYLAB <a>
           sifatida qoldiramiz - o'ng tugma "Save link as" ishlaydi va yuklanish
           JS'ga bog'liq bo'lmaydi.
           Fayli yo'q platforma: <button> emas, <div aria-disabled> - bosiladigan
           narsaga o'xshamasligi kerak. -->
      <template v-for="card in cards" :key="card.key">
        <a
          v-if="card.href"
          class="dl__card dl__card--ready"
          :href="card.href"
          download
          :aria-label="`${t('downloadCta')} — ${card.name}, ${card.meta}`"
        >
          <span class="dl__os"><component :is="card.icon" :size="card.key === 'macos' ? 19 : 20" /></span>
          <span class="dl__body">
            <span class="dl__name">{{ card.name }}</span>
            <span class="dl__req">{{ card.req }}</span>
          </span>
          <span class="dl__action">
            <DownloadIcon :size="16" />
            <span class="dl__meta">{{ card.meta }}</span>
          </span>
        </a>

        <div v-else class="dl__card dl__card--off" aria-disabled="true">
          <span class="dl__os"><component :is="card.icon" :size="card.key === 'macos' ? 19 : 20" /></span>
          <span class="dl__body">
            <span class="dl__name">{{ card.name }}</span>
            <span class="dl__req">{{ card.req }}</span>
          </span>
          <span class="dl__action dl__action--muted">
            <!-- Uch xil sabab, uch xil matn: hali tekshirilmoqda / manifest
                 o'qilmadi / manifest keldi-yu bu platforma unda yo'q. -->
            {{
              loading
                ? t('downloadChecking')
                : release
                  ? t('comingSoon')
                  : t('downloadUnavailable')
            }}
          </span>
        </div>
      </template>
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
