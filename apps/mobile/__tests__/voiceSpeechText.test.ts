/**
 * O'qishga tayyorlash: web `prepareSpeech` qoidalari (markdown, iqtiboslar, ro'yxat, jadval,
 * audit izi) + mobil qo'shimchalari (URL, vazifa kaliti, emoji, apostrof); transkript matni;
 * kirill javobni lotin ovoz o'qimaydi.
 */
import { answerBody, cleanForSpeech, displayText, isSpeakable } from '@/features/voice/speechText';

const TRAIL = [
  'Siz bugun kech qolmagansiz [T1].',
  '',
  "Tekshirilgan HRM ma'lumotlari:",
  '[T1] hrm_search_employees - employeeId=22 -> 1 ta',
  '[T2] hrm_attendance - month=9, year=2026 -> ok',
].join('\n');

describe('answerBody (web 1:1)', () => {
  it('cuts the audit trail and the line introducing it', () => {
    expect(answerBody(TRAIL)).toBe('Siz bugun kech qolmagansiz [T1].');
  });
  it('keeps an answer with no trail; an all-trail answer is read as is', () => {
    expect(answerBody('Salom.\nQalaysiz?')).toBe('Salom.\nQalaysiz?');
    const only = '[T1] hrm_x - ok';
    expect(answerBody(only)).toBe(only);
  });
});

describe('cleanForSpeech', () => {
  it('drops markdown emphasis, headings and code', () => {
    expect(cleanForSpeech("## Natija\n**Muhim:** ta'til `14` kun.\n```js\nx()\n```")).toBe("Natija. Muhim: ta'til 14 kun.");
  });

  it('removes citation, tool and evidence markers but keeps bracketed words', () => {
    expect(cleanForSpeech('Uch kishi kechikdi [T1, T2]. Qoida [1, 2] va [HR_045] (e1, e2) bo\'yicha [eslatma].')).toBe(
      "Uch kishi kechikdi. Qoida va bo'yicha [eslatma].",
    );
    expect(cleanForSpeech('Band (21) va (lavozimi) qoladi (e4).')).toBe('Band (21) va (lavozimi) qoladi.');
  });

  it('link text stays, URL goes; bare URLs are removed', () => {
    expect(cleanForSpeech('Batafsil [nizomda](https://x.uz/doc) va https://llm.brb-tech.uz/a?b=1 manzilida.')).toBe('Batafsil nizomda va manzilida.');
    expect(cleanForSpeech('Sayt: www.brb.uz bor.')).toBe('Sayt: bor.');
  });

  it('turns list items and table rows into sentence boundaries', () => {
    expect(cleanForSpeech('Kechikkanlar:\n- Ali\n- Vali\n1. Sardor')).toBe('Kechikkanlar: Ali. Vali. Sardor');
    expect(cleanForSpeech('| Ism | Soat |\n|---|---|\n| Ali | 9:15 |')).toBe('Ism, Soat. Ali, 9:15');
  });

  it("tidies punctuation left by removed markers (\"kechikdi [T1]:\" -> \"kechikdi:\")", () => {
    expect(cleanForSpeech('Bugun kechikdi [T1]:\n- Ali')).toBe('Bugun kechikdi: Ali');
  });

  it('task keys: leading "KEY: name" keeps the name; others vanish', () => {
    expect(cleanForSpeech('DVSIB-245: Hisobotni tayyorlash')).toBe('Hisobotni tayyorlash');
    expect(cleanForSpeech('- DVSIB-12 - Shartnoma (HR2-7) tayyor.')).toBe('Shartnoma tayyor.');
    expect(cleanForSpeech('Vazifa DVSIB-245 yopildi.')).toBe('Vazifa yopildi.');
    // So'z ichida yoki sana - kalit emas
    expect(cleanForSpeech('xDVSIB-1 va HR-2024-05 qoladi.')).toBe('xDVSIB-1 va HR-2024-05 qoladi.');
  });

  it('emoji vanish, arrows pause, long dashes become commas, apostrophes become ASCII', () => {
    expect(cleanForSpeech('Tayyor ✅ 👍 → keyingi — oxirgi')).toBe('Tayyor keyingi, oxirgi');
    expect(cleanForSpeech('Oʻzbekiston va gʼalaba ‘yaxshi’')).toBe("O'zbekiston va g'alaba 'yaxshi'");
    expect(cleanForSpeech('Ish vaqti 09:00-18:00 gacha.')).toBe('Ish vaqti 09:00-18:00 gacha.');
  });
});

describe('displayText', () => {
  it('keeps lines and [1] citations, drops tool marks, bold and the audit trail', () => {
    expect(displayText(TRAIL)).toBe('Siz bugun kech qolmagansiz.');
    expect(displayText('**Natija:**\n- Ali [1]\n* DVSIB-2 tayyor\n\n\n\nOxiri')).toBe('Natija:\n• Ali [1]\n• DVSIB-2 tayyor\n\nOxiri');
  });
});

describe('isSpeakable', () => {
  it('is false for a mostly Cyrillic answer or a non-uz UI', () => {
    expect(isSpeakable('Сегодня три сотрудника опоздали.', 'uz')).toBe(false);
    expect(isSpeakable("Bugun bo'limda uch kishi ishga kechikdi (Иванов).", 'uz')).toBe(true);
    expect(isSpeakable('Bugun uch kishi kechikdi.', 'ru')).toBe(false);
    expect(isSpeakable('12:30', 'uz')).toBe(true);
  });
});
