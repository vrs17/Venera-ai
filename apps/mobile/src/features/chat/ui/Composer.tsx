/**
 * Yozish maydoni - Claude ilovasidagi kabi BITTA karta (Mini App `Composer.vue` bilan
 * bir xil dizayn):
 *
 *   tepada   matn (butun kenglikda, 8 qatorgacha o'sadi, ekranning ~30% idan oshmaydi)
 *   ostida   chapda "Pro" (dvigatel ruxsat bersa), o'ngda mikrofon va yuborish
 *
 * O'ngdagi asosiy tugma: matn bor - brend rangidagi ↑ yuborish; matn yo'q - "Jonli"
 * (ovozli suhbat, Claude'dagi ovoz tugmasi kabi "siyoh" rangida); javob ketayotganda -
 * to'xtatish. Mikrofon har doim diktovka. Ovoz yozilayotganda karta bitta qatorga aylanadi:
 *
 *   ✕ bekor   ~~to'lqin~~ 0:07   ■ to'xtatib tahrirlash   ↑ darhol yuborish
 *
 * Diktovka: mikrofon -> AAC (yig'ilish yozuvi bilan bir xil sozlama, Gapi uni o'qiydi)
 * -> `/stt/transcribe` -> matn maydonga TUSHADI (eski matn o'rniga - qayta aytilgan gap
 * eskisini almashtiradi). ↑ bosilgan bo'lsa matn tushishi bilan o'zi yuboriladi.
 *
 * "Tinglash" pleeri (javobni ovoz chiqarib o'qish) kartaning USTIDA, oqim ichida
 * chiziladi (absolute emas) - oxirgi xabarni hech qachon yopmaydi. `index.tsx` ga
 * tegmaslik uchun u shu yerda.
 */
import * as Haptics from 'expo-haptics';
import {
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  type RecordingOptions,
} from 'expo-audio';
import { router } from 'expo-router';
import { ArrowUp, AudioLines, Headset, Mic, Sparkles, Square, X } from 'lucide-react-native';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Keyboard,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
  type NativeSyntheticEvent,
  type TextInputContentSizeChangeEventData,
} from 'react-native';

import type { ChatApi } from '@/api/chat';
import { StreamAbortedError } from '@/api/client';
import { proActiveNow, usePro } from '@/features/chat/proStore';
import { levelFromDb } from '@/features/recorder/metering';
import { MEETING_PRESET } from '@/features/recorder/preset';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { useSettings, useT } from '@/features/settings/settingsStore';
// Chat ekrani: barrel (`@/features/voice`) EMAS - u expo-router hook'larini olib keladi.
import { PREVIEW_KEY, stopReadAloud, useReadAloud } from '@/features/voice/readAloud';
import { ReadAloudBar } from '@/features/voice/ui/ReadAloudBar';
import { errorText, showToast } from '@/ui/errors';
import { useTheme, type Theme } from '@/ui/theme';

/** Diktovka: yig'ilish yozuvi bilan bir xil format (AAC ADTS, 16 kHz) - lekin keshda. */
const DICTATION_PRESET: RecordingOptions = { ...MEETING_PRESET, directory: 'cache' };
const MAX_MS = 120_000;
const MIN_MS = 400;
/** Butun yozuvda shundan baland ovoz bo'lmasa - gap yo'q, yuklanmaydi. */
const SPEECH_DB = -42;
const LINE = 24;
const MAX_ROWS = 8;
const BAR_COUNT = 40;

type DictState = 'idle' | 'starting' | 'recording' | 'transcribing';

export interface ComposerHandle {
  focus(): void;
  setText(text: string): void;
}

export interface ComposerProps {
  api: ChatApi;
  busy: boolean;
  /** true - qabul qilindi (maydon tozalanadi). */
  onSend: (text: string) => boolean;
  onStop: () => void;
}

export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer({ api, busy, onSend, onStop }, ref) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const { height: winH } = useWindowDimensions();
  const uiLang = useSettings((x) => x.uiLang);
  const proOn = useSettings((x) => x.proOn);
  const setSettings = useSettings((x) => x.set);
  const proAvailable = usePro((x) => x.available);
  const proLeft = usePro((x) => x.remaining);

  // Sozlamalardagi ovoz namunasi chat pleerida ko'rsatilmaydi.
  const readAloudActive = useReadAloud((x) => x.key !== null && x.key !== PREVIEW_KEY);

  const [text, setText] = useState('');
  const [inputH, setInputH] = useState(LINE);
  const inputRef = useRef<TextInput>(null);
  const hasText = text.trim().length > 0;

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
    setText: (v: string) => setText(v),
  }));

  const maxInputH = Math.min(LINE * MAX_ROWS, Math.max(LINE * 3, Math.round(winH * 0.3)));
  const onContentSize = (e: NativeSyntheticEvent<TextInputContentSizeChangeEventData>) => {
    setInputH(Math.max(LINE, Math.min(maxInputH, Math.ceil(e.nativeEvent.contentSize.height))));
  };

  const send = useCallback(
    (value: string) => {
      if (!value.trim()) return false;
      if (onSend(value)) {
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
        setText('');
        setInputH(LINE);
        return true;
      }
      return false;
    },
    [onSend],
  );

  // --- Pro -------------------------------------------------------------------------
  const proSpent = proLeft !== null && proLeft <= 0;
  const proActive = proAvailable && proOn && !proSpent;
  const proBadge = proLeft !== null && proLeft <= 3 ? Math.max(0, proLeft) : null;
  const togglePro = () => {
    if (proSpent) {
      showToast(t('pro.exhausted'));
      return;
    }
    void Haptics.selectionAsync().catch(() => {});
    setSettings({ proOn: !proOn });
  };

  // --- Diktovka ----------------------------------------------------------------------
  const recorder = useAudioRecorder(DICTATION_PRESET);
  const [dict, setDict] = useState<DictState>('idle');
  const [pending, setPending] = useState<'done' | 'send' | null>(null);
  const [levels, setLevels] = useState<number[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(0);
  const loudest = useRef(-160);
  const session = useRef(0);
  const aborter = useRef<AbortController | null>(null);
  const meetingActive = useRecorderStore((x) => ['preparing', 'recording', 'paused', 'stopping'].includes(x.machine.status));

  // 120 s chegarasida yozuv o'zi tugaydi - taymer eng so'nggi `finish` ni chaqirsin.
  const finishRef = useRef<(intent: 'done' | 'send') => Promise<void>>(async () => {});
  useEffect(() => {
    finishRef.current = finish;
  });

  // Har 100 ms: to'lqin ustuni (yozuvchining o'z o'lchovi) + soat + 120 s chegarasi.
  useEffect(() => {
    if (dict !== 'recording') return;
    const timer = setInterval(() => {
      let db: number | undefined;
      try {
        db = recorder.getStatus().metering;
      } catch {
        db = undefined;
      }
      if (typeof db === 'number' && Number.isFinite(db)) loudest.current = Math.max(loudest.current, db);
      setLevels((prev) => {
        const next = prev.length >= BAR_COUNT ? prev.slice(prev.length - BAR_COUNT + 1) : prev.slice();
        next.push(levelFromDb(db));
        return next;
      });
      const ms = Date.now() - startedAt.current;
      setElapsed(Math.floor(ms / 1000));
      if (ms >= MAX_MS) void finishRef.current('done');
    }, 100);
    return () => clearInterval(timer);
  }, [dict, recorder]);

  const release = useCallback(async () => {
    try {
      if (recorder.isRecording) await recorder.stop();
    } catch {
      /* allaqachon to'xtagan */
    }
  }, [recorder]);

  const removeFile = (uri: string | null | undefined) => {
    if (!uri) return;
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const FS = require('expo-file-system') as typeof import('expo-file-system');
      const f = new FS.File(uri);
      if (f.exists) f.delete();
    } catch {
      /* kesh baribir tozalanadi */
    }
  };

  async function start() {
    if (busy || dict !== 'idle') return;
    if (meetingActive) {
      showToast(t('dict.meetingBusy'));
      return;
    }
    // O'qilayotgan javob ovozi diktovkaga yozilib qolmasin.
    stopReadAloud();
    const mine = ++session.current;
    setPending(null);
    setLevels([]);
    setElapsed(0);
    loudest.current = -160;
    setDict('starting');
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    try {
      const perm = await requestRecordingPermissionsAsync();
      if (mine !== session.current) return;
      if (!perm.granted) {
        setDict('idle');
        showToast(t('dict.denied'));
        return;
      }
      await setAudioModeAsync({ allowsRecording: true, interruptionMode: 'mixWithOthers' });
      await recorder.prepareToRecordAsync(DICTATION_PRESET);
      if (mine !== session.current) {
        await release();
        return;
      }
      recorder.record();
      startedAt.current = Date.now();
      setDict('recording');
    } catch {
      if (mine !== session.current) return;
      await release();
      setDict('idle');
      showToast(t('dict.failed'));
    }
  }

  async function finish(intent: 'done' | 'send') {
    if (dict !== 'recording') return;
    const mine = session.current;
    const ms = Date.now() - startedAt.current;
    setPending(intent);
    setDict('transcribing');
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    await release();
    const uri = recorder.uri;
    if (mine !== session.current) return;
    // Juda qisqa bosish yoki butunlay jim - yuklanmaydi.
    if (ms < MIN_MS) {
      removeFile(uri);
      setDict('idle');
      return;
    }
    if (loudest.current < SPEECH_DB || !uri) {
      removeFile(uri);
      setDict('idle');
      showToast(t('dict.noSpeech'));
      return;
    }
    const ctl = new AbortController();
    aborter.current = ctl;
    try {
      const res = await api.transcribe(uri, 'audio/aac', uiLang, ctl.signal);
      if (mine !== session.current) return;
      const said = (res.text ?? '').trim();
      setDict('idle');
      setPending(null);
      if (!said) {
        showToast(t('dict.noSpeech'));
        return;
      }
      if (res.truncated) showToast(t('dict.truncated'));
      // Matn avval maydonga tushadi: yuborish qabul qilinmasa (javob ketyapti) u yo'qolmaydi.
      setText(said);
      if (intent === 'send' && !busy) {
        send(said);
      } else {
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      }
    } catch (err) {
      if (mine !== session.current || err instanceof StreamAbortedError) return;
      setDict('idle');
      setPending(null);
      showToast(errorText(t, err));
    } finally {
      removeFile(uri);
      if (aborter.current === ctl) aborter.current = null;
    }
  }

  async function cancel() {
    session.current++;
    aborter.current?.abort();
    aborter.current = null;
    setDict('idle');
    setPending(null);
    await release();
    removeFile(recorder.uri);
  }

  // Ikki ovozli kirish (ega qarori 2026-11-20 - ikkalasi ham qoladi, har birining o'z vazifasi bor):
  //   o'ngdagi asosiy tugma (bo'sh maydonda) - "Jonli suhbat" (`/live`): Barno bilan jonli qo'ng'iroq (Speko,
  //     saytdagi /barno). Foydalanuvchiga eng qiziq va muhimi - shuning uchun eng qulay joyda;
  //   chapdagi «Ovozli» chipi - "Ovozli rejim" (`/voice`): chat ichidagi ovozli savol-javob (CRM/HRM ma'lumotlari,
  //     savollar chatda qoladi). Avval asosiy tugma shu edi.
  // Yig'ilish yozilayotganda mikrofon band (ikki yozuvchi bir-birini buzadi) - faqat ogohlantirish.
  const openVoice = (path: '/live' | '/voice') => {
    if (isActive(useRecorderStore.getState().machine)) {
      showToast(t('dict.meetingBusy'));
      return;
    }
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    Keyboard.dismiss();
    router.push(path);
  };

  // Ekran yopilsa - mikrofon albatta bo'shaydi.
  useEffect(
    () => () => {
      session.current++;
      aborter.current?.abort();
      void release();
    },
    [release],
  );

  const clock = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;

  if (dict !== 'idle') {
    const transcribing = dict === 'transcribing';
    const status = dict === 'starting' ? t('dict.starting') : transcribing ? t(pending === 'send' ? 'dict.sending' : 'dict.transcribing') : null;
    return (
      <View>
        {readAloudActive ? <ReadAloudBar /> : null}
        <View style={[s.card, s.cardRow]} testID="composer-dictation" accessibilityLabel={t('dict.start')}>
          <RoundButton label={t('dict.cancel')} onPress={() => void cancel()} bg={th.composerBtn} testID="dict-cancel">
            <X size={18} color={th.text} strokeWidth={2} />
          </RoundButton>
          <View style={s.wave}>
            {status ? (
              <Text numberOfLines={1} style={s.status}>
                {status}
              </Text>
            ) : (
              <Wave levels={levels} color={th.text} faint={th.textFaint} />
            )}
          </View>
          {!transcribing ? <Text style={s.clock}>{clock}</Text> : null}
          <RoundButton label={t('dict.stop')} onPress={() => void finish('done')} bg={th.composerBtn} disabled={dict !== 'recording'} testID="dict-stop">
            {transcribing && pending === 'done' ? <ActivityIndicator size="small" color={th.text} /> : <Square size={12} color={th.text} fill={th.text} strokeWidth={0} />}
          </RoundButton>
          <RoundButton label={t('dict.send')} onPress={() => void finish('send')} bg={th.brand} disabled={dict !== 'recording'} testID="dict-send">
            {transcribing && pending === 'send' ? <ActivityIndicator size="small" color="#fff" /> : <ArrowUp size={19} color="#fff" strokeWidth={2.25} />}
          </RoundButton>
        </View>
      </View>
    );
  }

  return (
    <View>
      {readAloudActive ? <ReadAloudBar /> : null}
      <View style={[s.card, proActive && proAvailable ? { borderColor: th.brand } : null]}>
        <TextInput
          ref={inputRef}
          testID="composer-input"
          value={text}
          onChangeText={setText}
          multiline
          placeholder={t('chat.placeholder')}
          placeholderTextColor={th.textMuted}
          accessibilityLabel={t('chat.message')}
          onContentSizeChange={onContentSize}
          style={[s.input, { height: inputH + 18 }]}
          scrollEnabled={inputH >= maxInputH}
          textAlignVertical="top"
          autoCapitalize="sentences"
        />
        <View style={s.bar}>
          {proAvailable ? (
            <Pressable
              testID="composer-pro"
              onPress={togglePro}
              accessibilityRole="switch"
              accessibilityState={{ checked: proActive }}
              accessibilityLabel={proLeft !== null ? `${t('pro.label')} · ${t('pro.left', { n: proLeft })}` : t('pro.label')}
              hitSlop={6}
              style={({ pressed }) => [s.pro, proActive ? s.proOn : null, pressed && s.pressed]}>
              <Sparkles size={16} color={proActive ? th.brand : proSpent ? th.textFaint : th.textSoft} strokeWidth={2} />
              <Text style={[s.proText, proActive ? { color: th.brand } : proSpent ? { color: th.textFaint } : null]}>
                {proBadge !== null ? `${t('pro.label')} · ${proBadge}` : t('pro.label')}
              </Text>
            </Pressable>
          ) : null}
          <Pressable
            testID="composer-voice"
            onPress={() => openVoice('/voice')}
            accessibilityRole="button"
            accessibilityLabel={t('nav.voice.open')}
            hitSlop={6}
            style={({ pressed }) => [s.pro, s.chipShrink, pressed && s.pressed]}>
            <Headset size={16} color={th.textSoft} strokeWidth={2} />
            <Text style={s.proText} numberOfLines={1}>
              {t('nav.voice.chip')}
            </Text>
          </Pressable>
          <View style={{ flex: 1 }} />
          <RoundButton label={t('dict.start')} onPress={() => void start()} bg={th.composerBtn} disabled={busy} testID="composer-mic">
            <Mic size={19} color={th.textSoft} strokeWidth={1.9} />
          </RoundButton>
          {busy ? (
            <RoundButton label={t('chat.stop')} onPress={onStop} bg={th.primary} testID="composer-stop">
              <Square size={12} color={th.primaryText} fill={th.primaryText} strokeWidth={0} />
            </RoundButton>
          ) : hasText ? (
            <RoundButton label={t('chat.send')} onPress={() => void send(text)} bg={th.brand} testID="composer-send">
              <ArrowUp size={19} color="#fff" strokeWidth={2.25} />
            </RoundButton>
          ) : (
            // Bo'sh maydon: "Jonli suhbat" (Speko) - Claude'dagi ovoz tugmasi kabi "siyoh" rangida.
            <RoundButton label={t('nav.live.open')} onPress={() => openVoice('/live')} bg={th.primary} testID="composer-live">
              <AudioLines size={19} color={th.primaryText} strokeWidth={2} />
            </RoundButton>
          )}
        </View>
      </View>
    </View>
  );
});

/** Pro kalitining holati tashqaridan ham kerak (yuborishda) - store'dagi bilan bir xil. */
export { proActiveNow };

function RoundButton(props: {
  label: string;
  onPress: () => void;
  bg: string;
  disabled?: boolean;
  /** O'chiq holatda xiralashtirish (yuborish o'z rangini o'zi beradi). */
  dimmed?: boolean;
  testID?: string;
  children: React.ReactNode;
}) {
  const { disabled, dimmed = true } = props;
  return (
    <Pressable
      testID={props.testID}
      accessibilityRole="button"
      accessibilityLabel={props.label}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={props.onPress}
      hitSlop={5}
      style={({ pressed }) => [
        {
          width: 36,
          height: 36,
          borderRadius: 18,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: props.bg,
          opacity: disabled && dimmed ? 0.45 : 1,
          transform: [{ scale: pressed ? 0.92 : 1 }],
        },
      ]}>
      {props.children}
    </Pressable>
  );
}

/** Jonli to'lqin: eng yangi ustun o'ngda; hali yozilmagan joy - xira nuqtalar. */
function Wave({ levels, color, faint }: { levels: number[]; color: string; faint: string }) {
  const bars = Array.from({ length: BAR_COUNT }, (_, i) => {
    const from = BAR_COUNT - levels.length;
    return i >= from ? levels[i - from] : null;
  });
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', height: 28, gap: 3, overflow: 'hidden' }}>
      {bars.map((lv, i) => (
        <View
          key={i}
          style={{
            width: 3,
            height: lv === null ? 3 : Math.max(3, Math.round(3 + lv * 25)),
            borderRadius: 1.5,
            backgroundColor: lv === null ? faint : color,
          }}
        />
      ))}
    </View>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    card: {
      borderWidth: 1,
      borderColor: th.composerLine,
      borderRadius: 24,
      backgroundColor: th.composerBg,
      ...(th.dark
        ? null
        : { shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 2 }),
    },
    cardRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 10, gap: 8 },
    input: {
      color: th.text,
      fontSize: 16,
      lineHeight: LINE,
      paddingTop: 13,
      paddingBottom: 5,
      paddingHorizontal: 16,
    },
    bar: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 8, paddingTop: 4, paddingBottom: 8 },
    pro: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      height: 36,
      paddingLeft: 11,
      paddingRight: 14,
      borderRadius: 18,
      borderWidth: 1,
      borderColor: 'transparent',
      backgroundColor: th.composerBtn,
    },
    proOn: { backgroundColor: th.brandSoft, borderColor: th.brand },
    // Tor ekranda «Ovozli» chipi qisqaradi (matn ... bilan) - o'ngdagi tugmalar joyidan siljimaydi.
    chipShrink: { flexShrink: 1, minWidth: 0 },
    proText: { color: th.textSoft, fontSize: 14, fontWeight: '600' },
    pressed: { opacity: 0.8 },
    wave: { flex: 1, minWidth: 0, justifyContent: 'center', height: 36 },
    status: { color: th.textMuted, fontSize: 14 },
    clock: { color: th.textMuted, fontSize: 14, fontVariant: ['tabular-nums'] },
  });
}
