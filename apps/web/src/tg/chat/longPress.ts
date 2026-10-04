// Uzoq bosish -> amallar menyusi (xabar: nusxa, belgilash, xabar berish; tarix qatori:
// nomini o'zgartirish, o'chirish).
//
// Telegram foydalanuvchisi xabarni ushlab turishga o'rgangan - bu yerda ham shunday.
// Android WebView uzoq bosishda `contextmenu` hodisasini beradi (u ham ushlanadi, aks
// holda tizim menyusi chiqardi); iOS bermaydi - u yerda taymer.
//
// USHLAB TURGANDA JAVOB. 450 ms davomida hech narsa o'zgarmasa, odam "ishlamayapti"
// deb barmog'ini erta oladi. Shuning uchun 120 ms dan keyin element `is-pressing`
// sinfini oladi: CSS uni 330 ms da biroz kichraytiradi va fonini bo'yaydi - aynan
// taymer tugaganda (120 + 330 = 450) to'liq bo'ladi va shu lahzada menyu ochiladi
// (tebranish ham shu lahzada).
//
// Barmoq siljisa (aylantirish) - bekor: ro'yxatni aylantirayotgan odamga menyu ochilmasin.
// Menyu ochilgandan keyingi `click` yutiladi - barmoq qo'yib yuborilganda tagidagi
// iqtibos chipi yoki havola "bosilib" ketmasin.

const HOLD_MS = 450
const PRESS_FEEDBACK_MS = 120
const SLOP_PX = 10

export function longPress(onFire: (el: HTMLElement, e: Event) => void) {
  let timer = 0
  let feedback = 0
  let startX = 0
  let startY = 0
  let fired = false
  let target: HTMLElement | null = null

  function clear() {
    window.clearTimeout(timer)
    window.clearTimeout(feedback)
    timer = 0
    feedback = 0
    target?.classList.remove('is-pressing')
  }

  function onPointerDown(e: PointerEvent) {
    // Sichqonchada uzoq bosish odatiy emas - u yerda o'ng tugma (contextmenu).
    if (e.pointerType === 'mouse') return
    fired = false
    startX = e.clientX
    startY = e.clientY
    clear()
    target = e.currentTarget as HTMLElement
    const el = target
    feedback = window.setTimeout(() => el.classList.add('is-pressing'), PRESS_FEEDBACK_MS)
    timer = window.setTimeout(() => {
      timer = 0
      fired = true
      clear()
      onFire(el, e)
    }, HOLD_MS)
  }

  function onPointerMove(e: PointerEvent) {
    if (!timer) return
    if (Math.abs(e.clientX - startX) > SLOP_PX || Math.abs(e.clientY - startY) > SLOP_PX) clear()
  }

  function onContextMenu(e: Event) {
    e.preventDefault()
    if (fired) return
    clear()
    fired = true
    onFire(e.currentTarget as HTMLElement, e)
  }

  function onClickCapture(e: Event) {
    if (!fired) return
    fired = false
    e.preventDefault()
    // Shu elementdagi boshqa tinglovchilar ham (iqtibos chipi ushlagichi) ishlamasin.
    e.stopImmediatePropagation()
  }

  return {
    onPointerdown: onPointerDown,
    onPointermove: onPointerMove,
    onPointerup: clear,
    onPointercancel: clear,
    onPointerleave: clear,
    onContextmenu: onContextMenu,
    onClickCapture,
  }
}
