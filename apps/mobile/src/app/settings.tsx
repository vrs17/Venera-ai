/**
 * Sozlamalar (Mini App sozlamalari + yig'ilish yozish): profil; til va mavzu;
 * HRM/CRM ulanishlari (qayta kirish); yig'ilish yozuvlari bo'limi; "Tez yozish"
 * (Yozish launcher belgisi, Quick Settings plitkasi, yorliq, Samsung/Pixel yon
 * tugma yo'riqnomasi); yozish; xotira; ilova haqida; chiqish.
 */
import { useQuery } from '@tanstack/react-query';
import { Directory } from 'expo-file-system';
import { router } from 'expo-router';
import { ChevronRight, ListChecks, Mic } from 'lucide-react-native';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, AppState, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';

import { useAuth } from '@/features/auth/authStore';
import {
  isAvailable,
  isKeyServiceEnabled,
  isLauncherEnabled,
  openAccessibilitySettings,
  requestAddTile,
  setLauncherEnabled,
  type AddTileResult,
} from '@/features/entry/nativeEntry';
import { openBatterySettings } from '@/features/recorder/battery';
import { RECORDING_SOURCES } from '@/features/recorder/preset';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { useSettings, useT, type ThemePref } from '@/features/settings/settingsStore';
import { useChat } from '@/features/chat/chatStore';
import { isPending } from '@/features/upload/uploader';
import { useQueueRows } from '@/features/upload/useQueue';
import { UI_LANGS, type TKey, type UiLang } from '@/i18n';
import { recordingsDir } from '@/lib/paths';
import { useServices } from '@/services';
import { Banner, Button, Card, Chip, Muted, Segmented, styles as ui } from '@/ui/components';
import { useTheme } from '@/ui/theme';

export default function SettingsScreen() {
  const t = useT();
  const th = useTheme();
  const services = useServices();
  const user = useAuth((s) => s.user);
  const settings = useSettings();
  const rows = useQueueRows();
  const [launcher, setLauncher] = useState(() => isLauncherEnabled());
  const [tileResult, setTileResult] = useState<AddTileResult | null>(null);
  // Ovoz tugmasi xizmati Android sozlamasida yoqiladi - ilovaga qaytganda holat qayta o'qiladi.
  const [volumeOn, setVolumeOn] = useState(() => isKeyServiceEnabled());
  useEffect(() => {
    const sub = AppState.addEventListener('change', (st) => {
      if (st === 'active') setVolumeOn(isKeyServiceEnabled());
    });
    return () => sub.remove();
  }, []);
  const pending = rows.filter((r) => isPending(r) || r.state === 'recording' || r.state === 'failed');
  // Yozuv ketayotganda chiqish yozilayotgan faylni o'chirib yuborardi (yozuv jim yo'qoladi).
  const recording = useRecorderStore((s) => isActive(s.machine));
  const meetingsOn = useAuth((s) => s.config !== null);
  const connectors = useQuery({ queryKey: ['connectors'], queryFn: () => services.chat.connectors(), staleTime: 30_000 });

  const reconnect = () =>
    Alert.alert(t('settings.reconnect'), t('settings.reconnectHint'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('settings.reconnect'),
        onPress: () => {
          useChat.getState().abort();
          // Navbat (yuklanmagan yozuvlar) SAQLANADI - faqat sessiya; qayta kirganda davom etadi.
          void services.session.logout();
        },
      },
    ]);

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

  const tileText: Record<AddTileResult, string> = {
    added: t('settings.tile.added'),
    already: t('settings.tile.already'),
    denied: t('settings.tile.denied'),
    unsupported: t('settings.tile.unsupported'),
  };

  return (
    <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 48 }}>
      <Card>
        <View style={[ui.row, { gap: 12 }]}>
          <View style={[s.avatar, { backgroundColor: th.surfaceAlt, borderColor: th.border }]}>
            <Text style={{ color: th.text, fontWeight: '700', fontSize: 16 }}>{initialsOf(user?.fullName)}</Text>
          </View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ color: th.text, fontSize: 17, fontWeight: '700' }} numberOfLines={1}>
              {user?.fullName ?? user?.email ?? '—'}
            </Text>
            {user?.position || user?.email ? <Muted>{[user?.position, user?.email].filter(Boolean).join(' · ')}</Muted> : null}
          </View>
        </View>
      </Card>

      <Card>
        <Text style={[s.h, { color: th.text }]}>{t('settings.appearance')}</Text>
        <Muted style={{ marginBottom: 6 }}>{t('settings.uiLang')}</Muted>
        <Segmented
          testIDPrefix="uilang"
          options={UI_LANGS.map((l) => ({ value: l, label: t(`lang.${l}`) }))}
          value={settings.uiLang}
          onChange={(v: UiLang) => settings.set({ uiLang: v })}
        />
        <Muted style={{ marginTop: 12, marginBottom: 6 }}>{t('settings.theme')}</Muted>
        <Segmented
          testIDPrefix="theme"
          options={(['system', 'light', 'dark'] as ThemePref[]).map((v) => ({ value: v, label: t(THEME_KEYS[v]) }))}
          value={settings.themePref}
          onChange={(v: ThemePref) => settings.set({ themePref: v })}
        />
      </Card>

      <Card>
        <Text style={[s.h, { color: th.text }]}>{t('settings.connections')}</Text>
        {connectors.isLoading ? <ActivityIndicator color={th.textMuted} style={{ alignSelf: 'flex-start' }} /> : null}
        {(connectors.data?.connectors ?? []).map((c) => {
          const tone = !c.configured ? 'neutral' : c.state === 'connected' ? 'good' : c.state === 'expired' ? 'warn' : 'bad';
          const label = !c.configured
            ? t('settings.connNotConfigured')
            : c.state === 'connected'
              ? t('settings.connConnected')
              : c.state === 'expired'
                ? t('settings.connExpired')
                : t('settings.connDisconnected');
          return (
            <View key={c.id} style={[ui.row, { justifyContent: 'space-between', paddingVertical: 8 }]}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={{ color: th.text, fontSize: 15, fontWeight: '600' }}>{c.label || c.id.toUpperCase()}</Text>
                {c.login ? <Muted>{t('settings.connAs', { login: c.login })}</Muted> : null}
              </View>
              <View style={{ borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, backgroundColor: th.tones[tone].bg }}>
                <Text style={{ color: th.tones[tone].fg, fontSize: 13, fontWeight: '600' }}>{label}</Text>
              </View>
            </View>
          );
        })}
        <Muted style={{ marginTop: 6 }}>{t('settings.reconnectHint')}</Muted>
        <Button small variant="secondary" title={t('settings.reconnect')} onPress={reconnect} style={{ marginTop: 8, alignSelf: 'flex-start' }} />
      </Card>

      {meetingsOn ? (
        <Card>
          <NavRow icon={<Mic size={18} color={th.textSoft} />} title={t('settings.meetings')} hint={t('settings.meetingsHint')} onPress={() => router.push('/meetings')} testID="settings-meetings" />
          <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: th.border, marginVertical: 4 }} />
          <NavRow icon={<ListChecks size={18} color={th.textSoft} />} title={t('settings.myTasks')} onPress={() => router.push('/action-items')} />
        </Card>
      ) : null}

      {/* Tez yozish (yon tugma, plitka, ovoz tugmasi) - DOIM ko'rinadi: yozish internetsiz va
          server yig'ilishlar bo'limini yoqmagan paytda ham ishlaydi (navbatda kutadi). */}
      <Card>
        <Text style={[s.h, { color: th.text }]}>{t('settings.quick')}</Text>
        <Muted style={{ marginBottom: 10 }}>{t('settings.quickIntro')}</Muted>
        <View style={[ui.row, { justifyContent: 'space-between' }]}>
          <Text style={{ color: th.text, flex: 1, fontSize: 15 }}>{t('settings.launcherToggle')}</Text>
          <Switch
            testID="launcher-toggle"
            value={launcher}
            disabled={!isAvailable()}
            onValueChange={(v) => {
              setLauncherEnabled(v);
              setLauncher(isLauncherEnabled() || v);
            }}
          />
        </View>
        <Muted style={{ marginBottom: 10 }}>{t('settings.launcherHint')}</Muted>
        <Button
          small
          variant="secondary"
          title={t('settings.addTile')}
          onPress={async () => setTileResult(await requestAddTile())}
          style={{ alignSelf: 'flex-start' }}
        />
        {tileResult ? <Muted style={{ marginTop: 4 }}>{tileText[tileResult]}</Muted> : null}
        <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: th.border, marginVertical: 12 }} />
        <View style={[ui.row, { justifyContent: 'space-between', gap: 8 }]}>
          <Text style={{ color: th.text, flex: 1, fontSize: 15, fontWeight: '600' }}>{t('settings.volumeTitle')}</Text>
          <View style={{ borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, backgroundColor: volumeOn ? th.tones.good.bg : th.surfaceAlt }}>
            <Text testID="volume-status" style={{ color: volumeOn ? th.tones.good.fg : th.textMuted, fontSize: 13, fontWeight: '600' }}>
              {volumeOn ? t('settings.volumeOn') : t('settings.volumeOff')}
            </Text>
          </View>
        </View>
        <Muted style={{ marginTop: 4 }}>{t('settings.volumeHint')}</Muted>
        {!volumeOn ? <Muted style={{ marginTop: 6 }}>{t('settings.volumeSteps')}</Muted> : null}
        <Button
          small
          variant="secondary"
          testID="volume-open"
          title={volumeOn ? t('settings.volumeManage') : t('settings.volumeOpen')}
          disabled={!isAvailable()}
          onPress={() => openAccessibilitySettings()}
          style={{ marginTop: 8, alignSelf: 'flex-start' }}
        />
        <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: th.border, marginVertical: 12 }} />
        <Muted style={{ marginTop: 10 }}>{t('settings.shortcut')}</Muted>
        <View style={{ marginTop: 10 }}>
          {(['settings.step1', 'settings.step2', 'settings.step3', 'settings.step4'] as const).map((k) => (
            <Text key={k} style={[s.step, { color: th.text }]}>
              {t(k)}
            </Text>
          ))}
        </View>
        <Banner tone="info" text={t('settings.powerNote')} />
        <Muted>{t('settings.lockNote')}</Muted>
      </Card>

      {meetingsOn ? (
      <>
      <Card>
        <Text style={[s.h, { color: th.text }]}>{t('settings.recording')}</Text>
        {__DEV__ ? (
          <View style={{ marginBottom: 10 }}>
            <Muted>{t('settings.audioSource')}</Muted>
            <View style={ui.wrap}>
              <Chip
                label={t('settings.audioSourceServer')}
                tone={settings.audioSourceOverride == null ? 'accent' : 'neutral'}
                selected={settings.audioSourceOverride == null}
                onPress={() => settings.set({ audioSourceOverride: null })}
              />
              {RECORDING_SOURCES.map((src) => (
                <Chip key={src} label={src} tone={settings.audioSourceOverride === src ? 'accent' : 'neutral'} selected={settings.audioSourceOverride === src} onPress={() => settings.set({ audioSourceOverride: src })} />
              ))}
            </View>
          </View>
        ) : null}
        <Button small variant="secondary" title={t('settings.battery')} onPress={() => void openBatterySettings()} style={{ alignSelf: 'flex-start' }} />
      </Card>

      <Card>
        <Text style={[s.h, { color: th.text }]}>{t('settings.storage')}</Text>
        <Segmented
          options={[
            { value: '0', label: t('settings.keep0') },
            { value: '7', label: t('settings.keep7') },
          ]}
          value={String(settings.keepDays) as '0' | '7'}
          onChange={(v) => settings.set({ keepDays: v === '7' ? 7 : 0 })}
        />
        <View style={[ui.row, { marginTop: 10, justifyContent: 'space-between' }]}>
          <Muted>{t('settings.queue', { n: pending.length })}</Muted>
          <Button small variant="secondary" title={t('settings.uploadNow')} onPress={() => void services.uploader.runOnce()} />
        </View>
      </Card>
      </>
      ) : null}

      <Card>
        <Text style={[s.h, { color: th.text }]}>{t('settings.about')}</Text>
        <Muted>{t('settings.version', { v: services.appVersion })}</Muted>
        <Muted>{t('settings.server', { url: services.apiBaseUrl })}</Muted>
      </Card>

      <Button
        variant="danger"
        testID="settings-logout"
        title={t('settings.logout')}
        onPress={confirmLogout}
        disabled={recording}
        style={{ marginTop: 4 }}
      />
      {recording ? <Muted style={{ marginTop: 4 }}>{t('settings.logoutBlocked')}</Muted> : null}
    </ScrollView>
  );
}

const THEME_KEYS: Record<ThemePref, TKey> = {
  system: 'settings.themeSystem',
  light: 'settings.themeLight',
  dark: 'settings.themeDark',
};

function initialsOf(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '·';
  return (parts[0][0] + (parts[1]?.[0] ?? '')).toUpperCase();
}

function NavRow({ icon, title, hint, onPress, testID }: { icon: React.ReactNode; title: string; hint?: string; onPress: () => void; testID?: string }) {
  const th = useTheme();
  return (
    <Pressable testID={testID} onPress={onPress} accessibilityRole="button" style={({ pressed }) => [ui.row, { gap: 12, paddingVertical: 10, opacity: pressed ? 0.7 : 1 }]}>
      <View style={[s.navIcon, { backgroundColor: th.surfaceAlt }]}>{icon}</View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={{ color: th.text, fontSize: 16, fontWeight: '600' }}>{title}</Text>
        {hint ? <Muted>{hint}</Muted> : null}
      </View>
      <ChevronRight size={18} color={th.textMuted} />
    </Pressable>
  );
}

const s = StyleSheet.create({
  h: { fontSize: 17, fontWeight: '700', marginBottom: 8 },
  step: { fontSize: 14, lineHeight: 20, marginBottom: 6 },
  avatar: { width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  navIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
});
