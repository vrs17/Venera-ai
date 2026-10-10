/**
 * "Qisqa xulosa" - rahbar/hamkasbga bir qarashda yuboriladigan qisqa blok
 * (mahsulot egasi 2026-10-10 da tasdiqlagan format):
 *
 *   **Sarlavha**
 *   10-oktabr 2026 (shanba), 12:37 · 1 daq 53 s · 2 ishtirokchi
 *   **Maqsad:** ...            (purpose)
 *   **Qisqacha:** ...          (overview, ko'pi 2 gap)
 *   **Asosiy fikrlar:** - ...  (keyPoints, ko'pi 6 ta)
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

/** Asosiy fikrlar 3-6 ta (prompt qoidasi); model ko'p bersa ham blok qisqa qoladi. */
export const MAX_KEY_POINTS = 6;
/** "Qisqacha" - ko'pi 2 gap (eski xulosalarda umumiy xulosa 3-5 gap edi). */
export const MAX_OVERVIEW_SENTENCES = 2;

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
  const dur = durationWords(meeting.durationSec ?? content.meeting?.durationSec, lang);
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
  let points: BriefItem[] = (content.keyPoints ?? []).map((k) => ({ text: withDot(R(k.text)), start: k.start }));
  if (!points.length) points = (content.topics ?? []).flatMap((tp) => tp.keyPoints.map((k) => ({ text: withDot(R(k.text)), start: k.start })));
  if (!points.length) points = (content.topics ?? []).map((tp) => ({ text: withDot(R(tp.summary) || R(tp.title)), start: tp.start }));
  push('keyPoints', 'recs.brief.keyPoint', 'recs.brief.keyPoints', points.slice(0, MAX_KEY_POINTS));

  // Bekor qilingan qaror endi qaror emas - qisqa blokda chalg'itadi. Yakuniy bo'lmagani va
  // tasdiqlanmagani belgilanadi (bitta qavsda, nuqtadan oldin): tasdiqlanmagan band HECH
  // QACHON tasdiqlangandek ketmaydi.
  push(
    'decisions',
    'recs.brief.decision',
    'recs.brief.decisions',
    (content.decisions ?? [])
      .filter((d) => d.status !== 'reversed')
      .map((d) => {
        const status = d.status === 'tentative' || d.status === 'conditional' ? tr(lang, `recs.brief.${d.status}`) : '';
        const tags = [status, needsCheck(d) ? checkWord : ''].filter(Boolean);
        const text = R(d.text);
        return { text: text && tags.length ? `${text.replace(TRAIL, '')} (${tags.join(', ')}).` : withDot(text), start: d.start };
      }),
  );

  push(
    'actionItems',
    'recs.brief.task',
    'recs.brief.tasks',
    tasksOf(content, opts.actions).map((a) => {
      const base = R(a.task);
      if (!base) return { text: '', start: a.start };
      const cond = R(a.condition);
      const task = withDot(cond ? `${base} (${tr(lang, 'recs.brief.condition', { text: cond })})` : base);
      const bySpeaker = a.ownerSpeaker ? speakerLabel(a.ownerSpeaker, speakers, lang) : null;
      const byName = a.ownerName?.trim() || null;
      const owner = (a.nameFirst ? byName ?? bySpeaker : bySpeaker ?? byName) ?? (a.ownerKind === 'team' ? tr(lang, 'recs.brief.team') : null);
      const due = formatDue(a.due.date, a.due.time, a.due.raw, lang);
      const ownerPart = owner ? tr(lang, 'recs.brief.owner', { owner }) : tr(lang, 'recs.brief.noOwner');
      const duePart = due ? tr(lang, 'recs.brief.due', { due }) : tr(lang, 'recs.brief.noDue');
      return { text: `${a.done ? '✓ ' : ''}${task} ${ownerPart}. ${duePart}.${a.check ? ` (${checkWord})` : ''}`, start: a.start };
    }),
  );

  push(
    'openQuestions',
    'recs.brief.question',
    'recs.brief.questions',
    (content.openQuestions ?? []).map((q) => ({ text: withQuestionMark(R(q.text)), start: q.start })),
  );

  const purposeText = R(content.purpose);
  const overviewText = firstSentences(R(content.overview));
  const purpose = purposeText ? { label: tr(lang, 'recs.brief.purpose'), text: withDot(purposeText) } : null;
  const overview = overviewText ? { label: tr(lang, 'recs.brief.overview'), text: withDot(overviewText) } : null;
  if (!purpose && !overview && !lists.length) return null;
  return { language: lang, title, meta: meta.join(' · '), purpose, overview, lists };
}

export type BriefCovered = 'overview' | 'keyPoints' | 'openQuestions';

/**
 * To'liq xulosaning qaysi bo'limlarini "Qisqa xulosa" TO'LIQ takrorlaydi (server
 * `export.brief_covers` bilan bir xil qoida): umumiy xulosa (qisqartirilmagan bo'lsa),
 * asosiy fikrlar (hammasi sig'gan bo'lsa) va ochiq savollar (blokda hammasi bor). NEGA:
 * qisqa qo'ng'iroqda "Batafsil" ostida xuddi shu matn ikkinchi marta chiqardi. Qarorlar va
 * vazifalar bo'limi (holat, mas'ul, CRM, belgilash) doim qoladi.
 */
export function briefCovers(content: SummaryContent | null | undefined, speakers: Speaker[] = []): Set<BriefCovered> {
  const covered = new Set<BriefCovered>(['openQuestions']);
  if (!content) return covered;
  const overview = renderTokens(content.overview, speakers, content.language).replace(/\s+/g, ' ').trim();
  if (!overview || firstSentences(overview) === overview) covered.add('overview');
  const points = (content.keyPoints ?? []).filter((k) => k.text);
  if (points.length && points.length <= MAX_KEY_POINTS) covered.add('keyPoints');
  return covered;
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
