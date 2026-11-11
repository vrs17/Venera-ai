/**
 * Yozuv chatining sof mantig'i (`chatModel`): server javobini tarixga qo'shish (takrorsiz), xabar
 * kaliti (`clientId`) va xabar aslida yetib borganmi, javobi noma'lum xato, xato matni (WAF ning
 * HTML 403 i "ruxsat yo'q" emas), chat 404 ining ikki ma'nosi (eski server / yozuv yo'q), model nomi
 * va yozish maydonining klaviatura/pleer ustidagi bo'shlig'i. Tarmoqqa chiqmaydi.
 */
import { ApiClient, ApiError, type TokenProvider } from '@/api/client';
import { createMeetingsApi } from '@/api/meetings';
import { makeT } from '@/i18n';
import {
  chatErrorText,
  chatMissingOnServer,
  chatModelLabel,
  chatOutcomeUnknown,
  chatRecordingGone,
  composerInset,
  newChatClientId,
  wasDelivered,
  withTurn,
} from '@/features/meeting/chatModel';

import { envelope, fakeFetch } from './fixtures/fakeFetch';
import { chatTurn } from './fixtures/server';

const t = makeT('uz');
const tp: TokenProvider = { getToken: async () => 'tok', refreshToken: async () => 'tok2' };

describe('withTurn', () => {
  const a = chatTurn({ id: 'a' });
  const b = chatTurn({ id: 'b', answer: 'birinchi' });

  it('appends the server turn at the end (history is oldest first)', () => {
    expect(withTurn({ items: [a], model: 'claude-sonnet-5-5' }, b)).toEqual({ items: [a, b], model: 'claude-sonnet-5-5' });
  });

  it('no history in the cache yet: a list of one, model from the turn', () => {
    expect(withTurn(undefined, b)).toEqual({ items: [b], model: 'claude-sonnet-5-5' });
    expect(withTurn(undefined, chatTurn({ id: 'x', model: null }))).toMatchObject({ model: '' });
  });

  it('the same id is never shown twice (refetch already brought it): replaced in place', () => {
    const fresh = { ...b, answer: 'yangilangan' };
    const out = withTurn({ items: [a, b], model: 'm' }, fresh);
    expect(out.items.map((x) => [x.id, x.answer])).toEqual([
      ['a', a.answer],
      ['b', 'yangilangan'],
    ]);
  });
});

describe('newChatClientId (idempotency key of a message: server ChatRequest.clientId)', () => {
  /** Server qoidasi (R3-1): 8-64 belgi, faqat harf, raqam, `_` va `-`; ilova 16-36 belgi beradi. */
  const SERVER_RULE = /^[A-Za-z0-9_-]{8,64}$/;
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  it('a url-safe UUID v4 (36 chars) that the server accepts; every call is a new key', () => {
    const ids = Array.from({ length: 200 }, () => newChatClientId());
    for (const id of ids) {
      expect(id).toMatch(UUID);
      expect(id).toMatch(SERVER_RULE);
      expect(id.length).toBeGreaterThanOrEqual(16);
      expect(id.length).toBeLessThanOrEqual(36);
    }
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('built from the given random bytes (expo-crypto in the app)', () => {
    expect(newChatClientId((n) => new Uint8Array(n).fill(0xab))).toBe('abababab-abab-4bab-abab-abababababab');
  });

  it('the native random source fails or returns junk: still a valid, distinct key (Math.random fallback)', () => {
    const broken = [
      () => {
        throw new Error('UnavailabilityError: getRandomBytes');
      },
      () => undefined as unknown as Uint8Array,
      () => new Uint8Array(3),
    ];
    const ids = broken.map((source) => newChatClientId(source));
    for (const id of ids) expect(id).toMatch(UUID);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('wasDelivered (the history has the turn of this message: same clientId)', () => {
  const KEY = '5f0c2a3b-1111-4222-8333-444455556666';
  const old = chatTurn({ id: '1'.repeat(32), question: 'Narx qancha?', clientId: 'eski-kalit-0000000000' });
  const stored = chatTurn({ id: '2'.repeat(32), question: 'Narx qancha?', clientId: KEY });

  it('a turn carrying exactly this clientId = delivered (wherever it is in the list)', () => {
    expect(wasDelivered([old, stored], KEY)).toBe(true);
    expect(wasDelivered([stored, old], KEY)).toBe(true);
  });

  it('the same question TEXT is no proof: an earlier identical question with another key, a bot turn or a legacy row without a key', () => {
    expect(wasDelivered([old], KEY)).toBe(false);
    expect(wasDelivered([chatTurn({ question: 'Narx qancha?', clientId: null, channel: 'telegram' })], KEY)).toBe(false);
    expect(wasDelivered([chatTurn({ question: 'Narx qancha?', clientId: KEY.toUpperCase() })], KEY)).toBe(false);
  });

  it('no history, or a message without a key, is never "delivered"; the time of the turn plays no part', () => {
    expect(wasDelivered(undefined, KEY)).toBe(false);
    expect(wasDelivered([], KEY)).toBe(false);
    expect(wasDelivered([chatTurn({ clientId: null })], null)).toBe(false);
    expect(wasDelivered([chatTurn({ clientId: null })], '')).toBe(false);
    expect(wasDelivered([chatTurn({ clientId: null })], undefined)).toBe(false);
    // Server soati telefondan ancha orqada bo'lsa ham - kalit hal qiladi.
    expect(wasDelivered([{ ...stored, createdAt: '2001-01-01T00:00:00Z' }], KEY)).toBe(true);
  });
});

describe('chatOutcomeUnknown (did the server get the message? - cannot tell)', () => {
  it('no connection, the phone stopped waiting, or a proxy page instead of our envelope (5xx with no JSON body) = unknown', () => {
    expect(chatOutcomeUnknown(new ApiError(0, 'network', 'Tarmoq xatosi'))).toBe(true);
    expect(chatOutcomeUnknown(new ApiError(0, 'timeout', "So'rov vaqti tugadi (150 s)"))).toBe(true);
    for (const status of [500, 502, 503, 504]) expect(chatOutcomeUnknown(new ApiError(status, `http_${status}`, 'x', null))).toBe(true);
  });

  it('our own envelope answers for sure (nothing stored), and so does every 4xx', () => {
    expect(chatOutcomeUnknown(new ApiError(503, 'llm_unavailable', 'x', { code: 'llm_unavailable' }))).toBe(false);
    expect(chatOutcomeUnknown(new ApiError(500, 'internal', 'x', { message: 'Ichki xato' }))).toBe(false);
    expect(chatOutcomeUnknown(new ApiError(429, 'rate_limited', 'x', null, 60))).toBe(false);
    expect(chatOutcomeUnknown(new ApiError(403, 'forbidden', 'x', null))).toBe(false);
    expect(chatOutcomeUnknown(new ApiError(404, 'not_found', 'x', { code: 'not_found' }))).toBe(false);
    expect(chatOutcomeUnknown(new Error('boom'))).toBe(false);
    expect(chatOutcomeUnknown(null)).toBe(false);
  });

  it('through the real client: an nginx 504 page and a dropped connection are unknown, our 503 envelope is not', async () => {
    let reply: 'html' | 'ours' | 'drop' = 'html';
    const ff = fakeFetch(() => {
      if (reply === 'drop') return { networkError: true };
      return reply === 'html' ? { status: 504, text: '<html><body>504 Gateway Time-out</body></html>' } : envelope(503, 'Model band', { code: 'llm_unavailable' });
    });
    const api = createMeetingsApi(new ApiClient({ baseUrl: 'https://llm.brb-tech.uz', fetch: ff.fetch, tokens: tp }));
    const send = async (kind: typeof reply) => {
      reply = kind;
      return api.sendChat('m1', { message: 'q', channel: 'mobile', clientId: 'k'.repeat(16) }).catch((e: unknown) => e);
    };
    expect(chatOutcomeUnknown(await send('html'))).toBe(true);
    expect(chatOutcomeUnknown(await send('drop'))).toBe(true);
    expect(chatOutcomeUnknown(await send('ours'))).toBe(false);
  });
});

describe('chatErrorText', () => {
  it('rate limit, model unavailable and transcript-not-ready have their own words', () => {
    expect(chatErrorText(t, new ApiError(429, 'rate_limited', "So'rovlar ko'p", null, 60))).toBe("Juda ko'p so'rov - birozdan keyin urinib ko'ring");
    expect(chatErrorText(t, new ApiError(503, 'llm_unavailable', 'x', { code: 'llm_unavailable' }))).toBe("AI hozir mavjud emas - keyinroq urinib ko'ring");
    expect(chatErrorText(t, new ApiError(409, 'not_ready', 'x', { code: 'not_ready' }))).toBe("Savol berish uchun matn tayyor bo'lishi kerak");
  });

  it('WAF/proxy 403 with an HTML body (real client): "did not get through", not "no permission"; our JSON 403 stays "no permission"', async () => {
    const ff = fakeFetch((r) =>
      r.method === 'POST' ? { status: 403, text: '<html><body><h1>403 Forbidden</h1>Request blocked</body></html>' } : envelope(403, "Ruxsat yo'q", { code: 'forbidden' }),
    );
    const api = createMeetingsApi(new ApiClient({ baseUrl: 'https://llm.brb-tech.uz', fetch: ff.fetch, tokens: tp }));
    const waf = await api.sendChat('m1', { message: 'q', channel: 'mobile' }).catch((e: unknown) => e);
    expect(waf).toMatchObject({ status: 403, body: null });
    expect(chatErrorText(t, waf)).toBe('Xabar yetib bormadi - qayta yuboring');
    expect(chatErrorText(t, waf)).not.toMatch(/html|403/i);
    const ours = await api.chatHistory('m1').catch((e: unknown) => e);
    expect(chatErrorText(t, ours)).toBe("Bu bo'lim uchun ruxsat yo'q");
  });

  it('everything else goes through the common error words (code kept for unknown ones)', () => {
    expect(chatErrorText(t, new ApiError(0, 'network', 'Tarmoq xatosi'))).toBe("Internet yo'q");
    expect(chatErrorText(t, new ApiError(0, 'timeout', 'x'))).toBe('Server javob bermadi');
    expect(chatErrorText(t, new ApiError(500, 'weird_code', 'x', { code: 'weird_code' }))).toBe('Xatolik yuz berdi (weird_code)');
    expect(chatErrorText(t, new Error('boom'))).toBe('Xatolik yuz berdi');
    expect(chatErrorText(makeT('en'), new ApiError(403, 'forbidden', 'x', null))).toBe("The message didn't go through - send it again");
  });
});

describe('chatMissingOnServer / chatRecordingGone / chatModelLabel', () => {
  /** Server konverti (`core/errors.py`): yo'l topilmasa `code` yo'q, yozuv topilmasa `code: not_found`. */
  const routeMissing = { timestamp: '2026-11-11T06:00:00Z', status: 404, error: 'Not Found', message: 'Not Found', path: '/api/v1/meetings/m1/chat' };
  const recordingMissing = { ...routeMissing, message: "Yig'ilish topilmadi", code: 'not_found' };

  it('a 404 WITHOUT a server code on the chat history = the server has no /chat yet (old server)', () => {
    // client.ts kodsiz 404 ga ham `not_found` qo'yadi - shuning uchun konvert (`body.code`) qaraladi.
    expect(chatMissingOnServer(new ApiError(404, 'not_found', 'Not Found'))).toBe(true);
    expect(chatMissingOnServer(new ApiError(404, 'not_found', 'Not Found', routeMissing))).toBe(true);
    expect(chatMissingOnServer(new ApiError(404, 'not_found', 'Not Found', { ...routeMissing, code: '' }))).toBe(true);
    expect(chatRecordingGone(new ApiError(404, 'not_found', 'Not Found', routeMissing))).toBe(false);
    expect(chatMissingOnServer(new ApiError(500, 'internal', 'x'))).toBe(false);
    expect(chatMissingOnServer(new Error('x'))).toBe(false);
  });

  it('a 404 WITH the server code not_found = the recording is deleted or not yours, not an old server', () => {
    const err = new ApiError(404, 'not_found', "Yig'ilish topilmadi", recordingMissing);
    expect(chatMissingOnServer(err)).toBe(false);
    expect(chatRecordingGone(err)).toBe(true);
    expect(chatRecordingGone(new ApiError(404, 'not_found', 'Not Found'))).toBe(false);
    expect(chatRecordingGone(new ApiError(409, 'not_found', 'x', { code: 'not_found' }))).toBe(false);
    expect(chatRecordingGone(new Error('x'))).toBe(false);
  });

  it('both 404 bodies through the real client: old server (envelope without code, nginx HTML page) vs recording not found', async () => {
    const reply = { old: envelope(404, 'Not Found'), html: { status: 404, text: '<html><body>404 Not Found</body></html>' }, gone: envelope(404, "Yig'ilish topilmadi", { code: 'not_found' }) };
    let next: keyof typeof reply = 'old';
    const ff = fakeFetch(() => reply[next]);
    const api = createMeetingsApi(new ApiClient({ baseUrl: 'https://llm.brb-tech.uz', fetch: ff.fetch, tokens: tp }));
    const load = async (kind: keyof typeof reply) => {
      next = kind;
      return api.chatHistory('m1').catch((e: unknown) => e);
    };
    const old = await load('old');
    expect(old).toMatchObject({ status: 404, code: 'not_found' });
    expect([chatMissingOnServer(old), chatRecordingGone(old)]).toEqual([true, false]);
    const html = await load('html');
    expect(html).toMatchObject({ status: 404, body: null });
    expect([chatMissingOnServer(html), chatRecordingGone(html)]).toEqual([true, false]);
    const gone = await load('gone');
    expect(gone).toMatchObject({ status: 404, code: 'not_found' });
    expect([chatMissingOnServer(gone), chatRecordingGone(gone)]).toEqual([false, true]);
  });

  it('Claude models get the same name as the summary caption; other labels are not shown', () => {
    expect(chatModelLabel('claude-sonnet-5-5')).toBe('Claude Sonnet 5.5');
    expect(chatModelLabel('claude-opus-5-5')).toBe('Claude Opus 5.5');
    expect(chatModelLabel('claude')).toBe('Claude');
    expect(chatModelLabel('')).toBeNull();
    expect(chatModelLabel(null)).toBeNull();
    expect(chatModelLabel('gemma4:31b')).toBeNull();
  });
});

describe('composerInset (composer above the keyboard, not above the hidden player)', () => {
  it('keyboard closed: the player already covers the navigation bar; without a player - the bar inset', () => {
    expect(composerInset({ keyboard: 0, navInset: 24, below: 96 })).toBe(0);
    expect(composerInset({ keyboard: 0, navInset: 24, below: 0 })).toBe(24);
  });

  it('keyboard open: the player stays under the keyboard, so only the rest is padded', () => {
    // useKeyboardPadding: klaviatura + navigatsiya paneli (oyna qisqarmagan, edge-to-edge).
    expect(composerInset({ keyboard: 324, navInset: 24, below: 96 })).toBe(228);
    expect(composerInset({ keyboard: 324, navInset: 24, below: 0 })).toBe(324);
    expect(composerInset({ keyboard: 50, navInset: 24, below: 96 })).toBe(0);
    expect(composerInset({ keyboard: 324, navInset: 24, below: -5 })).toBe(324);
  });
});
