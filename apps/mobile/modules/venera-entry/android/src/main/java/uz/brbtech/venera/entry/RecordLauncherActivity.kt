package uz.brbtech.venera.entry

import android.app.Activity
import android.content.ActivityNotFoundException
import android.os.Bundle

/**
 * "Yozish" launcher belgisi (spec 2.1, 2.2). Samsung yon tugmasi
 * (Ikki marta bosish > Ilovani ochish) shu belgini ochadi.
 *
 * ALMASHTIRGICH (plitka kabi): yozuv ketmayotgan bo'lsa - boshlaydi, ketayotgan
 * bo'lsa - TO'XTATADI. Ya'ni yon tugmani ikki marta bosish yozuvni boshlaydi,
 * yana ikki marta bosish uni tugatadi (Plaud'ning bitta tugmasi kabi).
 *
 * Hech narsa chizmaydi: ishonchli kalit bilan deep link yuboradi va darhol
 * yopiladi. Asosiy activity ko'rinadi - Android mikrofon foreground
 * service'ini faqat ko'rinib turgan activity'dan boshlashga ruxsat beradi.
 */
class RecordLauncherActivity : Activity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    try {
      startActivity(EntryPrefs.recordIntent(this, "launcher", stop = EntryPrefs.isRecording(this)))
    } catch (_: ActivityNotFoundException) {
      // Asosiy ilova o'chirilgan/yo'q - qiladigan ish yo'q.
    }
    finish()
  }
}
