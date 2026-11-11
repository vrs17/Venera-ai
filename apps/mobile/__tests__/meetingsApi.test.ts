/** Har bir endpoint (spec 3.2 #1-31) to'g'ri metod va yo'lga boradimi. */
import { ApiClient, type TokenProvider } from '@/api/client';
import { createAuthApi, createMeetingsApi } from '@/api/meetings';

import { fakeFetch } from './fixtures/fakeFetch';

const tp: TokenProvider = { getToken: async () => 'tok', refreshToken: async () => 'tok2' };

function setup() {
  const ff = fakeFetch((r) => (r.path.endsWith('/export') ? { text: 'TEXT' } : { status: 200, json: { ok: true, upload: {} } }));
  const client = new ApiClient({ baseUrl: 'https://llm.brb-tech.uz', fetch: ff.fetch, tokens: tp });
  return { ...ff, m: createMeetingsApi(client), a: createAuthApi(client), client };
}

const ID = 'a'.repeat(32);
const M = '/api/v1/meetings';

describe('meetings API endpoints', () => {
  const cases: [string, (s: ReturnType<typeof setup>) => Promise<unknown>, string, string, Record<string, string>?][] = [
    ['1 config', (s) => s.m.config(), 'GET', `${M}/config`],
    [
      '2 create',
      (s) =>
        s.m.create({
          clientId: 'u',
          title: null,
          recordedAt: 'x',
          language: 'uz',
          template: 'auto',
          expectedSpeakers: null,
          contentType: 'audio/aac',
          source: 'app',
          appVersion: '1',
          device: 'd',
        }),
      'POST',
      M,
    ],
    ['3 upload position', (s) => s.m.uploadPosition(ID), 'GET', `${M}/${ID}/upload`],
    ['4 chunk', (s) => s.m.putChunk(ID, 4194304, new Uint8Array([1]), 'abc'), 'PUT', `${M}/${ID}/audio`, { offset: '4194304' }],
    ['5 complete', (s) => s.m.complete(ID, { totalBytes: 1, sha256: 'x', durationSec: 1, endedAt: 'x', marks: [] }), 'POST', `${M}/${ID}/complete`],
    ['6 list', (s) => s.m.list({ q: "narx", status: 'ready' }), 'GET', M, { limit: '20', offset: '0', q: 'narx', status: 'ready' }],
    ['6b list: Plaud filtri va tartibi', (s) => s.m.list({ origin: 'slack', sort: 'listed' }), 'GET', M, { limit: '20', offset: '0', origin: 'slack', sort: 'listed' }],
    ['6c list: filtrsiz (Hammasi)', (s) => s.m.list({ origin: null, sort: 'listed' }), 'GET', M, { limit: '20', offset: '0', sort: 'listed' }],
    ['7 get', (s) => s.m.get(ID), 'GET', `${M}/${ID}`],
    ['8 patch', (s) => s.m.patch(ID, { title: 'T' }), 'PATCH', `${M}/${ID}`],
    ['9 delete', (s) => s.m.remove(ID), 'DELETE', `${M}/${ID}`],
    ['10 retry', (s) => s.m.retry(ID), 'POST', `${M}/${ID}/retry`],
    ['11 retranscribe', (s) => s.m.retranscribe(ID, { language: 'ru', confirmCharge: true }), 'POST', `${M}/${ID}/retranscribe`],
    ['12 transcript', (s) => s.m.transcript(ID), 'GET', `${M}/${ID}/transcript`],
    ['13 rename speaker', (s) => s.m.renameSpeaker(ID, 'S2', 'Aziz'), 'PATCH', `${M}/${ID}/speakers/S2`],
    ['14 merge speakers', (s) => s.m.mergeSpeakers(ID, { from: ['S3'], into: 'S1' }), 'POST', `${M}/${ID}/speakers/merge`],
    ['15 patch segment', (s) => s.m.patchSegment(ID, 12, { text: 'x' }), 'PATCH', `${M}/${ID}/segments/12`],
    ['16 summaries', (s) => s.m.summaries(ID), 'GET', `${M}/${ID}/summaries`],
    ['17 create summary', (s) => s.m.createSummary(ID, { template: 'minutes' }), 'POST', `${M}/${ID}/summaries`],
    ['18 summary', (s) => s.m.summary(ID, 'S'), 'GET', `${M}/${ID}/summaries/S`],
    ['19 delete summary', (s) => s.m.deleteSummary(ID, 'S'), 'DELETE', `${M}/${ID}/summaries/S`],
    ['20 export summary', (s) => s.m.exportSummary(ID, 'S', 'md'), 'GET', `${M}/${ID}/summaries/S/export`, { format: 'md' }],
    [
      '21 export transcript',
      (s) => s.m.exportTranscript(ID, { format: 'srt' }),
      'GET',
      `${M}/${ID}/transcript/export`,
      { format: 'srt', speakers: '1', timestamps: '1' },
    ],
    ['22 action items', (s) => s.m.actionItems(ID), 'GET', `${M}/${ID}/action-items`],
    ['23 add action item', (s) => s.m.addActionItem(ID, { task: 'x' }), 'POST', `${M}/${ID}/action-items`],
    ['24 patch action item', (s) => s.m.patchActionItem(ID, 'I', { status: 'done' }), 'PATCH', `${M}/${ID}/action-items/I`],
    ['25 my action items', (s) => s.m.myActionItems('open', 100), 'GET', `${M}/action-items`, { status: 'open', limit: '100' }],
    ['26a chat history', (s) => s.m.chatHistory(ID), 'GET', `${M}/${ID}/chat`],
    ['26b chat message', (s) => s.m.sendChat(ID, { message: 'q', language: 'uz', channel: 'mobile' }), 'POST', `${M}/${ID}/chat`],
    ['26c new chat (archive)', (s) => s.m.resetChat(ID), 'DELETE', `${M}/${ID}/chat`],
    ['34a minutes list', (s) => s.m.minutesList(ID), 'GET', `${M}/${ID}/minutes`],
    ['34b create minutes', (s) => s.m.createMinutes(ID, { language: 'uz-cyrl', force: true }), 'POST', `${M}/${ID}/minutes`],
    ['34c minutes', (s) => s.m.minutes(ID, 'D1'), 'GET', `${M}/${ID}/minutes/D1`],
    ['29 register device', (s) => s.a.registerDevice({ deviceName: 'd', platform: 'android', appVersion: '1' }, 'jwt'), 'POST', '/api/v1/auth/devices'],
    ['30 device session', (s) => s.a.deviceSession('dt'), 'POST', '/api/v1/auth/devices/session'],
    ['31 revoke device', (s) => s.a.revokeDevice('dt'), 'POST', '/api/v1/auth/devices/revoke'],
    ['login', (s) => s.a.login({ username: 'u', password: 'p' }), 'POST', '/api/v1/auth/login'],
    ['logout', (s) => s.a.logout(), 'POST', '/api/v1/auth/logout'],
    ['me', (s) => s.a.me(), 'GET', '/api/v1/auth/me'],
  ];

  // Obyekt ko'rinishi: qator uzunligi har xil bo'lsa jest oxirgi parametrni `done` deb o'ylaydi.
  const rows = cases.map(([name, call, method, path, query]) => ({ name, call, method, path, query }));

  it.each(rows)('$name', async ({ call, method, path, query }) => {
    const s = setup();
    await call(s);
    expect(s.calls).toHaveLength(1);
    expect(s.calls[0].method).toBe(method);
    expect(s.calls[0].path).toBe(path);
    if (query) expect(s.calls[0].query).toEqual(query);
  });

  it('28 audio URL is built for the player (auth via headers)', () => {
    const s = setup();
    expect(s.m.audioUrl(ID)).toBe(`https://llm.brb-tech.uz${M}/${ID}/audio`);
  });

  it('chunk PUT carries X-Chunk-Sha256 and raw body', async () => {
    const s = setup();
    await s.m.putChunk(ID, 0, new Uint8Array([9, 9]), 'deadbeef');
    expect(s.calls[0].headers['X-Chunk-Sha256']).toBe('deadbeef');
    expect(Array.from(s.calls[0].raw ?? [])).toEqual([9, 9]);
  });

  it('device session / revoke / login never send a Bearer; register sends the fresh JWT', async () => {
    const s = setup();
    await s.a.deviceSession('dt');
    await s.a.revokeDevice('dt');
    await s.a.login({ username: 'u', password: 'p' });
    await s.a.registerDevice({ deviceName: 'd', platform: 'android', appVersion: '1' }, 'fresh');
    expect(s.calls.slice(0, 3).map((c) => c.headers.Authorization)).toEqual([undefined, undefined, undefined]);
    expect(s.calls[3].headers.Authorization).toBe('Bearer fresh');
    expect(s.calls[0].body).toEqual({ deviceToken: 'dt' });
  });

  it('26b chat message: JSON body with the message, answer language, channel=mobile and the idempotency key, Bearer; 26a/26c have no body', async () => {
    const s = setup();
    const clientId = '5f0c2a3b-1111-4222-8333-444455556666';
    await s.m.sendChat(ID, { message: 'Kim hisobot yuboradi?', language: 'ru', channel: 'mobile', clientId });
    await s.m.chatHistory(ID);
    await s.m.resetChat(ID);
    expect(s.calls[0].body).toEqual({ message: 'Kim hisobot yuboradi?', language: 'ru', channel: 'mobile', clientId });
    expect(s.calls[0].headers['Content-Type']).toBe('application/json');
    expect(s.calls.map((c) => [c.method, c.headers.Authorization, c.body])).toEqual([
      ['POST', 'Bearer tok', { message: 'Kim hisobot yuboradi?', language: 'ru', channel: 'mobile', clientId }],
      ['GET', 'Bearer tok', null],
      ['DELETE', 'Bearer tok', null],
    ]);
  });

  it('34b sends an explicit document language and force (server: plain "uz" = Latin, none = Cyrillic)', async () => {
    const s = setup();
    await s.m.createMinutes(ID, { language: 'uz-latn', force: false });
    expect(s.calls[0].body).toEqual({ language: 'uz-latn', force: false });
    expect(s.calls[0].headers.Authorization).toBe('Bearer tok');
  });

  it('34d/21b file URLs: minutes export and transcript subtitles (downloaded with auth, not via JSON)', () => {
    const s = setup();
    expect(s.m.minutesExportUrl(ID, 'D1', 'docx')).toBe(`https://llm.brb-tech.uz${M}/${ID}/minutes/D1/export?format=docx`);
    expect(s.m.minutesExportUrl(ID, 'D1', 'pdf')).toBe(`https://llm.brb-tech.uz${M}/${ID}/minutes/D1/export?format=pdf`);
    expect(s.m.transcriptExportUrl(ID, 'srt')).toBe(`https://llm.brb-tech.uz${M}/${ID}/transcript/export?format=srt`);
    expect(s.calls).toHaveLength(0);
  });

  it('export endpoints return text', async () => {
    const s = setup();
    await expect(s.m.exportSummary(ID, 'S', 'txt')).resolves.toBe('TEXT');
  });
});
