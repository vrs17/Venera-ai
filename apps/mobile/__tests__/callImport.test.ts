/**
 * Qo'ng'iroq yozuvlari importi (sof mantiq): Samsung nomini o'qish, takror yubormaslik
 * (deterministik clientId + yuborilganlar ro'yxati), navbat qatori (contentType, source,
 * sarlavha, vaqt), avtomatik yuborish xavfsizligi va calls holati (egasi, chegaralar).
 */
import { translate } from '@/i18n';
import type { CallRecording, ImportMeta } from '@/features/entry/nativeEntry';
import { MAX_PER_RUN, pickAutoSend, QUIET_MS, runAutoSendOnce, type SizeMemory } from '@/features/calls/autoSend';
import { __setCallsStorage, DEFAULT_CALLS, MAX_SENT, parseCallsPrefs, pruneSent, useCalls } from '@/features/calls/callsStore';
import { formatSize, importTitle, parseCallFileName, recordedAtMs } from '@/features/calls/fileName';
import { limitMb, toastSendOutcome } from '@/features/calls/feedback';
import { callsHubValue } from '@/features/calls/hub';
import { callClientId, callKey, isStillWriting, sendCallRecording, sendImportedFile, type CallSendDeps, type ImportSendDeps, type SendOptions } from '@/features/calls/send';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import { UUID_RE } from '@/lib/uuid';
import { showToast } from '@/ui/errors';

jest.mock('@/ui/errors', () => ({ ...jest.requireActual('@/ui/errors'), showToast: jest.fn() }));

const t = ((k: string, p?: Record<string, string | number>) => translate('uz', k as never, p)) as SendOptions['t'];
const local = (y: number, mo: number, d: number, h: number, mi: number, s: number) => new Date(y, mo - 1, d, h, mi, s).getTime();

const NOW = local(2024, 10, 10, 16, 0, 0);

function rec(over: Partial<CallRecording> = {}): CallRecording {
  return {
    uri: 'content://media/external/audio/media/41',
    displayName: 'Call recording Alisher_241010_143012.m4a',
    relativePath: 'Recordings/Call/',
    sizeBytes: 2_400_000,
    durationMs: 185_000,
    dateMs: local(2024, 10, 10, 14, 33, 17),
    mimeType: 'audio/mp4',
    contentType: 'audio/mp4',
    ...over,
  };
}

describe('Samsung call file names', () => {
  it('reads the counterpart and the start time (One UI 4+, older, numbers, Russian, long year)', () => {
    expect(parseCallFileName('Call recording Alisher_241010_143012.m4a')).toEqual({
      counterpart: 'Alisher',
      isNumber: false,
      startedAtMs: local(2024, 10, 10, 14, 30, 12),
      looksLikeCall: true,
    });
    expect(parseCallFileName('+998901234567_241010_143012.m4a')).toMatchObject({ counterpart: '+998901234567', isNumber: true });
    expect(parseCallFileName('Запись вызова Алишер Каримов_241010_090501.m4a')).toMatchObject({
      counterpart: 'Алишер Каримов',
      startedAtMs: local(2024, 10, 10, 9, 5, 1),
    });
    expect(parseCallFileName('Alisher aka 2_20241010_143012.m4a').counterpart).toBe('Alisher aka 2');
    expect(parseCallFileName('Call_20241010143012.m4a')).toMatchObject({ counterpart: null, startedAtMs: local(2024, 10, 10, 14, 30, 12) });
    expect(parseCallFileName('Ota 2024-10-10 14-30-12.m4a')).toMatchObject({ counterpart: 'Ota', startedAtMs: local(2024, 10, 10, 14, 30, 12) });
    expect(parseCallFileName('+998 90 123 45 67_241010_143012.m4a')).toMatchObject({ counterpart: '+998 90 123 45 67', isNumber: true });
  });

  it('does not invent dates or strip real names', () => {
    // 31-fevral - noto'g'ri sana: vaqt yo'q, nom esa butunligicha qoladi.
    expect(parseCallFileName('Ali_240231_101010.m4a').startedAtMs).toBeNull();
    expect(parseCallFileName('Callum_241010_143012.m4a').counterpart).toBe('Callum');
    const plain = parseCallFileName('Mijoz bilan uchrashuv.m4a');
    expect(plain).toEqual({ counterpart: 'Mijoz bilan uchrashuv', isNumber: false, startedAtMs: null, looksLikeCall: false });
    expect(parseCallFileName('')).toEqual({ counterpart: null, isNumber: false, startedAtMs: null, looksLikeCall: false });
  });

  it('titles, start time fallbacks and sizes', () => {
    expect(importTitle(t, parseCallFileName('Call recording Alisher_241010_143012.m4a'), '14:30')).toBe("Qo'ng'iroq: Alisher");
    expect(importTitle(t, parseCallFileName('Call_241010_143012.m4a'), '14:30')).toBe("Qo'ng'iroq, 14:30");
    expect(importTitle(t, parseCallFileName('Mijoz bilan uchrashuv.m4a'), '14:30')).toBe('Mijoz bilan uchrashuv');
    expect(importTitle(t, parseCallFileName(`Call recording ${'A'.repeat(300)}_241010_143012.m4a`), 'x').length).toBe(120);

    const noName = parseCallFileName('voice.m4a');
    // Nomda vaqt yo'q: fayl vaqti (qo'ng'iroq oxiri) - davomiylik; u ham yo'q - hozir.
    expect(recordedAtMs(noName, NOW - 1000, 60_000, NOW)).toBe(NOW - 61_000);
    expect(recordedAtMs(noName, null, 0, NOW)).toBe(NOW);
    // Kelajakdagi "sana" (noto'g'ri soat) ishonchsiz.
    expect(recordedAtMs(parseCallFileName('A_301010_101010.m4a'), NOW, 0, NOW)).toBe(NOW);

    expect(formatSize(2_400_000, t, 'uz')).toBe('2,3 MB');
    expect(formatSize(2_400_000, t, 'en')).toBe('2.3 MB');
    expect(formatSize(300_000, t, 'uz')).toBe('293 KB');
    expect(formatSize(0, t, 'uz')).toBe('');
  });
});

describe('dedupe keys', () => {
  it('callClientId is a stable UUID per owner and recording', () => {
    const key = callKey(rec());
    expect(key).toBe('Recordings/Call/Call recording Alisher_241010_143012.m4a|2400000');
    const a = callClientId('7', key);
    expect(a).toMatch(UUID_RE);
    expect(callClientId('7', key)).toBe(a);
    expect(callClientId('8', key)).not.toBe(a);
    // Hajm o'zgardi (qo'ng'iroq hali yozilmoqda edi) - boshqa yozuv.
    expect(callClientId('7', callKey(rec({ sizeBytes: 2_500_000 })))).not.toBe(a);
    expect(callClientId(null, 'Запись вызова Алишер')).toMatch(UUID_RE);
  });
});

function callDeps(over: Partial<CallSendDeps> = {}) {
  const queue = createMemoryQueueStore();
  const marks: [string, string][] = [];
  const deps: CallSendDeps = {
    queue,
    uploader: { runOnce: jest.fn(async () => {}) },
    copy: jest.fn(async (_uri: string, name: string) => `/data/user/0/app/files/recordings/${name}`),
    removeFile: jest.fn(async () => {}),
    markSent: (k, c) => marks.push([k, c]),
    toFileUri: (p) => `file://${p}`,
    now: () => NOW,
    ...over,
  };
  return { deps, queue, marks };
}

const OPTS: SendOptions = { owner: '7', language: 'ru', maxBytes: 150 * 1024 * 1024, t };

describe('sending a call recording', () => {
  it('copies into app storage and queues an audio/mp4 call row (title, times, 2 speakers)', async () => {
    const { deps, queue, marks } = callDeps();
    const r = rec();
    const out = await sendCallRecording(deps, r, OPTS);
    const clientId = callClientId('7', callKey(r));
    expect(out).toEqual({ kind: 'queued', clientId });
    expect(deps.copy).toHaveBeenCalledWith(r.uri, `${clientId}.m4a`);
    const row = await queue.get(clientId);
    expect(row).toMatchObject({
      fileUri: `file:///data/user/0/app/files/recordings/${clientId}.m4a`,
      contentType: 'audio/mp4',
      source: 'call',
      language: 'ru',
      template: 'auto',
      expectedSpeakers: 2,
      title: "Qo'ng'iroq: Alisher",
      state: 'stopped',
      durationSec: 185,
      totalBytes: 2_400_000,
      startedAt: new Date(local(2024, 10, 10, 14, 30, 12)).toISOString(),
      endedAt: new Date(r.dateMs).toISOString(),
    });
    expect(marks).toEqual([[callKey(r), clientId]]);
    expect(deps.uploader.runOnce).toHaveBeenCalled();
  });

  it('never queues twice: an existing row only re-marks it', async () => {
    const { deps, queue } = callDeps();
    await sendCallRecording(deps, rec(), OPTS);
    (deps.copy as jest.Mock).mockClear();
    const again = await sendCallRecording(deps, rec(), OPTS);
    expect(again.kind).toBe('already');
    expect(deps.copy).not.toHaveBeenCalled();
    expect((await queue.list()).length).toBe(1);
  });

  it('a manual tap and an auto scan at the same moment make one copy', async () => {
    const { deps, queue } = callDeps();
    const [a, b] = await Promise.all([sendCallRecording(deps, rec(), OPTS), sendCallRecording(deps, rec(), OPTS)]);
    expect([a.kind, b.kind].sort()).toEqual(['already', 'queued']);
    expect(deps.copy).toHaveBeenCalledTimes(1);
    expect((await queue.list()).length).toBe(1);
  });

  it('rejects unsupported and oversized files before copying; reports copy errors', async () => {
    const { deps } = callDeps();
    expect(await sendCallRecording(deps, rec({ contentType: null, displayName: 'x.amr' }), OPTS)).toEqual({ kind: 'unsupported' });
    expect(await sendCallRecording(deps, rec({ sizeBytes: 200 * 1024 * 1024 }), OPTS)).toEqual({ kind: 'too_large', maxBytes: OPTS.maxBytes });
    expect(deps.copy).not.toHaveBeenCalled();
    const failing = callDeps({ copy: jest.fn(async () => Promise.reject(Object.assign(new Error('x'), { code: 'ERR_NO_SPACE' }))) });
    expect(await sendCallRecording(failing.deps, rec(), OPTS)).toEqual({ kind: 'error', code: 'ERR_NO_SPACE' });
    expect(failing.marks).toEqual([]);
  });

  it('a file Samsung is still writing (changed < 60 s ago) is not copied, manual tap or not', async () => {
    const { deps, marks } = callDeps();
    expect(await sendCallRecording(deps, rec({ dateMs: NOW - 10_000 }), OPTS)).toEqual({ kind: 'not_ready' });
    expect(deps.copy).not.toHaveBeenCalled();
    expect(marks).toEqual([]);
    // 60 s jimlikdan keyin - yuboriladi.
    expect((await sendCallRecording(deps, rec({ dateMs: NOW - QUIET_MS }), OPTS)).kind).toBe('queued');
    // Noto'g'ri soat (uzoq kelajak) yozuvni abadiy qulflamaydi; sanasiz yozuv ham.
    expect(isStillWriting({ dateMs: NOW + 10 * QUIET_MS }, NOW)).toBe(false);
    expect(isStillWriting({ dateMs: 0 }, NOW)).toBe(false);
    expect(isStillWriting({ dateMs: NOW + 1_000 }, NOW)).toBe(true);
  });

  it('removes the copy when the queue write fails (no orphan, not marked sent)', async () => {
    const { deps, marks } = callDeps();
    deps.queue.insert = jest.fn(async () => Promise.reject(new Error('db')));
    const out = await sendCallRecording(deps, rec(), OPTS);
    expect(out).toEqual({ kind: 'error', code: 'queue' });
    expect(deps.removeFile).toHaveBeenCalledWith(expect.stringMatching(/^file:\/\/.*\.m4a$/));
    expect(marks).toEqual([]);
  });
});

describe('sending a shared file', () => {
  const meta = (over: Partial<ImportMeta> = {}): ImportMeta => ({
    fileName: 'share_1728560000000_0_x.aac',
    path: '/data/user/0/app/files/imports/share_1728560000000_0_x.aac',
    displayName: '+998901234567_241010_143012.aac',
    contentType: 'audio/aac',
    sizeBytes: 900_000,
    durationMs: 60_000,
    dateMs: null,
    source: 'share',
    ...over,
  });
  function importDeps() {
    const queue = createMemoryQueueStore();
    const deps: ImportSendDeps = {
      queue,
      moveIntoRecordings: jest.fn((_m: ImportMeta, id: string, ext: string) => `file:///doc/recordings/${id}${ext}`),
      removeImport: jest.fn(() => true),
      newClientId: () => '11111111-2222-4333-8444-555555555555',
      now: () => NOW,
    };
    return { deps, queue };
  }

  it('moves the file into recordings and queues a share row', async () => {
    const { deps, queue } = importDeps();
    const out = await sendImportedFile(deps, meta(), OPTS);
    expect(out).toEqual({ kind: 'queued', clientId: '11111111-2222-4333-8444-555555555555' });
    expect(deps.moveIntoRecordings).toHaveBeenCalledWith(expect.objectContaining({ fileName: 'share_1728560000000_0_x.aac' }), out.kind === 'queued' ? out.clientId : '', '.aac');
    expect(deps.removeImport).toHaveBeenCalledWith('share_1728560000000_0_x.aac');
    expect((await queue.list())[0]).toMatchObject({
      fileUri: 'file:///doc/recordings/11111111-2222-4333-8444-555555555555.aac',
      contentType: 'audio/aac',
      source: 'share',
      expectedSpeakers: 2,
      title: "Qo'ng'iroq: +998901234567",
      startedAt: new Date(local(2024, 10, 10, 14, 30, 12)).toISOString(),
      durationSec: 60,
    });
  });

  it('a non-call file gets no title (the server names it) and unknown speakers; bad files are not moved', async () => {
    const { deps, queue } = importDeps();
    await sendImportedFile(deps, meta({ displayName: 'AUD-20241010-WA0003.m4a', contentType: 'audio/mp4', dateMs: NOW - 60_000 }), OPTS);
    expect((await queue.list())[0]).toMatchObject({ title: null, expectedSpeakers: null, contentType: 'audio/mp4', startedAt: new Date(NOW - 120_000).toISOString() });
    (deps.moveIntoRecordings as jest.Mock).mockClear();
    expect(await sendImportedFile(deps, meta({ contentType: null }), OPTS)).toEqual({ kind: 'unsupported' });
    expect(await sendImportedFile(deps, meta({ sizeBytes: 0 }), OPTS)).toEqual({ kind: 'missing' });
    expect(await sendImportedFile(deps, meta({ sizeBytes: 999 * 1024 * 1024 }), OPTS)).toEqual({ kind: 'too_large', maxBytes: OPTS.maxBytes });
    expect(deps.moveIntoRecordings).not.toHaveBeenCalled();
  });
});

describe('auto-send safety', () => {
  const since = local(2024, 10, 10, 12, 0, 0);
  const state = (sent: Record<string, unknown> = {}) => ({ autoSendSince: since, sent });

  it('needs two scans with the same size and 60 s of quiet; older calls and sent ones are skipped', () => {
    const memory: SizeMemory = new Map();
    const fresh = rec({ dateMs: NOW - 10_000 });
    const old = rec({ uri: 'content://media/external/audio/media/1', dateMs: since - 1, displayName: 'Old_241009_101010.m4a' });
    const done = rec({ uri: 'content://media/external/audio/media/2', displayName: 'Done_241010_130000.m4a' });
    const amr = rec({ uri: 'content://media/external/audio/media/3', contentType: null });

    // 1-skan: hajm hali ma'lum emas - kutamiz.
    let p = pickAutoSend([fresh, old, done, amr], state({ [callKey(done)]: 1 }), memory, NOW, null);
    expect(p).toEqual({ ready: [], waiting: true });
    memory.set(fresh.uri, fresh.sizeBytes);
    // 2-skan, hajm bir xil, lekin 60 s o'tmagan.
    p = pickAutoSend([fresh], state(), memory, NOW, null);
    expect(p).toEqual({ ready: [], waiting: true });
    // 60 s o'tdi - yuboriladi.
    p = pickAutoSend([fresh], state(), memory, fresh.dateMs + QUIET_MS, null);
    expect(p).toEqual({ ready: [fresh], waiting: false });
    // Hajm o'zgardi (hali yozilmoqda) - yana kutadi.
    p = pickAutoSend([{ ...fresh, sizeBytes: 3_000_000 }], state(), memory, fresh.dateMs + QUIET_MS, null);
    expect(p.waiting).toBe(true);
    // Avtomatik yuborish yoqilmagan (since yo'q) - hech narsa.
    expect(pickAutoSend([fresh], { autoSendSince: null, sent: {} }, memory, NOW + QUIET_MS, null)).toEqual({ ready: [], waiting: false });
    // Server chegarasidan katta - o'tkazib yuboriladi.
    expect(pickAutoSend([fresh], state(), memory, NOW + QUIET_MS, 1000).ready).toEqual([]);
  });

  it('runs at most MAX_PER_RUN per scan, oldest first, and stops on a copy error', async () => {
    const recs = Array.from({ length: MAX_PER_RUN + 3 }, (_, i) => rec({ uri: `content://m/${i}`, displayName: `N${i}_241010_1300${String(i).padStart(2, '0')}.m4a`, dateMs: since + 1000 + i }));
    const memory: SizeMemory = new Map(recs.map((r) => [r.uri, r.sizeBytes]));
    const sent: string[] = [];
    const res = await runAutoSendOnce({
      list: jest.fn(async () => recs),
      state: () => ({ autoSendSince: since, sent: {} }),
      send: async (r) => {
        sent.push(r.uri);
        return { kind: 'queued', clientId: r.uri };
      },
      memory,
      maxBytes: null,
      now: () => NOW,
    });
    expect(res).toEqual({ sent: MAX_PER_RUN, recheck: true });
    expect(sent[0]).toBe('content://m/0');

    const failing = await runAutoSendOnce({
      list: async () => recs,
      state: () => ({ autoSendSince: since, sent: {} }),
      send: async () => ({ kind: 'error', code: 'ERR_NO_SPACE' }),
      memory,
      maxBytes: null,
      now: () => NOW,
    });
    expect(failing).toEqual({ sent: 0, recheck: false });

    // Yuborish "hali yozilmoqda" desa (soat farqi) - keyinroq qayta skan.
    const notReady = await runAutoSendOnce({
      list: async () => recs.slice(0, 1),
      state: () => ({ autoSendSince: since, sent: {} }),
      send: async () => ({ kind: 'not_ready' }),
      memory,
      maxBytes: null,
      now: () => NOW,
    });
    expect(notReady).toEqual({ sent: 0, recheck: true });
  });
});

describe('calls state', () => {
  beforeEach(() => __setCallsStorage(null));

  it('parses stored prefs defensively', () => {
    expect(parseCallsPrefs(null)).toEqual(DEFAULT_CALLS);
    expect(parseCallsPrefs('{bad')).toEqual(DEFAULT_CALLS);
    const p = parseCallsPrefs(JSON.stringify({ owner: '7', enabled: false, autoSend: true, language: 'de', sent: { a: { c: 'x', at: 1 }, b: 'junk', d: { c: 'y', at: 2, s: 'srv-1' } } }));
    expect(p).toMatchObject({ owner: '7', enabled: false, autoSend: false, language: null, sent: { a: { c: 'x', at: 1 }, d: { c: 'y', at: 2, s: 'srv-1' } } });
  });

  it('remembers the server id of a sent call (the queue row is purged after a few days)', () => {
    const data = new Map<string, string>();
    __setCallsStorage({ getItemSync: (k) => data.get(k) ?? null, setItemSync: (k, v) => void data.set(k, v) });
    useCalls.getState().markSent('k1', 'c1', 10);
    useCalls.getState().markSent('k2', 'c2', 11);
    const writes = () => data.size && JSON.parse(data.get('venera.calls.v1') ?? '{}');
    useCalls.getState().linkServerIds(new Map([['c1', 'srv-1'], ['other', 'srv-x']]));
    expect(useCalls.getState().sent).toEqual({ k1: { c: 'c1', at: 10, s: 'srv-1' }, k2: { c: 'c2', at: 11 } });
    expect(writes().sent.k1.s).toBe('srv-1');
    // O'zgarish yo'q - holat (va xotira) qayta yozilmaydi.
    const before = useCalls.getState().sent;
    useCalls.getState().linkServerIds(new Map([['c1', 'srv-1']]));
    expect(useCalls.getState().sent).toBe(before);
  });

  it('a different signed-in user starts from a clean state; turning detection off also stops auto-send', () => {
    const st = useCalls.getState();
    st.adoptOwner('7');
    st.set({ enabled: true, autoSend: true, autoSendSince: 5, consentAt: 1 });
    st.markSent('k1', 'c1', 10);
    useCalls.getState().adoptOwner('7');
    expect(useCalls.getState()).toMatchObject({ owner: '7', enabled: true, sent: { k1: { c: 'c1', at: 10 } } });
    useCalls.getState().adoptOwner('8');
    expect(useCalls.getState()).toMatchObject({ owner: '8', enabled: false, autoSend: false, consentAt: null, sent: {} });
    useCalls.getState().set({ enabled: true, autoSend: true });
    useCalls.getState().set({ enabled: false });
    expect(useCalls.getState().autoSend).toBe(false);
    useCalls.getState().reset();
    expect(useCalls.getState().owner).toBeNull();
  });

  it('persists to its own key and keeps the sent list bounded', () => {
    const data = new Map<string, string>();
    __setCallsStorage({ getItemSync: (k) => data.get(k) ?? null, setItemSync: (k, v) => void data.set(k, v) });
    useCalls.getState().set({ enabled: true, language: 'ru' });
    expect(JSON.parse(data.get('venera.calls.v1') ?? '{}')).toMatchObject({ enabled: true, language: 'ru' });
    const big = Object.fromEntries(Array.from({ length: MAX_SENT + 5 }, (_, i) => [`k${i}`, { c: `c${i}`, at: i }]));
    const pruned = pruneSent(big);
    expect(Object.keys(pruned)).toHaveLength(MAX_SENT);
    expect(pruned.k0).toBeUndefined();
    expect(pruned[`k${MAX_SENT + 4}`]).toBeDefined();
  });

  it('hub value states the mode', () => {
    expect(callsHubValue(t, { enabled: false, autoSend: false })).toBe("O'chiq");
    expect(callsHubValue(t, { enabled: true, autoSend: false })).toBe("Qo'lda yuborish");
    expect(callsHubValue(t, { enabled: true, autoSend: true })).toBe('Avtomatik yuborish');
    // Yoqilgan, lekin ruxsat yo'q - ishlayotgandek ko'rsatilmaydi.
    expect(callsHubValue(t, { enabled: true, autoSend: true }, false)).toBe('Ruxsat kerak');
    expect(callsHubValue(t, { enabled: false, autoSend: false }, false)).toBe("O'chiq");
  });
});

describe('send feedback', () => {
  it('names the cause in lower case, with the limit and the next step', () => {
    const toast = showToast as jest.Mock;
    toastSendOutcome(t, { kind: 'too_large', maxBytes: 157286400 });
    expect(toast).toHaveBeenLastCalledWith("Yuborib bo'lmadi: fayl 150 MB dan katta");
    toastSendOutcome(t, { kind: 'unsupported' });
    expect(toast).toHaveBeenLastCalledWith("Yuborib bo'lmadi: format mos emas");
    toastSendOutcome(t, { kind: 'not_ready' });
    expect(toast).toHaveBeenLastCalledWith("Yuborib bo'lmadi: yozuv hali tugamagan - birozdan keyin");
    toastSendOutcome(t, { kind: 'error', code: 'ERR_NO_SPACE' });
    expect(toast).toHaveBeenLastCalledWith("Yuborib bo'lmadi: telefonda joy kam - joy bo'shating");
    toastSendOutcome(t, { kind: 'queued', clientId: 'x' });
    expect(toast).toHaveBeenLastCalledWith('Yuborilmoqda - holati Yozuvlarda');
    expect(limitMb(157286400)).toBe('150');
  });
});
