package uz.brbtech.venera.entry

import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.service.quicksettings.TileService
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * JS API (modules/venera-entry/index.ts):
 *   setRecordingState(recording), requestAddTile(), setLauncherEnabled(enabled),
 *   isLauncherEnabled(), setTrustedKey(key)
 *   Qo'ng'iroq yozuvlari: hasAudioReadPermission(), listCallRecordings(sinceMs, limit),
 *   copyToAppStorage(uri, destFileName), getImportMeta(fileName), removeImport(fileName),
 *   clearImports() - CallImport.kt; "Ulashish -> Barno" - ImportActivity.kt.
 *
 * Holat (yozilmoqdami, ishonchli kalit) private SharedPreferences'da: plitka
 * va launcher activity JS ishlamayotganda ham uni o'qiy oladi.
 */
class VeneraEntryModule : Module() {
  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  override fun definition() = ModuleDefinition {
    Name("VeneraEntry")

    Function("setRecordingState") { recording: Boolean ->
      EntryPrefs.setRecording(context, recording)
      // Plitka ko'rinib turgan bo'lsa holatini darhol yangilasin.
      try {
        TileService.requestListeningState(context, ComponentName(context, RecordTileService::class.java))
      } catch (_: Exception) {
        // Plitka qo'shilmagan bo'lsa tizim istisno berishi mumkin - muhim emas.
      }
    }

    Function("setTrustedKey") { key: String ->
      EntryPrefs.setKey(context, key)
    }

    Function("setLauncherEnabled") { enabled: Boolean ->
      val state = if (enabled) {
        PackageManager.COMPONENT_ENABLED_STATE_ENABLED
      } else {
        PackageManager.COMPONENT_ENABLED_STATE_DISABLED
      }
      context.packageManager.setComponentEnabledSetting(
        ComponentName(context, RecordLauncherActivity::class.java),
        state,
        PackageManager.DONT_KILL_APP
      )
    }

    Function("isLauncherEnabled") {
      context.packageManager.getComponentEnabledSetting(
        ComponentName(context, RecordLauncherActivity::class.java)
      ) == PackageManager.COMPONENT_ENABLED_STATE_ENABLED
    }

    AsyncFunction("requestAddTile") { promise: Promise ->
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
        promise.resolve("unsupported")
      } else {
        requestAddTile33(promise)
      }
    }

    // --- Qo'ng'iroq yozuvlari (2026-10-10, mantiq CallImport.kt da) ---

    Function("hasAudioReadPermission") {
      CallImport.hasAudioReadPermission(context)
    }

    AsyncFunction("listCallRecordings") { sinceMs: Double, limit: Int, promise: Promise ->
      runImport(promise) { CallImport.listCallRecordings(context, sinceMs.toLong(), limit) }
    }

    AsyncFunction("copyToAppStorage") { uri: String, destFileName: String, promise: Promise ->
      runImport(promise) { CallImport.copyToAppStorage(context, uri, destFileName).absolutePath }
    }

    AsyncFunction("getImportMeta") { fileName: String, promise: Promise ->
      runImport(promise) { CallImport.readImportMeta(context, fileName) }
    }

    Function("removeImport") { fileName: String ->
      CallImport.removeImport(context, fileName)
    }

    Function("clearImports") {
      CallImport.clearImports(context)
    }
  }

  /**
   * NIMA UCHUN o'z oqimimiz: Expo AsyncFunction'lari BITTA umumiy oqimda
   * (modulesQueue) ishlaydi - 100 MB nusxa SecureStore/audio chaqiruvlarini ham
   * kuttirib qo'yardi. Xatolar JS'ga `error.code` (ERR_PERMISSION, ERR_TOO_LARGE ...).
   */
  private fun <T> runImport(promise: Promise, block: () -> T) {
    importExecutor.execute {
      try {
        promise.resolve(block())
      } catch (e: expo.modules.kotlin.exception.CodedException) {
        promise.reject(e)
      } catch (e: Throwable) {
        val code = CallImport.errorCode(e)
        promise.reject(code, e.message ?: code, e)
      }
    }
  }

  private companion object {
    /** Jarayonga bitta (dev reload'da modul qayta yaratilsa ham oqim ko'paymaydi). */
    val importExecutor: java.util.concurrent.ExecutorService by lazy {
      java.util.concurrent.Executors.newSingleThreadExecutor { r -> Thread(r, "barno-call-import") }
    }
  }

  @android.annotation.TargetApi(Build.VERSION_CODES.TIRAMISU)
  private fun requestAddTile33(promise: Promise) {
    val sbm = context.getSystemService(StatusBarManager::class.java)
    if (sbm == null) {
      promise.resolve("unsupported")
      return
    }
    try {
      sbm.requestAddTileService(
        ComponentName(context, RecordTileService::class.java),
        context.getString(R.string.venera_entry_tile_label),
        Icon.createWithResource(context, R.drawable.ic_record),
        context.mainExecutor
      ) { result ->
        promise.resolve(
          when (result) {
            StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED -> "added"
            StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED -> "already"
            else -> "denied"
          }
        )
      }
    } catch (_: Exception) {
      // Ilova old planda bo'lmasa tizim rad etadi.
      promise.resolve("denied")
    }
  }
}

/** Plitka, launcher va JS o'rtasidagi umumiy holat. */
internal object EntryPrefs {
  private const val FILE = "venera_entry"
  private const val KEY_RECORDING = "recording"
  private const val KEY_TRUSTED = "trusted_key"

  private fun prefs(ctx: Context) = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)

  fun isRecording(ctx: Context): Boolean = prefs(ctx).getBoolean(KEY_RECORDING, false)

  fun setRecording(ctx: Context, recording: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_RECORDING, recording).apply()
  }

  fun key(ctx: Context): String? = prefs(ctx).getString(KEY_TRUSTED, null)

  fun setKey(ctx: Context, key: String) {
    prefs(ctx).edit().putString(KEY_TRUSTED, key).apply()
  }

  /**
   * venera-rec://record?src=<src>&k=<installKey>[&action=stop]&n=<nonce>
   *
   * `n` har bosishda yangi: Record ekrani ochiq turganda AYNAN bir xil URL
   * kelsa expo-router qayta render bermaydi va ikkinchi bosish yo'qolardi.
   */
  fun recordUri(ctx: Context, src: String, stop: Boolean): Uri {
    val b = Uri.Builder().scheme("venera-rec").authority("record").appendQueryParameter("src", src)
    key(ctx)?.let { b.appendQueryParameter("k", it) }
    if (stop) b.appendQueryParameter("action", "stop")
    b.appendQueryParameter("n", SystemClock.elapsedRealtime().toString())
    return b.build()
  }

  /** Faqat O'Z ilovamizga (setPackage) - boshqa ilova bu intentni ushlay olmaydi. */
  fun recordIntent(ctx: Context, src: String, stop: Boolean): Intent =
    Intent(Intent.ACTION_VIEW, recordUri(ctx, src, stop)).apply {
      setPackage(ctx.packageName)
      addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    }
}
