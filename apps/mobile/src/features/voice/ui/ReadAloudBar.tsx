/**
 * "Tinglash" kichik pleeri: javob o'qilayotganda yozish kartasi ustida turadigan pill.
 *
 *   🔊 O'qilmoqda   [⏸]  [✕]
 *
 * NIMA UCHUN Composer ichida va oqimda (absolute emas): chat ekrani (`index.tsx`) ga
 * tegilmaydi va pill hech qachon oxirgi xabarni yopmaydi - kartani biroz yuqoriga suradi.
 *
 * Chat ekranidan boshqa sahifaga o'tilsa o'qish to'xtaydi: pleer boshqaruvi faqat shu yerda -
 * boshqa sahifada ovoz to'xtatib bo'lmaydigan bo'lib yangrab qolardi.
 *
 * DIQQAT: chat ekrani ichida chiziladi. Chat ekrani testlari expo-router'ni faqat
 * `{ router }` bilan mock qiladi - `useFocusEffect` shu sababli "bo'lsa" ishlatiladi.
 * `readAloud` modulidan to'g'ridan-to'g'ri import (barrel emas).
 */
import * as Haptics from 'expo-haptics';
import * as ExpoRouter from 'expo-router';
import { Pause, Play, Volume2, X } from 'lucide-react-native';
import { useCallback, useEffect, useRef } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { PREVIEW_KEY, stopReadAloud, useReadAloud, useReadAloudControls } from '@/features/voice/readAloud';
import { useTheme } from '@/ui/theme';

import { announce, useScreenReader } from './useScreenReader';

type FocusEffect = (effect: () => void | (() => void)) => void;
/** Haqiqiy navigator ichida - expo-router'niki; mock'da (yo'q bo'lsa) - hech narsa. */
const useFocusEffectIfAny: FocusEffect = typeof ExpoRouter.useFocusEffect === 'function' ? (ExpoRouter.useFocusEffect as FocusEffect) : () => {};

export function ReadAloudBar() {
  const th = useTheme();
  const t = useT();
  const key = useReadAloud((s) => s.key);
  const phase = useReadAloud((s) => s.phase);
  const controls = useReadAloudControls();
  const screenReader = useScreenReader();

  // Chat ekrani fokusdan chiqdi (sozlamalar, yozuvlar...) - o'qish to'xtaydi.
  useFocusEffectIfAny(
    useCallback(
      () => () => {
        if (useReadAloud.getState().key !== PREVIEW_KEY) stopReadAloud();
      },
      [],
    ),
  );

  // TalkBack: faqat bosqich o'zgarishi (tayyorlanmoqda -> o'qilmoqda -> pauza) e'lon qilinadi,
  // har bo'lak emas - e'lon o'qilayotgan javob ustidan gapirmasin.
  const lastPhase = useRef(phase);
  useEffect(() => {
    if (lastPhase.current === phase) return;
    lastPhase.current = phase;
    if (!screenReader || key === null || key === PREVIEW_KEY) return;
    if (phase === 'playing') announce(t('nav.voice.reading'));
    else if (phase === 'paused') announce(t('nav.voice.listenPause'));
  }, [phase, key, screenReader, t]);

  if (key === null || key === PREVIEW_KEY) return null;

  const paused = phase === 'paused';
  // Bo'lak hisobi ("2/…") ichki narsa - odamga ma'nosiz; faqat holat.
  const label = phase === 'loading' ? t('nav.voice.loading') : t('nav.voice.reading');

  return (
    <View
      testID="readaloud-bar"
      style={[
        s.bar,
        { backgroundColor: th.surfaceAlt, borderColor: th.border },
        th.dark ? null : { shadowColor: th.text, shadowOpacity: 0.08, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
      ]}>
      <Volume2 size={16} color={th.brand} strokeWidth={2} />
      <Text style={[s.text, { color: th.textSoft }]} numberOfLines={1} testID="readaloud-label">
        {label}
      </Text>
      <SmallButton
        testID="readaloud-pause"
        label={t(paused ? 'nav.voice.listenResume' : 'nav.voice.listenPause')}
        onPress={() => {
          void Haptics.selectionAsync().catch(() => {});
          if (paused) controls.resume();
          else controls.pause();
        }}
        pressedBg={th.border}>
        {paused ? <Play size={16} color={th.text} strokeWidth={2} /> : <Pause size={16} color={th.text} strokeWidth={2} />}
      </SmallButton>
      <SmallButton testID="readaloud-stop" label={t('nav.voice.listenStop')} onPress={controls.stop} pressedBg={th.border}>
        <X size={16} color={th.text} strokeWidth={2} />
      </SmallButton>
    </View>
  );
}

function SmallButton(props: { testID: string; label: string; onPress: () => void; pressedBg: string; children: React.ReactNode }) {
  return (
    <Pressable
      testID={props.testID}
      accessibilityRole="button"
      accessibilityLabel={props.label}
      onPress={props.onPress}
      // 32 dp ko'rinadi, bosish nishoni 44 dp (barmoq bilan aniq).
      hitSlop={6}
      style={({ pressed }) => [s.btn, pressed ? { backgroundColor: props.pressedBg } : null]}>
      {props.children}
    </Pressable>
  );
}

const s = StyleSheet.create({
  bar: {
    alignSelf: 'center',
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    paddingLeft: 14,
    paddingRight: 4,
    marginBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  text: { fontSize: 13, lineHeight: 18, fontWeight: '600', maxWidth: 220 },
  btn: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
});
