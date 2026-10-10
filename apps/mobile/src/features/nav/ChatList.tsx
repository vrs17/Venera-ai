/**
 * Drawer ichidagi suhbatlar ro'yxati (avvalgi `HistorySheet` mantig'i, o'zgarishsiz):
 * Bugun / Kecha / Shu hafta / Oldinroq guruhlari, bosish - ochish, bosib turish -
 * nomini o'zgartirish yoki o'chirish. Qidiruv mijoz tomonida, nom bo'yicha.
 *
 * NIMA UCHUN qator 44 dp va belgisiz: suhbatlar ko'p bo'ladi - Claude kabi zich, tinch
 * ro'yxat; belgilar faqat yuqoridagi asosiy bo'limlarda (Yangi suhbat, Yozuvlar...).
 */
import { useMemo, useState, type ReactNode } from 'react';
import { ActivityIndicator, Alert, Pressable, SectionList, StyleSheet, Text, View } from 'react-native';

import type { ChatApi, ChatSummary } from '@/api/chat';
import { useChat } from '@/features/chat/chatStore';
import { groupOf, useChats, type HistoryGroup } from '@/features/chat/chatsStore';
import { useT } from '@/features/settings/settingsStore';
import type { TKey } from '@/i18n';
import { errorText, showToast } from '@/ui/errors';
import { PromptModal } from '@/ui/modals';
import { useTheme } from '@/ui/theme';
import { hit, radius, type as typeScale } from '@/ui/tokens';

const GROUP_KEYS: Record<HistoryGroup, TKey> = {
  today: 'history.today',
  yesterday: 'history.yesterday',
  week: 'history.week',
  earlier: 'history.earlier',
};

const ORDER: HistoryGroup[] = ['today', 'yesterday', 'week', 'earlier'];

interface Section {
  key: string;
  title: string;
  data: ChatSummary[];
}

/** Toza: nom bo'yicha (katta-kichik harf farqsiz) filtr; nomsiz suhbat "Yangi suhbat" deb qidiriladi. */
export function filterChats(items: ChatSummary[], query: string, untitled: string): ChatSummary[] {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return items;
  return items.filter((c) => (c.title || untitled).toLocaleLowerCase().includes(q));
}

export function ChatList({
  api,
  query,
  activeId,
  onOpen,
}: {
  api: ChatApi;
  /** Bo'sh emas bo'lsa - qidiruv: guruh sarlavhalari yashiriladi. */
  query: string;
  activeId: string;
  onOpen: (id: string) => void;
}) {
  const th = useTheme();
  const t = useT();
  const { items, loading, error, loaded } = useChats();
  const [renaming, setRenaming] = useState<ChatSummary | null>(null);
  const searching = query.trim().length > 0;

  const sections = useMemo<Section[]>(() => {
    const list = filterChats(items, query, t('history.untitled'));
    // Qidiruvda vaqt guruhlari shovqin - natijalar bitta tekis ro'yxat.
    if (searching) return list.length ? [{ key: 'results', title: '', data: list }] : [];
    const now = new Date();
    const map = new Map<HistoryGroup, ChatSummary[]>();
    for (const c of list) {
      const g = groupOf(c.updated_at ?? c.created_at, now);
      map.set(g, [...(map.get(g) ?? []), c]);
    }
    return ORDER.filter((g) => map.get(g)?.length).map((g) => ({ key: g, title: t(GROUP_KEYS[g]), data: map.get(g)! }));
  }, [items, query, searching, t]);

  const menu = (c: ChatSummary) => {
    const name = c.title || t('history.untitled');
    Alert.alert(name, undefined, [
      { text: t('history.rename'), onPress: () => setRenaming(c) },
      {
        text: t('history.delete'),
        style: 'destructive',
        onPress: () =>
          Alert.alert(t('history.deleteConfirm', { title: name }), undefined, [
            { text: t('common.cancel'), style: 'cancel' },
            {
              text: t('history.delete'),
              style: 'destructive',
              onPress: () =>
                void useChats
                  .getState()
                  .remove(api, c.chat_id)
                  .then(() => {
                    // Ochiq suhbat o'chirildi - ekranda yo'q suhbat qolmasin.
                    if (c.chat_id === activeId) useChat.getState().newChat();
                  })
                  .catch((err) => showToast(errorText(t, err))),
            },
          ]),
      },
      { text: t('common.cancel'), style: 'cancel' },
    ]);
  };

  let state: ReactNode = null;
  if (loading && !loaded) state = <ActivityIndicator style={s.spinner} color={th.textMuted} />;
  else if (error && !items.length)
    state = (
      <Pressable onPress={() => void useChats.getState().load(api)} accessibilityRole="button" style={s.state}>
        <Text style={[typeScale.sub, s.center, { color: th.textMuted }]}>{t('history.loadFailed')}</Text>
        <Text style={[typeScale.label, s.center, { color: th.text }]}>{t('common.retry')}</Text>
      </Pressable>
    );
  else if (loaded && !items.length) state = <Text style={[typeScale.sub, s.state, s.center, { color: th.textMuted }]}>{t('history.empty')}</Text>;
  else if (searching && !sections.length)
    state = <Text style={[typeScale.sub, s.state, s.center, { color: th.textMuted }]}>{t('nav.noResults')}</Text>;

  return (
    <View style={s.root}>
      {state ?? (
        <SectionList
          sections={sections}
          keyExtractor={(c) => c.chat_id}
          stickySectionHeadersEnabled={false}
          keyboardShouldPersistTaps="handled"
          // Qidiruvda klaviatura natijalarni yopadi - ro'yxatni surish uni yashiradi.
          keyboardDismissMode="on-drag"
          contentContainerStyle={s.content}
          renderSectionHeader={({ section }) =>
            section.title ? <Text style={[typeScale.micro, s.group, { color: th.textFaint }]}>{section.title}</Text> : null
          }
          renderItem={({ item }) => {
            const active = item.chat_id === activeId;
            return (
              <Pressable
                testID={`history-${item.chat_id}`}
                onPress={() => onOpen(item.chat_id)}
                onLongPress={() => menu(item)}
                delayLongPress={350}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                accessibilityHint={t('nav.chatHint')}
                android_ripple={{ color: th.border }}
                style={({ pressed }) => [s.row, { backgroundColor: active || pressed ? th.surfaceAlt : 'transparent' }]}>
                <Text style={[typeScale.body, { color: th.text }, active ? s.bold : null]} numberOfLines={1}>
                  {item.title || t('history.untitled')}
                </Text>
              </Pressable>
            );
          }}
        />
      )}
      <PromptModal
        visible={!!renaming}
        title={t('history.renameTitle')}
        initial={renaming?.title ?? ''}
        maxLength={120}
        onCancel={() => setRenaming(null)}
        onSubmit={(value) => {
          const c = renaming;
          setRenaming(null);
          if (c) void useChats.getState().rename(api, c.chat_id, value).catch((err) => showToast(errorText(t, err)));
        }}
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, minHeight: 0 },
  content: { paddingBottom: 8 },
  spinner: { marginTop: 24 },
  state: { paddingHorizontal: 20, paddingVertical: 16, gap: 6 },
  center: { textAlign: 'center' },
  group: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 4 },
  row: {
    minHeight: hit.min,
    justifyContent: 'center',
    marginHorizontal: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
    overflow: 'hidden',
  },
  bold: { fontWeight: '600' },
});
