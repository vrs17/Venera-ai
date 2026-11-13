/**
 * Chatdagi bayonnoma kartasi - bayonnoma amali bo'lgan javob ostida (ega so'rovi, 2026-11-12):
 *   - ko'rsatma eslab qolindi (jami nechta) - hujjat tayyorlanganda hisobga olinadi;
 *   - hujjat yoki uning yangi versiyasi yozilmoqda (aylanma; karta qatorni har 3 s so'raydi);
 *   - tayyor: N-versiya va «Ochish» - bayonnoma varag'i shu tilda (Word/PDF ulashish o'sha yerda);
 *   - yozilmadi yoki ish boshlanmadi - sababi kod bo'yicha (server `message`i ko'rsatilmaydi).
 * Telegram'da berilgan so'rovlarniki ham shu yerda chiqadi (suhbat kanaldan qat'i nazar bitta).
 *
 * Holat sof mantiqdan (`minutesModel.minutesCardState`): navbatdagi havola (`ChatTurn.minutes` - tarix
 * o'qilgan paytdagi) va kartaning o'z so'rovi (`useMinutesDoc`, faqat havola `running` bo'lganda).
 * NIMA UCHUN tarix o'zi so'ralmaydi: savol-javoblar o'zgarmaydi - faqat hujjatning taqdiri kuzatiladi.
 */
import { FileCheck, NotebookPen, TriangleAlert, type LucideIcon } from 'lucide-react-native';
import { useMemo, type ReactNode } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import type { ChatMinutesRef, MinutesLanguage } from '@/api/types';
import { useT } from '@/features/settings/settingsStore';
import type { TFn } from '@/i18n';
import { Button } from '@/ui/components';
import { IconTile, type IconTileTone } from '@/ui/IconTile';
import { useTheme, type Theme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

import { failedText, minutesCardState, notStartedText, type MinutesCardState } from './minutesModel';
import { useMinutesDoc } from './queries';

export interface MinutesActionCardProps {
  meetingId: string;
  turnId: string;
  minutes: ChatMinutesRef;
  /** «Ochish»: bayonnoma varag'i shu tilda. */
  onOpenMinutes?: (lang: MinutesLanguage) => void;
}

interface CardBody {
  /** Belgi plitkasi; `null` - aylanma (yozilmoqda). */
  icon: LucideIcon | null;
  tone: IconTileTone;
  title: string;
  hint?: string;
}

/** Karta holati -> belgi, asosiy matn va (bo'lsa) izoh. */
function cardBody(t: TFn, state: MinutesCardState): CardBody {
  switch (state.kind) {
    case 'note':
      return { icon: NotebookPen, tone: 'info', title: t('mchat.minutes.noteSaved', { n: state.n }), hint: t('mchat.minutes.noteHint') };
    case 'running':
      return {
        icon: null,
        tone: 'neutral',
        title: t(state.revise ? 'mchat.minutes.revising' : 'mchat.minutes.creating'),
        hint: state.slow ? t('mchat.minutes.slow') : undefined,
      };
    case 'ready':
      return { icon: FileCheck, tone: 'good', title: t('mchat.minutes.ready', { version: state.version }) };
    case 'failed':
      return {
        icon: TriangleAlert,
        tone: 'bad',
        title: failedText(t, { error: { code: state.code, message: '' }, kind: state.revise ? 'revise' : 'generate' }),
      };
    case 'notStarted':
      return { icon: TriangleAlert, tone: 'warn', title: notStartedText(t, state.code, state.revise) };
    default:
      return { icon: TriangleAlert, tone: 'neutral', title: t('mchat.minutes.gone') };
  }
}

export function MinutesActionCard({ meetingId, turnId, minutes, onOpenMinutes }: MinutesActionCardProps) {
  const t = useT();
  const th = useTheme();
  const s = useMemo(() => makeStyles(th), [th]);
  // Faqat yozilayotgan qator so'raladi; tayyor/xato havola - tarixdagi holatning o'zi yetarli.
  const doc = useMinutesDoc(meetingId, minutes.id, minutes.status === 'running');
  const state = minutesCardState(minutes, { view: doc.data, error: doc.error, at: doc.dataUpdatedAt });
  if (!state) return null;
  const body = cardBody(t, state);
  const lang = state.kind === 'ready' ? state.language : null;
  let action: ReactNode = null;
  if (lang && onOpenMinutes) {
    action = <Button testID="mchat-minutes-open" small pill variant="ghost" title={t('mchat.minutes.open')} onPress={() => onOpenMinutes(lang)} />;
  }
  return (
    <View testID={`mchat-minutes-${turnId}`} style={s.card} accessibilityLiveRegion="polite">
      {body.icon ? <IconTile icon={body.icon} tone={body.tone} size="sm" /> : <ActivityIndicator style={s.spinner} color={th.textMuted} />}
      <View style={s.text}>
        <Text style={[typeScale.sub, { color: th.text }]}>{body.title}</Text>
        {body.hint ? <Text style={[typeScale.caption, { color: th.textMuted }]}>{body.hint}</Text> : null}
      </View>
      {action}
    </View>
  );
}

function makeStyles(th: Theme) {
  return StyleSheet.create({
    card: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      marginTop: 10,
      padding: 12,
      borderRadius: radius.lg,
      backgroundColor: th.surfaceAlt,
    },
    // Aylanma belgi plitkasi (32 dp) bilan bir xil joy egallasin - matn sakramasin.
    spinner: { width: 32, height: 32 },
    text: { flex: 1, minWidth: 0, gap: 2 },
  });
}
