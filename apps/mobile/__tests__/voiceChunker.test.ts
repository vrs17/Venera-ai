/**
 * Gap navbati: birinchi bo'lak qisqa (<=160, vergulda bo'linadi), keyingilar <=350 ga
 * yig'iladi; oqimda yarim gap va "3." o'qilmaydi; qisqartma, bosh harf va ro'yxat raqami
 * gapni bo'lmaydi; audit izi va uni tanishtirgan `:` qatori o'qilmaydi; 3000 chegarasi.
 */
import { CHUNK, createSentenceQueue, nextBoundary, splitAt } from '@/features/voice/chunker';

function drain(q: ReturnType<typeof createSentenceQueue>): string[] {
  const out: string[] = [];
  for (let c = q.take(); c !== null; c = q.take()) out.push(c);
  return out;
}

describe('nextBoundary', () => {
  it('does not split abbreviations, initials, list numbers or decimals', () => {
    const text = "Hujjat, ariza va h.k. bo'yicha A. Karimov javob berdi. Keyingisi.";
    expect(text.slice(0, nextBoundary(text, 0, true))).toBe("Hujjat, ariza va h.k. bo'yicha A. Karimov javob berdi.");
    const list = '1. Birinchi band 3.5 foiz. Ikkinchi.';
    expect(list.slice(0, nextBoundary(list, 0, true))).toBe('1. Birinchi band 3.5 foiz.');
    const ru = 'Сотрудники, т.е. все отделы. Дальше.';
    expect(ru.slice(0, nextBoundary(ru, 0, true))).toBe('Сотрудники, т.е. все отделы.');
  });

  it('while streaming, needs to see the next character after a sentence end', () => {
    expect(nextBoundary('Jami 3.', 0, false)).toBe(-1);
    expect(nextBoundary('Jami 3. ', 0, false)).toBe(-1);
    expect(nextBoundary('Jami 3. K', 0, false)).toBe(7);
    expect(nextBoundary('Jami 3.5', 0, false)).toBe(-1);
    // Yopilmagan kod/havola ichida chegara qidirilmaydi
    expect(nextBoundary('Qarang [hujjat. B', 0, false)).toBe(-1);
    expect(nextBoundary('Kod ```a. B', 0, false)).toBe(-1);
  });
});

describe('splitAt', () => {
  it('prefers a clause boundary, then a space', () => {
    const s = `${'a'.repeat(50)}, ${'b'.repeat(80)} ${'c'.repeat(60)}`;
    const [head, rest] = splitAt(s, 160, 40);
    expect(head).toBe(`${'a'.repeat(50)},`);
    expect(rest.startsWith('b')).toBe(true);
    const words = Array.from({ length: 60 }, () => 'soz').join(' ');
    const [h2] = splitAt(words, 160, 40);
    expect(h2.length).toBeLessThanOrEqual(160);
    expect(h2.endsWith('soz')).toBe(true);
  });
});

describe('createSentenceQueue', () => {
  it('first chunk is the first sentence only (split at a comma when > 160)', () => {
    const q = createSentenceQueue();
    const first = `Bugun bo'limda ${'xodimlar '.repeat(8)}ishga keldi, lekin ${'ba\'zilari '.repeat(10)}kechikdi.`;
    q.push(`${first} Ikkinchi gap. Uchinchi gap.`, true);
    const chunks = drain(q);
    expect(chunks[0].length).toBeLessThanOrEqual(CHUNK.FIRST_MAX);
    expect(chunks[0].endsWith(',')).toBe(true);
    // Qolgan qism va keyingi gaplar bitta <=350 bo'lakka yig'iladi
    expect(chunks).toHaveLength(2);
    expect(chunks[1].endsWith('Ikkinchi gap. Uchinchi gap.')).toBe(true);
    expect(q.finished).toBe(true);
  });

  it('packs later sentences greedily up to 350', () => {
    const q = createSentenceQueue();
    const s = (i: number) => `Bu ${i}-gap bo'lib ${'uzunroq '.repeat(6)}matn.`;
    q.push(Array.from({ length: 20 }, (_, i) => s(i + 1)).join(' '), true);
    const chunks = drain(q);
    expect(chunks[0]).toBe(s(1));
    for (const c of chunks.slice(1)) expect(c.length).toBeLessThanOrEqual(CHUNK.MAX);
    expect(chunks.length).toBeLessThan(20);
    expect(chunks.join(' ')).toBe(Array.from({ length: 20 }, (_, i) => s(i + 1)).join(' '));
  });

  it('streaming: a half sentence and a trailing "3." wait for more text', () => {
    const q = createSentenceQueue();
    q.push('Bugun uch', false);
    expect(q.take()).toBeNull();
    q.push('Bugun uch kishi kechikdi. Jami 3.', false);
    expect(q.take()).toBe('Bugun uch kishi kechikdi.');
    expect(q.take()).toBeNull();
    q.push('Bugun uch kishi kechikdi. Jami 3.5 soat', false);
    expect(q.take()).toBeNull();
    q.push('Bugun uch kishi kechikdi. Jami 3.5 soat.', true);
    expect(q.take()).toBe('Jami 3.5 soat.');
    expect(q.finished).toBe(true);
  });

  it('the same text pushed twice is idempotent', () => {
    const q = createSentenceQueue();
    q.push('Salom. Qalay', false);
    q.push('Salom. Qalay', false);
    expect(drain(q)).toEqual(['Salom.']);
  });

  it('a "...:" line is held while streaming and dropped with the audit trail', () => {
    const q = createSentenceQueue();
    q.push('Siz kech qolmagansiz [T1].\n\nTekshirilgan HRM ma\'lumotlari:\n', false);
    expect(drain(q)).toEqual(['Siz kech qolmagansiz.']);
    q.push("Siz kech qolmagansiz [T1].\n\nTekshirilgan HRM ma'lumotlari:\n[T", false);
    expect(q.take()).toBeNull();
    q.push("Siz kech qolmagansiz [T1].\n\nTekshirilgan HRM ma'lumotlari:\n[T1] hrm_x - ok\n[T2] hrm_y", false);
    expect(q.take()).toBeNull();
    // Iz boshlandi - javob hali oqayotgan bo'lsa ham navbat tugagan
    expect(q.finished).toBe(true);
  });

  it('a held "...:" line is spoken when a normal line follows', () => {
    const q = createSentenceQueue();
    q.push('Kechikkanlar:\n- Ali\n- Vali', true);
    expect(drain(q).join(' ')).toBe('Kechikkanlar: Ali. Vali.');
  });

  it('stops at the 3000 limit on a sentence boundary and reports shortened', () => {
    const q = createSentenceQueue();
    const sentence = `${'Bu juda uzun javobning bir qismi '.repeat(3)}hisoblanadi.`;
    q.push(Array.from({ length: 60 }, () => sentence).join(' '), true);
    const chunks = drain(q);
    const total = chunks.reduce((n, c) => n + c.length, 0);
    expect(total).toBeLessThanOrEqual(CHUNK.TOTAL_LIMIT);
    expect(chunks[chunks.length - 1].endsWith('hisoblanadi.')).toBe(true);
    expect(q.shortened).toBe(true);
    expect(q.finished).toBe(true);
  });

  it('an answer with nothing speakable finishes with no chunks', () => {
    const q = createSentenceQueue();
    q.push('```\nkod\n```\n[T1] hrm_x - ok', true);
    expect(q.take()).toBeNull();
    expect(q.finished).toBe(true);
    expect(q.taken).toBe(0);
  });
});

describe('chunk growth (no silence between the first and second clip)', () => {
  // Spec o'lchovlari: 66 ms ovoz / belgi; sintez 4.7x real vaqtdan tez + ~1.1 s birinchi bayt.
  const audioMs = (chars: number) => chars * 66;
  const synthMs = (chars: number) => 1100 + (chars * 66) / 4.7;

  it('each later chunk is synthesized while the previous one plays', () => {
    const q = createSentenceQueue();
    const answer = [
      'Bugun uch kishi kechikdi: Ali, Vali va Sardor.',
      "Ali 15 daqiqaga kechikdi, sababi tirbandlik bo'lgan.",
      "Vali esa 40 daqiqaga kechikdi va bu haftada uchinchi marta, rahbariyatga xabar berilgan.",
      "Sardor ertalabki yig'ilishga umuman kelmadi, lekin keyin tushdan oldin ishga keldi va tushuntirish xati yozdi.",
      "Qolgan xodimlar o'z vaqtida kelgan, bo'lim bo'yicha davomat 92 foizni tashkil qildi.",
      "Agar xohlasangiz, har bir xodim bo'yicha batafsil hisobotni ham tayyorlab beraman.",
    ].join(' ');
    q.push(answer, true);
    const chunks = drain(q);
    expect(chunks[0]).toBe('Bugun uch kishi kechikdi: Ali, Vali va Sardor.');
    // Ochko'z yig'ish bo'lganda ikkinchi bo'lak ~300+ belgi bo'lib, orada ~2.4 s jimlik qolardi.
    for (let i = 1; i < chunks.length; i++) {
      expect(synthMs(chunks[i].length)).toBeLessThanOrEqual(audioMs(chunks[i - 1].length));
      expect(chunks[i].length).toBeLessThanOrEqual(CHUNK.MAX);
    }
    expect(chunks.join(' ')).toBe(answer);
  });

  it('a long single sentence after a short first chunk is split at a clause, not sent whole', () => {
    const q = createSentenceQueue();
    q.push(`Salom. ${'Bu gap juda uzun bo\'lib, '.repeat(12)}oxiri shu.`, true);
    const chunks = drain(q);
    expect(chunks[0]).toBe('Salom.');
    expect(chunks[1].length).toBeLessThanOrEqual(CHUNK.GROW_MIN);
  });

  it('skip() resumes after the spoken part; a half-spoken sentence is read again from its start', () => {
    const text = 'Birinchi gap. Ikkinchi gap. Uchinchi gap. To\'rtinchi gap.';
    const full = createSentenceQueue();
    full.push(text, true);
    const all = drain(full);
    // Birinchi ikki bo'lak oxirigacha yangradi: har biri `uzunlik + 1`.
    const spoken = all.slice(0, 2).reduce((n, c) => n + c.length + 1, 0);
    const q = createSentenceQueue();
    q.push(text, true);
    q.skip(spoken);
    const rest = drain(q);
    expect(rest.join(' ')).toBe(all.slice(2).join(' '));
    const half = createSentenceQueue();
    half.push(text, true);
    half.skip('Birinchi gap.'.length + 1 + 5);
    expect(drain(half)[0].startsWith('Ikkinchi gap.')).toBe(true);
  });
});
