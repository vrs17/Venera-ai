package uz.brbtech.venera.entry

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/**
 * Quick Settings "Yozish" plitkasi (spec 2.2).
 *
 * onClick: telefon qulflangan bo'lsa avval `unlockAndRun` (PIN/barmoq izi),
 * keyin ilovani deep link bilan ochadi. Yozilmoqda bo'lsa `action=stop`.
 * API 34+ da faqat PendingIntent varianti ruxsat etilgan.
 * Holat JS `setRecordingState` orqali SharedPreferences'ga yozadi.
 */
class RecordTileService : TileService() {
  override fun onTileAdded() {
    super.onTileAdded()
    refresh()
  }

  override fun onStartListening() {
    super.onStartListening()
    refresh()
  }

  override fun onClick() {
    super.onClick()
    val stop = EntryPrefs.isRecording(this)
    val launch = Runnable { launch(stop) }
    if (isLocked) unlockAndRun(launch) else launch.run()
  }

  private fun refresh() {
    val tile = qsTile ?: return
    val recording = EntryPrefs.isRecording(this)
    tile.state = if (recording) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
    tile.label = getString(R.string.venera_entry_tile_label)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      tile.subtitle = getString(
        if (recording) R.string.venera_entry_tile_recording else R.string.venera_entry_tile_idle
      )
    }
    tile.updateTile()
  }

  @SuppressLint("StartActivityAndCollapseDeprecated")
  private fun launch(stop: Boolean) {
    val intent = EntryPrefs.recordIntent(this, "tile", stop)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      val pending = PendingIntent.getActivity(
        this,
        if (stop) 2 else 1,
        intent,
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
      )
      startActivityAndCollapse(pending)
    } else {
      @Suppress("DEPRECATION")
      startActivityAndCollapse(intent)
    }
  }
}
