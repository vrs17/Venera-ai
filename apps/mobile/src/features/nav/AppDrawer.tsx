/**
 * Chap panel (drawer) - Claude ilovasidagidek: tepada "Barno AI" va qidiruv, asosiy
 * bo'limlar (Yangi suhbat, Yozuvlar, Vazifalarim), so'ng suhbatlar ro'yxati, pastda
 * profil (-> Sozlamalar) va qizil "● Yozish" tugmasi.
 *
 * NIMA UCHUN navigator emas, Modal: drawer navigatori gesture-handler va reanimated
 * talab qiladi - ular loyihada yo'q (yangi native bog'liqlik qo'shmaymiz). Modal +
 * RN `Animated` (native driver) + `PanResponder` yetarli.
 *
 * NIMA UCHUN chetdan surib OCHILMAYDI: Android imo-ishora navigatsiyasida chap chetdan
 * surish = "orqaga". Ochish faqat ☰ bilan; yopish - fonni bosish, orqaga tugmasi,
 * panelni chapga surish yoki biror bo'limni tanlash.
 *
 * NIMA UCHUN pastdagi asosiy tugma "● Yozish" (Claude'da "+ New session"): yangi suhbat
 * tepa panelda ham, shu yerda birinchi qatorda ham bor; yig'ilish esa HOZIR boshlanadi -
 * eng ko'zga tashlanadigan joy yozuvga. Qizil rang ilovaning hamma joyida "yozuv" degani.
 */
import { router } from 'expo-router';
import { AudioLines, ListChecks, Search, Settings, SquarePen, X } from 'lucide-react-native';
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import {
  Animated,
  Easing,
  Modal,
  PanResponder,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';

import { useAuth } from '@/features/auth/authStore';
import { useChat } from '@/features/chat/chatStore';
import { useChats } from '@/features/chat/chatsStore';
import { meetingsVisible } from '@/features/nav/visibility';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { useRecordingClock } from '@/features/recorder/useRecordingClock';
import { useT } from '@/features/settings/settingsStore';
import { useQueueRows } from '@/features/upload/useQueue';
import { useServices } from '@/services';
import { Avatar } from '@/ui/Avatar';
import { IconButton } from '@/ui/IconButton';
import { useSafeInsets } from '@/ui/insets';
import { ListDivider, ListRow, type ListRowRight } from '@/ui/list';
import { StatusPill } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';
import { hit, iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

import { ChatList } from './ChatList';

const OPEN_MS = 220;
const CLOSE_MS = 180;

/** Panel kengligi: telefonda ekranning 85% i, planshetda ham 320 dan oshmaydi (chat ko'rinib tursin). */
export function drawerWidth(windowWidth: number): number {
  return Math.min(320, Math.round(windowWidth * 0.85));
}

/** Surishni panel oladimi: aniq chapga va gorizontal (vertikal aylantirish ro'yxatda qolsin). */
export function shouldClaimSwipe(dx: number, dy: number): boolean {
  return dx < -8 && Math.abs(dx) > Math.abs(dy);
}

/** Qo'yib yuborilganda yopiladimi: kenglikning 30% idan ko'p surildi yoki tez siltandi. */
export function shouldCloseOnRelease(dx: number, vx: number, width: number): boolean {
  return dx < -width * 0.3 || vx < -0.5;
}

/** "Ali Valiyev" -> "Ali" (drawer pastida joy kam - Claude ham faqat ismni yozadi). */
export function firstName(name: string | null | undefined): string {
  return (name ?? '').trim().split(/\s+/)[0] ?? '';
}

export function AppDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const th = useTheme();
  const t = useT();
  const insets = useSafeInsets();
  const { width: windowWidth } = useWindowDimensions();
  const width = drawerWidth(windowWidth);
  // Bitta qiymat panelni ham, fonni ham boshqaradi - barmoq bilan surganda fon ham xiralashadi.
  const [x] = useState(() => new Animated.Value(-width));
  // Yopilish animatsiyasi tugaguncha Modal ko'rinib turadi (`open` darhol false bo'ladi).
  const [shown, setShown] = useState(open);
  if (open && !shown) setShown(true);

  useEffect(() => {
    if (!shown) return;
    const anim = open
      ? Animated.timing(x, { toValue: 0, duration: OPEN_MS, easing: Easing.out(Easing.cubic), useNativeDriver: true })
      : Animated.timing(x, { toValue: -width, duration: CLOSE_MS, easing: Easing.in(Easing.cubic), useNativeDriver: true });
    anim.start(({ finished }) => {
      if (finished && !open) setShown(false);
    });
    return () => anim.stop();
  }, [open, shown, width, x]);

  const pan = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_e, g) => shouldClaimSwipe(g.dx, g.dy),
        // Surish boshlangach ro'yxat uni tortib olmasin - aks holda panel yarim yo'lda qotadi.
        onPanResponderTerminationRequest: () => false,
        onPanResponderMove: (_e, g) => x.setValue(Math.min(0, g.dx)),
        onPanResponderRelease: (_e, g) => {
          if (shouldCloseOnRelease(g.dx, g.vx, width)) onClose();
          else Animated.spring(x, { toValue: 0, bounciness: 0, useNativeDriver: true }).start();
        },
        onPanResponderTerminate: () => Animated.spring(x, { toValue: 0, bounciness: 0, useNativeDriver: true }).start(),
      }),
    [onClose, width, x],
  );

  const scrim = useMemo(() => x.interpolate({ inputRange: [-width, 0], outputRange: [0, 1], extrapolate: 'clamp' }), [width, x]);

  // Orqaga tugmasi: qidiruv ochiq bo'lsa avval qidiruvdan chiqadi (Android odati), keyin yopadi.
  const backRef = useRef<(() => boolean) | null>(null);
  const onBack = () => {
    if (backRef.current?.()) return;
    onClose();
  };

  return (
    <Modal
      visible={shown}
      transparent
      statusBarTranslucent
      navigationBarTranslucent
      animationType="none"
      onRequestClose={onBack}
      testID="drawer-modal">
      <View style={s.fill}>
        {/* Fon TalkBack uchun ko'rinmaydi: aks holda u panel oldidan birinchi o'qilardi; yopish - orqaga tugmasi. */}
        <Animated.View style={[StyleSheet.absoluteFill, s.scrim, { opacity: scrim }]}>
          <Pressable
            testID="drawer-scrim"
            style={StyleSheet.absoluteFill}
            onPress={onClose}
            accessible={false}
            accessibilityLabel={t('common.close')}
          />
        </Animated.View>
        <Animated.View
          testID="drawer"
          {...pan.panHandlers}
          style={[
            s.panel,
            { width, backgroundColor: th.bg, paddingTop: insets.top, paddingBottom: insets.bottom, transform: [{ translateX: x }] },
          ]}>
          {/* Ichki qism faqat ochiq paytda mount bo'ladi: navbat obunasi va qidiruv holati yopiq drawer'da yashamasin. */}
          {shown ? <DrawerContent onClose={onClose} backRef={backRef} /> : null}
        </Animated.View>
      </View>
    </Modal>
  );
}

function DrawerContent({ onClose, backRef }: { onClose: () => void; backRef: MutableRefObject<(() => boolean) | null> }) {
  const services = useServices();
  const th = useTheme();
  const t = useT();
  const user = useAuth((x) => x.user);
  const configured = useAuth((x) => x.config !== null);
  const status = useRecorderStore((x) => x.machine.status);
  const active = useRecorderStore((x) => isActive(x.machine));
  const chatId = useChat((x) => x.chatId);
  // Bitta obuna: ko'rinish qoidasi ham, "yuklanmagan" soni ham shu qatorlardan
  // (`useMeetingsVisible` + yana `useQueueRows` = navbatni ikki marta o'qish bo'lardi).
  const rows = useQueueRows();
  const meetings = meetingsVisible({ configured, live: active, localRows: rows.length });
  const live = status === 'recording' || status === 'paused';
  const pending = rows.filter((r) => r.state !== 'done').length;

  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState('');

  // Ochilganda ro'yxatni jim yangilaymiz: server nomlarni javobdan keyin yozadi, boshqa
  // qurilmada (Mini App) yangi suhbat bo'lishi mumkin. Mavjud ro'yxat ko'rinib turadi.
  useEffect(() => {
    if (!useChats.getState().loading) void useChats.getState().load(services.chat);
  }, [services]);

  /** Avval yopamiz, keyin o'tamiz: drawer yangi ekran ustida sirpanib yo'qoladi. */
  const go = (path: string) => {
    onClose();
    router.push(path);
  };

  const recordingsRight: ListRowRight = live
    ? { kind: 'node', node: <StatusPill label={t('record.recording')} tone="record" dot /> }
    : pending > 0
      ? { kind: 'node', node: <StatusPill label={String(pending)} tone="neutral" /> }
      : { kind: 'none' };
  const recordingsA11y = live
    ? `${t('nav.recordings')}, ${t('record.recording')}`
    : pending > 0
      ? `${t('nav.recordings')}, ${t('nav.pendingA11y', { n: pending })}`
      : undefined;

  const closeSearch = () => {
    setSearching(false);
    setQuery('');
  };

  useEffect(() => {
    backRef.current = () => {
      if (!searching) return false;
      setSearching(false);
      setQuery('');
      return true;
    };
    return () => {
      backRef.current = null;
    };
  }, [backRef, searching]);

  return (
    <View style={s.content}>
      {searching ? (
        <View style={s.head}>
          <View style={[s.searchBox, { backgroundColor: th.surfaceAlt }]}>
            <Search size={iconSize.sm} color={th.textMuted} strokeWidth={stroke.small} />
            <TextInput
              testID="drawer-search-input"
              value={query}
              onChangeText={setQuery}
              placeholder={t('nav.search')}
              placeholderTextColor={th.textMuted}
              accessibilityLabel={t('nav.search')}
              autoFocus
              autoCorrect={false}
              returnKeyType="search"
              style={[typeScale.body, s.searchInput, { color: th.text }]}
            />
          </View>
          <IconButton icon={X} label={t('nav.searchClose')} onPress={closeSearch} testID="drawer-search-close" />
        </View>
      ) : (
        <View style={s.head}>
          <Text style={[typeScale.display, s.brand, { color: th.text }]} numberOfLines={1} accessibilityRole="header">
            {t('app.name')}
          </Text>
          <IconButton icon={Search} label={t('nav.search')} onPress={() => setSearching(true)} testID="drawer-search" />
        </View>
      )}

      {/* Qidiruvda asosiy bo'limlar yashiriladi: klaviatura ochiq - natijalarga joy qolsin. */}
      {searching ? null : (
        <>
          <View style={s.nav}>
            <ListRow
              variant="plain"
              testID="drawer-new"
              icon={SquarePen}
              title={t('chat.newChat')}
              right={{ kind: 'none' }}
              onPress={() => {
                useChat.getState().newChat();
                onClose();
              }}
            />
            {meetings ? (
              <ListRow
                variant="plain"
                testID="drawer-recordings"
                icon={AudioLines}
                iconColor={live ? th.record : undefined}
                title={t('nav.recordings')}
                right={recordingsRight}
                accessibilityLabel={recordingsA11y}
                onPress={() => go('/meetings')}
              />
            ) : null}
            {configured ? (
              <ListRow
                variant="plain"
                testID="drawer-tasks"
                icon={ListChecks}
                title={t('list.myTasks')}
                right={{ kind: 'none' }}
                onPress={() => go('/action-items')}
              />
            ) : null}
          </View>
          <ListDivider style={s.divider} />
          <Text style={[typeScale.label, s.section, { color: th.textMuted }]} accessibilityRole="header">
            {t('chat.history')}
          </Text>
        </>
      )}

      <ChatList
        api={services.chat}
        query={searching ? query : ''}
        activeId={chatId}
        onOpen={(id) => {
          void useChat.getState().openHistory(id);
          onClose();
        }}
      />

      <ListDivider style={[s.divider, s.dividerTight]} />
      <View style={s.footer}>
        <Pressable
          testID="drawer-settings"
          onPress={() => go('/settings')}
          accessibilityRole="button"
          accessibilityLabel={t('nav.profileA11y')}
          android_ripple={{ color: th.border }}
          style={({ pressed }) => [s.me, { backgroundColor: pressed ? th.surfaceAlt : 'transparent' }]}>
          <Avatar name={user?.fullName ?? user?.email} size={36} />
          {/* Ikkinchi qator "Sozlamalar": avatar va ismni bosish sozlamalarga olib borishi taxmin qilinmaydi. */}
          <View style={s.meText}>
            <Text style={[typeScale.rowTitle, { color: th.text }]} numberOfLines={1}>
              {firstName(user?.fullName) || user?.email || ''}
            </Text>
            <View style={s.meSub}>
              <Settings size={iconSize.xs} color={th.textMuted} strokeWidth={stroke.small} />
              <Text style={[typeScale.caption, { color: th.textMuted }]} numberOfLines={1}>
                {t('settings.title')}
              </Text>
            </View>
          </View>
        </Pressable>
        {meetings ? <RecordPill onPress={() => go('/record?src=app')} /> : null}
      </View>
    </View>
  );
}

/**
 * Qizil "● Yozish" / "● Yozilmoqda 12:34" / "Pauzada 12:34". Alohida komponent - soat
 * har soniya yangilanadi, butun drawer (suhbatlar ro'yxati) qayta chizilmasin.
 *
 * Matn rangi `primaryText` (yozuv Button'i bilan bir xil): yorug' mavzuda oq; qorong'ida
 * qizil och pushti bo'ladi - u yerda oq matn o'qilmaydi, to'q matn o'qiladi.
 */
function RecordPill({ onPress }: { onPress: () => void }) {
  const th = useTheme();
  const t = useT();
  const clock = useRecordingClock();
  const label = !clock.live
    ? t('nav.record')
    : t(clock.paused ? 'nav.pausedLive' : 'nav.recordingLive', { time: clock.label });
  return (
    <Pressable
      testID="drawer-record"
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={4}
      style={({ pressed }) => [s.pill, { backgroundColor: th.record, opacity: pressed ? 0.85 : 1 }]}>
      {clock.paused ? null : <View style={[s.pillDot, { backgroundColor: th.primaryText }]} />}
      <Text style={[s.pillText, { color: th.primaryText }]} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1 },
  scrim: { backgroundColor: 'rgba(0,0,0,0.45)' },
  panel: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    elevation: 16,
    shadowColor: '#000',
    shadowOpacity: 0.2,
    shadowRadius: 16,
    shadowOffset: { width: 4, height: 0 },
  },
  content: { flex: 1 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 64, paddingLeft: 20, paddingRight: 8 },
  brand: { flex: 1 },
  searchBox: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: hit.min,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    marginLeft: -8,
  },
  searchInput: { flex: 1, paddingVertical: 0 },
  nav: { paddingHorizontal: 8, gap: 2 },
  divider: { marginHorizontal: 20 },
  dividerTight: { marginVertical: 0 },
  section: { paddingHorizontal: 20, paddingTop: 4, paddingBottom: 2 },
  footer: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 8, paddingVertical: 10 },
  me: {
    flex: 1,
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: hit.min,
    paddingHorizontal: 8,
    borderRadius: radius.md,
    overflow: 'hidden',
  },
  meText: { flex: 1, minWidth: 0 },
  meSub: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: hit.min,
    paddingHorizontal: 16,
    borderRadius: radius.pill,
    maxWidth: '62%',
  },
  pillDot: { width: 8, height: 8, borderRadius: 4 },
  pillText: { fontSize: 15, fontWeight: '600', fontVariant: ['tabular-nums'] },
});
