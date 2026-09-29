// "Orqaga" havolasi (savol izi -> ro'yxat, xabar -> quti).
//
// Havola oddiy havola bo'lib qoladi (o'rta tugma, "manzilni nusxalash" ishlaydi), lekin
// oldingi tarix yozuvi AYNAN o'sha ro'yxat bo'lsa, oddiy bosish brauzerning o'z
// "orqaga"siga aylanadi: aks holda ro'yxat -> iz -> ro'yxat -> iz ... tarix to'lib,
// brauzer tugmasi admin'ni aylanaga tushirardi.
//
//   <VButton :to="backTo" @click.capture="onBack">
//
// `capture`: RouterLink o'z o'tishini bosishning o'zida boshlaydi - bizning qaror undan
// OLDIN qabul qilinishi kerak (`preventDefault` - RouterLink o'tishni o'tkazib yuboradi).

import { useRouter } from 'vue-router'

export function useBackLink(isTarget: (path: string) => boolean): (e: MouseEvent) => void {
  const router = useRouter()
  return (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const back = (window.history.state as { back?: unknown } | null)?.back
    if (typeof back !== 'string' || !isTarget(back.split(/[?#]/)[0])) return
    e.preventDefault()
    router.back()
  }
}
