/**
 * Yuklash holati sababi (spec 3.4): qaror tartibining har qadami, tarmoq holatini
 * o'qish va telefondagi yozuvni o'chirish tartibi. Toza mantiq - ekran yo'q.
 */
import { discardLocalRecording } from '@/features/upload/discard';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import { onlineFrom, uploadStatus } from '@/features/upload/uploadStatus';

const row = (over: Partial<QueueRow> = {}): QueueRow =>
  newQueueRow({
    clientId: 'c1',
    fileUri: 'file:///doc/recordings/c1.aac',
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'app',
    startedAt: '2026-10-10T09:05:00Z',
    state: 'stopped',
    ...over,
  });

const ON = { online: true };
const OFF = { online: false };
const UNKNOWN = { online: null };

describe('uploadStatus - decision order (first match wins)', () => {
  it('1. recording beats everything (even offline with an error)', () => {
    expect(uploadStatus(row({ state: 'recording', lastError: 'network' }), OFF).cause).toBe('recording');
  });

  it('2. done', () => {
    expect(uploadStatus(row({ state: 'done', lastError: 'network' }), OFF).cause).toBe('done');
  });

  it('3. failed keeps the error code', () => {
    const st = uploadStatus(row({ state: 'failed', lastError: 'too_large' }), OFF);
    expect(st).toEqual({ cause: 'failed', percent: null, retryAt: null, errorCode: 'too_large' });
  });

  it('4. auth_required / unauthorized -> sign in again (even when offline)', () => {
    expect(uploadStatus(row({ lastError: 'auth_required' }), OFF).cause).toBe('auth');
    expect(uploadStatus(row({ lastError: 'unauthorized', state: 'uploading' }), ON).cause).toBe('auth');
  });

  it('5. phone offline -> offline, whatever the last server error was', () => {
    expect(uploadStatus(row({ lastError: 'timeout', nextAttemptAt: 5 }), OFF).cause).toBe('offline');
    expect(uploadStatus(row({ state: 'uploading', receivedBytes: 10, totalBytes: 100 }), OFF).cause).toBe('offline');
    expect(uploadStatus(row(), OFF).cause).toBe('offline');
  });

  it('6. network error: online -> server unreachable; unknown -> offline', () => {
    expect(uploadStatus(row({ lastError: 'network', nextAttemptAt: 123 }), ON)).toEqual({ cause: 'server', percent: null, retryAt: 123, errorCode: 'network' });
    expect(uploadStatus(row({ lastError: 'network' }), UNKNOWN).cause).toBe('offline');
  });

  it('7. forbidden, or not_found without a server id -> feature not enabled', () => {
    expect(uploadStatus(row({ lastError: 'forbidden' }), ON).cause).toBe('disabled');
    expect(uploadStatus(row({ lastError: 'not_found' }), UNKNOWN).cause).toBe('disabled');
    // Server id bilan 404 - uploader qayta yaratadi, bu server muammosi (8-qadam).
    expect(uploadStatus(row({ lastError: 'not_found', serverId: 'a'.repeat(32) }), ON).cause).toBe('server');
  });

  it('7b. server purged a half-uploaded meeting (uploader reset) -> just waiting, not "feature off"', () => {
    // 3 kun internetsiz qolgan telefon: server 72 soatda tozalagan, uploader qayta yaratadi.
    expect(uploadStatus(row({ lastError: 'server_reset', serverId: null, state: 'stopped' }), ON).cause).toBe('waiting');
    expect(uploadStatus(row({ lastError: 'server_reset', serverId: null, state: 'stopped' }), OFF).cause).toBe('offline');
  });

  it('8. any other error -> server, with the next retry time', () => {
    for (const code of ['timeout', 'unavailable', 'bad_gateway', 'gateway_timeout', 'internal', 'rate_limited', 'http_502', 'unknown']) {
      const st = uploadStatus(row({ lastError: code, nextAttemptAt: 1_000 }), ON);
      expect(st.cause).toBe('server');
      expect(st.retryAt).toBe(1_000);
      expect(st.errorCode).toBe(code);
    }
  });

  it('9. creating / uploading / completing -> uploading with percent (null while size unknown)', () => {
    expect(uploadStatus(row({ state: 'uploading', receivedBytes: 42, totalBytes: 100 }), ON)).toEqual({
      cause: 'uploading',
      percent: 42,
      retryAt: null,
      errorCode: null,
    });
    expect(uploadStatus(row({ state: 'creating' }), UNKNOWN).percent).toBeNull();
    expect(uploadStatus(row({ state: 'completing', receivedBytes: 100, totalBytes: 100 }), ON).percent).toBe(100);
  });

  it('10. stopped without an error -> waiting', () => {
    expect(uploadStatus(row({ state: 'stopped' }), ON).cause).toBe('waiting');
    expect(uploadStatus(row({ state: 'stopped' }), UNKNOWN).cause).toBe('waiting');
  });
});

describe('onlineFrom (expo-network state)', () => {
  it('maps connected / reachable flags and never guesses', () => {
    expect(onlineFrom({ isConnected: true, isInternetReachable: true })).toBe(true);
    expect(onlineFrom({ isConnected: true, isInternetReachable: null })).toBe(true);
    expect(onlineFrom({ isConnected: true, isInternetReachable: false })).toBe(false);
    expect(onlineFrom({ isConnected: false })).toBe(false);
    expect(onlineFrom({})).toBeNull();
    expect(onlineFrom(undefined)).toBeNull();
  });
});

describe('discardLocalRecording', () => {
  it('removes the queue row first, then the file, then the unfinished server meeting', async () => {
    const order: string[] = [];
    const queue = createMemoryQueueStore([row({ serverId: 'S1' })]);
    const remove = queue.remove.bind(queue);
    const deps = {
      queue: { remove: jest.fn(async (id: string) => (order.push(`queue:${id}`), remove(id))) },
      files: { remove: jest.fn(async (uri: string) => void order.push(`file:${uri}`)) },
      meetings: { remove: jest.fn(async (id: string) => (order.push(`server:${id}`), { deleted: true })) },
    };
    await expect(discardLocalRecording(deps as never, row({ serverId: 'S1' }))).resolves.toBe(true);
    expect(order).toEqual(['queue:c1', 'file:file:///doc/recordings/c1.aac', 'server:S1']);
    expect(queue.rows.size).toBe(0);
  });

  it('does not touch the server without a server id, and survives file/server errors', async () => {
    const deps = {
      queue: { remove: jest.fn(async () => {}) },
      files: { remove: jest.fn(async () => Promise.reject(new Error('gone'))) },
      meetings: { remove: jest.fn(async () => Promise.reject(new Error('offline'))) },
    };
    await expect(discardLocalRecording(deps as never, row())).resolves.toBe(true);
    expect(deps.meetings.remove).not.toHaveBeenCalled();
    await expect(discardLocalRecording(deps as never, row({ serverId: 'S2' }))).resolves.toBe(true);
    expect(deps.meetings.remove).toHaveBeenCalledWith('S2');
  });

  it('refuses while the row is still recording', async () => {
    const deps = { queue: { remove: jest.fn() }, files: { remove: jest.fn() }, meetings: { remove: jest.fn() } };
    await expect(discardLocalRecording(deps as never, row({ state: 'recording' }))).resolves.toBe(false);
    expect(deps.queue.remove).not.toHaveBeenCalled();
    expect(deps.files.remove).not.toHaveBeenCalled();
  });
});
