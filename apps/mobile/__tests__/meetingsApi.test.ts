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
    ['26 ask', (s) => s.m.ask(ID, { question: 'q' }), 'POST', `${M}/${ID}/ask`],
    ['27 questions', (s) => s.m.questions(ID), 'GET', `${M}/${ID}/questions`],
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

  it('export endpoints return text', async () => {
    const s = setup();
    await expect(s.m.exportSummary(ID, 'S', 'txt')).resolves.toBe('TEXT');
  });
});
