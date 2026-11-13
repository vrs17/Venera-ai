/**
 * Bayonnoma varag'ining sof mantig'i: hujjat tili default'i (server `default_lang` bilan bir xil),
 * ro'yxatdan tanlangan til holati, izoh/ogohlantirishni himoyalangan o'qish, xato qatori va server
 * xatosini sababga aylantirish (eski server 404 - "serverda hali yoqilmagan", aniq hujjat yo'q -
 * ro'yxat yangilanadi) va 3 s / 10 daqiqalik so'rash. Chatdagi bayonnoma: karta holati
 * (`minutesCardState`), "nima o'zgardi" (`changesText`), sarlavha qatorlari, tahrir xato kodlari va
 * kartaning so'rovi (`minutesDocPollMs`).
 */
import { ApiError, AuthRequiredError } from '@/api/client';
import type { MinutesView } from '@/api/types';
import {
  changesText,
  defaultMinutesLang,
  failedText,
  isTransientMinutesError,
  MINUTES_LANG_NAME,
  MINUTES_LANGS,
  MINUTES_POLL_LIMIT_MS,
  MINUTES_POLL_MS,
  minutesCardState,
  minutesDocPollMs,
  minutesHeaderInfo,
  minutesNotes,
  minutesProblem,
  minutesProblemAction,
  minutesProblemText,
  minutesSlot,
  minutesWarnings,
  notStartedText,
  pollMinutes,
  retryWaitText,
  upsertMinutes,
  warningNumber,
} from '@/features/meeting/minutesModel';
import { makeT } from '@/i18n';

import { chatMinutes, minutesChanges, minutesHeader, minutesView } from './fixtures/server';

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

  it('the current document is the chain tip finished last (an earlier request applied on top of a later one)', () => {
    const head = minutesView({ id: 'h', createdAt: at(1), finishedAt: at(2) });
    // R1 oldin so'ralgan, lekin R2 dan KEYIN uning ustiga yozilgan: joriy - R1.
    const r1 = minutesView({ id: 'r1', createdAt: at(3), finishedAt: at(9), parentId: 'r2', kind: 'revise', version: 3 });
    const r2 = minutesView({ id: 'r2', createdAt: at(4), finishedAt: at(6), parentId: 'h', kind: 'revise', version: 2 });
    expect(minutesSlot([head, r1, r2], 'uz-cyrl').ready?.id).toBe('r1');
    // Ikki mustaqil hujjat (masalan «Qayta yozish»): eng keyin tayyor bo'lgani.
    const rewrite = minutesView({ id: 'w', createdAt: at(5), finishedAt: at(12) });
    expect(minutesSlot([head, r1, r2, rewrite], 'uz-cyrl').ready?.id).toBe('w');
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

  it('superseded edits and truncated directions are their own lines, not counted; their numbers are read defensively', () => {
    const w = ['header_dropped:attendees', 'superseded_revisions:2', 'guidance_truncated:3', 'provider_failed:ollama'];
    expect(minutesWarnings(w)).toEqual(['header_dropped:attendees']);
    expect(warningNumber(w, 'superseded_revisions')).toBe(2);
    expect(warningNumber(w, 'guidance_truncated')).toBe(3);
    expect(warningNumber(['guidance_truncated:x', 'superseded_revisions:0'], 'guidance_truncated')).toBeNull();
    expect(warningNumber(['superseded_revisions:0'], 'superseded_revisions')).toBeNull();
    expect(warningNumber(null, 'superseded_revisions')).toBeNull();
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

  it('chat edits: no change, re-transcribed, no document, queue full; a revision the model could not write says so', () => {
    const row = (code: string, kind?: 'generate' | 'revise'): Pick<MinutesView, 'error' | 'kind'> => ({ error: { code, message: 'raw' }, kind });
    expect(failedText(t, row('no_change', 'revise'))).toBe("Bayonnomada o'zgarish bo'lmadi - nimani o'zgartirish kerakligini aniqroq yozing");
    expect(failedText(t, row('minutes_outdated', 'revise'))).toBe("Yozuv qayta o'girilgan - bayonnomani yangidan tayyorlang");
    expect(failedText(t, row('minutes_missing', 'revise'))).toBe("Bu tilda tahrirlash uchun tayyor bayonnoma yo'q - avval tayyorlang");
    expect(failedText(t, row('minutes_busy', 'revise'))).toBe("Oldingi o'zgartirishlar hali tayyorlanmoqda - tugashini kuting");
    expect(failedText(t, row('llm_failed', 'revise'))).toBe("Model bayonnomani tahrirlay olmadi - qayta urinib ko'ring");
    // Asl hujjat (yoki eski server - `kind` yo'q) - avvalgidek "yozolmadi".
    expect(failedText(t, row('llm_failed', 'generate'))).toBe("Model bayonnomani yozolmadi - qayta urinib ko'ring");
    expect(failedText(t, row('llm_failed'))).toBe("Model bayonnomani yozolmadi - qayta urinib ko'ring");
    expect(failedText(makeT('ru'), row('no_change', 'revise'))).toBe('Протокол не изменился - уточните, что именно изменить');
  });

  it('a chat request that could not start the work: the reason by code (edit limit vs minutes limit), unknown codes via err.<code>', () => {
    expect(notStartedText(t, 'minutes_busy', true)).toBe("Bayonnoma ishi boshlanmadi: Oldingi o'zgartirishlar hali tayyorlanmoqda - tugashini kuting");
    expect(notStartedText(t, 'rate_limited', true)).toBe("Bayonnoma ishi boshlanmadi: Bir soatlik tahrir chegarasi tugadi - keyinroq urinib ko'ring");
    expect(notStartedText(t, 'rate_limited', false)).toBe("Bayonnoma ishi boshlanmadi: Bir soatlik bayonnoma chegarasi tugadi - keyinroq urinib ko'ring");
    expect(notStartedText(t, 'minutes_outdated', true)).toBe("Bayonnoma ishi boshlanmadi: Yozuv qayta o'girilgan - bayonnomani yangidan tayyorlang");
    expect(notStartedText(t, 'llm_not_configured', false)).toBe('Bayonnoma ishi boshlanmadi: Bayonnoma xizmati hali sozlanmagan - administratorga murojaat qiling');
    expect(notStartedText(t, 'transcript_empty', false)).toBe("Bayonnoma ishi boshlanmadi: Yozuvda nutq topilmadi - bayonnoma uchun gapirilgan yig'ilish yozuvi kerak");
    expect(notStartedText(t, 'something_new', false)).toBe('Bayonnoma ishi boshlanmadi: Xatolik yuz berdi (something_new)');
    expect(notStartedText(makeT('en'), 'minutes_busy', true)).toBe("Work on the minutes didn't start: Earlier changes are still being prepared - please wait");
  });
});

describe('minutes: what a revision changed, the owner-stated header', () => {
  it('names the changed items as numbered in Word (singular and plural), added and removed items, agenda, header and other parts', () => {
    expect(changesText(t, minutesChanges())).toBe("O'zgarishlar: 3-band; qo'shildi: 8; sarlavha qismi");
    expect(
      changesText(t, {
        items: { changed: [7, 3, 3], added: [8, 9], removed: [4] },
        agenda: { changed: [2], added: [], removed: [] },
        header: [],
        other: ['title'],
      }),
    ).toBe("O'zgarishlar: 3, 7-bandlar; qo'shildi: 8, 9; olib tashlandi: 1 ta; kun tartibi; boshqa qismlar");
    expect(changesText(makeT('ru'), minutesChanges({ items: { changed: [3, 7], added: [], removed: [] }, header: [] }))).toBe('Изменения: пункты 3, 7');
    expect(changesText(makeT('en'), minutesChanges())).toBe('Changes: item 3; added: 8; header');
  });

  it('an empty diff (a directions revision already reflected) says the text did not change; no changes (original) - no line', () => {
    const none = { items: { changed: [], added: [], removed: [] }, agenda: { changed: [], added: [], removed: [] }, header: [], other: [] };
    expect(changesText(t, none)).toBe("O'zgarishlar: ko'rsatmalar allaqachon aks etgan - matn o'zgarmadi");
    expect(changesText(t, null)).toBeNull();
    expect(changesText(t, undefined)).toBeNull();
    // Buzuq server javobi varaqni buzmaydi.
    expect(changesText(t, { items: { changed: ['3', -1, 2.5] }, header: 'chair' } as never)).toBe("O'zgarishlar: ko'rsatmalar allaqachon aks etgan - matn o'zgarmadi");
  });

  it('header: chair and attendees lines only from what the owner stated; any filled value makes the draft note "the remaining blanks"', () => {
    expect(minutesHeaderInfo(minutesHeader())).toEqual({ chair: 'Boshqaruv raisi A.Karimov', attendees: ['[S2]', "B.Aliyev - bo'lim boshlig'i"], filled: true });
    expect(minutesHeaderInfo(minutesHeader({ chair: '  ', attendees: [] }))).toEqual({ chair: null, attendees: [], filled: false });
    expect(minutesHeaderInfo(minutesHeader({ chair: null, attendees: [], city: 'Toshkent' }))).toEqual({ chair: null, attendees: [], filled: true });
    expect(minutesHeaderInfo(null)).toEqual({ chair: null, attendees: [], filled: false });
    expect(minutesHeaderInfo({ attendees: 'x' } as never)).toEqual({ chair: null, attendees: [], filled: false });
  });
});

describe('minutes: the card under a chat answer', () => {
  const NOW = Date.parse('2026-11-06T06:02:00Z');
  const running = (over: Partial<MinutesView> = {}) => minutesView({ status: 'running', finishedAt: null, createdAt: '2026-11-06T06:00:00Z', ...over });

  it('no reference - no card; a direction - saved with the live count (at least 1)', () => {
    expect(minutesCardState(null)).toBeNull();
    expect(minutesCardState(undefined)).toBeNull();
    expect(minutesCardState(chatMinutes({ action: 'note', id: null, status: null, version: null, notes: 3 }))).toEqual({ kind: 'note', n: 3 });
    expect(minutesCardState(chatMinutes({ action: 'note', id: null, status: null, version: null, notes: null }))).toEqual({ kind: 'note', n: 1 });
  });

  it('work not started: the error code, and whether it was an edit (for the right limit text)', () => {
    const error = { code: 'minutes_busy', message: 'Bayonnomaning oldingi o\'zgarishlari hali tayyorlanmoqda' };
    expect(minutesCardState(chatMinutes({ id: null, status: null, version: null, error }))).toEqual({ kind: 'notStarted', code: 'minutes_busy', revise: true });
    expect(minutesCardState(chatMinutes({ action: 'create', id: null, status: null, version: null, error: { code: 'rate_limited', message: '' } }))).toEqual({
      kind: 'notStarted',
      code: 'rate_limited',
      revise: false,
    });
    // Na id, na xato - ko'rsatadigan narsa yo'q.
    expect(minutesCardState(chatMinutes({ id: null, status: null, error: null }))).toBeNull();
  });

  it('running: an edit (or a directions revision, version >= 2) is "a new version"; a first document is "being prepared"', () => {
    expect(minutesCardState(chatMinutes())).toEqual({ kind: 'running', revise: true, slow: false });
    expect(minutesCardState(chatMinutes({ action: 'create', version: 1 }))).toEqual({ kind: 'running', revise: false, slow: false });
    expect(minutesCardState(chatMinutes({ action: 'create', version: 2 }))).toEqual({ kind: 'running', revise: true, slow: false });
    expect(minutesCardState(chatMinutes({ action: 'create', version: 1 }), { view: running({ kind: 'revise', version: 2 }), at: NOW })).toMatchObject({ revise: true });
  });

  it('the card\'s own poll overrides the history reference: running -> ready with version and language, or failed with its code', () => {
    const ref = chatMinutes({ language: 'ru' });
    expect(minutesCardState(ref, { view: running({ language: 'ru' }), at: NOW })).toEqual({ kind: 'running', revise: true, slow: false });
    expect(minutesCardState(ref, { view: minutesView({ language: 'ru', kind: 'revise', version: 3 }), at: NOW })).toEqual({ kind: 'ready', version: 3, language: 'ru' });
    const failed = minutesView({ status: 'failed', kind: 'revise', version: 2, error: { code: 'no_change', message: 'x' } });
    expect(minutesCardState(ref, { view: failed, at: NOW })).toEqual({ kind: 'failed', code: 'no_change', revise: true });
    // Tarixdan kelgan tayyor/xato havola - so'rovsiz.
    expect(minutesCardState(chatMinutes({ status: 'ready', version: 2 }))).toEqual({ kind: 'ready', version: 2, language: 'uz-cyrl' });
    expect(minutesCardState(chatMinutes({ status: 'failed', error: { code: 'llm_failed', message: 'x' } }))).toEqual({ kind: 'failed', code: 'llm_failed', revise: true });
  });

  it('a settled history reference wins over an older cached "running" poll answer (rows never go back to running)', () => {
    const stale = { view: running(), at: NOW };
    expect(minutesCardState(chatMinutes({ status: 'ready', version: 2 }), stale)).toEqual({ kind: 'ready', version: 2, language: 'uz-cyrl' });
    const failed = chatMinutes({ status: 'failed', error: { code: 'llm_busy', message: 'x' } });
    expect(minutesCardState(failed, stale)).toEqual({ kind: 'failed', code: 'llm_busy', revise: true });
    expect(minutesCardState(chatMinutes({ status: 'ready' }), { error: new ApiError(404, 'minutes_not_found', 'x') })).toMatchObject({ kind: 'ready' });
  });

  it('still running 10 minutes after the row was created: slow ("the result will be in the sheet")', () => {
    const v = running();
    expect(minutesCardState(chatMinutes(), { view: v, at: Date.parse(v.createdAt) + MINUTES_POLL_LIMIT_MS - 1 })).toMatchObject({ slow: false });
    expect(minutesCardState(chatMinutes(), { view: v, at: Date.parse(v.createdAt) + MINUTES_POLL_LIMIT_MS })).toMatchObject({ slow: true });
  });

  it('gone: the poll got 404, or the history reference has an id but no status (the row no longer exists)', () => {
    expect(minutesCardState(chatMinutes(), { error: new ApiError(404, 'minutes_not_found', 'x') })).toEqual({ kind: 'gone' });
    expect(minutesCardState(chatMinutes({ status: null }))).toEqual({ kind: 'gone' });
    // O'tkinchi xato - hali yozilmoqda.
    expect(minutesCardState(chatMinutes(), { error: new ApiError(0, 'network', 'x') })).toEqual({ kind: 'running', revise: true, slow: false });
  });

  it('the card polls every 3 s while running and only for 10 minutes since the row was created; stops on ready, failed or a fatal error', () => {
    const v = running();
    const created = Date.parse(v.createdAt);
    expect(minutesDocPollMs(undefined, null, 0)).toBe(MINUTES_POLL_MS);
    expect(minutesDocPollMs(v, null, created + 60_000)).toBe(MINUTES_POLL_MS);
    expect(minutesDocPollMs(v, null, created + MINUTES_POLL_LIMIT_MS)).toBe(false);
    expect(minutesDocPollMs(minutesView(), null, created)).toBe(false);
    expect(minutesDocPollMs(minutesView({ status: 'failed' }), null, created)).toBe(false);
    expect(minutesDocPollMs(undefined, new ApiError(503, 'unavailable', 'x'), 0)).toBe(MINUTES_POLL_MS);
    expect(minutesDocPollMs(v, new ApiError(0, 'network', 'x'), created)).toBe(MINUTES_POLL_MS);
    expect(minutesDocPollMs(undefined, new ApiError(404, 'minutes_not_found', 'x'), 0)).toBe(false);
    expect(minutesDocPollMs(v, new ApiError(403, 'forbidden', 'x'), created)).toBe(false);
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

  it('409 minutes_busy on "Qo\'llash" (a directions revision) is the edit queue, not the transcript: re-check', () => {
    const p = minutesProblem(err(409, 'minutes_busy'), 'create');
    expect(p).toEqual({ kind: 'editBusy' });
    expect(minutesProblemText(t, p)).toBe("Oldingi o'zgartirishlar hali tayyorlanmoqda - tugashini kuting");
    expect(minutesProblemAction(p)).toBe('recheck');
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
