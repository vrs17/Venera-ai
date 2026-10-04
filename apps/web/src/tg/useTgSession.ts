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
//      so'ramasdan qayta kirish. BACKEND'DA HALI YO'Q: 404/405/501 - jim o'tkazib
//      yuboriladi. Javob shakli POST /auth/login niki bilan bir xil (LoginResponse).
//   3. Kirish ekrani (HRM/CRM login + parol, Keycloak). Kirgach Telegram ulanadi -
//      keyingi ochilishlar 1- yoki 2-yo'ldan o'tadi.
//
// TARMOQ YO'Q (token bor, lekin server javob bermadi): token O'CHIRILMAYDI va kirish
// ekrani ko'rsatilmaydi - "ulanib bo'lmadi, qayta urinish" ekrani. Aks holda metroda
// ochilgan Mini App odamni parol so'rashga majburlardi.

import { readonly, ref } from 'vue'
import * as authApi from '../api/auth.api'
import { ApiError, apiFetch, clearToken, getToken, setToken } from '../api/http'
import { useAuth } from '../composables/useAuth'
import { usePro } from '../composables/usePro'
import { useChats } from '../composables/useChats'
import { clearSources } from '../sourcesCache'
import { toast } from '../ui/useToast'
import type { LoginResponse } from '../types'
import { initData } from './telegram'

export type SessionPhase = 'boot' | 'login' | 'ready' | 'offline'

const phase = ref<SessionPhase>('boot')
/** "Qayta ulash" dan keyin kirish ekranida login tayyor turadi - faqat parol. */
const lastLogin = ref('')

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
    return true
  } catch (err) {
    // 404/405/501 - hali yo'q; 400/401/403 - ulanmagan yoki imzo eskirgan. Ikkalasida
    // ham kirish ekrani to'g'ri javob.
    if (!missing(err)) console.debug('[tg] telegram/session', err instanceof ApiError ? err.status : err)
    return false
  }
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
  phase.value = 'login'
}

/** "Qayta ulash" (HRM/CRM tokeni yo'q yoki eskirgan - javob kartasidagi tugma).
 *  Keycloak tokenlari faqat parol bilan kirishda olinadi: sessiya yopiladi va kirish
 *  ekrani ochiladi, login oldindan to'ldirilgan. Telegram ulanishi UZILMAYDI - u shu
 *  hisobniki bo'lib qoladi, kirgach jim yangilanadi. */
async function reconnect(): Promise<void> {
  const auth = useAuth()
  lastLogin.value = auth.user.value?.email ?? ''
  await auth.logout()
  forgetLocalState()
  phase.value = 'login'
}

/** Ish paytida 401 keldi (sessiya serverda bekor qilingan): avval Telegram orqali jim
 *  qayta kirishga urinamiz, bo'lmasa - kirish ekrani. */
async function expire(): Promise<void> {
  clearToken()
  useAuth().user.value = null
  if (await telegramSession()) return
  forgetLocalState()
  phase.value = 'login'
}

export function useTgSession() {
  return { phase: readonly(phase), lastLogin: readonly(lastLogin), boot, login, logout, reconnect, expire }
}
