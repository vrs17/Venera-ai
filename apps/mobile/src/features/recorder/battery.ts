/**
 * Batareya tejash sozlamasi (spec 2.3): Samsung "Hech qachon uxlamaydigan
 * ilovalar" ga qo'shish yo'li. REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
 * ruxsatini ATAYIN e'lon qilmaymiz (Play siyosati) - faqat sozlamani ochamiz.
 */
import * as Application from 'expo-application';
import * as IntentLauncher from 'expo-intent-launcher';
import { Linking, Platform } from 'react-native';

export async function openBatterySettings(): Promise<void> {
  if (Platform.OS !== 'android') return;
  try {
    await IntentLauncher.startActivityAsync(IntentLauncher.ActivityAction.IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
    return;
  } catch {
    /* ba'zi OEM'larda yo'q */
  }
  try {
    await IntentLauncher.startActivityAsync(IntentLauncher.ActivityAction.APPLICATION_DETAILS_SETTINGS, {
      data: `package:${Application.applicationId ?? 'uz.brbtech.venera.meetings'}`,
    });
    return;
  } catch {
    await Linking.openSettings().catch(() => {});
  }
}
