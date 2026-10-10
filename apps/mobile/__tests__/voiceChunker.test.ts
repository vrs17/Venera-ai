/**
 * Gap navbati: birinchi bo'lak qisqa (<=60, ibora chegarasida; chegara bo'lmasa gap butun
 * <=100), juda qisqa ochilish keyingi gap bilan qo'shiladi; keyingilar 1.5x o'sib <=350 ga
 * yig'iladi; oqimda yarim gap va "3." o'qilmaydi; qisqartma, bosh harf va ro'yxat raqami
 * gapni bo'lmaydi; audit izi va uni tanishtirgan `:` qatori o'qilmaydi; 3000 chegarasi.
 */
import { CHUNK, createSentenceQueue, nextBoundary, splitAt } from '@/features/voice/chunker';

/** >= FIRST_MIN (40) belgi: qisqa ochilish sifatida kutilmaydi/qo'shilmaydi. */
const FIRST = "Bugun bo'limda uch nafar xodim ishga kechikdi.";

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
  it('a long first sentence without a clause boundary <= 60 is cut at a clause <= 100, never mid-word', () => {
    const q = createSentenceQueue();
    const first = `Bugun bo'limda ${'xodimlar '.repeat(8)}ishga keldi, lekin ${'ba\'zilari '.repeat(10)}kechikdi.`;
    q.push(`${first} Ikkinchi gap. Uchinchi gap.`, true);
    const chunks = drain(q);
    expect(chunks[0].length).toBeGreaterThan(CHUNK.FIRST_MAX);
    expect(chunks[0].length).toBeLessThanOrEqual(CHUNK.FIRST_SOFT_MAX);
    expect(chunks[0].endsWith('ishga keldi,')).toBe(true);
    // Qolgan qism va keyingi gaplar bitta bo'lakka yig'iladi (1.5 x 100 = 150 ga sig'adi)
    expect(chunks).toHaveLength(2);
    expect(chunks[1].endsWith('Ikkinchi gap. Uchinchi gap.')).toBe(true);
    expect(q.finished).toBe(true);
  });

  it('the first chunk is cut at a clause boundary within 60 chars (~2 TTS pieces, ~2.2 s)', () => {
    const q = createSentenceQueue();
    const first = "Bugun sizning kalendaringizda uchta uchrashuv bor, birinchisi soat o'nda boshlanadi va bir soat davom etadi.";
    q.push(first, true);
    const chunks = drain(q);
    expect(chunks[0]).toBe('Bugun sizning kalendaringizda uchta uchrashuv bor,');
    expect(chunks[0].length).toBeLessThanOrEqual(CHUNK.FIRST_MAX);
    expect(chunks.join(' ')).toBe(first);
  });

  it('a first sentence of 61-100 chars without a clause boundary is taken whole', () => {
    const q = createSentenceQueue();
    const first = "Sizning bugungi vazifalaringiz ro'yxatida yangi mijoz kartasini yaratish va hisobot yuborish bor.";
    expect(first.length).toBeGreaterThan(CHUNK.FIRST_MAX);
    expect(first.length).toBeLessThanOrEqual(CHUNK.FIRST_SOFT_MAX);
    q.push(`${first} Keyingi gap.`, true);
    expect(q.take()).toBe(first);
  });

  it('a very short opener is joined with the next sentence (or its first clause) into the first chunk', () => {
    const q = createSentenceQueue();
    q.push('Albatta! Bugun sizda uchta uchrashuv bor. Birinchisi soat o\'nda.', true);
    expect(q.take()).toBe('Albatta! Bugun sizda uchta uchrashuv bor.');
    const q2 = createSentenceQueue();
    q2.push("Ha. Bugun bo'limda o'n ikki kishi ishga kelgan, ulardan uch nafari esa ertalabki yig'ilishga kechikib kelgan.", true);
    expect(drain(q2)).toEqual(["Ha. Bugun bo'limda o'n ikki kishi ishga kelgan,", "ulardan uch nafari esa ertalabki yig'ilishga kechikib kelgan."]);
    // Ibora chegarasi yo'q bo'lsa - qisqa ochilish yolg'iz (so'z o'rtasidan kesilmaydi).
    const q3 = createSentenceQueue();
    q3.push(`Ha. Bu ${'juda uzun '.repeat(12)}gap.`, true);
    expect(q3.take()).toBe('Ha.');
  });

  it('while streaming, a short opener waits (bounded) for the next sentence to join it', () => {
    const q = createSentenceQueue();
    q.push('Albatta! Bugun', false);
    // Javob token-token keladi: keyingi gap hali yo'q, lekin u birinchi bo'lakka sig'ishi mumkin.
    expect(q.take()).toBeNull();
    expect(q.finished).toBe(false);
    q.push('Albatta! Bugun sizda uchta uchrashuv bor. Bi', false);
    expect(q.take()).toBe('Albatta! Bugun sizda uchta uchrashuv bor.');
    // Keyingi gap sig'masligi aniq bo'lgach (oqayotgan qism uzun) - ochilish kutmasdan yolg'iz.
    const long = createSentenceQueue();
    long.push(`Albatta! Bugun ${'juda uzun matn '.repeat(4)}`, false);
    expect(long.take()).toBe('Albatta!');
    // Javob tugagan bo'lsa ham kutilmaydi.
    const done = createSentenceQueue();
    done.push('Albatta!', true);
    expect(done.take()).toBe('Albatta!');
  });

  it('openerWait marks the wait (text length) and releaseOpener() lets the opener go alone', () => {
    const q = createSentenceQueue();
    q.push('Albatta! Bu', false);
    expect(q.take()).toBeNull();
    expect(q.openerWait).toBe('Albatta! Bu'.length);
    q.push('Albatta! Bugun', false);
    expect(q.take()).toBeNull();
    expect(q.openerWait).toBe('Albatta! Bugun'.length);
    // Oqim to'xtab qoldi - gap navbati ochilishni yolg'iz aytadi.
    q.releaseOpener();
    expect(q.openerWait).toBeNull();
    expect(q.take()).toBe('Albatta!');
    expect(q.openerWait).toBeNull();
    // Hali to'liq gap yo'q - bu ochilish kutishi EMAS.
    expect(q.take()).toBeNull();
    expect(q.openerWait).toBeNull();
  });

  it('packs later sentences, growing at most 1.5x per chunk, up to 350', () => {
    const q = createSentenceQueue();
    const s = (i: number) => `Bu ${i}-gap qisqa matn.`;
    const all = Array.from({ length: 60 }, (_, i) => s(i + 1));
    q.push(all.join(' '), true);
    const chunks = drain(q);
    // Juda qisqa birinchi gap keyingisi bilan qo'shilgan
    expect(chunks[0]).toBe(`${s(1)} ${s(2)}`);
    for (let i = 1; i < chunks.length; i++) {
      expect(chunks[i].length).toBeLessThanOrEqual(CHUNK.MAX);
      expect(chunks[i].length).toBeLessThanOrEqual(Math.max(CHUNK.GROW_MIN, Math.round(CHUNK.GROW * (chunks[i - 1].length + 1))));
    }
    expect(Math.max(...chunks.map((c) => c.length))).toBeGreaterThan(CHUNK.MAX - 30);
    expect(chunks.length).toBeLessThan(15);
    expect(chunks.join(' ')).toBe(all.join(' '));
  });

  it('same-length sentences are not split just to grow', () => {
    const q = createSentenceQueue();
    const s = (i: number) => `Bu ${i}-gap bo'lib ${'uzunroq '.repeat(6)}matn.`;
    const all = Array.from({ length: 6 }, (_, i) => s(i + 1));
    q.push(all.join(' '), true);
    expect(drain(q)).toEqual(all);
  });

  it('streaming: a half sentence and a trailing "3." wait for more text', () => {
    const q = createSentenceQueue();
    q.push('Bugun uch', false);
    expect(q.take()).toBeNull();
    q.push(`${FIRST} Jami 3.`, false);
    expect(q.take()).toBe(FIRST);
    expect(q.take()).toBeNull();
    q.push(`${FIRST} Jami 3.5 soat`, false);
    expect(q.take()).toBeNull();
    q.push(`${FIRST} Jami 3.5 soat.`, true);
    expect(q.take()).toBe('Jami 3.5 soat.');
    expect(q.finished).toBe(true);
  });

  it('the same text pushed twice is idempotent', () => {
    const q = createSentenceQueue();
    q.push(`${FIRST} Qalay`, false);
    q.push(`${FIRST} Qalay`, false);
    expect(drain(q)).toEqual([FIRST]);
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

describe('chunk growth (no silence between clips) - measured TTS model', () => {
  // Prod o'lchovi (2026-10-10): ovoz ~78 ms/belgi; TTS matnni ~2.45 s ovozli bo'laklarga bo'lib
  // ketma-ket sintez qiladi, har biri ~1.1 s (44 belgi 1.19 s, 60 -> 2.24 s, 164 -> 6.50 s, 254 -> 9.74 s).
  const audioMs = (chars: number) => chars * 78;
  const synthMs = (chars: number, slow = 1) => slow * 1100 * Math.ceil(audioMs(chars) / 2450);
  const answer = [
    'Bugun uch kishi kechikdi: Ali, Vali va Sardor.',
    "Ali 15 daqiqaga kechikdi, sababi tirbandlik bo'lgan.",
    "Vali esa 40 daqiqaga kechikdi va bu haftada uchinchi marta, rahbariyatga xabar berilgan.",
    "Sardor ertalabki yig'ilishga umuman kelmadi, lekin keyin tushdan oldin ishga keldi va tushuntirish xati yozdi.",
    "Qolgan xodimlar o'z vaqtida kelgan, bo'lim bo'yicha davomat 92 foizni tashkil qildi.",
    "Agar xohlasangiz, har bir xodim bo'yicha batafsil hisobotni ham tayyorlab beraman.",
  ].join(' ');

  it('the first chunk is synthesized in ~2 TTS pieces and each later chunk while the previous one plays', () => {
    const q = createSentenceQueue();
    q.push(answer, true);
    const chunks = drain(q);
    expect(chunks[0]).toBe('Bugun uch kishi kechikdi: Ali, Vali va Sardor.');
    expect(synthMs(chunks[0].length)).toBeLessThanOrEqual(2200);
    for (let i = 1; i < chunks.length; i++) {
      expect(synthMs(chunks[i].length)).toBeLessThanOrEqual(audioMs(chunks[i - 1].length));
      expect(chunks[i].length).toBeLessThanOrEqual(CHUNK.MAX);
    }
    expect(chunks.join(' ')).toBe(answer);
  });

  it('a split never leaves a short tail chunk (it would play ~2 s while the next one needs longer)', () => {
    const q = createSentenceQueue();
    q.push(answer, true);
    const chunks = drain(q);
    // 88 belgilik gap 80 lik chegarada bo'linsa 28 belgilik dum qolardi - u butun olinadi.
    expect(chunks).toContain("Vali esa 40 daqiqaga kechikdi va bu haftada uchinchi marta, rahbariyatga xabar berilgan.");
    for (const c of chunks.slice(1, -1)) expect(c.length).toBeGreaterThanOrEqual(CHUNK.CLAUSE_MIN);
  });

  it('a long first sentence no longer delays the first sound by ~6 s (old rule: whole sentence up to 160)', () => {
    const q = createSentenceQueue();
    const first = "Hisobot bo'yicha bugun bo'limda o'n ikki kishi ishga kelgan, ulardan uch nafari kechikkan, ikki nafari esa kasallik sababli uyda qolgan va bu haqda rahbarga xabar bergan.";
    q.push(first, true);
    const chunks = drain(q);
    expect(synthMs(chunks[0].length)).toBeLessThanOrEqual(2200);
    expect(synthMs(first.length)).toBeGreaterThan(5000);
    for (let i = 1; i < chunks.length; i++) expect(synthMs(chunks[i].length)).toBeLessThanOrEqual(audioMs(chunks[i - 1].length));
  });

  it('a long single sentence after a short opener is split at clauses, growing from the first chunk', () => {
    const q = createSentenceQueue();
    q.push(`Salom. ${'Bu gap juda uzun bo\'lib, '.repeat(12)}oxiri shu.`, true);
    const chunks = drain(q);
    expect(chunks[0]).toBe("Salom. Bu gap juda uzun bo'lib, Bu gap juda uzun bo'lib,");
    expect(chunks[1].length).toBeLessThanOrEqual(Math.round(CHUNK.GROW * (chunks[0].length + 1)));
    expect(chunks[1].endsWith(',')).toBe(true);
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
