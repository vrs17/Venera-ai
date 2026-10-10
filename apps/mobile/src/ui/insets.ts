/**
 * Xavfsiz zona chekinishlari (status bar, navigatsiya paneli).
 *
 * NIMA UCHUN `useSafeAreaInsets` emas: u provayder bo'lmasa XATO tashlaydi -
 * `renderRouter` testlari va alohida komponent testlari `SafeAreaProvider`siz
 * yuradi. Bu hook provayder bo'lmasa nollarni qaytaradi va hech qachon yiqilmaydi.
 */
import { useContext } from 'react';
import { SafeAreaInsetsContext } from 'react-native-safe-area-context';

export interface SafeInsets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

const ZERO: SafeInsets = { top: 0, bottom: 0, left: 0, right: 0 };

export function useSafeInsets(): SafeInsets {
  return useContext(SafeAreaInsetsContext) ?? ZERO;
}
