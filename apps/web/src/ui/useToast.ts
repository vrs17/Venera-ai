import { reactive, readonly } from 'vue'

/* Global bildirishnomalar navbati.

   Komponentdan tashqarida ham chaqirsa bo'ladi (`toast.show(...)` - masalan, API
   xatosida composable ichidan). Ekranga <VToastHost/> chizadi; u ilovada BIR marta
   o'rnatiladi (App.vue).

   Vaqt: standart 4 s. Sichqoncha toast ustida turganda yoki sahifa yashirin bo'lsa
   hisob TO'XTAYDI (WCAG 2.2.1 - foydalanuvchi o'qib ulgurishi kerak), keyin qolgan
   vaqtdan davom etadi. Ekranda ko'pi bilan 3 ta - eskisi o'rnini bo'shatadi. */

export type ToastTone = 'neutral' | 'good' | 'crit'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastOptions {
  message: string
  tone?: ToastTone
  action?: ToastAction
  /** ms; 0 - o'zi yopilmaydi. */
  duration?: number
  /** Bir xil id bilan qayta chaqirilsa - eskisi yangilanadi (takrorlanmaydi). */
  id?: string
}

export interface ToastItem {
  id: string
  message: string
  tone: ToastTone
  action?: ToastAction
  duration: number
}

const MAX_VISIBLE = 3
const DEFAULT_DURATION = 4000

const state = reactive<{ items: ToastItem[] }>({ items: [] })

interface Timer {
  handle: ReturnType<typeof setTimeout> | undefined
  remaining: number
  startedAt: number
}
const timers = new Map<string, Timer>()
// To'xtatish sabablari alohida: sichqoncha ustida + sahifa yashirin bir vaqtda bo'lsa,
// bittasi tugashi bilan hisob qayta boshlanib ketmasin.
const pauseReasons = new Set<string>()
let paused = false
let seq = 0

function arm(id: string) {
  const tm = timers.get(id)
  if (!tm || paused || tm.remaining <= 0) return
  clearTimeout(tm.handle)
  tm.startedAt = Date.now()
  tm.handle = setTimeout(() => dismiss(id), tm.remaining)
}

function show(input: string | ToastOptions): string {
  const opts: ToastOptions = typeof input === 'string' ? { message: input } : input
  const id = opts.id ?? `t${++seq}`
  const item: ToastItem = {
    id,
    message: opts.message,
    tone: opts.tone ?? 'neutral',
    action: opts.action,
    duration: opts.duration ?? DEFAULT_DURATION,
  }
  const existing = state.items.findIndex((x) => x.id === id)
  if (existing >= 0) state.items.splice(existing, 1, item)
  else state.items.push(item)

  while (state.items.length > MAX_VISIBLE) dismiss(state.items[0].id)

  clearTimeout(timers.get(id)?.handle)
  if (item.duration > 0) {
    timers.set(id, { handle: undefined, remaining: item.duration, startedAt: Date.now() })
    arm(id)
  } else timers.delete(id)
  syncVisibility()
  return id
}

function dismiss(id: string) {
  const tm = timers.get(id)
  if (tm) clearTimeout(tm.handle)
  timers.delete(id)
  const i = state.items.findIndex((x) => x.id === id)
  if (i >= 0) state.items.splice(i, 1)
  syncVisibility()
}

function clear() {
  for (const id of [...timers.keys()]) dismiss(id)
  state.items.splice(0)
}

/** Hamma taymerlarni to'xtatish (hover / fokus / sahifa yashirin). */
function pause(reason = 'manual') {
  pauseReasons.add(reason)
  if (paused) return
  paused = true
  const now = Date.now()
  for (const tm of timers.values()) {
    clearTimeout(tm.handle)
    tm.handle = undefined
    tm.remaining = Math.max(0, tm.remaining - (now - tm.startedAt))
  }
}

function resume(reason = 'manual') {
  pauseReasons.delete(reason)
  if (!paused || pauseReasons.size) return
  paused = false
  // Kamida 1 s qolsin: sichqonchani olib ketishi bilan yo'qolib qolmasin.
  for (const [id, tm] of timers) {
    tm.remaining = Math.max(tm.remaining, 1000)
    arm(id)
  }
}

// Sahifa yashirinsa hisob to'xtaydi. Tinglovchi faqat taymerli toast bor paytda
// ulanadi - ekranda hech narsa bo'lmasa, global hodisaga ilinib turmaymiz.
function onVisibility() {
  if (document.hidden) pause('hidden')
  else resume('hidden')
}
let watchingVisibility = false
function syncVisibility() {
  if (typeof document === 'undefined') return
  const need = timers.size > 0
  if (need === watchingVisibility) return
  watchingVisibility = need
  if (need) {
    document.addEventListener('visibilitychange', onVisibility)
    if (document.hidden) pause('hidden')
  } else {
    document.removeEventListener('visibilitychange', onVisibility)
    resume('hidden')
  }
}

export const toast = {
  show,
  success: (message: string, opts: Omit<ToastOptions, 'message' | 'tone'> = {}) =>
    show({ ...opts, message, tone: 'good' }),
  error: (message: string, opts: Omit<ToastOptions, 'message' | 'tone'> = {}) =>
    show({ ...opts, message, tone: 'crit' }),
  dismiss,
  clear,
  pause,
  resume,
}

export function useToast() {
  return { toasts: readonly(state.items), ...toast }
}
