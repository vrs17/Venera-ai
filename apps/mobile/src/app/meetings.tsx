/**
 * Plaud bo'limi - yozuvlar ro'yxati (spec 3.1, Plaud uslubi; 2026-11-06 dan bo'lim nomi ham
 * "Plaud" - Slack/Telegram'dagi «🎙 Plaud» bilan bir xil, marshrut `/meetings` o'zgarmagan):
 * bitta vaqt chizig'i - serverdagi yig'ilishlar va telefonda turgan (hali yuklanmagan) yozuvlar birga, kunlar
 * bo'yicha ("Bugun", "Kecha", "8-oktabr"). Har karta: belgi, nom, davomiylik,
 * soat va holat (yuklash sababi bilan: "Internet yo'q", "Yuklanmoqda 42%").
 *
 * Yozish - bosh amal: pastda katta qizil tugma; bo'sh holat esa yozishni o'rgatadi.
 * Yozuv ketayotganda tepada jonli karta ("Yozilmoqda 12:34").
 *
 * "Audio yuklash" (sarlavhada va bo'sh holatda): telefondagi audio fayl(lar) tizim oynasidan
 * tanlanadi va "Ulashish -> Barno AI" bilan bir yo'ldan o'tadi - `/import` tasdiq ekrani
 * (`features/calls/useAudioUpload`). Faqat native import bor ilovada (tasdiq ekrani shunga tayanadi).
 *
 * Saqlangan xatti-harakat: sessiya tugadi banneri, 403/404 -> "bo'lim yoqilmagan",
 * pastga tortib yangilash, sahifalab yuklash, ishlov yoki lokal yozuv bo'lsa 15 s da
 * avtomatik yangilash.
 *
 * "Yozuvlar | Qo'ng'iroqlar" almashtirgichi olib tashlangan (ega qarori 2026-11-12): Plaud ochilishi bilan
 * yozuvlar ro'yxati, "Qo'ng'iroqlar" bo'limi (`features/calls/CallsPanel`) hozirgi bosqichda kerak emas.
 * Avtomatik yuborilgan qo'ng'iroq (Sozlamalar -> "Qo'ng'iroq yozuvlari") oddiy navbat qatori - ro'yxatda ko'rinadi.
 *
 * Manba filtri va tartib (2026-11-11, ega talabi): qidiruv ostida chiplar - ilovada yozilgan, yuklangan
 * fayl, Slack, Telegram bot, Mini App, web (`OriginFilter`); server filtrlaydi (`?origin=`, sahifalash
 * to'g'ri qolsin). Tartib `?sort=listed`: bugun yuklangan eski fayl "Bugun" ostida, eng tepada
 * (`timeline.ts` - qaysi vaqt).
 */
import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query';
import { router, Stack, useFocusEffect } from 'expo-router';
import { ChevronRight, CircleAlert, CircleDot, CloudOff, ListChecks, ListFilter, Mic, RotateCcw, Search, Upload, X } from 'lucide-react-native';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  TextInput,
  View,
  type SectionListData,
} from 'react-native';

import { ApiError } from '@/api/client';
import type { MeetingOrigin } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { useAudioUpload } from '@/features/calls/useAudioUpload';
import { OriginFilter } from '@/features/meeting/OriginFilter';
import { isProcessing, qk } from '@/features/meeting/queries';
import { localTitle, RecordingCard } from '@/features/meeting/RecordingCard';
import { dayLabel, groupByDay, matchesQuery, mergeTimeline, type TimelineItem, type TimelineSection } from '@/features/meeting/timeline';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { useRecordingClock } from '@/features/recorder/useRecordingClock';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useOnline } from '@/features/upload/uploadStatus';
import { pendingRows, useQueueRows } from '@/features/upload/useQueue';
import { useServices } from '@/services';
import { Banner } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { errorText } from '@/ui/errors';
import { IconButton } from '@/ui/IconButton';
import { IconTile } from '@/ui/IconTile';
import { useSafeInsets } from '@/ui/insets';
import { useTheme } from '@/ui/theme';
import { hit, iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

const PAGE = 20;
/** Qidiruv serverga shuncha jimlikdan keyin ketadi (har harfga so'rov va spinner bo'lmasin). */
const SEARCH_DEBOUNCE_MS = 300;

/** Qiymat `ms` davomida o'zgarmay tursa qaytadi (qidiruv maydoni uchun). */
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const h = setTimeout(() => setV(value), ms);
    return () => clearTimeout(h);
  }, [value, ms]);
  return v;
}

export default function MeetingsScreen() {
  const t = useT();
  const th = useTheme();
  const lang = useSettings((s) => s.uiLang);
  const insets = useSafeInsets();
  const services = useServices();
  const expired = useAuth((s) => s.expired);
  // Faqat holat (soat EMAS): soat har soniya yangilanadi - butun ro'yxat qayta chizilmasin,
  // u jonli kartaning o'zida (`LiveCard`).
  const recStatus = useRecorderStore((s) => s.machine.status);
  const live = recStatus === 'recording' || recStatus === 'paused';
  const liveClientId = useRecorderStore((s) => s.machine.clientId);
  const online = useOnline();
  const [q, setQ] = useState('');
  // Manba filtri: `null` - hammasi.
  const [origin, setOrigin] = useState<MeetingOrigin | null>(null);
  const [focused, setFocused] = useState(true);
  const [pulling, setPulling] = useState(false);
  // "Bugun/Kecha" uchun soat: ekranga qaytganda va tortib yangilaganda yangilanadi.
  const [now, setNow] = useState(() => Date.now());
  const rows = useQueueRows();
  const pending = pendingRows(rows);
  const upload = useAudioUpload();

  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      setNow(Date.now());
      return () => setFocused(false);
    }, []),
  );

  const query = q.trim();
  const serverQ = useDebounced(query, SEARCH_DEBOUNCE_MS);

  const list = useInfiniteQuery({
    queryKey: qk.list(serverQ, origin),
    initialPageParam: 0,
    // `sort: 'listed'` - server ham `timeline` dagi vaqt bilan tartiblaydi (sahifalar orasida sakrash bo'lmasin).
    queryFn: ({ pageParam }) => services.meetings.list({ limit: PAGE, offset: pageParam, q: serverQ, origin, sort: 'listed' }),
    // Yozayotganda ro'yxat spinner'ga aylanib "sakramasin" - yangi natija kelguncha eskisi turadi.
    placeholderData: keepPreviousData,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
    refetchInterval: (query) => {
      const anyProcessing = query.state.data?.pages.some((p) => p.items.some((m) => isProcessing(m)));
      return focused && (anyProcessing || pending.length > 0) ? 15_000 : false;
    },
  });

  const cards = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const items = useMemo(() => {
    // Hozir yozilayotgan yozuv tepadagi jonli kartada - ro'yxatda takrorlanmaydi.
    const merged = mergeTimeline(cards, rows, { hideClientId: live ? liveClientId : null, origin });
    // Server `q` bilan o'zi qidiradi; telefondagi yozuvlarni nomi bo'yicha shu yerda.
    return query ? merged.filter((it) => it.kind === 'server' || matchesQuery(localTitle(it.row, t), query)) : merged;
  }, [cards, rows, live, liveClientId, origin, query, t]);
  const sections = useMemo(() => groupByDay(items), [items]);

  // Ro'yxat yuklanmadi: "Hali yozuv yo'q" deyish yolg'on bo'lardi (yozuvlar bor, faqat kelmadi).
  const listFailed = list.isError && !list.data;
  // 403/404: bo'lim bu odamga yoqilmagan - yozishga undamaymiz (yuklash baribir "Yoqilmagan" bo'ladi).
  const featureOff = listFailed && list.error instanceof ApiError && (list.error.status === 403 || list.error.status === 404);
  // Filtr tanlangan va bo'sh - bu "hali yozuv yo'q" EMAS (boshqa manbada bor): katta bo'sh holat o'rniga izoh.
  const filtered = origin !== null;
  const nothing = items.length === 0 && !query && !filtered && !live;
  const empty = !list.isLoading && !listFailed && nothing;
  const failedEmpty = listFailed && nothing;
  const showSearch = q !== '' || filtered || items.length > 0 || list.isLoading;
  const fabHidden = live || empty || featureOff;
  // Yuklash yozuv ketayotganda ham mumkin (mikrofon kerak emas); bo'lim yoqilmagan bo'lsa - yo'q (FAB kabi).
  const uploadOn = upload.supported && !featureOff;

  const onRefresh = async () => {
    setPulling(true);
    setNow(Date.now());
    // Tortib yangilash yuklashni ham turtadi (backoff muddati baribir hurmat qilinadi).
    void services.uploader.runOnce().catch(() => {});
    try {
      await list.refetch();
    } finally {
      setPulling(false);
    }
  };

  const header = (
    <View style={s.header}>
      {expired ? (
        <Banner tone="warn" text={t('list.sessionExpired')} action={{ title: t('login.submit'), onPress: () => useAuth.getState().setSignedOut(true) }} />
      ) : null}
      {/* Telefondagi yozuvlar ko'rinib turibdi - xato kichik banner; hech narsa yo'q bo'lsa pastda katta holat. */}
      {listFailed && !failedEmpty ? (
        <Banner
          tone="bad"
          testID="meetings-error"
          text={
            // Mini App orqali kirgan, lekin bo'lim unga hali yoqilmagan odam (403/404).
            featureOff ? t('login.featureDisabled') : errorText(t, list.error)
          }
          action={{ title: t('common.retry'), onPress: () => void list.refetch() }}
        />
      ) : null}
      {showSearch ? (
        <View style={[s.search, { backgroundColor: th.surfaceAlt }]}>
          <Search size={iconSize.md - 2} color={th.textMuted} strokeWidth={stroke.regular} />
          <TextInput
            testID="meetings-search"
            value={q}
            onChangeText={setQ}
            placeholder={t('list.search')}
            placeholderTextColor={th.textMuted}
            accessibilityLabel={t('list.search')}
            returnKeyType="search"
            style={[typeScale.body, s.searchInput, { color: th.text }]}
          />
          {q ? (
            <Pressable testID="meetings-search-clear" accessibilityRole="button" accessibilityLabel={t('common.close')} onPress={() => setQ('')} hitSlop={8} style={s.clear}>
              <X size={iconSize.sm} color={th.textMuted} strokeWidth={stroke.small} />
            </Pressable>
          ) : null}
        </View>
      ) : null}
      {showSearch ? <OriginFilter value={origin} onChange={setOrigin} /> : null}
      {live ? <LiveCard /> : null}
    </View>
  );

  // Barqaror funksiyalar: kartalar (memo) qayta chizilmasin - faqat ma'lumot o'zgarganda.
  const renderItem = useCallback(
    ({ item }: { item: TimelineItem }) => <RecordingCard item={item} lang={lang} online={online} />,
    [lang, online],
  );
  const renderSectionHeader = useCallback(
    ({ section }: { section: SectionListData<TimelineItem, TimelineSection> }) => {
      const d = dayLabel(section.key, now, lang);
      const title = d.kind === 'today' ? t('history.today') : d.kind === 'yesterday' ? t('history.yesterday') : d.text;
      return (
        <Text accessibilityRole="header" style={[typeScale.label, s.day, { color: th.textMuted }]}>
          {title}
        </Text>
      );
    },
    [now, lang, t, th.textMuted],
  );

  const renderEmpty = () => {
    if (list.isLoading) {
      return (
        <View style={s.loading}>
          <ActivityIndicator color={th.textMuted} />
        </View>
      );
    }
    if (failedEmpty) {
      return featureOff ? (
        <EmptyState testID="meetings-error" icon={CircleAlert} tone="warn" title={t('login.featureDisabled')} body={t('recs.disabledHint')} />
      ) : (
        <EmptyState
          testID="meetings-error"
          icon={CloudOff}
          tone="warn"
          title={t('recs.listFailed')}
          body={errorText(t, list.error)}
          action={{ title: t('common.retry'), icon: RotateCcw, variant: 'secondary', testID: 'meetings-retry', onPress: () => void list.refetch() }}
        />
      );
    }
    if (empty) {
      return (
        <EmptyState
          testID="meetings-empty"
          icon={Mic}
          tone="record"
          title={t('recs.emptyTitle')}
          body={t('recs.emptyBody')}
          action={{ title: t('list.record'), icon: CircleDot, variant: 'record', testID: 'meetings-empty-record', onPress: () => router.push('/record?src=app') }}
          altAction={
            uploadOn
              ? { title: t('calls.pick.title'), icon: Upload, testID: 'meetings-empty-upload', loading: upload.busy, onPress: () => void upload.pick() }
              : undefined
          }
          secondary={{ title: t('recs.emptyQuick'), testID: 'meetings-empty-quick', onPress: () => router.push('/settings/quick') }}
        />
      );
    }
    if (query) return <EmptyState compact icon={Search} title={t('tr.noResults')} testID="meetings-no-results" />;
    if (filtered) {
      return (
        <EmptyState
          compact
          icon={ListFilter}
          title={t('recs.origin.empty')}
          testID="meetings-origin-empty"
          action={{ title: t('recs.origin.reset'), variant: 'secondary', testID: 'meetings-origin-reset', onPress: () => setOrigin(null) }}
        />
      );
    }
    return null;
  };

  return (
    <View style={s.root}>
      <Stack.Screen
        options={{
          headerRight: () => (
            <View style={s.headerRight}>
              {uploadOn ? (
                upload.busy ? (
                  // Katta fayl nusxalanguncha bir necha soniya - qayta bosilmasin, nima bo'layotgani ko'rinsin.
                  <View testID="meetings-upload-busy" style={s.headerBusy} accessible accessibilityLabel={t('calls.pick.preparing')}>
                    <ActivityIndicator color={th.textMuted} />
                  </View>
                ) : (
                  <IconButton testID="meetings-upload" icon={Upload} label={t('calls.pick.title')} onPress={() => void upload.pick()} />
                )
              ) : null}
              <IconButton testID="meetings-tasks" icon={ListChecks} label={t('list.myTasks')} onPress={() => router.push('/action-items')} />
            </View>
          ),
        }}
      />
      <SectionList<TimelineItem, TimelineSection>
        testID="meetings-list"
        sections={sections}
        keyExtractor={(it) => it.key}
        stickySectionHeadersEnabled={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={[s.content, { paddingBottom: (fabHidden ? 32 : 120) + insets.bottom }]}
        refreshControl={<RefreshControl refreshing={pulling} onRefresh={() => void onRefresh()} />}
        onEndReached={() => {
          if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
        }}
        ListHeaderComponent={header}
        ListEmptyComponent={renderEmpty()}
        ListFooterComponent={list.isFetchingNextPage ? <ActivityIndicator style={s.more} color={th.textMuted} /> : null}
        renderSectionHeader={renderSectionHeader}
        renderItem={renderItem}
      />
      {fabHidden ? null : (
        <Pressable
          testID="record-fab"
          accessibilityRole="button"
          accessibilityLabel={t('list.record')}
          onPress={() => router.push('/record?src=app')}
          style={({ pressed }) => [s.fab, { backgroundColor: th.record, bottom: 24 + insets.bottom, transform: [{ scale: pressed ? 0.94 : 1 }] }]}>
          {/* Nuqta `primaryText`: qorong'i mavzuda qizil och pushti - oq nuqta u yerda ko'rinmasdi. */}
          <View style={[s.fabDot, { backgroundColor: th.primaryText }]} />
        </Pressable>
      )}
    </View>
  );
}

/** Yozuv ketmoqda: bir bosishda yozuv ekraniga (to'xtatish, belgi qo'yish). Soat faqat shu yerda tiqillaydi. */
function LiveCard() {
  const t = useT();
  const th = useTheme();
  const clock = useRecordingClock();
  const text = `${clock.paused ? t('record.paused') : t('record.recording')} ${clock.label}`;
  return (
    <Pressable
      testID="meetings-live"
      accessibilityRole="button"
      accessibilityLabel={`${text}, ${t('recs.open')}`}
      onPress={() => router.push('/record?src=app')}
      style={({ pressed }) => [s.live, { backgroundColor: th.tones.bad.bg, opacity: pressed ? 0.85 : 1 }]}>
      <IconTile icon={CircleDot} tone="record" />
      <Text style={[typeScale.headline, s.liveText, { color: th.record }]} numberOfLines={1}>
        {text}
      </Text>
      <Text style={[typeScale.label, { color: th.record }]}>{t('recs.open')}</Text>
      <ChevronRight size={iconSize.sm} color={th.record} strokeWidth={stroke.small} />
    </Pressable>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  headerRight: { flexDirection: 'row', alignItems: 'center' },
  headerBusy: { width: hit.min, height: hit.min, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 16, paddingTop: 8, flexGrow: 1 },
  header: { gap: 12, paddingBottom: 4 },
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: radius.md, paddingHorizontal: 12, minHeight: hit.min },
  searchInput: { flex: 1, paddingVertical: 10 },
  clear: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center' },
  live: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: radius.lg, padding: 12, paddingRight: 14 },
  liveText: { flex: 1, fontVariant: ['tabular-nums'] },
  day: { paddingTop: 16, paddingBottom: 8, paddingHorizontal: 4 },
  loading: { paddingVertical: 48, alignItems: 'center' },
  more: { paddingVertical: 16 },
  fab: {
    position: 'absolute',
    alignSelf: 'center',
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 6,
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
  },
  fabDot: { width: 26, height: 26, borderRadius: 13 },
});
