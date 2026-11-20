package uz.brbtech.venera.entry

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ContentResolver
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast

/**
 * "Ulashish -> Barno" (2026-10-10): istalgan ilovadan (Samsung Telefon,
 * Mening fayllarim, Telegram ...) audio fayl(lar)ni qabul qiladi.
 *
 * Hech narsa chizmaydi (shaffof). Oqimlarni SHU YERDA filesDir/imports/ ga
 * nusxalaydi va asosiy ilovani venera-rec://import?files=... bilan ochadi; u yerda
 * tasdiqlash ekrani fayllarni ko'rsatib yuboradi.
 *
 * NIMA UCHUN nusxa shu activity'da: ulashuvchi ilova bergan o'qish ruxsati
 * (FLAG_GRANT_READ_URI_PERMISSION) shu activity yashaguncha amal qiladi - URI'ni
 * JS'ga uzatsak, ilova ochilguncha ruxsat yo'qolishi mumkin edi.
 * NIMA UCHUN alohida oqimda: katta yozuvni asosiy oqimda nusxalash ANR beradi.
 */
class ImportActivity : Activity() {
  private val handler = Handler(Looper.getMainLooper())
  private var slowToast: Toast? = null

  // Nusxa sezilarli vaqt olsa (katta fayl) foydalanuvchi nima bo'layotganini ko'rsin.
  private val showSlow = Runnable {
    slowToast = Toast.makeText(applicationContext, R.string.venera_entry_import_preparing, Toast.LENGTH_LONG)
    slowToast?.show()
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    // Qayta yaratilganda (configChanges'dan tashqari holat) import ikki marta boshlanmasin.
    if (savedInstanceState != null) {
      finish()
      return
    }
    val uris = sharedUris(intent)
    if (uris.isEmpty()) {
      // Masalan, eski ilova file:// bergan - jim yopilmaylik, foydalanuvchi sababini bilsin.
      Toast.makeText(applicationContext, R.string.venera_entry_import_unsupported, Toast.LENGTH_LONG).show()
      finish()
      return
    }
    val app = applicationContext
    handler.postDelayed(showSlow, SLOW_MS)
    Thread({
      val result = try {
        CallImport.importShared(app, uris)
      } catch (_: Throwable) {
        CallImport.SharedImport(emptyList(), uris.size)
      }
      handler.post { deliver(result) }
    }, "barno-import").start()
  }

  override fun onDestroy() {
    handler.removeCallbacks(showSlow)
    super.onDestroy()
  }

  private fun deliver(result: CallImport.SharedImport) {
    handler.removeCallbacks(showSlow)
    slowToast?.cancel()
    val app = applicationContext
    if (result.files.isEmpty()) {
      Toast.makeText(app, R.string.venera_entry_import_unsupported, Toast.LENGTH_LONG).show()
    } else {
      try {
        // Faqat O'Z ilovamizga (setPackage) - boshqa ilova bu havolani ushlay olmaydi.
        app.startActivity(CallImport.importIntent(app, result.files, result.skipped))
      } catch (_: ActivityNotFoundException) {
        // Asosiy activity topilmadi - fayllar imports/ da qoladi, JS keyingi ochilishda tozalaydi.
      }
    }
    if (!isFinishing) finish()
  }

  /** SEND: EXTRA_STREAM; SEND_MULTIPLE: EXTRA_STREAM ro'yxati; ba'zi ilovalar faqat ClipData beradi. */
  private fun sharedUris(intent: Intent?): List<Uri> {
    if (intent == null) return emptyList()
    val out = LinkedHashSet<Uri>()
    when (intent.action) {
      Intent.ACTION_SEND -> streamOf(intent)?.let { out.add(it) }
      Intent.ACTION_SEND_MULTIPLE -> out.addAll(streamsOf(intent))
      else -> return emptyList()
    }
    intent.clipData?.let { clip ->
      for (i in 0 until clip.itemCount) {
        clip.getItemAt(i).uri?.let { out.add(it) }
      }
    }
    // file:// qabul qilinmaydi: begona ilova bizning shaxsiy faylimizni ko'rsatib yuborolmasin.
    return out.filter { it.scheme == ContentResolver.SCHEME_CONTENT }
  }

  // API 33 dagi tipli getParcelableExtra xatosi tufayli tipli variant faqat 34+ da.
  @Suppress("DEPRECATION")
  private fun streamOf(intent: Intent): Uri? =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
    } else {
      intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
    }

  @Suppress("DEPRECATION")
  private fun streamsOf(intent: Intent): List<Uri> {
    val list: List<Uri?>? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
    } else {
      intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
    }
    return list?.filterNotNull() ?: emptyList()
  }

  private companion object {
    const val SLOW_MS = 700L
  }
}
