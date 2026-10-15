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
 *  - har bir dalil (`Ev.start`) bosilsa audio va transkript o'sha joyga o'tadi;
 *  - server birlashtirgan fakt (`alsoIn`) va kuzatish sababi (`followUps`) - o'z bandida chip.
 *
 * "Har fakt BIR marta" (egasi, 2026-10-15): ekranda "Qisqa xulosa" kartasi, ostida "Batafsil" -
 * faqat kartada YO'Q narsalar, yig'iq guruhlar (`detailGroups`), eng pastda bitta jim qator
 * (`summaryMetaParts`: kayfiyat, kalit so'zlar, faollik, model).
 */
import type { AlsoIn, Lang, Speaker, Summary, SummaryContent, TemplateSection } from '@/api/types';
import type { TFn, TKey } from '@/i18n';

import { meetingTier, type MeetingTier } from './brief';
import { formatClock, formatDay, formatDue } from './formatDate';
import { engineLabel } from './provenance';
import { renderTokens, resolveSpeakerId, speakerLabel } from './renderTokens';

export type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'info' | 'accent';

export interface ChipView {
  label: string;
  tone: Tone;
  /**
   * `alsoIn` - fakt yana qaysi bo'limda edi (server birlashtirgan); `followUp` - nima uchun
   * kuzatish kerak. Kartada band yig'iq turganda ham faqat shu chiplar ko'rinadi.
   */
  kind?: 'alsoIn' | 'followUp';
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
  /**
   * Kartadagi band ochilganda ko'rinadigan qatorlar, agar `sub` dan farq qilsa: vazifada mas'ul va
   * muddat karta matnining o'zida (jonli ro'yxatdan) - eskirgan nusxasi takrorlanmasin.
   */
  more?: string[];
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
  /**
   * Har band `bo'lim/id` bo'yicha (ichki bandlar ham: `topics/T1.2`) - "Qisqa xulosa" kartasi o'z
   * qatoriga chip va tafsilotni shundan oladi. Karta bo'limlari `layout` da bo'lmasa ham bor.
   */
  index: Map<string, ItemView>;
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

/** Karta bandlari shu bo'limlardan - `index` da doim bo'lsin (layout'da yo'q bo'lsa ham). */
const CARD_KEYS = ['keyPoints', 'topics', 'decisions', 'actionItems', 'openQuestions'] as const;

/** `followUps[].reasons` -> chip (ilova tilida). Noma'lum kod ko'rsatilmaydi (u matn emas). */
const REASON_KEYS: Record<string, TKey> = {
  no_answer: 'sum.reason.no_answer',
  no_owner: 'sum.reason.no_owner',
  deferred: 'sum.reason.deferred',
  tentative: 'sum.reason.tentative',
  conditional: 'sum.reason.conditional',
  no_due: 'sum.reason.no_due',
  no_mitigation: 'sum.reason.no_mitigation',
};

/** Bir xil yozuvli chip bir marta (server ham bo'lim nomini takrorlamaydi - bu qo'shimcha himoya). */
function uniqueChips(chips: ChipView[]): ChipView[] {
  const seen = new Set<string>();
  return chips.filter((c) => {
    const k = c.label.trim().toLocaleLowerCase();
    if (!k || seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/** `alsoIn` - neytral chiplar, yozuvi serverdan (xulosa tilida, birlik shaklda). */
function alsoInChips(x: { alsoIn?: AlsoIn[] | null }): ChipView[] {
  return (x.alsoIn ?? []).map((a) => ({ label: (a.label ?? '').trim(), tone: 'neutral' as const, kind: 'alsoIn' as const }));
}

/**
 * Kuzatish sabablari band id'si bo'yicha. Vazifa, qaror va ochiq savolga havola qilganlari
 * O'TKAZIB yuboriladi: ular kartada (mas'ul/muddat/shart, holat, "ochiq savol" - matnning o'zida),
 * server ham ularni olib tashlaydi. Eski xulosada ular hali bor - shu yerda ham tushadi.
 */
function followUpChips(c: SummaryContent, t: TFn): Map<string, ChipView[]> {
  const out = new Map<string, ChipView[]>();
  const inCard = new Set([...(c.actionItems ?? []), ...(c.decisions ?? []), ...(c.openQuestions ?? [])].map((x) => x.id));
  for (const f of c.followUps ?? []) {
    if (!f?.ref || inCard.has(f.ref) || f.kind === 'actionItem' || f.kind === 'decision' || f.kind === 'openQuestion') continue;
    const chips = (f.reasons ?? []).flatMap((r) => (REASON_KEYS[r] ? [{ label: t(REASON_KEYS[r]), tone: 'warn' as const, kind: 'followUp' as const }] : []));
    if (chips.length) out.set(f.ref, [...(out.get(f.ref) ?? []), ...chips]);
  }
  return out;
}

function item(p: Partial<ItemView> & { id: string; text: string }, merged?: { alsoIn?: AlsoIn[] | null }): ItemView {
  const it: ItemView = { sub: [], chips: [], quote: null, start: null, needsCheck: false, children: [], action: null, ...p };
  if (merged?.alsoIn?.length) it.chips = uniqueChips([...it.chips, ...alsoInChips(merged)]);
  return it;
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

  const ctx: Ctx = { t, R, who, whoList, lang, speakers };
  const sections: SectionView[] = [];
  const seen = new Set<string>();
  for (const key of order) {
    if (seen.has(key) || key === 'title' || key === 'quality') continue;
    seen.add(key);
    const s = buildSection(key, titleOf(key), c, ctx);
    if (s) sections.push(s);
  }
  // Karta bandlari uchun (layout'da yo'q bo'lsa ham) - faqat `index` ga, ekranga emas.
  const hidden = CARD_KEYS.filter((k) => !seen.has(k)).flatMap((k) => buildSection(k, titleOf(k), c, ctx) ?? []);

  const follow = followUpChips(c, t);
  const index = new Map<string, ItemView>();
  const visit = (key: string, it: ItemView) => {
    // Kuzatish sababi (ogohlantirish) - "yana qayerda" chiplaridan oldin.
    const extra = follow.get(it.id);
    if (extra) it.chips = uniqueChips([...it.chips.filter((x) => x.kind !== 'alsoIn'), ...extra, ...it.chips.filter((x) => x.kind === 'alsoIn')]);
    index.set(`${key}/${it.id}`, it);
    for (const ch of it.children) visit(key, ch);
  };
  for (const sec of [...sections, ...hidden]) for (const it of sec.items) visit(sec.key, it);

  const warnings: string[] = [];
  if (c.quality?.droppedItems > 0) warnings.push(t('sum.qualityWarn', { n: c.quality.droppedItems }));
  // Odam o'qiydigan ogohlantirish bo'lsa - tarjimasi; qolgan ichki kodlar avvalgidek.
  for (const w of c.quality?.warnings ?? []) warnings.push(w === 'key_points_missing' ? t('sum.warn.key_points_missing') : w);

  return { title: R(c.title) || '', language: lang, sections, warnings, index };
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
            children: tp.keyPoints.map((kp, i) => item({ id: `${tp.id}.${i + 1}`, text: R(kp.text), start: kp.start }, kp)),
          }),
        ),
      );

    case 'keyPoints':
      return itemsSection(key, title, c.keyPoints.map((k) => item({ id: k.id, text: R(k.text), start: k.start }, k)));

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
          }, d),
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
          // Mas'ul va muddat - kartadagi vazifa matnida bor; ochilganda faqat qolganlari (`more`).
          const more = [
            a.deliverable ? t('sum.deliverable', { what: R(a.deliverable) }) : '',
            a.assignedBy ? t('sum.assignedBy', { who: who(a.assignedBy) ?? a.assignedBy }) : '',
            a.dependsOn?.length ? t('sum.dependsOn', { ids: a.dependsOn.join(', ') }) : '',
          ].filter(Boolean);
          return item(
            {
              id: a.id,
              text: R(a.task),
              sub: [
                ownerName ? t('sum.owner', { owner: ownerName }) : t('sum.noOwner'),
                due ? t(a.due.basis === 'vague' ? 'sum.dueVague' : 'sum.due', { due }) : '',
                ...more,
              ].filter(Boolean),
              more,
              chips,
              quote: a.quote || null,
              start: a.start,
              needsCheck: needsCheck(a),
            },
            a,
          );
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
          }, q),
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
          }, r),
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
      return itemsSection(key, title, c.nextSteps.map((x) => item({ id: x.id, text: R(x.text), start: x.start }, x)));

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

    // "Hal qilinmagan masalalar" alohida bo'lim emas: sababi o'z bandida chip (`followUpChips`),
    // vazifa/qaror/savolniki esa kartada. NEGA: aks holda o'sha band ikkinchi marta o'qilardi.
    case 'followUps':
      return null;

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
          item(
            {
              id: `${key}.${i + 1}`,
              text: R(x.text),
              sub: x.speaker ? [who(x.speaker) ?? x.speaker] : [],
              start: x.start,
            },
            x,
          ),
        ),
      );
    }
  }
}

// --------------------------------------------------------------- "Batafsil" guruhlari

export interface DetailGroup {
  key: string;
  /** Bo'lim sarlavhasi (`layout` dan, xulosa tilida) - yig'iq qatorda "Sarlavha · son". */
  title: string;
  /** Bandlar soni (kartadagilarsiz); matnli bo'limda null - son ma'nosiz. */
  count: number | null;
  /** Ochilganda chiziladigan bo'lim - kartadagi bandlari olib tashlangan. */
  section: SectionView;
}

export interface DetailPlan {
  /** Darhol ko'rinadigan yig'iq qatorlar. */
  shown: DetailGroup[];
  /** "Yana N ta bo'lim" qatori ortidagilar (bosilsa ochiladi). */
  more: DetailGroup[];
}

export interface DetailOptions {
  /** Karta butunlay o'z ichiga olgan bo'limlar (`briefCovers`). */
  covered?: ReadonlySet<string>;
  /** Kartadagi bandlar `bo'lim/id` (`briefRefs`) - qolgan fikrlar, bekor qilingan qarorlar qoladi. */
  inCard?: ReadonlySet<string>;
  /** Yig'ilish uzunligi (`briefDurationSec`): guruhlar soni va mavzular o'rni shunga qarab. */
  durationSec?: number | null;
}

/** Guruh emas, eng pastdagi jim qator (`summaryMetaParts`). */
const META_KEYS = new Set(['keywords', 'sentiment']);

/** Darhol ko'rinadigan guruhlar: qisqa (va noma'lum) - 2, o'rta - 4, uzun - hammasi. */
const GROUP_BUDGET: Record<MeetingTier, number> = { short: 2, medium: 4, long: Infinity };

function withoutCard(it: ItemView, key: string, inCard: ReadonlySet<string>): ItemView | null {
  if (inCard.has(`${key}/${it.id}`)) return null;
  if (!it.children.some((ch) => inCard.has(`${key}/${ch.id}`))) return it;
  return { ...it, children: it.children.flatMap((ch) => withoutCard(ch, key, inCard) ?? []) };
}

/**
 * "Batafsil" - FAQAT kartada yo'q narsalar, har bo'lim bitta yig'iq qator ("Muhokama · 2").
 *
 * Qoidalar (egasi, 2026-10-15 - "har fakt bir marta"):
 *  - karta butunlay qamragan bo'lim yo'q (`covered`); qisman qamraganidan kartadagi bandlar
 *    olib tashlanadi (`inCard`): asosiy fikrlardan kartadagilari, qarorlardan - bekor
 *    qilinmaganlari. Bandi qolmagan bo'lim chiqmaydi;
 *  - kalit so'zlar va kayfiyat - pastdagi jim qatorda; ishtirokchilar ham (faollik), guruhi
 *    faqat tasdiqlanadigan taklif qilingan ism bo'lsa qoladi;
 *  - <= 15 daqiqa: mavzular (boblar) oxirida - qisqa suhbatda ular asosiy fikrlarni takrorlaydi;
 *  - ko'rinadigan guruhlar soni uzunlikka qarab (`GROUP_BUDGET`), qolgani "Yana N ta bo'lim"
 *    ortida. Ortda BITTA guruh qolsa - o'zi ko'rsatiladi: "Yana 1 ta bo'lim" qatori o'sha guruh
 *    qatori bilan bir xil joy oladi, faqat bir bosish ortiqcha bo'lardi.
 */
export function detailGroups(view: SummaryViewModel, opts: DetailOptions = {}): DetailPlan {
  const covered = opts.covered ?? new Set<string>();
  const inCard = opts.inCard ?? new Set<string>();
  const tier = meetingTier(opts.durationSec);
  let groups: DetailGroup[] = [];
  for (const sec of view.sections) {
    if (covered.has(sec.key) || META_KEYS.has(sec.key)) continue;
    if (sec.key === 'participants' && !sec.items.some((i) => i.action?.kind === 'acceptName')) continue;
    const items = sec.items.flatMap((it) => withoutCard(it, sec.key, inCard) ?? []).filter((it) => it.text.trim());
    if (sec.kind === 'items' && !items.length) continue;
    const count = sec.kind === 'items' ? items.length : sec.kind === 'tags' ? sec.tags.length : null;
    groups.push({ key: sec.key, title: sec.title, count, section: { ...sec, items } });
  }
  if (tier === 'short') groups = [...groups.filter((g) => g.key !== 'topics'), ...groups.filter((g) => g.key === 'topics')];
  const budget = GROUP_BUDGET[tier ?? 'short'];
  if (groups.length <= budget + 1) return { shown: groups, more: [] };
  return { shown: groups.slice(0, budget), more: groups.slice(budget) };
}

/**
 * Xulosa ostidagi BITTA jim qator (alohida kartalar o'rniga): "Kayfiyat: neytral · Kalit so'zlar:
 * LLM, Gemini · Faollik: 1-ishtirokchi 52%, 2-ishtirokchi 31% · Tayyorladi: Gemma". Bor qismlar
 * xolos. Yorliqlar ilova tilida, ismlar va kalit so'zlar - xulosa tilida (bo'limlardagidek).
 * Faollik - kamida 2 kishining ulushi ma'lum bo'lsa (bitta odam "100%" - ma'lumot emas);
 * birlashtirilgan spiker qabul qilganiga qo'shiladi.
 */
export function summaryMetaParts(
  summary: Pick<Summary, 'generatedBy' | 'content' | 'speakers' | 'language'>,
  t: TFn,
  speakersOverride?: Speaker[],
): string[] {
  const c = summary.content;
  const parts: string[] = [];
  if (c) {
    const lang: Lang = c.language ?? summary.language;
    const speakers = speakersOverride ?? summary.speakers ?? [];
    if (c.sentiment?.overall) parts.push(t('sum.meta.sentiment', { value: t(`sum.sentiment.${c.sentiment.overall}` as TKey).toLocaleLowerCase() }));
    const keywords = (c.keywords ?? []).map((k) => k.trim()).filter(Boolean);
    if (keywords.length) parts.push(t('sum.meta.keywords', { value: keywords.join(', ') }));
    const share = new Map<string, number>();
    for (const p of c.participants ?? []) {
      if (!p?.speaker || !(p.talkShare > 0)) continue;
      const id = resolveSpeakerId(p.speaker, speakers);
      share.set(id, (share.get(id) ?? 0) + p.talkShare);
    }
    if (share.size >= 2) {
      const value = [...share].map(([id, x]) => `${speakerLabel(id, speakers, lang)} ${Math.round(x * 100)}%`).join(', ');
      parts.push(t('sum.meta.talk', { value }));
    }
  }
  const engine = engineLabel(summary.generatedBy);
  if (engine) parts.push(t('sum.generatedBy', { engine }));
  return parts;
}

// --------------------------------------------------------------- text export

export interface TextOptions {
  header?: string[];
  includeQuotes?: boolean;
  /**
   * "Qisqa xulosa" matni (`briefToText`). Berilsa matn shu bilan boshlanadi - sarlavha va sana
   * unda bor, `title`/`header` takrorlanmaydi; bo'limlar esa faqat kartada yo'qlari bo'lsin.
   */
  brief?: string | null;
  /** Oxirgi qatorlar (pastdagi jim qator). */
  footer?: string[];
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
export function summaryToText(view: Pick<SummaryViewModel, 'title' | 'sections'>, t: TFn, opts: TextOptions = {}): string {
  const out: string[] = [];
  if (opts.brief?.trim()) {
    out.push(opts.brief.trimEnd());
  } else {
    if (view.title) out.push(view.title);
    if (opts.header?.length) out.push(...opts.header);
  }
  for (const s of view.sections) {
    out.push('', `## ${s.title}`);
    if (s.kind === 'text' && s.text) out.push(s.text);
    else if (s.kind === 'tags') out.push(s.tags.join(', '));
    else for (const it of s.items) out.push(...itemLines(it, t, '', opts.includeQuotes ?? true));
  }
  if (opts.footer?.length) out.push('', ...opts.footer);
  return out.join('\n').trim() + '\n';
}

/** Qisqa yordamchi: xulosa ichidagi sanani ko'rsatish (`meeting.date`). */
export function meetingDateLabel(c: SummaryContent): string {
  return formatDay(c.meeting.date, c.language);
}
