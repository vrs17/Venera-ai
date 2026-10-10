/**
 * Xulosadan "aqliy xarita" (Plaud kabi): ildiz - sarlavha; shoxlar - mavzular
 * (ichida fikrlari), qarorlar, vazifalar (mas'ul va muddat bilan), ochiq savollar.
 *
 * NIMA UCHUN React'siz: daraxt va uning joylashuvi (chapdan o'ngga) sof hisob -
 * ustma-ust tushmaslik, yig'ish/ochish va matn o'rash Jest'da to'liq tekshiriladi;
 * SVG va ro'yxat ko'rinishi (MindMap*.tsx) faqat shu natijani chizadi.
 *
 * Til qisqa xulosa (`brief.ts`) bilan bir xil: daraxt TO'LIQ XULOSA tilida (shox yorliqlari,
 * "Muddat:", "Jamoa" ham) - tugunda ilova tilidagi yorliq va xulosa tilidagi matn aralashmasin.
 * Faqat asboblar paneli (kattalik, "Ro'yxat") - ilova tilida.
 *
 * Telefonda chizish (`MindMapCanvas`): xarita BITTA katta SVG emas - plitkalarga bo'linadi va
 * faqat ko'rinib turgan atrofidagilari chiziladi (`canvasTiles`/`visibleTiles`). NIMA UCHUN:
 * react-native-svg Android'da butun ko'rinish o'lchamida bitta bitmap ajratadi; 10 mavzuli
 * yig'ilish xaritasi 100% da ~120 MB bo'lib, Android "too large bitmap" bilan ilovani yiqitardi.
 */
import type { ActionItem, Lang, Speaker, SummaryContent } from '@/api/types';
import { translate, type TKey } from '@/i18n';

import { summaryTitle, type BriefMeeting } from './brief';
import { formatClock, formatDue } from './formatDate';
import { renderTokens, speakerLabel } from './renderTokens';

export type MindKind = 'root' | 'topic' | 'group' | 'point' | 'decision' | 'action' | 'question';
export type MindTone = 'neutral' | 'info' | 'accent' | 'good' | 'warn' | 'bad';

export interface MindNode {
  id: string;
  kind: MindKind;
  label: string;
  /** Qo'shimcha qator (vazifa: mas'ul · muddat). */
  meta: string | null;
  /** Bosilsa pleer/transkript shu soniyaga o'tadi; null - o'tadigan joy yo'q. */
  start: number | null;
  /** Shox rangi (mavzu tokeni) - butun shox bir rangda, ko'z shoxni kuzatsin. */
  tone: MindTone;
  children: MindNode[];
}

/**
 * Mavzular navbat bilan shu ranglarda. Qarorlar (yashil), vazifalar (accent) va ochiq savollar
 * (sariq) ranglari mavzuga BERILMAYDI - aks holda 3-mavzu "Qarorlar"ga o'xshab qolardi;
 * "xavf" qizili ham yo'q (xavotir uyg'otadi).
 */
const TOPIC_TONES: MindTone[] = ['info', 'neutral'];

function node(p: Partial<MindNode> & Pick<MindNode, 'id' | 'kind' | 'label' | 'tone'>): MindNode {
  return { meta: null, start: null, children: [], ...p };
}

/** Bola bilan qayta rang berish: shoxning hamma bo'g'ini ildizdagi rangda. */
function paint(n: MindNode, tone: MindTone): MindNode {
  return { ...n, tone, children: n.children.map((c) => paint(c, tone)) };
}

export interface MindMapOptions {
  meeting?: BriefMeeting;
  speakers?: Speaker[];
  /** Asosiy xulosa uchun jonli vazifalar (tahrirlangan/qo'shilgan) - qisqa xulosa bilan bir xil. */
  actions?: ActionItem[] | null;
}

/** Xulosadan daraxt; ko'rsatadigan shox bo'lmasa `null` (bo'sh holat). */
export function buildMindMap(content: SummaryContent | null | undefined, opts: MindMapOptions = {}): MindNode | null {
  if (!content) return null;
  const lang: Lang = content.language;
  const speakers = opts.speakers ?? [];
  const R = (s: string | null | undefined) => renderTokens(s, speakers, lang).replace(/\s+/g, ' ').trim();
  const branches: MindNode[] = [];

  const topics = content.topics ?? [];
  topics.forEach((tp, i) => {
    const label = R(tp.title);
    if (!label) return;
    branches.push(
      paint(
        node({
          id: `topic:${tp.id}`,
          kind: 'topic',
          label,
          start: tp.start ?? null,
          tone: 'info',
          children: tp.keyPoints
            .map((kp, j) => node({ id: `topic:${tp.id}:${j + 1}`, kind: 'point', label: R(kp.text), start: kp.start, tone: 'info' }))
            .filter((c) => c.label),
        }),
        TOPIC_TONES[i % TOPIC_TONES.length],
      ),
    );
  });

  const group = (key: string, tone: MindTone, children: MindNode[]) => {
    const kids = children.filter((c) => c.label);
    if (!kids.length) return;
    // Guruh - faqat yig'ish/ochish uchun; o'zining vaqti yo'q.
    const label = translate(lang, `recs.brief.${key}` as TKey);
    branches.push(paint(node({ id: `group:${key}`, kind: 'group', label, tone, children: kids }), tone));
  };

  // Mavzu ichida fikrlar bo'lsa umumiy "Asosiy fikrlar" ularni takrorlaydi; mavzu yoki
  // ularning fikrlari bo'lmasa (qisqa qo'ng'iroq) - asosiy fikrlar alohida shox.
  const topicPoints = branches.some((b) => b.kind === 'topic' && b.children.length > 0);
  if (!topicPoints) {
    group(
      'keyPoints',
      'info',
      (content.keyPoints ?? []).map((k) => node({ id: `kp:${k.id}`, kind: 'point', label: R(k.text), start: k.start, tone: 'info' })),
    );
  }

  group(
    'decisions',
    'good',
    (content.decisions ?? [])
      .filter((d) => d.status !== 'reversed')
      .map((d) => node({ id: `dec:${d.id}`, kind: 'decision', label: R(d.text), start: d.start, tone: 'good' })),
  );

  const team = translate(lang, 'recs.brief.team');
  // Muddat yorlig'i bilan ("Muddat: 10-oktabr"): yonidagi audio vaqti (▶ 00:09) muddat soati
  // deb o'qilmasin.
  const taskNode = (id: string, task: string, owner: string | null, due: string | null, start: number | null) =>
    node({
      id: `act:${id}`,
      kind: 'action',
      label: R(task),
      meta: [owner, due ? translate(lang, 'recs.brief.due', { due }) : null].filter(Boolean).join(' · ') || null,
      start,
      tone: 'accent',
    });
  group(
    'tasks',
    'accent',
    opts.actions
      ? opts.actions
          .filter((i) => i.status !== 'dismissed')
          .map((i) =>
            taskNode(
              i.id,
              i.task,
              // Jonli vazifada odam yozgan ism ustun (qisqa xulosa va server eksporti kabi).
              i.owner.name?.trim() || (i.owner.speaker ? speakerLabel(i.owner.speaker, speakers, lang) : null) || (i.owner.kind === 'team' ? team : null),
              formatDue(i.due.date, i.due.time, i.due.raw, lang),
              i.start,
            ),
          )
      : (content.actionItems ?? []).map((a) =>
          taskNode(
            a.id,
            a.task,
            (a.owner.speaker ? speakerLabel(a.owner.speaker, speakers, lang) : null) || a.owner.name?.trim() || (a.owner.kind === 'team' ? team : null),
            formatDue(a.due.date, a.due.time, a.due.raw, lang),
            a.start,
          ),
        ),
  );

  group(
    'questions',
    'warn',
    (content.openQuestions ?? []).map((q) => node({ id: `q:${q.id}`, kind: 'question', label: R(q.text), start: q.start, tone: 'warn' })),
  );

  if (!branches.length) return null;
  const title = summaryTitle(content, opts.meeting ?? {}, speakers);
  return node({ id: 'root', kind: 'root', label: title || '-', tone: 'neutral', children: branches });
}

// ------------------------------------------------------------------ layout

export interface MindMetrics {
  /** Tugun eni chuqurlik bo'yicha (oxirgisi qolganlarga). */
  widths: readonly number[];
  fontSize: readonly number[];
  lineH: readonly number[];
  metaSize: number;
  metaLineH: number;
  padX: number;
  padY: number;
  /** Ustunlar orasi (bog'lovchi chiziq uchun joy). */
  hGap: number;
  /** Qo'shni tugunlar orasi. */
  vGap: number;
  margin: number;
  maxLines: number;
  /** O'rtacha harf eni / shrift o'lchami. SVG matnni o'zi o'ramaydi - shuning uchun taxmin. */
  charW: number;
  /** Yig'ish tugmasi radiusi (tugun o'ng chetida). */
  knob: number;
}

export const MIND_METRICS: MindMetrics = {
  widths: [168, 184, 216],
  fontSize: [16, 14, 13],
  lineH: [21, 19, 18],
  metaSize: 11,
  metaLineH: 16,
  padX: 12,
  padY: 9,
  hGap: 48,
  vGap: 10,
  margin: 16,
  maxLines: 5,
  // Kirill harflari lotindan kengroq - 0.6 bilan matn to'rtburchakdan chiqmaydi.
  charW: 0.6,
  knob: 9,
};

const at = <T,>(arr: readonly T[], i: number): T => arr[Math.min(i, arr.length - 1)];

/** 2-pog'onadan chuqur tugunlarda chapda rangli chiziq - matn shuncha o'ngga suriladi. */
export const BAR_INSET = 4;

/**
 * So'zlab o'rash: `maxChars` dan uzun qator yo'q; `maxLines` dan oshsa oxirgi qator
 * "..." bilan tugaydi. Juda uzun so'z (havola) bo'linadi.
 */
export function wrapText(text: string, maxChars: number, maxLines: number): string[] {
  const width = Math.max(4, Math.floor(maxChars));
  const lines: string[] = [];
  let cur = '';
  for (let w of text.split(/\s+/).filter(Boolean)) {
    while (w.length > width) {
      if (cur) {
        lines.push(cur);
        cur = '';
      }
      lines.push(w.slice(0, width));
      w = w.slice(width);
    }
    if (!w) continue;
    if (!cur) cur = w;
    else if (cur.length + 1 + w.length <= width) cur = `${cur} ${w}`;
    else {
      lines.push(cur);
      cur = w;
    }
  }
  if (cur) lines.push(cur);
  if (!lines.length) return [''];
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, Math.max(1, maxLines));
  const last = kept[kept.length - 1];
  kept[kept.length - 1] = `${last.length + 3 > width ? last.slice(0, width - 3).trimEnd() : last}...`;
  return kept;
}

export interface LaidNode {
  id: string;
  kind: MindKind;
  tone: MindTone;
  label: string;
  start: number | null;
  depth: number;
  x: number;
  y: number;
  w: number;
  h: number;
  lines: string[];
  /** Mas'ul/muddat va audio vaqti (`2-ishtirokchi · Muddat: 10-oktabr · ▶ 00:09`), ko'pi 2 qator. */
  metaLines: string[];
  fontSize: number;
  lineH: number;
  childCount: number;
  collapsed: boolean;
}

export interface LaidEdge {
  id: string;
  from: string;
  to: string;
  d: string;
  tone: MindTone;
}

export interface MindLayout {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
}

interface Measured {
  n: MindNode;
  depth: number;
  lines: string[];
  metaLines: string[];
  w: number;
  h: number;
  kids: Measured[];
  /** Butun ko'rinadigan shox balandligi. */
  sh: number;
}

/** Tugundagi kichik qator: vazifa uchun mas'ul/muddat, dalil bo'lsa audio vaqti (▶ belgisi bilan). */
export function metaLineOf(n: Pick<MindNode, 'meta' | 'start' | 'kind'>): string | null {
  const parts = [n.meta, n.kind !== 'root' && n.start != null ? `▶ ${formatClock(n.start)}` : null].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}

/**
 * Tugun bosilganda nima bo'ladi - xarita va ro'yxatda BIR XIL: mavzu va guruh shoxlari (1-pog'ona,
 * bolasi bor) - yig'iladi/ochiladi (Plaud kabi: xarita yig'iq ochiladi); bandlar - yozuv o'sha
 * joydan eshitiladi. NIMA UCHUN: avval bir xil ko'rinadigan shoxning biri eshittirar, biri
 * ochardi - qaysi biri nima qilishini oldindan bilib bo'lmasdi.
 */
export function pressAction(n: { kind: MindKind; start: number | null }, childCount: number): 'toggle' | 'seek' | null {
  if ((n.kind === 'topic' || n.kind === 'group') && childCount > 0) return 'toggle';
  if (n.start != null) return 'seek';
  return n.kind !== 'root' && childCount > 0 ? 'toggle' : null;
}

/**
 * Chapdan o'ngga daraxt: ustun = chuqurlik; har shox o'z bolalari ustida o'rtada.
 * `collapsed` dagi tugunlarning bolalari chizilmaydi (balandlik ham qisqaradi).
 */
export function layoutMindMap(root: MindNode, collapsed: ReadonlySet<string> = new Set(), m: MindMetrics = MIND_METRICS): MindLayout {
  const measure = (n: MindNode, depth: number): Measured => {
    const w = at(m.widths, depth);
    const fontSize = at(m.fontSize, depth);
    const inner = w - m.padX * 2 - (depth >= 2 ? BAR_INSET : 0);
    const lines = wrapText(n.label, inner / (fontSize * m.charW), m.maxLines);
    const metaLine = metaLineOf(n);
    // Vaqt qatorning oxirida - kesilib qolmasin, shuning uchun 2 qatorgacha.
    const metaLines = metaLine ? wrapText(metaLine, inner / (m.metaSize * m.charW), 2) : [];
    const h = m.padY * 2 + lines.length * at(m.lineH, depth) + metaLines.length * m.metaLineH;
    const kids = depth > 0 && collapsed.has(n.id) ? [] : n.children.map((c) => measure(c, depth + 1));
    const block = kids.reduce((s, k) => s + k.sh, 0) + Math.max(0, kids.length - 1) * m.vGap;
    return { n, depth, lines, metaLines, w, h, kids, sh: Math.max(h, block) };
  };

  const tree = measure(root, 0);
  const xs: number[] = [m.margin];
  const xOf = (depth: number) => {
    while (xs.length <= depth) xs.push(xs[xs.length - 1] + at(m.widths, xs.length - 1) + m.hGap);
    return xs[depth];
  };

  const nodes: LaidNode[] = [];
  const edges: LaidEdge[] = [];
  const place = (t: Measured, top: number, parent: LaidNode | null) => {
    const self: LaidNode = {
      id: t.n.id,
      kind: t.n.kind,
      tone: t.n.tone,
      label: t.n.label,
      start: t.n.start,
      depth: t.depth,
      x: xOf(t.depth),
      y: top + (t.sh - t.h) / 2,
      w: t.w,
      h: t.h,
      lines: t.lines,
      metaLines: t.metaLines,
      fontSize: at(m.fontSize, t.depth),
      lineH: at(m.lineH, t.depth),
      childCount: t.n.children.length,
      collapsed: t.depth > 0 && t.n.children.length > 0 && collapsed.has(t.n.id),
    };
    nodes.push(self);
    if (parent) {
      const x1 = parent.x + parent.w;
      const y1 = parent.y + parent.h / 2;
      const x2 = self.x;
      const y2 = self.y + self.h / 2;
      const mx = (x1 + x2) / 2;
      edges.push({ id: `${parent.id}>${self.id}`, from: parent.id, to: self.id, tone: self.tone, d: `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}` });
    }
    const block = t.kids.reduce((s, k) => s + k.sh, 0) + Math.max(0, t.kids.length - 1) * m.vGap;
    let cursor = top + (t.sh - block) / 2;
    for (const k of t.kids) {
      place(k, cursor, self);
      cursor += k.sh + m.vGap;
    }
  };
  place(tree, m.margin, null);

  // O'ng chetda yig'ish tugmasi va yashirin bolalar soni uchun joy.
  const right = Math.max(...nodes.map((n) => n.x + n.w + (n.childCount ? m.knob * 2 + 22 : 0)));
  return { nodes, edges, width: Math.ceil(right + m.margin), height: Math.ceil(tree.sh + m.margin * 2) };
}

// ------------------------------------------------------------------ canvas tiles

/** Kattalik pog'onalari; ekranga moslari `fitZoom` bilan tanlanadi. */
export const ZOOM_STEPS = [0.5, 0.65, 0.8, 1, 1.25, 1.5, 1.8] as const;

/**
 * Boshlang'ich kattalik: 100% dan oshmagan va xarita (yig'iq holatda - ildiz va shoxlar)
 * ekran eniga sig'adigan eng katta pog'ona; hech biri sig'masa - eng kichigi.
 */
export function fitZoom(layoutWidth: number, viewWidth: number): number {
  const one = ZOOM_STEPS.indexOf(1);
  if (!(viewWidth > 0) || !(layoutWidth > 0)) return one;
  for (let i = one; i >= 0; i--) if (layoutWidth * ZOOM_STEPS[i] <= viewWidth) return i;
  return 0;
}

/**
 * Bitta SVG plitkaning eni/bo'yi, FIZIK piksel: 1024 x 1024 x 4 bayt = 4 MB bitmap. Android
 * bitmap'ni 100 MB dan katta bo'lsa chizmaydi (ilova yiqiladi) - plitka shunchalik kichik
 * bo'lgani uchun xarita qancha katta bo'lmasin, bitta bitmap 4 MB dan oshmaydi.
 */
export const TILE_PX = 1024;
/** Plitka bitmap'ining eng katta hajmi (bayt) - test shu chegarani har kattalikda tekshiradi. */
export const TILE_MAX_BYTES = TILE_PX * TILE_PX * 4;

export interface CanvasTile {
  key: string;
  /** Xarita koordinatalarida (layout birligi, kattalikdan oldin). */
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Xaritani plitkalarga bo'lish. Plitka tomoni `TILE_PX / (pixelRatio * scale)` layout birligi -
 * ekranda aynan `TILE_PX` piksel; chegaralar butun pikselga tushadi (plitkalar orasida tirqish
 * qolmaydi).
 */
export function canvasTiles(size: Pick<MindLayout, 'width' | 'height'>, scale: number, pixelRatio: number): CanvasTile[] {
  const step = TILE_PX / (Math.max(1, pixelRatio) * Math.max(0.01, scale));
  const cols = Math.max(1, Math.ceil(size.width / step));
  const rows = Math.max(1, Math.ceil(size.height / step));
  const tiles: CanvasTile[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = c * step;
      const y = r * step;
      tiles.push({ key: `${c}:${r}`, x, y, w: Math.min(step, size.width - x), h: Math.min(step, size.height - y) });
    }
  }
  return tiles;
}

/** Plitka bitmap'i hajmi (bayt): react-native-svg ko'rinish o'lchamida ARGB_8888 ajratadi. */
export function tileBytes(tile: CanvasTile, scale: number, pixelRatio: number): number {
  return 4 * Math.ceil(tile.w * scale * pixelRatio) * Math.ceil(tile.h * scale * pixelRatio);
}

export interface Viewport {
  /** Aylantirish joyi va ko'rinadigan o'lcham, dp (kattalikdan keyin). */
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Chiziladigan plitkalar: ko'rinib turgan oyna va zahira - tepa/pastda yarim ekran (asosiy
 * aylantirish vertikal - tez aylantirganda bo'sh joy ko'rinmasin), yon tomonlarda chorak ekran.
 * Qolganlari umuman yo'q - xotira ekran o'lchamiga bog'liq, xarita o'lchamiga emas.
 */
export function visibleTiles(tiles: CanvasTile[], scale: number, view: Viewport, margin: { x: number; y: number } = { x: 0.25, y: 0.5 }): CanvasTile[] {
  const x0 = view.x - view.w * margin.x;
  const x1 = view.x + view.w * (1 + margin.x);
  const y0 = view.y - view.h * margin.y;
  const y1 = view.y + view.h * (1 + margin.y);
  return tiles.filter((t) => t.x * scale < x1 && (t.x + t.w) * scale > x0 && t.y * scale < y1 && (t.y + t.h) * scale > y0);
}

/** Yig'ish tugmasining ko'rinmas nishoni (radius) - plitkaga tegishini hisoblash uchun ham. */
export const KNOB_HIT = 18;

export interface TileContent {
  edges: LaidEdge[];
  /** `home` - tugunning markazi shu plitkada: testID va ekran o'quvchi yorlig'i faqat shu nusxada. */
  nodes: { node: LaidNode; home: boolean }[];
  knobs: { node: LaidNode; home: boolean }[];
}

const inside = (t: CanvasTile, x: number, y: number) => x >= t.x && x < t.x + t.w && y >= t.y && y < t.y + t.h;
const overlaps = (t: CanvasTile, x0: number, y0: number, x1: number, y1: number) => x0 < t.x + t.w && x1 > t.x && y0 < t.y + t.h && y1 > t.y;

/**
 * Plitkaga tushadigan bo'laklar. Chegarada turgan tugun ikkala plitkada ham chiziladi (har biri
 * o'z qismini ko'rsatadi, ikkalasi ham bosiladi), lekin `home` faqat bittasida.
 */
export function tileContent(layout: MindLayout, tile: CanvasTile, m: MindMetrics = MIND_METRICS): TileContent {
  const byId = new Map(layout.nodes.map((n) => [n.id, n]));
  const edges = layout.edges.filter((e) => {
    const from = byId.get(e.from);
    const to = byId.get(e.to);
    if (!from || !to) return false;
    const ya = from.y + from.h / 2;
    const yb = to.y + to.h / 2;
    return overlaps(tile, from.x + from.w, Math.min(ya, yb) - 2, to.x, Math.max(ya, yb) + 2);
  });
  const nodes = layout.nodes
    .filter((n) => overlaps(tile, n.x, n.y, n.x + n.w, n.y + n.h))
    .map((n) => ({ node: n, home: inside(tile, n.x + n.w / 2, n.y + n.h / 2) }));
  const knobs = layout.nodes
    .filter((n) => n.depth > 0 && n.childCount > 0)
    .filter((n) => {
      const cx = n.x + n.w;
      const cy = n.y + n.h / 2;
      return overlaps(tile, cx - KNOB_HIT, cy - KNOB_HIT, cx + m.knob + 4 + 22, cy + KNOB_HIT);
    })
    .map((n) => ({ node: n, home: inside(tile, n.x + n.w, n.y + n.h / 2) }));
  return { edges, nodes, knobs };
}

/** Yig'iladigan tugunlar (ildizdan tashqari, bolasi bor) - "Hammasini yig'ish" uchun. */
export function collapsibleIds(root: MindNode): string[] {
  const out: string[] = [];
  const walk = (n: MindNode, depth: number) => {
    if (depth > 0 && n.children.length) out.push(n.id);
    n.children.forEach((c) => walk(c, depth + 1));
  };
  walk(root, 0);
  return out;
}

export interface OutlineRow {
  node: MindNode;
  depth: number;
  collapsed: boolean;
}

/** Ro'yxat ko'rinishi (tor ekran, TalkBack): ildizsiz, yig'ilganlarning bolalarisiz. */
export function outlineRows(root: MindNode, collapsed: ReadonlySet<string> = new Set()): OutlineRow[] {
  const rows: OutlineRow[] = [];
  const walk = (n: MindNode, depth: number) => {
    const isCollapsed = n.children.length > 0 && collapsed.has(n.id);
    rows.push({ node: n, depth, collapsed: isCollapsed });
    if (!isCollapsed) n.children.forEach((c) => walk(c, depth + 1));
  };
  root.children.forEach((c) => walk(c, 1));
  return rows;
}

/** Xarita bo'yicha qidirish (testlar va ekran o'quvchi yorlig'i uchun). */
export function findNode(root: MindNode, id: string): MindNode | null {
  if (root.id === id) return root;
  for (const c of root.children) {
    const hit = findNode(c, id);
    if (hit) return hit;
  }
  return null;
}
