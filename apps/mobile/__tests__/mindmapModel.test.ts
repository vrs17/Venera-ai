/**
 * Xarita modeli: xulosadan daraxt (shoxlar, rang, vaqt), chapdan o'ngga joylashuv
 * (ustma-ust tushmaydi, ota bolalar o'rtasida), yig'ish, matn o'rash, bosish qoidasi va
 * plitkalar (Android bitmap chegarasi - har kattalikda).
 */
import type { SummaryContent } from '@/api/types';
import {
  BAR_INSET,
  buildMindMap,
  canvasTiles,
  collapsibleIds,
  findNode,
  fitZoom,
  layoutMindMap,
  MIND_METRICS,
  outlineRows,
  pressAction,
  TILE_MAX_BYTES,
  TILE_PX,
  tileBytes,
  tileContent,
  visibleTiles,
  wrapText,
  ZOOM_STEPS,
  type LaidNode,
  type MindNode,
} from '@/features/meeting/mindmapModel';

import { actionItem, summary } from './fixtures/server';

const s = summary();
const content = s.content!;
const root = buildMindMap(content, { speakers: s.speakers, meeting: { title: "Yig'ilish 9-oktabr, 11:00", titleSource: 'auto' } })!;

describe('mind map tree', () => {
  it('root = title; branches = topics (with points), decisions, action items, open questions', () => {
    expect(root.label).toBe('Narxlar va hisobot');
    expect(root.children.map((c) => [c.id, c.label])).toEqual([
      ['topic:T1', 'Narxlar'],
      ['group:decisions', 'Qarorlar'],
      ['group:tasks', 'Vazifalar'],
      ['group:questions', 'Ochiq savollar'],
    ]);
    // Mavzuning fikrlari bor - umumiy "Asosiy fikrlar" shoxi takrorlanmaydi.
    expect(findNode(root, 'group:keyPoints')).toBeNull();
    expect(findNode(root, 'topic:T1')!.children.map((c) => [c.label, c.start])).toEqual([['Narx 15 mln', 4.3]]);
    expect(findNode(root, 'topic:T1')!.start).toBe(0);
  });

  it('action items carry owner and due; unknown owner is left out; groups have no time', () => {
    const tasks = findNode(root, 'group:tasks')!;
    expect(tasks.start).toBeNull();
    expect(tasks.children.map((c) => [c.label, c.meta, c.start])).toEqual([
      // Muddat yorlig'i bilan - yonidagi audio vaqti muddat soati deb o'qilmasin.
      ['Hisobotni yuborish', '2-ishtirokchi · Muddat: 10-oktabr', 9.5],
      ['Shartnomani tekshirish', 'Jamoa · Muddat: tez orada', 4.3],
    ]);
    expect(findNode(root, 'group:questions')!.children[0]).toMatchObject({ label: 'Yetkazib berish qachon?', start: 15.2, kind: 'question' });
  });

  it('a whole branch shares one tone; topics alternate tones that the semantic groups do not use', () => {
    const walk = (n: MindNode, tone: string): boolean => n.tone === tone && n.children.every((c) => walk(c, tone));
    for (const b of root.children) expect(walk(b, b.tone)).toBe(true);
    const multi = buildMindMap({ ...content, topics: [0, 1, 2, 3, 4].map((i) => ({ ...content.topics[0], id: `T${i}`, title: `M${i}` })) })!;
    expect(multi.children.slice(0, 5).map((c) => c.tone)).toEqual(['info', 'neutral', 'info', 'neutral', 'info']);
    // Qarorlar (yashil), vazifalar (accent), ochiq savollar (sariq) ranglari - faqat o'z guruhida.
    const topicTones = new Set(multi.children.filter((c) => c.kind === 'topic').map((c) => c.tone));
    for (const tone of ['good', 'accent', 'warn']) expect(topicTones.has(tone as never)).toBe(false);
  });

  it('short call without topics shows key points; reversed decisions are dropped; labels in summary language', () => {
    const short: SummaryContent = {
      ...content,
      language: 'ru',
      template: 'short_call',
      topics: [],
      decisions: [{ ...content.decisions[0], status: 'reversed' }],
      actionItems: [],
      openQuestions: [],
    };
    const r = buildMindMap(short)!;
    expect(r.children.map((c) => [c.id, c.label])).toEqual([['group:keyPoints', 'Ключевые моменты']]);
    expect(r.children[0].children[0]).toMatchObject({ label: 'Narx kelishildi', start: 15.2 });
    // Hech narsa yo'q - xarita yo'q (bo'sh holat).
    expect(buildMindMap({ ...short, keyPoints: [] })).toBeNull();
    expect(buildMindMap(null)).toBeNull();
  });

  it('branch labels and dates in the SUMMARY language; live action items replace the summary ones', () => {
    const live = [
      { ...actionItem, owner: { speaker: 'S2', name: 'Dilnoza', kind: 'person' as const } },
      { ...actionItem, id: 'gone', status: 'dismissed' as const },
    ];
    const r = buildMindMap({ ...content, language: 'en' }, { speakers: s.speakers, actions: live })!;
    expect(r.children.map((c) => c.label)).toEqual(['Narxlar', 'Decisions', 'Action items', 'Open questions']);
    expect(findNode(r, 'group:tasks')!.children.map((c) => [c.id, c.label, c.meta, c.start])).toEqual([
      [`act:${actionItem.id}`, 'Hisobotni yuborish', 'Dilnoza · Due: October 10', 9.5],
    ]);
  });

  it('press rule is the same everywhere: branches fold, items seek', () => {
    expect(pressAction(findNode(root, 'topic:T1')!, 1)).toBe('toggle'); // vaqti bor mavzu ham ochiladi
    expect(pressAction(findNode(root, 'group:tasks')!, 2)).toBe('toggle');
    expect(pressAction(findNode(root, 'act:A1')!, 0)).toBe('seek');
    expect(pressAction({ kind: 'topic', start: 3 }, 0)).toBe('seek'); // bolasiz mavzu - eshitiladi
    expect(pressAction(root, root.children.length)).toBeNull();
  });

  it('a user title wins over the summary title', () => {
    expect(buildMindMap(content, { meeting: { title: 'Mening nomim', titleSource: 'user' } })!.label).toBe('Mening nomim');
  });
});

describe('mind map layout', () => {
  const overlaps = (a: LaidNode, b: LaidNode) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

  it('left to right: one column per depth, parents centred on their children, no overlaps', () => {
    const l = layoutMindMap(root);
    expect(l.nodes).toHaveLength(1 + 4 + 1 + 2 + 2 + 1);
    expect(l.edges).toHaveLength(l.nodes.length - 1);
    const byDepth = (d: number) => l.nodes.filter((n) => n.depth === d);
    expect(new Set(byDepth(1).map((n) => n.x)).size).toBe(1);
    expect(byDepth(1)[0].x).toBeGreaterThan(byDepth(0)[0].x + byDepth(0)[0].w);
    expect(byDepth(2)[0].x).toBeGreaterThan(byDepth(1)[0].x + byDepth(1)[0].w);
    for (const a of l.nodes) for (const b of l.nodes) if (a !== b) expect([a.id, b.id, overlaps(a, b)]).toEqual([a.id, b.id, false]);
    // Ota bolalar blokining o'rtasida.
    const tasks = l.nodes.find((n) => n.id === 'group:tasks')!;
    const kids = l.nodes.filter((n) => n.id.startsWith('act:'));
    const mid = (kids[0].y + kids[1].y + kids[1].h) / 2;
    expect(Math.abs(tasks.y + tasks.h / 2 - mid)).toBeLessThan(0.01);
    // Hamma narsa chizma ichida.
    for (const n of l.nodes) {
      expect(n.x + n.w).toBeLessThanOrEqual(l.width);
      expect(n.y + n.h).toBeLessThanOrEqual(l.height);
    }
    // Bog'lovchi ota o'ng chetidan bola chap chetigacha.
    const e = l.edges.find((x) => x.to === 'act:A1')!;
    expect(e.from).toBe('group:tasks');
    expect(e.d.startsWith(`M${tasks.x + tasks.w} ${tasks.y + tasks.h / 2} C`)).toBe(true);
  });

  it('nodes show owner/due and the time; text is wrapped inside the box', () => {
    const l = layoutMindMap(root);
    const a1 = l.nodes.find((n) => n.id === 'act:A1')!;
    // Uzun meta 2 qatorga o'raladi - oxiridagi vaqt kesilmaydi; audio vaqti ▶ bilan.
    expect(a1.metaLines.join(' ')).toBe('2-ishtirokchi · Muddat: 10-oktabr · ▶ 00:09');
    expect(l.nodes.find((n) => n.id === 'group:tasks')!.metaLines).toEqual([]);
    expect(l.nodes.find((n) => n.id === 'topic:T1')!.metaLines).toEqual(['▶ 00:00']);
    const maxChars = (a1.w - MIND_METRICS.padX * 2 - BAR_INSET) / (a1.fontSize * MIND_METRICS.charW);
    const long = buildMindMap({ ...content, keyPoints: [], topics: [{ ...content.topics[0], keyPoints: [{ text: 'juda '.repeat(80), sourceSegmentIds: [1], start: 1 }] }] })!;
    const n = layoutMindMap(long).nodes.find((x) => x.id === 'topic:T1:1')!;
    expect(n.lines).toHaveLength(MIND_METRICS.maxLines);
    expect(n.lines.at(-1)!.endsWith('...')).toBe(true);
    for (const line of n.lines) expect(line.length).toBeLessThanOrEqual(Math.floor(maxChars));
  });

  it('collapsing hides descendants and shrinks the map; the root never collapses', () => {
    const full = layoutMindMap(root);
    const folded = layoutMindMap(root, new Set(['group:tasks', 'root']));
    expect(folded.nodes.some((n) => n.id.startsWith('act:'))).toBe(false);
    expect(folded.nodes.find((n) => n.id === 'group:tasks')).toMatchObject({ collapsed: true, childCount: 2 });
    expect(folded.height).toBeLessThan(full.height);
    expect(folded.nodes.find((n) => n.id === 'root')!.collapsed).toBe(false);
    expect(collapsibleIds(root)).toEqual(['topic:T1', 'group:decisions', 'group:tasks', 'group:questions']);
    const all = layoutMindMap(root, new Set(collapsibleIds(root)));
    expect(all.nodes.map((n) => n.depth)).toEqual([0, 1, 1, 1, 1]);
  });

  it('outline rows follow the same tree and collapse state', () => {
    const rows = outlineRows(root, new Set(['group:decisions']));
    expect(rows.map((r) => [r.node.id, r.depth])).toEqual([
      ['topic:T1', 1],
      ['topic:T1:1', 2],
      ['group:decisions', 1],
      ['group:tasks', 1],
      ['act:A1', 2],
      ['act:A2', 2],
      ['group:questions', 1],
      ['q:Q1', 2],
    ]);
    expect(rows.find((r) => r.node.id === 'group:decisions')!.collapsed).toBe(true);
  });
});

/** Katta yig'ilish: 30 mavzu x 3 fikr, 12 qaror, 15 vazifa, 10 savol - hammasi ochiq. */
function bigMeeting(): MindNode {
  const ev = (start: number) => ({ sourceSegmentIds: [1], start });
  const topics = Array.from({ length: 30 }, (_, i) => ({
    ...content.topics[0],
    id: `T${i}`,
    title: `Mavzu ${i}: uzunroq sarlavha, ikki qatorga o'raladigan`,
    start: i * 60,
    keyPoints: [0, 1, 2].map((j) => ({ text: `Mavzu ${i} bo'yicha ${j}-fikr - yetarlicha uzun matn, uch qatorga o'raladi va joy egallaydi`, ...ev(i * 60 + j) })),
  }));
  const big: SummaryContent = {
    ...content,
    topics,
    decisions: Array.from({ length: 12 }, (_, i) => ({ ...content.decisions[0], id: `D${i}`, text: `Qaror ${i}`, start: i })),
    actionItems: Array.from({ length: 15 }, (_, i) => ({ ...content.actionItems[0], id: `A${i}`, task: `Vazifa ${i} - batafsil tavsif bilan`, start: i })),
    openQuestions: Array.from({ length: 10 }, (_, i) => ({ ...content.openQuestions[0], id: `Q${i}`, text: `Savol ${i}?`, start: i })),
  };
  return buildMindMap(big, { speakers: s.speakers })!;
}

describe('mind map tiles (Android bitmap budget)', () => {
  const big = bigMeeting();
  const full = layoutMindMap(big);

  it('the fully expanded 30-topic map would be far beyond one bitmap - hence tiles', () => {
    // Bitta <Svg> bo'lganida 100% da ham Android'ning 100 MB chegarasidan o'tardi.
    expect(full.width * full.height * 2.75 ** 2 * 4).toBeGreaterThan(100 * 1024 * 1024);
  });

  it.each([2, 2.75, 3.5])('every tile stays <= 4 MB at every zoom step (pixel ratio %p)', (pr) => {
    for (const scale of ZOOM_STEPS) {
      const tiles = canvasTiles(full, scale, pr);
      for (const t of tiles) {
        expect(tileBytes(t, scale, pr)).toBeLessThanOrEqual(TILE_MAX_BYTES);
        expect(Math.ceil(t.w * scale * pr)).toBeLessThanOrEqual(TILE_PX);
        expect(Math.ceil(t.h * scale * pr)).toBeLessThanOrEqual(TILE_PX);
      }
      // Plitkalar xaritani bo'shliqsiz va ustma-ust tushmasdan qoplaydi.
      const area = tiles.reduce((sum, t) => sum + t.w * t.h, 0);
      expect(Math.abs(area - full.width * full.height)).toBeLessThan(1);
      // Telefonda bir vaqtda chiziladiganlari (ekran + yarim ekran zahira) - 64 MB dan kam,
      // xarita qancha katta bo'lmasin.
      for (const y of [0, (full.height * scale) / 2, full.height * scale]) {
        const shown = visibleTiles(tiles, scale, { x: 0, y, w: 393, h: 700 });
        expect(shown.length).toBeGreaterThan(0);
        expect(shown.reduce((sum, t) => sum + tileBytes(t, scale, pr), 0)).toBeLessThanOrEqual(64 * 1024 * 1024);
      }
    }
  });

  it('each node has exactly one "home" tile (testID / screen reader); border nodes are drawn in both', () => {
    const tiles = canvasTiles(full, 1.8, 3.5);
    const homes = new Map<string, number>();
    let shared = 0;
    for (const t of tiles) {
      const c = tileContent(full, t);
      for (const { node, home } of c.nodes) if (home) homes.set(node.id, (homes.get(node.id) ?? 0) + 1);
      shared += c.nodes.filter((x) => !x.home).length;
    }
    expect(homes.size).toBe(full.nodes.length);
    for (const n of homes.values()) expect(n).toBe(1);
    expect(shared).toBeGreaterThan(0);
  });

  it('opens collapsed: root + branches fit a phone; the starting zoom fits the screen width', () => {
    const folded = layoutMindMap(big, new Set(collapsibleIds(big)));
    expect(folded.nodes.every((n) => n.depth <= 1)).toBe(true);
    const z = fitZoom(folded.width + 16, 393);
    expect(ZOOM_STEPS[z]).toBeLessThanOrEqual(1);
    expect((folded.width + 16) * ZOOM_STEPS[z]).toBeLessThanOrEqual(393);
    expect(fitZoom(300, 1200)).toBe(ZOOM_STEPS.indexOf(1)); // keng ekranda 100% dan oshmaydi
    expect(fitZoom(5000, 300)).toBe(0);
  });
});

describe('wrapText', () => {
  it('wraps by words, splits very long words and ellipsizes', () => {
    expect(wrapText('bir ikki uch tort', 8, 5)).toEqual(['bir ikki', 'uch tort']);
    expect(wrapText('https://example.com/very/long/path', 10, 5)).toEqual(['https://ex', 'ample.com/', 'very/long/', 'path']);
    expect(wrapText('a b c d e f g h', 4, 2)).toEqual(['a b', 'c...']);
    expect(wrapText('abcd efgh ijkl', 4, 1)).toEqual(['a...']);
    expect(wrapText('', 10, 3)).toEqual(['']);
  });
});
