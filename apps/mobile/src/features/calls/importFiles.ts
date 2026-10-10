/**
 * "Ulashish -> Barno AI": ImportActivity `imports/` ga nusxalagan fayllar bilan ishlash -
 * meta o'qish, holat (yuborsa bo'ladimi), navbatga ko'chirish va tashlab yuborish.
 *
 * Tasdiqlanmagan fayl `imports/` da qoladi: "Bekor qilish" va yuborilmay qolganlar shu
 * yerda o'chiriladi, chiqishda esa butun papka (integratsiya eslatmasi).
 */
import * as Crypto from 'expo-crypto';
import { File } from 'expo-file-system';

import { getImportMeta, removeImport, type ImportMeta } from '@/features/entry/nativeEntry';
import { recordingFile, toFileUri } from '@/lib/paths';
import { uuidV4 } from '@/lib/uuid';
import type { Services } from '@/services';

import type { ImportSendDeps } from './send';

export type ImportItemStatus = 'ok' | 'missing' | 'unsupported' | 'too_large';

export interface ImportItem {
  name: string;
  meta: ImportMeta | null;
}

export function importItemStatus(it: ImportItem, maxBytes: number | null): ImportItemStatus {
  if (!it.meta || it.meta.sizeBytes <= 0) return 'missing';
  if (!it.meta.contentType) return 'unsupported';
  if (maxBytes && it.meta.sizeBytes > maxBytes) return 'too_large';
  return 'ok';
}

export async function loadImportItems(names: string[]): Promise<ImportItem[]> {
  return Promise.all(names.map(async (name) => ({ name, meta: await getImportMeta(name).catch(() => null) })));
}

/** Yuborilmaydigan fayllarni `imports/` dan o'chiradi (begona ilovadan kelgan audio telefonda qolib ketmasin). */
export function discardImports(names: string[]): void {
  for (const n of names) removeImport(n);
}

export function importSendDeps(services: Pick<Services, 'queue'>): ImportSendDeps {
  return {
    queue: services.queue,
    moveIntoRecordings(meta, clientId, ext) {
      const dst = recordingFile(clientId, ext);
      new File(toFileUri(meta.path)).moveSync(dst);
      return dst.uri;
    },
    removeImport,
    newClientId: () => uuidV4((n) => Crypto.getRandomBytes(n)),
  };
}
