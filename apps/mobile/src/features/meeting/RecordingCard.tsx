/**
 * Yozuvlar ro'yxatidagi bitta karta (Plaud uslubi): chapda holat belgisi, sarlavha
 * va davomiylik, pastda soat + holat pill'lari, tayyor bo'lsa 2 qatorli qisqacha.
 *
 * Server kartasi va telefondagi (yuklanmagan) yozuv bir xil ko'rinishda - farq
 * faqat belgi va pill'da (sabab bo'yicha: "Internet yo'q", "Yuklanmoqda 42%").
 */
import { router } from 'expo-router';
import { AudioLines, CircleAlert, CloudUpload, type LucideIcon } from 'lucide-react-native';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Lang, MeetingCard, MeetingStatus } from '@/api/types';
import { useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { uploadStatus } from '@/features/upload/uploadStatus';
import type { TFn } from '@/i18n';
import { IconTile, type IconTileTone } from '@/ui/IconTile';
import { StatusPill, type PillTone } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

import { formatDuration, formatTime } from './formatDate';
import type { Tone } from './summaryModel';
import type { TimelineItem } from './timeline';
import { uploadListTile, uploadPill } from './UploadStatusCard';

const STATUS_TONES: Record<MeetingStatus, Tone> = {
  uploading: 'info',
  uploaded: 'neutral',
  transcribing: 'info',
  summarizing: 'accent',
  ready: 'good',
  failed: 'bad',
  waiting_quota: 'warn',
};

/** "Matnga o'girilmoqda 42%" - BITTA matn (testlar va TalkBack uchun). */
export function meetingStatusLabel(t: TFn, status: MeetingStatus, progress: number | null | undefined): string {
  const label = t(`status.${status}`);
  return progress != null && status !== 'ready' && status !== 'failed' ? `${label} ${Math.round(progress)}%` : label;
}

export function MeetingStatusPill({ status, progress }: { status: MeetingStatus; progress?: number | null }) {
  const t = useT();
  return <StatusPill label={meetingStatusLabel(t, status, progress)} tone={STATUS_TONES[status]} />;
}

/** Telefondagi yozuv sarlavhasi: nom yo'q bo'lsa "Yozuv, 14:05". */
export function localTitle(row: QueueRow, t: TFn): string {
  return row.title ?? t('recs.untitled', { time: formatTime(row.startedAt) });
}

/**
 * Telefondagi yozuv DOIM telefondagi sahifaga ochiladi (server id bo'lsa ham): bu karta
 * ro'yxatda alohida turibdi - demak server kartasi yo'q (ko'pincha internet yo'q).
 * Server sahifasi internetsiz ochilmaydi, telefondagi sahifa esa faylni darhol ijro
 * etadi; yuklash tugagach u o'zi server sahifasiga almashadi.
 */
export function localHref(row: QueueRow): string {
  return `/meeting/${row.clientId}?local=1`;
}

function serverTile(status: MeetingStatus): { icon: LucideIcon; tone: IconTileTone } {
  // `raised` (sahifa foni): karta foni `surfaceAlt` - `plain` plitka unda ko'rinmay qolardi.
  if (status === 'ready') return { icon: AudioLines, tone: 'raised' };
  if (status === 'failed') return { icon: CircleAlert, tone: 'bad' };
  if (status === 'uploading') return { icon: CloudUpload, tone: 'info' };
  return { icon: AudioLines, tone: 'info' };
}

/** memo: ro'yxat (soat, polling) qayta chizilganda o'zgarmagan kartalar qayta hisoblanmaydi. */
export const RecordingCard = memo(function RecordingCard({ item, lang, online }: { item: TimelineItem; lang: Lang; online: boolean | null }) {
  const t = useT();
  if (item.kind === 'local') {
    const row = item.row;
    const st = uploadStatus(row, { online });
    const pill = uploadPill(st, t);
    return (
      <CardShell
        testID={`local-${row.clientId}`}
        tile={uploadListTile(st.cause)}
        title={localTitle(row, t)}
        // Kun guruhi bilan bir xil vaqt (`timeline`): tayyor fayl - qo'shilgan, yozuv - boshlangan.
        time={formatTime(item.at, lang)}
        durationSec={row.durationSec}
        pills={pill ? [{ key: 'up', ...pill }] : []}
        onPress={() => router.push(localHref(row))}
      />
    );
  }
  const m: MeetingCard = item.card;
  const up = item.local ? uploadStatus(item.local, { online }) : null;
  const upPill = up ? uploadPill(up, t) : null;
  const pills: PillSpec[] = [];
  if (upPill) pills.push({ key: 'up', ...upPill });
  else if (m.status !== 'ready') pills.push({ key: 'status', label: meetingStatusLabel(t, m.status, m.progress), tone: STATUS_TONES[m.status] });
  if (m.openActionItems > 0) pills.push({ key: 'tasks', label: t('recs.tasks', { n: m.openActionItems }), tone: 'accent' });
  return (
    <CardShell
      testID={`meeting-${m.id}`}
      tile={up && upPill ? uploadListTile(up.cause) : serverTile(m.status)}
      title={m.title}
      time={formatTime(item.at, lang)}
      durationSec={m.durationSec}
      pills={pills}
      overview={m.status === 'ready' ? m.overview : null}
      error={m.status === 'failed' ? (m.error?.message ?? null) : null}
      onPress={() => router.push(`/meeting/${m.id}`)}
    />
  );
});

type PillSpec = { key: string; label: string; tone: PillTone; dot?: boolean };

function CardShell({
  testID,
  tile,
  title,
  time,
  durationSec,
  pills,
  overview,
  error,
  onPress,
}: {
  testID: string;
  tile: { icon: LucideIcon; tone: IconTileTone };
  title: string;
  time: string;
  durationSec: number | null;
  pills: PillSpec[];
  overview?: string | null;
  error?: string | null;
  onPress: () => void;
}) {
  const th = useTheme();
  const dur = formatDuration(durationSec);
  // TalkBack bitta jumlada: nom, soat, davomiylik, holat.
  const a11y = [title, time, dur, ...pills.map((p) => p.label)].filter(Boolean).join(', ');
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={a11y}
      onPress={onPress}
      android_ripple={{ color: th.border }}
      style={({ pressed }) => [s.card, { backgroundColor: pressed ? th.border : th.surfaceAlt }]}>
      <IconTile icon={tile.icon} tone={tile.tone} />
      <View style={s.body}>
        <View style={s.top}>
          <Text numberOfLines={2} style={[typeScale.headline, s.title, { color: th.text }]}>
            {title}
          </Text>
          {dur ? <Text style={[typeScale.caption, s.tabular, { color: th.textMuted }]}>{dur}</Text> : null}
        </View>
        <View style={s.meta}>
          {time ? <Text style={[typeScale.caption, s.tabular, { color: th.textMuted }]}>{time}</Text> : null}
          {pills.map((p) => (
            // Neytral pill foni karta foniga juda yaqin - sahifa fonida ajralib tursin.
            <StatusPill key={p.key} label={p.label} tone={p.tone} dot={p.dot} style={p.tone === 'neutral' ? { backgroundColor: th.bg } : undefined} />
          ))}
        </View>
        {overview ? (
          <Text numberOfLines={2} style={[typeScale.sub, { color: th.textMuted }]}>
            {overview}
          </Text>
        ) : null}
        {error ? (
          <Text numberOfLines={1} style={[typeScale.caption, { color: th.danger }]}>
            {error}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14, borderRadius: radius.lg, marginBottom: 8, overflow: 'hidden' },
  body: { flex: 1, gap: 6 },
  top: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  title: { flex: 1, fontSize: 16, lineHeight: 21 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  tabular: { fontVariant: ['tabular-nums'] },
});
