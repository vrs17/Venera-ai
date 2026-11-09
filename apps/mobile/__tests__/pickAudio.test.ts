/**
 * "Audio yuklash" ning sof mantig'i: tanlangan fayllar `imports/` ga native ImportActivity bergan
 * nom (`share_<to'plam>_<tartib>_<o'zak>.<kengaytma>`) va `<nom>.json` meta bilan tushadi. Turlar -
 * serverning beshtasi (m4a, aac, mp3, wav, ogg); mazmun boshi kengaytmaga zid bo'lsa - sababi bilan
 * rad etiladi; 160 MB, joy va 20 ta cheklovi native bilan bir xil. Native qatlam o'rniga xotiradagi
 * soxta papka.
 */
import { buildImportPath, parseImportParams } from '@/features/entry/deepLink';
import {
  audioUploadSupported,
  headerProblem,
  importFileName,
  importPickedAudio,
  importStem,
  MAX_COPY_BYTES,
  PICK_MIME_TYPES,
  RESERVE_BYTES,
  uniqueImportName,
  type ImportMetaFile,
  type ImportsDir,
  type PickedAudio,
} from '@/features/calls/pickAudio';
import { pickFailedText } from '@/features/calls/useAudioUpload';
import { makeT } from '@/i18n';

import { isImportFileName, MAX_SHARED_FILES } from '../modules/venera-entry/importNames';

const BATCH = 1728560000000;
const MP4 = Uint8Array.from([0, 0, 0, 0x20, ...Array.from('ftypM4A ', (c) => c.charCodeAt(0)), 0, 0, 0, 0]);
const ADTS = Uint8Array.from([0xff, 0xf1, 0x50, 0x80, 0x01, 0x7f, 0xfc, 0, 0, 0, 0, 0, 0, 0]);
const PDF = Uint8Array.from(Array.from('%PDF-1.7 something', (c) => c.charCodeAt(0)));
const ascii = (s: string) => Array.from(s, (c) => c.charCodeAt(0));
// MP3: ID3 tegi yoki MPEG-1 Layer III kadri (0xFFFB); WAV: RIFF....WAVE; Ogg: OggS.
const MP3 = Uint8Array.from([...ascii('ID3'), 4, 0, 0, 0, 0, 0x21, 0x76, 0, 0, 0]);
const MP3_FRAME = Uint8Array.from([0xff, 0xfb, 0x90, 0x64, 0, 0, 0, 0, 0, 0, 0, 0]);
const WAV = Uint8Array.from([...ascii('RIFF'), 0x24, 0x08, 0, 0, ...ascii('WAVEfmt ')]);
const OGG = Uint8Array.from([...ascii('OggS'), 0, 2, 0, 0, 0, 0, 0, 0]);

/** Xotiradagi `imports/`: manba URI -> baytlar, nusxa/meta/o'chirish yozib boriladi. */
function fakeDir(sources: Record<string, Uint8Array | Error>, opts: { free?: number | null; taken?: string[] } = {}) {
  const files = new Map<string, Uint8Array>((opts.taken ?? []).map((n) => [n, MP4]));
  const metas = new Map<string, ImportMetaFile>();
  const removed: string[] = [];
  const sweeps: number[] = [];
  const dir: ImportsDir = {
    exists: (name) => files.has(name),
    copyIn: jest.fn(async (src: string, name: string) => {
      const data = sources[src];
      if (!data || data instanceof Error) throw data ?? new Error('ERR_READ');
      files.set(name, data);
      return data.length;
    }),
    head: (name, n) => (files.get(name) ?? new Uint8Array()).slice(0, n),
    writeMeta: (name, meta) => void metas.set(name, meta),
    readMeta: (name) => (metas.has(name) ? { ...metas.get(name) } : null),
    stat: (name) => (files.has(name) ? { path: `/data/user/0/app/files/imports/${name}`, size: files.get(name)!.length } : null),
    remove: (name) => {
      removed.push(name);
      files.delete(name);
    },
    freeBytes: () => (opts.free === undefined ? 10 * 1024 * 1024 * 1024 : opts.free),
    sweep: (now) => void sweeps.push(now),
  };
  return { dir, files, metas, removed, sweeps };
}

const asset = (over: Partial<PickedAudio> & { uri: string }): PickedAudio => ({ name: 'x.m4a', size: 1000, mimeType: 'audio/mp4', lastModified: BATCH - 60_000, ...over });

describe('pickAudio: names exactly like the native ImportActivity', () => {
  it('stem: ASCII only, no dots, trimmed, 40 chars; Cyrillic names become "audio"', () => {
    expect(importStem('Call recording Alisher_241010_143012.m4a')).toBe('Call_recording_Alisher_241010_143012');
    expect(importStem('Йиғилиш 10-ноябр.m4a')).toBe('10');
    expect(importStem('Йиғилиш.m4a')).toBe('audio');
    expect(importStem('a.b.c.aac')).toBe('a_b_c');
    expect(importStem('../../databases/venera.m4a')).toBe('venera');
    expect(importStem('__-x-__.m4a')).toBe('x');
    expect(importStem(`${'a'.repeat(39)}_b.m4a`)).toBe('a'.repeat(39));
    expect(importStem(null)).toBe('audio');
  });

  it('file name = share_<batch>_<index>_<stem>.<ext> and passes the deep-link name check', () => {
    // ImportScreen testidagi native nomi bilan aynan bir xil.
    expect(importFileName(BATCH, 0, 'Call recording Alisher_241010_143012.m4a', 'audio/mp4')).toBe('share_1728560000000_0_Call_recording_Alisher_241010_143012.m4a');
    expect(importFileName(BATCH, 3, 'notes', 'audio/aac')).toBe('share_1728560000000_3_notes.aac');
    for (const n of ['Йиғилиш.m4a', 'a'.repeat(300), '../x.aac', '..', '']) expect(isImportFileName(importFileName(BATCH, 19, n, 'audio/mp4'))).toBe(true);
  });

  it('a taken name gets -1, -2 ... like CallImport.uniqueFile', () => {
    const taken = new Set(['a.m4a', 'a-1.m4a']);
    expect(uniqueImportName('a.m4a', (n) => taken.has(n))).toBe('a-2.m4a');
    expect(uniqueImportName('b.m4a', (n) => taken.has(n))).toBe('b.m4a');
  });

  it('extension comes from the type: .m4a, .aac, .mp3, .wav, .ogg (Opus/oga files are stored as .ogg)', () => {
    expect(importFileName(BATCH, 0, 'Kengash.MP3', 'audio/mpeg')).toBe('share_1728560000000_0_Kengash.mp3');
    expect(importFileName(BATCH, 1, 'dictaphone.wav', 'audio/wav')).toBe('share_1728560000000_1_dictaphone.wav');
    expect(importFileName(BATCH, 2, 'voice.opus', 'audio/ogg')).toBe('share_1728560000000_2_voice.ogg');
    for (const type of ['audio/mpeg', 'audio/wav', 'audio/ogg'] as const) expect(isImportFileName(importFileName(BATCH, 0, 'x', type))).toBe(false); // native nomi emas - JS yo'li
  });

  it('content check per type (server sniff): match -> ok, another known format -> mismatch, junk -> unsupported', () => {
    expect(headerProblem(MP4, 'audio/mp4')).toBeNull();
    expect(headerProblem(ADTS, 'audio/aac')).toBeNull();
    expect(headerProblem(MP3, 'audio/mpeg')).toBeNull();
    expect(headerProblem(MP3_FRAME, 'audio/mpeg')).toBeNull();
    expect(headerProblem(WAV, 'audio/wav')).toBeNull();
    expect(headerProblem(OGG, 'audio/ogg')).toBeNull();
    // Kengaytma va mazmun zid: ".mp3" ichida WAV, ".aac" ichida MP3 kadri, ".m4a" ichida Ogg.
    expect(headerProblem(WAV, 'audio/mpeg')).toBe('mismatch');
    expect(headerProblem(MP3_FRAME, 'audio/aac')).toBe('mismatch');
    expect(headerProblem(ADTS, 'audio/mpeg')).toBe('mismatch');
    expect(headerProblem(OGG, 'audio/mp4')).toBe('mismatch');
    expect(headerProblem(PDF, 'audio/wav')).toBe('unsupported');
    expect(headerProblem(new Uint8Array(), 'audio/ogg')).toBe('unsupported');
  });

  it('the picker also offers application/ogg (Opus labelled that way is not audio/*)', () => {
    expect([...PICK_MIME_TYPES]).toEqual(['audio/*', 'application/ogg']);
  });
});

describe('pickAudio: importPickedAudio (same limits as the share flow)', () => {
  it('copies accepted files into imports/ with share metadata and returns a valid /import link', async () => {
    const f = fakeDir({ 'content://a': MP4, 'content://b': ADTS });
    const out = await importPickedAudio(
      f.dir,
      [
        asset({ uri: 'content://a', name: 'Mijoz bilan uchrashuv.m4a', size: 1000, lastModified: BATCH - 3_600_000 }),
        // Kengaytmasiz, MIME bo'yicha AAC.
        asset({ uri: 'content://b', name: 'voice', mimeType: 'audio/aac', lastModified: 0 }),
      ],
      { now: () => BATCH },
    );
    expect(out).toEqual({ files: ['share_1728560000000_0_Mijoz_bilan_uchrashuv.m4a', 'share_1728560000000_1_voice.aac'], skipped: 0, reason: null });
    expect(f.metas.get(out.files[0])).toEqual({
      displayName: 'Mijoz bilan uchrashuv.m4a',
      contentType: 'audio/mp4',
      sizeBytes: MP4.length,
      durationMs: 0,
      dateMs: BATCH - 3_600_000,
      source: 'share',
    });
    // Noma'lum sana - null (tasdiq ekrani "hozir" deb oladi).
    expect(f.metas.get(out.files[1])).toMatchObject({ contentType: 'audio/aac', dateMs: null, source: 'share' });
    // Eskirgan tasdiqlanmagan nusxalar tozalanadi (native kabi).
    expect(f.sweeps).toEqual([BATCH]);
    // Deep link tozalovchisidan o'zgarmay o'tadi.
    const path = buildImportPath({ files: out.files, skipped: out.skipped, n: '5' });
    expect(path).toBe('/import?files=share_1728560000000_0_Mijoz_bilan_uchrashuv.m4a,share_1728560000000_1_voice.aac&n=5');
    expect(parseImportParams({ files: out.files.join(','), n: '5' }).files).toEqual(out.files);
  });

  it('mp3, wav and ogg/opus are accepted with their own type, extension and metadata', async () => {
    const f = fakeDir({ 'content://a': MP3, 'content://b': WAV, 'content://c': OGG, 'content://d': MP3_FRAME });
    const out = await importPickedAudio(
      f.dir,
      [
        asset({ uri: 'content://a', name: 'Kengash 9-noyabr.mp3', mimeType: 'audio/mpeg' }),
        asset({ uri: 'content://b', name: 'diktofon.WAV', mimeType: 'audio/x-wav' }),
        // Telegram ovozli xabari: kengaytmasiz, `application/ogg` deb keladi.
        asset({ uri: 'content://c', name: 'voice', mimeType: 'application/ogg' }),
        asset({ uri: 'content://d', name: 'zoom', mimeType: 'audio/mp3' }),
      ],
      { now: () => BATCH },
    );
    expect(out).toEqual({
      files: ['share_1728560000000_0_Kengash_9-noyabr.mp3', 'share_1728560000000_1_diktofon.wav', 'share_1728560000000_2_voice.ogg', 'share_1728560000000_3_zoom.mp3'],
      skipped: 0,
      reason: null,
    });
    expect(out.files.map((n) => f.metas.get(n)?.contentType)).toEqual(['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/mpeg']);
    expect(f.metas.get(out.files[1])).toEqual({ displayName: 'diktofon.WAV', contentType: 'audio/wav', sizeBytes: WAV.length, durationMs: 0, dateMs: BATCH - 60_000, source: 'share' });
    // Tasdiq ekraniga deep link tozalovchisidan o'zgarmay o'tadi (JS nomlari ham).
    expect(parseImportParams({ files: out.files.join(','), n: '1' }).files).toEqual(out.files);
  });

  it('unsupported formats are not copied; a header that contradicts the extension is copied, checked and removed', async () => {
    const f = fakeDir({ 'content://flac': MP4, 'content://fake': PDF, 'content://lie': WAV });
    const out = await importPickedAudio(
      f.dir,
      [
        asset({ uri: 'content://flac', name: 'song.flac', mimeType: 'audio/mpeg' }),
        asset({ uri: 'content://fake', name: 'report.m4a' }),
        // ".mp3" deyilgan, ichida WAV - server birinchi bo'lakdayoq 415 berardi.
        asset({ uri: 'content://lie', name: 'meeting.mp3', mimeType: 'audio/mpeg' }),
      ],
      { now: () => BATCH },
    );
    expect(out).toEqual({ files: [], skipped: 3, reason: 'unsupported' });
    expect(f.dir.copyIn).toHaveBeenCalledTimes(2);
    expect(f.removed).toEqual(['share_1728560000000_1_report.m4a', 'share_1728560000000_2_meeting.mp3']);
    expect(f.files.size).toBe(0);

    const mismatch = fakeDir({ 'content://lie': WAV });
    expect(await importPickedAudio(mismatch.dir, [asset({ uri: 'content://lie', name: 'meeting.mp3' })], { now: () => BATCH })).toEqual({
      files: [],
      skipped: 1,
      reason: 'mismatch',
    });
  });

  it('size and space: over 160 MB is never copied; too little free space (50 MB reserve) is refused', async () => {
    const big = fakeDir({ 'content://big': MP4 });
    expect(await importPickedAudio(big.dir, [asset({ uri: 'content://big', size: MAX_COPY_BYTES + 1 })])).toEqual({ files: [], skipped: 1, reason: 'too_large' });
    expect(big.dir.copyIn).not.toHaveBeenCalled();

    const full = fakeDir({ 'content://a': MP4 }, { free: 1000 + RESERVE_BYTES - 1 });
    expect(await importPickedAudio(full.dir, [asset({ uri: 'content://a', size: 1000 })])).toEqual({ files: [], skipped: 1, reason: 'no_space' });
    // Hajm noma'lum - nusxalanadi, keyin haqiqiy hajm tekshiriladi.
    const unknown = fakeDir({ 'content://a': MP4 }, { free: 0 });
    expect((await importPickedAudio(unknown.dir, [asset({ uri: 'content://a', size: null })])).files).toHaveLength(1);
  });

  it('read failures and empty files are skipped (and leave nothing behind); the first reason is reported', async () => {
    const f = fakeDir({ 'content://gone': new Error('ERR_READ'), 'content://empty': new Uint8Array(), 'content://ok': MP4 });
    const out = await importPickedAudio(
      f.dir,
      [asset({ uri: 'content://gone' }), asset({ uri: 'content://empty' }), asset({ uri: 'content://ok' })],
      { now: () => BATCH },
    );
    expect(out).toEqual({ files: ['share_1728560000000_2_x.m4a'], skipped: 2, reason: 'read' });
    expect(f.removed).toEqual(['share_1728560000000_1_x.m4a']);
  });

  it('never overwrites an existing import; at most 20 files, the rest are counted as skipped', async () => {
    const taken = fakeDir({ 'content://a': MP4 }, { taken: ['share_1728560000000_0_x.m4a'] });
    expect((await importPickedAudio(taken.dir, [asset({ uri: 'content://a' })], { now: () => BATCH })).files).toEqual(['share_1728560000000_0_x-1.m4a']);

    const many = Array.from({ length: MAX_SHARED_FILES + 3 }, (_, i) => asset({ uri: `content://${i}` }));
    const f = fakeDir(Object.fromEntries(many.map((a) => [a.uri, MP4])));
    const out = await importPickedAudio(f.dir, many, { now: () => BATCH });
    expect(out.files).toHaveLength(MAX_SHARED_FILES);
    expect(out.skipped).toBe(3);
    expect(out.reason).toBeNull();
  });

  it('without the native import module (Jest, iOS) the upload button is not offered', () => {
    expect(audioUploadSupported()).toBe(false);
  });
});

describe('pickAudio: why nothing was added (toast)', () => {
  const t = makeT('uz');
  it('names the cause and, for size, the server limit', () => {
    expect(pickFailedText(t, 'unsupported', null)).toBe("Audio qo'shilmadi: faqat .m4a, .aac, .mp3, .wav yoki .ogg audio qabul qilinadi");
    expect(pickFailedText(t, 'mismatch', null)).toBe("Audio qo'shilmadi: fayl ichidagi format kengaytmasiga mos emas");
    expect(pickFailedText(makeT('ru'), 'unsupported', null)).toBe('Аудио не добавлено: подходят только аудио .m4a, .aac, .mp3, .wav и .ogg');
    expect(pickFailedText(t, 'too_large', 157286400)).toBe("Audio qo'shilmadi: fayl 150 MB dan katta");
    expect(pickFailedText(t, 'too_large', null)).toBe("Audio qo'shilmadi: fayl 160 MB dan katta");
    expect(pickFailedText(t, 'no_space', null)).toBe("Audio qo'shilmadi: telefonda joy kam - joy bo'shating");
    expect(pickFailedText(t, 'read', null)).toBe("Audio qo'shilmadi: faylni o'qib bo'lmadi");
    expect(pickFailedText(makeT('en'), 'unsupported', null)).toBe('Audio not added: only .m4a, .aac, .mp3, .wav or .ogg audio is accepted');
    expect(pickFailedText(makeT('en'), 'mismatch', null)).toBe("Audio not added: the file's content doesn't match its extension");
  });
});
