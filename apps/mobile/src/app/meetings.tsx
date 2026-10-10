/**
 * Yig'ilishlar ro'yxati (spec 7.4): status chiplari, qisqacha, ochiq
 * vazifalar soni; tepada telefonda turgan (yuklanmagan) yozuvlar; pastga
 * tortib yangilash; ishlov ketayotganda 15 s da avtomatik yangilash; katta
 * qizil yozish tugmasi.
 *
 * `/meetings` - ikkinchi bo'lim: asosiy ekran Mini App (`index.tsx`), bu yerga
 * uning sozlamalaridagi "Yig'ilish yozuvlari" ({type:'venera:open'}) olib keladi.
 */
import { useInfiniteQuery } from '@tanstack/react-query';
import { router, Stack, useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import type { MeetingCard } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { formatDateTime, formatDuration } from '@/features/meeting/formatDate';
import { isProcessing } from '@/features/meeting/queries';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { pendingRows, uploadPercent, useQueueRows } from '@/features/upload/useQueue';
import { useServices } from '@/services';
import { Banner, Button, Card, Chip, Field, Muted, StatusChip, styles as ui } from '@/ui/components';
import { errorText } from '@/ui/errors';
import { useTheme } from '@/ui/theme';

const PAGE = 20;

export default function MeetingsScreen() {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const insets = useSafeAreaInsets();
  const { meetings } = useServices();
  const expired = useAuth((s) => s.expired);
  const recStatus = useRecorderStore((s) => s.machine.status);
  const [q, setQ] = useState('');
  const [focused, setFocused] = useState(true);
  const rows = useQueueRows();
  const local = pendingRows(rows);

  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, []),
  );

  const list = useInfiniteQuery({
    queryKey: ['meetings', 'list', q],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => meetings.list({ limit: PAGE, offset: pageParam, q }),
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
    refetchInterval: (query) => {
      const anyProcessing = query.state.data?.pages.some((p) => p.items.some((m) => isProcessing(m)));
      return focused && (anyProcessing || local.length > 0) ? 15_000 : false;
    },
  });

  const items = useMemo(() => {
    const all = list.data?.pages.flatMap((p) => p.items) ?? [];
    // Server allaqachon bilgan clientId'lar lokal ro'yxatda takrorlanmasin.
    return all;
  }, [list.data]);
  const serverClientIds = new Set(items.map((m) => m.clientId));
  const localOnly = local.filter((r) => !serverClientIds.has(r.clientId) || r.state === 'failed');
  const recording = recStatus === 'recording' || recStatus === 'paused';

  return (
    <View style={{ flex: 1 }}>
      <Stack.Screen
        options={{
          headerRight: () => (
            <View style={ui.row}>
              <Button small variant="ghost" title={t('list.myTasks')} onPress={() => router.push('/action-items')} />
              <Button small variant="ghost" style={{ marginLeft: 6 }} title="⚙" accessibilityLabel={t('list.settings')} onPress={() => router.push('/settings')} />
            </View>
          ),
        }}
      />
      <FlatList
        testID="meetings-list"
        data={items}
        keyExtractor={(m) => m.id}
        contentContainerStyle={{ padding: 12, paddingBottom: 120 + insets.bottom }}
        refreshControl={<RefreshControl refreshing={list.isRefetching} onRefresh={() => void list.refetch()} />}
        onEndReached={() => list.hasNextPage && !list.isFetchingNextPage && void list.fetchNextPage()}
        ListHeaderComponent={
          <View>
            {expired ? (
              <Banner tone="warn" text={t('list.sessionExpired')} action={{ title: t('login.submit'), onPress: () => useAuth.getState().setSignedOut(true) }} />
            ) : null}
            {list.isError && !list.data ? (
              <Banner
                tone="bad"
                testID="meetings-error"
                text={
                  // Mini App orqali kirgan, lekin bo'lim unga hali yoqilmagan odam (403/404).
                  list.error instanceof ApiError && (list.error.status === 403 || list.error.status === 404)
                    ? t('login.featureDisabled')
                    : errorText(t, list.error)
                }
                action={{ title: t('common.retry'), onPress: () => void list.refetch() }}
              />
            ) : null}
            {recording ? (
              <Banner tone="bad" text={`● ${t('record.recording')}`} action={{ title: t('record.title'), onPress: () => router.push('/record?src=app') }} />
            ) : null}
            <Field testID="meetings-search" placeholder={t('list.search')} value={q} onChangeText={setQ} />
            {localOnly.map((r) => (
              <LocalCard key={r.clientId} row={r} lang={lang} />
            ))}
          </View>
        }
        ListEmptyComponent={!list.isLoading && !localOnly.length ? <Muted style={{ padding: 24 }}>{t('list.empty')}</Muted> : null}
        renderItem={({ item }) => <MeetingRow m={item} lang={lang} />}
      />
      <Pressable
        testID="record-fab"
        accessibilityRole="button"
        accessibilityLabel={t('list.record')}
        onPress={() => router.push('/record?src=app')}
        style={[s.fab, { backgroundColor: th.record, bottom: 24 + insets.bottom }]}>
        <View style={s.fabDot} />
      </Pressable>
    </View>
  );
}

function MeetingRow({ m, lang }: { m: MeetingCard; lang: 'uz' | 'ru' | 'en' }) {
  const t = useT();
  const th = useTheme();
  return (
    <Pressable testID={`meeting-${m.id}`} accessibilityRole="button" accessibilityLabel={m.title} onPress={() => router.push(`/meeting/${m.id}`)}>
      <Card>
        <Text numberOfLines={2} style={[s.title, { color: th.text }]}>
          {m.title}
        </Text>
        <Muted>
          {formatDateTime(m.recordedAt, lang)}
          {m.durationSec ? ` · ${formatDuration(m.durationSec)}` : ''}
        </Muted>
        <View style={ui.wrap}>
          <StatusChip status={m.status} progress={m.progress} />
          {m.openActionItems > 0 ? <Chip label={t('list.openItems', { n: m.openActionItems })} tone="accent" /> : null}
        </View>
        {m.overview ? (
          <Text numberOfLines={2} style={[s.overview, { color: th.textMuted }]}>
            {m.overview}
          </Text>
        ) : null}
        {m.error ? <Text style={{ color: th.danger, marginTop: 4 }}>{m.error.message}</Text> : null}
      </Card>
    </Pressable>
  );
}

function LocalCard({ row, lang }: { row: QueueRow; lang: 'uz' | 'ru' | 'en' }) {
  const t = useT();
  const th = useTheme();
  const { uploader } = useServices();
  const pct = uploadPercent(row);
  const label = t(`local.${row.state}`);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={row.title ?? t('local.onPhone')}
      onPress={() => router.push(`/meeting/${row.serverId ?? row.clientId}${row.serverId ? '' : '?local=1'}`)}>
      <Card style={{ borderStyle: 'dashed' }}>
        <Text style={[s.title, { color: th.text }]}>{row.title ?? t('local.onPhone')}</Text>
        <Muted>
          {formatDateTime(row.startedAt, lang)}
          {row.durationSec ? ` · ${formatDuration(row.durationSec)}` : ''}
        </Muted>
        <View style={ui.wrap}>
          <Chip label={pct != null && row.state !== 'failed' ? `${label} ${pct}%` : label} tone={row.state === 'failed' ? 'bad' : 'info'} />
          {row.lastError && row.state !== 'failed' ? <Chip label={errorText(t, row.lastError)} tone="warn" /> : null}
        </View>
        {row.state === 'failed' ? (
          <View style={[ui.row, { marginTop: 6 }]}>
            <Text style={{ color: th.danger, flex: 1 }}>{row.lastError ? errorText(t, row.lastError) : ''}</Text>
            <Button small title={t('common.retry')} onPress={() => void uploader.retry(row.clientId)} />
          </View>
        ) : null}
      </Card>
    </Pressable>
  );
}

const s = StyleSheet.create({
  title: { fontSize: 16, fontWeight: '700', marginBottom: 2 },
  overview: { fontSize: 13, lineHeight: 18, marginTop: 6 },
  fab: {
    position: 'absolute',
    alignSelf: 'center',
    width: 76,
    height: 76,
    borderRadius: 38,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 6,
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
  },
  fabDot: { width: 28, height: 28, borderRadius: 14, backgroundColor: '#fff' },
});
