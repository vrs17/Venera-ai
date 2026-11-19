/**
 * Chat tepa paneli va yozuv paytidagi qizil chiziq (Claude ilovasi kabi):
 *
 *   ☰  menyu (drawer)  ·  suhbat nomi (markazda)  ·  Plaud (yozuvlar)  ·  ✎ yangi suhbat
 *   ● Yozilmoqda 03:12                                   Ochish ›   (faqat yozuv paytida)
 *
 * NIMA UCHUN Plaud tepada: egasi "yozuvlarni qayerdan ko'raman?" dedi - chatdan yozuvlarga
 * BIR bosish. Profil (avatar) bu yerdan drawer pastiga ko'chdi: tepada uchta belgi
 * yetarli, sozlamalar kamdan-kam ochiladi.
 *
 * Plaud belgisi - `MeetingsIcon` (pufak va uch kishi, `@/ui/icons`), `AudioLines` EMAS: to'lqin belgisi -
 * chatdagi jonli suhbat tugmasiniki, ikkalasi bir xil bo'lib qolgan edi (ega, 2026-11-19).
 *
 * Qizil chiziq alohida komponent: soat har soniya yangilanadi - butun chat ekrani
 * (javoblar ro'yxati) har soniya qayta chizilmasin.
 */
import { router } from 'expo-router';
import { ChevronRight, Menu, SquarePen } from 'lucide-react-native';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useChat } from '@/features/chat/chatStore';
import { useMeetingsVisible } from '@/features/nav/visibility';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { useRecordingClock } from '@/features/recorder/useRecordingClock';
import { useT } from '@/features/settings/settingsStore';
import { IconButton } from '@/ui/IconButton';
import { MeetingsIcon } from '@/ui/icons';
import { useTheme } from '@/ui/theme';
import { hit, iconSize, stroke, type as typeScale } from '@/ui/tokens';

/** Yon ustunlar bir xil kenglikda - sarlavha ekranning AYNAN o'rtasida tursin (o'ngda 2 tugma, chapda 1). */
const SIDE = hit.min * 2;

export function ChatTopBar({ title, onMenu }: { title: string; onMenu: () => void }) {
  const th = useTheme();
  const t = useT();
  const meetings = useMeetingsVisible();
  const status = useRecorderStore((x) => x.machine.status);
  const live = status === 'recording' || status === 'paused';
  return (
    <View style={[s.bar, { borderBottomColor: th.border }]}>
      <View style={s.side}>
        <IconButton icon={Menu} label={t('nav.menu')} onPress={onMenu} testID="chat-menu" />
      </View>
      <Text style={[typeScale.headline, s.title, { color: th.text }]} numberOfLines={1} accessibilityRole="header">
        {title || t('app.name')}
      </Text>
      <View style={[s.side, s.sideRight]}>
        {meetings ? (
          <IconButton
            icon={MeetingsIcon}
            label={t('nav.recordings')}
            // Yozuv ketayotganda belgi qizil - "yozuv shu yerda" degan ishora.
            color={live ? th.record : th.textSoft}
            onPress={() => router.push('/meetings')}
            testID="chat-meetings"
          />
        ) : null}
        <IconButton icon={SquarePen} label={t('chat.newChat')} onPress={() => useChat.getState().newChat()} testID="chat-new" />
      </View>
    </View>
  );
}

/** Yozuv (yoki pauza) paytida tepa panel ostidagi qizil chiziq: bir bosishda yozuv ekrani. */
export function RecordingStrip() {
  const th = useTheme();
  const t = useT();
  const clock = useRecordingClock();
  if (!clock.live) return null;
  const text = t(clock.paused ? 'nav.pausedLive' : 'nav.recordingLive', { time: clock.label });
  return (
    <Pressable
      testID="chat-recording"
      onPress={() => router.push('/record?src=app')}
      accessibilityRole="button"
      accessibilityLabel={`${text}. ${t('nav.open')}`}
      android_ripple={{ color: th.border }}
      style={({ pressed }) => [s.strip, { backgroundColor: th.tones.bad.bg, opacity: pressed ? 0.85 : 1 }]}>
      <View style={[s.dot, { backgroundColor: th.record, opacity: clock.paused ? 0.5 : 1 }]} />
      <Text style={[typeScale.label, s.tabular, { color: th.record }]} numberOfLines={1}>
        {text}
      </Text>
      <View style={s.spacer} />
      <Text style={[typeScale.label, { color: th.textSoft }]}>{t('nav.open')}</Text>
      <ChevronRight size={iconSize.sm} color={th.textSoft} strokeWidth={stroke.small} />
    </Pressable>
  );
}

const s = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 52,
    paddingHorizontal: 4,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  side: { width: SIDE, flexDirection: 'row', alignItems: 'center' },
  sideRight: { justifyContent: 'flex-end' },
  title: { flex: 1, textAlign: 'center', paddingHorizontal: 4 },
  strip: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 40, paddingHorizontal: 16 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  tabular: { fontVariant: ['tabular-nums'] },
  spacer: { flex: 1 },
});
