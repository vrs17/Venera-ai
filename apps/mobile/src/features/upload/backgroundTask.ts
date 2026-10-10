/**
 * Xavfsizlik to'ri (spec 7.5): ilova yopiq bo'lsa ham navbat kamida
 * ~15 daqiqada bir yuklanadi (expo-background-task / WorkManager).
 *
 * `defineTask` modul darajasida chaqirilishi SHART (komponent ichida emas) -
 * tizim ilovani fonda ko'targanda JS shu faylni yuklab vazifani topadi.
 * Asosiy triggerlar baribir: ilova ochilishi, AppState active, tarmoq
 * qaytishi va Stop.
 */
import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

export const UPLOAD_TASK = 'venera-upload-queue';
export const MIN_INTERVAL_MIN = 15;

TaskManager.defineTask(UPLOAD_TASK, async () => {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { getAppServices } = require('@/services') as typeof import('@/services');
    const s = await getAppServices();
    await s.uploader.runOnce();
    return BackgroundTask.BackgroundTaskResult.Success;
  } catch {
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
});

export async function registerUploadTask(): Promise<void> {
  try {
    const status = await BackgroundTask.getStatusAsync();
    if (status !== BackgroundTask.BackgroundTaskStatus.Available) return;
    if (await TaskManager.isTaskRegisteredAsync(UPLOAD_TASK)) return;
    await BackgroundTask.registerTaskAsync(UPLOAD_TASK, { minimumInterval: MIN_INTERVAL_MIN });
  } catch {
    /* fon vazifasi ixtiyoriy */
  }
}
