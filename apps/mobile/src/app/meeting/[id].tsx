/**
 * Yozuv sahifasi (spec 3.2): sarlavha + meta (sana, davomiylik, holat), belgili
 * tablar (Xulosa | Matn | Vazifalar | Savol), pastda doim turgan pleer. Xulosa tabining
 * tepasida "Xulosa | Xarita" almashtirgichi (Plaud kabi): xarita 5-tab bo'lganda 360 dp
 * telefonda "Vazifalar 2" va "Transcript" kesilib qolardi.
 * Sarlavhadagi ulashish belgisi - eksport varag'i (PDF, Word, Markdown, matn, subtitr, audio) -
 * ko'rib turilgan xulosa bilan. ⋮ menyusida (Slack/Telegram'dagi Plaud tugmalari bilan bir xil):
 * ulashish, «Bayonnoma» (rasmiy hujjat loyihasi - `MinutesSheet`), "Boshqa tilda qayta o'girish"
 * (doim - til ogohlantirishi bo'lmasa ham), nomlash, o'chirish.
 *
 * Pleer manbasi: telefondagi fayl, u yo'q bo'lsa - serverdagi audio
 * (`PlayerBar.useAudioChoice`). Shuning uchun yuklanayotgan yozuvni ham darhol
 * eshitish mumkin. Yuklash tugamagan bo'lsa tepada yuklash kartasi sababi bilan.
 *
 * `?local=1` - hali serverda id'si yo'q (Stop'dan darhol keyin) yozuv: telefondagi
 * sahifa (`LocalRecording`); yuklash tugashi bilan (`done`) server sahifasiga o'tadi.
 *
 * NIMA UCHUN bitta "xost" (`RecordingScreen`) va pleer unda: sahifa ichki qismi
 * almashadi (telefondagi -> server sahifasi, internet uzilsa server -> telefondagi), pleer
 * esa daraxtda O'SHA joyda qoladi. Aks holda yuklash tugagan lahzada eshitilayotgan
 * yozuv to'xtab, 0:00 ga qaytardi.
 */
import { Stack, useLocalSearchParams } from 'expo-router';
import {
  AudioLines,
  CloudOff,
  EllipsisVertical,
  FilePen,
  Languages,
  ListChecks,
  MessageCircleQuestionMark,
  Network,
  Pencil,
  ScrollText,
  Share2,
  Sparkles,
  Trash,
} from 'lucide-react-native';
import { useCallback, useState, type ReactNode } from 'react';
import { Alert, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '@/api/client';
import type { Lang, Meeting } from '@/api/types';
import { ActionItemsView } from '@/features/meeting/ActionItemsView';
import { ActionMenu } from '@/features/meeting/ActionMenu';
import { AskView } from '@/features/meeting/AskView';
import { ExportSheet } from '@/features/meeting/ExportSheet';
import { formatDateTime } from '@/features/meeting/formatDate';
import { LocalRecording } from '@/features/meeting/LocalRecording';
import { MeetingHeader } from '@/features/meeting/MeetingHeader';
import { MinutesSheet } from '@/features/meeting/MinutesSheet';
import { MindMapTab } from '@/features/meeting/MindMapView';
import { leaveRecording } from '@/features/meeting/nav';
import { AudioDock, useAudioChoice, type AudioChoice, type SeekRequest } from '@/features/meeting/PlayerBar';
import { useMeeting, useMeetingMutations, useSummaries } from '@/features/meeting/queries';
import { MeetingStatusPill } from '@/features/meeting/RecordingCard';
import { RETRANSCRIBE_TITLE, retranscribeTargets } from '@/features/meeting/retranscribe';
import { SummaryView } from '@/features/meeting/SummaryView';
import { TranscriptView } from '@/features/meeting/TranscriptView';
import { UploadStatusCard } from '@/features/meeting/UploadStatusCard';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { useQueue } from '@/features/upload/useQueue';
import { clearExports } from '@/lib/paths';
import { useServices } from '@/services';
import { Banner, Button, Loading, Segmented, styles as ui } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { errorText } from '@/ui/errors';
import { IconButton } from '@/ui/IconButton';
import { PromptModal } from '@/ui/modals';
import { useTheme } from '@/ui/theme';

type Tab = 'summary' | 'transcript' | 'actions' | 'ask';
/** Xulosa tabining ko'rinishi: matn (Qisqa xulosa + bo'limlar) yoki aqliy xarita. */
type SummaryMode = 'text' | 'map';

export default function MeetingRoute() {
  const { id, local } = useLocalSearchParams<{ id: string; local?: string }>();
  const { rows, loaded } = useQueue();
  if (local) {
    const row = rows.find((r) => r.clientId === id);
    // Server id yaratilishda paydo bo'ladi, lekin audio hali yuklanayotgan bo'lishi mumkin -
    // yuklash tugaguncha telefondagi sahifa (pleer + holat) ko'rsatiladi.
    const serverId = row?.serverId && row.state === 'done' ? row.serverId : null;
    return <RecordingScreen serverId={serverId} clientId={id} rows={rows} rowsLoaded={loaded} />;
  }
  return <RecordingScreen serverId={id} clientId={null} rows={rows} rowsLoaded={loaded} />;
}

/**
 * Yozuv sahifasining xosti: qaysi ichki qism (server / telefondagi / yuklanmoqda / xato)
 * va BITTA pleer. Pleer ichki qismdan keyingi ikkinchi bola - ichki qism almashganda u
 * qayta yaratilmaydi (ijro davom etadi).
 */
function RecordingScreen({
  serverId,
  clientId,
  rows,
  rowsLoaded,
}: {
  serverId: string | null;
  /** `?local=1` sahifasi: telefondagi qator clientId'si. */
  clientId: string | null;
  rows: QueueRow[];
  rowsLoaded: boolean;
}) {
  const t = useT();
  const q = useMeeting(serverId);
  const m = q.data ?? null;
  const row =
    rows.find(
      (r) => (clientId != null && r.clientId === clientId) || (serverId != null && r.serverId === serverId) || (m != null && r.clientId === m.clientId),
    ) ?? null;
  const [seek, setSeek] = useState<SeekRequest | null>(null);
  const onSeek = useCallback((sec: number) => setSeek({ t: sec, n: Date.now() }), []);
  const playbackKey = m?.id ?? row?.clientId ?? null;
  const choice = useAudioChoice(m, row, playbackKey);

  let body: ReactNode;
  let dock = true;
  if (m) {
    body = <MeetingBody m={m} localRow={row} choice={choice} seek={seek} onSeek={onSeek} />;
  } else if (row && (clientId != null || q.isError || q.failureCount > 0)) {
    // Telefondagi sahifa: hali yuklanmagan yozuv, server sahifasi yuklanayotgan lahza
    // (yuklash endi tugadi) yoki internet yo'q - fayl telefonda, uni baribir eshitish mumkin.
    // Server sahifasi so'ralgan (yoki yuklash endi tugagan), lekin kelmadi - sababini aytamiz.
    const failed = serverId ? (q.error ?? q.failureReason) : null;
    body = (
      <LocalRecording
        row={row}
        serverFailed={failed ? { text: errorText(t, failed), onRetry: () => void q.refetch() } : undefined}
      />
    );
  } else if (clientId != null) {
    dock = false;
    // Navbat hali o'qilmagan bo'lsa kutamiz; o'qilgan va qator yo'q - yozuv o'chirilgan/tozalangan.
    body = rowsLoaded ? <RecordingNotFound /> : <Loading />;
  } else if (q.isLoading || q.isPending) {
    dock = false;
    body = <Loading />;
  } else {
    dock = false;
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    body = (
      <View style={s.pad}>
        <Banner
          tone="bad"
          text={notFound ? t('detail.notFound') : errorText(t, q.error)}
          action={{ title: t('common.retry'), onPress: () => void q.refetch() }}
        />
      </View>
    );
  }

  return (
    <View style={s.root}>
      {body}
      {dock ? <AudioDock choice={choice} seek={seek} playbackKey={playbackKey ?? ''} durationHint={m?.durationSec ?? row?.durationSec ?? null} /> : null}
    </View>
  );
}

/** Deep link yoki bildirishnoma o'chirilgan/tozalangan yozuvga olib keldi - abadiy aylanma o'rniga. */
function RecordingNotFound() {
  const t = useT();
  return (
    <View style={s.root}>
      <Stack.Screen options={{ title: '' }} />
      <EmptyState
        testID="recording-not-found"
        icon={CloudOff}
        title={t('recs.notFound')}
        action={{ title: t('nav.recordings'), icon: AudioLines, onPress: leaveRecording, variant: 'secondary', testID: 'recording-not-found-back' }}
      />
    </View>
  );
}

function MeetingBody({
  m,
  localRow,
  choice,
  seek,
  onSeek,
}: {
  m: Meeting;
  localRow: QueueRow | null;
  choice: AudioChoice;
  seek: SeekRequest | null;
  onSeek: (sec: number) => void;
}) {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const services = useServices();
  const muts = useMeetingMutations(m.id);
  const [tab, setTab] = useState<Tab>('summary');
  const [summaryMode, setSummaryMode] = useState<SummaryMode>('text');
  const [editTitle, setEditTitle] = useState(false);
  const [menu, setMenu] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [minutesOpen, setMinutesOpen] = useState(false);
  // "Boshqa tilda qayta o'girish" -> maqsad tilini tanlash varag'i.
  const [relang, setRelang] = useState(false);
  // Xulosa tabida tanlangan xulosa - xarita va eksport ham shundan (null - asosiysi).
  const [summaryId, setSummaryId] = useState<string | null>(null);
  // Xulosalar ro'yxati xulosa ko'rinishi bilan UMUMIY keshda - qo'shimcha so'rov yo'q.
  const summaries = useSummaries(m.id, m.transcript.available, m.status === 'summarizing');
  const summaryCards = summaries.data?.items ?? [];
  const viewed = summaryCards.find((c) => c.id === summaryId) ?? summaryCards.find((c) => c.primary) ?? null;
  // Eksport faqat TAYYOR xulosadan; ro'yxat hali kelmagan bo'lsa - yozuvdagi asosiy xulosa holati.
  const exportReady = viewed ? viewed.status === 'ready' : m.primarySummaryId != null && m.summaryStatus === 'ready';

  const uploading = !m.upload.complete && !!localRow && localRow.state !== 'done';

  const confirmDelete = () =>
    Alert.alert(t('common.delete'), t('detail.deleteConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('common.delete'),
        style: 'destructive',
        onPress: () => {
          // AVVAL server: u o'chmasa (internet yo'q, 5xx) telefondagi YAGONA to'liq nusxa
          // saqlanib qoladi va xato toast'da ko'rinadi. Server o'chirgandan keyin telefondagi
          // nusxa ham ketadi - aks holda uploader uni clientId bilan qayta yaratib qo'yardi.
          muts.remove.mutate(undefined, {
            onSuccess: () => {
              void (async () => {
                if (localRow && localRow.state !== 'recording') {
                  await services.queue.remove(localRow.clientId).catch(() => {});
                  await services.files.remove(localRow.fileUri).catch(() => {});
                }
                // Eksport keshi (oxirgi ulashilgan PDF/Word/audio) ham: o'chirilgan yozuvning nusxasi
                // telefonda keyingi eksport yoki ilova qayta ochilguncha yotib qolmasin.
                clearExports();
                leaveRecording();
              })();
            },
          });
        },
      },
    ]);

  const confirmRetranscribe = (language: Lang) =>
    Alert.alert(t(RETRANSCRIBE_TITLE[language]), t('detail.retranscribeConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('common.ok'), onPress: () => muts.retranscribe.mutate({ language, expectedSpeakers: m.expectedSpeakers }) },
    ]);

  // "Vazifalar 2" - BITTA matn (Savol tabidagi "Vazifalar" tezkor chipi bilan adashmasin).
  const tabs = [
    { value: 'summary' as const, label: t('detail.tab.summary'), icon: Sparkles },
    { value: 'transcript' as const, label: t('detail.tab.transcript'), icon: ScrollText },
    { value: 'actions' as const, label: m.openActionItems ? `${t('detail.tab.actions')} ${m.openActionItems}` : t('detail.tab.actions'), icon: ListChecks },
    { value: 'ask' as const, label: t('detail.tab.ask'), icon: MessageCircleQuestionMark },
  ];

  const uploadCard = uploading && localRow ? <UploadStatusCard row={localRow} onDeleted={leaveRecording} /> : null;

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
      {/* Telefonda nusxa bo'lsa u ijro etiladi - "faqat matn qoldi" deyish noto'g'ri bo'lardi. */}
      {!m.audioAvailable && m.upload.complete && choice.kind === 'none' ? <Banner tone="neutral" text={t('detail.audioExpired')} /> : null}
    </View>
  );

  const modeSwitch = (
    <View style={s.modeSwitch}>
      <Segmented
        testIDPrefix="summary-view"
        value={summaryMode}
        onChange={setSummaryMode}
        options={[
          { value: 'text', label: t('recs.view.text'), icon: Sparkles },
          { value: 'map', label: t('recs.tab.map'), icon: Network },
        ]}
      />
    </View>
  );

  // Yuklash kartasi ko'rinib turganda "Yuklanmoqda" pill'i takror - sababni karta aytadi.
  const showPill = m.status !== 'ready' && !(uploading && m.status === 'uploading');

  return (
    <View style={s.root}>
      <Stack.Screen
        options={{
          title: '',
          headerRight: () => (
            <View style={s.headerActions}>
              <IconButton testID="meeting-export" icon={Share2} label={t('recs.export')} onPress={() => setExporting(true)} />
              <IconButton testID="meeting-menu" icon={EllipsisVertical} label={t('recs.menu')} onPress={() => setMenu(true)} />
            </View>
          ),
        }}
      />
      <View style={[s.top, { borderColor: th.border }]}>
        <MeetingHeader
          title={m.title}
          at={m.recordedAt}
          durationSec={m.durationSec}
          lang={lang}
          onTitlePress={() => setEditTitle(true)}
          titleA11y={t('detail.renameTitle')}
          pill={showPill ? <MeetingStatusPill status={m.status} progress={m.progress} /> : null}
        />
        <Segmented testIDPrefix="tab" options={tabs} value={tab} onChange={setTab} iconPosition="top" />
      </View>

      {tab === 'transcript' ? (
        <View style={s.transcript}>
          {uploadCard ? <View style={s.cardGap}>{uploadCard}</View> : null}
          <TranscriptView meeting={m} focus={seek} onSeek={onSeek} />
        </View>
      ) : tab === 'summary' && summaryMode === 'map' ? (
        // Xarita o'zi ikki tomonga aylanadi - tashqi ScrollView ichiga qo'yilmaydi.
        <View style={s.root}>
          <View style={s.mapHead}>{modeSwitch}</View>
          {uploadCard ? <View style={[s.cardGap, s.mapCard]}>{uploadCard}</View> : null}
          <MindMapTab meeting={m} summaryId={summaryId} onSeek={onSeek} />
        </View>
      ) : (
        <ScrollView style={s.root} contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          {tab === 'summary' ? modeSwitch : null}
          {uploadCard ? <View style={s.cardGap}>{uploadCard}</View> : null}
          {banners}
          {tab === 'summary' ? (
            <SummaryView
              meeting={m}
              speakers={m.speakers}
              onSeek={onSeek}
              onAcceptName={(speakerId, name) => muts.renameSpeaker.mutate({ speakerId, name })}
              selectedId={summaryId}
              onSelect={setSummaryId}
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
      <ActionMenu
        visible={menu}
        title={t('recs.menu')}
        onClose={() => setMenu(false)}
        items={[
          { key: 'export', title: t('recs.export'), icon: Share2, onPress: () => setExporting(true) },
          { key: 'minutes', title: t('minutes.title'), icon: FilePen, onPress: () => setMinutesOpen(true) },
          { key: 'retranscribe', title: t('detail.retranscribeOther'), icon: Languages, onPress: () => setRelang(true) },
          { key: 'rename', title: t('tr.rename'), icon: Pencil, onPress: () => setEditTitle(true) },
          { key: 'delete', title: t('common.delete'), icon: Trash, destructive: true, onPress: confirmDelete },
        ]}
      />
      {/* Ikkinchi varaq birinchisi yopilgandan keyin ochiladi (ActionMenu amalni yopilishdan keyin bajaradi). */}
      <ActionMenu
        visible={relang}
        title={t('detail.retranscribeOther')}
        onClose={() => setRelang(false)}
        items={retranscribeTargets(m.language).map((language) => ({
          key: `relang-${language}`,
          title: t(RETRANSCRIBE_TITLE[language]),
          icon: Languages,
          onPress: () => confirmRetranscribe(language),
        }))}
      />
      <MinutesSheet
        visible={minutesOpen}
        onClose={() => setMinutesOpen(false)}
        meetingId={m.id}
        title={m.title}
        // Hujjat tili default'i yig'ilish tilidan (uz -> kirill, server qoidasi).
        meetingLanguage={m.language}
      />
      <ExportSheet
        visible={exporting}
        onClose={() => setExporting(false)}
        meetingId={m.id}
        title={m.title}
        // Ko'rib turilgan xulosa: boshqa shablonni o'qib turgan odam aynan o'shani ulashadi.
        hasSummary={exportReady}
        summaryId={viewed && !viewed.primary ? viewed.id : null}
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  pad: { padding: 16 },
  top: { paddingHorizontal: 16, paddingTop: 4, paddingBottom: 12, gap: 14, borderBottomWidth: StyleSheet.hairlineWidth },
  transcript: { flex: 1, paddingHorizontal: 12, paddingTop: 10 },
  scroll: { padding: 12, paddingBottom: 32 },
  cardGap: { marginBottom: 12 },
  mapCard: { marginHorizontal: 12, marginTop: 10, marginBottom: 0 },
  modeSwitch: { marginBottom: 10 },
  mapHead: { paddingHorizontal: 12, paddingTop: 12 },
  headerActions: { flexDirection: 'row', alignItems: 'center' },
});
