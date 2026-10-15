import type { Summary } from '@/api/types';
import { briefCovers, briefRefs, briefToText, buildBrief } from '@/features/meeting/brief';
import { buildSummaryView, DEFAULT_ORDER, detailGroups, summaryToText } from '@/features/meeting/summaryModel';
import { makeT } from '@/i18n';

import { summary } from './fixtures/server';

const t = makeT('uz');

describe('summary rendering model', () => {
  const view = buildSummaryView(summary(), t)!;
  const section = (key: string) => view.sections.find((s) => s.key === key)!;

  it('renders sections in layout order with server headings, skipping title/quality and empty ones', () => {
    expect(view.title).toBe('Narxlar va hisobot');
    expect(view.sections.map((s) => s.key)).toEqual([
      'overview',
      'actionItems',
      'decisions',
      'topics',
      'openQuestions',
      'risks',
      'numbers',
      'dates',
      'nextSteps',
      'nextMeeting',
      'highlights',
      'participants',
      'keyPoints',
      'keywords',
      'sentiment',
      'objections',
    ]);
    expect(section('decisions').title).toBe('Qarorlar');
  });

  it('covers every Plaud-superset section present in the content', () => {
    // Plaud: overview, key points, action items, decisions, next steps, "AI suggestion" (open questions),
    // key numbers, highlights, outline/topics, speakers; biz: + risks, dates, next meeting, sentiment, keywords.
    for (const key of ['overview', 'keyPoints', 'actionItems', 'decisions', 'nextSteps', 'openQuestions', 'numbers', 'highlights', 'topics', 'participants', 'risks', 'dates', 'nextMeeting', 'sentiment', 'keywords']) {
      expect(view.sections.some((s) => s.key === key)).toBe(true);
    }
  });

  it('replaces [S#] tokens with confirmed names, merged speakers and fallbacks', () => {
    // S1 = Aziz; S2 nomsiz -> "2-ishtirokchi"; S3 S1 ga birlashtirilgan -> Aziz.
    expect(section('overview').text).toBe("Aziz narxlarni ko'rib chiqdi. 2-ishtirokchi hisobot yuboradi. Aziz rozi bo'ldi.");
    expect(section('nextSteps').items[0].text).toBe('2-ishtirokchi hisobot yuboradi');
    const ru = buildSummaryView(summary(), makeT('ru'), { speakers: [] })!;
    // Xulosa tili uz - zaxira yorliq xulosa tilida.
    expect(ru.sections.find((s) => s.key === 'overview')!.text).toContain('1-ishtirokchi');
  });

  it('action items carry owner, resolved/vague due, chips, quote and evidence; unverified ones are flagged', () => {
    const [a1, a2] = section('actionItems').items;
    expect(a1.text).toBe('Hisobotni yuborish');
    expect(a1.sub).toEqual(["Mas'ul: 2-ishtirokchi", 'Muddat: 10-oktabr', 'Natija: PDF hisobot']);
    expect(a1.chips.map((c) => c.label)).toEqual(['Muhim', "Va'da (bilvosita)", 'tasdiqlangan']);
    expect(a1.needsCheck).toBe(false);
    expect(a1.quote).toBe('Men ertaga hisobotni yuboraman');
    expect(a1.start).toBe(9.5);

    expect(a2.sub).toEqual(["Mas'ul: Jamoa", 'Muddat: tez orada (aniq emas)', 'Topshirdi: Aziz', "Bog'liq: A1"]);
    expect(a2.needsCheck).toBe(true);
    expect(a2.chips.map((c) => c.label)).toContain('tekshiring');
    expect(a2.chips.map((c) => c.label)).not.toContain('tasdiqlangan');
  });

  it('decisions show status, rationale, who proposed/agreed; verified=false is never shown as confirmed', () => {
    const [d1, d2] = section('decisions').items;
    expect(d1.chips.map((c) => c.label)).toEqual(['Yakuniy', 'tasdiqlangan']);
    expect(d1.sub).toEqual(['Sabab: Bozor narxi', 'Taklif: Aziz', 'Rozi: 2-ishtirokchi, Aziz']);
    expect(d2.needsCheck).toBe(true);
    expect(d2.chips.map((c) => c.label)).toEqual(['Taxminiy', 'tekshiring']);
  });

  it('topics nest key points with timestamps; other sections get their facts', () => {
    const topic = section('topics').items[0];
    expect(topic.chips.map((c) => c.label)).toEqual(['Hal qilindi', '00:00-00:18']);
    expect(topic.children[0]).toMatchObject({ text: 'Narx 15 mln', start: 4.3 });
    expect(section('openQuestions').items[0].sub).toEqual(["Ko'targan: Aziz", 'Kimga: 2-ishtirokchi']);
    expect(section('openQuestions').items[0].chips[0].label).toBe('Javob berilmadi');
    expect(section('risks').items[0].chips.map((c) => c.label)).toEqual(['Xavf', 'Yuqori']);
    expect(section('risks').items[0].sub).toContain('Chora: Avans olish');
    expect(section('numbers').items[0].text).toBe("15 mln so'm - narx");
    expect(section('dates').items[0].text).toBe('25-oktabr - muddat');
    expect(section('nextMeeting').items[0]).toMatchObject({ text: '13-oktabr, 10:00', sub: ['Kun tartibi: Natijalar'] });
    expect(section('highlights').items[0]).toMatchObject({ text: '"kelishdik"', sub: ['Aziz', 'Qaror'] });
    expect(section('highlights').items[0].chips[0].label).toBe('Sizning belgingiz');
    expect(section('keywords').tags).toEqual(['narx', 'hisobot']);
    expect(section('sentiment').text).toBe('Ijobiy. Aziz mamnun');
    expect(section('objections').items[0]).toMatchObject({ text: 'Qimmat', sub: ['2-ishtirokchi'], start: 9.5 });
  });

  it('participants offer a suggested name that is never auto-applied', () => {
    const p = section('participants').items;
    expect(p[0]).toMatchObject({ text: 'Aziz', action: null });
    expect(p[1].text).toBe('2-ishtirokchi');
    expect(p[1].action).toEqual({ kind: 'acceptName', speaker: 'S2', name: 'Dilnoza' });
    expect(p[1].chips[0].label).toBe('Bu Dilnozami?');
    expect(p[1].sub).toContain('42% gapirdi (07:00)');
  });

  it('falls back to a default order with localized headings when layout is missing', () => {
    const v = buildSummaryView(summary({ layout: [] }), t)!;
    const keys = v.sections.map((s) => s.key);
    expect(keys.slice(0, 4)).toEqual(['overview', 'purpose', 'actionItems', 'decisions']);
    expect(keys).toContain('objections');
    expect(v.sections.find((s) => s.key === 'purpose')!.title).toBe('Maqsad');
    expect(DEFAULT_ORDER).toContain('followUpMessage');
  });

  it('renders follow-up messages and hides empty sections', () => {
    const s = summary();
    s.content!.followUpMessage = { subject: 'Yig\'ilish yakuni', body: 'Rahmat, [S1]!' };
    s.content!.risks = [];
    s.content!.nextMeeting = null;
    s.layout = [{ key: 'followUpMessage', title: 'Kuzatuv xabari' }, { key: 'risks', title: 'Xavflar' }, { key: 'nextMeeting', title: 'X' }];
    const v = buildSummaryView(s, t)!;
    expect(v.sections).toHaveLength(1);
    expect(v.sections[0].text).toBe("Mavzu: Yig'ilish yakuni\n\nRahmat, Aziz!");
  });

  it('returns null without content and reports quality warnings', () => {
    expect(buildSummaryView(summary({ content: null }), t)).toBeNull();
    expect(view.warnings[0]).toContain('(1)');
  });

  it('exports plain text that keeps every section, flag and quote', () => {
    const text = summaryToText(view, t, { header: ['9-oktyabr, 11:00 · 1:00:00'] });
    expect(text.startsWith('Narxlar va hisobot\n9-oktyabr, 11:00 · 1:00:00\n')).toBe(true);
    expect(text).toContain('## Vazifalar');
    expect(text).toContain("- Hisobotni yuborish (Muhim, Va'da (bilvosita), tasdiqlangan)");
    expect(text).toContain("  Mas'ul: 2-ishtirokchi");
    expect(text).toContain('  > "Men ertaga hisobotni yuboraman" [00:09]');
    expect(text).toMatch(/- Shartnomani tekshirish.*\[tekshiring\]\n  Mas'ul: Jamoa/);
    expect(text).toContain("## Kalit so'zlar\nnarx, hisobot");
    expect(text).toContain('  - Narx 15 mln');
  });

  it('task details for the card skip owner/due (they are in the card line, from the live list)', () => {
    const [a1, a2] = section('actionItems').items;
    expect(a1.more).toEqual(['Natija: PDF hisobot']);
    expect(a2.more).toEqual(['Topshirdi: Aziz', "Bog'liq: A1"]);
    expect(section('decisions').items[0].more).toBeUndefined(); // qarorda `sub` ning o'zi
  });

  it('indexes every item by section/id (nested ones too), card sections even when the layout skips them', () => {
    expect(view.index.get('decisions/D1')?.text).toBe("Narx 15 mln so'm");
    expect(view.index.get('topics/T1.1')?.text).toBe('Narx 15 mln');
    expect(view.index.get('objections/objections.1')?.text).toBe('Qimmat');
    const noCard = buildSummaryView(summary({ layout: [{ key: 'risks', title: 'Xavflar' }] }), t)!;
    expect(noCard.sections.map((x) => x.key)).toEqual(['risks']);
    expect(noCard.index.get('actionItems/A2')?.needsCheck).toBe(true);
    expect(noCard.index.get('keyPoints/K1')?.text).toBe('Narx kelishildi');
  });
});

describe('merged facts (server alsoIn) and follow-up reasons', () => {
  function merged(): Summary {
    const s = summary();
    const c = s.content!;
    c.keyPoints[0].alsoIn = [
      { section: 'template', key: 'shortlist', label: 'Tanlangan' },
      { section: 'risks', key: null, label: 'Xavf' },
      { section: 'template', key: 'pros', label: 'Tanlangan' }, // bir xil yozuv - bitta chip
    ];
    c.actionItems[0].alsoIn = [{ section: 'nextSteps', label: 'Keyingi qadam' }];
    c.decisions[0].alsoIn = [{ section: 'template', key: 'agreements', label: 'Kelishuv' }];
    c.openQuestions[0].alsoIn = [{ section: 'risks', label: 'Xavf' }];
    c.risks[0].alsoIn = [{ section: 'template', key: 'cons', label: 'Kamchilik' }];
    c.nextSteps[0].alsoIn = [{ section: 'template', key: 'ideas', label: "G'oya" }];
    c.templateSections[0].items[0].alsoIn = [{ section: 'risks', label: 'Xavf' }];
    c.topics[0].keyPoints[0].alsoIn = [{ section: 'decisions', label: 'Qaror' }];
    c.view = { compact: 1, merged: 6 };
    c.followUps = [
      { id: 'F1', kind: 'risk', ref: 'R1', text: 'Kurs oshishi', reasons: ['no_mitigation', 'mystery_code'], sourceSegmentIds: [2], start: 4.3 },
      // Vazifa, qaror, savolga havola - kartada holati bilan bor: chip bo'lmaydi (server ham olib tashlaydi).
      { id: 'F2', kind: 'openQuestion', ref: 'Q1', text: 'Yetkazib berish qachon?', reasons: ['no_answer'], sourceSegmentIds: [4], start: 15.2 },
      { id: 'F3', kind: 'actionItem', ref: 'A2', text: 'Shartnomani tekshirish', reasons: ['no_owner', 'no_due'], sourceSegmentIds: [2], start: 4.3 },
    ];
    s.layout = [...s.layout, { key: 'followUps', title: 'Hal qilinmagan masalalar' }];
    return s;
  }
  const v = buildSummaryView(merged(), t)!;
  const sec = (key: string) => v.sections.find((x) => x.key === key)!;
  const tagged = (chips: { label: string; kind?: string }[]) => chips.filter((c) => c.kind).map((c) => `${c.kind}:${c.label}`);

  it('renders every alsoIn entry as a neutral chip on the surviving item (deduped by label)', () => {
    expect(sec('keyPoints').items[0].chips).toEqual([
      { label: 'Tanlangan', tone: 'neutral', kind: 'alsoIn' },
      { label: 'Xavf', tone: 'neutral', kind: 'alsoIn' },
    ]);
    // O'z chiplari saqlanadi, alsoIn - oxirida.
    expect(sec('actionItems').items[0].chips.map((c) => c.label)).toEqual(['Muhim', "Va'da (bilvosita)", 'tasdiqlangan', 'Keyingi qadam']);
    expect(tagged(sec('decisions').items[0].chips)).toEqual(['alsoIn:Kelishuv']);
    expect(tagged(sec('openQuestions').items[0].chips)).toEqual(['alsoIn:Xavf']);
    expect(tagged(sec('nextSteps').items[0].chips)).toEqual(["alsoIn:G'oya"]);
    expect(tagged(sec('objections').items[0].chips)).toEqual(['alsoIn:Xavf']);
    expect(tagged(sec('topics').items[0].children[0].chips)).toEqual(['alsoIn:Qaror']);
  });

  it('a remaining follow-up becomes a chip on the item it points to, not a section', () => {
    expect(v.sections.some((x) => x.key === 'followUps')).toBe(false);
    expect(tagged(sec('risks').items[0].chips)).toEqual(['followUp:Yechim aytilmagan', 'alsoIn:Kamchilik']);
    expect(sec('risks').items[0].chips.find((c) => c.kind === 'followUp')!.tone).toBe('warn');
    expect(tagged(sec('openQuestions').items[0].chips)).not.toContain('followUp:Javob berilmagan');
    expect(tagged(sec('actionItems').items[1].chips)).toEqual([]);
    // Ilova tilida.
    const ru = buildSummaryView(merged(), makeT('ru'))!;
    expect(tagged(ru.sections.find((x) => x.key === 'risks')!.items[0].chips)).toContain('followUp:Решение не названо');
  });

  it('old summaries without alsoIn/followUps/view render exactly as before', () => {
    const old = buildSummaryView(summary(), t)!;
    for (const s of old.sections) for (const it of s.items) expect(it.chips.every((c) => !c.kind)).toBe(true);
  });

  it('the full-summary text keeps the chips as written on screen', () => {
    const text = summaryToText(v, t);
    expect(text).toContain('- Narx kelishildi (Tanlangan, Xavf)');
    expect(text).toContain('- Kurs oshishi (Xavf, Yuqori, Yechim aytilmagan, Kamchilik)');
  });
});

describe('"Batafsil" groups: only what the card does not show', () => {
  const plan = (s: Summary, durationSec: number) => {
    const brief = buildBrief(s.content, { durationSec }, s.speakers);
    return detailGroups(buildSummaryView(s, t)!, { covered: briefCovers(s.content, s.speakers), inCard: briefRefs(brief), durationSec });
  };
  const keys = (gs: { key: string }[]) => gs.map((g) => g.key);

  it('long meeting: every remaining group is listed, card sections and meta-line sections are gone', () => {
    const p = plan(summary(), 3600);
    // overview: 3 gap - kartada 1 gap, to'lig'i qoladi. Qarorlar (bekor qilinmagan), vazifalar,
    // savollar, kartadagi yagona fikr - yo'q; kalit so'zlar va kayfiyat - pastdagi qatorda.
    expect(keys(p.shown)).toEqual(['overview', 'topics', 'risks', 'numbers', 'dates', 'nextSteps', 'nextMeeting', 'highlights', 'participants', 'objections']);
    expect(p.more).toEqual([]);
    expect(p.shown.map((g) => g.count)).toEqual([null, 1, 1, 1, 1, 1, 1, 1, 2, 1]);
    expect(p.shown[1].title).toBe('Mavzular'); // xulosa tilidagi sarlavha (layout)
  });

  it('short meeting: 2 groups, the rest behind "N more"; topics (chapters) go last', () => {
    const p = plan(summary(), 600);
    expect(keys(p.shown)).toEqual(['overview', 'risks']);
    expect(keys(p.more)).toEqual(['numbers', 'dates', 'nextSteps', 'nextMeeting', 'highlights', 'participants', 'objections', 'topics']);
    // O'rta (<= 45 daq): 4 ta, mavzular o'z joyida.
    const mid = plan(summary(), 1800);
    expect(keys(mid.shown)).toEqual(['overview', 'topics', 'risks', 'numbers']);
    expect(mid.more).toHaveLength(6);
  });

  it('a single hidden group is just shown ("1 more" would take the same row)', () => {
    const s = summary();
    s.layout = [{ key: 'overview', title: 'Qisqacha' }, { key: 'risks', title: 'Xavflar' }, { key: 'numbers', title: 'Raqamlar' }];
    expect(keys(plan(s, 600).shown)).toEqual(['overview', 'risks', 'numbers']);
    s.layout.push({ key: 'dates', title: 'Sanalar' });
    expect(plan(s, 600).more).toHaveLength(2);
  });

  it('counts exclude card items: key points beyond the card count, reversed decisions only', () => {
    const s = summary();
    const c = s.content!;
    c.keyPoints = Array.from({ length: 5 }, (_, i) => ({ id: `K${i + 1}`, text: `Fikr ${i + 1}`, sourceSegmentIds: [1], start: i }));
    c.decisions = [c.decisions[0], { ...c.decisions[1], status: 'reversed' }];
    // 1 soat: kartada 5 ta fikr - hammasi sig'di, guruh yo'q.
    expect(keys(plan(s, 3600).shown)).not.toContain('keyPoints');
    const short = plan(s, 600);
    const all = [...short.shown, ...short.more];
    const kp = all.find((x) => x.key === 'keyPoints')!;
    expect(kp.count).toBe(2);
    expect(kp.section.items.map((i) => i.id)).toEqual(['K4', 'K5']);
    // Bekor qilingan qaror kartada yo'q - "Batafsil" da faqat u.
    const dec = all.find((x) => x.key === 'decisions')!;
    expect(dec.count).toBe(1);
    expect(dec.section.items.map((i) => i.id)).toEqual(['D2']);
    // Bir gaplik umumiy xulosa kartada to'liq - guruh yo'q.
    c.overview = "[S1] narxlarni ko'rib chiqdi.";
    expect(keys([...plan(s, 600).shown, ...plan(s, 600).more])).not.toContain('overview');
  });

  it('participants only stay for a name to accept; otherwise they live in the meta line', () => {
    const s = summary();
    s.content!.participants = s.content!.participants.map((p) => ({ ...p, suggestedName: null }));
    expect(keys(plan(s, 3600).shown)).not.toContain('participants');
  });

  it('copy text = the card, then the remaining groups, then the meta line - nothing twice', () => {
    const s = summary();
    const brief = buildBrief(s.content, { durationSec: 3600, recordedAt: '2026-10-09T06:00:00Z' }, s.speakers)!;
    const p = plan(s, 3600);
    const text = summaryToText({ title: 'X', sections: [...p.shown, ...p.more].map((g) => g.section) }, t, {
      header: ['9-oktyabr'],
      brief: briefToText(brief),
      footer: ['Kayfiyat: ijobiy · Tayyorladi: Gemma'],
    });
    expect(text.startsWith(briefToText(brief))).toBe(true);
    expect(text).not.toContain('9-oktyabr'); // sana kartada bor
    expect(text).not.toContain('## Vazifalar');
    expect(text).not.toContain('## Qarorlar');
    expect(text).toContain('## Xavflar\n- Kurs oshishi');
    expect(text.split('Hisobotni yuborish')).toHaveLength(2); // vazifa bir marta
    expect(text.endsWith('\n\nKayfiyat: ijobiy · Tayyorladi: Gemma\n')).toBe(true);
  });
});
