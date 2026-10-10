/**
 * Yuklash holati kartasi (spec 3.4) va ro'yxat pill'i: SABAB + keyingi qadam.
 *
 * NIMA UCHUN: eski sahifa har holatda "Internet bo'lganda o'zi yuklanadi" derdi.
 * Endi karta aniq aytadi - internet yo'q (kutish kifoya), server javob bermayapti
 * (qachon qayta urinadi + "Hozir urinish"), bo'lim yoqilmagan (administrator),
 * sessiya tugagan ("Qayta kirish"), yuklanmoqda N% yoki yiqildi (qayta / o'chirish).
 */
import { router } from 'expo-router';
import { CircleAlert, CircleDot, CloudOff, CloudUpload, LockKeyhole, RotateCcw, Trash, type LucideIcon } from 'lucide-react-native';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { useChat } from '@/features/chat/chatStore';
import { useT } from '@/features/settings/settingsStore';
import { discardLocalRecording, type DiscardDeps } from '@/features/upload/discard';
import type { QueueRow } from '@/features/upload/queueStore';
import { uploadStatus, useOnline, type UploadCause, type UploadStatus } from '@/features/upload/uploadStatus';
import type { TFn } from '@/i18n';
import { useServices } from '@/services';
import { Button } from '@/ui/components';
import { errorText } from '@/ui/errors';
import { IconTile, type IconTileTone } from '@/ui/IconTile';
import { ProgressBar, type PillTone } from '@/ui/StatusPill';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

import { formatTime } from './formatDate';

/** Ro'yxatdagi kichik pill: matn va ton (done - pill yo'q). */
export function uploadPill(st: UploadStatus, t: TFn): { label: string; tone: PillTone; dot?: boolean } | null {
  switch (st.cause) {
    case 'recording':
      return { label: t('record.recording'), tone: 'record', dot: true };
    case 'waiting':
      return { label: t('recs.pill.waiting'), tone: 'neutral' };
    case 'uploading':
      return { label: st.percent != null ? t('recs.pill.uploading', { p: st.percent }) : t('recs.pill.uploadingNoPct'), tone: 'info' };
    case 'offline':
      return { label: t('recs.pill.offline'), tone: 'warn' };
    case 'server':
      return { label: t('recs.pill.server'), tone: 'warn' };
    case 'disabled':
      return { label: t('recs.pill.disabled'), tone: 'warn' };
    case 'auth':
      return { label: t('recs.pill.auth'), tone: 'warn' };
    case 'failed':
      return { label: t('recs.pill.failed'), tone: 'bad' };
    case 'done':
      return null;
  }
}

/** Ro'yxat kartasidagi belgi (sabab bo'yicha). */
export function uploadListTile(cause: UploadCause): { icon: LucideIcon; tone: IconTileTone } {
  if (cause === 'recording') return { icon: CircleDot, tone: 'record' };
  if (cause === 'failed') return { icon: CircleAlert, tone: 'bad' };
  if (cause === 'offline' || cause === 'server' || cause === 'disabled' || cause === 'auth') return { icon: CloudOff, tone: 'warn' };
  return { icon: CloudUpload, tone: 'info' };
}

/** Kartadagi katta belgi (spec 3.4 jadvali). */
function cardTile(cause: UploadCause): { icon: LucideIcon; tone: IconTileTone } {
  switch (cause) {
    case 'recording':
      return { icon: CircleDot, tone: 'record' };
    case 'offline':
    case 'server':
      return { icon: CloudOff, tone: 'warn' };
    case 'disabled':
      return { icon: CircleAlert, tone: 'warn' };
    case 'auth':
      return { icon: LockKeyhole, tone: 'warn' };
    case 'failed':
      return { icon: CircleAlert, tone: 'bad' };
    default:
      return { icon: CloudUpload, tone: 'info' };
  }
}

function cardText(st: UploadStatus, t: TFn): { title: string; body: string } {
  switch (st.cause) {
    case 'recording':
      return { title: t('recs.up.recordingTitle'), body: t('recs.up.recordingBody') };
    case 'waiting':
      return { title: t('recs.up.waitingTitle'), body: t('recs.up.waitingBody') };
    case 'uploading':
      return {
        title: st.percent != null ? t('recs.up.uploadingTitle', { p: st.percent }) : t('recs.pill.uploadingNoPct'),
        body: t('recs.up.uploadingBody'),
      };
    case 'offline':
      return { title: t('recs.up.offlineTitle'), body: t('recs.up.offlineBody') };
    case 'server':
      return {
        title: t('recs.up.serverTitle'),
        body: st.retryAt != null && st.retryAt > Date.now() ? t('recs.up.serverBodyAt', { time: formatTime(st.retryAt) }) : t('recs.up.serverBody'),
      };
    case 'disabled':
      return { title: t('recs.up.disabledTitle'), body: t('recs.up.disabledBody') };
    case 'auth':
      return { title: t('recs.up.authTitle'), body: t('recs.up.authBody') };
    case 'failed':
      return { title: t('recs.up.failedTitle'), body: errorText(t, st.errorCode) };
    case 'done':
      return { title: '', body: '' };
  }
}

/**
 * "O'chirish" tasdig'i (karta va ⋮ menyusi bir xil): yuklanmagan yozuv qaytmaydi -
 * shuning uchun doim so'raladi.
 */
export function confirmDiscard(t: TFn, deps: DiscardDeps, row: QueueRow, onDone?: () => void): void {
  Alert.alert(t('common.delete'), t('recs.deleteLocalConfirm'), [
    { text: t('common.cancel'), style: 'cancel' },
    {
      text: t('common.delete'),
      style: 'destructive',
      onPress: () => {
        void discardLocalRecording(deps, row)
          .then((ok) => ok && onDone?.())
          .catch(() => {});
      },
    },
  ]);
}

export function UploadStatusCard({ row, onDeleted }: { row: QueueRow; onDeleted?: () => void }) {
  const t = useT();
  const th = useTheme();
  const services = useServices();
  const online = useOnline();
  const st = uploadStatus(row, { online });
  if (st.cause === 'done') return null;
  const tile = cardTile(st.cause);
  const text = cardText(st, t);

  const retry = () => void services.uploader.retry(row.clientId).catch(() => {});
  const runNow = () => void services.uploader.runOnce().catch(() => {});
  const reconnect = () =>
    Alert.alert(t('settings.reconnect'), t('settings.reconnectHint'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('settings.reconnect'),
        onPress: () => {
          useChat.getState().abort();
          // Navbat SAQLANADI - qayta kirgach yozuv o'zi yuklanadi (karta shuni va'da qiladi).
          void services.session.logout();
        },
      },
    ]);
  const confirmDelete = () => confirmDiscard(t, services, row, onDeleted);

  // Bitta asosiy amal (siyoh rang): karta foni `surfaceAlt` - kulrang tugma unda ko'rinmay qolardi.
  let action: { title: string; onPress: () => void; icon: LucideIcon } | null = null;
  if (st.cause === 'recording') action = { title: t('recs.up.openRecorder'), onPress: () => router.push('/record?src=app'), icon: CircleDot };
  if (st.cause === 'waiting') action = { title: t('recs.up.tryNow'), onPress: runNow, icon: CloudUpload };
  if (st.cause === 'server') action = { title: t('recs.up.tryNow'), onPress: retry, icon: RotateCcw };
  if (st.cause === 'disabled') action = { title: t('common.retry'), onPress: retry, icon: RotateCcw };
  if (st.cause === 'auth') action = { title: t('settings.reconnect'), onPress: reconnect, icon: LockKeyhole };
  if (st.cause === 'failed') action = { title: t('common.retry'), onPress: retry, icon: RotateCcw };

  return (
    <View testID="upload-card" style={[s.card, { backgroundColor: th.surfaceAlt }]}>
      <View style={s.head}>
        <IconTile icon={tile.icon} tone={tile.tone} />
        <View style={s.text}>
          <Text testID="upload-title" style={[typeScale.headline, { color: th.text, fontSize: 16 }]}>
            {text.title}
          </Text>
          {text.body ? <Text style={[typeScale.sub, { color: th.textMuted }]}>{text.body}</Text> : null}
        </View>
      </View>
      {st.cause === 'uploading' ? <ProgressBar testID="upload-progress" value={st.percent != null ? st.percent / 100 : null} tone="info" /> : null}
      {action || st.cause === 'failed' ? (
        <View style={s.actions}>
          {action ? (
            <Button small pill testID="upload-action" title={action.title} icon={action.icon} onPress={action.onPress} />
          ) : null}
          {st.cause === 'failed' ? (
            <Button small pill testID="upload-delete" variant="ghost" title={t('common.delete')} icon={Trash} onPress={confirmDelete} />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: { borderRadius: radius.lg, padding: 16, gap: 12 },
  head: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  text: { flex: 1, gap: 2 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingLeft: 52 },
});
