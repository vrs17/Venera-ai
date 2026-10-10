import { buildSummaryView, DEFAULT_ORDER, summaryToText } from '@/features/meeting/summaryModel';
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
});
