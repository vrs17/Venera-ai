package uz.brbtech.venera.entry

import android.accessibilityservice.AccessibilityService
import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.SystemClock
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent

/**
 * Ovozni PASAYTIRISH tugmasini ketma-ket ikki marta bosish - yozuvni boshlash, yana
 * ikki marta - to'xtatish (yon tugma va plitka bilan bir xil almashtirgich).
 *
 * NEGA "Maxsus imkoniyatlar" xizmati: Android oddiy ilovaga tugma bosishlarini
 * ilovadan TASHQARIDA ko'rsatmaydi (quvvat tugmasini esa umuman hech kimga). Faqat
 * foydalanuvchi o'zi yoqqan AccessibilityService `onKeyEvent` oladi - telefon
 * qaysi markaligidan qat'i nazar.
 *
 * Xizmat FAQAT tugma hodisalarini oladi (`flagRequestFilterKeyEvents`); ekrandagi
 * matnni o'qimaydi (`canRetrieveWindowContent=false`, hodisalar faqat o'z paketimizdan).
 * Bosish ISTE'MOL QILINMAYDI (`false`): ovoz odatdagidek pasayadi - tugmaning o'z
 * ishi buzilmaydi. Hech narsa jurnalga yozilmaydi.
 */
class RecordKeyService : AccessibilityService() {
  private var lastDown = 0L
  private var lastFired = 0L

  override fun onKeyEvent(event: KeyEvent): Boolean {
    if (event.keyCode != KeyEvent.KEYCODE_VOLUME_DOWN) return false
    if (event.action != KeyEvent.ACTION_DOWN || event.repeatCount != 0) return false
    val now = SystemClock.elapsedRealtime()
    if (now - lastFired < COOLDOWN_MS) return false
    if (now - lastDown <= DOUBLE_MS) {
      lastDown = 0L
      lastFired = now
      fire()
    } else {
      lastDown = now
    }
    return false
  }

  private fun fire() {
    try {
      val intent = EntryPrefs.recordIntent(this, "volume", stop = EntryPrefs.isRecording(this))
      intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      startActivity(intent)
    } catch (_: ActivityNotFoundException) {
      // Asosiy ilova yo'q - qiladigan ish yo'q.
    } catch (_: SecurityException) {
      // Tizim fon'dan ochishni rad etdi - jim.
    }
  }

  override fun onAccessibilityEvent(event: AccessibilityEvent?) {
    // Ekran hodisalari kerak emas.
  }

  override fun onInterrupt() {}

  companion object {
    /** Ikki bosish orasidagi eng uzun vaqt (Android'ning ikki marta bosish chegarasiga yaqin). */
    const val DOUBLE_MS = 450L
    /** Ishga tushgandan keyin shuncha vaqt yangi juftlik kutilmaydi (tasodifiy uchinchi bosish). */
    const val COOLDOWN_MS = 1500L
  }
}
