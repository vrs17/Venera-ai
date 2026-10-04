// Telegram'ning "Orqaga" tugmasi - ochiq oynalar STEKI.
//
// Telegram sarlavhasida bitta tugma bor: yopiq holatda "Yopish" (✕), `BackButton.show()`
// dan keyin "← Orqaga". Mobil foydalanuvchi oynani (tarix, manbalar, sozlamalar) aynan
// shu bilan yopishni kutadi - Android'ning tizim "orqaga" tugmasi ham shunga keladi.
//
// Bir vaqtda bir nechta oyna ochiq bo'lishi mumkin (manbalar ustida "Xabar berish"),
// shuning uchun stek: tugma ENG YUQORIDAGI oynani yopadi; stek bo'sh bo'lsa tugma
// yashirinadi va Telegram yana "Yopish" ni ko'rsatadi. Tinglovchi BITTA (SDK har
// `onClick` ni alohida chaqiradi - har oyna o'zinikini qo'shsa, bitta bosish hammasini
// yopardi).

import { getCurrentScope, onScopeDispose, toValue, watch } from 'vue'
import type { MaybeRefOrGetter } from 'vue'
import { backButton } from './telegram'

const stack: { close: () => void }[] = []
let detach: (() => void) | null = null

function onBack(): void {
  stack[stack.length - 1]?.close()
}

function sync(): void {
  // `has-sheet`: biror oyna ochiq - toast'lar kompozer ustiga emas, ekran pastiga
  // tushadi (oyna kompozerni yopib turibdi; aks holda "Bekor qilish" ro'yxat
  // qatorlari orasida osilib qolardi). styles.css.
  document.documentElement.classList.toggle('has-sheet', stack.length > 0)
  if (stack.length) {
    if (!detach) detach = backButton.onClick(onBack)
    backButton.show()
  } else {
    backButton.hide()
    detach?.()
    detach = null
  }
}

/** `open` true bo'lganda stekka qo'shiladi, false - chiqariladi. Komponent yo'qolsa
 *  ham chiqariladi (yopilmay qolgan oyna tugmani "osib" qoldirmasin). */
export function useBackButton(open: MaybeRefOrGetter<boolean>, close: () => void): void {
  const entry = { close }
  function set(on: boolean) {
    const i = stack.indexOf(entry)
    if (on && i < 0) stack.push(entry)
    if (!on && i >= 0) stack.splice(i, 1)
    sync()
  }
  watch(() => !!toValue(open), set, { immediate: true })
  if (getCurrentScope()) onScopeDispose(() => set(false))
}
