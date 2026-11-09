/**
 * Bayonnoma varag'ining sof mantig'i: hujjat tili default'i (server `default_lang` bilan bir xil),
 * ro'yxatdan tanlangan til holati, izoh/ogohlantirishni himoyalangan o'qish, xato qatori va server
 * xatosini sababga aylantirish (eski server 404 - "serverda hali yoqilmagan", aniq hujjat yo'q -
 * ro'yxat yangilanadi) va 3 s / 10 daqiqalik so'rash.
 */
import { ApiError, AuthRequiredError } from '@/api/client';
import type { MinutesView } from '@/api/types';
import {
  defaultMinutesLang,
  failedText,
  isTransientMinutesError,
  MINUTES_LANG_NAME,
  MINUTES_LANGS,
  MINUTES_POLL_LIMIT_MS,
  MINUTES_POLL_MS,
  minutesNotes,
  minutesProblem,
  minutesProblemAction,
  minutesProblemText,
  minutesSlot,
  minutesWarnings,
  pollMinutes,
  retryWaitText,
  upsertMinutes,
} from '@/features/meeting/minutesModel';
import { makeT } from '@/i18n';

import { minutesView } from './fixtures/server';

const t = makeT('uz');
const at = (min: number) => new Date(Date.UTC(2026, 10, 6, 6, min)).toISOString();

describe('minutes: document language', () => {
  it('defaults like the server: uz -> Cyrillic, ru -> ru, en -> en, anything else -> Cyrillic', () => {
    expect(defaultMinutesLang('uz')).toBe('uz-cyrl');
    expect(defaultMinutesLang('ru')).toBe('ru');
    expect(defaultMinutesLang('en')).toBe('en');
    expect(defaultMinutesLang(null)).toBe('uz-cyrl');
    expect(defaultMinutesLang('kk')).toBe('uz-cyrl');
  });

  it('offers exactly the four server languages, named in their own script', () => {
    expect([...MINUTES_LANGS]).toEqual(['uz-cyrl', 'uz-latn', 'ru', 'en']);
    expect(MINUTES_LANGS.map((l) => MINUTES_LANG_NAME[l])).toEqual(["O'zbekcha (kirill)", "O'zbekcha (lotin)", 'Русский', 'English']);
  });
});

describe('minutes: state of the chosen language', () => {
  it('a ready, non-stale document of that language is offered; other languages and stale ones are not', () => {
    const items = [
      minutesView({ id: 'ru1', language: 'ru', createdAt: at(1) }),
      minutesView({ id: 'old', createdAt: at(2), stale: true }),
      minutesView({ id: 'cur', createdAt: at(3) }),
    ];
    expect(minutesSlot(items, 'uz-cyrl')).toEqual({ ready: items[2], running: null, failed: null, staleOnly: false });
    expect(minutesSlot(items, 'ru').ready?.id).toBe('ru1');
    expect(minutesSlot(items, 'en')).toEqual({ ready: null, running: null, failed: null, staleOnly: false });
  });

  it('only a stale document -> nothing to share, "prepare a new one" hint', () => {
    const slot = minutesSlot([minutesView({ stale: true })], 'uz-cyrl');
    expect(slot).toEqual({ ready: null, running: null, failed: null, staleOnly: true });
  });

  it('a run newer than the ready document is polled (forced rewrite); an older leftover run is ignored', () => {
    const ready = minutesView({ id: 'r', createdAt: at(5) });
    const newer = minutesView({ id: 'n', status: 'running', createdAt: at(6) });
    const older = minutesView({ id: 'o', status: 'running', createdAt: at(4) });
    expect(minutesSlot([ready, newer], 'uz-cyrl')).toMatchObject({ ready, running: newer });
    expect(minutesSlot([older, ready], 'uz-cyrl')).toMatchObject({ ready, running: null });
  });

  it('the latest attempt failed -> failed (the older ready document can still be shared)', () => {
    const ready = minutesView({ id: 'r', createdAt: at(1) });
    const bad = minutesView({ id: 'b', status: 'failed', createdAt: at(2), error: { code: 'llm_busy', message: "navbat to'la" } });
    expect(minutesSlot([ready, bad], 'uz-cyrl')).toMatchObject({ ready, failed: bad, running: null });
    // Xatodan keyin yangi urinish yozilmoqda - endi u.
    const again = minutesView({ id: 'a', status: 'running', createdAt: at(3) });
    expect(minutesSlot([ready, bad, again], 'uz-cyrl')).toMatchObject({ running: again, failed: null });
  });

  it('same timestamp: the later list position wins (server lists oldest first)', () => {
    const a = minutesView({ id: 'a', status: 'failed', createdAt: at(1), error: { code: 'internal', message: '' } });
    const b = minutesView({ id: 'b', status: 'running', createdAt: at(1) });
    expect(minutesSlot([a, b], 'uz-cyrl').running?.id).toBe('b');
  });

  it('upsert replaces by id or appends', () => {
    const a = minutesView({ id: 'a', status: 'running' });
    expect(upsertMinutes(null, a)).toEqual([a]);
    const done = { ...a, status: 'ready' as const };
    expect(upsertMinutes([a], done)).toEqual([done]);
    expect(upsertMinutes([a], minutesView({ id: 'b' })).map((x) => x.id)).toEqual(['a', 'b']);
  });
});

describe('minutes: notes, warnings, failed rows', () => {
  it('notes are read defensively: list, multi-line string, {text}; blanks, bullets and duplicates dropped; at most 10', () => {
    expect(minutesNotes(['  Muddat aniq emas ', '', 'Muddat aniq emas', 7, null, { text: 'Rais ismi yo‘q' }])).toEqual(['Muddat aniq emas', 'Rais ismi yo‘q']);
    expect(minutesNotes('- birinchi\n• ikkinchi\n\n')).toEqual(['birinchi', 'ikkinchi']);
    expect(minutesNotes(undefined)).toEqual([]);
    expect(minutesNotes({ a: 1 })).toEqual([]);
    expect(minutesNotes(Array.from({ length: 15 }, (_, i) => `izoh ${i}`))).toHaveLength(10);
  });

  it('warnings count only document issues: provider fallbacks are not the reader\'s concern', () => {
    expect(minutesWarnings(['ungrounded_name:Aziz', 'provider_failed:ollama', 'script_mismatch', '', 3])).toEqual(['ungrounded_name:Aziz', 'script_mismatch']);
    expect(minutesWarnings(null)).toEqual([]);
  });

  it('failed rows are explained by error.code only - the technical message is never shown', () => {
    const row = (code: string, message = 'bayonnoma: javob kesildi (max tokens)'): Pick<MinutesView, 'error'> => ({ error: { code, message } });
    expect(failedText(t, row('llm_failed'))).toBe("Model bayonnomani yozolmadi - qayta urinib ko'ring");
    expect(failedText(t, row('llm_busy', "navbat to'la"))).toBe("Model hozir band - birozdan keyin qayta urinib ko'ring");
    expect(failedText(t, row('llm_rate_limited', '429'))).toBe("Model chegarasiga yetdi - birozdan keyin qayta urinib ko'ring");
    expect(failedText(t, row('llm_not_configured'))).toBe('Bayonnoma xizmati hali sozlanmagan - administratorga murojaat qiling');
    expect(failedText(t, row('internal', 'KeyError'))).toBe("Serverda ichki xato - qayta urinib ko'ring");
    expect(failedText(t, row('interrupted', ''))).toBe("Bayonnoma yozish uzilib qoldi - qayta urinib ko'ring");
    expect(failedText(t, row('something_new', 'raw'))).toBe("Bayonnoma yozilmadi - qayta urinib ko'ring");
    expect(failedText(t, { error: null })).toBe("Bayonnoma yozilmadi - qayta urinib ko'ring");
    for (const code of ['llm_failed', 'llm_busy', 'internal', 'interrupted']) expect(failedText(t, row(code))).not.toMatch(/max tokens|KeyError/);
  });
});

describe('minutes: server error -> reason and next step', () => {
  const err = (status: number, code: string, retryAfter: number | null = null) => new ApiError(status, code, code, null, retryAfter);

  it('offline / stalled download offer a retry', () => {
    expect(minutesProblem(err(0, 'network'), 'create')).toEqual({ kind: 'offline' });
    expect(minutesProblem(err(0, 'timeout'), 'list')).toEqual({ kind: 'offline' });
    expect(minutesProblem(err(0, 'stalled'), 'export')).toEqual({ kind: 'stalled' });
    expect(minutesProblemAction({ kind: 'offline' })).toBe('retry');
    expect(minutesProblemText(t, { kind: 'offline' })).toMatch(/^Internet yo'q\. Bayonnoma serverda yoziladi/);
  });

  it('429 rate_limited names the hourly limit and the Retry-After wait - no retry button', () => {
    const p = minutesProblem(err(429, 'rate_limited', 300), 'create');
    expect(p).toEqual({ kind: 'rateLimited', retryAfterSec: 300 });
    expect(minutesProblemText(t, p)).toBe("Bir soatlik bayonnoma chegarasi tugadi - 5 daqiqadan keyin urinib ko'ring");
    expect(minutesProblemText(t, { kind: 'rateLimited', retryAfterSec: 40 })).toBe("Bir soatlik bayonnoma chegarasi tugadi - 40 soniyadan keyin urinib ko'ring");
    expect(minutesProblemText(t, { kind: 'rateLimited', retryAfterSec: null })).toBe("Bir soatlik bayonnoma chegarasi tugadi - keyinroq urinib ko'ring");
    expect(minutesProblemAction(p)).toBeNull();
    expect(retryWaitText(makeT('ru'), 61)).toBe('2 мин');
    expect(retryWaitText(t, 0)).toBeNull();
  });

  it('409: transcript empty / not ready on create; on export the document itself is not ready -> re-check', () => {
    expect(minutesProblem(err(409, 'transcript_empty'), 'create')).toEqual({ kind: 'transcriptEmpty' });
    expect(minutesProblem(err(409, 'not_ready'), 'create')).toEqual({ kind: 'transcriptNotReady' });
    expect(minutesProblem(err(409, 'not_ready'), 'export')).toEqual({ kind: 'docNotReady' });
    expect(minutesProblemAction({ kind: 'transcriptEmpty' })).toBeNull();
    expect(minutesProblemAction({ kind: 'docNotReady' })).toBe('recheck');
    expect(minutesProblemText(t, { kind: 'transcriptEmpty' })).toBe("Yozuvda nutq topilmadi - bayonnoma uchun gapirilgan yig'ilish yozuvi kerak");
  });

  it('503: model not configured (no retry), model busy (retry), PDF/Word renderer missing (switch format)', () => {
    expect(minutesProblem(err(503, 'llm_not_configured'), 'create')).toEqual({ kind: 'notConfigured' });
    expect(minutesProblemAction({ kind: 'notConfigured' })).toBeNull();
    expect(minutesProblem(err(503, 'llm_busy'), 'create')).toEqual({ kind: 'busy' });
    expect(minutesProblem(err(502, 'llm_failed'), 'create')).toEqual({ kind: 'writeFailed' });
    expect(minutesProblem(err(503, 'pdf_unavailable'), 'export')).toEqual({ kind: 'pdfUnavailable' });
    expect(minutesProblemAction({ kind: 'pdfUnavailable' })).toBe('useDocx');
    expect(minutesProblemAction({ kind: 'docxUnavailable' })).toBe('usePdf');
  });

  it('export_busy: 429 = my previous file is still being made, 503 = the server queue is full (both retry)', () => {
    const mine = minutesProblem(err(429, 'export_busy', 10), 'export');
    const server = minutesProblem(err(503, 'export_busy', 10), 'export');
    expect([mine, server]).toEqual([
      { kind: 'exportBusy', server: false },
      { kind: 'exportBusy', server: true },
    ]);
    expect(minutesProblemText(t, mine)).toBe("Oldingi fayl hali tayyorlanmoqda - birozdan keyin qayta urinib ko'ring");
    expect(minutesProblemText(t, server)).toBe("Server band - birozdan keyin qayta urinib ko'ring");
    expect(minutesProblemAction(mine)).toBe('retry');
  });

  it('404 on the listing/POST = the server has no minutes routes yet (honest, no retry); a missing document = gone', () => {
    // Varaq faqat yuklangan yig'ilishdan ochiladi - ro'yxat/POST 404 bo'lsa, server eski.
    for (const stage of ['list', 'create'] as const) {
      const p = minutesProblem(err(404, 'not_found'), stage);
      expect([stage, p]).toEqual([stage, { kind: 'notOnServer' }]);
      expect(minutesProblemAction(p)).toBeNull();
      expect(minutesProblemText(t, p)).toBe('Bayonnoma serverda hali yoqilmagan - server yangilangach ishlaydi');
    }
    expect(minutesProblemText(makeT('ru'), { kind: 'notOnServer' })).toMatch(/после обновления сервера/);
    expect(minutesProblemText(makeT('en'), { kind: 'notOnServer' })).toMatch(/once the server is updated/);
    // Aniq hujjat (GET /minutes/{id}, eksport) - u yo'q: ro'yxat yangilanadi.
    expect(minutesProblem(err(404, 'minutes_not_found'), 'poll')).toEqual({ kind: 'gone' });
    expect(minutesProblem(err(404, 'minutes_not_found'), 'export')).toEqual({ kind: 'gone' });
    expect(minutesProblem(err(404, 'minutes_not_found'), 'list')).toEqual({ kind: 'gone' });
    expect(minutesProblem(err(404, 'not_found'), 'poll')).toEqual({ kind: 'gone' });
    expect(minutesProblemText(t, { kind: 'gone' })).toBe('Bayonnoma topilmadi - qaytadan tayyorlang');
  });

  it('403/401/410 are final; anything else is a retryable error with the code', () => {
    expect(minutesProblem(err(403, 'forbidden'), 'list')).toMatchObject({ kind: 'final' });
    expect(minutesProblem(new AuthRequiredError(), 'create')).toMatchObject({ kind: 'final' });
    const p = minutesProblem(err(500, 'internal'), 'create');
    expect(p).toMatchObject({ kind: 'error' });
    expect(minutesProblemAction(p)).toBe('retry');
    expect(minutesProblem(new Error('boom'), 'create')).toMatchObject({ kind: 'error' });
  });
});

describe('minutes: polling', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  const cb = () => ({ onUpdate: jest.fn(), onTransient: jest.fn(), onFatal: jest.fn(), onTimeout: jest.fn() });
  const tick = async (ms = MINUTES_POLL_MS) => {
    await jest.advanceTimersByTimeAsync(ms);
  };

  it('asks every 3 s until the document is ready, then stops by itself', async () => {
    const get = jest
      .fn<Promise<MinutesView>, []>()
      .mockResolvedValueOnce(minutesView({ status: 'running' }))
      .mockResolvedValueOnce(minutesView({ status: 'ready' }));
    const h = cb();
    pollMinutes(get, h);
    expect(get).not.toHaveBeenCalled(); // birinchi so'rov ham 3 s dan keyin
    await tick();
    expect(get).toHaveBeenCalledTimes(1);
    await tick();
    expect(get).toHaveBeenCalledTimes(2);
    expect(h.onUpdate.mock.calls.map(([v]) => v.status)).toEqual(['running', 'ready']);
    await tick(30_000);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('a failed row also ends polling', async () => {
    const get = jest.fn(async () => minutesView({ status: 'failed', error: { code: 'interrupted', message: '' } }));
    const h = cb();
    pollMinutes(get, h);
    await tick();
    await tick(10_000);
    expect(get).toHaveBeenCalledTimes(1);
    expect(h.onUpdate).toHaveBeenCalledTimes(1);
  });

  it('transient errors (offline, 5xx, 429) keep polling; a fatal one (404) stops it', async () => {
    const get = jest
      .fn<Promise<MinutesView>, []>()
      .mockRejectedValueOnce(new ApiError(0, 'network', 'x'))
      .mockRejectedValueOnce(new ApiError(503, 'unavailable', 'x'))
      .mockRejectedValueOnce(new ApiError(404, 'minutes_not_found', 'x'));
    const h = cb();
    pollMinutes(get, h);
    await tick();
    await tick();
    await tick();
    await tick();
    expect(get).toHaveBeenCalledTimes(3);
    expect(h.onTransient).toHaveBeenCalledTimes(2);
    expect(h.onFatal).toHaveBeenCalledTimes(1);
    expect(isTransientMinutesError(new ApiError(429, 'rate_limited', 'x'))).toBe(true);
    expect(isTransientMinutesError(new ApiError(403, 'forbidden', 'x'))).toBe(false);
  });

  it('gives up after 10 minutes while the server keeps writing ("taking longer, check later")', async () => {
    const get = jest.fn(async () => minutesView({ status: 'running' }));
    const h = cb();
    pollMinutes(get, h);
    await tick(MINUTES_POLL_LIMIT_MS - MINUTES_POLL_MS);
    expect(h.onTimeout).not.toHaveBeenCalled();
    await tick(2 * MINUTES_POLL_MS);
    expect(h.onTimeout).toHaveBeenCalledTimes(1);
    const calls = get.mock.calls.length;
    expect(calls).toBe(MINUTES_POLL_LIMIT_MS / MINUTES_POLL_MS);
    await tick(60_000);
    expect(get.mock.calls.length).toBe(calls);
  });

  it('stop() (sheet closed, language changed) cancels the next request and ignores a late answer', async () => {
    let finish: (v: MinutesView) => void = () => {};
    const get = jest.fn(() => new Promise<MinutesView>((r) => (finish = r)));
    const h = cb();
    const stop = pollMinutes(get, h);
    await tick();
    stop();
    finish(minutesView({ status: 'ready' }));
    await tick(30_000);
    expect(get).toHaveBeenCalledTimes(1);
    expect(h.onUpdate).not.toHaveBeenCalled();
  });
});
