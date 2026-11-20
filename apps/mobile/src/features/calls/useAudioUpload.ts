/**
 * Plaud ro'yxatidagi "Audio/video yuklash": tizim fayl oynasi (expo-document-picker - audio,
 * `application/ogg` va video, bir nechta fayl; m4a, aac, mp3, wav, ogg, mp4, mov) -> `imports/` (`pickAudio`) -> mavjud
 * `/import` tasdiq ekrani ("Ulashish -> Barno" bilan bir yo'l). Hech bir fayl qabul qilinmasa -
 * sababi toast'da (format, mazmun, hajm, joy): odamni bo'sh tasdiq ekraniga olib bormaymiz.
 *
 * NIMA UCHUN `copyToCacheDirectory: false`: aks holda tanlash oynasi faylni ASOSIY oqimda keshga
 * nusxalaydi (katta yozuvda ilova qotadi), keyin biz yana bir marta nusxalardik. `content://` ni
 * expo-file-system fon oqimida to'g'ridan-to'g'ri `imports/` ga nusxalaydi.
 *
 * NIMA UCHUN `require` bosilganda: modul yuklanishi bilan native qismni so'raydi - u yo'q eski
 * dev client'da (yangi native modul hali yig'ilmagan) butun Plaud ekrani yiqilardi. Endi faqat
 * "Fayl tanlash oynasini ochib bo'lmadi" deyiladi (ExportSheet'dagi native qatlam kabi).
 */
import type { DocumentPickerResult } from 'expo-document-picker';
import { router } from 'expo-router';
import { useCallback, useRef, useState } from 'react';

import { useAuth } from '@/features/auth/authStore';
import { buildImportPath } from '@/features/entry/deepLink';
import { useT } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { showToast } from '@/ui/errors';

import { limitMb } from './feedback';
import { appImportsDir, audioUploadSupported, importPickedAudio, MAX_COPY_BYTES, MAX_VIDEO_COPY_BYTES, PICK_MIME_TYPES, type PickSkipReason } from './pickAudio';

/**
 * Hech bir fayl qabul qilinmadi -> "Audio qo'shilmadi: <sabab>" (sabab gap ichida kichik harf
 * bilan, `calls.sendFailed` kabi). Hajm - server chegarasi (bilinsa), aks holda nusxa chegarasi.
 */
export function pickFailedText(t: TFn, reason: PickSkipReason | null, maxBytes: number | null, maxVideoBytes: number | null = null): string {
  return t('calls.pick.failed', { reason: pickReasonText(t, reason, maxBytes, maxVideoBytes) });
}

function pickReasonText(t: TFn, reason: PickSkipReason | null, maxBytes: number | null, maxVideoBytes: number | null): string {
  switch (reason) {
    case 'unsupported':
      return t('calls.pick.unsupported');
    case 'mismatch':
      return t('calls.pick.mismatch');
    case 'video_unsupported':
      return t('calls.pick.videoUnsupported');
    case 'video_too_large':
      return t('calls.err.tooLarge', { mb: limitMb(maxVideoBytes ?? MAX_VIDEO_COPY_BYTES) });
    case 'too_large':
      return t('calls.err.tooLarge', { mb: limitMb(maxBytes ?? MAX_COPY_BYTES) });
    case 'no_space':
      return t('calls.err.space');
    default:
      return t('calls.err.read');
  }
}

export function useAudioUpload(): { supported: boolean; busy: boolean; pick: () => Promise<void> } {
  const t = useT();
  const maxBytes = useAuth((s) => s.config?.maxUploadBytes || null);
  const maxVideoBytes = useAuth((s) => s.config?.maxVideoUploadBytes || null);
  // Native funksiyalar mavjudligi ishga tushgandan keyin o'zgarmaydi - bir marta o'qiladi.
  const [supported] = useState(audioUploadSupported);
  const [busy, setBusy] = useState(false);
  // Ikki marta bosish ikkinchi oynani ochmasin (native "picking in progress" xatosi beradi).
  const running = useRef(false);

  const pick = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    try {
      let res: DocumentPickerResult;
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const DocumentPicker = require('expo-document-picker') as typeof import('expo-document-picker');
        res = await DocumentPicker.getDocumentAsync({ type: [...PICK_MIME_TYPES], multiple: true, copyToCacheDirectory: false });
      } catch {
        showToast(t('calls.pick.openFailed'));
        return;
      }
      if (res.canceled || !res.assets?.length) return;
      const out = await importPickedAudio(appImportsDir(), res.assets);
      if (out.files.length) {
        // `n` - har tanlash noyob: tasdiq ekrani ochiq turganda ham yangi ro'yxat o'qiladi.
        router.push(buildImportPath({ files: out.files, skipped: out.skipped, n: String(Date.now()) }));
        return;
      }
      showToast(pickFailedText(t, out.reason, maxBytes, maxVideoBytes));
    } catch {
      showToast(pickFailedText(t, 'read', maxBytes, maxVideoBytes));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [t, maxBytes, maxVideoBytes]);

  return { supported, busy, pick };
}
