/**
 * Asosiy ekran - Barno bilan suhbat (NATIVE; Mini App'ning dizayni va mantig'i).
 *
 *   tepada   tarix · suhbat nomi · yangi suhbat · profil (sozlamalar)
 *   o'rtada  salomlashuv (bo'sh suhbatda) yoki savol-javoblar
 *   pastda   Claude uslubidagi yozish maydoni (matn + Pro + mikrofon + yuborish)
 *
 * Javob oqim bilan keladi (NDJSON, `api/chat.ts`), ekran pastga o'zi aylanadi - odam
 * yuqoriga aylantirgan bo'lsa to'xtaydi va "Oxirgi xabarga" tugmasi chiqadi.
 * Kanal `mobile`: server dvigatelni shunga qarab tanlaydi (prod: v3).
 */
import { router } from 'expo-router';
import { ArrowDown, History, SquarePen } from 'lucide-react-native';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { AnswerSource } from '@/api/chat';
import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import { useChats } from '@/features/chat/chatsStore';
import { useKeyboardPadding } from '@/features/chat/keyboard';
import { proActiveNow, usePro } from '@/features/chat/proStore';
import { Composer } from '@/features/chat/ui/Composer';
import { ExchangeView } from '@/features/chat/ui/ExchangeView';
import { HistorySheet, SourcesSheet } from '@/features/chat/ui/Sheets';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { useTheme, type Theme } from '@/ui/theme';

/** Pastdan shuncha piksel ichida bo'lsa - "pastda" hisoblanadi (oqim ergashadi). */
const NEAR_BOTTOM = 80;

export function initials(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '·';
  return (parts[0][0] + (parts[1]?.[0] ?? '')).toUpperCase();
}

function firstName(name: string | null | undefined): string {
  return (name ?? '').trim().split(/\s+/)[0] ?? '';
}

export default function ChatScreen() {
  const services = useServices();
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const insets = useSafeAreaInsets();
  const kb = useKeyboardPadding(insets.bottom);
  const user = useAuth((x) => x.user);

  const chatId = useChat((x) => x.chatId);
  const exchanges = useChat((x) => x.exchanges);
  const phase = useChat((x) => x.phase);
  const historyLoading = useChat((x) => x.historyLoading);
  const historyError = useChat((x) => x.historyError);
  const epoch = useChat((x) => x.epoch);
  const chatItems = useChats((x) => x.items);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [sources, setSources] = useState<{ list: AnswerSource[]; focus?: string } | null>(null);

  // Dvigatelga bog'liqliklar - bir marta (servislar o'zgarmaydi).
  useEffect(() => {
    useChat.getState().bind({
      api: services.chat,
      locale: () => useSettings.getState().uiLang,
      proActive: proActiveNow,
      onPro: (info) => usePro.getState().note(info),
      onTurn: (id, question) => useChats.getState().noteTurn(services.chat, id, question),
      onForget: (id) => useChats.getState().forget(id),
    });
    void useChats.getState().load(services.chat);
    void usePro.getState().load(services.chat);
  }, [services]);

  const title = useMemo(() => {
    const row = chatItems.find((c) => c.chat_id === chatId);
    if (row?.title) return row.title;
    const first = exchanges.find((e) => e.question)?.question;
    return first ? first.replace(/\s+/g, ' ').slice(0, 60) : '';
  }, [chatItems, chatId, exchanges]);

  // --- Aylantirish ------------------------------------------------------------------
  const scroller = useRef<ScrollView>(null);
  const atBottom = useRef(true);
  // "Oxirgi xabarga" - faqat SHU suhbatda yuqoriga aylantirilgan bo'lsa (yangi suhbat/tarix
  // ochilganda `epoch` o'zgaradi va tugma o'zi yo'qoladi).
  const [jump, setJump] = useState<{ epoch: number; show: boolean }>({ epoch: 0, show: false });
  const showJump = jump.epoch === epoch && jump.show;
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const near = contentSize.height - (contentOffset.y + layoutMeasurement.height) < NEAR_BOTTOM;
    atBottom.current = near;
    if (showJump !== !near) setJump({ epoch, show: !near });
  };
  const onContentSize = () => {
    if (atBottom.current) scroller.current?.scrollToEnd({ animated: false });
  };
  useEffect(() => {
    atBottom.current = true;
    requestAnimationFrame(() => scroller.current?.scrollToEnd({ animated: false }));
  }, [epoch]);

  const send = useCallback((text: string) => {
    const ok = useChat.getState().send(text);
    if (ok) {
      atBottom.current = true;
      requestAnimationFrame(() => scroller.current?.scrollToEnd({ animated: true }));
    }
    return ok;
  }, []);

  const reconnect = useCallback(() => {
    Alert.alert(t('chat.reconnect'), t('settings.reconnectHint'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('settings.reconnect'),
        onPress: () => {
          useChat.getState().abort();
          void services.session.logout();
        },
      },
    ]);
  }, [services, t]);

  const empty = !exchanges.length && !historyLoading && !historyError;
  const name = firstName(user?.fullName);

  return (
    <View style={[s.root, { paddingTop: insets.top, paddingBottom: kb.paddingBottom || insets.bottom }]} onLayout={kb.onLayout}>
      <View style={s.top}>
        <IconButton label={t('chat.history')} onPress={() => setHistoryOpen(true)} testID="chat-history">
          <History size={21} color={th.textSoft} strokeWidth={1.9} />
        </IconButton>
        <Text style={s.title} numberOfLines={1} accessibilityRole="header">
          {title || t('app.name')}
        </Text>
        <IconButton label={t('chat.newChat')} onPress={() => useChat.getState().newChat()} testID="chat-new">
          <SquarePen size={20} color={th.textSoft} strokeWidth={1.9} />
        </IconButton>
        <Pressable
          testID="chat-settings"
          onPress={() => router.push('/settings')}
          accessibilityRole="button"
          accessibilityLabel={t('chat.settings')}
          hitSlop={6}
          style={({ pressed }) => [s.avatar, pressed ? { opacity: 0.7 } : null]}>
          <Text style={s.avatarText}>{initials(user?.fullName)}</Text>
        </Pressable>
      </View>

      <View style={{ flex: 1 }}>
        {empty ? (
          <Welcome name={name} onPick={(q) => send(q)} disabled={phase !== 'idle'} />
        ) : (
          <ScrollView
            ref={scroller}
            testID="chat-scroll"
            style={{ flex: 1 }}
            contentContainerStyle={{ paddingBottom: 16 }}
            onScroll={onScroll}
            scrollEventThrottle={64}
            onContentSizeChange={onContentSize}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive">
            {historyLoading ? <ActivityIndicator style={{ marginTop: 40 }} color={th.textMuted} /> : null}
            {historyError ? (
              <Pressable onPress={() => void useChat.getState().openHistory(chatId, true)} style={{ padding: 24, alignItems: 'center' }}>
                <Text style={{ color: th.textMuted, fontSize: 15, textAlign: 'center' }}>{t('chat.historyLoadFailed')}</Text>
                <Text style={{ color: th.text, fontWeight: '600', marginTop: 8 }}>{t('common.retry')}</Text>
              </Pressable>
            ) : null}
            {exchanges.map((ex, i) => (
              <ExchangeView
                key={ex.id}
                ex={ex}
                api={services.chat}
                actions={services.actions}
                live={i === exchanges.length - 1}
                onRetry={(id) => useChat.getState().regenerate(id)}
                onReconnect={reconnect}
                onSources={(list, focus) => setSources({ list, focus })}
              />
            ))}
          </ScrollView>
        )}
        {showJump && !empty ? (
          <Pressable
            onPress={() => {
              atBottom.current = true;
              setJump({ epoch, show: false });
              scroller.current?.scrollToEnd({ animated: true });
            }}
            accessibilityRole="button"
            accessibilityLabel={t('chat.jumpLatest')}
            style={s.jump}>
            <ArrowDown size={20} color={th.textSoft} strokeWidth={2} />
          </Pressable>
        ) : null}
      </View>

      <View style={s.composerWrap}>
        <Composer api={services.chat} busy={phase === 'sending'} onSend={send} onStop={() => useChat.getState().stop()} />
        <Text style={s.disclaimer}>{t('chat.disclaimer')}</Text>
      </View>

      <HistorySheet
        visible={historyOpen}
        onClose={() => setHistoryOpen(false)}
        api={services.chat}
        activeId={chatId}
        onOpen={(id) => void useChat.getState().openHistory(id)}
        onNew={() => useChat.getState().newChat()}
        onRemovedActive={() => useChat.getState().newChat()}
      />
      <SourcesSheet visible={!!sources} onClose={() => setSources(null)} sources={sources?.list ?? []} focus={sources?.focus} api={services.chat} />
    </View>
  );
}

function IconButton({ label, onPress, children, testID }: { label: string; onPress: () => void; children: React.ReactNode; testID?: string }) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={6}
      style={({ pressed }) => ({ width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.6 : 1 })}>
      {children}
    </Pressable>
  );
}

/** Bo'sh suhbat: salomlashuv markazda, ikki tayyor savol pastda (Mini App `TgWelcome`). */
function Welcome({ name, onPick, disabled }: { name: string; onPick: (q: string) => void; disabled: boolean }) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const cards = [
    { q: t('chat.suggestLate'), hint: t('chat.suggestLateHint') },
    { q: t('chat.suggestTasks'), hint: t('chat.suggestTasksHint') },
  ];
  return (
    <View style={s.welcome} testID="chat-welcome">
      <View style={s.hero}>
        <View style={s.spark}>
          <Text style={{ color: th.brand, fontSize: 26 }}>✦</Text>
        </View>
        <Text style={s.hello} accessibilityRole="header">
          {name ? t('chat.helloName', { name }) : t('chat.hello')}
        </Text>
        <Text style={s.lead}>{t('chat.lead')}</Text>
      </View>
      <View style={s.cards}>
        {cards.map((c) => (
          <Pressable
            key={c.q}
            disabled={disabled}
            onPress={() => onPick(c.q)}
            accessibilityRole="button"
            style={({ pressed }) => [s.card, pressed ? { opacity: 0.75 } : null]}>
            <Text style={s.cardQ} numberOfLines={2}>
              {c.q}
            </Text>
            <Text style={s.cardHint}>{c.hint}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    root: { flex: 1, backgroundColor: th.bg },
    top: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      paddingHorizontal: 8,
      height: 52,
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: th.border,
    },
    title: { flex: 1, color: th.text, fontSize: 17, fontWeight: '700', textAlign: 'center', paddingHorizontal: 4 },
    avatar: {
      width: 36,
      height: 36,
      borderRadius: 18,
      marginLeft: 4,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: th.surfaceAlt,
      borderWidth: 1,
      borderColor: th.border,
    },
    avatarText: { color: th.text, fontSize: 13, fontWeight: '700' },
    composerWrap: { paddingHorizontal: 12, paddingTop: 6, paddingBottom: 6, backgroundColor: th.bg },
    disclaimer: { color: th.textFaint, fontSize: 11, textAlign: 'center', marginTop: 6 },
    jump: {
      position: 'absolute',
      alignSelf: 'center',
      bottom: 10,
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: th.surface,
      borderWidth: 1,
      borderColor: th.border,
      elevation: 3,
      shadowColor: '#000',
      shadowOpacity: 0.12,
      shadowRadius: 8,
      shadowOffset: { width: 0, height: 3 },
    },
    welcome: { flex: 1, paddingHorizontal: 16, paddingBottom: 8 },
    hero: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10 },
    spark: { width: 60, height: 60, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: th.brandSoft, marginBottom: 6 },
    hello: { color: th.text, fontSize: 26, fontWeight: '700', textAlign: 'center' },
    lead: { color: th.textMuted, fontSize: 16, textAlign: 'center' },
    cards: { flexDirection: 'row', gap: 10 },
    card: { flex: 1, borderWidth: 1, borderColor: th.border, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 12, backgroundColor: th.surface, gap: 4 },
    cardQ: { color: th.text, fontSize: 15, fontWeight: '600' },
    cardHint: { color: th.textMuted, fontSize: 13 },
  });
}
