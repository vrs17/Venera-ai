/**
 * Ilova kodi native modulga faqat shu fayl orqali murojaat qiladi -
 * testlarda bitta joyni mock qilish kifoya.
 */
export {
  isAvailable,
  isLauncherEnabled,
  requestAddTile,
  setLauncherEnabled,
  setRecordingState,
  setTrustedKey,
  type AddTileResult,
} from '../../../modules/venera-entry';

/**
 * Qo'ng'iroq yozuvlari importi (2026-10-10): Samsung Recordings/Call/ (MediaStore)
 * va "Ulashish -> Barno AI". Sof yordamchilar (contentTypeFor, parseImportFiles,
 * IMPORT_NAME_RE ...) native'siz - deepLink.ts ularni to'g'ridan-to'g'ri
 * `modules/venera-entry/importNames` dan olsin (bu fayl testlarda mock qilinadi).
 */
export {
  audioReadPermission,
  clearImports,
  contentTypeFor,
  copyToAppStorage,
  getImportMeta,
  hasAudioReadPermission,
  IMPORT_NAME_RE,
  IMPORTS_DIR,
  isCallImportAvailable,
  isImportFileName,
  listCallRecordings,
  MAX_SHARED_FILES,
  parseImportFiles,
  removeImport,
  type CallContentType,
  type CallImportError,
  type CallImportErrorCode,
  type CallRecording,
  type ImportMeta,
} from '../../../modules/venera-entry';
