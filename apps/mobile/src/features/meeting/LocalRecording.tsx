/**
 * Telefonda turgan, hali serverga yetmagan yozuv sahifasi (spec 3.3).
 *
 * NIMA UCHUN pleer bor: egasining savoli - "yozilganini qayerda eshitaman?". Yozuv
 * telefonda - demak internet bo'lmasa ham uni darhol eshitish mumkin. Pastda
 * xuddi server yozuvidagi kabi pleer, tepada esa yuklash holati HAQIQIY sababi
 * bilan (internet yo'q / server / yoqilmagan / kirish kerak / N%).
 *
 * Yuklash tugashi bilan (`state === 'done'`) yo'nalish o'zi server sahifasiga
 * almashadi (`app/meeting/[id].tsx`, navbat obunasi). Pleer bu yerda EMAS - xostda
 * (`RecordingScreen`): sahifa almashganda ijro to'xtamasin.
 */
import { Stack } from 'expo-router';
import { EllipsisVertical, Sparkles, Trash } from 'lucide-react-native';
import { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { useSettings, useT } from '@/features/settings/settingsStore';
import type { QueueRow } from '@/features/upload/queueStore';
import { uploadStatus, useOnline, type UploadCause } from '@/features/upload/uploadStatus';
import { useServices } from '@/services';
import { Banner } from '@/ui/components';
import { EmptyState } from '@/ui/EmptyState';
import { IconButton } from '@/ui/IconButton';

import { ActionMenu } from './ActionMenu';
import { MeetingHeader } from './MeetingHeader';
import { leaveRecording } from './nav';
import { localTitle } from './RecordingCard';
import { confirmDiscard, UploadStatusCard } from './UploadStatusCard';

/**
 * "Xulosa yuklangandan keyin" va'dasi faqat yozuv rostdan yuklanadigan holatlarda.
 * Bo'lim yoqilmagan, yuklash yiqilgan yoki kirish kerak bo'lsa bu va'da tepadagi
 * halol kartaga zid bo'lardi.
 */
const PROMISE_CAUSES: ReadonlySet<UploadCause> = new Set(['recording', 'waiting', 'uploading', 'offline', 'server']);

export function LocalRecording({
  row,
  serverFailed,
}: {
  row: QueueRow;
  /**
   * Server sahifasi ochilmadi (ko'pincha internet yo'q), lekin fayl telefonda: sabab va
   * "Qayta urinish" tepada, pastda pleer baribir ishlaydi.
   */
  serverFailed?: { text: string; onRetry: () => void };
}) {
  const t = useT();
  const lang = useSettings((s) => s.uiLang);
  const services = useServices();
  const online = useOnline();
  const [menu, setMenu] = useState(false);
  const recording = row.state === 'recording';
  const promise = PROMISE_CAUSES.has(uploadStatus(row, { online }).cause);
  // Yuklangan yozuv (server nusxasi bor): bu yerdan o'chirish "hali yuklanmagan" tasdig'i
  // bilan noto'g'ri bo'lardi - o'chirish server sahifasida.
  const menuShown = row.state !== 'done';

  return (
    <View style={s.root}>
      <Stack.Screen
        options={{
          title: '',
          headerRight: menuShown
            ? () => <IconButton testID="meeting-menu" icon={EllipsisVertical} label={t('recs.menu')} onPress={() => setMenu(true)} disabled={recording} />
            : undefined,
        }}
      />
      <ScrollView contentContainerStyle={s.content}>
        <MeetingHeader title={localTitle(row, t)} at={row.startedAt} durationSec={row.durationSec} lang={lang} />
        {serverFailed ? (
          <Banner tone="warn" testID="local-server-failed" text={serverFailed.text} action={{ title: t('common.retry'), onPress: serverFailed.onRetry }} />
        ) : null}
        <UploadStatusCard row={row} onDeleted={leaveRecording} />
        {promise ? <EmptyState compact icon={Sparkles} tone="accent" title={t('recs.pendingTitle')} body={t('recs.pendingBody')} /> : null}
      </ScrollView>
      <ActionMenu
        visible={menu}
        title={t('recs.menu')}
        onClose={() => setMenu(false)}
        items={[
          {
            key: 'delete',
            title: t('common.delete'),
            icon: Trash,
            destructive: true,
            disabled: recording,
            onPress: () => confirmDiscard(t, services, row, leaveRecording),
          },
        ]}
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  content: { padding: 16, paddingBottom: 32, gap: 16 },
});
