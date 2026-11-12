/**
 * Xulosa tabi (spec 7.4) - "har fakt BIR marta" (egasi, 2026-10-15):
 *
 *  1. "Qisqa xulosa" kartasi (doim ochiq; bir bosishda nusxa/ulashish): maqsad, bir gaplik
 *     qisqacha, asosiy fikrlar, qarorlar, vazifalar (mas'ul, muddat, CRM tugmasi), ochiq savollar.
 *     Qaror va vazifa bosilsa tafsiloti ochiladi (sabab, shart, iqtibos, ▶ vaqt).
 *  2. "Batafsil" - FAQAT kartada yo'q narsalar, har bo'lim bitta yig'iq qator ("G'oyalar · 2").
 *  3. Eng pastda bitta jim qator: kayfiyat, kalit so'zlar, faollik, qaysi model yozgani.
 *
 * NEGA: 8,5 daqiqalik yig'ilish 16 ekran edi - bitta fakt 7 joyda (karta, keyin har bo'lim yana).
 * Server birlashtirgan fakt (`alsoIn`) bandida chip bo'lib qoladi - ma'no yo'qolmaydi.
 * Markdown ulashish, matn nusxalash, xato bo'lsa qayta urinish. "+ Yangi xulosa" (boshqa shablon bilan xulosa)
 * olib tashlangan (ega qarori 2026-11-12: hozirgi bosqichda kerak emas - xulosa avtomatik shablon bilan); eski
 * yig'ilishda bir nechta xulosa bo'lsa, ular orasida tanlash chiplari qoladi.
 *
 * Ko'rsatish mantig'i `summaryModel.ts` va `brief.ts` da - bu fayl faqat chizadi.
 */
import * as Clipboard from 'expo-clipboard';
import { ChevronDown, ChevronRight, Copy, Share2, Sparkles } from 'lucide-react-native';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';

import type { ActionItem, Meeting, Speaker, Summary, SummaryCard, TemplateId } from '@/api/types';
import { useAuth } from '@/features/auth/authStore';
import { CrmPanel } from '@/features/crm/CrmPanel';
import { useT } from '@/features/settings/settingsStore';
import { useServices } from '@/services';
import { Banner, Body, Button, Chip, EvidenceChip, Loading, Muted, styles as ui } from '@/ui/components';
import { errorText, shareableText, showToast } from '@/ui/errors';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

import { briefCovers, briefDurationSec, briefRefs, briefToText, buildBrief, type Brief, type BriefItem, type BriefListKey } from './brief';
import { formatClock, formatDateTime, formatDuration } from './formatDate';
import { useActionItems, useMeetingMutations, useSummaries, useSummary } from './queries';
import {
  buildSummaryView,
  detailGroups,
  summaryMetaParts,
  summaryToText,
  type DetailGroup,
  type DetailPlan,
  type ItemView,
  type SectionView,
} from './summaryModel';

const NO_GROUPS: DetailPlan = { shown: [], more: [] };

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
  /**
   * Tanlangan xulosa (ixtiyoriy, boshqariladigan): sahifa uni "Xarita" ko'rinishi va eksport
   * bilan bo'lishadi - xarita ham, ulashilgan fayl ham aynan ko'rib turilgan xulosadan.
   */
  selectedId?: string | null;
  onSelect?: (summaryId: string) => void;
}

export function SummaryView({ meeting, speakers, onSeek, onAcceptName, selectedId, onSelect }: SummaryViewProps) {
  const t = useT();
  const templateTitle = useTemplateTitle();
  const transcriptReady = meeting.transcript.available;
  const summaries = useSummaries(meeting.id, transcriptReady, meeting.status === 'summarizing');
  const items = useMemo(() => summaries.data?.items ?? [], [summaries.data]);
  const [own, setOwn] = useState<string | null>(null);
  const selected = selectedId !== undefined ? selectedId : own;
  const setSelected = (id: string) => {
    setOwn(id);
    onSelect?.(id);
  };
  const muts = useMeetingMutations(meeting.id);

  const activeId = selected && items.some((s) => s.id === selected) ? selected : (meeting.primarySummaryId ?? items[0]?.id ?? null);
  const active = items.find((s) => s.id === activeId) ?? null;

  if (!transcriptReady) {
    if (meeting.status === 'failed') return <Banner tone="bad" text={meeting.error?.message ?? t('common.error')} />;
    return <Banner tone="info" text={t('detail.processing')} />;
  }

  return (
    <View>
      {items.length > 1 ? (
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
        </ScrollView>
      ) : null}

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
  const th = useTheme();
  const q = useSummary(meeting.id, card.id);
  const summary: Summary | undefined = q.data;
  const view = useMemo(() => (summary ? buildSummaryView(summary, t, { speakers: props.speakers }) : null), [summary, t, props.speakers]);
  // Asosiy xulosada vazifalar JONLI ro'yxatdan (odam tahrirlagani, qo'shgani, bajargani) -
  // server eksportidagi "Qisqa xulosa" ham shunday; boshqa xulosada - xulosaning o'zidan.
  // Blok XULOSA tilida (ilova tilida emas) - eksport fayli bilan so'zma-so'z bir xil.
  const live = useActionItems(meeting.id, card.primary);
  const actions = card.primary ? (live.data?.items ?? null) : null;
  const briefSpeakers = props.speakers ?? summary?.speakers;
  const brief = useMemo(
    () => (summary ? buildBrief(summary.content, meeting, briefSpeakers ?? [], { actions }) : null),
    [summary, meeting, briefSpeakers, actions],
  );
  // "Batafsil" - kartada YO'Q narsalar (server eksporti `brief_covers` bilan bir xil qoida):
  // karta qamragan bo'limlar va kartadagi bandlar qayta chiqmaydi; vaqtga o'tish karta bandida.
  const plan = useMemo(() => {
    if (!view) return NO_GROUPS;
    const covered = brief && summary ? briefCovers(summary.content, briefSpeakers ?? []) : new Set<string>();
    return detailGroups(view, { covered, inCard: briefRefs(brief), durationSec: briefDurationSec(summary?.content, meeting) });
  }, [view, brief, summary, briefSpeakers, meeting]);
  const liveById = useMemo(() => new Map((actions ?? []).map((a) => [a.id, a])), [actions]);
  const metaParts = useMemo(() => (summary ? summaryMetaParts(summary, t, props.speakers) : []), [summary, t, props.speakers]);

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
      {brief ? <BriefCard brief={brief} onSeek={props.onSeek} index={view.index} live={liveById} speakers={briefSpeakers} /> : null}
      {brief && plan.shown.length ? <Text style={[typeScale.label, s.details, { color: th.textMuted }]}>{t('recs.brief.details')}</Text> : null}
      {plan.shown.length ? <DetailList key={card.id} plan={plan} onSeek={props.onSeek} onAcceptName={props.onAcceptName} /> : null}
      {view.warnings.length ? <Muted>{view.warnings.join('\n')}</Muted> : null}
      {/* To'liq xulosa nusxasi pastda: tepadagi "Qisqa xulosa" tugmalari bilan adashmasin. Matn - ekrandagining
          o'zi: karta, keyin "Batafsil" guruhlari (yashiringanlari ham), oxirida jim qator; hech narsa ikki marta emas. */}
      <ShareRow
        meeting={meeting}
        summary={summary}
        text={() =>
          summaryToText({ title: view.title, sections: [...plan.shown, ...plan.more].map((g) => g.section) }, t, {
            header: [headerLine(meeting, summary)],
            brief: brief ? briefToText(brief) : null,
            footer: metaParts.length ? [metaParts.join(' · ')] : [],
          })
        }
      />
      <SummaryMeta parts={metaParts} />
    </View>
  );
}

/**
 * Xulosa ostidagi BITTA jim qator ("Kayfiyat: neytral · Kalit so'zlar: ... · Tayyorladi: Gemma") -
 * avval bular alohida kartalar edi. Qismlar `summaryMetaParts` dan; bo'sh bo'lsa hech narsa.
 */
export function SummaryMeta({ parts }: { parts: string[] }) {
  if (!parts.length) return null;
  return (
    <Muted testID="summary-meta" style={s.provenance}>
      {parts.join(' · ')}
    </Muted>
  );
}

function headerLine(meeting: Meeting, summary: Summary): string {
  const lang = summary.content?.language ?? summary.language;
  const dur = formatDuration(meeting.durationSec);
  return `${formatDateTime(meeting.recordedAt, lang)}${dur ? ` · ${dur}` : ''}`;
}

/**
 * "Qisqa xulosa": egasi tasdiqlagan tartib (sarlavha, meta, Maqsad, Qisqacha, Asosiy
 * fikrlar, Qarorlar, Vazifalar, Ochiq savollar). Nusxa va ulashish - ODDIY matn
 * (`briefToText`): messenjerda `**` ko'rinib qolmasin; kartadagi bilan so'zma-so'z bir xil.
 *
 * Karta endi qaror va vazifaning TO'LIQ bo'limi o'rnida ("Batafsil" da ular yo'q), shuning uchun:
 *  - qaror/vazifa bandi bosilsa tafsiloti ochiladi (sabab, shart, kim taklif qildi, iqtibos,
 *    ▶ vaqt) - o'ngda o'q belgisi; tafsiloti yo'q band (fikr, savol) bosilsa yozuv o'sha joydan;
 *  - jonli vazifa ostida CRM tugmasi/holati (Vazifalar tabidagi `CrmPanel` - o'sha mantiq);
 *  - server birlashtirgan fakt chipi ("Tanlangan", "Xavf") band ostida doim ko'rinadi.
 * Vaqt, chip va tafsilot ulashiladigan matnga kirmaydi.
 */
export function BriefCard({
  brief,
  onSeek,
  index,
  live,
  speakers,
}: {
  brief: Brief;
  onSeek?: (t: number) => void;
  /** To'liq xulosa bandlari (`SummaryViewModel.index`) - chip va tafsilot shundan. */
  index?: Map<string, ItemView>;
  /** Jonli vazifalar id bo'yicha (asosiy xulosa) - CRM tugmasi uchun. */
  live?: Map<string, ActionItem>;
  speakers?: Speaker[];
}) {
  const t = useT();
  const th = useTheme();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const text = () => shareableText(briefToText(brief), t).text;
  return (
    <View testID="brief-card" style={[s.brief, { backgroundColor: th.surface, borderColor: th.border }]}>
      <View style={s.briefHead}>
        <Sparkles size={14} color={th.textMuted} strokeWidth={2} />
        <Text style={[typeScale.micro, { color: th.textMuted }]}>{t('recs.brief.heading')}</Text>
      </View>
      {brief.title ? (
        <Text selectable testID="brief-title" style={[s.briefTitle, { color: th.text }]}>
          {brief.title}
        </Text>
      ) : null}
      {brief.meta ? (
        <Text selectable testID="brief-meta" style={[typeScale.caption, { color: th.textMuted }]}>
          {brief.meta}
        </Text>
      ) : null}
      {[brief.purpose, brief.overview].map((line, i) =>
        line ? (
          <Text key={i} selectable testID={i === 0 ? 'brief-purpose' : 'brief-overview'} style={[s.briefText, s.briefGap, { color: th.text }]}>
            <Text style={s.bold}>{`${line.label}:`}</Text> {line.text}
          </Text>
        ) : null,
      )}
      {brief.lists.map((l) => (
        <View key={l.key} testID={`brief-${l.key}`} style={s.briefGap}>
          <Text style={[s.briefText, s.bold, { color: th.text }]}>{`${l.label}:`}</Text>
          {l.items.map((it, i) => (
            <BriefRow
              key={i}
              testID={`brief-${l.key}-${i}`}
              listKey={l.key}
              item={it}
              detail={it.source ? index?.get(`${it.source.section}/${it.source.id}`) : undefined}
              liveItem={it.liveId ? live?.get(it.liveId) : undefined}
              speakers={speakers}
              onSeek={onSeek}
            />
          ))}
        </View>
      ))}
      <View style={s.briefActions}>
        <Button
          small
          variant="secondary"
          icon={Copy}
          title={copied ? t('common.copied') : t('recs.brief.copy')}
          testID="brief-copy"
          onPress={async () => {
            try {
              await Clipboard.setStringAsync(text());
              setCopied(true);
              if (timer.current) clearTimeout(timer.current);
              timer.current = setTimeout(() => setCopied(false), 1500);
            } catch (e) {
              showToast(errorText(t, e));
            }
          }}
        />
        <Button
          small
          variant="secondary"
          icon={Share2}
          title={t('recs.brief.share')}
          testID="brief-share"
          onPress={async () => {
            try {
              await Share.share({ message: text(), ...(brief.title ? { title: brief.title } : {}) });
            } catch (e) {
              showToast(errorText(t, e));
            }
          }}
        />
      </View>
    </View>
  );
}

/** Qaror va vazifa - karta ularning to'liq bo'limi o'rnida: bosilsa tafsiloti ochiladi. */
const EXPANDABLE: ReadonlySet<BriefListKey> = new Set(['decisions', 'actionItems']);

function BriefRow({
  testID,
  listKey,
  item,
  detail,
  liveItem,
  speakers,
  onSeek,
}: {
  testID: string;
  listKey: BriefListKey;
  item: BriefItem;
  detail?: ItemView;
  liveItem?: ActionItem;
  speakers?: Speaker[];
  onSeek?: (t: number) => void;
}) {
  const t = useT();
  const th = useTheme();
  const [open, setOpen] = useState(false);
  // Yig'iq turganda ham ko'rinadigan chiplar: fakt yana qayerda edi (`alsoIn`), kuzatish sababi.
  const tags = detail?.chips.filter((c) => c.kind) ?? [];
  // Ochilganda: band matnida yo'q qatorlar (vazifada mas'ul/muddat matnning o'zida), iqtibos, holat chiplari.
  const lines = detail ? (detail.more ?? detail.sub) : [];
  const chips = detail?.chips.filter((c) => !c.kind) ?? [];
  const expandable = EXPANDABLE.has(listKey) && !!detail && (lines.length > 0 || !!detail.quote || chips.length > 0);
  const seekable = !expandable && item.start != null && !!onSeek;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <View>
      <Pressable
        testID={testID}
        disabled={!expandable && !seekable}
        accessibilityRole={expandable || seekable ? 'button' : undefined}
        accessibilityState={expandable ? { expanded: open } : undefined}
        accessibilityLabel={
          expandable
            ? t(open ? 'recs.map.collapseNode' : 'recs.map.expandNode', { name: item.text })
            : seekable
              ? t('recs.map.playAt', { name: item.text, time: formatClock(item.start) })
              : undefined
        }
        onPress={() => {
          if (expandable) setOpen((x) => !x);
          else if (item.start != null) onSeek?.(item.start);
        }}
        style={s.bullet}>
        <Text style={[s.briefText, { color: th.textMuted }]}>•</Text>
        <Text selectable={!expandable && !seekable} style={[s.briefText, s.flex, { color: th.text }]}>
          {item.text}
        </Text>
        {expandable ? (
          <View style={s.briefChevron}>
            <Chevron size={16} color={th.textMuted} strokeWidth={2} />
          </View>
        ) : seekable ? (
          <Text style={[typeScale.micro, s.briefTime, { color: th.textMuted }]}>{formatClock(item.start)}</Text>
        ) : null}
      </Pressable>
      {tags.length ? (
        <View testID={`${testID}-tags`} style={[ui.wrap, s.briefInset]}>
          {tags.map((c) => (
            <Chip key={c.label} label={c.label} tone={c.tone} />
          ))}
        </View>
      ) : null}
      {open && detail ? (
        <View testID={`${testID}-details`} style={[s.briefInset, s.briefDetails]}>
          {lines.map((line, i) => (
            <Text key={i} style={[s.sub, { color: th.textMuted }]}>
              {line}
            </Text>
          ))}
          {detail.quote ? <Text style={[s.quote, { color: th.textMuted, borderColor: th.border }]}>“{detail.quote}”</Text> : null}
          <View style={ui.wrap}>
            {chips.map((c, i) => (
              <Chip key={i} label={c.label} tone={c.tone} />
            ))}
            <EvidenceChip start={item.start ?? detail.start} onSeek={onSeek} />
          </View>
        </View>
      ) : null}
      {liveItem ? <CrmPanel item={liveItem} speakers={speakers} indent={BULLET_INSET} /> : null}
    </View>
  );
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

/**
 * "Batafsil": har bo'lim bitta yig'iq qator "Sarlavha · son" (bosilsa ochiladi), qisqa yig'ilishda
 * birinchi guruhlar - qolgani "Yana N ta bo'lim" ortida. Bandlar ichida ▶ vaqt va iqtibos avvalgidek.
 */
function DetailList({
  plan,
  onSeek,
  onAcceptName,
}: {
  plan: DetailPlan;
  onSeek?: (t: number) => void;
  onAcceptName?: (speaker: string, name: string) => void;
}) {
  const t = useT();
  const th = useTheme();
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const [all, setAll] = useState(false);
  const groups = all ? [...plan.shown, ...plan.more] : plan.shown;
  const toggle = (key: string) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  return (
    <View testID="details" style={[s.groups, { backgroundColor: th.surface, borderColor: th.border }]}>
      {groups.map((g, i) => (
        <GroupRow key={g.key} group={g} first={i === 0} open={open.has(g.key)} onToggle={() => toggle(g.key)} onSeek={onSeek} onAcceptName={onAcceptName} />
      ))}
      {!all && plan.more.length ? (
        <Pressable testID="details-more" accessibilityRole="button" onPress={() => setAll(true)} style={[s.groupHead, s.groupLine, { borderColor: th.border }]}>
          <Text style={[s.groupMore, { color: th.textMuted }]}>{t('recs.brief.moreGroups', { n: plan.more.length })}</Text>
          <ChevronDown size={18} color={th.textMuted} strokeWidth={2} />
        </Pressable>
      ) : null}
    </View>
  );
}

function GroupRow({
  group,
  first,
  open,
  onToggle,
  onSeek,
  onAcceptName,
}: {
  group: DetailGroup;
  first: boolean;
  open: boolean;
  onToggle: () => void;
  onSeek?: (t: number) => void;
  onAcceptName?: (speaker: string, name: string) => void;
}) {
  const t = useT();
  const th = useTheme();
  const label = group.count != null ? `${group.title} · ${group.count}` : group.title;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <View style={first ? null : [s.groupLine, { borderColor: th.border }]}>
      <Pressable
        testID={`group-${group.key}`}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={t(open ? 'recs.map.collapseNode' : 'recs.map.expandNode', { name: label })}
        onPress={onToggle}
        style={s.groupHead}>
        <Text testID={`section-${group.key}`} style={[s.groupTitle, { color: th.text }]}>
          {label}
        </Text>
        <Chevron size={18} color={th.textMuted} strokeWidth={2} />
      </Pressable>
      {open ? (
        <View testID={`group-body-${group.key}`} style={s.groupBody}>
          <SectionBody section={group.section} onSeek={onSeek} onAcceptName={onAcceptName} />
        </View>
      ) : null}
    </View>
  );
}

function SectionBody({
  section,
  onSeek,
  onAcceptName,
}: {
  section: SectionView;
  onSeek?: (t: number) => void;
  onAcceptName?: (speaker: string, name: string) => void;
}) {
  return (
    <>
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
    </>
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

/** Band matni chapdan qancha ichkarida (• + oraliq) - chip, tafsilot va CRM shu chiziqda. */
const BULLET_INSET = 16;

const s = StyleSheet.create({
  tabs: { marginBottom: 10, flexGrow: 0 },
  item: { paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth },
  itemText: { fontSize: 15, lineHeight: 21 },
  sub: { fontSize: 13, lineHeight: 18, marginTop: 2 },
  quote: { fontSize: 13, fontStyle: 'italic', marginTop: 4, paddingLeft: 8, borderLeftWidth: 2 },
  provenance: { fontSize: 12, marginTop: 2, marginBottom: 6 },
  flex: { flex: 1 },
  bold: { fontWeight: '700' },
  brief: { borderRadius: radius.lg, borderWidth: 1, padding: 16, marginBottom: 14, gap: 4 },
  briefHead: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 },
  briefTitle: { fontSize: 17, lineHeight: 23, fontWeight: '700' },
  briefText: { fontSize: 15, lineHeight: 22 },
  briefGap: { marginTop: 10 },
  bullet: { flexDirection: 'row', gap: 8, paddingLeft: 2 },
  briefTime: { paddingTop: 4, fontVariant: ['tabular-nums'] },
  briefActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  briefChevron: { paddingTop: 3 },
  briefInset: { marginLeft: BULLET_INSET },
  briefDetails: { marginTop: 2, marginBottom: 4 },
  details: { marginTop: 4, marginBottom: 8, marginLeft: 4 },
  groups: { borderRadius: radius.lg, borderWidth: 1, paddingHorizontal: 14, marginBottom: 14 },
  groupLine: { borderTopWidth: StyleSheet.hairlineWidth },
  groupHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 48, paddingVertical: 12, gap: 8 },
  groupTitle: { flex: 1, fontSize: 15, lineHeight: 21, fontWeight: '600' },
  groupMore: { flex: 1, fontSize: 14, lineHeight: 20 },
  groupBody: { paddingBottom: 8 },
});
