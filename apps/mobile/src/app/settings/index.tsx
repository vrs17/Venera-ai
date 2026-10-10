/**
 * Sozlamalar hub'i (Claude uslubi): tepada profil kartasi, keyin guruhlangan qatorlar.
 * Har qator = belgi + nom + bitta xira QIYMAT qatori ("HRM, CRM ulangan", "Tizim") va
 * o'z sahifasiga olib boradi. Hub'da tushuntirish paragrafi yo'q.
 *
 * NIMA UCHUN: egasi "hamma joyda matn, hammasi bir joyda, belgi yo'q" dedi - endi har
 * bo'lim alohida sahifa (`/settings/*`), hub esa faqat holatni bir qarashda ko'rsatadi.
 * Yozuvlar va "Vazifalarim" bu yerdan ketdi - ular drawer'da (Sozlamalarda faqat sozlama).
 *
 * Chiqish mantig'i (navbat, fayllar, recordings papkasi tozalanadi; yozuv ketayotganda
 * bloklanadi) eski bir sahifali Sozlamalardan o'zgarishsiz ko'chirilgan.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { Directory } from 'expo-file-system';
import { router, useFocusEffect } from 'expo-router';
import { ChevronRight, Info, Languages, LogOut, Mic, Plug, SunMoon, Zap } from 'lucide-react-native';
import { useCallback } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { ConnectorStatus } from '@/api/chat';
import type { AuthUser } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import type { Tone } from '@/features/meeting/summaryModel';
import { useMeetingsVisible } from '@/features/nav/visibility';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { LANG_ENDONYM } from '@/features/settings/langNames';
import { quickMethodCount, useQuickState } from '@/features/settings/quickMethods';
import { useSettings, useT, type ThemePref } from '@/features/settings/settingsStore';
import { isPending } from '@/features/upload/uploader';
import { useQueueRows } from '@/features/upload/useQueue';
import type { TFn, TKey } from '@/i18n';
import { recordingsDir } from '@/lib/paths';
import { useServices } from '@/services';
import { Avatar } from '@/ui/Avatar';
import { useSafeInsets } from '@/ui/insets';
import { ListGroup, ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';
import { iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

const THEME_KEYS: Record<ThemePref, TKey> = {
  system: 'settings.themeSystem',
  light: 'settings.themeLight',
  dark: 'settings.themeDark',
};

export default function SettingsScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const services = useServices();
  const user = useAuth((s) => s.user);
  const uiLang = useSettings((s) => s.uiLang);
  const themePref = useSettings((s) => s.themePref);
  const keepDays = useSettings((s) => s.keepDays);
  const rows = useQueueRows();
  const meetingsVisible = useMeetingsVisible();
  // Yozuv ketayotganda chiqish yozilayotgan faylni o'chirib yuborardi (yozuv jim yo'qoladi).
  const recording = useRecorderStore((s) => isActive(s.machine));
  const connectors = useQuery({ queryKey: ['connectors'], queryFn: () => services.chat.connectors(), staleTime: 30_000 });

  // "Tez yozish" sahifasida belgi yoqilgan yoki Android sozlamasidan qaytilgan bo'lishi
  // mumkin - hub'ga qaytganda son yangilansin.
  const quick = useQuickState();
  const { refresh: refreshQuick } = quick;
  useFocusEffect(useCallback(() => refreshQuick(), [refreshQuick]));

  // Navbat qiymati: yuklanishi kerak bo'lgan (kutayotgan yoki xato bilan to'xtagan) yozuvlar.
  const queued = rows.filter((r) => isPending(r) || r.state === 'failed').length;
  // Chiqish ogohlantirishi eski hisobda qoladi: ketayotgan yozuv ham yo'qoladi.
  const pending = rows.filter((r) => isPending(r) || r.state === 'recording' || r.state === 'failed');

  const doLogout = async () => {
    if (isActive(useRecorderStore.getState().machine)) return;
    await services.session.logout(async () => {
      // Spec 4.3: chiqishda yozuvlar, navbat va tokenlar tozalanadi.
      for (const r of await services.queue.list()) await services.files.remove(r.fileUri);
      await services.queue.clear();
      try {
        const dir: Directory = recordingsDir();
        if (dir.exists) dir.delete();
      } catch {
        /* papka yo'q */
      }
    });
    useAuth.getState().setSignedOut(false);
  };

  const confirmLogout = () =>
    Alert.alert(
      t('settings.logout'),
      pending.length ? t('settings.logoutConfirm', { n: pending.length }) : t('settings.logoutConfirmNone'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        { text: t('settings.logout'), style: 'destructive', onPress: () => void doLogout() },
      ],
    );

  const conn = connectionsSubtitle(t, connectors);
  const recordingValue =
    (keepDays === 7 ? t('set.keep7Short') : t('set.keepDeleteShort')) + (queued > 0 ? ` · ${t('set.queueShort', { n: queued })}` : '');

  return (
    <ScrollView
      style={{ backgroundColor: th.bg }}
      contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom }}
      testID="settings-hub">
      <ProfileCard user={user} t={t} />

      <ListGroup>
        <ListRow
          testID="settings-connections"
          icon={Plug}
          title={t('settings.connections')}
          subtitle={conn.text}
          subtitleTone={conn.tone}
          onPress={() => router.push('/settings/connections')}
        />
        <ListRow
          testID="settings-quick"
          icon={Zap}
          title={t('settings.quick')}
          subtitle={quickValue(t, quickMethodCount(quick))}
          onPress={() => router.push('/settings/quick')}
        />
        {meetingsVisible ? (
          <ListRow
            testID="settings-recording"
            icon={Mic}
            title={t('set.recording')}
            subtitle={recordingValue}
            onPress={() => router.push('/settings/recording')}
          />
        ) : null}
      </ListGroup>

      <ListGroup>
        <ListRow
          testID="settings-language"
          icon={Languages}
          title={t('set.language')}
          subtitle={LANG_ENDONYM[uiLang]}
          onPress={() => router.push('/settings/language')}
        />
        <ListRow
          testID="settings-theme"
          icon={SunMoon}
          title={t('settings.theme')}
          subtitle={t(THEME_KEYS[themePref])}
          onPress={() => router.push('/settings/theme')}
        />
      </ListGroup>

      <ListGroup>
        <ListRow
          testID="settings-about"
          icon={Info}
          title={t('settings.about')}
          subtitle={t('settings.version', { v: services.appVersion })}
          onPress={() => router.push('/settings/about')}
        />
      </ListGroup>

      <ListGroup>
        <ListRow
          testID="settings-logout"
          icon={LogOut}
          title={t('settings.logout')}
          subtitle={recording ? t('set.logoutBlockedShort') : null}
          destructive
          disabled={recording}
          onPress={confirmLogout}
        />
      </ListGroup>
    </ScrollView>
  );
}

/**
 * "Tez yozish" qiymati. Ilova yorlig'i doim bor - faqat u bo'lsa "1 ta usul yoqilgan"
 * deyish hech narsani sozlamagan odamni sozlashga undamasdi; "Faqat ilova yorlig'i" esa
 * ham rost, ham "yana usullar bor" degan ishora.
 */
function quickValue(t: TFn, n: number): string {
  return n <= 1 ? t('set.quickNone') : t('set.quickCount', { n });
}

/**
 * "Ulanishlar" qiymati. Muammo bo'lsa (muddati tugagan, uzilgan) o'sha tizim nomi
 * sariq rangda - foydalanuvchi ichkariga kirmasdan nima qilish kerakligini ko'radi.
 */
function connectionsSubtitle(
  t: TFn,
  q: UseQueryResult<{ connectors: ConnectorStatus[] }>,
): { text: string | null; tone?: Tone } {
  // Yuklanayotganda ham qator joyi band: javob kelganda qator 52 -> 64 dp ga sakramasin.
  if (!q.data) return { text: q.isError ? t('set.connLoadFailed') : '...' };
  const label = (c: ConnectorStatus) => c.label || c.id.toUpperCase();
  const configured = q.data.connectors.filter((c) => c.configured);
  const bad = configured.filter((c) => c.state !== 'connected');
  if (bad.length) return { text: t('set.connIssue', { names: bad.map(label).join(', ') }), tone: 'warn' };
  if (configured.length) return { text: t('set.connOk', { names: configured.map(label).join(', ') }) };
  return { text: t('set.connNone') };
}

/**
 * Profil kartasi: ListRow'dan kattaroq (72 dp, avatar 48, ism 17/600) - Claude'dagi
 * hisob kartasi kabi sahifaning "kimligi" bir qarashda ko'rinsin.
 */
function ProfileCard({ user, t }: { user: AuthUser | null; t: TFn }) {
  const th = useTheme();
  const name = user?.fullName || user?.email || '-';
  const sub = user?.email ? [user.position, user.email].filter(Boolean).join(' · ') : (user?.position ?? null);
  return (
    <ListGroup>
      <Pressable
        testID="settings-profile"
        accessibilityRole="button"
        accessibilityLabel={`${name}, ${t('set.profile')}`}
        onPress={() => router.push('/settings/account')}
        android_ripple={{ color: th.border }}
        style={({ pressed }) => [s.profile, { backgroundColor: pressed ? th.border : th.surfaceAlt }]}>
        <Avatar name={user?.fullName || user?.email} size={48} />
        <View style={s.profileText}>
          <Text numberOfLines={1} style={[typeScale.headline, { color: th.text }]}>
            {name}
          </Text>
          {sub ? (
            <Text numberOfLines={1} style={[typeScale.sub, { color: th.textMuted }]}>
              {sub}
            </Text>
          ) : null}
        </View>
        <ChevronRight size={iconSize.md} color={th.textFaint} strokeWidth={stroke.regular} />
      </Pressable>
    </ListGroup>
  );
}

const s = StyleSheet.create({
  profile: {
    minHeight: 72,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: radius.lg,
  },
  profileText: { flex: 1, minWidth: 0, gap: 2 },
});
