/**
 * Jonli suhbat ekranining pastdan ko'tariladigan "tuman"i (Claude ovozli rejimi kabi).
 *
 *   sovuq (ko'k)   - foydalanuvchi gapirayotganda, mikrofon balandligi bilan
 *   iliq (brend)   - Barno gapirayotganda, klipning o'z ovoz egri chizig'i bilan
 *
 * NIMA UCHUN shunday qurilgan:
 * - SVG gradientlar STATIK (hech bir SVG xossasi animatsiya qilinmaydi) - 30 Hz da React
 *   qayta chizilmaydi. Faqat `Animated.View` ning `opacity` va `transform` i native driver
 *   bilan o'zgaradi -> JS band bo'lsa ham 60 fps.
 * - Daraja (`subscribeLevel`) React holatiga TUSHMAYDI: `level.setValue` to'g'ridan-to'g'ri
 *   native tugunga yoziladi.
 * - Gradient id'lari har qatlam/blob uchun noyob: ba'zi renderer'larda id hujjat bo'yicha
 *   global, takrorlansa bir qatlam boshqasining rangini olib qo'yadi.
 * - "Harakatni kamaytirish" yoqilgan bo'lsa siljish va ko'tarilish yo'q - faqat shaffoflik
 *   (daraja baribir ko'rinadi).
 */
import { useEffect, useMemo, useState } from 'react';
import { Animated, Easing, StyleSheet, useWindowDimensions } from 'react-native';
import Svg, { Defs, Ellipse, LinearGradient, RadialGradient, Rect, Stop } from 'react-native-svg';

import type { FogSource, UseVoiceSession, VoiceStatus } from '@/features/voice';
import { darkTheme as D } from '@/ui/theme';

import { useReducedMotion } from './useReducedMotion';

export interface VoiceFogProps {
  subscribeLevel: UseVoiceSession['subscribeLevel'];
  status: VoiceStatus;
  micMuted: boolean;
  testID?: string;
}

type LayerId = 'cool' | 'warm';

interface Blob {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

const BLOBS: readonly Blob[] = [
  { cx: 24, cy: 100, rx: 46, ry: 40 },
  { cx: 76, cy: 100, rx: 46, ry: 36 },
  { cx: 50, cy: 106, rx: 62, ry: 48 },
];

const DRIFT_MS = [7000, 9000, 11000] as const;
/** Uchinchi blob kechroq boshlaydi - uchalasi bir maromda "nafas olmasin". */
const DRIFT_DELAY_MS = [0, 0, 1800] as const;
const WARM_MS = 450;
const BREATH_MS = 2400;
/**
 * "Nafas" kuchi. NIMA UCHUN 0.4 (0.25 emas): o'ylash paytida tuman tinglashdagidan
 * aniq farq qilsin - xona shovqini (u o'ylashda kuchsizlantiriladi) uni bosib ketmasin.
 */
const BREATH_GAIN = 0.4;
/**
 * Rang almashishi shuncha ushlab turilgandan keyin: Barno gapirayotganda yo'tal yoki
 * aks-sado bo'lib gapirish nomzodini bir-ikki kadr yig'sa tuman iliq-sovuq-iliq "lip-lip"
 * qilmasin.
 */
const SWITCH_HOLD_MS = 200;
/** Hech kim gapirmay shuncha o'tsa iliq rang so'nadi (mikrofon o'chgach tuman Barno rangida qolmasin). */
const NONE_FADE_MS = 1000;

/** Holat bo'yicha umumiy xiralik: o'chiq mikrofon, xato, ulanish - tuman "so'nadi". */
export function fogDim(status: VoiceStatus, micMuted: boolean): number {
  if (status === 'muted' || (micMuted && status === 'listening')) return 0.35;
  if (status === 'error') return 0.2;
  if (status === 'idle') return 0.5;
  return 1;
}

const COLORS: Record<LayerId, { base: string; blobs: readonly [string, string, string] }> = {
  cool: { base: D.tones.info.bg, blobs: [D.tones.info.fg, D.tones.info.fg, D.tones.info.fg] },
  warm: { base: D.brand, blobs: [D.tones.accent.fg, D.tones.accent.fg, D.brand] },
};

export function VoiceFog({ subscribeLevel, status, micMuted, testID = 'voice-fog' }: VoiceFogProps) {
  const { width, height } = useWindowDimensions();
  const H = Math.round(height * 0.55);
  const reduced = useReducedMotion();

  const [level] = useState(() => new Animated.Value(0));
  const [warm] = useState(() => new Animated.Value(0));
  const [breath] = useState(() => new Animated.Value(0));
  const [dim] = useState(() => new Animated.Value(fogDim(status, micMuted)));
  const [drift0] = useState(() => new Animated.Value(0));
  const [drift1] = useState(() => new Animated.Value(1));
  const [drift2] = useState(() => new Animated.Value(0));
  const drifts = useMemo(() => [drift0, drift1, drift2] as const, [drift0, drift1, drift2]);

  // Darajani native tugunga "bog'lab qo'yamiz": 0 ms native animatsiya qiymatni native
  // qiladi, keyingi `setValue` lar JS -> ko'prik -> native yo'lidan (render'siz) o'tadi.
  useEffect(() => {
    Animated.timing(level, { toValue: 0, duration: 0, useNativeDriver: true }).start();
  }, [level]);

  // Daraja va rang manbai: faqat obuna orqali (30 Hz), React holatisiz.
  useEffect(() => {
    /** Hozir ko'rsatilayotgan rang. */
    let shown: FogSource = 'none';
    /** Kelayotgan manba va u qachondan beri o'zgarmagan. */
    let candidate: FogSource = 'none';
    let since = 0;
    let anim: Animated.CompositeAnimation | null = null;
    const show = (to: 'barno' | 'user') => {
      shown = to;
      anim?.stop();
      anim = Animated.timing(warm, { toValue: to === 'barno' ? 1 : 0, duration: WARM_MS, easing: Easing.inOut(Easing.quad), useNativeDriver: true });
      anim.start();
    };
    const off = subscribeLevel((value, src) => {
      level.setValue(Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0);
      const now = Date.now();
      if (src !== candidate) {
        candidate = src;
        since = now;
      }
      const held = now - since;
      if (candidate === 'none') {
        // Gap orasidagi qisqa jimlikda rang qoladi; uzoq jimlikda iliq rang so'nadi.
        if (shown === 'barno' && held >= NONE_FADE_MS) show('user');
        return;
      }
      if (candidate !== shown && (shown === 'none' || held >= SWITCH_HOLD_MS)) show(candidate);
    });
    return () => {
      off();
      anim?.stop();
    };
  }, [subscribeLevel, level, warm]);

  // "Nafas": transkripsiya va o'ylash paytida tuman sekin ko'tarilib tushadi - jim ekran
  // "qotib qoldi" degan taassurot bermasin.
  const breathing = status === 'thinking' || status === 'transcribing';
  useEffect(() => {
    if (!breathing) {
      const back = Animated.timing(breath, { toValue: 0, duration: 300, easing: Easing.out(Easing.quad), useNativeDriver: true });
      back.start();
      return () => back.stop();
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(breath, { toValue: 1, duration: BREATH_MS / 2, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(breath, { toValue: 0, duration: BREATH_MS / 2, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [breathing, breath]);

  // Holat xiraligi silliq o'tadi (sakrash ko'zga tashlanadi).
  const dimTarget = fogDim(status, micMuted);
  useEffect(() => {
    const a = Animated.timing(dim, { toValue: dimTarget, duration: 300, easing: Easing.inOut(Easing.quad), useNativeDriver: true });
    a.start();
    return () => a.stop();
  }, [dimTarget, dim]);

  // Siljish: har blob o'z davri bilan chapga-o'ngga (7/9/11 s) - bir-biriga mos kelmaydi.
  useEffect(() => {
    if (reduced) {
      drifts.forEach((d) => d.stopAnimation());
      return;
    }
    const loops: Animated.CompositeAnimation[] = [];
    const timers: ReturnType<typeof setTimeout>[] = [];
    drifts.forEach((d, i) => {
      const from = i === 1 ? 1 : 0;
      const to = 1 - from;
      const half = DRIFT_MS[i] / 2;
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(d, { toValue: to, duration: half, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
          Animated.timing(d, { toValue: from, duration: half, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        ]),
      );
      loops.push(loop);
      if (DRIFT_DELAY_MS[i]) timers.push(setTimeout(() => loop.start(), DRIFT_DELAY_MS[i]));
      else loop.start();
    });
    return () => {
      timers.forEach(clearTimeout);
      loops.forEach((l) => l.stop());
    };
  }, [reduced, drifts]);

  const energy = useMemo(
    () => Animated.add(level, Animated.multiply(breath, BREATH_GAIN)).interpolate({ inputRange: [0, 1], outputRange: [0, 1], extrapolate: 'clamp' }),
    [level, breath],
  );

  const containerStyle = useMemo(
    () => ({
      opacity: energy.interpolate({ inputRange: [0, 1], outputRange: [0.42, 1] }),
      transform: reduced ? [] : [{ translateY: energy.interpolate({ inputRange: [0, 1], outputRange: [0.16 * H, 0] }) }],
    }),
    [energy, reduced, H],
  );

  const blobStyles = useMemo(() => drifts.map((d) => blobStyle(d, energy, reduced, width)), [drifts, energy, reduced, width]);

  const coolOpacity = useMemo(() => warm.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }), [warm]);

  return (
    <Animated.View testID={testID} pointerEvents="none" style={[s.wrap, { height: H, opacity: dim }]}>
      <Animated.View style={[StyleSheet.absoluteFill, containerStyle]}>
        <FogLayer id="cool" opacity={coolOpacity} blobStyles={blobStyles} />
        <FogLayer id="warm" opacity={warm} blobStyles={blobStyles} />
      </Animated.View>
    </Animated.View>
  );
}

type BlobStyle = ReturnType<typeof blobStyle>;

/** Blob harakati: drift (chap-o'ng) + ovoz bilan pastdan yuqoriga cho'zilish. */
function blobStyle(drift: Animated.Value, energy: Animated.AnimatedInterpolation<number>, reduced: boolean, width: number) {
  return {
    // Pastki chetdan cho'ziladi - blob yuqoriga "ko'tariladi", pastdan uzilmaydi.
    transformOrigin: 'bottom',
    transform: reduced
      ? []
      : [
          { translateX: drift.interpolate({ inputRange: [0, 1], outputRange: [-0.06 * width, 0.06 * width] }) },
          { scaleY: energy.interpolate({ inputRange: [0, 1], outputRange: [0.9, 1.12] }) },
        ],
  } as const;
}

/** Bitta rang qatlami: statik asos + uchta suzuvchi blob. Faqat qatlam shaffofligi o'zgaradi. */
function FogLayer({ id, opacity, blobStyles }: { id: LayerId; opacity: Animated.Value | Animated.AnimatedInterpolation<number>; blobStyles: BlobStyle[] }) {
  const c = COLORS[id];
  return (
    <Animated.View testID={`voice-fog-${id}`} style={[StyleSheet.absoluteFill, { opacity }]}>
      <StaticSvg>
        <Defs>
          <LinearGradient id={`${id}-base`} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={c.base} stopOpacity={0} />
            <Stop offset="0.55" stopColor={c.base} stopOpacity={0.16} />
            <Stop offset="1" stopColor={c.base} stopOpacity={0.5} />
          </LinearGradient>
        </Defs>
        <Rect x="0" y="0" width="100" height="100" fill={`url(#${id}-base)`} />
      </StaticSvg>
      {BLOBS.map((b, i) => (
        <Animated.View key={i} style={[StyleSheet.absoluteFill, blobStyles[i]]}>
          <StaticSvg>
            <Defs>
              <RadialGradient id={`${id}-blob${i}`} cx="50%" cy="50%" r="50%">
                <Stop offset="0" stopColor={c.blobs[i]} stopOpacity={0.6} />
                <Stop offset="0.55" stopColor={c.blobs[i]} stopOpacity={0.22} />
                <Stop offset="1" stopColor={c.blobs[i]} stopOpacity={0} />
              </RadialGradient>
            </Defs>
            <Ellipse cx={b.cx} cy={b.cy} rx={b.rx} ry={b.ry} fill={`url(#${id}-blob${i})`} />
          </StaticSvg>
        </Animated.View>
      ))}
    </Animated.View>
  );
}

/** 0..100 koordinatali, butun qatlamga cho'ziladigan SVG (gradient shakli ekran nisbatiga moslashadi). */
function StaticSvg({ children }: { children: React.ReactNode }) {
  return (
    <Svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
      {children}
    </Svg>
  );
}

const s = StyleSheet.create({
  wrap: { position: 'absolute', left: 0, right: 0, bottom: 0, overflow: 'visible' },
});
