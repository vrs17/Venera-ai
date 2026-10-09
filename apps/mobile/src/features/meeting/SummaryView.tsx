/**
 * Xulosa tabi (spec 7.4): `layout` tartibidagi bo'limlar, har biri uchun
 * mos karta; dalil chiplari audio/transkriptga o'tkazadi. Shablon
 * almashtirgich (+ Yangi xulosa), Markdown ulashish, matn nusxalash,
 * xato bo'lsa qayta urinish.
 *
 * Ko'rsatish mantig'i `summaryModel.ts` da - bu fayl faqat chizadi.
 */
import * as Clipboard from 'expo-clipboard';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';

import type { Meeting, Speaker, Summary, SummaryCard, TemplateId } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Banner, Body, Button, Card, Chip, EvidenceChip, Loading, Muted, styles as ui } from '@/ui/components';
import { errorText, shareableText, showToast } from '@/ui/errors';
import { PickerModal, type PickerOption } from '@/ui/modals';
import { useTheme } from '@/ui/theme';

import { formatDateTime, formatDuration } from './formatDate';
import { engineLabel } from './provenance';
import { useMeetingMutations, useSummaries, useSummary } from './queries';
import { buildSummaryView, summaryToText, type ItemView, type SectionView } from './summaryModel';

export const TEMPLATE_IDS: TemplateId[] = [
  'auto',
  'general',
  'minutes',
  'standup',
  'one_on_one',
  'project_review',
  'brainstorm',
  'sales_call',
  'interview',
  'lecture',
  'short_call',
  'follow_up',
];

export function useTemplateTitle(): (id: TemplateId) => string {
  const t = useT();
  const config = useAuth((s) => s.config);
  return (id) => config?.templates.find((x) => x.id === id)?.title ?? t(`template.${id}`);
}

export interface SummaryViewProps {
  meeting: Meeting;
  speakers?: Speaker[];
  onSeek?: (t: number) => void;
  onAcceptName?: (speaker: string, name: string) => void;
}

export function SummaryView({ meeting, speakers, onSeek, onAcceptName }: SummaryViewProps) {
  const t = useT();
  const templateTitle = useTemplateTitle();
  const transcriptReady = meeting.transcript.available;
  const summaries = useSummaries(meeting.id, transcriptReady, meeting.status === 'summarizing');
  const items = useMemo(() => summaries.data?.items ?? [], [summaries.data]);
  const [selected, setSelected] = useState<string | null>(null);
  const [picker, setPicker] = useState(false);
  const muts = useMeetingMutations(meeting.id);

  const activeId = selected && items.some((s) => s.id === selected) ? selected : (meeting.primarySummaryId ?? items[0]?.id ?? null);
  const active = items.find((s) => s.id === activeId) ?? null;

  if (!transcriptReady) {
    if (meeting.status === 'failed') return <Banner tone="bad" text={meeting.error?.message ?? t('common.error')} />;
    return <Banner tone="info" text={t('detail.processing')} />;
  }

  const templateOptions: PickerOption<TemplateId>[] = TEMPLATE_IDS.filter((id) => id !== 'auto').map((id) => ({
    value: id,
    label: templateTitle(id),
  }));

  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.tabs}>
        {items.map((card) => (
          <Chip
            key={card.id}
            testID={`summary-tab-${card.id}`}
            label={`${templateTitle(card.template)}${card.primary ? ' ★' : ''}`}
            tone={card.id === activeId ? 'accent' : 'neutral'}
            selected={card.id === activeId}
            onPress={() => setSelected(card.id)}
          />
        ))}
        <Chip testID="summary-new" label={t('detail.newSummary')} tone="info" onPress={() => setPicker(true)} />
      </ScrollView>

      {meeting.summaryStatus === 'skipped' && !active ? <Banner tone="neutral" text={t('detail.summarySkipped')} /> : null}
      {!active && summaries.isLoading ? <Loading /> : null}
      {!active && !summaries.isLoading && meeting.summaryStatus !== 'skipped' ? (
        <Banner tone="info" text={meeting.summaryStatus === 'queued' || meeting.summaryStatus === 'running' ? t('detail.processing') : t('detail.summaryNone')} />
      ) : null}

      {active ? (
        <SummaryBody
          meeting={meeting}
          card={active}
          speakers={speakers}
          onSeek={onSeek}
          onAcceptName={onAcceptName}
          onRegenerate={() => muts.createSummary.mutate({ template: active.template, language: active.language, force: true, makePrimary: active.primary })}
          regenerating={muts.createSummary.isPending}
        />
      ) : null}

      <PickerModal
        visible={picker}
        title={t('detail.chooseTemplate')}
        options={templateOptions}
        onCancel={() => setPicker(false)}
        onPick={(template) => {
          setPicker(false);
          muts.createSummary.mutate({ template, makePrimary: template !== 'follow_up' });
        }}
      />
    </View>
  );
}

function SummaryBody(props: {
  meeting: Meeting;
  card: SummaryCard;
  speakers?: Speaker[];
  onSeek?: (t: number) => void;
  onAcceptName?: (speaker: string, name: string) => void;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  const { meeting, card } = props;
  const t = useT();
  const q = useSummary(meeting.id, card.id);
  const summary: Summary | undefined = q.data;
  const view = useMemo(() => (summary ? buildSummaryView(summary, t, { speakers: props.speakers }) : null), [summary, t, props.speakers]);

  if (card.status === 'queued' || card.status === 'running') return <Banner tone="info" text={t('detail.processing')} />;
  if (card.status === 'skipped') return <Banner tone="neutral" text={t('detail.summarySkipped')} />;
  if (card.status === 'failed') {
    return (
      <Banner
        tone="bad"
        text={t('detail.summaryFailed', { message: card.error?.message ?? '' })}
        action={{ title: t('common.retry'), onPress: props.onRegenerate }}
      />
    );
  }
  if (q.isLoading || !summary) return <Loading />;
  if (!view) return <Banner tone="info" text={t('detail.summaryNone')} />;

  return (
    <View testID="summary-body">
      {card.stale ? (
        <Banner tone="warn" text={t('detail.stale')} action={{ title: t('detail.regenerate'), onPress: props.onRegenerate }} />
      ) : null}
      <ShareRow meeting={meeting} summary={summary} text={() => summaryToText(view, t, { header: [headerLine(meeting, summary)] })} />
      {view.sections.map((sec) => (
        <SectionCard key={sec.key} section={sec} onSeek={props.onSeek} onAcceptName={props.onAcceptName} />
      ))}
      {view.warnings.length ? <Muted>{view.warnings.join('\n')}</Muted> : null}
      <Provenance summary={summary} />
    </View>
  );
}

/** "Xulosa: Barno Core" - qaysi model yozgani; server aytmasa ko'rinmaydi. */
export function Provenance({ summary }: { summary: Pick<Summary, 'generatedBy'> }) {
  const t = useT();
  const engine = engineLabel(summary.generatedBy);
  if (!engine) return null;
  return (
    <Muted testID="summary-provenance" style={s.provenance}>
      {t('sum.generatedBy', { engine })}
    </Muted>
  );
}

function headerLine(meeting: Meeting, summary: Summary): string {
  const lang = summary.content?.language ?? summary.language;
  const dur = formatDuration(meeting.durationSec);
  return `${formatDateTime(meeting.recordedAt, lang)}${dur ? ` · ${dur}` : ''}`;
}

function ShareRow({ meeting, summary, text }: { meeting: Meeting; summary: Summary; text: () => string }) {
  const t = useT();
  const { meetings } = useServices();
  const [copied, setCopied] = useState(false);
  return (
    <View style={[ui.row, { marginBottom: 10 }]}>
      <Button
        small
        variant="secondary"
        title={t('detail.copyText')}
        testID="summary-copy"
        onPress={async () => {
          try {
            await Clipboard.setStringAsync(shareableText(text(), t).text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch (e) {
            showToast(errorText(t, e));
          }
        }}
      />
      <Button
        small
        variant="secondary"
        style={{ marginLeft: 8 }}
        title={t('detail.shareMd')}
        testID="summary-share"
        onPress={async () => {
          let md: string;
          try {
            md = await meetings.exportSummary(meeting.id, summary.id, 'md');
          } catch {
            md = text(); // oflayn: lokal matn
          }
          try {
            await Share.share({ message: shareableText(md, t).text, title: summary.content?.title ?? meeting.title });
          } catch (e) {
            showToast(errorText(t, e));
          }
        }}
      />
      {copied ? <Text style={{ marginLeft: 8, alignSelf: 'center' }}>{t('common.copied')}</Text> : null}
    </View>
  );
}

function SectionCard({ section, onSeek, onAcceptName }: { section: SectionView; onSeek?: (t: number) => void; onAcceptName?: (speaker: string, name: string) => void }) {
  const th = useTheme();
  return (
    <Card>
      <Text testID={`section-${section.key}`} style={[s.sectionTitle, { color: th.text }]}>
        {section.title}
      </Text>
      {section.kind === 'text' && section.text ? <Body selectable>{section.text}</Body> : null}
      {section.kind === 'tags' ? (
        <View style={ui.wrap}>
          {section.tags.map((tag) => (
            <Chip key={tag} label={tag} />
          ))}
        </View>
      ) : null}
      {section.items.map((it) => (
        <ItemRow key={it.id} item={it} onSeek={onSeek} onAcceptName={onAcceptName} checkable={section.key === 'actionItems'} />
      ))}
    </Card>
  );
}

function ItemRow({
  item,
  onSeek,
  onAcceptName,
  depth = 0,
  checkable,
}: {
  item: ItemView;
  onSeek?: (t: number) => void;
  onAcceptName?: (speaker: string, name: string) => void;
  depth?: number;
  checkable?: boolean;
}) {
  const th = useTheme();
  const t = useT();
  return (
    <View style={[s.item, depth > 0 && { marginLeft: 14 }, { borderColor: th.border }]}>
      <Pressable disabled={item.start == null || !onSeek} onPress={() => item.start != null && onSeek?.(item.start)}>
        <Text selectable style={[s.itemText, { color: th.text }]}>
          {checkable ? '☐ ' : depth > 0 ? '· ' : '• '}
          {item.text}
        </Text>
      </Pressable>
      {item.sub.map((line, i) => (
        <Text key={i} style={[s.sub, { color: th.textMuted }]}>
          {line}
        </Text>
      ))}
      {item.quote ? <Text style={[s.quote, { color: th.textMuted, borderColor: th.border }]}>“{item.quote}”</Text> : null}
      {item.chips.length || item.start != null || item.action ? (
        <View style={ui.wrap}>
          {item.chips.map((c, i) => (
            <Chip
              key={i}
              label={c.label}
              tone={c.tone}
              onPress={item.action && c.tone === 'info' && onAcceptName ? () => onAcceptName(item.action!.speaker, item.action!.name) : undefined}
            />
          ))}
          {item.action && onAcceptName ? (
            <Chip label={t('common.yes')} tone="good" onPress={() => onAcceptName(item.action!.speaker, item.action!.name)} />
          ) : null}
          <EvidenceChip start={item.start} onSeek={onSeek} />
        </View>
      ) : null}
      {item.children.map((ch) => (
        <ItemRow key={ch.id} item={ch} onSeek={onSeek} depth={depth + 1} />
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  tabs: { marginBottom: 10, flexGrow: 0 },
  sectionTitle: { fontSize: 17, fontWeight: '700', marginBottom: 6 },
  item: { paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth },
  itemText: { fontSize: 15, lineHeight: 21 },
  sub: { fontSize: 13, lineHeight: 18, marginTop: 2 },
  quote: { fontSize: 13, fontStyle: 'italic', marginTop: 4, paddingLeft: 8, borderLeftWidth: 2 },
  provenance: { fontSize: 12, marginTop: 2, marginBottom: 6 },
});
