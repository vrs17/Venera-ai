/**
 * Yozuvlar ekranidagi "Qo'ng'iroqlar" bo'limi: Samsung Telefon yozgan qo'ng'iroqlar
 * (suhbatdosh, vaqt, davomiylik, hajm) va har birida "Yuborish" yoki holat.
 *
 * Holatlar (birinchi mos kelgani):
 *  - aniqlash yoqilmagan -> tanishtiruv: "Yoqish" (rozilik eslatmasi + ruxsat), "Qo'ng'iroqni qanday yozish";
 *  - ruxsat yo'q -> "Ruxsat berish" (yopilgan bo'lsa - tizim sozlamasi);
 *  - yozuv yo'q -> Samsung'da yozish yoki boshqa telefondan "Ulashish";
 *  - ro'yxat: tepada "Avtomatik yuborish" kaliti, pastda qo'ng'iroqlar kunlar bo'yicha
 *    ("Bugun", "Kecha" - Yozuvlar vaqt chizig'i bilan bir xil, kartada faqat soat).
 *
 * Yuborilgan qo'ng'iroq navbatda bo'lsa - yozuvlar bilan bir xil yuklash pill'i (sabab bilan),
 * bosilsa yozuv sahifasi ochiladi; navbatdan chiqib ketgan bo'lsa - "Yuborildi" va bosilsa
 * serverdagi xulosa (id ma'lum bo'lsa) yoki Yozuvlar qidiruvi suhbatdosh nomi bilan.
 */
import { router } from 'expo-router';
import { ChevronRight, LockKeyhole, Phone, PhoneCall, PhoneOff, Send } from 'lucide-react-native';
import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, SectionList, StyleSheet, Text, View, type SectionListData } from 'react-native';

import type { Lang } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import type { CallRecording } from '@/features/entry/nativeEntry';
import { formatDuration, formatTime, tashkentDayKey } from '@/features/meeting/formatDate';
import { localHref } from '@/features/meeting/RecordingCard';
import { dayLabel } from '@/features/meeting/timeline';
import { uploadPill } from '@/features/meeting/UploadStatusCard';
import { useSettings, useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { uploadStatus, useOnline } from '@/features/upload/uploadStatus';
import { useQueueRows } from '@/features/upload/useQueue';
import { useServices } from '@/services';
import { Button } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { IconTile } from '@/ui/IconTile';
import { ListGroup, ListRow } from '@/ui/list';
import { StatusPill, type PillTone } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

import { callSendDeps, currentSendOptions, kickCallAutoSend, useCallAutoSend } from './CallAutoSend';
import { useCalls, type SentMark } from './callsStore';
import { limitMb, toastSendOutcome } from './feedback';
import { displayStartMs, formatSize, parseCallFileName, type ParsedCallName } from './fileName';
import { askAudioPermission, audioPermissionLabel, enableAutoSend, enableCallDetection } from './permission';
import { callClientId, callKey, isStillWriting, QUIET_MS, sendCallRecording } from './send';
import { useCallRecordings } from './useCallRecordings';

interface Entry {
  rec: CallRecording;
  key: string;
  clientId: string;
  mark: SentMark | null;
  parsed: ParsedCallName;
  /** Ko'rsatiladigan boshlanish vaqti (nomdagi vaqt yoki fayl vaqti - davomiylik). */
  startMs: number | null;
}

interface CallSection {
  /** `YYYY-MM-DD` (Toshkent) yoki 'unknown'. */
  key: string;
  data: Entry[];
}

type ItemStatus = 'ready' | 'recording' | 'sending' | 'queue' | 'sent' | 'unsupported' | 'too_large';

/** Sozlamadagi Samsung yo'riqnomasi ochiq holda (ikkinchi bosish kerak bo'lmasin). */
export const CALLS_HOWTO_HREF = '/settings/calls?howto=1';

export function CallsPanel({ bottomInset = 0, onFind }: { bottomInset?: number; onFind?: (query: string) => void }) {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const services = useServices();
  const online = useOnline();
  const enabled = useCalls((s) => s.enabled);
  const autoSend = useCalls((s) => s.autoSend);
  const sent = useCalls((s) => s.sent);
  const storedOwner = useCalls((s) => s.owner);
  const actorId = useAuth((s) => s.user?.actorId ?? null);
  const maxBytes = useAuth((s) => s.config?.maxUploadBytes || null);
  // Ildiz layout'ga `<CallAutoSend />` qo'yilmaguncha ham bo'lim ochiq turganda ishlasin (single-flight).
  useCallAutoSend();
  const list = useCallRecordings(enabled);
  const { items, readAt, refresh } = list;
  const rows = useQueueRows();
  const [busy, setBusy] = useState<ReadonlySet<string>>(() => new Set());
  // Ikki marta tez bosish: holat hali qayta chizilmagan bo'lsa ham ikkinchi nusxa olinmasin.
  const inFlight = useRef(new Set<string>());
  const [pulling, setPulling] = useState(false);

  const owner = actorId != null ? String(actorId) : storedOwner;
  const rowsById = useMemo(() => new Map(rows.map((r) => [r.clientId, r])), [rows]);
  const entries = useMemo<Entry[]>(
    () =>
      items.map((rec) => {
        const key = callKey(rec);
        const mark = sent[key] ?? null;
        const parsed = parseCallFileName(rec.displayName);
        return {
          rec,
          key,
          clientId: mark?.c ?? callClientId(owner, key),
          mark,
          parsed,
          startMs: displayStartMs(parsed, rec.dateMs || null, rec.durationMs),
        };
      }),
    [items, sent, owner],
  );
  const sections = useMemo<CallSection[]>(() => {
    const out: CallSection[] = [];
    const sorted = [...entries].sort((a, b) => (b.startMs ?? 0) - (a.startMs ?? 0));
    for (const e of sorted) {
      const key = (e.startMs != null && tashkentDayKey(e.startMs)) || 'unknown';
      const last = out[out.length - 1];
      if (last && last.key === key) last.data.push(e);
      else out.push({ key, data: [e] });
    }
    return out;
  }, [entries]);

  // Yuborilgan qo'ng'iroqning server id'si navbat qatorida paydo bo'lganda eslab qolinadi:
  // qator bir necha kundan keyin tozalanadi, "Yuborildi" kartasi esa baribir xulosaga ochilsin.
  useEffect(() => {
    const ids = new Map<string, string>();
    for (const r of rows) if (r.source === 'call' && r.serverId) ids.set(r.clientId, r.serverId);
    if (ids.size) useCalls.getState().linkServerIds(ids);
  }, [rows]);

  // "Yozilmoqda" yozuvi tinchigach ro'yxat o'zi yangilansin - foydalanuvchi ekranga tikilib turgan bo'lsa ham.
  useEffect(() => {
    const writing = items.filter((r) => isStillWriting(r, readAt));
    if (!writing.length) return;
    const wait = Math.min(...writing.map((r) => QUIET_MS - (readAt - r.dateMs)));
    const timer = setTimeout(() => void refresh(), Math.min(Math.max(wait, 1_000), QUIET_MS) + 1_000);
    return () => clearTimeout(timer);
  }, [items, readAt, refresh]);

  const send = useCallback(
    async (e: Entry) => {
      if (inFlight.current.has(e.key)) return;
      inFlight.current.add(e.key);
      setBusy((b) => new Set(b).add(e.key));
      try {
        toastSendOutcome(t, await sendCallRecording(callSendDeps(services), e.rec, currentSendOptions(t)));
      } finally {
        inFlight.current.delete(e.key);
        setBusy((b) => {
          const next = new Set(b);
          next.delete(e.key);
          return next;
        });
      }
    },
    [services, t],
  );

  const open = useCallback(
    (e: Entry, row: QueueRow | null) => {
      if (row) router.push(localHref(row));
      else if (e.mark?.s) router.push(`/meeting/${e.mark.s}`);
      // Server id'si noma'lum (qator tozalangan, bo'lim o'shanda ochilmagan) - Yozuvlarda suhbatdosh bo'yicha qidiruv.
      else onFind?.(e.parsed.counterpart ?? t('calls.unknown'));
    },
    [onFind, t],
  );

  const onRefresh = async () => {
    setPulling(true);
    try {
      await refresh();
      await kickCallAutoSend(services);
    } finally {
      setPulling(false);
    }
  };

  const statusOf = (e: Entry): ItemStatus => {
    if (busy.has(e.key)) return 'sending';
    if (rowsById.has(e.clientId)) return 'queue';
    if (e.mark) return 'sent';
    if (!e.rec.contentType) return 'unsupported';
    if (maxBytes && e.rec.sizeBytes > maxBytes) return 'too_large';
    if (isStillWriting(e.rec, readAt)) return 'recording';
    return 'ready';
  };

  const setAuto = (v: boolean) => {
    // Yoqish - har safar ogohlantirish bilan (shaxsiy qo'ng'iroqlar ham ketadi); faqat SHU paytdan keyingilari.
    if (v) void enableAutoSend(t);
    else useCalls.getState().set({ autoSend: false });
  };

  const renderEmpty = () => {
    if (!enabled) {
      return (
        <EmptyState
          testID="calls-intro"
          icon={PhoneCall}
          title={t('calls.introTitle')}
          body={t('calls.introBody')}
          action={{ title: t('calls.enable'), testID: 'calls-enable', onPress: () => void enableCallDetection(t).then(() => refresh()) }}
          secondary={{ title: t('calls.howTo'), testID: 'calls-howto', onPress: () => router.push(CALLS_HOWTO_HREF) }}
        />
      );
    }
    if (!list.permitted) {
      return (
        <EmptyState
          testID="calls-permission"
          icon={LockKeyhole}
          tone="warn"
          title={t('calls.permTitle')}
          body={t('calls.permBody', { perm: audioPermissionLabel(t) })}
          action={{ title: t('calls.permGrant'), testID: 'calls-grant', onPress: () => void askAudioPermission(t).then(() => refresh()) }}
        />
      );
    }
    if (!list.loaded) {
      return (
        <View style={s.loading}>
          <ActivityIndicator color={th.textMuted} />
        </View>
      );
    }
    return (
      <EmptyState
        testID="calls-empty"
        icon={PhoneOff}
        title={t('calls.emptyTitle')}
        body={t('calls.emptyBody')}
        secondary={{ title: t('calls.howTo'), testID: 'calls-howto', onPress: () => router.push(CALLS_HOWTO_HREF) }}
      />
    );
  };

  const renderSectionHeader = ({ section }: { section: SectionListData<Entry, CallSection> }) => {
    if (section.key === 'unknown') return null;
    const d = dayLabel(section.key, readAt, lang);
    const title = d.kind === 'today' ? t('history.today') : d.kind === 'yesterday' ? t('history.yesterday') : d.text;
    return (
      <Text accessibilityRole="header" style={[typeScale.label, s.day, { color: th.textMuted }]}>
        {title}
      </Text>
    );
  };

  const showList = enabled && list.permitted && entries.length > 0;
  const header = showList ? (
    <ListGroup>
      <ListRow
        testID="calls-auto"
        icon={Send}
        title={t('calls.autoSend')}
        subtitle={autoSend ? t('calls.autoOn') : t('calls.autoOff')}
        right={{ kind: 'switch', value: autoSend, onChange: setAuto, testID: 'calls-auto-toggle' }}
      />
    </ListGroup>
  ) : null;

  return (
    <SectionList<Entry, CallSection>
      testID="calls-list"
      sections={showList ? sections : []}
      keyExtractor={(e) => e.key}
      stickySectionHeadersEnabled={false}
      contentContainerStyle={[s.content, { paddingBottom: 32 + bottomInset }]}
      refreshControl={enabled ? <RefreshControl refreshing={pulling} onRefresh={() => void onRefresh()} /> : undefined}
      ListHeaderComponent={header}
      ListEmptyComponent={renderEmpty()}
      ItemSeparatorComponent={Separator}
      renderSectionHeader={renderSectionHeader}
      renderItem={({ item }) => (
        <CallCard
          entry={item}
          status={statusOf(item)}
          row={rowsById.get(item.clientId) ?? null}
          online={online}
          lang={lang}
          maxBytes={maxBytes}
          onSend={send}
          onOpen={open}
        />
      )}
    />
  );
}

function Separator() {
  return <View style={s.sep} />;
}

const CallCard = memo(function CallCard({
  entry,
  status,
  row,
  online,
  lang,
  maxBytes,
  onSend,
  onOpen,
}: {
  entry: Entry;
  status: ItemStatus;
  row: QueueRow | null;
  online: boolean | null;
  lang: Lang;
  maxBytes: number | null;
  onSend: (e: Entry) => void;
  onOpen: (e: Entry, row: QueueRow | null) => void;
}) {
  const t = useT();
  const th = useTheme();
  const { rec, parsed, startMs } = entry;
  const title = parsed.counterpart ?? t('calls.unknown');
  // Kun bo'lim sarlavhasida - kartada faqat soat (Yozuvlar vaqt chizig'i bilan bir xil).
  const meta = [
    startMs != null ? formatTime(startMs) : '',
    formatDuration(rec.durationMs > 0 ? rec.durationMs / 1000 : null),
    formatSize(rec.sizeBytes, t, lang),
  ]
    .filter(Boolean)
    .join(' · ');
  const id = rec.displayName;

  let right: ReactNode = null;
  let pill: { label: string; tone: PillTone } | null = null;
  if (status === 'ready') {
    right = (
      <Button
        small
        pill
        variant="secondary"
        icon={Send}
        testID={`call-send-${id}`}
        accessibilityLabel={`${t('calls.send')}: ${title}`}
        title={t('calls.send')}
        onPress={() => onSend(entry)}
        style={[s.button, { backgroundColor: th.bg, borderColor: th.borderStrong }]}
      />
    );
  } else if (status === 'sending') {
    right = <ActivityIndicator testID={`call-sending-${id}`} color={th.textMuted} />;
  } else if (status === 'recording') {
    pill = { label: t('calls.recordingNow'), tone: 'info' };
  } else if (status === 'queue' && row) {
    pill = uploadPill(uploadStatus(row, { online }), t) ?? { label: t('calls.sent'), tone: 'good' };
  } else if (status === 'sent' || status === 'queue') {
    pill = { label: t('calls.sent'), tone: 'good' };
  } else if (status === 'unsupported') {
    pill = { label: t('calls.unsupported'), tone: 'warn' };
  } else if (status === 'too_large') {
    pill = { label: t('calls.tooLarge', { mb: maxBytes ? limitMb(maxBytes) : '' }), tone: 'warn' };
  }
  if (pill) right = <StatusPill testID={`call-status-${id}`} label={pill.label} tone={pill.tone} />;

  // Navbatdagi yoki yuborilgan qo'ng'iroq bosiladi: yozuv sahifasi / xulosa / Yozuvlar qidiruvi.
  const openable = status === 'queue' || status === 'sent';
  const body = (
    <>
      <IconTile icon={Phone} tone="raised" />
      <View style={s.body}>
        <Text numberOfLines={1} style={[typeScale.rowTitle, { color: th.text }]}>
          {title}
        </Text>
        <Text numberOfLines={1} style={[typeScale.caption, s.meta, { color: th.textMuted }]}>
          {meta}
        </Text>
      </View>
      {right}
      {openable ? <ChevronRight size={20} color={th.textFaint} /> : null}
    </>
  );
  if (openable) {
    return (
      <Pressable
        testID={`call-${id}`}
        accessibilityRole="button"
        accessibilityLabel={[title, meta, pill?.label].filter(Boolean).join(', ')}
        onPress={() => onOpen(entry, row)}
        android_ripple={{ color: th.border }}
        style={({ pressed }) => [s.card, { backgroundColor: pressed ? th.border : th.surfaceAlt }]}>
        {body}
      </Pressable>
    );
  }
  return (
    <View testID={`call-${id}`} style={[s.card, { backgroundColor: th.surfaceAlt }]}>
      {body}
    </View>
  );
});

const s = StyleSheet.create({
  content: { paddingHorizontal: 16, paddingTop: 8, flexGrow: 1 },
  loading: { paddingVertical: 48, alignItems: 'center' },
  day: { paddingTop: 16, paddingBottom: 8, paddingHorizontal: 4 },
  sep: { height: 8 },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: radius.lg, padding: 14 },
  body: { flex: 1, minWidth: 0 },
  meta: { marginTop: 2, fontVariant: ['tabular-nums'] },
  button: { borderWidth: StyleSheet.hairlineWidth },
});
