// Mini App sozlamalari (faqat shu qurilmada).
//
// "Javobni ovoz bilan o'qish" - DEFAULT O'CHIQ (foydalanuvchi qarori, 2026-10-04):
// telefonda Mini App ko'pincha jamoat joyida ochiladi va kutilmagan ovoz noqulay;
// yoqilmaguncha javob ostida karnay tugmasi ham chiqmaydi - qator tinchroq. Faqat
// ochiq '1' yoqadi: xotira tozalansa yana o'chiq.

import { ref, watch } from 'vue'

const KEY = 'venera_tg_read_aloud'

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

const readAloud = ref(read())
watch(readAloud, (on) => {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* saqlanmaydi - shu sessiyada ishlaydi */
  }
})

export function usePrefs() {
  return { readAloud }
}
