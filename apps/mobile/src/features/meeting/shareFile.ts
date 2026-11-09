/**
 * Serverdagi faylni ulashish uchun umumiy native qatlam: `Authorization` bilan telefon keshiga
 * (`cache/exports/`) yuklash va Android ulashish oynasi (Telegram, Gmail, Drive...).
 *
 * NIMA UCHUN alohida fayl: eksport varag'i (`ExportSheet`) va bayonnoma varag'i (`MinutesSheet`)
 * aynan bir yo'ldan yuradi - yuklash qo'riqchisi, xato konverti va fayl nomi bir joyda.
 * Xatoni sababga aylantirish (va qaysi keyingi qadam) har varaqning o'zida.
 */
import type { TokenProvider } from '@/api/client';
import { downloadWithAuth, type DownloadProgress, type FileDownloader, type RawDownload } from '@/api/meetings';

export interface ShareNative {
  io: FileDownloader;
  /** Eksport papkasi (`.../cache/exports/`), oldingi fayllardan tozalangan (chiqishda ham - `lib/paths`). */
  freshDir(): Promise<string>;
  move(from: string, to: string): Promise<void>;
  canShare(): Promise<boolean>;
  share(uri: string, mimeType: string, dialogTitle: string): Promise<void>;
}

/**
 * NIMA UCHUN `expo-file-system/legacy` ning `createDownloadResumable`i: u xato statusda ham
 * tanani faylga yozib `status` qaytaradi - 409/503 dagi server kodi (`pdf_unavailable`,
 * `export_busy`, `available`) o'qiladi. Yangi `File.downloadFileAsync` esa faqat
 * "HTTP 503" deydi - PDF yo'qmi yoki server bandmi, ajratib bo'lmasdi. Oddiy `downloadAsync`
 * emas: u oqim o'rtasida uzilsa va'dani hech qachon tugatmasdi; resumable - xatoda reject
 * qiladi, bekor qilinadi (`cancelAsync`) va progress beradi (qo'riqchi shunga tayanadi).
 * `require` - native modullar faqat ulashish paytida yuklanadi (ekran va testlar ularsiz).
 */
export function nativeShare(): ShareNative {
  /* eslint-disable @typescript-eslint/no-require-imports */
  const FS = require('expo-file-system/legacy') as typeof import('expo-file-system/legacy');
  const Sharing = require('expo-sharing') as typeof import('expo-sharing');
  /* eslint-enable @typescript-eslint/no-require-imports */
  return {
    io: {
      async download(url, fileUri, headers, control) {
        const task = FS.createDownloadResumable(url, fileUri, { headers }, (p) =>
          control?.onProgress?.({ written: p.totalBytesWritten, total: p.totalBytesExpectedToWrite }),
        );
        const cancel = () => void task.cancelAsync().catch(() => {});
        control?.signal?.addEventListener('abort', cancel);
        try {
          const r = await task.downloadAsync();
          if (!r) throw new Error('cancelled');
          return { status: r.status, uri: r.uri, headers: r.headers ?? {} };
        } finally {
          control?.signal?.removeEventListener('abort', cancel);
        }
      },
      readText: (uri) => FS.readAsStringAsync(uri),
      remove: (uri) => FS.deleteAsync(uri, { idempotent: true }),
    },
    async freshDir() {
      const dir = `${FS.cacheDirectory ?? ''}exports/`;
      // Oldingi eksport (audio o'nlab MB bo'lishi mumkin) keshda yig'ilib qolmasin. Ulashishdan
      // DARHOL keyin emas, keyingi eksportda tozalanadi: qabul qilgan ilova (Telegram) faylni
      // ulashish oynasi yopilgandan keyin ham o'qib turgan bo'lishi mumkin.
      await FS.deleteAsync(dir, { idempotent: true });
      await FS.makeDirectoryAsync(dir, { intermediates: true });
      return dir;
    },
    move: (from, to) => FS.moveAsync({ from, to }),
    canShare: () => Sharing.isAvailableAsync(),
    share: (uri, mimeType, dialogTitle) => Sharing.shareAsync(uri, { mimeType, dialogTitle }),
  };
}

/** Faylga yuklash uchun vaqtinchalik nom (har urinish o'zinikini oladi). */
export function partFileName(): string {
  return `download-${Date.now()}.part`;
}

export interface ShareDownloadOptions {
  tokens: TokenProvider;
  /** `Accept-Language`: hujjatdagi sarlavhalar shu tilda. */
  language: string;
  signal?: AbortSignal;
  onProgress?: (p: DownloadProgress) => void;
}

/**
 * Toza eksport papkasiga vaqtinchalik nom bilan yuklaydi (`downloadWithAuth`: 401 - bitta
 * yangilash, xato konverti -> `ApiError`, uzilish qo'riqchisi). Fayl nomi va MIME'ni chaqiruvchi
 * javob sarlavhalaridan o'zi tanlaydi, keyin `placeForShare`.
 */
export async function downloadForShare(nat: ShareNative, url: string, o: ShareDownloadOptions): Promise<{ res: RawDownload; dir: string }> {
  const dir = await nat.freshDir();
  const res = await downloadWithAuth(url, `${dir}${partFileName()}`, {
    tokens: o.tokens,
    io: nat.io,
    language: o.language,
    signal: o.signal,
    onProgress: o.onProgress,
  });
  return { res, dir };
}

/** Yuklangan faylni odamga ko'rinadigan nomga ko'chiradi va uning URI'sini qaytaradi. */
export async function placeForShare(nat: ShareNative, dir: string, from: string, name: string): Promise<string> {
  // URI ichida nom kodlanadi: "#" yoki "%" bo'lsa ham `Uri.parse` yo'lni buzmasin.
  const target = `${dir}${encodeURIComponent(name)}`;
  await nat.move(from, target);
  return target;
}
