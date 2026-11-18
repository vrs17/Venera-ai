/**
 * «Ovoz namunasi» (ega qarori 2026-11-18): Plaud yig'ilishlarida xodim ism-familiyasi bilan chiqishi uchun ~45 s lik
 * namuna. Tartib va o'qiladigan matn SERVERDAN (`GET /voice-sample` -> `instructions`) - Telegram va Slack'dagi bilan
 * AYNAN bir xil. Ekran: holat -> tartib -> matn -> yozish (expo-audio, AAC) -> yuborish -> natija (server 5-60 s
 * tekshiradi, `GET /voice-sample/{id}` so'raladi) -> «Ovozimni o'chirish».
 *
 * YIG'ILISH YOZILAYOTGAN BO'LSA yozish bloklanadi: ikkinchi yozuvchi va `setAudioModeAsync` yig'ilishning foreground
 * xizmatini buzardi (`features/voice/native.ts` dagi qoida).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder, useAudioRecorderState, type RecordingOptions } from 'expo-audio';
import { Mic, RotateCcw, Send, Square, Trash2 } from 'lucide-react-native';
import { useEffect, useRef, useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import type { VoiceSampleView } from '@/api/types';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Banner, Button, Card, Loading, Muted, SectionTitle } from '@/ui/components';
import { useSafeInsets } from '@/ui/insets';
import { useTheme } from '@/ui/theme';
import { type as typeScale } from '@/ui/tokens';

/** AAC (ADTS), mono 16 kHz - yig'ilish yozuvi bilan bir xil format (server va GAPI qabul qiladi). */
const SAMPLE_PRESET: RecordingOptions = {
  ...RecordingPresets.HIGH_QUALITY,
  extension: '.aac',
  sampleRate: 16000,
  numberOfChannels: 1,
  bitRate: 48000,
  android: { extension: '.aac', outputFormat: 'aac_adts', audioEncoder: 'aac', audioSource: 'voice_recognition' },
  ios: { ...RecordingPresets.HIGH_QUALITY.ios, extension: '.m4a', sampleRate: 16000 },
};
const MIN_SEC = 30;
/** 90 s AAC (48 kbps) ~0.55 MB - edge proksining ~1 MB chegarasidan ancha past. */
const MAX_SEC = 90;
const POLL_MS = 2000;
const POLL_LIMIT_MS = 120_000;

function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export default function VoiceSampleScreen() {
  const t = useT();
  const th = useTheme();
  const insets = useSafeInsets();
  const services = useServices();
  const queryClient = useQueryClient();
  const meetingRecording = useRecorderStore((s) => isActive(s.machine));
  const status = useQuery({ queryKey: ['voice-sample'], queryFn: () => services.meetings.voiceStatus(), staleTime: 10_000 });
  const recorder = useAudioRecorder(SAMPLE_PRESET);
  const rec = useAudioRecorderState(recorder, 250);
  const [recordedMs, setRecordedMs] = useState(0);
  const [fileUri, setFileUri] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VoiceSampleView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const limit = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAt = useRef(0);

  useEffect(
    () => () => {
      alive.current = false;
      if (limit.current) clearTimeout(limit.current);
    },
    [],
  );

  const stop = async () => {
    if (limit.current) clearTimeout(limit.current);
    limit.current = null;
    // Taymerdan chaqirilganda holat eskirgan bo'ladi - davomiylik boshlangan vaqtdan.
    const ms = startedAt.current ? Date.now() - startedAt.current : rec.durationMillis;
    startedAt.current = 0;
    try {
      await recorder.stop();
    } catch {
      /* allaqachon to'xtagan */
    }
    try {
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false, allowsBackgroundRecording: false, shouldPlayInBackground: false });
    } catch {
      /* rejim qaytmasa ham namuna saqlanadi */
    }
    setRecordedMs(ms);
    setFileUri(recorder.uri ?? null);
  };

  const start = async () => {
    setError(null);
    setResult(null);
    if (meetingRecording) {
      setError(t('vs.busyRecorder'));
      return;
    }
    const perm = await requestRecordingPermissionsAsync();
    if (!perm.granted) {
      setError(t('vs.micDenied'));
      return;
    }
    try {
      // Qayta yozish: oldingi (yuborilmagan) namuna fayli telefonda qolmasin.
      if (fileUri) await services.files.remove(fileUri);
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true, allowsBackgroundRecording: false, shouldPlayInBackground: false });
      await recorder.prepareToRecordAsync(SAMPLE_PRESET);
      recorder.record();
      setFileUri(null);
      setRecordedMs(0);
      // Uzoq yozuv kerak emas: 90 soniyada o'zi to'xtaydi.
      startedAt.current = Date.now();
      limit.current = setTimeout(() => void stop(), MAX_SEC * 1000);
    } catch {
      setError(t('common.error'));
    }
  };

  const send = async () => {
    if (!fileUri) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      let view = await services.meetings.uploadVoiceSample(fileUri, fileUri.endsWith('.m4a') ? 'audio/mp4' : 'audio/aac');
      const started = Date.now();
      while (view.status === 'processing' && alive.current && Date.now() - started < POLL_LIMIT_MS) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        view = await services.meetings.voiceSample(view.id);
      }
      if (!alive.current) return;
      setResult(view);
      if (view.status === 'ok') {
        await services.files.remove(fileUri);
        setFileUri(null);
      }
      await queryClient.invalidateQueries({ queryKey: ['voice-sample'] });
    } catch (e) {
      // Server xabari bo'lsa (masalan "Oldingi namuna hali tekshirilmoqda") - o'sha; tarmoq yoki proksi xatosi
      // (HTML 403/502, timeout) - tushunarli umumiy matn, "Request failed (403)" emas.
      if (alive.current) setError(e instanceof ApiError && e.body?.message ? e.body.message : t('vs.failed'));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const confirmDelete = () =>
    Alert.alert(t('vs.delete'), t('vs.deleteConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('common.delete'),
        style: 'destructive',
        onPress: () => {
          void (async () => {
            try {
              const res = await services.meetings.deleteVoice();
              setResult(null);
              Alert.alert(t('vs.title'), res.message);
            } catch (e) {
              setError((e as { message?: string })?.message || t('common.error'));
            }
            await queryClient.invalidateQueries({ queryKey: ['voice-sample'] });
          })();
        },
      },
    ]);

  if (status.isLoading) return <Loading />;
  const data = status.data;
  if (!data) {
    return (
      <View style={{ flex: 1, backgroundColor: th.bg, padding: 16 }}>
        <Banner tone="bad" text={t('common.error')} action={{ title: t('common.retry'), onPress: () => void status.refetch() }} />
      </View>
    );
  }
  const info = data.instructions;
  const short = fileUri != null && recordedMs > 0 && recordedMs < MIN_SEC * 1000;

  return (
    <ScrollView style={{ backgroundColor: th.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 48 + insets.bottom, gap: 12 }} testID="voice-sample">
      <Text style={[typeScale.body, { color: th.text }]}>{info.intro}</Text>
      {!data.enabled ? <Banner tone="warn" text={t('vs.disabled')} /> : null}
      {data.enrolled ? <Banner tone="good" text={t('vs.saved', { n: data.samples })} testID="voice-sample-saved" /> : null}

      <Card>
        <SectionTitle>{t('vs.steps')}</SectionTitle>
        {info.steps.map((step, i) => (
          <Text key={i} style={[typeScale.sub, styles.step, { color: th.text }]}>
            {i + 1}. {step}
          </Text>
        ))}
      </Card>

      <Card>
        <SectionTitle>{t('vs.textTitle')}</SectionTitle>
        <Text selectable style={[styles.sampleText, { color: th.text, borderLeftColor: th.primary }]} testID="voice-sample-text">
          {info.text}
        </Text>
        <Muted style={{ marginTop: 8 }}>{info.freeSpeech}</Muted>
      </Card>

      {error ? <Banner tone="bad" text={error} testID="voice-sample-error" /> : null}
      {result ? <Banner tone={result.status === 'ok' ? 'good' : 'bad'} text={result.message} testID="voice-sample-result" /> : null}
      {busy ? <Banner tone="info" text={t('vs.checking')} /> : null}

      {rec.isRecording ? (
        <Card>
          <Text style={[typeScale.headline, { color: th.record, textAlign: 'center' }]}>{t('vs.recording', { time: clock(rec.durationMillis) })}</Text>
          <Button title={t('vs.stop')} icon={Square} variant="record" pill onPress={() => void stop()} style={{ marginTop: 12 }} testID="voice-sample-stop" />
        </Card>
      ) : fileUri ? (
        <Card>
          <Text style={[typeScale.headline, { color: th.text, textAlign: 'center' }]}>{t('vs.recorded', { time: clock(recordedMs) })}</Text>
          {short ? <Muted style={{ textAlign: 'center', marginTop: 4 }}>{t('vs.tooShort')}</Muted> : null}
          <View style={styles.row}>
            <Button title={t('vs.again')} icon={RotateCcw} variant="secondary" onPress={() => void start()} disabled={busy} style={styles.half} testID="voice-sample-again" />
            <Button title={t('vs.send')} icon={Send} onPress={() => void send()} loading={busy} disabled={short} style={styles.half} testID="voice-sample-send" />
          </View>
        </Card>
      ) : (
        <Button
          title={t('vs.start')}
          icon={Mic}
          variant="record"
          pill
          disabled={!data.enabled || busy || meetingRecording}
          onPress={() => void start()}
          testID="voice-sample-start"
        />
      )}
      {meetingRecording ? <Muted style={{ textAlign: 'center' }}>{t('vs.busyRecorder')}</Muted> : null}

      {data.enrolled ? (
        <Button title={t('vs.delete')} icon={Trash2} variant="ghost" onPress={confirmDelete} disabled={busy || rec.isRecording} testID="voice-sample-delete" />
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  step: { marginTop: 6 },
  sampleText: { marginTop: 8, fontSize: 17, lineHeight: 26, borderLeftWidth: 3, paddingLeft: 12 },
  row: { flexDirection: 'row', gap: 12, marginTop: 12 },
  half: { flex: 1 },
});
