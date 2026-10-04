<script setup lang="ts">
import { defineAsyncComponent, h, onMounted } from 'vue'
import { getToken } from '../api/http'
import { getInitialLocale, setLocale } from '../i18n'
import VToastHost from '../ui/VToast.vue'
import BootScreen from './screens/BootScreen.vue'
import LoginScreen from './screens/LoginScreen.vue'
import { tgUser } from './telegram'
import { useTgSession } from './useTgSession'

/**
 * Ekranlar holat mashinasi: boot -> (login | chat | offline). Router yo'q - Mini
 * App'da manzil satri ham, "orqaga" tarixi ham yo'q (orqaga - Telegram tugmasi,
 * backStack.ts).
 *
 * Chat ekrani alohida bo'lak, lekin uni yuklash SHU ZAHOTI boshlanadi - sessiya
 * tekshirilayotgan paytda parallel. 99% ochilish avtomatik kirish bilan chatga tushadi:
 * bo'lak oxirida emas, /auth/me bilan bir vaqtda keladi.
 *
 * BOOT SKELETI token bor-yo'qligiga qarab: token bor - chat skeleti (ehtimol chatga
 * tushamiz); yo'q - faqat brend belgisi, KIRISH ekranidagi joyida. Birinchi marta
 * ochgan odam ilova "ochilib", keyin kirish formasiga almashganini ko'rmaydi - belgi
 * joyida qoladi, forma uning ostida paydo bo'ladi.
 */
const chatChunk = import('./screens/ChatScreen.vue')
// Bo'lak hali kelmagan bo'lsa (sekin tarmoq) - skelet turadi, bo'sh ekran emas.
const ChatScreen = defineAsyncComponent({
  loader: () => chatChunk,
  loadingComponent: { render: () => h(BootScreen, { variant: 'chat' }) },
  delay: 0,
})

const { phase, boot } = useTgSession()
const bootVariant = getToken() ? 'chat' : 'brand'

// Til: odam o'zi tanlamagan bo'lsa va Telegram'i ruscha bo'lsa - ruscha. Boshqa hollarda
// o'zbekcha (standart): ko'p xodimning Telegram'i inglizcha, lekin bu "inglizcha
// o'qiyman" degani emas.
function adoptTelegramLocale() {
  let saved: string | null = null
  try {
    saved = localStorage.getItem('venera_locale')
  } catch {
    /* xotira yo'q */
  }
  if (!saved && tgUser?.language_code?.toLowerCase().startsWith('ru') && getInitialLocale() === 'uz') setLocale('ru')
}

onMounted(() => {
  adoptTelegramLocale()
  void boot()
})
</script>

<template>
  <div class="tg-app">
    <!-- Ustma-ust almashadi (out-in emas): brend belgisi kirish ekranidagi bilan bir
         joyda - bo'sh kadr bo'lmaydi, belgi "qoladi". -->
    <Transition name="tg-screen">
      <BootScreen
        v-if="phase === 'boot' || phase === 'offline'"
        key="boot"
        :variant="bootVariant"
        :offline="phase === 'offline'"
        @retry="boot"
      />
      <LoginScreen v-else-if="phase === 'login'" key="login" :from-brand="bootVariant === 'brand'" />
      <ChatScreen v-else key="chat" />
    </Transition>
  </div>
  <VToastHost />
</template>

<style scoped>
.tg-screen-enter-active {
  transition: opacity var(--dur-2) var(--ease-out);
}
.tg-screen-leave-active {
  position: absolute;
  inset: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.tg-screen-enter-from,
.tg-screen-leave-to {
  opacity: 0;
}
</style>
