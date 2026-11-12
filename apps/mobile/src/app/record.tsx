/**
 * Yozish ekrani - deep link nishoni (spec 2.2, 7.4).
 *
 * Kirish qarori `decideEntry`: ishonchli kalit (`k`) bo'lsa yozish o'zi
 * boshlanadi (yon tugma / plitka / yorliq), aks holda ekran "tayyor"
 * holatda ochiladi. Yozuv ketayotgan bo'lsa havola faqat uni ko'rsatadi.
 *
 * "Saqlandi -> batafsil ekran" o'tishi FAQAT shu ekran ochiq paytda bo'lgan
 * to'xtatishdan keyin. Ekran yopiq paytdagi to'xtash (bildirishnoma Stop,
 * limit, xato) `stopped` holatini qoldiradi - keyingi ochilishda u jimgina
 * tozalanadi, aks holda yon tugma eski yig'ilishga olib ketib, yangi yozuvni
 * boshlamas edi.
 */
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BackHandler, Linking, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import type { Lang } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { decideEntry, entrySignature, parseEntryParams, type EntryParams } from '@/features/entry/deepLink';
import { formatClock } from '@/features/meeting/formatDate';
import { openBatterySettings } from '@/features/recorder/battery';
import { useRecorder, useRecorderStore } from '@/features/recorder/RecorderProvider';
import { elapsedMs, limitState } from '@/features/recorder/recorderMachine';
import { useSettings, useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Banner, Button, Card, Chip, Muted, Segmented, styles as ui } from '@/ui/components';
import { useTheme } from '@/ui/theme';

const SPEAKER_CHOICES: (number | null)[] = [null, 1, 2, 3, 4, 5, 6, 8];

export default function RecordRoute() {
  const params = useLocalSearchParams<{ src?: string; k?: string; action?: string; n?: string }>();
  const signedIn = useAuth((s) => s.status === 'signedIn');
  // Zaxira: `_layout` ning `anchor: 'index'` i ostiga Mini App'ni qo'yadi, lekin stek
  // baribir bo'sh bo'lib qolsa "Orqaga" ilovadan chiqarmasin - asosiy ekranga (Mini App,
  // login talab qilmaydi) olib borsin (yozuv RecorderProvider'da davom etadi).
  useFocusEffect(
    useCallback(() => {
      const sub = BackHandler.addEventListener('hardwareBackPress', () => {
        if (router.canGoBack()) return false;
        router.replace('/');
        return true;
      });
      return () => sub.remove();
    }, []),
  );
  return (
    <RecordScreen
      params={params}
      onSaved={(clientId) => {
        if (signedIn) router.replace(`/meeting/${clientId}?local=1`);
      }}
    />
  );
}

export function RecordScreen({
  params,
  onSaved,
}: {
  params: { src?: string; k?: string; action?: string; n?: string };
  onSaved?: (clientId: string) => void;
}) {
  const t = useT();
  const th = useTheme();
  const services = useServices();
  const actions = useRecorder();
  const m = useRecorderStore((s) => s.machine);
  const levels = useRecorderStore((s) => s.levels);
  const silent = useRecorderStore((s) => s.silent);
  const lastSaved = useRecorderStore((s) => s.lastSavedClientId);
  const settings = useSettings();
  const config = useAuth((s) => s.config);
  const [language, setLanguage] = useState<Lang>(settings.lastLanguage);
  const [speakers, setSpeakers] = useState<number | null>(settings.lastSpeakers);
  const [now, setNow] = useState(() => Date.now());
  const [note, setNote] = useState('');
  const [noteOpen, setNoteOpen] = useState(false);
  const handled = useRef<string | null>(null);
  /** Ekran ochilgan vaqt: undan oldingi to'xtash bu ekranniki emas. */
  const [mountedAt] = useState(() => Date.now());

  const startWith = (source: EntryParams['src']) => {
    useSettings.getState().set({ lastLanguage: language, lastSpeakers: speakers });
    // Shablon tanlovi yo'q (ega qarori 2026-11-12): xulosa turini Barno o'zi aniqlaydi.
    void actions.start({ language, template: 'auto', expectedSpeakers: speakers, source });
  };

  // Deep link / yorliq / plitka qarori - har bir intent bir marta.
  useEffect(() => {
    const p = parseEntryParams(params);
    const sig = entrySignature(p);
    if (handled.current === sig) return;
    handled.current = sig;
    let alive = true;
    (async () => {
      const key = p.k ? await services.tokens.getInstallKey() : null;
      if (!alive) return;
      const decision = decideEntry(p, key, useRecorderStore.getState().machine.status);
      if (decision === 'start') startWith(p.src);
      else if (decision === 'stop') void actions.stop();
    })().catch(() => {});
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.src, params.k, params.action, params.n]);

  // Taymer (yozilayotganda).
  useEffect(() => {
    if (m.status !== 'recording') return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [m.status]);

  // Stop'dan keyin: "Saqlandi, yuklanmoqda" va batafsil ekranga - faqat shu
  // ekran ochiq paytda to'xtagan bo'lsa. Oldingi (ekran yopiq paytdagi) to'xtash
  // jimgina tozalanadi: keyingi tez yozish (yon tugma, plitka) shu ekranda qoladi.
  useEffect(() => {
    if (m.status !== 'stopped' || !lastSaved) return;
    actions.reset();
    if (m.endedAt != null && m.endedAt >= mountedAt) onSaved?.(lastSaved);
    else useRecorderStore.getState().setLastSaved(null);
  }, [m.status, m.endedAt, lastSaved, actions, onSaved, mountedAt]);

  // Ekrandan chiqilganda "Saqlandi" belgisi keyingi safar ko'rinmasin.
  useEffect(() => () => useRecorderStore.getState().setLastSaved(null), []);

  const active = m.status === 'recording' || m.status === 'paused' || m.status === 'stopping';
  const savedBanner = !!lastSaved && !active && m.status !== 'preparing';
  const elapsed = elapsedMs(m, m.status === 'recording' ? now : (m.endedAt ?? now));
  const limit = m.status === 'recording' ? limitState(m, now) : 'ok';
  const minutesLeft = Math.max(1, Math.ceil((m.maxSec - elapsed / 1000) / 60));
  const languages = (config?.languages?.length ? config.languages : (['uz', 'ru', 'en'] as Lang[])).map((l) => ({
    value: l,
    label: t(`lang.${l}`),
  }));

  return (
    <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
      {savedBanner ? <Banner tone="good" text={t('record.saved')} testID="record-saved" /> : null}
      {m.autoStopped && savedBanner ? <Banner tone="warn" text={t('record.limitReached')} /> : null}
      <ErrorBanner status={m.status} message={m.error} onRetry={() => startWith('app')} />

      {!active ? (
        <View>
          {!settings.consentSeen ? (
            <Card>
              <Text style={[s.cardTitle, { color: th.text }]}>{t('record.consentTitle')}</Text>
              <Muted>{t('record.consentBody')}</Muted>
              <Button
                small
                style={{ marginTop: 8, alignSelf: 'flex-start' }}
                title={t('common.ok')}
                onPress={() => useSettings.getState().set({ consentSeen: true })}
              />
            </Card>
          ) : null}
          {!settings.batteryHintSeen ? (
            <Card>
              <Text style={[s.cardTitle, { color: th.text }]}>{t('record.batteryTitle')}</Text>
              <Muted>{t('record.batteryBody')}</Muted>
              <View style={[ui.row, { marginTop: 8 }]}>
                <Button small variant="secondary" title={t('record.batteryAction')} onPress={() => void openBatterySettings()} />
                <Button
                  small
                  variant="ghost"
                  style={{ marginLeft: 8 }}
                  title={t('common.close')}
                  onPress={() => useSettings.getState().set({ batteryHintSeen: true })}
                />
              </View>
            </Card>
          ) : null}

          <Text style={[s.label, { color: th.textMuted }]}>{t('record.language')}</Text>
          <Segmented testIDPrefix="lang" options={languages} value={language} onChange={setLanguage} />

          <Text style={[s.label, { color: th.textMuted }]}>
            {t('record.speakers')} ({t('common.optional')})
          </Text>
          <View style={ui.wrap}>
            {SPEAKER_CHOICES.map((n) => (
              <Chip
                key={String(n)}
                testID={`spk-${n ?? 'auto'}`}
                label={n == null ? t('record.speakersAuto') : String(n)}
                tone={n === speakers ? 'accent' : 'neutral'}
                selected={n === speakers}
                onPress={() => setSpeakers(n)}
              />
            ))}
          </View>

          <Muted style={{ marginTop: 16, textAlign: 'center' }}>{t('record.consent')}</Muted>
          <Pressable
            testID="record-start"
            accessibilityRole="button"
            accessibilityLabel={t('record.start')}
            disabled={m.status === 'preparing'}
            onPress={() => startWith('app')}
            style={[s.bigButton, { backgroundColor: th.record, opacity: m.status === 'preparing' ? 0.6 : 1 }]}>
            <View style={s.bigDot} />
          </Pressable>
          <Text style={[s.center, { color: th.text }]}>{m.status === 'preparing' ? t('record.preparing') : t('record.start')}</Text>
        </View>
      ) : (
        <View>
          <Text
            testID="record-status"
            style={[s.center, { color: m.status === 'paused' ? th.textMuted : th.record, fontWeight: '700' }]}>
            {m.status === 'paused' ? t('record.paused') : `● ${t('record.recording')}`}
          </Text>
          <Text testID="record-timer" style={[s.timer, { color: th.text }]}>
            {formatClock(elapsed / 1000)}
          </Text>
          <LevelBars levels={levels} color={th.record} dim={m.status !== 'recording'} />
          <Muted style={{ textAlign: 'center', marginBottom: 12 }}>{t('record.consent')}</Muted>
          {silent ? <Banner tone="warn" text={t('record.silent')} testID="record-silent" /> : null}
          {limit !== 'ok' ? <Banner tone="warn" testID="record-limit" text={t('record.limitWarn', { min: minutesLeft })} /> : null}

          <View style={s.controls}>
            {m.status === 'paused' ? (
              <Button testID="record-resume" variant="secondary" title={t('record.resume')} onPress={actions.resume} style={s.ctrl} />
            ) : (
              <Button
                testID="record-pause"
                variant="secondary"
                title={t('record.pause')}
                onPress={actions.pause}
                style={s.ctrl}
                disabled={m.status !== 'recording'}
              />
            )}
            <Button
              testID="record-mark"
              variant="primary"
              title={`★ ${t('record.mark')}`}
              onPress={() => {
                actions.mark(null);
                setNote('');
                setNoteOpen(true);
              }}
              style={s.ctrl}
            />
          </View>
          {m.marks.length ? (
            <Muted style={{ textAlign: 'center', marginTop: 6 }}>
              {t('record.marks', { n: m.marks.length })} · {t('record.markAdded', { time: formatClock(m.marks[m.marks.length - 1].t) })}
            </Muted>
          ) : null}
          {noteOpen ? (
            <View style={[ui.row, { marginTop: 8 }]}>
              <TextInput
                testID="mark-note"
                value={note}
                onChangeText={setNote}
                placeholder={t('record.markNote')}
                placeholderTextColor={th.textMuted}
                maxLength={200}
                style={[s.noteInput, { color: th.text, borderColor: th.border }]}
                onSubmitEditing={() => {
                  if (note.trim()) actions.setLastMarkNote(note);
                  setNoteOpen(false);
                }}
              />
              <Button
                small
                testID="mark-note-save"
                title={t('common.save')}
                style={{ marginLeft: 6 }}
                onPress={() => {
                  if (note.trim()) actions.setLastMarkNote(note);
                  setNoteOpen(false);
                }}
              />
            </View>
          ) : null}
          <Button
            testID="record-stop"
            variant="danger"
            title={`■ ${t('record.stop')}`}
            onPress={() => void actions.stop()}
            disabled={m.status === 'stopping'}
            style={{ marginTop: 20 }}
          />
        </View>
      )}
    </ScrollView>
  );
}

function ErrorBanner({ status, message, onRetry }: { status: string; message: string | null; onRetry: () => void }) {
  const t = useT();
  const open = { title: t('record.openSettings'), onPress: () => void Linking.openSettings().catch(() => {}) };
  if (status === 'permission_denied') return <Banner tone="bad" testID="record-error" text={t('record.permissionDenied')} action={open} />;
  if (status === 'notifications_denied') return <Banner tone="bad" testID="record-error" text={t('record.notificationsDenied')} action={open} />;
  if (status === 'disk_low') return <Banner tone="bad" testID="record-error" text={t('record.diskLow')} />;
  if (status === 'not_foreground') {
    return <Banner tone="bad" testID="record-error" text={t('record.notForeground')} action={{ title: t('common.retry'), onPress: onRetry }} />;
  }
  if (status === 'recorder_error') {
    return (
      <Banner
        tone="bad"
        testID="record-error"
        text={t('record.recorderError', { message: message ?? '' })}
        action={{ title: t('common.retry'), onPress: onRetry }}
      />
    );
  }
  return null;
}

function LevelBars({ levels, color, dim }: { levels: number[]; color: string; dim: boolean }) {
  const bars = Array.from({ length: 24 }, (_, i) => levels[levels.length - 24 + i] ?? 0);
  return (
    <View style={s.levels} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {bars.map((v, i) => (
        <View key={i} style={[s.bar, { height: 6 + Math.round(v * 54), backgroundColor: color, opacity: dim ? 0.3 : 0.9 }]} />
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingBottom: 48 },
  cardTitle: { fontSize: 15, fontWeight: '700', marginBottom: 4 },
  label: { fontSize: 13, marginTop: 14, marginBottom: 6 },
  bigButton: {
    width: 120,
    height: 120,
    borderRadius: 60,
    alignSelf: 'center',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 16,
    elevation: 6,
  },
  bigDot: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#fff' },
  center: { textAlign: 'center', marginTop: 10, fontSize: 16 },
  timer: { fontSize: 56, fontWeight: '300', textAlign: 'center', fontVariant: ['tabular-nums'], marginVertical: 8 },
  levels: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', height: 64, marginBottom: 8 },
  bar: { width: 6, borderRadius: 3, marginHorizontal: 2 },
  controls: { flexDirection: 'row', marginTop: 8 },
  ctrl: { flex: 1, marginHorizontal: 4 },
  noteInput: { flex: 1, borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 },
});
