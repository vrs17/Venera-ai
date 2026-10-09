/**
 * Yig'ilish sahifasi (spec 7.4): sarlavha (tahrirlanadi), sana, davomiylik,
 * holat va progress; yopishqoq pleer; tablar: Xulosa | Matn | Vazifalar | Savol.
 *
 * `?local=1` - hali serverda id'si yo'q (Stop'dan darhol keyin) yozuv:
 * navbat qatori ko'rsatiladi, server id paydo bo'lishi bilan haqiqiy sahifa.
 */
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import type { Lang, Meeting } from '@/api/types';
import { ActionItemsView } from '@/features/meeting/ActionItemsView';
import { AskView } from '@/features/meeting/AskView';
import { formatDateTime, formatDuration } from '@/features/meeting/formatDate';
import { PlayerBar, type SeekRequest } from '@/features/meeting/PlayerBar';
import { useMeeting, useMeetingMutations } from '@/features/meeting/queries';
import { SummaryView } from '@/features/meeting/SummaryView';
import { TranscriptView } from '@/features/meeting/TranscriptView';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { uploadPercent, useQueueRows } from '@/features/upload/useQueue';
import { useServices } from '@/services';
import { Banner, Button, Card, Chip, Loading, Muted, Segmented, StatusChip, styles as ui } from '@/ui/components';
import { errorText } from '@/ui/errors';
import { PromptModal } from '@/ui/modals';
import { useTheme } from '@/ui/theme';

type Tab = 'summary' | 'transcript' | 'actions' | 'ask';

export default function MeetingRoute() {
  const { id, local } = useLocalSearchParams<{ id: string; local?: string }>();
  const rows = useQueueRows();
  if (local) {
    const row = rows.find((r) => r.clientId === id);
    // Server id yaratilishda paydo bo'ladi, lekin audio hali yuklanayotgan bo'lishi mumkin -
    // yuklash tugaguncha telefondagi holat (progress) ko'rsatiladi.
    if (row?.serverId && row.state === 'done') return <MeetingDetail id={row.serverId} />;
    return <LocalPending row={row ?? null} />;
  }
  return <MeetingDetail id={id} />;
}

function LocalPending({ row }: { row: QueueRow | null }) {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const { uploader } = useServices();
  if (!row) return <Loading />;
  const pct = uploadPercent(row);
  return (
    <ScrollView contentContainerStyle={{ padding: 16 }}>
      <Card>
        <Text style={[s.title, { color: th.text }]}>{row.title ?? t('local.onPhone')}</Text>
        <Muted>
          {formatDateTime(row.startedAt, lang)}
          {row.durationSec ? ` · ${formatDuration(row.durationSec)}` : ''}
        </Muted>
        <View style={ui.wrap}>
          <Chip label={`${t(`local.${row.state}`)}${pct != null ? ` ${pct}%` : ''}`} tone={row.state === 'failed' ? 'bad' : 'info'} />
        </View>
      </Card>
      <Banner tone="info" text={t('detail.localPending')} />
      {row.state === 'failed' ? (
        <Banner
          tone="bad"
          text={errorText(t, row.lastError)}
          action={{ title: t('common.retry'), onPress: () => void uploader.retry(row.clientId) }}
        />
      ) : (
        <Button variant="secondary" title={t('settings.uploadNow')} onPress={() => void uploader.runOnce()} />
      )}
    </ScrollView>
  );
}

export function MeetingDetail({ id }: { id: string }) {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const q = useMeeting(id);
  const muts = useMeetingMutations(id);
  const [tab, setTab] = useState<Tab>('summary');
  const [seek, setSeek] = useState<SeekRequest | null>(null);
  const [editTitle, setEditTitle] = useState(false);
  const onSeek = useCallback((sec: number) => setSeek({ t: sec, n: Date.now() }), []);

  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <View style={{ padding: 16 }}>
        <Banner tone="bad" text={notFound ? t('detail.notFound') : t('common.error')} action={{ title: t('common.retry'), onPress: () => void q.refetch() }} />
      </View>
    );
  }
  const m: Meeting = q.data;

  const confirmDelete = () =>
    Alert.alert(t('common.delete'), t('detail.deleteConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('common.delete'),
        style: 'destructive',
        onPress: () => muts.remove.mutate(undefined, { onSuccess: () => router.back() }),
      },
    ]);

  const confirmRetranscribe = (language: Lang) =>
    Alert.alert(language === 'ru' ? t('detail.retranscribeRu') : t('detail.retranscribeEn'), t('detail.retranscribeConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('common.ok'), onPress: () => muts.retranscribe.mutate({ language, expectedSpeakers: m.expectedSpeakers }) },
    ]);

  const tabs: { value: Tab; label: string }[] = [
    { value: 'summary', label: t('detail.tab.summary') },
    { value: 'transcript', label: t('detail.tab.transcript') },
    { value: 'actions', label: m.openActionItems ? `${t('detail.tab.actions')} ${m.openActionItems}` : t('detail.tab.actions') },
    { value: 'ask', label: t('detail.tab.ask') },
  ];

  const banners = (
    <View>
      {m.error && m.status === 'failed' ? (
        <Banner
          tone="bad"
          testID="meeting-error"
          text={m.error.message}
          action={m.error.retryable ? { title: t('detail.retryProcessing'), onPress: () => muts.retry.mutate() } : undefined}
        />
      ) : null}
      {m.status === 'waiting_quota' ? (
        <Banner
          tone="warn"
          text={t('detail.waitingQuota', { time: m.error?.retryAt ? formatDateTime(m.error.retryAt, lang) : '-' })}
          action={{ title: t('detail.retryProcessing'), onPress: () => muts.retry.mutate() }}
        />
      ) : null}
      {m.languageWarning === 'mostly_other_language' ? (
        <View>
          <Banner tone="warn" testID="language-warning" text={t('detail.languageWarning')} />
          <View style={[ui.row, { marginBottom: 10 }]}>
            <Button small variant="secondary" title={t('detail.retranscribeRu')} onPress={() => confirmRetranscribe('ru')} />
            <Button small variant="secondary" style={{ marginLeft: 8 }} title={t('detail.retranscribeEn')} onPress={() => confirmRetranscribe('en')} />
          </View>
        </View>
      ) : null}
      {m.transcript.engine === 'router' ? <Banner tone="info" text={t('detail.routerMode')} /> : null}
      {!m.audioAvailable && m.upload.complete ? <Banner tone="neutral" text={t('detail.audioExpired')} /> : null}
    </View>
  );

  return (
    <View style={{ flex: 1 }}>
      <Stack.Screen
        options={{
          title: '',
          headerRight: () => <Button small variant="ghost" title={t('common.delete')} onPress={confirmDelete} />,
        }}
      />
      <View style={[s.top, { borderColor: th.border }]}>
        <Pressable onPress={() => setEditTitle(true)} accessibilityRole="button" accessibilityLabel={t('detail.renameTitle')}>
          <Text testID="meeting-title" numberOfLines={2} style={[s.title, { color: th.text }]}>
            {m.title} ✎
          </Text>
        </Pressable>
        <View style={[ui.row, { flexWrap: 'wrap' }]}>
          <Muted>
            {formatDateTime(m.recordedAt, lang)}
            {m.durationSec ? ` · ${formatDuration(m.durationSec)}` : ''}
            {'  '}
          </Muted>
          <StatusChip status={m.status} progress={m.progress} />
        </View>
        {m.upload.complete ? <View style={{ marginTop: 8 }}><PlayerBar meetingId={m.id} available={m.audioAvailable} seek={seek} /></View> : null}
        <Segmented testIDPrefix="tab" options={tabs} value={tab} onChange={setTab} />
      </View>

      {tab === 'transcript' ? (
        <View style={{ flex: 1, paddingHorizontal: 12, paddingTop: 10 }}>
          <TranscriptView meeting={m} focus={seek} onSeek={onSeek} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 48 }} keyboardShouldPersistTaps="handled">
          {banners}
          {tab === 'summary' ? (
            <SummaryView
              meeting={m}
              speakers={m.speakers}
              onSeek={onSeek}
              onAcceptName={(speakerId, name) => muts.renameSpeaker.mutate({ speakerId, name })}
            />
          ) : null}
          {tab === 'actions' ? <ActionItemsView meeting={m} speakers={m.speakers} onSeek={onSeek} /> : null}
          {tab === 'ask' ? <AskView meeting={m} speakers={m.speakers} onSeek={onSeek} /> : null}
        </ScrollView>
      )}

      <PromptModal
        visible={editTitle}
        title={t('detail.renameTitle')}
        initial={m.title}
        maxLength={120}
        onCancel={() => setEditTitle(false)}
        onSubmit={(title) => {
          setEditTitle(false);
          if (title && title !== m.title) muts.patch.mutate({ title });
        }}
      />
    </View>
  );
}

const s = StyleSheet.create({
  top: { paddingHorizontal: 12, paddingTop: 10, paddingBottom: 10, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: 20, fontWeight: '800', marginBottom: 4 },
});
