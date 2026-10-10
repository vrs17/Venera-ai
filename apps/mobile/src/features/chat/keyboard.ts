/**
 * Klaviatura -> chat ekrani ostidagi bo'shliq.
 *
 * NIMA UCHUN: RN 0.86 / Android 15+ edge-to-edge - oyna klaviatura chiqqanda
 * QISQARMAYDI, ekran to'liq balandlikda qoladi va kompozer klaviatura ostida
 * qolardi. Shuning uchun ekran pastiga aynan klaviatura balandligicha bo'shliq
 * qo'shamiz: RN bergan balandlik navigatsiya panelisiz (`ime - systemBars`),
 * panel balandligi (`insets.bottom`) qo'shiladi.
 *
 * Tizim oynani baribir qisqartirgan bo'lsa (eski rejim) - qisqargan qism
 * ayiriladi, bo'shliq ikki marta qo'shilmaydi. iOS'da YO'Q: WKWebView klaviaturani
 * o'zi `visualViewport` orqali aytadi (Mini App buni allaqachon biladi).
 */
import { useEffect, useRef, useState } from 'react';
import { Keyboard, Platform, type LayoutChangeEvent } from 'react-native';

export function keyboardPadding(p: { keyboard: number; navInset: number; baseHeight: number; currentHeight: number }): number {
  if (!(p.keyboard > 0)) return 0;
  const shrunk = Math.max(0, p.baseHeight - p.currentHeight);
  return Math.max(0, Math.round(p.keyboard + Math.max(0, p.navInset) - shrunk));
}

/** `{paddingBottom, onLayout}` - ekran o'ramasiga. */
export function useKeyboardPadding(navInset: number): { paddingBottom: number; onLayout: (e: LayoutChangeEvent) => void } {
  const [keyboard, setKeyboard] = useState(0);
  const [heights, setHeights] = useState({ base: 0, current: 0 });
  const keyboardRef = useRef(0);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const show = Keyboard.addListener('keyboardDidShow', (e) => {
      keyboardRef.current = Math.max(0, e?.endCoordinates?.height ?? 0);
      setKeyboard(keyboardRef.current);
    });
    const hide = Keyboard.addListener('keyboardDidHide', () => {
      keyboardRef.current = 0;
      setKeyboard(0);
    });
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  const onLayout = (e: LayoutChangeEvent) => {
    const h = e.nativeEvent.layout.height;
    // Klaviatura yopiq paytdagi balandlik - "to'liq" o'lcham.
    setHeights((prev) => ({ base: keyboardRef.current > 0 ? prev.base || h : h, current: h }));
  };

  return {
    paddingBottom: keyboardPadding({ keyboard, navInset, baseHeight: heights.base, currentHeight: heights.current }),
    onLayout,
  };
}
