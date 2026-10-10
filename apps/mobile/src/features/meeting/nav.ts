/**
 * Yozuv o'chirilgandan keyin sahifadan chiqish.
 *
 * NIMA UCHUN `router.back()` yetmaydi: sahifa deep link (`venera-rec://meeting/...`) yoki
 * bildirishnomadan ochilgan bo'lsa orqada ekran yo'q - `back()` hech narsa qilmaydi va
 * foydalanuvchi o'chirilgan yozuv sahifasida qolib ketadi. U holda ro'yxatga o'tamiz.
 */
import { router } from 'expo-router';

export function leaveRecording(): void {
  if (router.canGoBack()) router.back();
  else router.replace('/meetings');
}
