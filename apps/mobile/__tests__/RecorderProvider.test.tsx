/**
 * Haqiqiy RecorderProvider mantiqi skriptlanadigan soxta expo-audio yozuvchisi
 * bilan: start tartibi (navbat qatori record() dan OLDIN), native hodisalar
 * (bildirishnoma Stop, hajm limiti, MediaRecorder xatosi), xatodan keyin
 * native yozuvchining bo'shatilishi va qayta urinish, belgilar saqlanishi,
 * ilova ekranda bo'lmagan holat.
 */
import { act, render, waitFor } from '@testing-library/react-native';
import { useEffect } from 'react';

import { useAuth } from '@/features/auth/authStore';
import { maxFileSizeFor } from '@/features/recorder/preset';
import {
  RecorderProvider,
  useRecorder,
  useRecorderStore,
  type RecorderActions,
} from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import type { QueueRow } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';

import { fakeServices, Providers } from './fixtures/fakeServices';

// ---- native modul soxtalari -------------------------------------------------

const mockFg = { active: true, wait: true };
jest.mock('@/lib/appState', () => ({
  isForeground: () => mockFg.active,
  waitForForeground: async () => mockFg.wait,
  yieldToUi: async () => {},
}));

const mockFs = { moved: [] as [string, string][], deleted: [] as string[] };
jest.mock('expo-file-system', () => ({
  File: class {
    uri: string;
    constructor(uri: string) {
      this.uri = uri;
    }
    get exists() {
      return true;
    }
    moveSync(target: { uri: string }) {
      mockFs.moved.push([this.uri, target.uri]);
    }
    delete() {
      mockFs.deleted.push(this.uri);
    }
  },
}));

jest.mock('@/lib/paths', () => ({
  MIN_FREE_BYTES: 200 * 1024 * 1024,
  availableDiskBytes: () => 10 * 1024 * 1024 * 1024,
  recordingFile: (id: string) => ({ uri: `file:///doc/recordings/${id}.aac` }),
  toFileUri: (p: string) => (/^[a-z]+:\/\//i.test(p) ? p : `file://${p}`),
}));

let mockSeq = 0;
jest.mock('expo-crypto', () => ({
  getRandomBytes: (n: number) => Uint8Array.from({ length: n }, (_, i) => (i === 0 ? ++mockSeq : i)),
}));

jest.mock('expo-haptics', () => ({
  impactAsync: async () => {},
  notificationAsync: async () => {},
  selectionAsync: async () => {},
  ImpactFeedbackStyle: { Medium: 'medium' },
  NotificationFeedbackType: { Success: 'success' },
}));

type StatusEvent = { isFinished?: boolean; hasError?: boolean; error?: string | null; url?: string | null };

/** Skriptlanadigan yozuvchi: expo-audio 57 Android xatti-harakatiga mos (isPrepared -> AlreadyPrepared). */
class FakeRecorder {
  uri = '';
  prepared = false;
  isRecording = false;
  n = 0;
  failRecordOnce = false;
  log: string[] = [];
  lastOptions: Record<string, unknown> | null = null;
  listener: ((s: StatusEvent) => void) | null = null;

  prepareToRecordAsync = jest.fn(async (opts: Record<string, unknown>) => {
    this.log.push('prepare');
    if (this.prepared) throw new Error('AudioRecorderAlreadyPreparedException');
    this.prepared = true;
    this.n += 1;
    this.uri = `file:///doc/Audio/recording-${this.n}.aac`;
    this.lastOptions = opts;
  });
  record = jest.fn(() => {
    this.log.push('record');
    if (this.failRecordOnce) {
      this.failRecordOnce = false;
      throw new Error('start failed');
    }
    this.isRecording = true;
  });
  pause = jest.fn(() => {
    this.isRecording = false;
  });
  stop = jest.fn(async () => {
    this.log.push('stop');
    this.prepared = false;
    this.isRecording = false;
  });
  getStatus = jest.fn(() => ({ canRecord: this.prepared, isRecording: this.isRecording, durationMillis: 0, metering: -30, url: this.uri }));

  emit(e: StatusEvent) {
    this.listener?.(e);
  }
}

const audio = jest.requireMock('expo-audio') as {
  useAudioRecorder: jest.Mock;
  setAudioModeAsync: jest.Mock;
};

// ---- yordamchilar -----------------------------------------------------------

let fake: FakeRecorder;
/** Provider ichidan olingan amallar (ref - render paytida tashqi o'zgaruvchiga yozmaslik uchun). */
const grabbed: { current: RecorderActions | null } = { current: null };
let queue: ReturnType<typeof createMemoryQueueStore>;
let services: ReturnType<typeof fakeServices>;

function Grab() {
  const a = useRecorder();
  useEffect(() => {
    grabbed.current = a;
  }, [a]);
  return null;
}

const actions = {
  start: (o: Parameters<RecorderActions['start']>[0]) => grabbed.current!.start(o),
  mark: (n: string | null) => grabbed.current!.mark(n),
  setLastMarkNote: (n: string) => grabbed.current!.setLastMarkNote(n),
};

async function mount() {
  services = fakeServices();
  queue = createMemoryQueueStore();
  services.queue = queue;
  const origInsert = queue.insert.bind(queue);
  queue.insert = async (row: QueueRow) => {
    fake.log.push('insert');
    await origInsert(row);
  };
  await render(
    <Providers services={services}>
      <RecorderProvider>
        <Grab />
      </RecorderProvider>
    </Providers>,
  );
  await act(async () => {});
}

const OPTS = { language: 'uz' as const, template: 'auto' as const, expectedSpeakers: null, source: 'launcher' as const };
const machine = () => useRecorderStore.getState().machine;

async function startOk(): Promise<string> {
  let ok = false;
  await act(async () => {
    ok = await actions.start(OPTS);
  });
  expect(ok).toBe(true);
  expect(machine().status).toBe('recording');
  return machine().clientId as string;
}

beforeEach(() => {
  fake = new FakeRecorder();
  audio.useAudioRecorder.mockImplementation((_opts: unknown, listener: (s: StatusEvent) => void) => {
    fake.listener = listener;
    return fake;
  });
  mockFg.active = true;
  mockFg.wait = true;
  mockFs.moved = [];
  mockFs.deleted = [];
  useRecorderStore.setState({ machine: { ...initialRecorderState }, levels: [], silent: false, lastSavedClientId: null });
  useAuth.setState({ config: null });
});

// ---- testlar ----------------------------------------------------------------

describe('RecorderProvider', () => {
  it('writes the queue row (state recording) BEFORE record() and arms the native size limit', async () => {
    await mount();
    const id = await startOk();
    expect(audio.setAudioModeAsync).toHaveBeenCalledWith({
      playsInSilentMode: true,
      allowsRecording: true,
      allowsBackgroundRecording: true,
      interruptionMode: 'mixWithOthers',
    });
    expect(fake.log).toEqual(['prepare', 'insert', 'record']);
    const row = await queue.get(id);
    expect(row).toMatchObject({ state: 'recording', fileUri: fake.uri, source: 'launcher' });
    // Ekran o'chiq bo'lsa ham limitda to'xtash - MediaRecorder maxFileSize (3 soat, 48 kbps, 16 kHz).
    const android = (fake.lastOptions as { android: { maxFileSize?: number } }).android;
    expect(android.maxFileSize).toBe(maxFileSizeFor(180 * 60, 48000, 16000));
  });

  it('notification Stop (native isFinished) saves the file under recordings/<clientId>.aac and kicks the uploader', async () => {
    await mount();
    const id = await startOk();
    await act(async () => fake.emit({ isFinished: true, hasError: false, url: fake.uri }));
    await waitFor(() => expect(machine().status).toBe('stopped'));
    const row = await queue.get(id);
    expect(row).toMatchObject({ state: 'stopped', fileUri: `file:///doc/recordings/${id}.aac` });
    expect(mockFs.moved).toEqual([[fake.uri, `file:///doc/recordings/${id}.aac`]]);
    expect(useRecorderStore.getState().lastSavedClientId).toBe(id);
    expect(machine().autoStopped).toBe(false);
    expect(services.uploader.runOnce).toHaveBeenCalled();
  });

  it('the native size limit (MAX_FILESIZE_REACHED: hasError, no message, url) is an auto-stop, not an error', async () => {
    await mount();
    const id = await startOk();
    fake.prepared = false; // native o'zi reset qilgan
    await act(async () => fake.emit({ isFinished: true, hasError: true, error: null, url: fake.uri }));
    await waitFor(() => expect(machine().status).toBe('stopped'));
    expect(machine().autoStopped).toBe(true);
    expect((await queue.get(id))?.state).toBe('stopped');
    expect(fake.stop).not.toHaveBeenCalled();
  });

  it('a MediaRecorder error releases the native recorder, keeps the audio, and Retry works', async () => {
    await mount();
    const id = await startOk();
    await act(async () => fake.emit({ isFinished: true, hasError: true, error: 'The media server has crashed', url: null }));
    await waitFor(() => expect(machine().status).toBe('recorder_error'));
    expect(machine().error).toBe('The media server has crashed');
    expect(fake.stop).toHaveBeenCalledTimes(1);
    expect((await queue.get(id))?.state).toBe('stopped');
    // Native yozuvchi bo'shatilgan - yangi start AlreadyPrepared bilan yiqilmaydi.
    const id2 = await startOk();
    expect(id2).not.toBe(id);
  });

  it('record() throwing leaves no prepared recorder, no queue row and no stray file; the next start works', async () => {
    await mount();
    fake.failRecordOnce = true;
    let ok = true;
    await act(async () => {
      ok = await actions.start(OPTS);
    });
    expect(ok).toBe(false);
    expect(machine().status).toBe('recorder_error');
    expect(fake.stop).toHaveBeenCalledTimes(1);
    expect(fake.prepared).toBe(false);
    expect(await queue.list()).toEqual([]);
    expect(mockFs.deleted).toEqual(['file:///doc/Audio/recording-1.aac']);
    await startOk();
  });

  it('releases a leftover prepared native recorder before preparing again', async () => {
    await mount();
    fake.prepared = true; // oldingi xato sessiyadan qolgan holat
    await startOk();
    expect(fake.log.slice(0, 2)).toEqual(['stop', 'prepare']);
  });

  it('two simultaneous starts (deep link + button) share one session instead of releasing each other', async () => {
    await mount();
    let a = false;
    let b = false;
    await act(async () => {
      [a, b] = await Promise.all([actions.start(OPTS), actions.start(OPTS)]);
    });
    expect([a, b]).toEqual([true, true]);
    expect(fake.prepareToRecordAsync).toHaveBeenCalledTimes(1);
    expect(fake.stop).not.toHaveBeenCalled();
    expect(machine().status).toBe('recording');
    expect(await queue.list()).toHaveLength(1);
  });

  it('ignores a late native event that belongs to an older file', async () => {
    await mount();
    await startOk();
    await act(async () => fake.emit({ isFinished: true, hasError: false, url: 'file:///doc/Audio/recording-0.aac' }));
    expect(machine().status).toBe('recording');
  });

  it('persists "Muhim" marks to the queue row on every press (crash keeps them)', async () => {
    await mount();
    const id = await startOk();
    await act(async () => actions.mark(null));
    await act(async () => actions.setLastMarkNote('narx bo‘yicha qaror'));
    await waitFor(async () => expect((await queue.get(id))?.marks).toEqual([{ t: expect.any(Number), note: 'narx bo‘yicha qaror' }]));
  });

  it('does not start when the app never comes to the foreground (Android 14+ FGS rule)', async () => {
    await mount();
    mockFg.wait = false;
    let ok = true;
    await act(async () => {
      ok = await actions.start(OPTS);
    });
    expect(ok).toBe(false);
    expect(machine().status).toBe('not_foreground');
    expect(fake.prepareToRecordAsync).not.toHaveBeenCalled();
  });

  it('cleans up when the app left the screen between prepare and record()', async () => {
    await mount();
    mockFg.active = false;
    let ok = true;
    await act(async () => {
      ok = await actions.start(OPTS);
    });
    expect(ok).toBe(false);
    expect(machine().status).toBe('not_foreground');
    expect(fake.record).not.toHaveBeenCalled();
    expect(fake.stop).toHaveBeenCalledTimes(1);
    expect(await queue.list()).toEqual([]);
  });
});
