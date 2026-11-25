/**
 * Asosiy ekran - Barno bilan suhbat (NATIVE; Mini App'ning dizayni va mantig'i).
 *
 *   tepada   ☰ menyu (drawer) · suhbat nomi · Plaud (yozuvlar) · ✎ yangi suhbat (`features/nav/TopBar`)
 *            yozuv paytida ostida qizil chiziq - bir bosishda yozuv ekrani
 *   o'rtada  salomlashuv (bo'sh suhbatda) yoki savol-javoblar
 *   pastda   Claude uslubidagi yozish maydoni (matn + Pro + mikrofon + yuborish)
 *
 * Javob oqim bilan keladi (NDJSON, `api/chat.ts`), ekran pastga o'zi aylanadi - odam
 * yuqoriga aylantirgan bo'lsa to'xtaydi va "Oxirgi xabarga" tugmasi chiqadi.
 * Kanal `mobile`: server dvigatelni shunga qarab tanlaydi (prod: v3).
 *
 * Suhbatlar tarixi, profil/sozlamalar va yozuvlar - chap panelda (`AppDrawer`, ☰ bilan).
 */
import { ArrowDown } from "lucide-react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { AnswerSource } from "@/api/chat";
import { useAuth } from "@/features/auth/authStore";
import { useChat } from "@/features/chat/chatStore";
import { useChats } from "@/features/chat/chatsStore";
import { useKeyboardPadding } from "@/features/chat/keyboard";
import { proActiveNow, usePro } from "@/features/chat/proStore";
import { Composer } from "@/features/chat/ui/Composer";
import { ExchangeView } from "@/features/chat/ui/ExchangeView";
import { SourcesSheet } from "@/features/chat/ui/Sheets";
import { AppDrawer, firstName } from "@/features/nav/AppDrawer";
import { ChatTopBar, RecordingStrip } from "@/features/nav/TopBar";
import { useSettings, useT } from "@/features/settings/settingsStore";
import { useServices } from "@/services";
import { useTheme, type Theme } from "@/ui/theme";

/** Pastdan shuncha piksel ichida bo'lsa - "pastda" hisoblanadi (oqim ergashadi). */
const NEAR_BOTTOM = 80;

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

  const [drawerOpen, setDrawerOpen] = useState(false);
  // Barqaror funksiyalar: drawer surish (PanResponder) har chizishda qayta yaratilmasin.
  const openDrawer = useCallback(() => {
    // Composer klaviaturasi ochiq qolsa drawer ustini yopib turardi.
    Keyboard.dismiss();
    setDrawerOpen(true);
  }, []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const [sources, setSources] = useState<{
    list: AnswerSource[];
    focus?: string;
  } | null>(null);

  // Dvigatelga bog'liqliklar - bir marta (servislar o'zgarmaydi).
  useEffect(() => {
    useChat.getState().bind({
      api: services.chat,
      locale: () => useSettings.getState().uiLang,
      proActive: proActiveNow,
      onPro: (info) => usePro.getState().note(info),
      onTurn: (id, question) =>
        useChats.getState().noteTurn(services.chat, id, question),
      onForget: (id) => useChats.getState().forget(id),
    });
    void useChats.getState().load(services.chat);
    void usePro.getState().load(services.chat);
  }, [services]);

  const title = useMemo(() => {
    const row = chatItems.find((c) => c.chat_id === chatId);
    if (row?.title) return row.title;
    const first = exchanges.find((e) => e.question)?.question;
    return first ? first.replace(/\s+/g, " ").slice(0, 60) : "";
  }, [chatItems, chatId, exchanges]);

  // --- Aylantirish ------------------------------------------------------------------
  const scroller = useRef<ScrollView>(null);
  const atBottom = useRef(true);
  // "Oxirgi xabarga" - faqat SHU suhbatda yuqoriga aylantirilgan bo'lsa (yangi suhbat/tarix
  // ochilganda `epoch` o'zgaradi va tugma o'zi yo'qoladi).
  const [jump, setJump] = useState<{ epoch: number; show: boolean }>({
    epoch: 0,
    show: false,
  });
  const showJump = jump.epoch === epoch && jump.show;
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const near =
      contentSize.height - (contentOffset.y + layoutMeasurement.height) <
      NEAR_BOTTOM;
    atBottom.current = near;
    if (showJump !== !near) setJump({ epoch, show: !near });
  };
  const onContentSize = () => {
    if (atBottom.current) scroller.current?.scrollToEnd({ animated: false });
  };
  useEffect(() => {
    atBottom.current = true;
    requestAnimationFrame(() =>
      scroller.current?.scrollToEnd({ animated: false }),
    );
  }, [epoch]);

  const send = useCallback((text: string) => {
    const ok = useChat.getState().send(text);
    if (ok) {
      atBottom.current = true;
      requestAnimationFrame(() =>
        scroller.current?.scrollToEnd({ animated: true }),
      );
    }
    return ok;
  }, []);

  const reconnect = useCallback(() => {
    Alert.alert(t("chat.reconnect"), t("settings.reconnectHint"), [
      { text: t("common.cancel"), style: "cancel" },
      {
        text: t("settings.reconnect"),
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
    <View
      style={[
        s.root,
        {
          paddingTop: insets.top,
          paddingBottom: kb.paddingBottom || insets.bottom,
        },
      ]}
      onLayout={kb.onLayout}
    >
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        enabled={Platform.OS === "ios"}
        behavior="padding"
      >
        <ChatTopBar title={title} onMenu={openDrawer} showNewChat={!empty} />
        <RecordingStrip />

        <View style={{ flex: 1 }}>
          {empty ? (
            <Welcome
              name={name}
              onPick={(q) => send(q)}
              disabled={phase !== "idle"}
            />
          ) : (
            <ScrollView
              ref={scroller}
              testID="chat-scroll"
              style={{ flex: 1 }}
              contentContainerStyle={{ flexGrow: 1, paddingBottom: 16 }}
              onScroll={onScroll}
              scrollEventThrottle={64}
              onContentSizeChange={onContentSize}
              onLayout={onContentSize}
              keyboardShouldPersistTaps="handled"
              keyboardDismissMode="interactive"
            >
              {historyLoading ? (
                <ActivityIndicator
                  style={{ marginTop: 40 }}
                  color={th.textMuted}
                />
              ) : null}
              {historyError ? (
                <Pressable
                  onPress={() =>
                    void useChat.getState().openHistory(chatId, true)
                  }
                  style={{ padding: 24, alignItems: "center" }}
                >
                  <Text
                    style={{
                      color: th.textMuted,
                      fontSize: 15,
                      textAlign: "center",
                    }}
                  >
                    {t("chat.historyLoadFailed")}
                  </Text>
                  <Text
                    style={{ color: th.text, fontWeight: "600", marginTop: 8 }}
                  >
                    {t("common.retry")}
                  </Text>
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
              testID="chat-jump"
              accessibilityRole="button"
              accessibilityLabel={t("chat.jumpLatest")}
              hitSlop={4}
              style={s.jump}
            >
              <ArrowDown size={20} color={th.textSoft} strokeWidth={2} />
            </Pressable>
          ) : null}
        </View>

        <View style={s.composerWrap}>
          <Composer
            api={services.chat}
            busy={phase === "sending"}
            onSend={send}
            onStop={() => useChat.getState().stop()}
          />
          <Text style={s.disclaimer}>{t("chat.disclaimer")}</Text>
        </View>
      </KeyboardAvoidingView>

      <AppDrawer open={drawerOpen} onClose={closeDrawer} />
      <SourcesSheet
        visible={!!sources}
        onClose={() => setSources(null)}
        sources={sources?.list ?? []}
        focus={sources?.focus}
        api={services.chat}
      />
    </View>
  );
}

/** Bo'sh suhbat: salomlashuv markazda, ikki tayyor savol pastda (Mini App `TgWelcome`). */
function Welcome({
  name,
  onPick,
  disabled,
}: {
  name: string;
  onPick: (q: string) => void;
  disabled: boolean;
}) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const cards = [
    { q: t("chat.suggestLate"), hint: t("chat.suggestLateHint") },
    { q: t("chat.suggestTasks"), hint: t("chat.suggestTasksHint") },
  ];
  return (
    <Pressable
      style={s.welcome}
      testID="chat-welcome"
      accessible={false}
      onPress={Keyboard.dismiss}
    >
      <View style={s.hero}>
        <View style={s.spark}>
          <Text style={{ color: th.brand, fontSize: 26 }}>✦</Text>
        </View>
        <Text style={s.hello} accessibilityRole="header">
          {name ? t("chat.helloName", { name }) : t("chat.hello")}
        </Text>
        <Text style={s.lead}>{t("chat.lead")}</Text>
      </View>
      <View style={s.cards}>
        {cards.map((c) => (
          <Pressable
            key={c.q}
            disabled={disabled}
            onPress={() => onPick(c.q)}
            accessibilityRole="button"
            style={({ pressed }) => [
              s.card,
              pressed ? { opacity: 0.75 } : null,
            ]}
          >
            <Text style={s.cardQ} numberOfLines={2}>
              {c.q}
            </Text>
            <Text style={s.cardHint}>{c.hint}</Text>
          </Pressable>
        ))}
      </View>
    </Pressable>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    root: { flex: 1, backgroundColor: th.bg },
    composerWrap: {
      paddingHorizontal: 12,
      paddingTop: 6,
      paddingBottom: 6,
      backgroundColor: th.bg,
    },
    disclaimer: {
      color: th.textFaint,
      fontSize: 11,
      textAlign: "center",
      marginTop: 6,
    },
    // O'ng chetda, yozish maydoni ustida (2026-10-10): o'rtada turganda javob matnining
    // o'rtasini yopib qo'yardi (egasining skrinshoti). `right` - kompozer cheti bilan bir chiziqda.
    jump: {
      position: "absolute",
      right: 12,
      bottom: 8,
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: th.surface,
      borderWidth: 1,
      borderColor: th.border,
      elevation: 3,
      shadowColor: "#000",
      shadowOpacity: 0.12,
      shadowRadius: 8,
      shadowOffset: { width: 0, height: 3 },
    },
    welcome: { flex: 1, paddingHorizontal: 16, paddingBottom: 8 },
    hero: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
    spark: {
      width: 60,
      height: 60,
      borderRadius: 18,
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: th.brandSoft,
      marginBottom: 6,
    },
    hello: {
      color: th.text,
      fontSize: 26,
      fontWeight: "700",
      textAlign: "center",
    },
    lead: { color: th.textMuted, fontSize: 16, textAlign: "center" },
    cards: { flexDirection: "row", gap: 10 },
    card: {
      flex: 1,
      borderWidth: 1,
      borderColor: th.border,
      borderRadius: 18,
      paddingHorizontal: 14,
      paddingVertical: 12,
      backgroundColor: th.surface,
      gap: 4,
    },
    cardQ: { color: th.text, fontSize: 15, fontWeight: "600" },
    cardHint: { color: th.textMuted, fontSize: 13 },
  });
}
