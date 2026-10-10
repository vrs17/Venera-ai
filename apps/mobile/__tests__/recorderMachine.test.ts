import { addMark, MAX_MARKS, MAX_NOTE_CHARS, normalizeNote, setLastNote } from '@/features/recorder/marks';
import { createSilenceDetector, levelFromDb, pushLevel } from '@/features/recorder/metering';
import { adtsBytesPerSec, maxFileSizeFor, MEETING_PRESET, NATIVE_LIMIT_MARGIN_SEC, presetFromConfig } from '@/features/recorder/preset';
import {
  classifyNativeEvent,
  durationSec,
  elapsedMs,
  initialRecorderState,
  isActive,
  limitState,
  recoverRows,
  reduce,
  type RecorderEvent,
  type RecorderState,
} from '@/features/recorder/recorderMachine';
import { newQueueRow } from '@/features/upload/queueStore';

const run = (events: RecorderEvent[], from: RecorderState = initialRecorderState) => events.reduce(reduce, from);
const T0 = 1_000_000;

describe('recorderMachine', () => {
  it('idle -> preparing -> recording <-> paused -> stopping -> stopped', () => {
    let s = run([{ type: 'PREPARE', clientId: 'c1', maxSec: 3600, source: 'tile' }]);
    expect(s).toMatchObject({ status: 'preparing', clientId: 'c1', source: 'tile' });
    s = reduce(s, { type: 'STARTED', at: T0 });
    expect(s.status).toBe('recording');
    s = reduce(s, { type: 'PAUSE', at: T0 + 10_000 });
    expect(s.status).toBe('paused');
    s = reduce(s, { type: 'RESUME', at: T0 + 70_000 });
    expect(s.status).toBe('recording');
    s = reduce(s, { type: 'STOP', at: T0 + 80_000 });
    expect(s.status).toBe('stopping');
    s = reduce(s, { type: 'STOPPED' });
    expect(s.status).toBe('stopped');
    expect(isActive(s)).toBe(false);
  });

  it('excludes paused time from the timeline (duration and mark times)', () => {
    let s = run([
      { type: 'PREPARE', clientId: 'c1', maxSec: 3600, source: 'app' },
      { type: 'STARTED', at: T0 },
      { type: 'MARK', at: T0 + 5_000, note: 'boshi' },
      { type: 'PAUSE', at: T0 + 10_000 },
    ]);
    expect(elapsedMs(s, T0 + 60_000)).toBe(10_000); // pauza davomida vaqt o'smaydi
    s = run([{ type: 'MARK', at: T0 + 60_000 }, { type: 'RESUME', at: T0 + 70_000 }, { type: 'MARK', at: T0 + 75_000, note: 'narx' }], s);
    expect(s.marks).toEqual([
      { t: 5, note: 'boshi' },
      { t: 10, note: null },
      { t: 15, note: 'narx' },
    ]);
    s = reduce(s, { type: 'STOP', at: T0 + 80_500 });
    expect(durationSec(s, T0 + 999_999)).toBe(20.5);
    expect(s.endedAt).toBe(T0 + 80_500);
  });

  it('is idempotent: PREPARE while recording does nothing; invalid transitions are ignored', () => {
    const rec = run([
      { type: 'PREPARE', clientId: 'c1', maxSec: 3600, source: 'app' },
      { type: 'STARTED', at: T0 },
    ]);
    expect(reduce(rec, { type: 'PREPARE', clientId: 'c2', maxSec: 1, source: 'tile' })).toBe(rec);
    expect(reduce(rec, { type: 'RESUME', at: T0 })).toBe(rec);
    expect(reduce(rec, { type: 'RESET' })).toBe(rec);
    expect(reduce(initialRecorderState, { type: 'STOP', at: T0 })).toBe(initialRecorderState);
    expect(reduce(initialRecorderState, { type: 'MARK', at: T0 })).toBe(initialRecorderState);
  });

  it('warns 10 minutes before the limit and reports the limit for auto-stop', () => {
    let s = run([
      { type: 'PREPARE', clientId: 'c1', maxSec: 30 * 60, source: 'app' },
      { type: 'STARTED', at: T0 },
    ]);
    expect(limitState(s, T0 + 19 * 60_000)).toBe('ok');
    s = reduce(s, { type: 'TICK', at: T0 + 19 * 60_000 });
    expect(s.warned).toBe(false);
    s = reduce(s, { type: 'TICK', at: T0 + 20 * 60_000 });
    expect(s.warned).toBe(true);
    expect(limitState(s, T0 + 30 * 60_000)).toBe('limit');
    s = reduce(s, { type: 'STOP', at: T0 + 30 * 60_000, auto: true });
    expect(s.autoStopped).toBe(true);
    expect(durationSec(s, 0)).toBe(1800);
  });

  it('errors keep the elapsed time and allow a reset', () => {
    let s = run([
      { type: 'PREPARE', clientId: 'c1', maxSec: 3600, source: 'app' },
      { type: 'STARTED', at: T0 },
      { type: 'FAIL', status: 'recorder_error', message: 'mic busy', at: T0 + 3000 },
    ]);
    expect(s).toMatchObject({ status: 'recorder_error', error: 'mic busy', accumulatedMs: 3000 });
    s = reduce(s, { type: 'RESET' });
    expect(s).toEqual(initialRecorderState);
    expect(reduce(initialRecorderState, { type: 'FAIL', status: 'permission_denied' }).status).toBe('permission_denied');
  });

  it('crash recovery: recording rows that are not the active recorder become stopped', () => {
    const mk = (id: string, state: 'recording' | 'uploading') =>
      newQueueRow({ clientId: id, fileUri: `file:///${id}.aac`, language: 'uz', template: 'auto', expectedSpeakers: null, source: 'app', startedAt: 'x', state });
    const out = recoverRows([mk('dead', 'recording'), mk('live', 'recording'), mk('up', 'uploading')], 'live', '2026-10-09T08:00:00Z');
    expect(out).toEqual([{ clientId: 'dead', patch: { state: 'stopped', endedAt: '2026-10-09T08:00:00Z' } }]);
  });
});

describe('marks', () => {
  it('caps notes at 200 chars and the list at 200 marks', () => {
    expect(normalizeNote('  narx   bo\'yicha  ')).toBe("narx bo'yicha");
    expect(normalizeNote('   ')).toBeNull();
    expect(normalizeNote('x'.repeat(500))).toHaveLength(MAX_NOTE_CHARS);
    let marks = addMark([], 1.234, null);
    expect(marks).toEqual([{ t: 1.23, note: null }]);
    marks = setLastNote(marks, 'muhim');
    expect(marks[0].note).toBe('muhim');
    const full = Array.from({ length: MAX_MARKS }, (_, i) => ({ t: i, note: null }));
    expect(addMark(full, 999)).toBe(full);
  });
});

describe('metering', () => {
  it('maps dBFS to a 0..1 level', () => {
    expect(levelFromDb(0)).toBe(1);
    expect(levelFromDb(-60)).toBe(0);
    expect(levelFromDb(-90)).toBe(0);
    expect(levelFromDb(undefined)).toBe(0);
    expect(levelFromDb(-30)).toBeCloseTo(0.5);
    expect(pushLevel([1, 2, 3], 4, 3)).toEqual([2, 3, 4]);
  });

  it('flags silence below -50 dBFS only after 60 s', () => {
    const d = createSilenceDetector();
    expect(d.push(-55, 0)).toBe(false);
    expect(d.push(-55, 59_000)).toBe(false);
    expect(d.push(-55, 60_000)).toBe(true);
    expect(d.push(-20, 61_000)).toBe(false);
    expect(d.push(-55, 62_000)).toBe(false);
  });
});

describe('recording preset', () => {
  it('is AAC-LC ADTS mono 16 kHz 48 kbps in the document directory', () => {
    expect(MEETING_PRESET).toMatchObject({
      extension: '.aac',
      sampleRate: 16000,
      numberOfChannels: 1,
      bitRate: 48000,
      isMeteringEnabled: true,
      directory: 'document',
      android: { extension: '.aac', outputFormat: 'aac_adts', audioEncoder: 'aac', audioSource: 'voice_recognition' },
    });
  });

  it('takes audioSource/sampleRate/bitRate from the server config, ignoring junk', () => {
    const p = presetFromConfig({ sampleRate: 22050, bitRate: 64000, audioSource: 'camcorder' });
    expect(p.android).toMatchObject({ audioSource: 'camcorder', sampleRate: 22050, outputFormat: 'aac_adts' });
    expect(p.bitRate).toBe(64000);
    const junk = presetFromConfig({ sampleRate: 5, bitRate: Number.NaN, audioSource: 'hack' });
    expect(junk.sampleRate).toBe(16000);
    expect(junk.bitRate).toBe(48000);
    expect(junk.android.audioSource).toBe('voice_recognition');
    expect(presetFromConfig(null, 'mic').android.audioSource).toBe('mic');
  });

  it('caps the file natively just under the server limit (works with the screen off; pauses do not count)', () => {
    // 48 kbps + 7 bayt ADTS sarlavhasi * 15.625 kadr/s = 6109.375 bayt/s
    expect(adtsBytesPerSec(48000, 16000)).toBeCloseTo(6109.375, 3);
    const cap = maxFileSizeFor(180 * 60, 48000, 16000);
    expect(cap).toBe(Math.floor(6109.375 * (180 * 60 - NATIVE_LIMIT_MARGIN_SEC)));
    // Fayl shu hajmda to'xtaganda davomiylik server chegarasidan (maxMinutes*60+30) kichik.
    expect(cap / adtsBytesPerSec(48000, 16000)).toBeLessThan(180 * 60 + 30);
    expect(Number.isInteger(cap)).toBe(true);
    expect(presetFromConfig(null, null, 180 * 60).android.maxFileSize).toBe(cap);
    expect(presetFromConfig({ bitRate: 64000, sampleRate: 22050 }, null, 3600).android.maxFileSize).toBe(maxFileSizeFor(3600, 64000, 22050));
    expect(presetFromConfig(null).android.maxFileSize).toBeUndefined();
    expect(maxFileSizeFor(1e9, 256000, 48000)).toBe(2_147_483_647); // Kotlin Int
  });
});

describe('native recorder events (expo-audio 57 Android)', () => {
  it('tells the size-limit stop, a recorder error and the notification Stop apart', () => {
    const url = 'file:///doc/Audio/recording-1.aac';
    expect(classifyNativeEvent({ isFinished: true, hasError: true, error: null, url }, 'recording')).toBe('limit');
    expect(classifyNativeEvent({ isFinished: true, hasError: true, error: null, url }, 'paused')).toBe('limit');
    expect(classifyNativeEvent({ isFinished: true, hasError: true, error: 'The media server has crashed', url: null }, 'recording')).toBe('error');
    expect(classifyNativeEvent({ isFinished: true, hasError: true, error: null, url: null }, 'recording')).toBe('error');
    expect(classifyNativeEvent({ isFinished: true, hasError: false, url }, 'recording')).toBe('finished');
    // O'zimiz chaqirgan stop() aks-sadosi va yozuvsiz holat - e'tiborsiz.
    expect(classifyNativeEvent({ isFinished: true, hasError: false, url }, 'stopping')).toBe('ignore');
    expect(classifyNativeEvent({ isFinished: true, hasError: true, error: 'x' }, 'idle')).toBe('ignore');
    expect(classifyNativeEvent({ isFinished: false }, 'recording')).toBe('ignore');
  });
});
