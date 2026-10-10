/**
 * Hali yuklanmagan yozuvni telefondan o'chirish (spec 3.4).
 *
 * Tartib: avval navbat qatori, keyin fayl, keyin (server id bo'lsa) serverdagi
 * tugallanmagan yig'ilish. NIMA UCHUN qator birinchi: uploader shu qatorni
 * ishlayotgan bo'lsa, `store.update` yo'q qator uchun null qaytaradi va qator qayta
 * yozilmaydi - ya'ni o'chirilgan yozuv "tirilib" qolmaydi. Server tomoni - eng
 * yaxshi urinish: tarmoq bo'lmasa ham server 72 soatdan keyin tugallanmagan
 * yuklashni o'zi tozalaydi.
 *
 * Yozilayotgan qator o'chirilmaydi: fayl hali ochiq, yozuvchi unga yozmoqda.
 */
import type { MeetingsApi } from '@/api/meetings';

import type { QueueRow, QueueStore } from './queueStore';
import type { FileAccess } from './uploader';

export interface DiscardDeps {
  queue: Pick<QueueStore, 'remove'>;
  files: Pick<FileAccess, 'remove'>;
  meetings: Pick<MeetingsApi, 'remove'>;
}

/** true - o'chirildi; false - rad etildi (yozuv davom etmoqda). */
export async function discardLocalRecording(deps: DiscardDeps, row: QueueRow): Promise<boolean> {
  if (row.state === 'recording') return false;
  await deps.queue.remove(row.clientId);
  try {
    await deps.files.remove(row.fileUri);
  } catch {
    /* fayl allaqachon yo'q - qator baribir o'chdi */
  }
  if (row.serverId) {
    try {
      void Promise.resolve(deps.meetings.remove(row.serverId)).catch(() => {});
    } catch {
      /* sinxron xato ham foydalanuvchini to'xtatmasin */
    }
  }
  return true;
}
