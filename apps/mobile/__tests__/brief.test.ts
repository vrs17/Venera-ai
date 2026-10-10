/**
 * "Qisqa xulosa" bloki: egasi tasdiqlagan format (2026-10-10) so'zma-so'z,
 * uz/ru/en yorliqlari xulosa tilida, yetishmagan qismlar tushib qoladi. Server bilan
 * so'zma-so'z tengligi - `briefGolden.test.ts` (umumiy namuna).
 */
import type { Speaker, SummaryContent } from '@/api/types';
import {
  briefCovers,
  briefDate,
  briefToMarkdown,
  briefToText,
  buildBrief,
  durationWords,
  firstSentences,
  pluralForm,
  summaryTitle,
} from '@/features/meeting/brief';

import { actionItem, summary } from './fixtures/server';

const base = summary().content!;

const twoSpeakers: Speaker[] = [
  { id: 'S1', name: null, suggestedName: null, talkSec: 60, mergedInto: null },
  { id: 'S2', name: null, suggestedName: null, talkSec: 50, mergedInto: null },
];

const ev = (start: number | null) => ({ sourceSegmentIds: [1], start });

/** Egasi yuborgan namunadagi yig'ilish (12:37 Toshkent = 07:37 UTC, 1 daq 53 s). */
function ownerExample(over: Partial<SummaryContent> = {}): SummaryContent {
  return {
    ...base,
    template: 'short_call',
    language: 'uz',
    meeting: { date: '2026-10-10', weekday: 'shanba', timezone: 'Asia/Tashkent', durationSec: 113, speakerCount: 2 },
    title: 'Transkripsiya va CRM integratsiyasi muhokamasi',
    purpose: 'yangi transkripsiya va avtomatik vazifalar tizimining imkoniyatlarini muhokama qilish',
    overview:
      "tizim suhbatni yozib, spikerlarga ajratib matnga aylantirishi, mazmunidan CRM'ga vazifa yaratishi va loyihalar bo'yicha kontekst to'plashi muhokama qilindi.",
    topics: [],
    keyPoints: [
      { id: 'K1', text: "Transkript spikerlar bo'yicha ajratib chiqariladi.", ...ev(3) },
      { id: 'K2', text: "Suhbat mazmunidan CRM'ga vazifa yaratiladi, tizim loyihalar bo'yicha kontekst to'plab boradi.", ...ev(20) },
      { id: 'K3', text: "G'oya: chatda yig'ilishdagi kelishuvga zid gap yozilsa, tizim ogohlantiradi va deadline'larni eslatadi.", ...ev(41) },
      { id: 'K4', text: 'Yozuv paytida "Muhim" belgisi bilan kerakli joyni belgilash va izoh qo\'shish mumkin.', ...ev(60) },
      { id: 'K5', text: "Ma'lumot manbalari (CRM, HRM va boshqalar) alohida yoqib-o'chiriladi.", ...ev(80) },
    ],
    decisions: [],
    actionItems: [
      {
        id: 'A1',
        task: 'Skriptni yuborish',
        deliverable: null,
        owner: { speaker: 'S2', name: null, kind: 'person', basis: 'self_commitment' },
        assignedBy: null,
        due: { raw: null, date: null, time: null, basis: 'none' },
        priority: null,
        status: 'open',
        origin: 'explicit',
        dependsOn: [],
        topicId: null,
        quote: 'skriptni yuboraman',
        confidence: 0.9,
        needsConfirmation: false,
        verified: true,
        ...ev(100),
      },
    ],
    openQuestions: [{ id: 'Q1', text: 'Suhbat paytida matn yozish (typing) imkoniyati qanday ishlaydi?', raisedBy: 'S1', directedTo: null, whyOpen: 'no_answer', ...ev(105) }],
    quality: { ...base.quality, speakersAvailable: true },
    ...over,
  };
}

const meeting = { title: "Yig'ilish 10-oktyabr, 12:37", titleSource: 'auto' as const, recordedAt: '2026-10-10T07:37:00Z', durationSec: 113.2 };

describe('short stakeholder summary (brief)', () => {
  it("reproduces the owner's approved format word for word (plain text and Markdown)", () => {
    const b = buildBrief(ownerExample(), meeting, twoSpeakers)!;
    expect(briefToMarkdown(b)).toBe(
      [
        // Markdown: sarlavha va meta bir paragrafda - majburiy qator uzilishi (ikki bo'shliq).
        '**Transkripsiya va CRM integratsiyasi muhokamasi**  ',
        '10-oktabr 2026 (shanba), 12:37 · 1 daq 53 s · 2 ishtirokchi',
        '',
        '**Maqsad:** yangi transkripsiya va avtomatik vazifalar tizimining imkoniyatlarini muhokama qilish.',
        '',
        "**Qisqacha:** tizim suhbatni yozib, spikerlarga ajratib matnga aylantirishi, mazmunidan CRM'ga vazifa yaratishi va loyihalar bo'yicha kontekst to'plashi muhokama qilindi.",
        '',
        '**Asosiy fikrlar:**',
        "- Transkript spikerlar bo'yicha ajratib chiqariladi.",
        "- Suhbat mazmunidan CRM'ga vazifa yaratiladi, tizim loyihalar bo'yicha kontekst to'plab boradi.",
        "- G'oya: chatda yig'ilishdagi kelishuvga zid gap yozilsa, tizim ogohlantiradi va deadline'larni eslatadi.",
        '- Yozuv paytida "Muhim" belgisi bilan kerakli joyni belgilash va izoh qo\'shish mumkin.',
        "- Ma'lumot manbalari (CRM, HRM va boshqalar) alohida yoqib-o'chiriladi.",
        '',
        '**Vazifa:**',
        "- Skriptni yuborish. Mas'ul: 2-ishtirokchi. Muddat belgilanmagan.",
        '',
        '**Ochiq savol:**',
        '- Suhbat paytida matn yozish (typing) imkoniyati qanday ishlaydi?',
        '',
      ].join('\n'),
    );
    // Oddiy matn - xuddi shu, faqat `**` siz (messenjerda yulduzchalar ko'rinmasin).
    const text = briefToText(b);
    expect(text).not.toContain('**');
    expect(text.split('\n').slice(0, 4)).toEqual([
      'Transkripsiya va CRM integratsiyasi muhokamasi',
      '10-oktabr 2026 (shanba), 12:37 · 1 daq 53 s · 2 ishtirokchi',
      '',
      'Maqsad: yangi transkripsiya va avtomatik vazifalar tizimining imkoniyatlarini muhokama qilish.',
    ]);
    expect(b.lists.map((l) => l.key)).toEqual(['keyPoints', 'actionItems', 'openQuestions']);
    expect(b.lists[0].items[1].start).toBe(20);
  });

  it('plural labels, decisions, named/team owners, due dates and the "check" flag', () => {
    const b = buildBrief(base, { ...meeting, recordedAt: '2026-10-09T06:00:00Z', durationSec: 3600.4 }, summary().speakers)!;
    expect(b.title).toBe('Narxlar va hisobot'); // avto nom emas - xulosa sarlavhasi
    expect(b.meta).toBe('9-oktabr 2026 (juma), 11:00 · 1 soat · 2 ishtirokchi'); // S3 S1 ga birlashtirilgan
    // Qisqacha - ko'pi 2 gap (3-gap tushib qoladi).
    expect(b.overview).toEqual({ label: 'Qisqacha', text: "Aziz narxlarni ko'rib chiqdi. 2-ishtirokchi hisobot yuboradi." });
    const list = (k: string) => b.lists.find((l) => l.key === k)!;
    expect(b.lists.map((l) => l.key)).toEqual(['keyPoints', 'decisions', 'actionItems', 'openQuestions']);
    expect(list('keyPoints').label).toBe('Asosiy fikr'); // bitta fikr - birlik
    expect(list('decisions').label).toBe('Qarorlar');
    // Yakuniy bo'lmagan va tasdiqlanmagan qaror belgilanadi - bitta qavsda, holat so'zi bilan
    // ("tekshiring" kabi buyruq emas: blok rahbarga yuboriladi).
    expect(list('decisions').items.map((i) => i.text)).toEqual(["Narx 15 mln so'm.", 'Chegirma berilmaydi (taxminiy, aniqlashtirish kerak).']);
    expect(list('actionItems').label).toBe('Vazifalar');
    expect(list('actionItems').items.map((i) => i.text)).toEqual([
      "Hisobotni yuborish. Mas'ul: 2-ishtirokchi. Muddat: 10-oktabr.",
      // Tasdiqlanmagan vazifa hech qachon tasdiqlangandek ketmaydi.
      "Shartnomani tekshirish. Mas'ul: Jamoa. Muddat: tez orada. (aniqlashtirish kerak)",
    ]);
    expect(list('openQuestions').label).toBe('Ochiq savol');
  });

  it('a Russian summary gets Russian labels by default', () => {
    const ru = ownerExample({
      language: 'ru',
      title: 'Обсуждение интеграции с CRM',
      purpose: 'Обсудить новую систему',
      overview: 'Обсудили расшифровку и задачи в CRM',
      keyPoints: [{ id: 'K1', text: 'Расшифровка делится по спикерам', ...ev(3) }],
      openQuestions: [{ id: 'Q1', text: 'Как работает набор текста', raisedBy: null, directedTo: null, whyOpen: 'no_answer', ...ev(5) }],
    });
    const b = buildBrief(ru, meeting, twoSpeakers)!;
    expect(briefToText(b)).toBe(
      [
        'Обсуждение интеграции с CRM',
        '10 октября 2026 (суббота), 12:37 · 1 мин 53 с · 2 участника',
        '',
        'Цель: Обсудить новую систему.',
        '',
        'Кратко: Обсудили расшифровку и задачи в CRM.',
        '',
        'Ключевой момент:',
        '- Расшифровка делится по спикерам.',
        '',
        'Задача:',
        '- Skriptni yuborish. Ответственный: Участник 2. Срок не указан.',
        '',
        'Открытый вопрос:',
        '- Как работает набор текста?',
        '',
      ].join('\n'),
    );
  });

  it('the whole block is in the SUMMARY language (never mixed with the app language)', () => {
    // Ilova tili buildBrief'ga umuman berilmaydi: "Ответственный: 2-ishtirokchi" aralashmasi
    // chiqmasin - yuklab olingan fayl (server) ham aynan shunday.
    const b = buildBrief(ownerExample(), meeting, twoSpeakers)!;
    expect(b.language).toBe('uz');
    expect(b.purpose!.label).toBe('Maqsad');
    expect(b.lists.map((l) => l.label)).toEqual(['Asosiy fikrlar', 'Vazifa', 'Ochiq savol']);
    expect(b.lists[1].items[0].text).toBe("Skriptni yuborish. Mas'ul: 2-ishtirokchi. Muddat belgilanmagan.");
  });

  it('a conditional task keeps its condition; an unverified one is flagged', () => {
    const [a1] = ownerExample().actionItems;
    const b = buildBrief(ownerExample({ actionItems: [{ ...a1, condition: "agar mijoz rozi bo'lsa", verified: false }] }), meeting, twoSpeakers)!;
    expect(b.lists.find((l) => l.key === 'actionItems')!.items[0].text).toBe(
      "Skriptni yuborish (shart: agar mijoz rozi bo'lsa). Mas'ul: 2-ishtirokchi. Muddat belgilanmagan. (aniqlashtirish kerak)",
    );
  });

  it('briefCovers: which full-summary sections the brief repeats word for word', () => {
    // Qisqa qo'ng'iroq: 1 gaplik umumiy xulosa va 5 ta fikr - ikkalasi ham blokda to'liq.
    expect([...briefCovers(ownerExample())].sort()).toEqual(['keyPoints', 'openQuestions', 'overview']);
    // 3 gaplik umumiy xulosa qisqartiriladi va 7 ta fikrdan 6 tasi sig'adi - bo'limlar qoladi.
    const long = ownerExample({ overview: 'Bir. Ikki. Uch.', keyPoints: Array.from({ length: 7 }, (_, i) => ({ id: `K${i}`, text: `Fikr ${i}`, ...ev(i) })) });
    expect([...briefCovers(long)]).toEqual(['openQuestions']);
  });

  it('the primary summary uses the LIVE action items (edited, added, done, dismissed)', () => {
    const live = [
      { ...actionItem, task: 'Hisobotni yuborish (tahrirlangan)', owner: { speaker: 'S2', name: 'Dilnoza', kind: 'person' as const } },
      { ...actionItem, id: 'x2', task: 'Shartnoma', status: 'done' as const, owner: { speaker: null, name: null, kind: 'team' as const }, due: { date: null, time: null, raw: null } },
      { ...actionItem, id: 'x3', task: 'Bekor', status: 'dismissed' as const },
      { ...actionItem, id: 'x4', task: 'Narxni tasdiqlash', needsConfirmation: true, owner: { speaker: null, name: null, kind: 'unknown' as const }, due: { date: '2026-10-12', time: '10:00', raw: null } },
    ];
    const b = buildBrief(base, meeting, summary().speakers, { actions: live })!;
    expect(b.lists.find((l) => l.key === 'actionItems')!.items.map((i) => i.text)).toEqual([
      // Odam yozgan ism spiker yorlig'idan ustun (server eksporti kabi).
      "Hisobotni yuborish (tahrirlangan). Mas'ul: Dilnoza. Muddat: 10-oktabr.",
      "✓ Shartnoma. Mas'ul: Jamoa. Muddat belgilanmagan.",
      "Narxni tasdiqlash. Mas'ul belgilanmagan. Muddat: 12-oktabr, 10:00. (aniqlashtirish kerak)",
    ]);
    // Bo'sh jonli ro'yxat - vazifa yo'q (xulosadagilar qaytib kelmaydi).
    expect(buildBrief(base, meeting, [], { actions: [] })!.lists.some((l) => l.key === 'actionItems')).toBe(false);
  });

  it('en labels, singular participant, hours without seconds', () => {
    const en = ownerExample({ language: 'en', title: 'CRM sync', purpose: null, overview: 'Short sync.', actionItems: [], openQuestions: [] });
    const b = buildBrief(en, { ...meeting, durationSec: 3725 }, [twoSpeakers[0]])!;
    expect(b.meta).toBe('October 10, 2026 (Saturday), 12:37 · 1 h 2 min · 1 participant');
    expect(briefToText(b).split('\n')).toEqual(['CRM sync', b.meta, '', 'In short: Short sync.', '', 'Key points:', ...b.lists[0].items.map((i) => `- ${i.text}`), '']);
  });

  it('missing parts are dropped; short_call without key points falls back to topics', () => {
    const bare = ownerExample({ purpose: null, keyPoints: [], actionItems: [], openQuestions: [] });
    const b = buildBrief(bare, meeting, twoSpeakers)!;
    expect(b.purpose).toBeNull();
    expect(b.lists).toEqual([]);
    expect(briefToText(b)).not.toContain('Maqsad');
    expect(briefToText(b)).not.toContain('Asosiy fikrlar');

    const topicsOnly = ownerExample({
      keyPoints: [],
      topics: [{ ...base.topics[0], keyPoints: [{ text: 'Narx 15 mln', sourceSegmentIds: [2], start: 4.3 }] }],
    });
    expect(buildBrief(topicsOnly, meeting, twoSpeakers)!.lists[0]).toEqual({ key: 'keyPoints', label: 'Asosiy fikr', items: [{ text: 'Narx 15 mln.', start: 4.3 }] });

    const topicNoPoints = ownerExample({ keyPoints: [], topics: [{ ...base.topics[0], summary: '[S1] narxni so\'radi', keyPoints: [] }] });
    expect(buildBrief(topicNoPoints, meeting, twoSpeakers)!.lists[0].items[0].text).toBe("1-ishtirokchi narxni so'radi.");

    // Ko'p fikr - eng ko'pi 6 ta.
    const many = ownerExample({ keyPoints: Array.from({ length: 9 }, (_, i) => ({ id: `K${i}`, text: `Fikr ${i}`, ...ev(i) })) });
    expect(buildBrief(many, meeting, twoSpeakers)!.lists[0].items).toHaveLength(6);

    // Hech narsa yo'q - blok yo'q.
    expect(buildBrief(ownerExample({ purpose: null, overview: '', keyPoints: [], actionItems: [], openQuestions: [] }), meeting, twoSpeakers)).toBeNull();
    expect(buildBrief(null, meeting)).toBeNull();
  });

  it('meta degrades gracefully: no recordedAt, no duration, speakers not separated', () => {
    const noSpk = ownerExample({ quality: { ...base.quality, speakersAvailable: false } });
    const b = buildBrief(noSpk, { titleSource: 'auto' }, [])!;
    // Sana xulosadan (vaqtsiz), davomiylik xulosadan; spikerlar ajratilmagan - son yozilmaydi.
    expect(b.meta).toBe('10-oktabr 2026 (shanba) · 1 daq 53 s');
    const none = buildBrief(ownerExample({ meeting: { ...ownerExample().meeting, date: '', durationSec: 0, speakerCount: 0 } }), {}, [])!;
    expect(none.meta).toBe('');
    expect(briefToText(none).startsWith('Transkripsiya va CRM integratsiyasi muhokamasi\n\nMaqsad:')).toBe(true);
  });

  it('a user-given title wins; speaker names and merges are applied', () => {
    expect(summaryTitle(base, { title: 'Mening nomim', titleSource: 'user' })).toBe('Mening nomim');
    expect(summaryTitle({ ...base, title: '' }, { title: 'Yozuv', titleSource: 'auto' })).toBe('Yozuv');
    const named = buildBrief(ownerExample(), meeting, [twoSpeakers[0], { ...twoSpeakers[1], name: 'Dilnoza' }])!;
    expect(named.lists.find((l) => l.key === 'actionItems')!.items[0].text).toBe("Skriptni yuborish. Mas'ul: Dilnoza. Muddat belgilanmagan.");
  });

  it('helpers: duration words, Russian plurals, dates', () => {
    expect(durationWords(113.2, 'uz')).toBe('1 daq 53 s');
    expect(durationWords(45, 'ru')).toBe('45 с');
    expect(durationWords(600, 'en')).toBe('10 min');
    expect(durationWords(7200, 'uz')).toBe('2 soat');
    expect(durationWords(null, 'uz')).toBe('');
    expect([1, 2, 4, 5, 11, 12, 21, 22, 25, 111].map((n) => pluralForm(n, 'ru'))).toEqual(['one', 'few', 'few', 'many', 'many', 'many', 'one', 'few', 'many', 'many']);
    expect(pluralForm(2, 'en')).toBe('many');
    expect(briefDate('2026-10-11T19:30:00Z', null, 'uz')).toBe('12-oktabr 2026 (dushanba), 00:30'); // Toshkent kuni
    expect(briefDate(null, '2026-10-11', 'en')).toBe('October 11, 2026 (Sunday)');
    expect(briefDate('bad', null, 'ru')).toBe('');
    // Gap chegarasi: bosh harf/raqam bilan boshlansa; "15 mln. so'm" bo'linmaydi.
    expect(firstSentences("Narx 15 mln. so'm bo'ldi. Ikkinchi gap! 3-gap? To'rtinchi.")).toBe("Narx 15 mln. so'm bo'ldi. Ikkinchi gap!");
    expect(firstSentences('Bitta gap')).toBe('Bitta gap');
    expect(firstSentences('Один. Два. Три.', 1)).toBe('Один.');
  });
});
