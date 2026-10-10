/**
 * Spec 3.2 #2-5, #7 yuklash protokolining soxta serveri (xotirada).
 * Haqiqiy ApiClient + createMeetingsApi shu server bilan fakeFetch orqali
 * gaplashadi - uploader testlari protokolni oxirigacha tekshiradi.
 */
import { createHash } from 'crypto';

import type { Meeting } from '@/api/types';

import { meeting as meetingFixture } from './server';
import { envelope, fakeFetch, type FakeReply, type FakeRequest } from './fakeFetch';

export interface ServerMeeting {
  id: string;
  clientId: string;
  data: Uint8Array;
  complete: boolean;
  completeBody: Record<string, unknown> | null;
  creates: number;
}

const sha = (b: Uint8Array) => createHash('sha256').update(b).digest('hex');

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

export class FakeServer {
  meetings = new Map<string, ServerMeeting>();
  maxChunkBytes: number;
  /** Navbatdagi so'rovga maxsus javob (xato kiritish). true qaytarsa ishlatiladi. */
  injections: { match: (r: FakeRequest) => boolean; reply: FakeReply | ((r: FakeRequest) => FakeReply); once: boolean; storeFirst?: boolean }[] = [];
  /** Bu tokenlar 401 oladi. */
  rejectTokens = new Set<string>();
  /** /upload pozitsiyasini shuncha baytga orqada ko'rsatish (eskirgan replika simulyatsiyasi). */
  positionLag = 0;
  readonly ff: ReturnType<typeof fakeFetch>;

  constructor(maxChunkBytes = 4 * 1024 * 1024) {
    this.maxChunkBytes = maxChunkBytes;
    this.ff = fakeFetch((r) => this.handle(r));
  }

  get fetch() {
    return this.ff.fetch;
  }

  get calls() {
    return this.ff.calls;
  }

  inject(match: (r: FakeRequest) => boolean, reply: FakeReply | ((r: FakeRequest) => FakeReply), opts: { once?: boolean; storeFirst?: boolean } = {}) {
    this.injections.push({ match, reply, once: opts.once ?? true, storeFirst: opts.storeFirst });
  }

  putOffsets(): number[] {
    return this.calls.filter((c) => c.method === 'PUT').map((c) => Number(c.query.offset));
  }

  private meetingJson(m: ServerMeeting): Meeting {
    return meetingFixture({
      id: m.id,
      clientId: m.clientId,
      status: m.complete ? 'uploaded' : 'uploading',
      upload: { receivedBytes: m.data.length, totalBytes: m.complete ? m.data.length : null, maxChunkBytes: this.maxChunkBytes, complete: m.complete },
    });
  }

  private byId(path: string): ServerMeeting | undefined {
    const id = path.split('/')[4];
    return [...this.meetings.values()].find((m) => m.id === id);
  }

  private handle(r: FakeRequest): FakeReply {
    const token = (r.headers.Authorization ?? '').replace('Bearer ', '');
    if (this.rejectTokens.has(token)) return envelope(401, 'Token eskirgan');

    const inj = this.injections.find((i) => i.match(r));
    if (inj) {
      if (inj.once) this.injections.splice(this.injections.indexOf(inj), 1);
      if (inj.storeFirst) this.real(r);
      return typeof inj.reply === 'function' ? inj.reply(r) : inj.reply;
    }
    return this.real(r);
  }

  private real(r: FakeRequest): FakeReply {
    const path = r.path;
    if (r.method === 'POST' && path === '/api/v1/meetings') {
      const body = r.body as { clientId: string };
      let m = [...this.meetings.values()].find((x) => x.clientId === body.clientId);
      const existed = !!m;
      if (!m) {
        m = { id: `m${this.meetings.size + 1}`.padEnd(32, '0'), clientId: body.clientId, data: new Uint8Array(), complete: false, completeBody: null, creates: 0 };
        this.meetings.set(m.id, m);
      }
      m.creates += 1;
      return { status: existed ? 200 : 201, json: this.meetingJson(m) };
    }
    const m = this.byId(path);
    if (!m) return envelope(404, 'Topilmadi', { code: 'not_found' });

    if (r.method === 'GET' && path.endsWith('/upload')) {
      return { json: { receivedBytes: Math.max(0, m.data.length - this.positionLag), maxChunkBytes: this.maxChunkBytes, complete: m.complete } };
    }
    if (r.method === 'PUT' && path.endsWith('/audio')) {
      if (m.complete) return envelope(409, 'Yopilgan', { code: 'upload_closed' });
      const offset = Number(r.query.offset);
      const bytes = r.raw ?? new Uint8Array();
      if (bytes.length > this.maxChunkBytes) return envelope(413, 'Katta', { code: 'chunk_too_large' });
      if (sha(bytes) !== r.headers['X-Chunk-Sha256']) return envelope(400, 'Sha', { code: 'sha_mismatch' });
      if (offset === m.data.length) {
        m.data = concat(m.data, bytes);
        return { json: { receivedBytes: m.data.length } };
      }
      if (offset + bytes.length <= m.data.length && sha(m.data.subarray(offset, offset + bytes.length)) === sha(bytes)) {
        return { json: { receivedBytes: m.data.length } }; // takroriy so'rov
      }
      return envelope(409, 'Offset', { code: 'offset_mismatch', receivedBytes: m.data.length });
    }
    if (r.method === 'POST' && path.endsWith('/complete')) {
      const body = r.body as { totalBytes: number; sha256: string };
      if (body.totalBytes !== m.data.length) return envelope(409, 'Tugallanmagan', { code: 'upload_incomplete', receivedBytes: m.data.length });
      if (body.sha256 !== sha(m.data)) {
        m.data = new Uint8Array();
        return envelope(409, 'Sha', { code: 'sha_mismatch', receivedBytes: 0 });
      }
      const already = m.complete;
      m.complete = true;
      m.completeBody = body as Record<string, unknown>;
      return { status: already ? 200 : 202, json: this.meetingJson(m) };
    }
    if (r.method === 'GET' && /^\/api\/v1\/meetings\/[^/]+$/.test(path)) return { json: this.meetingJson(m) };
    return envelope(404, 'Yo\'q');
  }
}

export function fileBytes(size: number, seed = 1): Uint8Array {
  const b = new Uint8Array(size);
  let x = seed;
  for (let i = 0; i < size; i++) {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    b[i] = x & 0xff;
  }
  return b;
}

export { sha };
