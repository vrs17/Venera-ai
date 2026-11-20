package uz.brbtech.venera.entry

import android.Manifest
import android.content.ContentResolver
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.database.Cursor
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.SystemClock
import android.provider.BaseColumns
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.provider.OpenableColumns
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.IOException

/**
 * Qo'ng'iroq yozuvlarini Barno'ga olib kirish (2026-10-10).
 *
 * NIMA UCHUN shunday: Android 10+ da oddiy ilova qo'ng'iroq ovozini o'zi yoza
 * olmaydi. Samsung "Telefon" ilovasi yozadi (One UI 4+: Recordings/Call/, eskilari:
 * Call/), Barno esa tayyor faylni MediaStore orqali topadi yoki foydalanuvchi
 * "Ulashish -> Barno" qiladi. Ikkala yo'l ham faylni ilovaning SHAXSIY papkasiga
 * nusxalaydi: keyin yig'ilish yozuvi bilan bir xil navbat/yuklovchi ishlaydi, asl
 * fayl o'chirilsa yoki ko'chirilsa ham yuklash buzilmaydi.
 *
 * Expo'ga bog'liq emas - ImportActivity ham, VeneraEntryModule ham ishlatadi.
 */
internal object CallImport {
  /** Ulashilgan, hali tasdiqlanmagan fayllar: filesDir/imports/ (+ <nom>.json yonida). */
  const val IMPORTS_DIR = "imports"

  /** MediaStore'dan nusxa yig'ilish yozuvlari yonida: chiqishda (logout) birga o'chadi. */
  const val RECORDINGS_DIR = "recordings"

  /** Server qabul qiladigan turlar (apps/api meetings ACCEPTED_TYPES) - boshqasini nusxalash befoyda. */
  const val TYPE_MP4 = "audio/mp4"
  const val TYPE_AAC = "audio/aac"

  /**
   * Bitta fayl chegarasi: server 150 MB oladi (meetings_max_upload_mb). Kattasini nusxalash
   * befoyda - baribir yuborilmaydi, faqat telefon xotirasini egallaydi. Server chegarasi
   * oshirilsa, shu son ham oshirilsin.
   */
  const val MAX_COPY_BYTES = 160L * 1024 * 1024

  /**
   * imports/ dagi tasdiqlanmagan nusxalar jami chegarasi. NIMA UCHUN: ImportActivity eksport
   * qilingan - begona ilova uni qayta-qayta ochib, xotirani to'ldirib qo'ymasin.
   */
  private const val MAX_PENDING_IMPORT_BYTES = 1024L * 1024 * 1024

  /** Tasdiqlanmagan ulashilgan nusxa shuncha vaqtdan keyin o'chiriladi (orqaga bosildi, ekran yopildi ...). */
  private const val STALE_IMPORT_MS = 24L * 60 * 60 * 1000

  /** Yarim qolgan `.part` (jarayon o'ldirilgan) shuncha vaqtdan keyin o'chiriladi - parallel nusxaga tegmaymiz. */
  private const val STALE_PART_MS = 60L * 60 * 1000

  /** Ulashilgan faylning boshidan shuncha bayt tekshiriladi (MP4 `ftyp` / AAC ADTS). */
  private const val HEADER_BYTES = 12

  /** Asl nom (meta .json) chegarasi - begona ilova cheksiz uzun nom berishi mumkin. */
  private const val MAX_DISPLAY_NAME = 200

  /** Nusxadan keyin ham shuncha joy qolsin - yangi yig'ilish yozuvi uchun. */
  private const val RESERVE_BYTES = 50L * 1024 * 1024

  /** Bir ulashishda ko'pi bilan shuncha fayl: deep link qisqa, tasdiqlash ekrani o'qiladigan. */
  const val MAX_SHARED_FILES = 20

  /** Xavfsiz nom - JS (importNames.ts IMPORT_NAME_RE) ham AYNAN shu qoidani tekshiradi. */
  val SAFE_NAME = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")

  // Samsung Telefon papkalari: One UI 4+ "Recordings/Call/", eskilari xotira ildizidagi "Call/".
  // NIMA UCHUN boshidan bog'langan ("%/Call/%" emas): SQLite LIKE ASCII'da katta-kichik harfni
  // farqlamaydi - "Download/call/" yoki "Music/Call/" dagi begona fayllar qo'ng'iroq bo'lib chiqmasin.
  private val RELATIVE_PATTERNS = arrayOf("Recordings/Call/%", "Call/%")

  /** Android 9 va pastda (DATA ustuni - absolyut yo'l): ildizdagi Call/ va istalgan Recordings/Call/. */
  @Suppress("DEPRECATION")
  private fun dataPatterns(): Array<String> {
    val root = Environment.getExternalStorageDirectory().absolutePath.trimEnd('/')
    return arrayOf("$root/Call/%", "%/Recordings/Call/%")
  }

  // Kengaytma aniq boshqa format bo'lsa MIME'ga ishonmaymiz (yuboruvchi ilova noto'g'ri MIME berishi mumkin).
  private val OTHER_AUDIO_EXT = setOf("mp3", "ogg", "oga", "opus", "wav", "amr", "awb", "3gp", "3ga", "flac", "wma", "mid", "midi", "webm")

  /** JS'ga `error.code` bo'lib boradi (index.ts CallImportErrorCode). */
  class ImportException(val code: String, message: String) : IOException(message)

  fun errorCode(e: Throwable): String = when (e) {
    is ImportException -> e.code
    is SecurityException -> "ERR_PERMISSION"
    is FileNotFoundException -> "ERR_READ"
    else -> "ERR_IO"
  }

  // ---------------------------------------------------------------- ruxsat

  /** Android 13+ da READ_MEDIA_AUDIO, undan pastda READ_EXTERNAL_STORAGE (manifestda maxSdk 32). */
  fun audioReadPermission(): String =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      Manifest.permission.READ_MEDIA_AUDIO
    } else {
      Manifest.permission.READ_EXTERNAL_STORAGE
    }

  fun hasAudioReadPermission(ctx: Context): Boolean =
    ctx.checkSelfPermission(audioReadPermission()) == PackageManager.PERMISSION_GRANTED

  // ---------------------------------------------------------------- MediaStore

  /**
   * Samsung qo'ng'iroq yozuvlari, eng yangisi birinchi. `sinceMs` - fayl o'zgargan
   * vaqt (DATE_MODIFIED, ~qo'ng'iroq OXIRI) bo'yicha. NIMA UCHUN DATE_ADDED emas:
   * zaxiradan tiklangan ESKI yozuvlar "yangi" bo'lib avtomatik yuborilib ketmasin.
   */
  fun listCallRecordings(ctx: Context, sinceMs: Long, limit: Int): List<Map<String, Any?>> {
    if (!hasAudioReadPermission(ctx)) throw ImportException("ERR_PERMISSION", "audio read permission missing")
    val max = limit.coerceIn(1, 500)
    val scoped = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
    val collection: Uri = if (scoped) {
      MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
    } else {
      MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
    }
    @Suppress("DEPRECATION")
    val pathColumn = if (scoped) MediaStore.MediaColumns.RELATIVE_PATH else MediaStore.MediaColumns.DATA
    val patterns = if (scoped) RELATIVE_PATTERNS else dataPatterns()
    val selection = patterns.joinToString(" OR ", prefix = "(", postfix = ")") { "$pathColumn LIKE ?" } +
      " AND ${MediaStore.MediaColumns.DATE_MODIFIED} >= ?" +
      " AND ${MediaStore.MediaColumns.SIZE} > 0"
    val args = ArrayList<String>(patterns.size + 1)
    args.addAll(patterns)
    args.add((sinceMs.coerceAtLeast(0L) / 1000L).toString())
    val projection = arrayOf(
      BaseColumns._ID,
      MediaStore.MediaColumns.DISPLAY_NAME,
      MediaStore.MediaColumns.SIZE,
      MediaStore.Audio.AudioColumns.DURATION,
      MediaStore.MediaColumns.DATE_MODIFIED,
      MediaStore.MediaColumns.DATE_ADDED,
      MediaStore.MediaColumns.MIME_TYPE,
      pathColumn
    )
    val out = ArrayList<Map<String, Any?>>()
    // LIMIT'ni sortOrder'ga yozib bo'lmaydi (Android 11+ MediaProvider rad etadi) - kursorda to'xtaymiz.
    ctx.contentResolver.query(
      collection,
      projection,
      selection,
      args.toTypedArray(),
      "${MediaStore.MediaColumns.DATE_MODIFIED} DESC"
    )?.use { c ->
      val iId = c.getColumnIndex(BaseColumns._ID)
      val iName = c.getColumnIndex(MediaStore.MediaColumns.DISPLAY_NAME)
      val iSize = c.getColumnIndex(MediaStore.MediaColumns.SIZE)
      val iDuration = c.getColumnIndex(MediaStore.Audio.AudioColumns.DURATION)
      val iModified = c.getColumnIndex(MediaStore.MediaColumns.DATE_MODIFIED)
      val iAdded = c.getColumnIndex(MediaStore.MediaColumns.DATE_ADDED)
      val iMime = c.getColumnIndex(MediaStore.MediaColumns.MIME_TYPE)
      val iPath = c.getColumnIndex(pathColumn)
      while (out.size < max && c.moveToNext()) {
        if (iId < 0 || c.isNull(iId)) continue
        val id = c.getLong(iId)
        val name = c.stringOr(iName) ?: ""
        val mime = c.stringOr(iMime)
        val modified = c.longOr(iModified)
        val stamp = if (modified > 0) modified else c.longOr(iAdded)
        val path = c.stringOr(iPath)
        out.add(
          mapOf(
            "uri" to ContentUris.withAppendedId(collection, id).toString(),
            "displayName" to name,
            "relativePath" to (if (scoped) (path ?: "") else relativeFromData(path)),
            "sizeBytes" to c.longOr(iSize),
            "durationMs" to c.longOr(iDuration),
            "dateMs" to toMs(stamp),
            "mimeType" to mime,
            "contentType" to uploadType(name, mime)
          )
        )
      }
    }
    return out
  }

  // ---------------------------------------------------------------- nusxalash

  /**
   * MediaStore (yoki boshqa content://) faylini filesDir/recordings/<xavfsiz nom> ga
   * oqim bilan nusxalaydi (butun fayl xotiraga o'qilmaydi). Nom band bo'lsa `-1`, `-2`
   * qo'shiladi - navbatdagi boshqa fayl ustidan yozilmasin. Haqiqiy faylni qaytaradi.
   */
  fun copyToAppStorage(ctx: Context, source: String, destFileName: String): File {
    val uri = checkedSource(ctx, source)
    val info = describe(ctx.contentResolver, uri)
    val dir = File(ctx.filesDir, RECORDINGS_DIR)
    preflight(dir, info.sizeBytes)
    val target = uniqueFile(dir, safeFileName(destFileName, "call_${System.currentTimeMillis()}.m4a"))
    copyInto(ctx.contentResolver, uri, target)
    return target
  }

  /**
   * Faqat content:// va faqat BOSHQA ilovaning provayderi. NIMA UCHUN: begona ilova
   * bizning o'z (eksport qilinmagan) provayderimiz manzilini "ulashib", Barno'ga
   * o'zining shaxsiy faylini nusxalatib yuborishi mumkin edi (confused deputy).
   */
  fun checkedSource(ctx: Context, raw: String): Uri {
    val uri = Uri.parse(raw)
    val authority = uri.authority
    if (uri.scheme != ContentResolver.SCHEME_CONTENT || authority == null || authority.isEmpty()) {
      throw ImportException("ERR_BAD_URI", "only content:// sources are accepted")
    }
    // "content://0@<bizning provayder>/..." - resolveContentProvider "0@..." ni tanimaydi (null),
    // ContentResolver esa "0@" (foydalanuvchi raqami)ni olib tashlab baribir O'Z provayderimizni
    // ochadi. Oddiy ulashishda foydalanuvchi qismi bo'lmaydi - bunday manzil umuman qabul qilinmaydi.
    if (uri.userInfo != null || authority.contains('@')) {
      throw ImportException("ERR_BAD_URI", "user-qualified authority is not accepted")
    }
    if (isOwnAuthority(ctx, authority)) throw ImportException("ERR_BAD_URI", "own provider is not a source")
    return uri
  }

  @Suppress("DEPRECATION")
  private fun isOwnAuthority(ctx: Context, authority: String): Boolean {
    // Ikkinchi qavat: "@" yuqorida rad etilgan, lekin tekshiruv baribir provayder nomining o'zi bo'yicha.
    val name = authority.substringAfterLast('@')
    val owner = try {
      ctx.packageManager.resolveContentProvider(name, 0)?.packageName
    } catch (_: Exception) {
      null
    }
    return owner == ctx.packageName
  }

  private fun preflight(dir: File, size: Long?) {
    if (!dir.exists() && !dir.mkdirs()) throw ImportException("ERR_IO", "cannot create ${dir.name}")
    if (size != null && size > MAX_COPY_BYTES) throw ImportException("ERR_TOO_LARGE", "file is too large")
    if (size != null && dir.usableSpace < size + RESERVE_BYTES) throw ImportException("ERR_NO_SPACE", "not enough free space")
  }

  /**
   * `.part` ga yozib, oxirida nomini almashtiradi: yarim nusxa (xotira tugadi, ilova
   * o'ldirildi) hech qachon tayyor fayl bo'lib ko'rinmaydi va yuklanmaydi.
   */
  private fun copyInto(resolver: ContentResolver, uri: Uri, target: File, checkHeader: Boolean = false): Long {
    val dir = target.parentFile ?: throw ImportException("ERR_IO", "no parent dir")
    if (!dir.exists() && !dir.mkdirs()) throw ImportException("ERR_IO", "cannot create ${dir.name}")
    val part = File(dir, target.name + ".part")
    var total = 0L
    val head = ByteArray(HEADER_BYTES)
    var headLen = 0
    try {
      val input = resolver.openInputStream(uri) ?: throw ImportException("ERR_READ", "cannot open source")
      input.use { ins ->
        FileOutputStream(part).use { out ->
          val buf = ByteArray(64 * 1024)
          while (true) {
            val n = ins.read(buf)
            if (n < 0) break
            if (checkHeader && headLen < HEADER_BYTES) {
              val take = minOf(n, HEADER_BYTES - headLen)
              System.arraycopy(buf, 0, head, headLen, take)
              headLen += take
              // Birinchi baytlardayoq to'xtaymiz: "x.m4a" deb berilgan boshqa narsa 160 MB ko'chirilmasin.
              if (headLen == HEADER_BYTES && !looksLikeUploadAudio(head, headLen)) {
                throw ImportException("ERR_FORMAT", "not an m4a/aac stream")
              }
            }
            total += n
            if (total > MAX_COPY_BYTES) throw ImportException("ERR_TOO_LARGE", "file is too large")
            out.write(buf, 0, n)
          }
          out.fd.sync()
        }
      }
      if (total == 0L) throw ImportException("ERR_EMPTY", "source is empty")
      if (checkHeader && headLen < HEADER_BYTES && !looksLikeUploadAudio(head, headLen)) {
        throw ImportException("ERR_FORMAT", "not an m4a/aac stream")
      }
      if (!part.renameTo(target)) throw ImportException("ERR_IO", "rename failed")
      return total
    } catch (e: Exception) {
      part.delete()
      throw e
    }
  }

  // ---------------------------------------------------------------- "Ulashish -> Barno"

  class SharedImport(val files: List<String>, val skipped: Int)

  /**
   * Ulashilgan oqimlarni filesDir/imports/ ga nusxalaydi. Har fayl yonida
   * `<nom>.json`: asl nom (kirill/raqam bilan - deep link'ga sig'maydi), tur,
   * hajm, davomiylik, sana. Qo'llab-quvvatlanmaydigan yoki o'qib bo'lmaydigan
   * fayllar `skipped` ga sanaladi.
   */
  fun importShared(ctx: Context, uris: List<Uri>): SharedImport {
    val dir = File(ctx.filesDir, IMPORTS_DIR)
    if (!dir.exists()) dir.mkdirs()
    // Tasdiqlanmay qolgan eski nusxalar (orqaga bosildi, yangi ulashish ekranni almashtirdi,
    // kirish ekraniga o'tib ketdi) shu yerda tozalanadi - imports/ cheksiz o'smasin.
    removeStale(dir, System.currentTimeMillis())
    val batch = System.currentTimeMillis()
    val files = ArrayList<String>()
    var skipped = (uris.size - MAX_SHARED_FILES).coerceAtLeast(0)
    for ((i, raw) in uris.take(MAX_SHARED_FILES).withIndex()) {
      try {
        val uri = checkedSource(ctx, raw.toString())
        val info = describe(ctx.contentResolver, uri)
        val type = uploadType(info.displayName, info.mimeType)
        if (type == null) {
          skipped++
          continue
        }
        val ext = if (type == TYPE_AAC) "aac" else "m4a"
        preflight(dir, info.sizeBytes)
        if (dirBytes(dir) + (info.sizeBytes ?: 0L) > MAX_PENDING_IMPORT_BYTES) {
          throw ImportException("ERR_NO_SPACE", "too many pending imports")
        }
        val target = uniqueFile(dir, "share_${batch}_${i}_${safeStem(info.displayName)}.$ext")
        // Kengaytma/MIME'ni yuboruvchi ilova aytadi - mazmun ham MP4/AAC ekanini tekshiramiz.
        val size = copyInto(ctx.contentResolver, uri, target, checkHeader = true)
        writeMeta(target, info, type, size)
        files.add(target.name)
      } catch (_: Exception) {
        skipped++
      }
    }
    return SharedImport(files, skipped)
  }

  /**
   * venera-rec://import?files=<nom1,nom2>[&skipped=<n>]&n=<nonce>
   *
   * So'rov qatori qo'lda yig'iladi: nomlar faqat [A-Za-z0-9._-], nonce raqam - hammasi
   * URL'da xavfsiz, vergul esa %2C ga aylanmaydi (JS oddiy split qiladi). `n` - har
   * ulashish noyob (ochiq ekranda bir xil URL qayta render bermasdi).
   * NIMA UCHUN `k` (o'rnatish kaliti) YO'Q: import doim tasdiq ekrani orqali o'tadi, kalit
   * hech narsani hal qilmaydi - uni ortiqcha havola va router holatiga tarqatmaymiz.
   */
  fun importIntent(ctx: Context, files: List<String>, skipped: Int): Intent {
    val q = StringBuilder("files=").append(files.filter { SAFE_NAME.matches(it) }.joinToString(","))
    if (skipped > 0) q.append("&skipped=").append(skipped)
    q.append("&n=").append(SystemClock.elapsedRealtime())
    val uri = Uri.Builder().scheme("venera-rec").authority("import").encodedQuery(q.toString()).build()
    return Intent(Intent.ACTION_VIEW, uri).apply {
      setPackage(ctx.packageName)
      addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    }
  }

  /** Tasdiqlash ekrani uchun: imports/<nom> haqida ma'lumot (fayl yo'q bo'lsa null). */
  fun readImportMeta(ctx: Context, fileName: String): Map<String, Any?>? {
    if (!isImportName(fileName)) return null
    val dir = File(ctx.filesDir, IMPORTS_DIR)
    val audio = File(dir, fileName)
    if (!audio.isFile) return null
    val json = try {
      val meta = File(dir, "$fileName.json")
      if (meta.isFile) JSONObject(meta.readText()) else null
    } catch (_: Exception) {
      null
    }
    val type = json?.optString("contentType")?.takeIf { it == TYPE_MP4 || it == TYPE_AAC }
      ?: uploadType(fileName, null)
    val dateMs = if (json == null || json.isNull("dateMs")) null else json.optLong("dateMs", 0L).takeIf { it > 0 }
    return mapOf(
      "fileName" to fileName,
      "path" to audio.absolutePath,
      "displayName" to (json?.optString("displayName")?.takeIf { it.isNotBlank() } ?: fileName),
      "contentType" to type,
      "sizeBytes" to audio.length(),
      "durationMs" to (json?.optLong("durationMs", 0L) ?: 0L),
      "dateMs" to dateMs,
      "source" to "share"
    )
  }

  /** imports/<nom> va uning .json'ini o'chiradi (bekor qilindi yoki navbatga ko'chirildi). */
  fun removeImport(ctx: Context, fileName: String): Boolean {
    if (!isImportName(fileName)) return false
    val dir = File(ctx.filesDir, IMPORTS_DIR)
    File(dir, "$fileName.json").delete()
    val audio = File(dir, fileName)
    return !audio.exists() || audio.delete()
  }

  /** Chiqishda (umumiy telefon): tasdiqlanmagan ulashilgan fayllar ham qolmasin. */
  fun clearImports(ctx: Context) {
    File(ctx.filesDir, IMPORTS_DIR).deleteRecursively()
  }

  private fun isImportName(name: String): Boolean =
    SAFE_NAME.matches(name) && !name.contains("..") && uploadType(name, null) != null

  private fun removeStale(dir: File, now: Long) {
    dir.listFiles()?.forEach { f ->
      val age = now - f.lastModified()
      val stale = if (f.name.endsWith(".part")) age > STALE_PART_MS else age > STALE_IMPORT_MS
      if (f.isFile && stale) f.delete()
    }
  }

  private fun dirBytes(dir: File): Long {
    var total = 0L
    dir.listFiles()?.forEach { if (it.isFile) total += it.length() }
    return total
  }

  /**
   * Server qabul qiladigan audio boshi: MP4/M4A (4-baytdan `ftyp`, ba'zan `moov`/`mdat`/`free`/
   * `skip`/`wide` qutisi), AAC ADTS (0xFFF sinx so'zi) yoki ID3 tegli AAC.
   */
  private fun looksLikeUploadAudio(b: ByteArray, len: Int): Boolean {
    if (len >= 8) {
      for (box in arrayOf("ftyp", "moov", "mdat", "free", "skip", "wide")) {
        if (asciiAt(b, len, 4, box)) return true
      }
    }
    if (len >= 2 && (b[0].toInt() and 0xFF) == 0xFF && (b[1].toInt() and 0xF6) == 0xF0) return true
    return asciiAt(b, len, 0, "ID3")
  }

  private fun asciiAt(b: ByteArray, len: Int, at: Int, s: String): Boolean {
    if (at + s.length > len) return false
    for (i in s.indices) {
      if (b[at + i] != s[i].code.toByte()) return false
    }
    return true
  }

  private fun writeMeta(target: File, info: SourceInfo, type: String, size: Long) {
    try {
      val json = JSONObject()
        .put("displayName", (info.displayName ?: target.name).take(MAX_DISPLAY_NAME))
        .put("contentType", type)
        .put("sizeBytes", size)
        .put("durationMs", probeDurationMs(target) ?: 0L)
        .put("dateMs", info.dateMs ?: JSONObject.NULL)
        .put("source", "share")
      File(target.parentFile, target.name + ".json").writeText(json.toString())
    } catch (_: Exception) {
      // Meta bo'lmasa ham fayl yaroqli - JS fayl nomini ko'rsatadi.
    }
  }

  // ---------------------------------------------------------------- yordamchilar

  private class SourceInfo(val displayName: String?, val sizeBytes: Long?, val mimeType: String?, val dateMs: Long?)

  /** OpenableColumns (har provayder beradi) + imkon bo'lsa o'zgargan sana. */
  private fun describe(resolver: ContentResolver, uri: Uri): SourceInfo {
    var name: String? = null
    var size: Long? = null
    try {
      resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
        if (c.moveToFirst()) {
          name = c.stringOr(c.getColumnIndex(OpenableColumns.DISPLAY_NAME))
          val iSize = c.getColumnIndex(OpenableColumns.SIZE)
          if (iSize >= 0 && !c.isNull(iSize)) size = c.getLong(iSize)
        }
      }
    } catch (_: Exception) {
      // Ba'zi provayderlar so'rovni qo'llamaydi - nom va hajmsiz ham nusxalaymiz.
    }
    val mime = try {
      resolver.getType(uri)
    } catch (_: Exception) {
      null
    }
    // MediaStore: date_modified (soniya); DocumentsProvider: last_modified (ms). Noma'lum ustun -> null.
    val date = queryLong(resolver, uri, MediaStore.MediaColumns.DATE_MODIFIED)
      ?: queryLong(resolver, uri, DocumentsContract.Document.COLUMN_LAST_MODIFIED)
    return SourceInfo(name ?: uri.lastPathSegment, size?.takeIf { it > 0 }, mime, date?.let { toMs(it) }?.takeIf { it > 0 })
  }

  private fun queryLong(resolver: ContentResolver, uri: Uri, column: String): Long? = try {
    resolver.query(uri, arrayOf(column), null, null, null)?.use { c ->
      val i = c.getColumnIndex(column)
      if (c.moveToFirst() && i >= 0 && !c.isNull(i)) c.getLong(i) else null
    }
  } catch (_: Exception) {
    null
  }

  private fun probeDurationMs(file: File): Long? {
    val r = MediaMetadataRetriever()
    return try {
      r.setDataSource(file.absolutePath)
      r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
    } catch (_: Exception) {
      null
    } finally {
      try {
        r.release()
      } catch (_: Exception) {
        // e'tiborsiz
      }
    }
  }

  /** Kengaytma birinchi (m4a/mp4/aac), keyin MIME. Server faqat audio/mp4 va audio/aac oladi. */
  fun uploadType(name: String?, mime: String?): String? {
    val dot = name?.lastIndexOf('.') ?: -1
    val ext = if (name != null && dot >= 0 && dot < name.length - 1) name.substring(dot + 1).lowercase() else ""
    when (ext) {
      "m4a", "mp4" -> return TYPE_MP4
      "aac" -> return TYPE_AAC
      in OTHER_AUDIO_EXT -> return null
    }
    return when (mime?.substringBefore(';')?.trim()?.lowercase()) {
      "audio/mp4", "audio/m4a", "audio/x-m4a" -> TYPE_MP4
      "audio/aac", "audio/x-aac", "audio/aacp", "audio/aac-adts" -> TYPE_AAC
      else -> null
    }
  }

  /** JS bergan nomdan faqat [A-Za-z0-9._-] qoladi, 100 belgigacha; yaroqsiz bo'lsa `fallback`. */
  fun safeFileName(raw: String?, fallback: String): String {
    val base = (raw ?: "").substringAfterLast('/').substringAfterLast('\\')
    var s = asciiOnly(base).replace(Regex("\\.{2,}"), ".").trimStart('.', '_', '-')
    if (s.length > 100) {
      val dot = s.lastIndexOf('.')
      val ext = if (dot > 0 && s.length - dot <= 6) s.substring(dot) else ""
      s = s.substring(0, 100 - ext.length) + ext
    }
    val ok = SAFE_NAME.matches(s) && !s.endsWith(".part") && !s.endsWith(".json")
    return if (ok) s else fallback
  }

  /** Ulashilgan fayl nomining o'zagi (kengaytmasiz, 40 belgi). Kirill nom bo'lsa "audio". */
  private fun safeStem(displayName: String?): String {
    val base = (displayName ?: "").substringAfterLast('/')
    val dot = base.lastIndexOf('.')
    val stem = asciiOnly(if (dot > 0) base.substring(0, dot) else base).replace(".", "_").trim('_', '-')
    return stem.take(40).trimEnd('_', '-').ifEmpty { "audio" }
  }

  private fun asciiOnly(s: String): String {
    val sb = StringBuilder(s.length)
    for (ch in s) {
      val ok = ch in 'a'..'z' || ch in 'A'..'Z' || ch in '0'..'9' || ch == '.' || ch == '-' || ch == '_'
      sb.append(if (ok) ch else '_')
    }
    return sb.toString().replace(Regex("_{2,}"), "_")
  }

  /** Nom band bo'lsa `-1`, `-2` ... (navbatdagi boshqa fayl ustidan yozilmasin). */
  private fun uniqueFile(dir: File, name: String): File {
    val first = File(dir, name)
    if (!first.exists()) return first
    val dot = name.lastIndexOf('.')
    val stem = if (dot > 0) name.substring(0, dot) else name
    val ext = if (dot > 0) name.substring(dot) else ""
    for (i in 1..999) {
      val f = File(dir, "$stem-$i$ext")
      if (!f.exists()) return f
    }
    throw ImportException("ERR_IO", "no free file name")
  }

  @Suppress("DEPRECATION")
  private fun relativeFromData(data: String?): String {
    val parent = data?.let { File(it).parent } ?: return ""
    val root = Environment.getExternalStorageDirectory().absolutePath
    return if (parent.startsWith(root)) parent.removePrefix(root).trimStart('/') + "/" else "$parent/"
  }

  /** MediaStore sanalari soniyada; ba'zi provayderlar ms beradi - kattaligidan ajratamiz. */
  private fun toMs(v: Long): Long = if (v > 100_000_000_000L) v else v * 1000L

  private fun Cursor.longOr(i: Int): Long = if (i < 0 || isNull(i)) 0L else getLong(i)

  private fun Cursor.stringOr(i: Int): String? = if (i < 0 || isNull(i)) null else getString(i)
}
