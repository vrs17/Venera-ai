/**
 * Jonli suhbat ekranining pastki qismi (Claude ovozli rejimi kabi):
 *
 *            holat yozuvi (Tinglayapman / O'ylayapman… / xato)
 *   [✦ Pro]          ( 🎤 )          [🔈] [✕]
 *
 * - Markazdagi katta tugma mikrofonni o'chiradi/yoqadi (suhbat tugamaydi).
 * - Mikrofon atrofidagi halqa foydalanuvchi ovozi balandligi bilan kattalashadi -
 *   "meni eshityaptimi?" savoliga ko'z bilan javob. Halqa ham 30 Hz obuna orqali, React
 *   holatisiz (native driver).
 * - ✕ suhbatni tugatadi: mikrofon bo'shaydi, ovoz to'xtaydi; ketayotgan javob baribir
 *   chatga matn bo'lib tushadi. Quloq rejimida (telefon quloqda) ✕ ni BOSIB TURISH kerak:
 *   yonoq tegib ketsa suhbat tugab qolmasin.
 * - Karnay tugmasi faqat ovoz bo'lganda (uz); ru/en da hech narsa yangramaydi.
 *
 * Ekran DOIM qorong'i (`darkTheme`) - ilova mavzusidan qat'i nazar.
 */
import * as Haptics from 'expo-haptics';
import { Ear, Mic, MicOff, Sparkles, X, type LucideIcon } from 'lucide-react-native';
import { useEffect, useRef, useState } from 'react';
import { Animated, Linking, Pressable, StyleSheet, Text, View, type AccessibilityActionEvent } from 'react-native';

import { usePro } from '@/features/chat/proStore';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { UseVoiceSession, VoiceActions, VoiceSnapshot } from '@/features/voice';
import { showToast } from '@/ui/errors';
import { darkTheme as D } from '@/ui/theme';

import { useReducedMotion } from './useReducedMotion';
import { announce, useScreenReader } from './useScreenReader';
import { statusLine } from './voiceText';

/** Quloq rejimida ✕ shuncha bosib turilsa tugaydi. */
const END_HOLD_MS = 600;

export interface VoiceControlsProps {
  snap: VoiceSnapshot;
  actions: VoiceActions;
  subscribeLevel: UseVoiceSession['subscribeLevel'];
  /** ✕ va Android "orqaga" bitta yo'ldan: sessiya yopiladi, keyin ekran. */
  onEnd: () => void;
  /** "Matnsiz" rejimda holat katta sarlavhada - pastda faqat xato/eslatma qoladi. */
  stateInTitle?: boolean;
}

export function VoiceControls({ snap, actions, subscribeLevel, onEnd, stateInTitle }: VoiceControlsProps) {
  const t = useT();
  const screenReader = useScreenReader();
  const line = statusLine(snap, t);
  const showLine = !(stateInTitle && line.kind === 'state');
  const micDisabled = snap.status === 'idle' || snap.status === 'error';
  const canInterrupt = snap.status === 'speaking' || !!snap.holdText;

  // TalkBack: holat o'zgarishlari e'lon qilinmaydi (Barno ustidan gapirib, mikrofonga
  // tushardi). Faqat "navbat sizda" - Barno gapirib bo'lgach, hech narsa yangramayotganda.
  const prevStatus = useRef(snap.status);
  useEffect(() => {
    const from = prevStatus.current;
    prevStatus.current = snap.status;
    if (screenReader && from === 'speaking' && snap.status === 'listening' && !snap.hearing) announce(t('nav.voice.listening'));
  }, [snap.status, snap.hearing, screenReader, t]);

  const micActions = canInterrupt ? [{ name: 'activate' as const }, { name: 'interrupt', label: t('nav.voice.listenStop') }] : undefined;
  const onMicAction = (e: AccessibilityActionEvent) => {
    if (e.nativeEvent.actionName === 'interrupt') actions.interrupt();
    else if (e.nativeEvent.actionName === 'activate' && !micDisabled) actions.toggleMute();
  };

  return (
    <View>
      <Text
        testID="voice-status"
        // Faqat xato va eslatma e'lon qilinadi; holat matni (har soniyada o'zgaradi) - yo'q.
        accessibilityLiveRegion={line.kind === 'state' ? 'none' : 'polite'}
        numberOfLines={2}
        style={[s.status, line.kind === 'error' ? { color: D.tones.bad.fg } : null, showLine ? null : s.hidden]}>
        {showLine ? line.text : ' '}
      </Text>

      {snap.status === 'error' ? (
        <View style={s.errorRow}>
          <VoicePill label={t('common.retry')} onPress={actions.retry} testID="voice-retry" />
          {snap.error === 'mic_denied' ? (
            <VoicePill label={t('nav.voice.openSettings')} onPress={() => void Linking.openSettings().catch(() => {})} testID="voice-open-settings" />
          ) : null}
        </View>
      ) : null}

      <View style={s.row}>
        <View style={s.left}>
          <ProPill />
        </View>

        <View style={s.micWrap}>
          <LevelRing subscribeLevel={subscribeLevel} />
          <Pressable
            testID="voice-mic"
            accessibilityRole="switch"
            accessibilityLabel={t('nav.voice.mic')}
            accessibilityState={{ checked: !snap.micMuted, disabled: micDisabled }}
            // TalkBack: Barno gapirayotganda to'xtatish - qo'shimcha amal (matnga tegish
            // TalkBack'da ishlamaydi: u bosishni emas, "accessibility click" yuboradi).
            accessibilityActions={micActions}
            onAccessibilityAction={micActions ? onMicAction : undefined}
            disabled={micDisabled}
            onPress={() => {
              void Haptics.selectionAsync().catch(() => {});
              actions.toggleMute();
            }}
            style={({ pressed }) => [
              s.mic,
              snap.micMuted ? s.micMuted : s.micOn,
              { opacity: micDisabled ? 0.45 : 1, transform: [{ scale: pressed ? 0.94 : 1 }] },
            ]}>
            {snap.micMuted ? <MicOff size={32} color={D.bg} strokeWidth={2} /> : <Mic size={32} color={D.text} strokeWidth={2} />}
          </Pressable>
        </View>

        <View style={s.right}>
          {snap.canSpeak ? (
            <RoundIcon
              testID="voice-speaker"
              role="switch"
              checked={snap.earpiece}
              // Doimiy nom + holat: "Quloq dinamigi, yoqilgan/o'chirilgan" (nom almashsa
              // TalkBack "Karnay, o'chiq" deb, ishlab turgan karnayni o'chiq deb aytardi).
              label={t('nav.voice.earpiece')}
              icon={Ear}
              size={48}
              bg={snap.earpiece ? D.tones.info.bg : D.composerBtn}
              borderColor={snap.earpiece ? D.tones.info.fg : undefined}
              color={snap.earpiece ? D.tones.info.fg : D.text}
              onPress={() => {
                void Haptics.selectionAsync().catch(() => {});
                actions.setEarpiece(!snap.earpiece);
              }}
            />
          ) : null}
          <RoundIcon
            testID="voice-end"
            label={t('nav.voice.end')}
            hint={snap.earpiece ? t('nav.voice.holdToEnd') : undefined}
            icon={X}
            size={52}
            iconSize={24}
            strokeWidth={2.25}
            bg={D.text}
            color={D.bg}
            onPress={snap.earpiece ? () => showToast(t('nav.voice.holdToEnd')) : onEnd}
            onLongPress={snap.earpiece ? onEnd : undefined}
            delayLongPress={END_HOLD_MS}
          />
        </View>
      </View>
    </View>
  );
}

/** Pro kaliti - Composer'dagi bilan bir xil qoida (qoldiq tugasa toast). */
function ProPill() {
  const t = useT();
  const available = usePro((x) => x.available);
  const left = usePro((x) => x.remaining);
  const proOn = useSettings((x) => x.proOn);
  if (!available) return null;
  const spent = left !== null && left <= 0;
  const active = proOn && !spent;
  const badge = left !== null && left <= 3 ? Math.max(0, left) : null;
  const color = active ? D.brand : spent ? D.textFaint : D.textSoft;
  return (
    <Pressable
      testID="voice-pro"
      accessibilityRole="switch"
      accessibilityState={{ checked: active }}
      accessibilityLabel={left !== null ? `${t('pro.label')} · ${t('pro.left', { n: left })}` : t('pro.label')}
      hitSlop={6}
      onPress={() => {
        if (spent) {
          showToast(t('pro.exhausted'));
          return;
        }
        void Haptics.selectionAsync().catch(() => {});
        useSettings.getState().set({ proOn: !proOn });
      }}
      style={({ pressed }) => [s.pro, pressed && s.pressed]}>
      {/* Yoqilgan: shaffof brend rangi NOAYDIN asos ustida - Barno gapirganda pastdagi
          to'q sariq tuman ustida ham "Pro" o'qilsin (aks holda ~1.6:1 kontrast). */}
      {active ? <View pointerEvents="none" style={s.proTint} /> : null}
      <Sparkles size={16} color={color} strokeWidth={2} />
      <Text style={[s.proText, { color }]}>{badge !== null ? `${t('pro.label')} · ${badge}` : t('pro.label')}</Text>
    </Pressable>
  );
}

/** Mikrofon atrofidagi halqa: faqat foydalanuvchi ovozida ko'rinadi (Barno gapirsa - yo'q). */
function LevelRing({ subscribeLevel }: { subscribeLevel: UseVoiceSession['subscribeLevel'] }) {
  const reduced = useReducedMotion();
  const [ring] = useState(() => new Animated.Value(0));
  useEffect(() => {
    // Qiymatni native tugunga o'tkazamiz - keyingi setValue'lar render'siz.
    Animated.timing(ring, { toValue: 0, duration: 0, useNativeDriver: true }).start();
    return subscribeLevel((lv, src) => ring.setValue(src === 'user' && Number.isFinite(lv) ? Math.max(0, Math.min(1, lv)) : 0));
  }, [subscribeLevel, ring]);
  return (
    <Animated.View
      testID="voice-level-ring"
      pointerEvents="none"
      style={[
        s.ring,
        {
          opacity: ring.interpolate({ inputRange: [0, 1], outputRange: [0, 0.8] }),
          // "Harakatni kamaytirish": halqa kattalashmaydi, faqat yorqinligi o'zgaradi.
          transform: reduced ? [] : [{ scale: ring.interpolate({ inputRange: [0, 1], outputRange: [1, 1.18] }) }],
        },
      ]}
    />
  );
}

/**
 * Qorong'i ekran uchun doira tugma. NIMA UCHUN `@/ui/IconButton` emas: u bosilgandagi
 * fonni ILOVA mavzusidan oladi - yorug' mavzuda qora ekranda oq "chaqnash" bo'lardi.
 */
export function RoundIcon(props: {
  testID: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  size: number;
  iconSize?: number;
  strokeWidth?: number;
  bg: string;
  borderColor?: string;
  color: string;
  role?: 'button' | 'switch';
  checked?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
  delayLongPress?: number;
}) {
  const Icon = props.icon;
  const role = props.role ?? 'button';
  return (
    <Pressable
      testID={props.testID}
      accessibilityRole={role}
      accessibilityLabel={props.label}
      accessibilityHint={props.hint}
      accessibilityState={role === 'switch' ? { checked: !!props.checked } : undefined}
      onPress={props.onPress}
      onLongPress={props.onLongPress}
      delayLongPress={props.delayLongPress}
      hitSlop={4}
      style={({ pressed }) => [
        {
          width: props.size,
          height: props.size,
          borderRadius: props.size / 2,
          backgroundColor: props.bg,
          borderWidth: props.borderColor ? 1 : 0,
          borderColor: props.borderColor,
          alignItems: 'center',
          justifyContent: 'center',
          transform: [{ scale: pressed ? 0.92 : 1 }],
        },
      ]}>
      <Icon size={props.iconSize ?? 22} color={props.color} strokeWidth={props.strokeWidth ?? 2} />
    </Pressable>
  );
}

function VoicePill({ label, onPress, testID }: { label: string; onPress: () => void; testID: string }) {
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={label} onPress={onPress} hitSlop={4} style={({ pressed }) => [s.pill, pressed && s.pressed]}>
      <Text style={s.pillText}>{label}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  status: { color: D.textSoft, fontSize: 14, lineHeight: 19, fontWeight: '500', textAlign: 'center', marginBottom: 18, paddingHorizontal: 24 },
  hidden: { opacity: 0 },
  errorRow: { flexDirection: 'row', justifyContent: 'center', gap: 10, marginBottom: 14, paddingHorizontal: 16, flexWrap: 'wrap' },
  pill: { height: 40, borderRadius: 20, paddingHorizontal: 18, justifyContent: 'center', backgroundColor: D.composerBtn },
  pillText: { color: D.text, fontSize: 14, lineHeight: 19, fontWeight: '600' },
  row: { height: 84, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center' },
  left: { flex: 1, alignItems: 'flex-start' },
  right: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 12 },
  micWrap: { width: 80, height: 80, alignItems: 'center', justifyContent: 'center' },
  ring: { position: 'absolute', width: 80, height: 80, borderRadius: 40, borderWidth: 2, borderColor: D.tones.info.fg },
  mic: { width: 80, height: 80, borderRadius: 40, alignItems: 'center', justifyContent: 'center' },
  micOn: { backgroundColor: D.composerBtn, borderWidth: 1, borderColor: D.borderStrong },
  micMuted: { backgroundColor: D.text },
  pro: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: 40,
    paddingLeft: 12,
    paddingRight: 15,
    borderRadius: 20,
    overflow: 'hidden',
    backgroundColor: D.composerBtn,
  },
  proTint: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, borderRadius: 20, borderWidth: 1, borderColor: D.brand, backgroundColor: D.brandSoft },
  proText: { fontSize: 14, fontWeight: '600' },
  pressed: { opacity: 0.8 },
});
