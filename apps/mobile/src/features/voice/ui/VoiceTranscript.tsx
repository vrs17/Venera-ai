/**
 * Jonli suhbat matni: SHU sessiyadagi savol-javoblar, chat ko'rinishida.
 *
 *   o'ngda   foydalanuvchi pufakchasi (nima eshitilgani)
 *   chapda   Barno javobi - KATTA matn (telefon qo'ldan uzoqda bo'lsa ham o'qilsin)
 *
 * Javoblar chat store'dan olinadi (ovozli savollar oddiy chatga ham tushadi) - bu yerda
 * alohida nusxa saqlanmaydi. Barno gapirayotganda yoki kutish klipi yangrayotganda matnga
 * BIR MARTA tegish uni to'xtatadi (aylantirish to'xtatmaydi; quloq rejimida - yonoq
 * tegib ketmasin deb - o'chiq).
 *
 * Aylantirish: yangi javob kelganda uning BOSHI ko'rinadi (oxiriga sakramaydi) - javob
 * bir yo'la keladi, Barno esa boshidan o'qiydi; odam aytilayotgan joyni ko'rsin.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { useChat, type Exchange } from '@/features/chat/chatStore';
import { useT } from '@/features/settings/settingsStore';
import { displayText, type VoiceSnapshot } from '@/features/voice';
import { darkTheme as D } from '@/ui/theme';

import { useReducedMotion } from './useReducedMotion';

/** Foydalanuvchi yuqoriga surib o'qiyotgan bo'lsa shuncha vaqt aylantirmaymiz. */
const HOLD_SCROLL_MS = 4000;
const TAP_SLOP = 10;
/** Javob boshiga aylantirganda ustida shuncha joy qoladi (savol pufakchasining pasti ko'rinsin). */
const ANCHOR_GAP = 8;

/** Odam yaqinda o'zi surganmi (hodisa ichida chaqiriladi, render'da emas). */
function draggedRecently(at: number): boolean {
  return Date.now() - at < HOLD_SCROLL_MS;
}

export interface VoiceTranscriptProps {
  snap: VoiceSnapshot;
  onInterrupt: () => void;
  onSendPending: () => void;
  /** Matnga tegib to'xtatish (quloq rejimida o'chiq). Default: yoqiq. */
  tapToInterrupt?: boolean;
}

export function VoiceTranscript({ snap, onInterrupt, onSendPending, tapToInterrupt = true }: VoiceTranscriptProps) {
  const t = useT();
  const scroll = useRef<ScrollView>(null);
  const draggedAt = useRef(0);
  const touch = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  /** Har savol-javob blokining yuqori nuqtasi (ScrollView ichida). */
  const turnY = useRef(new Map<string, number>());
  /** Qaysi javobning boshiga allaqachon aylantirildi. */
  const anchored = useRef<string | null>(null);

  // zustand 5: selektor yangi massiv qaytarmasin (cheksiz qayta chizish) - butun ro'yxatni
  // olib, bu sessiyaning savollarini useMemo ichida tanlaymiz.
  const exchanges = useChat((s) => s.exchanges);
  const turns = useMemo(() => {
    const byId = new Map(exchanges.map((e) => [e.id, e] as const));
    return snap.turnIds.map((id) => byId.get(id)).filter((e): e is Exchange => !!e);
  }, [exchanges, snap.turnIds]);

  const canInterrupt = tapToInterrupt && (snap.status === 'speaking' || !!snap.holdText);
  const last = turns[turns.length - 1];
  const lastAnswered = !!last?.answer && !snap.pendingText && snap.status !== 'transcribing';

  const onContentSize = () => {
    if (draggedRecently(draggedAt.current)) return;
    if (lastAnswered && last) {
      // Javob paydo bo'ldi: boshini ko'rsatamiz (bir marta) - keyingi o'sishlarda sakramaymiz.
      if (anchored.current === last.id) return;
      const y = turnY.current.get(last.id);
      if (y == null) return;
      anchored.current = last.id;
      scroll.current?.scrollTo({ y: Math.max(0, y - ANCHOR_GAP), animated: true });
      return;
    }
    scroll.current?.scrollToEnd({ animated: true });
  };

  return (
    <View
      style={s.wrap}
      testID="voice-transcript"
      onTouchStart={(e) => {
        touch.current = { x: e.nativeEvent.pageX, y: e.nativeEvent.pageY, moved: false };
      }}
      onTouchMove={(e) => {
        const tc = touch.current;
        // Barmoqning kichik titrashi "surish" emas - 10 dp dan oshsagina bosish bekor.
        if (tc && Math.hypot(e.nativeEvent.pageX - tc.x, e.nativeEvent.pageY - tc.y) > TAP_SLOP) tc.moved = true;
      }}
      onTouchEnd={() => {
        const tap = touch.current && !touch.current.moved;
        touch.current = null;
        if (tap && canInterrupt) onInterrupt();
      }}>
      <ScrollView
        ref={scroll}
        style={s.scroll}
        contentContainerStyle={s.content}
        onContentSizeChange={onContentSize}
        onScrollBeginDrag={() => {
          draggedAt.current = Date.now();
          if (touch.current) touch.current.moved = true;
        }}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled">
        {turns.map((ex) => (
          <View
            key={ex.id}
            onLayout={(e) => {
              turnY.current.set(ex.id, e.nativeEvent.layout.y);
            }}>
            <Turn ex={ex} />
          </View>
        ))}
        {snap.pendingText ? (
          <View style={s.pendingBlock}>
            <UserBubble faded>
              <Text style={s.userText}>{snap.pendingText}</Text>
            </UserBubble>
            <Pressable
              testID="voice-send-pending"
              accessibilityRole="button"
              accessibilityLabel={t('nav.voice.sendAnyway')}
              onPress={onSendPending}
              hitSlop={8}
              style={({ pressed }) => [s.sendPill, pressed && s.pressed]}>
              <Text style={s.sendText}>{t('nav.voice.sendAnyway')}</Text>
            </Pressable>
          </View>
        ) : null}
        {snap.status === 'transcribing' ? (
          <UserBubble testID="voice-transcribing">
            <Dots />
          </UserBubble>
        ) : null}
      </ScrollView>
      {/* Tepada yumshoq so'nish: matn tepa panel ostiga keskin kesilib kirmasin. */}
      <View pointerEvents="none" style={s.fade}>
        <Svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <Defs>
            <LinearGradient id="voice-top-fade" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={D.bg} stopOpacity={1} />
              <Stop offset="1" stopColor={D.bg} stopOpacity={0} />
            </LinearGradient>
          </Defs>
          <Rect x="0" y="0" width="100" height="100" fill="url(#voice-top-fade)" />
        </Svg>
      </View>
    </View>
  );
}

function Turn({ ex }: { ex: Exchange }) {
  const t = useT();
  const answer = useMemo(() => (ex.answer ? displayText(ex.answer) : ''), [ex.answer]);
  const waiting = (ex.status === 'pending' || ex.status === 'streaming') && !answer;
  return (
    <View testID={`voice-turn-${ex.id}`}>
      {ex.question ? (
        <UserBubble>
          <Text style={s.userText}>{ex.question}</Text>
        </UserBubble>
      ) : null}
      <View style={s.assistant}>
        {waiting ? (
          // Faqat nuqtalar (+ agent bosqichi): kutish matni pastdagi holat yozuvida - ikki
          // joyda bir xil "O'ylayapman…" turmasin. E'lon qilinmaydi (TalkBack shovqini).
          <View style={s.waitRow}>
            <Dots />
            {ex.stage ? (
              <Text style={s.waitText} numberOfLines={2}>
                {ex.stage}
              </Text>
            ) : null}
          </View>
        ) : null}
        {answer ? (
          <Text style={s.answer} selectable testID={`voice-answer-${ex.id}`}>
            {answer}
          </Text>
        ) : null}
        {ex.status === 'error' && ex.error ? <Text style={s.error}>{ex.error}</Text> : null}
        {ex.status === 'stopped' ? <Text style={s.caption}>{t('chat.stopped')}</Text> : null}
        {ex.status === 'cancelled' ? <Text style={s.caption}>{t('chat.cancelled')}</Text> : null}
        {ex.proposal && !answer ? <Text style={s.caption}>{t('nav.voice.seeScreen')}</Text> : null}
      </View>
    </View>
  );
}

function UserBubble({ children, faded, testID }: { children: React.ReactNode; faded?: boolean; testID?: string }) {
  return (
    <View testID={testID} style={[s.bubble, faded ? s.faded : null]}>
      {children}
    </View>
  );
}

/** Uch nuqta: navbatma-navbat yonib-o'chadi (native driver; harakat kamaytirilsa - statik). */
export function Dots() {
  const reduced = useReducedMotion();
  const [a] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (reduced) return;
    const loop = Animated.loop(Animated.timing(a, { toValue: 1, duration: 900, easing: Easing.linear, useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [a, reduced]);
  return (
    <View style={s.dots} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {[0, 1, 2].map((i) => {
        const opacity = reduced
          ? 0.7
          : a.interpolate({
              inputRange: [0, 0.33, 0.66, 1],
              outputRange: [0, 1, 2, 3].map((k) => ((k + 3 - i) % 3 === 0 ? 1 : 0.3)),
            });
        return <Animated.View key={i} style={[s.dot, { opacity }]} />;
      })}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1 },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 24, gap: 20 },
  fade: { position: 'absolute', top: 0, left: 0, right: 0, height: 24 },
  bubble: {
    alignSelf: 'flex-end',
    maxWidth: '82%',
    backgroundColor: D.surfaceAlt,
    borderRadius: 20,
    borderBottomRightRadius: 6,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  faded: { opacity: 0.6 },
  userText: { color: D.text, fontSize: 17, lineHeight: 24 },
  assistant: { marginTop: 14 },
  waitRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  waitText: { color: D.textMuted, fontSize: 16, lineHeight: 22, flex: 1 },
  answer: { color: D.text, fontSize: 22, lineHeight: 31, fontWeight: '400' },
  error: { color: D.tones.bad.fg, fontSize: 17, lineHeight: 24 },
  caption: { color: D.textMuted, fontSize: 13, lineHeight: 18, marginTop: 4 },
  pendingBlock: { gap: 8 },
  sendPill: {
    alignSelf: 'flex-end',
    height: 32,
    borderRadius: 16,
    paddingHorizontal: 14,
    justifyContent: 'center',
    backgroundColor: D.composerBtn,
  },
  sendText: { color: D.text, fontSize: 13, lineHeight: 18, fontWeight: '600' },
  pressed: { opacity: 0.8 },
  dots: { flexDirection: 'row', alignItems: 'center', gap: 5, height: 22 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: D.textMuted },
});
