/**
 * Xulosani ko'rsatish modeli: `Summary` (spec 6.2) -> bo'limlar ro'yxati.
 *
 * NIMA UCHUN alohida qatlam: ekran (SummaryView) va "matn sifatida
 * nusxalash/ulashish" AYNAN bir xil mazmunni ko'rsatishi kerak. Mantiq shu
 * yerda, React'siz - shuning uchun Jest'da to'liq tekshiriladi.
 *
 * Qoidalar (spec 6.2):
 *  - bo'limlar `layout` tartibida, sarlavhalar `layout` dan (xulosa tilida);
 *  - har bir matndagi `[S#]` ism bilan almashtiriladi (mergedInto hisobga olinadi);
 *  - `needsConfirmation` yoki `verified === false` -> "tekshiring" belgisi;
 *    tasdiqlanmagan band HECH QACHON tasdiqlangan vazifa sifatida ko'rsatilmaydi;
 *  - bo'sh bo'lim ko'rsatilmaydi;
 *  - har bir dalil (`Ev.start`) bosilsa audio va transkript o'sha joyga o'tadi.
 */
import type { Lang, Speaker, Summary, SummaryContent, TemplateSection } from '@/api/types';
import type { TFn, TKey } from '@/i18n';

import { formatClock, formatDay, formatDue } from './formatDate';
import { renderTokens, speakerLabel } from './renderTokens';

export type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'info' | 'accent';

export interface ChipView {
  label: string;
  tone: Tone;
}

export interface ItemAction {
  kind: 'acceptName';
  speaker: string;
  name: string;
}

export interface ItemView {
  id: string;
  text: string;
  sub: string[];
  chips: ChipView[];
  quote: string | null;
  /** Dalil: audio/transkriptda shu soniyaga o'tish. */
  start: number | null;
  /** "tekshiring" belgisi. */
  needsCheck: boolean;
  children: ItemView[];
  action: ItemAction | null;
}

export type SectionKind = 'text' | 'items' | 'tags';

export interface SectionView {
  key: string;
  title: string;
  kind: SectionKind;
  text: string | null;
  items: ItemView[];
  tags: string[];
}

export interface SummaryViewModel {
  title: string;
  language: Lang;
  sections: SectionView[];
  warnings: string[];
}

/** Layout bo'lmasa (eski server / xato) - asosiy bo'limlar shu tartibda. */
export const DEFAULT_ORDER = [
  'overview',
  'purpose',
  'actionItems',
  'decisions',
  'topics',
  'keyPoints',
  'openQuestions',
  'risks',
  'numbers',
  'dates',
  'nextSteps',
  'nextMeeting',
  'highlights',
  'participants',
  'keywords',
  'sentiment',
  'followUpMessage',
] as const;

const SECTION_KEYS: Record<string, TKey> = {
  title: 'section.title',
  overview: 'section.overview',
  purpose: 'section.purpose',
  participants: 'section.participants',
  topics: 'section.topics',
  keyPoints: 'section.keyPoints',
  decisions: 'section.decisions',
  actionItems: 'section.actionItems',
  openQuestions: 'section.openQuestions',
  risks: 'section.risks',
  numbers: 'section.numbers',
  dates: 'section.dates',
  nextSteps: 'section.nextSteps',
  nextMeeting: 'section.nextMeeting',
  highlights: 'section.highlights',
  userMarks: 'section.userMarks',
  keywords: 'section.keywords',
  sentiment: 'section.sentiment',
  followUpMessage: 'section.followUpMessage',
};

function item(p: Partial<ItemView> & { id: string; text: string }): ItemView {
  return { sub: [], chips: [], quote: null, start: null, needsCheck: false, children: [], action: null, ...p };
}

function textSection(key: string, title: string, text: string | null): SectionView | null {
  if (!text || !text.trim()) return null;
  return { key, title, kind: 'text', text, items: [], tags: [] };
}

function itemsSection(key: string, title: string, items: ItemView[]): SectionView | null {
  if (!items.length) return null;
  return { key, title, kind: 'items', text: null, items, tags: [] };
}

export interface BuildOptions {
  /** Server javobidagi `summary.speakers` dan yangiroq bo'lsa (rename'dan keyin). */
  speakers?: Speaker[];
}

export function buildSummaryView(summary: Summary, t: TFn, opts: BuildOptions = {}): SummaryViewModel | null {
  const c = summary.content;
  if (!c) return null;
  const lang: Lang = c.language ?? summary.language;
  const speakers = opts.speakers ?? summary.speakers ?? [];
  const R = (s: string | null | undefined) => renderTokens(s, speakers, lang);
  const who = (id: string | null | undefined) => (id ? speakerLabel(id, speakers, lang) : null);
  const whoList = (ids: string[]) => ids.map((id) => speakerLabel(id, speakers, lang)).join(', ');

  const titles = new Map(summary.layout?.map((l) => [l.key, l.title]) ?? []);
  const titleOf = (key: string) => titles.get(key) || (SECTION_KEYS[key] ? t(SECTION_KEYS[key]) : key);

  const order: string[] = summary.layout?.length
    ? summary.layout.map((l) => l.key)
    : [...DEFAULT_ORDER, ...c.templateSections.map((s) => s.key)];

  const sections: SectionView[] = [];
  const seen = new Set<string>();
  for (const key of order) {
    if (seen.has(key) || key === 'title' || key === 'quality') continue;
    seen.add(key);
    const s = buildSection(key, titleOf(key), c, { t, R, who, whoList, lang, speakers });
    if (s) sections.push(s);
  }

  const warnings: string[] = [];
  if (c.quality?.droppedItems > 0) warnings.push(t('sum.qualityWarn', { n: c.quality.droppedItems }));
  for (const w of c.quality?.warnings ?? []) warnings.push(w);

  return { title: R(c.title) || '', language: lang, sections, warnings };
}

interface Ctx {
  t: TFn;
  R: (s: string | null | undefined) => string;
  who: (id: string | null | undefined) => string | null;
  whoList: (ids: string[]) => string;
  lang: Lang;
  speakers: Speaker[];
}

function needsCheck(x: { needsConfirmation?: boolean; verified?: boolean | null }): boolean {
  return !!x.needsConfirmation || x.verified === false;
}

function checkChips(x: { needsConfirmation?: boolean; verified?: boolean | null }, t: TFn): ChipView[] {
  if (needsCheck(x)) return [{ label: t('sum.check'), tone: 'warn' }];
  if (x.verified === true) return [{ label: t('sum.verified'), tone: 'good' }];
  return [];
}

function buildSection(key: string, title: string, c: SummaryContent, ctx: Ctx): SectionView | null {
  const { t, R, who, whoList, lang } = ctx;
  switch (key) {
    case 'overview':
      return textSection(key, title, R(c.overview));
    case 'purpose':
      return textSection(key, title, R(c.purpose));

    case 'participants':
      return itemsSection(
        key,
        title,
        c.participants.map((p) => {
          const sp = ctx.speakers.find((s) => s.id === p.speaker);
          const suggested = p.suggestedName && !sp?.name ? p.suggestedName : null;
          return item({
            id: p.speaker,
            text: who(p.speaker) ?? p.speaker,
            sub: [p.role ? R(p.role) : '', t('sum.talk', { share: Math.round((p.talkShare ?? 0) * 100), dur: formatClock(p.talkSec) })].filter(Boolean),
            chips: suggested ? [{ label: t('sum.suggested', { name: suggested }), tone: 'info' }] : [],
            action: suggested ? { kind: 'acceptName', speaker: p.speaker, name: suggested } : null,
          });
        }),
      );

    case 'topics':
      return itemsSection(
        key,
        title,
        c.topics.map((tp) =>
          item({
            id: tp.id,
            text: R(tp.title),
            sub: [R(tp.summary)].filter(Boolean),
            chips: [
              {
                label: t(`sum.outcome.${tp.outcome}` as TKey),
                tone: tp.outcome === 'decided' ? 'good' : tp.outcome === 'open' ? 'warn' : 'neutral',
              },
              { label: `${formatClock(tp.start)}-${formatClock(tp.end)}`, tone: 'neutral' },
            ],
            start: tp.start,
            children: tp.keyPoints.map((kp, i) => item({ id: `${tp.id}.${i + 1}`, text: R(kp.text), start: kp.start })),
          }),
        ),
      );

    case 'keyPoints':
      return itemsSection(key, title, c.keyPoints.map((k) => item({ id: k.id, text: R(k.text), start: k.start })));

    case 'decisions':
      return itemsSection(
        key,
        title,
        c.decisions.map((d) =>
          item({
            id: d.id,
            text: R(d.text),
            sub: [
              d.condition ? t('sum.condition', { text: R(d.condition) }) : '',
              d.rationale ? t('sum.rationale', { text: R(d.rationale) }) : '',
              d.proposedBy?.length ? t('sum.proposedBy', { who: whoList(d.proposedBy) }) : '',
              d.agreedBy?.length ? t('sum.agreedBy', { who: whoList(d.agreedBy) }) : '',
            ].filter(Boolean),
            chips: [
              {
                label: t(`sum.decision.${d.status}` as TKey),
                tone: d.status === 'final' ? 'good' : d.status === 'reversed' ? 'bad' : 'warn',
              },
              ...checkChips(d, t),
            ],
            quote: d.quote || null,
            start: d.start,
            needsCheck: needsCheck(d),
          }),
        ),
      );

    case 'actionItems':
      return itemsSection(
        key,
        title,
        c.actionItems.map((a) => {
          const ownerName =
            a.owner.speaker ? who(a.owner.speaker) : a.owner.name ? a.owner.name : a.owner.kind === 'team' ? t('sum.team') : null;
          const due = formatDue(a.due.date, a.due.time, a.due.raw, lang);
          const chips: ChipView[] = [];
          if (a.priority === 'high') chips.push({ label: t('sum.priority.high'), tone: 'bad' });
          if (a.status === 'done_in_meeting') chips.push({ label: t('sum.doneInMeeting'), tone: 'good' });
          if (a.origin === 'implicit_commitment') chips.push({ label: t('sum.implicit'), tone: 'info' });
          if (a.owner.basis === 'assigned_no_reply') chips.push({ label: t('sum.assignedNoReply'), tone: 'warn' });
          chips.push(...checkChips(a, t));
          return item({
            id: a.id,
            text: R(a.task),
            sub: [
              ownerName ? t('sum.owner', { owner: ownerName }) : t('sum.noOwner'),
              due ? t(a.due.basis === 'vague' ? 'sum.dueVague' : 'sum.due', { due }) : '',
              a.deliverable ? t('sum.deliverable', { what: R(a.deliverable) }) : '',
              a.assignedBy ? t('sum.assignedBy', { who: who(a.assignedBy) ?? a.assignedBy }) : '',
              a.dependsOn?.length ? t('sum.dependsOn', { ids: a.dependsOn.join(', ') }) : '',
            ].filter(Boolean),
            chips,
            quote: a.quote || null,
            start: a.start,
            needsCheck: needsCheck(a),
          });
        }),
      );

    case 'openQuestions':
      return itemsSection(
        key,
        title,
        c.openQuestions.map((q) =>
          item({
            id: q.id,
            text: R(q.text),
            sub: [
              q.raisedBy ? t('sum.raisedBy', { who: who(q.raisedBy) ?? q.raisedBy }) : '',
              q.directedTo ? t('sum.directedTo', { who: who(q.directedTo) ?? q.directedTo }) : '',
            ].filter(Boolean),
            chips: [{ label: t(`sum.whyOpen.${q.whyOpen}` as TKey), tone: 'warn' }],
            start: q.start,
          }),
        ),
      );

    case 'risks':
      return itemsSection(
        key,
        title,
        c.risks.map((r) =>
          item({
            id: r.id,
            text: R(r.text),
            sub: [
              r.raisedBy ? t('sum.raisedBy', { who: who(r.raisedBy) ?? r.raisedBy }) : '',
              r.mitigation ? t('sum.mitigation', { text: R(r.mitigation) }) : '',
            ].filter(Boolean),
            chips: [
              { label: t(`sum.risk.${r.kind}` as TKey), tone: r.kind === 'blocker' ? 'bad' : 'warn' },
              ...(r.severity ? [{ label: t(`sum.severity.${r.severity}` as TKey), tone: (r.severity === 'high' ? 'bad' : 'neutral') as Tone }] : []),
            ],
            start: r.start,
          }),
        ),
      );

    case 'numbers':
      return itemsSection(
        key,
        title,
        c.numbers.map((n) =>
          item({ id: n.id, text: `${n.value}${n.unit ? ` ${n.unit}` : ''} - ${R(n.what)}`, start: n.start }),
        ),
      );

    case 'dates':
      return itemsSection(
        key,
        title,
        c.dates.map((d) => {
          const when = formatDue(d.date, d.time, d.raw, lang) ?? d.raw;
          return item({
            id: d.id,
            text: `${when} - ${R(d.what)}`,
            sub: d.date && d.raw ? [`"${d.raw}"`] : [],
            start: d.start,
          });
        }),
      );

    case 'nextSteps':
      return itemsSection(key, title, c.nextSteps.map((x) => item({ id: x.id, text: R(x.text), start: x.start })));

    case 'nextMeeting': {
      const nm = c.nextMeeting;
      if (!nm) return null;
      const when = formatDue(nm.date, nm.time, nm.raw, lang);
      if (!when && !nm.agenda?.length) return null;
      return itemsSection(key, title, [
        item({
          id: 'nextMeeting',
          text: when ?? '-',
          sub: nm.agenda?.length ? [t('sum.agenda', { items: nm.agenda.map(R).join('; ') })] : [],
          start: nm.start,
        }),
      ]);
    }

    case 'highlights':
      return itemsSection(
        key,
        title,
        c.highlights.map((h) =>
          item({
            id: h.id,
            text: `"${h.quote}"`,
            sub: [h.speaker ? who(h.speaker) ?? '' : '', R(h.why)].filter(Boolean),
            chips: h.fromMark ? [{ label: t('sum.fromMark'), tone: 'accent' }] : [],
            start: h.start,
          }),
        ),
      );

    case 'userMarks':
      return itemsSection(
        key,
        title,
        c.userMarks.map((m) =>
          item({
            id: m.id,
            text: m.note ? `${formatClock(m.t)} - ${m.note}` : formatClock(m.t),
            chips: m.coveredBy.length ? [] : [{ label: t('sum.markUncovered'), tone: 'warn' }],
            start: m.t,
          }),
        ),
      );

    case 'keywords':
      if (!c.keywords?.length) return null;
      return { key, title, kind: 'tags', text: null, items: [], tags: c.keywords };

    case 'sentiment': {
      const s = c.sentiment;
      if (!s) return null;
      const label = t(`sum.sentiment.${s.overall}` as TKey);
      return { key, title, kind: 'text', text: s.note ? `${label}. ${R(s.note)}` : label, items: [], tags: [] };
    }

    case 'followUpMessage': {
      const f = c.followUpMessage;
      if (!f?.body) return null;
      const text = f.subject ? `${t('sum.subject', { subject: R(f.subject) })}\n\n${R(f.body)}` : R(f.body);
      return { key, title, kind: 'text', text, items: [], tags: [] };
    }

    default: {
      const ts: TemplateSection | undefined = c.templateSections.find((s) => s.key === key);
      if (!ts) return null;
      return itemsSection(
        key,
        title,
        ts.items.map((x, i) =>
          item({
            id: `${key}.${i + 1}`,
            text: R(x.text),
            sub: x.speaker ? [who(x.speaker) ?? x.speaker] : [],
            start: x.start,
          }),
        ),
      );
    }
  }
}

// --------------------------------------------------------------- text export

export interface TextOptions {
  header?: string[];
  includeQuotes?: boolean;
}

function itemLines(it: ItemView, t: TFn, indent: string, includeQuotes: boolean): string[] {
  const badge = it.needsCheck ? ` [${t('sum.check')}]` : '';
  const chips = it.chips.filter((c) => c.label !== t('sum.check')).map((c) => c.label);
  const head = `${indent}- ${it.text}${chips.length ? ` (${chips.join(', ')})` : ''}${badge}`;
  const lines = [head];
  for (const s of it.sub) lines.push(`${indent}  ${s}`);
  if (includeQuotes && it.quote) lines.push(`${indent}  > "${it.quote}"${it.start != null ? ` [${formatClock(it.start)}]` : ''}`);
  for (const ch of it.children) lines.push(...itemLines(ch, t, `${indent}  `, includeQuotes));
  return lines;
}

/** Nusxalash / Telegram'ga ulashish uchun oddiy matn (markdown bilan mos). */
export function summaryToText(view: SummaryViewModel, t: TFn, opts: TextOptions = {}): string {
  const out: string[] = [];
  if (view.title) out.push(view.title);
  if (opts.header?.length) out.push(...opts.header);
  for (const s of view.sections) {
    out.push('', `## ${s.title}`);
    if (s.kind === 'text' && s.text) out.push(s.text);
    else if (s.kind === 'tags') out.push(s.tags.join(', '));
    else for (const it of s.items) out.push(...itemLines(it, t, '', opts.includeQuotes ?? true));
  }
  return out.join('\n').trim() + '\n';
}

/** Qisqa yordamchi: xulosa ichidagi sanani ko'rsatish (`meeting.date`). */
export function meetingDateLabel(c: SummaryContent): string {
  return formatDay(c.meeting.date, c.language);
}
