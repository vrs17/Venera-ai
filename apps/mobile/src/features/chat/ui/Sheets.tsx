/**
 * Chat oynalari: manbalar ro'yxati va suhbatlar tarixi (Mini App `SourcesSheet`,
 * `HistorySheet` kabi). Ikkalasi - pastdan chiqadigan varaq; orqaga tugmasi yopadi.
 */
import { BookOpen, Database, Landmark, MessageSquarePlus, X } from 'lucide-react-native';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Linking, Modal, Pressable, ScrollView, SectionList, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { AnswerSource, ChatApi, ChatSummary } from '@/api/chat';
import { groupOf, useChats, type HistoryGroup } from '@/features/chat/chatsStore';
import { useT } from '@/features/settings/settingsStore';
import type { TKey } from '@/i18n';
import { errorText, showToast } from '@/ui/errors';
import { PromptModal } from '@/ui/modals';
import { useTheme, type Theme } from '@/ui/theme';

function Sheet({ visible, onClose, title, children, full }: { visible: boolean; onClose: () => void; title: string; children: React.ReactNode; full?: boolean }) {
  const th = useTheme();
  const t = useT();
  const insets = useSafeAreaInsets();
  const s = useMemo(() => makeStyles(th), [th]);
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={s.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel={t('common.close')} />
        <View style={[s.sheet, full ? s.sheetFull : null, { paddingBottom: Math.max(insets.bottom, 12) }]}>
          <View style={s.grabber} />
          <View style={s.head}>
            <Text style={s.title} accessibilityRole="header">
              {title}
            </Text>
            <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel={t('common.close')} style={s.close}>
              <X size={18} color={th.textSoft} strokeWidth={2} />
            </Pressable>
          </View>
          {children}
        </View>
      </View>
    </Modal>
  );
}

// --- Manbalar ---------------------------------------------------------------------

function kindOf(src: AnswerSource): 'doc' | 'law' | 'data' {
  if (src.kind === 'law') return 'law';
  if (src.kind === 'hrm' || src.kind === 'crm' || src.tool || src.marker) return 'data';
  return 'doc';
}

export function SourcesSheet({ visible, onClose, sources, focus, api }: { visible: boolean; onClose: () => void; sources: AnswerSource[]; focus?: string; api: ChatApi }) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const [opening, setOpening] = useState<number | null>(null);

  const open = async (src: AnswerSource, i: number) => {
    const kind = kindOf(src);
    try {
      if (kind === 'law' && src.url && /^https:\/\//i.test(src.url)) {
        await Linking.openURL(src.url);
        return;
      }
      if (kind === 'doc' && src.doc_id) {
        setOpening(i);
        const link = await api.docLink(src.doc_id, `${(src.title || 'hujjat').slice(0, 60)}.pdf`);
        await Linking.openURL(api.absolute(link.url));
      }
    } catch (err) {
      showToast(errorText(t, err) || t('chat.openFailed'));
    } finally {
      setOpening(null);
    }
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={t('chat.sourcesTitle')}>
      <ScrollView style={{ maxHeight: 520 }} contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 8, gap: 8 }}>
        {sources.map((src, i) => {
          const kind = kindOf(src);
          const marker = src.marker || (src.citation_index != null ? String(src.citation_index) : '');
          const focused = !!focus && marker === focus.replace(/^T/, src.marker ? 'T' : '');
          const Icon = kind === 'law' ? Landmark : kind === 'data' ? Database : BookOpen;
          const meta = [
            kind === 'data' ? t('chat.sourceData') : kind === 'law' ? t('chat.sourceLaw') : null,
            src.section,
            src.page ? t('chat.sourcePage', { n: src.page }) : null,
          ]
            .filter(Boolean)
            .join(' · ');
          const tappable = (kind === 'doc' && !!src.doc_id) || (kind === 'law' && !!src.url);
          return (
            <Pressable
              key={`${marker}-${i}`}
              disabled={!tappable}
              onPress={() => void open(src, i)}
              accessibilityRole={tappable ? 'button' : undefined}
              style={({ pressed }) => [s.srcRow, focused ? { borderColor: th.brand } : null, pressed && tappable ? { opacity: 0.7 } : null]}>
              <View style={s.srcIcon}>
                <Icon size={16} color={th.textSoft} strokeWidth={2} />
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={s.srcTitle} numberOfLines={3}>
                  {marker ? <Text style={s.srcMarker}>{`[${marker}] `}</Text> : null}
                  {src.title || src.tool || '—'}
                </Text>
                {meta ? <Text style={s.srcMeta}>{meta}</Text> : null}
                {src.digest ? (
                  <Text style={s.srcDigest} numberOfLines={4}>
                    {src.digest}
                  </Text>
                ) : null}
              </View>
              {opening === i ? <ActivityIndicator size="small" color={th.textMuted} /> : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </Sheet>
  );
}

// --- Suhbatlar tarixi ---------------------------------------------------------------

const GROUP_KEYS: Record<HistoryGroup, TKey> = {
  today: 'history.today',
  yesterday: 'history.yesterday',
  week: 'history.week',
  earlier: 'history.earlier',
};

export function HistorySheet({
  visible,
  onClose,
  api,
  activeId,
  onOpen,
  onNew,
  onRemovedActive,
}: {
  visible: boolean;
  onClose: () => void;
  api: ChatApi;
  activeId: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRemovedActive: () => void;
}) {
  const th = useTheme();
  const t = useT();
  const s = useMemo(() => makeStyles(th), [th]);
  const { items, loading, error, loaded } = useChats();
  const [renaming, setRenaming] = useState<ChatSummary | null>(null);

  const sections = useMemo(() => {
    const now = new Date();
    const order: HistoryGroup[] = ['today', 'yesterday', 'week', 'earlier'];
    const map = new Map<HistoryGroup, ChatSummary[]>();
    for (const c of items) {
      const g = groupOf(c.updated_at ?? c.created_at, now);
      map.set(g, [...(map.get(g) ?? []), c]);
    }
    return order.filter((g) => map.get(g)?.length).map((g) => ({ key: g, title: t(GROUP_KEYS[g]), data: map.get(g)! }));
  }, [items, t]);

  const menu = (c: ChatSummary) => {
    Alert.alert(c.title || t('history.untitled'), undefined, [
      { text: t('history.rename'), onPress: () => setRenaming(c) },
      {
        text: t('history.delete'),
        style: 'destructive',
        onPress: () =>
          Alert.alert(t('history.deleteConfirm', { title: c.title || t('history.untitled') }), undefined, [
            { text: t('common.cancel'), style: 'cancel' },
            {
              text: t('history.delete'),
              style: 'destructive',
              onPress: () =>
                void useChats
                  .getState()
                  .remove(api, c.chat_id)
                  .then(() => {
                    if (c.chat_id === activeId) onRemovedActive();
                  })
                  .catch((err) => showToast(errorText(t, err))),
            },
          ]),
      },
      { text: t('common.cancel'), style: 'cancel' },
    ]);
  };

  return (
    <Sheet visible={visible} onClose={onClose} title={t('chat.history')} full>
      <Pressable
        testID="history-new"
        onPress={() => {
          onNew();
          onClose();
        }}
        style={({ pressed }) => [s.newBtn, pressed ? { opacity: 0.8 } : null]}
        accessibilityRole="button">
        <MessageSquarePlus size={18} color={th.primaryText} strokeWidth={2} />
        <Text style={s.newText}>{t('chat.newChat')}</Text>
      </Pressable>
      {loading && !loaded ? <ActivityIndicator style={{ marginTop: 24 }} color={th.textMuted} /> : null}
      {error && !items.length ? (
        <Pressable onPress={() => void useChats.getState().load(api)} style={{ padding: 16 }}>
          <Text style={s.empty}>{t('history.loadFailed')}</Text>
          <Text style={[s.empty, { color: th.text, fontWeight: '600', marginTop: 6 }]}>{t('common.retry')}</Text>
        </Pressable>
      ) : null}
      {loaded && !items.length && !error ? <Text style={[s.empty, { padding: 16 }]}>{t('history.empty')}</Text> : null}
      <SectionList
        sections={sections}
        keyExtractor={(c) => c.chat_id}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={{ paddingBottom: 16 }}
        renderSectionHeader={({ section }) => <Text style={s.group}>{section.title}</Text>}
        renderItem={({ item }) => {
          const active = item.chat_id === activeId;
          return (
            <Pressable
              testID={`history-${item.chat_id}`}
              onPress={() => {
                onOpen(item.chat_id);
                onClose();
              }}
              onLongPress={() => menu(item)}
              delayLongPress={350}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              style={({ pressed }) => [s.row, active ? { backgroundColor: th.surfaceAlt } : null, pressed ? { opacity: 0.7 } : null]}>
              <Text style={[s.rowText, active ? { fontWeight: '700' } : null]} numberOfLines={1}>
                {item.title || t('history.untitled')}
              </Text>
            </Pressable>
          );
        }}
      />
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
    </Sheet>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.45)' },
    sheet: { backgroundColor: th.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: '88%', paddingTop: 8 },
    sheetFull: { height: '88%' },
    grabber: { alignSelf: 'center', width: 36, height: 4, borderRadius: 2, backgroundColor: th.borderStrong, marginBottom: 6 },
    head: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 },
    title: { flex: 1, color: th.text, fontSize: 18, fontWeight: '700' },
    close: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: th.surfaceAlt },
    srcRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', borderWidth: 1, borderColor: th.border, borderRadius: 14, padding: 12 },
    srcIcon: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: th.surfaceAlt },
    srcTitle: { color: th.text, fontSize: 15, lineHeight: 21, fontWeight: '600' },
    srcMarker: { color: th.textMuted, fontWeight: '700' },
    srcMeta: { color: th.textMuted, fontSize: 13, marginTop: 2 },
    srcDigest: { color: th.textSoft, fontSize: 13, lineHeight: 18, marginTop: 4 },
    newBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
      marginHorizontal: 16,
      marginBottom: 8,
      height: 46,
      borderRadius: 23,
      backgroundColor: th.primary,
    },
    newText: { color: th.primaryText, fontSize: 15, fontWeight: '700' },
    group: { color: th.textMuted, fontSize: 13, fontWeight: '600', paddingHorizontal: 16, paddingTop: 14, paddingBottom: 6 },
    row: { marginHorizontal: 8, paddingHorizontal: 12, paddingVertical: 12, borderRadius: 12 },
    rowText: { color: th.text, fontSize: 16 },
    empty: { color: th.textMuted, fontSize: 15, textAlign: 'center' },
  });
}
