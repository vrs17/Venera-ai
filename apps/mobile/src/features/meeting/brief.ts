/**
 * "Qisqa xulosa" - rahbar/hamkasbga bir qarashda yuboriladigan qisqa blok
 * (mahsulot egasi 2026-10-10 da tasdiqlagan format):
 *
 *   **Sarlavha**
 *   10-oktabr 2026 (shanba), 12:37 · 1 daq 53 s · 2 ishtirokchi
 *   **Maqsad:** ...            (purpose)
 *   **Qisqacha:** ...          (overview, BITTA gap)
 *   **Asosiy fikrlar:** - ...  (keyPoints, 3/4/5 ta - yig'ilish uzunligiga qarab)
 *   **Qarorlar:** - ...        (faqat bo'lsa)
 *   **Vazifa(lar):** - Ish. Mas'ul: X. Muddat: Y.
 *   **Ochiq savol(lar):** - ...
 *
 * NIMA UCHUN alohida, React'siz qatlam: kartada ko'rinadigan matn, "Nusxa olish"
 * va "Ulashish" AYNAN bir xil bo'lishi kerak - mantiq bitta joyda va Jest'da
 * to'liq tekshiriladi.
 *
 * Til: blok TO'LIQ XULOSA tilida - yorliqlar, meta qatori, "Mas'ul/Muddat" iboralari va
 * spiker nomlari ("2-ishtirokchi") ham. NEGA: blok rahbarga yuboriladi; ilova tilida yorliq
 * va xulosa tilidagi matn bitta qatorda aralashib ("Ответственный: 2-ishtirokchi") o'qilmasdi.
 * Faqat karta "ramkasi" (sarlavha "Qisqa xulosa", "Nusxa olish", "Ulashish") - ilova tilida.
 *
 * Server eksporti (`export.brief_block`) AYNAN shu matnni beradi: umumiy namuna
 * `packages/fixtures/meeting-brief.json` ni jest ham (`briefGolden.test.ts`), pytest ham tekshiradi.
 *
 * "Har fakt BIR marta" (egasi, 2026-10-15): karta - xulosaning o'zi, "Batafsil" faqat kartada
 * YO'Q narsalar. NEGA qisqaroq: 8,5 daqiqalik yig'ilish 16 ekran bo'lardi - bitta fakt 7 joyda.
 */
import type { ActionItem, Lang, Meeting, OwnerKind, Speaker, SummaryContent } from '@/api/types';
import { translate, type TKey, type TParams } from '@/i18n';

import { formatDay, formatDue, tashkentParts } from './formatDate';
import { renderTokens, speakerLabel, visibleSpeakers } from './renderTokens';

export type BriefListKey = 'keyPoints' | 'decisions' | 'actionItems' | 'openQuestions';

export interface BriefItem {
  text: string;
  /** Dalil: audio/transkriptda shu soniya. */
  start: number | null;
  /**
   * To'liq xulosadagi manba band: bo'lim va id (`keyPoints`/K1, `topics`/T1.2, `decisions`/D1,
   * `actionItems`/A1, `openQuestions`/Q1). Kartada band chiplari va ochiladigan tafsilot shundan,
   * "Batafsil" esa kartadagi bandni qayta ko'rsatmaydi. Ulashiladigan matnga TA'SIR QILMAYDI.
   * null - manbasi yo'q (odam qo'shgan jonli vazifa).
   */
  source?: { section: string; id: string } | null;
  /** Jonli vazifa id'si (asosiy xulosa) - kartadagi CRM tugmasi shu vazifaniki. */
  liveId?: string | null;
}

export interface BriefList {
  key: BriefListKey;
  /** "Vazifa" / "Vazifalar" - bitta band bo'lsa birlik (egasi bergan namunadagidek). */
  label: string;
  items: BriefItem[];
}

export interface BriefLine {
  label: string;
  text: string;
}

export interface Brief {
  /** Blok tili (= xulosa tili). */
  language: Lang;
  title: string;
  /** `10-oktabr 2026 (shanba), 12:37 · 1 daq 53 s · 2 ishtirokchi`; hech narsa ma'lum bo'lmasa ''. */
  meta: string;
  purpose: BriefLine | null;
  overview: BriefLine | null;
  lists: BriefList[];
}

export type BriefMeeting = Partial<Pick<Meeting, 'title' | 'titleSource' | 'recordedAt' | 'durationSec'>>;

export interface BriefOptions {
  /**
   * Asosiy xulosa uchun JONLI vazifalar (Vazifalar tabi: odam tahrirlagani, qo'shgani,
   * bajarilgani). Berilsa xulosadagi vazifalar o'rniga shular - server eksporti kabi.
   */
  actions?: ActionItem[] | null;
}

/**
 * "Qisqacha" - BITTA gap (egasi, 2026-10-15: "xulosa qisqa bo'lishi kerak"). To'liq umumiy
 * xulosa uzunroq bo'lsa - "Batafsil" ostida yig'iq qatorda qoladi (`briefCovers`).
 */
export const MAX_OVERVIEW_SENTENCES = 1;

/** Yig'ilish uzunligi: <= 15 daq - qisqa, <= 45 daq - o'rta, undan uzun - uzun. */
export type MeetingTier = 'short' | 'medium' | 'long';

/** Davomiylik noma'lum (0, null, NaN) - `null`: qoidalar uni qisqa yig'ilishdek ko'radi. */
export function meetingTier(durationSec: number | null | undefined): MeetingTier | null {
  if (durationSec == null || !Number.isFinite(durationSec) || durationSec <= 0) return null;
  if (durationSec <= 15 * 60) return 'short';
  if (durationSec <= 45 * 60) return 'medium';
  return 'long';
}

const POINTS: Record<MeetingTier, number> = { short: 3, medium: 4, long: 5 };

/**
 * Kartadagi asosiy fikrlar soni: <= 15 daq - 3, <= 45 daq - 4, uzunroq - 5 (noma'lum - 3).
 * Server `export.brief_points` bilan bir xil. NEGA uzunlikka qarab: 2 daqiqalik qo'ng'iroqda
 * 6 ta fikr - aslida 2-3 fakt qayta aytilgani; soatlik yig'ilishda 3 ta - kam. Qolgan fikrlar
 * "Batafsil" ostida (`keyPoints` guruhi).
 */
export function briefPointCount(durationSec: number | null | undefined): number {
  return POINTS[meetingTier(durationSec) ?? 'short'];
}

/** Qoidalar uchun davomiylik: yozuvniki ustun, bo'lmasa xulosadagi (meta qatori kabi). */
export function briefDurationSec(content: Pick<SummaryContent, 'meeting'> | null | undefined, meeting: BriefMeeting = {}): number | null {
  return meeting.durationSec ?? content?.meeting?.durationSec ?? null;
}

/** Hafta kunlari - serverdagi `dates.WEEKDAYS` bilan bir xil (dushanbadan). */
const WEEKDAYS: Record<Lang, string[]> = {
  uz: ['dushanba', 'seshanba', 'chorshanba', 'payshanba', 'juma', 'shanba', 'yakshanba'],
  ru: ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'],
  en: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
};

const pad = (n: number) => String(n).padStart(2, '0');

function tr(lang: Lang, key: TKey, params?: TParams): string {
  return translate(lang, key, params);
}

/** Ruscha ko'plik: 1 участник, 2 участника, 5 участников; uz - o'zgarmaydi; en - 1/ko'p. */
export function pluralForm(n: number, lang: Lang): 'one' | 'few' | 'many' {
  if (lang === 'ru') {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return 'one';
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'few';
    return 'many';
  }
  return n === 1 ? 'one' : 'many';
}

/** `1 soat 5 daq` / `1 daq 53 s` / `45 s` (soat bo'lsa soniya kerak emas - shovqin). */
export function durationWords(sec: number | null | undefined, lang: Lang): string {
  if (sec == null || !Number.isFinite(sec) || sec <= 0) return '';
  const total = Math.max(1, Math.round(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const parts: string[] = [];
  if (h > 0) {
    parts.push(tr(lang, 'recs.brief.hours', { n: h }));
    if (m > 0) parts.push(tr(lang, 'recs.brief.minutes', { n: m }));
  } else if (m > 0) {
    parts.push(tr(lang, 'recs.brief.minutes', { n: m }));
    if (s > 0) parts.push(tr(lang, 'recs.brief.seconds', { n: s }));
  } else {
    parts.push(tr(lang, 'recs.brief.seconds', { n: s }));
  }
  return parts.join(' ');
}

/**
 * `10-oktabr 2026 (shanba), 12:37` | `10 октября 2026 (суббота), 12:37` |
 * `October 10, 2026 (Saturday), 12:37`. Vaqt Toshkent bo'yicha (formatDate qoidasi).
 * `recordedAt` bo'lmasa - xulosadagi sana (vaqtsiz).
 */
export function briefDate(recordedAt: string | null | undefined, fallbackIsoDate: string | null | undefined, lang: Lang): string {
  const p = recordedAt ? tashkentParts(recordedAt) : null;
  let iso: string | null = null;
  let time = '';
  if (p) {
    iso = `${p.year}-${pad(p.month)}-${pad(p.day)}`;
    time = `${pad(p.hour)}:${pad(p.minute)}`;
  } else if (fallbackIsoDate && /^\d{4}-\d{2}-\d{2}$/.test(fallbackIsoDate)) {
    iso = fallbackIsoDate;
  }
  if (!iso) return '';
  const [y, mo, d] = iso.split('-').map(Number);
  // JS: 0 = yakshanba; jadval dushanbadan boshlanadi.
  const weekday = WEEKDAYS[lang][(new Date(Date.UTC(y, mo - 1, d)).getUTCDay() + 6) % 7];
  const day = formatDay(iso, lang);
  const date = lang === 'en' ? `${day}, ${y}` : `${day} ${y}`;
  return `${date} (${weekday})${time ? `, ${time}` : ''}`;
}

/**
 * Gap chegarasi: `.!?…`, bo'shliq, keyin BOSH harf, raqam yoki qo'shtirnoq (server
 * `export._SENTENCE_END` bilan bir xil). NIMA UCHUN bosh harf sharti: "15 mln. so'm" yoki
 * "1.2 versiya" gapni bo'lmasin. Lookbehind'siz - eski Hermes'da ham ishlasin.
 */
const SENTENCE_END = /[.!?…]\s+(?=[[«"„“'(0-9A-ZА-ЯЁЎҚҒҲ])/g;

/** Matnning birinchi `limit` gapi; qisqasi o'zgarmaydi. */
export function firstSentences(text: string, limit = MAX_OVERVIEW_SENTENCES): string {
  const x = text.replace(/\s+/g, ' ').trim();
  const re = new RegExp(SENTENCE_END.source, 'g');
  let count = 0;
  for (let m = re.exec(x); m; m = re.exec(x)) {
    count += 1;
    if (count >= limit) return x.slice(0, m.index + 1);
  }
  return x;
}

/** Oxiriga nuqta (savol/undov bo'lsa tegmaydi); oxiridagi `;:,` olib tashlanadi. */
function withDot(s: string): string {
  const x = trimEnd(s);
  if (!x) return x;
  return /[.!?…]$/.test(x) ? x : `${x}.`;
}

function withQuestionMark(s: string): string {
  const x = trimEnd(s);
  if (!x) return x;
  return /[.!?…]$/.test(x) ? x : `${x}?`;
}

function trimEnd(s: string): string {
  return s.trim().replace(/[\s;:,]+$/, '');
}

/** Qarorga holat qo'shishda oxiridagi tinish belgilari (server `export._TRAIL`). */
const TRAIL = /[\s.;:,!?…]+$/;

function needsCheck(x: { needsConfirmation?: boolean; verified?: boolean | null }): boolean {
  return !!x.needsConfirmation || x.verified === false;
}

/**
 * Blok sarlavhasi: foydalanuvchi qo'ygan nom - ustun; aks holda xulosa sarlavhasi
 * (avtomatik "Yig'ilish 9-oktabr, 11:00" dan aniqroq), u ham bo'lmasa yozuv nomi.
 */
export function summaryTitle(content: Pick<SummaryContent, 'title' | 'language'>, meeting: BriefMeeting, speakers: Speaker[] = []): string {
  const own = meeting.titleSource === 'user' ? meeting.title?.trim() : '';
  return own || renderTokens(content.title, speakers, content.language).trim() || meeting.title?.trim() || '';
}

/** Vazifa qatorining manbasi: xulosadagi band yoki jonli vazifa - bitta ko'rinish. */
interface TaskSource {
  task: string;
  /** Shartli majburiyat ("agar mijoz rozi bo'lsa") - shartsizdek o'qilmasin (server kabi). */
  condition: string | null;
  ownerSpeaker: string | null;
  ownerName: string | null;
  ownerKind: OwnerKind;
  /** Jonli vazifada odam yozgan ism ustun (server `actions_from_rows` kabi). */
  nameFirst: boolean;
  due: { date: string | null; time: string | null; raw: string | null };
  done: boolean;
  check: boolean;
  start: number | null;
  /** Xulosadagi vazifa id'si (A1): jonli vazifada `summaryItemId` (odam qo'shganida null). */
  id: string | null;
  liveId: string | null;
}

function tasksOf(content: SummaryContent, live: ActionItem[] | null | undefined): TaskSource[] {
  if (live) {
    return live
      .filter((i) => i.status !== 'dismissed')
      .map((i) => ({
        task: i.task,
        condition: null,
        ownerSpeaker: i.owner.speaker,
        ownerName: i.owner.name,
        ownerKind: i.owner.kind,
        nameFirst: true,
        due: i.due,
        done: i.status === 'done',
        check: i.needsConfirmation,
        start: i.start,
        id: i.summaryItemId,
        liveId: i.id,
      }));
  }
  return (content.actionItems ?? []).map((a) => ({
    task: a.task,
    condition: a.condition ?? null,
    ownerSpeaker: a.owner.speaker,
    ownerName: a.owner.name,
    ownerKind: a.owner.kind,
    nameFirst: false,
    due: a.due,
    done: a.status === 'done_in_meeting',
    check: needsCheck(a),
    start: a.start,
    id: a.id,
    liveId: null,
  }));
}

/**
 * Qisqa xulosa. `null` - ko'rsatadigan mazmun yo'q (sarlavha va meta o'zi blok emas).
 * `speakers` - sahifadagi yangiroq ro'yxat (nomlash/birlashtirishdan keyin).
 */
export function buildBrief(
  content: SummaryContent | null | undefined,
  meeting: BriefMeeting = {},
  speakers: Speaker[] = [],
  opts: BriefOptions = {},
): Brief | null {
  if (!content) return null;
  const lang: Lang = content.language;
  const R = (s: string | null | undefined) => renderTokens(s, speakers, lang).replace(/\s+/g, ' ').trim();
  const checkWord = tr(lang, 'recs.brief.check');

  const title = summaryTitle(content, meeting, speakers);

  // ---- meta qatori
  const meta: string[] = [];
  const date = briefDate(meeting.recordedAt, content.meeting?.date, lang);
  if (date) meta.push(date);
  const dur = durationWords(briefDurationSec(content, meeting), lang);
  if (dur) meta.push(dur);
  // Spikerlar ajratilmagan bo'lsa (router rejimi) son yolg'on bo'lardi - yozilmaydi.
  if (content.quality?.speakersAvailable !== false) {
    const visible = visibleSpeakers(speakers).length;
    const people = visible > 0 ? visible : (content.meeting?.speakerCount ?? 0);
    if (people > 0) meta.push(tr(lang, `recs.brief.people.${pluralForm(people, lang)}` as TKey, { n: people }));
  }

  // ---- ro'yxatlar
  const lists: BriefList[] = [];
  const push = (key: BriefListKey, one: TKey, many: TKey, items: BriefItem[]) => {
    const clean = items.filter((i) => i.text);
    if (clean.length) lists.push({ key, label: tr(lang, clean.length === 1 ? one : many), items: clean });
  };

  // Asosiy fikrlar har bir shablonda bo'lishi kerak; eski/qisqa xulosada bo'sh bo'lsa -
  // mavzular ichidagi fikrlar, ular ham bo'lmasa mavzularning o'zi (qo'shimcha himoya).
  // `source` id'lari `summaryModel` bandlarining id'si bilan bir xil (mavzu fikri - `T1.2`).
  const src = (section: string, id: string) => ({ section, id });
  // Server kabi: matnsiz band zaxiraga o'tishda ham, sanoqda ham hisobga olinmaydi.
  let points: BriefItem[] = (content.keyPoints ?? [])
    .filter((k) => k.text)
    .map((k) => ({ text: withDot(R(k.text)), start: k.start, source: src('keyPoints', k.id) }));
  if (!points.length) {
    points = (content.topics ?? []).flatMap((tp) =>
      tp.keyPoints.flatMap((k, i) => (k.text ? [{ text: withDot(R(k.text)), start: k.start, source: src('topics', `${tp.id}.${i + 1}`) }] : [])),
    );
  }
  if (!points.length) {
    points = (content.topics ?? []).map((tp) => ({ text: withDot(R(tp.summary) || R(tp.title)), start: tp.start, source: src('topics', tp.id) }));
  }
  points = points.filter((p) => p.text).slice(0, briefPointCount(briefDurationSec(content, meeting)));
  push('keyPoints', 'recs.brief.keyPoint', 'recs.brief.keyPoints', points);

  // Bekor qilingan qaror endi qaror emas - qisqa blokda chalg'itadi (u "Batafsil" da qoladi).
  // Yakuniy bo'lmagani, sharti va tasdiqlanmagani belgilanadi (BITTA qavsda, nuqtadan oldin):
  // tasdiqlanmagan band HECH QACHON tasdiqlangandek ketmaydi. Shart vazifadagidek "shart: X";
  // sharti yozilgan shartli qarorda "shartli" so'zi tushadi - "(shartli, shart: X)" ikki marta
  // aytardi. Karta qarorning to'liq bo'limi o'rnida - shart kartaning o'zida ko'rinsin.
  push(
    'decisions',
    'recs.brief.decision',
    'recs.brief.decisions',
    (content.decisions ?? [])
      .filter((d) => d.status !== 'reversed')
      .map((d) => {
        const cond = R(d.condition);
        const showStatus = d.status === 'tentative' || (d.status === 'conditional' && !cond);
        const status = showStatus ? tr(lang, `recs.brief.${d.status}` as TKey) : '';
        const tags = [status, cond ? tr(lang, 'recs.brief.condition', { text: cond }) : '', needsCheck(d) ? checkWord : ''].filter(Boolean);
        const text = R(d.text);
        return {
          text: text && tags.length ? `${text.replace(TRAIL, '')} (${tags.join(', ')}).` : withDot(text),
          start: d.start,
          source: src('decisions', d.id),
        };
      }),
  );

  push(
    'actionItems',
    'recs.brief.task',
    'recs.brief.tasks',
    tasksOf(content, opts.actions).map((a) => {
      const base = R(a.task);
      if (!base) return { text: '', start: a.start };
      const ref = { source: a.id ? src('actionItems', a.id) : null, liveId: a.liveId };
      const cond = R(a.condition);
      const task = withDot(cond ? `${base} (${tr(lang, 'recs.brief.condition', { text: cond })})` : base);
      const bySpeaker = a.ownerSpeaker ? speakerLabel(a.ownerSpeaker, speakers, lang) : null;
      const byName = a.ownerName?.trim() || null;
      const owner = (a.nameFirst ? byName ?? bySpeaker : bySpeaker ?? byName) ?? (a.ownerKind === 'team' ? tr(lang, 'recs.brief.team') : null);
      const due = formatDue(a.due.date, a.due.time, a.due.raw, lang);
      const ownerPart = owner ? tr(lang, 'recs.brief.owner', { owner }) : tr(lang, 'recs.brief.noOwner');
      const duePart = due ? tr(lang, 'recs.brief.due', { due }) : tr(lang, 'recs.brief.noDue');
      return { text: `${a.done ? '✓ ' : ''}${task} ${ownerPart}. ${duePart}.${a.check ? ` (${checkWord})` : ''}`, start: a.start, ...ref };
    }),
  );

  push(
    'openQuestions',
    'recs.brief.question',
    'recs.brief.questions',
    (content.openQuestions ?? []).map((q) => ({ text: withQuestionMark(R(q.text)), start: q.start, source: src('openQuestions', q.id) })),
  );

  const purposeText = R(content.purpose);
  const overviewText = firstSentences(R(content.overview));
  const purpose = purposeText ? { label: tr(lang, 'recs.brief.purpose'), text: withDot(purposeText) } : null;
  const overview = overviewText ? { label: tr(lang, 'recs.brief.overview'), text: withDot(overviewText) } : null;
  if (!purpose && !overview && !lists.length) return null;
  return { language: lang, title, meta: meta.join(' · '), purpose, overview, lists };
}

export type BriefCovered = 'overview' | 'purpose' | 'actionItems' | 'openQuestions' | 'followUps';

/**
 * To'liq xulosaning qaysi bo'limlarini "Qisqa xulosa" kartasi BUTUNLAY o'z ichiga oladi - ular
 * "Batafsil" ostida qayta chiqmaydi (egasi, 2026-10-15: "har fakt bir marta"). Server
 * `export.brief_covers` bilan bir xil qoida:
 *  - maqsad, qarorlar, vazifalar, ochiq savollar - kartada (qaror va vazifa bosilsa tafsiloti
 *    ochiladi, vazifada CRM tugmasi ham shu yerda); `followUps` - o'z bandida chip;
 *  - umumiy xulosa - faqat BITTA gap bo'lsa (yoki bo'sh); uzunrog'i yig'iq qatorda qoladi.
 *
 * Bo'lim butunlay emas, BANDMA-BAND kartada bo'lganlari: asosiy fikrlar (kartada birinchi
 * `briefPointCount` tasi, qolgani "Batafsil" da) va bekor qilingan qarorlar (kartada yo'q -
 * "Batafsil" da qoladi). Ular `BriefItem.source` orqali chiqariladi, bu ro'yxatga kirmaydi.
 */
export function briefCovers(content: SummaryContent | null | undefined, speakers: Speaker[] = []): Set<BriefCovered> {
  const covered = new Set<BriefCovered>(['purpose', 'actionItems', 'openQuestions', 'followUps']);
  if (!content) return covered;
  const overview = renderTokens(content.overview, speakers, content.language).replace(/\s+/g, ' ').trim();
  if (!overview || firstSentences(overview) === overview) covered.add('overview');
  return covered;
}

/** Kartadagi bandlar (`bo'lim/id`) - "Batafsil" ularni qayta ko'rsatmaydi. */
export function briefRefs(b: Brief | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const l of b?.lists ?? []) for (const i of l.items) if (i.source) out.add(`${i.source.section}/${i.source.id}`);
  return out;
}

function render(b: Brief, markdown: boolean): string {
  const bold = (s: string) => (markdown ? `**${s}**` : s);
  const head: string[] = [];
  // Markdown: sarlavha va meta bitta paragrafda, majburiy qator uzilishi (`  `) bilan.
  if (b.title) head.push(bold(b.title) + (markdown && b.meta ? '  ' : ''));
  if (b.meta) head.push(b.meta);
  const blocks: string[] = [];
  if (head.length) blocks.push(head.join('\n'));
  for (const line of [b.purpose, b.overview]) if (line) blocks.push(`${bold(`${line.label}:`)} ${line.text}`);
  for (const l of b.lists) blocks.push([bold(`${l.label}:`), ...l.items.map((i) => `- ${i.text}`)].join('\n'));
  return `${blocks.join('\n\n')}\n`;
}

/** Ulashish/nusxa uchun oddiy matn: messenjerlarda `**` belgilari ko'rinib qolmasin. */
export function briefToText(b: Brief): string {
  return render(b, false);
}

/** Markdown (`**qalin**` yorliqlar) - egasi bergan namunaning o'zi. */
export function briefToMarkdown(b: Brief): string {
  return render(b, true);
}
