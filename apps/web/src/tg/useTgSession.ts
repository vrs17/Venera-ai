// Mini App sessiyasi: "bir marta kiring, keyin avtomatik".
//
// OCHILISHDA TARTIB (har biri yiqilsa - keyingisi):
//
//   1. Saqlangan token (`venera_token`, web bilan bir xil kalit) -> GET /auth/me.
//      Eng arzon yo'l: tarmoqqa bitta so'rov, yangi sessiya yaratilmaydi. Muvaffaqiyatda
//      Telegram ulanishi jim yangilanadi (POST /telegram/link) - bot ham shu hisobni
//      taniydi va ulanish muddati uzayadi.
//   2. Telegram imzosi -> POST /telegram/session {initData} -> {token, user}.
//      Token yo'qolgan bo'lsa (iOS WebView xotirasini tozalaydi, boshqa telefon) parol
//      so'ramasdan qayta kirish. Javob shakli POST /auth/login niki (LoginResponse).
//      Server javoblari (api/v1/telegram.py):
//        401  imzo soxta/eskirgan (600 s), ulanmagan, ulanish muddati o'tgan - ATAYLAB
//             bitta umumiy xabar; kirish ekrani, izohsiz
//        403  hisob bloklangan - kirish ekrani BLOK XABARI bilan: aks holda odam
//             parolni terib, shundan keyingina sababini bilardi
//        429  daqiqasiga 6 urinishdan oshdi; 501 - bot sozlanmagan (dev) - kirish ekrani
//      404/405 - eski backend (endpoint yo'q) - ham jim kirish ekrani.
//   3. Kirish ekrani (HRM/CRM login + parol, Keycloak). Kirgach Telegram ulanadi -
//      keyingi ochilishlar 1- yoki 2-yo'ldan o'tadi.
//
// TARMOQ YO'Q (token bor, lekin server javob bermadi): token O'CHIRILMAYDI va kirish
// ekrani ko'rsatilmaydi - "ulanib bo'lmadi, qayta urinish" ekrani. Aks holda metroda
// ochilgan Mini App odamni parol so'rashga majburlardi.

import { readonly, ref } from 'vue'
import * as authApi from '../api/auth.api'
import { authErrorKind } from '../api/errors'
import { ApiError, apiFetch, clearToken, getToken, setToken } from '../api/http'
import { useAuth } from '../composables/useAuth'
import { usePro } from '../composables/usePro'
import { useChats } from '../composables/useChats'
import { clearSources } from '../sourcesCache'
import { toast } from '../ui/useToast'
import type { LoginResponse } from '../types'
import { initData, openLink } from './telegram'

export type SessionPhase = 'boot' | 'login' | 'ready' | 'offline'

const phase = ref<SessionPhase>('boot')
/** "Qayta ulash" dan keyin kirish ekranida login tayyor turadi - faqat parol. */
const lastLogin = ref('')
/** Kirish ekrani ochilishdanoq ko'rsatadigan sabab. Hozircha faqat blok: admin
 *  bloklagan odamga bo'sh forma ko'rsatsak, u parolni terib, keyingina "bloklangan"
 *  ni ko'rardi. Odam muvaffaqiyatli kirsa yoki yozishni boshlasa - yo'qoladi. */
export type SessionNotice = 'blocked' | null
const notice = ref<SessionNotice>(null)

/** Endpoint hali yo'q yoki bot sozlanmagan - xato emas, keyingi yo'lga o'tamiz. */
function missing(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 405 || err.status === 501)
}

/** Sessiya haqiqatan yaroqsiz (eskirgan, bekor qilingan) - tokenni tashlash mumkin.
 *  Boshqa hamma xato (tarmoq, 5xx) - token qoladi. */
function rejected(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.status === 403)
}

/** Bot chatini shu hisobga ulaydi / muddatini yangilaydi. Jim: bot o'chiq (501) yoki
 *  imzo eskirgan bo'lsa ham ilova ishlayveradi. */
async function linkTelegram(): Promise<void> {
  if (!initData) return
  try {
    await apiFetch('/api/v1/telegram/link', { method: 'POST', body: JSON.stringify({ initData }) })
  } catch {
    /* ixtiyoriy qadam */
  }
}

async function telegramSession(): Promise<boolean> {
  if (!initData) return false
  try {
    const res = await apiFetch<LoginResponse | undefined>('/api/v1/telegram/session', {
      method: 'POST',
      body: JSON.stringify({ initData }),
    })
    if (!res?.token || !res.user) return false
    setToken(res.token)
    const auth = useAuth()
    auth.user.value = res.user
    auth.initialized.value = true
    notice.value = null
    return true
  } catch (err) {
    // 403 - imzo va ulanish to'g'ri, lekin admin bloklagan: sababni darhol aytamiz.
    // Qolgani (401 ulanmagan/eskirgan, 429, 501, eski backend'da 404/405) - izohsiz
    // kirish ekrani: server sababni ataylab aytmaydi.
    if (err instanceof ApiError && err.status === 403) notice.value = 'blocked'
    else if (!missing(err)) console.debug('[tg] telegram/session', err instanceof ApiError ? err.status : err)
    return false
  }
}

/** /auth/me "Hisob bloklangan" (401) degan bo'lsa - Telegram'siz ochilishda ham (dev,
 *  initData yo'q) kirish ekrani sababni aytsin. */
function noteBlocked(err: unknown): void {
  if (authErrorKind(err) === 'blocked') notice.value = 'blocked'
}

async function boot(): Promise<void> {
  phase.value = 'boot'
  const auth = useAuth()
  if (getToken()) {
    try {
      auth.user.value = await authApi.me()
      auth.initialized.value = true
      phase.value = 'ready'
      void linkTelegram()
      return
    } catch (err) {
      if (!rejected(err)) {
        // Server yetib bo'lmadi - token saqlanadi, odam "qayta urinish" ni bosadi.
        phase.value = 'offline'
        return
      }
      noteBlocked(err)
      clearToken()
      auth.user.value = null
    }
  }
  if (await telegramSession()) {
    phase.value = 'ready'
    return
  }
  phase.value = 'login'
}

/** Kirish ekranidan. Xato `ApiError` sifatida qaytadi - ekran o'zi ko'rsatadi. */
async function login(username: string, password: string): Promise<LoginResponse> {
  const auth = useAuth()
  const res = await auth.login(username, password)
  if (res.passwordChangeRequired) {
    // Faqat zahira (lokal) hisoblarda: Mini App'da parol almashtirish oynasi yo'q.
    // Sessiyani qoldirsak chat 403 bilan yiqilardi - tozalaymiz.
    clearToken()
    auth.user.value = null
    return res
  }
  await linkTelegram()
  notice.value = null
  phase.value = 'ready'
  return res
}

/** Shu odamning brauzerdagi izlari: suhbatlar ro'yxati, manbalar keshi (HRM/CRM
 *  ma'lumoti bo'lishi mumkin), Pro byudjeti, toast'lar. */
function forgetLocalState(): void {
  usePro().reset()
  useChats().reset()
  clearSources()
  toast.clear()
}

/** "Chiqish": avval Telegram uziladi (bot boshqa odamga javob bermasin), keyin
 *  sessiya. Server yiqilsa ham lokal holat tozalanadi. */
async function logout(): Promise<void> {
  if (initData) {
    try {
      await apiFetch('/api/v1/telegram/unlink', { method: 'POST', body: JSON.stringify({ initData }) })
    } catch {
      /* baribir chiqamiz */
    }
  }
  await useAuth().logout()
  forgetLocalState()
  lastLogin.value = ''
  notice.value = null
  phase.value = 'login'
}

/** HRM yoki CRM ulanmagan (javob kartasidagi tugma). Ikkalasi ham VEB ilovada
 *  tiklanadi: HRM - "+" (Ulanishlar) menyusida login va parol bilan, CRM - BRB-Tech ID
 *  bilan kirishning o'zida (o'zi ulanadi). Token shu odamning HAMMA kanaliga (Mini App,
 *  bot) xizmat qiladi. Shuning uchun sessiya YOPILMAYDI (avval yopilardi va odam
 *  Keycloak paroli endi ishlamaydigan kirish ekranida qolardi) - veb ilova tashqi
 *  brauzerda ochiladi. */
async function reconnect(): Promise<void> {
  // SSO yoqilgan bo'lsa havola vebda BRB-Tech ID kirishini BOSHLAYDI (`/auth/sso/start`): odam vebga
  // allaqachon kirgan bo'lsa ham kirish qaytadan o'tadi va CRM shu kirishda o'zi ulanadi - ilovaning
  // bosh sahifasini ochish esa hech narsani ulamasdi. HRM uchun ham to'g'ri joy: kirgach «+» -> Ulanishlar.
  const sso = await useAuth().loadSsoConfig()
  const origin = window.location.origin
  openLink(sso.enabled ? `${origin}${sso.startPath}?channel=web` : `${origin}/`)
}

/** Ish paytida 401 keldi (sessiya serverda bekor qilingan yoki hisob bloklangan):
 *  avval Telegram orqali jim qayta kirishga urinamiz, bo'lmasa - kirish ekrani.
 *  `err` - o'sha 401: "bloklangan" bo'lsa kirish ekrani sababni aytadi. */
async function expire(err?: unknown): Promise<void> {
  if (err !== undefined) noteBlocked(err)
  clearToken()
  useAuth().user.value = null
  if (await telegramSession()) return
  forgetLocalState()
  phase.value = 'login'
}

export function useTgSession() {
  return {
    phase: readonly(phase),
    lastLogin: readonly(lastLogin),
    notice: readonly(notice),
    boot,
    login,
    logout,
    reconnect,
    expire,
  }
}
