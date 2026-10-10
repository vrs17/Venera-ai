/**
 * Native adapterlar (expo-audio soxtasi bilan): yarim tayyor qolgan yozuvchi bo'shatiladi,
 * `record()` yiqilsa ham "Qayta urinish" ishlaydi; pleer native tomonda o'zi qayta yoqilsa
 * darhol pauza qilinadi; `stop()` pleerni yo'q qiladi; pleer xatosi ham "tugadi"; pozitsiya
 * holat yangilanishidan (UI oqimini bloklamasdan). Aks-sado va "to'xta" tekshiruvi.
 */
import type { AudioPlayer, AudioStatus } from 'expo-audio';

import { isEchoOf, isStopCommand } from '@/features/voice/echo';
import { createClipPlayer, createMicPort, type RecorderLike } from '@/features/voice/native';

/** Android AudioRecorder.kt kabi: tayyor turganda yana prepare - AlreadyPrepared. */
function nativeLikeRecorder() {
  const st = { prepared: false, recording: false, failRecord: false };
  const rec = {
    uri: 'file:///cache/Audio/recording-1.aac',
    prepareToRecordAsync: jest.fn(async () => {
      if (st.prepared || st.recording) throw new Error('AudioRecorderAlreadyPreparedException');
      st.prepared = true;
    }),
    record: jest.fn(() => {
      if (st.failRecord) throw new Error('start failed');
      st.recording = true;
    }),
    stop: jest.fn(async () => {
      st.prepared = false;
      st.recording = false;
    }),
    getStatus: jest.fn(() => ({ canRecord: st.prepared, isRecording: st.recording, durationMillis: 0, mediaServicesDidReset: false, metering: -40, url: null })),
  };
  return { rec: rec as unknown as RecorderLike & typeof rec, st };
}

describe('createMicPort', () => {
  it('record() failing releases the prepared recorder, so Retry can succeed', async () => {
    const { rec, st } = nativeLikeRecorder();
    const mic = createMicPort(rec);
    st.failRecord = true;
    await expect(mic.start()).rejects.toThrow('start failed');
    expect(mic.recording).toBe(false);
    expect(st.prepared).toBe(false);
    st.failRecord = false;
    await mic.start();
    expect(mic.recording).toBe(true);
  });

  it('a recorder left half-prepared by someone else is released before prepare', async () => {
    const { rec, st } = nativeLikeRecorder();
    st.prepared = true;
    const mic = createMicPort(rec);
    await mic.start();
    expect(rec.stop).toHaveBeenCalledTimes(1);
    expect(mic.recording).toBe(true);
  });
});

type Listener = (s: AudioStatus) => void;

function fakePlayers() {
  const made: { player: AudioPlayer & Record<string, jest.Mock>; emit: (s: Partial<AudioStatus>) => void }[] = [];
  const factory = () => {
    let listener: Listener | null = null;
    const player = {
      replace: jest.fn(),
      play: jest.fn(),
      pause: jest.fn(),
      remove: jest.fn(),
      addListener: jest.fn((_e: string, l: Listener) => {
        listener = l;
        return { remove: jest.fn() };
      }),
    } as unknown as AudioPlayer & Record<string, jest.Mock>;
    made.push({ player, emit: (s) => listener?.(s as AudioStatus) });
    return player;
  };
  return { made, factory };
}

describe('createClipPlayer', () => {
  let now = 1_000_000;
  beforeEach(() => {
    now = 1_000_000;
    jest.spyOn(Date, 'now').mockImplementation(() => now);
  });
  afterEach(() => jest.restoreAllMocks());

  it('a natural end and a player error both report "ended" (the queue never hangs)', () => {
    const { made, factory } = fakePlayers();
    const p = createClipPlayer(factory);
    const ended = jest.fn();
    p.onEnd(ended);
    p.play('file:///a.wav');
    now += 1000;
    made[0].emit({ didJustFinish: true, playing: false });
    expect(ended).toHaveBeenCalledTimes(1);
    p.play('file:///b.wav');
    now += 1000;
    made[0].emit({ playing: false, ...({ error: 'Source error' } as object) });
    expect(ended).toHaveBeenCalledTimes(2);
  });

  it('if the native side resumes a paused clip by itself, it is paused again at once', () => {
    const { made, factory } = fakePlayers();
    const p = createClipPlayer(factory);
    p.play('file:///a.wav');
    p.pause();
    const pause = made[0].player.pause as unknown as jest.Mock;
    pause.mockClear();
    made[0].emit({ playing: true });
    expect(pause).toHaveBeenCalledTimes(1);
  });

  it('stop() destroys the native player (nothing left to auto-resume); the next play makes a new one', () => {
    const { made, factory } = fakePlayers();
    const p = createClipPlayer(factory);
    const ended = jest.fn();
    p.onEnd(ended);
    p.play('file:///a.wav');
    p.stop();
    expect(made[0].player.remove).toHaveBeenCalled();
    // Eski pleyerning kechikkan hodisasi hech narsa qilmaydi
    now += 1000;
    made[0].emit({ didJustFinish: true });
    expect(ended).not.toHaveBeenCalled();
    p.play('file:///b.wav');
    expect(made).toHaveLength(2);
    expect(made[1].player.replace).toHaveBeenCalledWith({ uri: 'file:///b.wav' });
  });

  it('position comes from status updates + wall clock (no blocking currentTime reads)', () => {
    const { made, factory } = fakePlayers();
    const p = createClipPlayer(factory);
    p.play('file:///a.wav');
    made[0].emit({ playing: true, currentTime: 0.5 });
    now += 80;
    expect(p.positionMs()).toBe(580);
    p.pause();
    expect(p.positionMs()).toBe(500);
  });

  it('a late "finished" right after replace is ignored', () => {
    const { made, factory } = fakePlayers();
    const p = createClipPlayer(factory);
    const ended = jest.fn();
    p.onEnd(ended);
    p.play('file:///a.wav');
    now += 50;
    made[0].emit({ didJustFinish: true });
    expect(ended).not.toHaveBeenCalled();
  });
});

describe('echo and stop-command checks', () => {
  it('a transcript of what Barno is saying is echo; a real question is not', () => {
    const spoken = ['Bugun uch kishi kechikdi.', "Ali, Vali va Sardor o'z vaqtida kelmadi."];
    expect(isEchoOf('bugun uch kishi kechikdi', spoken)).toBe(true);
    expect(isEchoOf("Ali Vali va Sardor o‘z vaqtida", spoken)).toBe(true);
    // O'zbekcha qo'shimcha: "kechikdilar" ~ "kechikdi"
    expect(isEchoOf('uch kishi kechikdilar', spoken)).toBe(true);
    expect(isEchoOf('Ertaga kim navbatchi?', spoken)).toBe(false);
    expect(isEchoOf('Bugun', [])).toBe(false);
  });

  it('short stop phrases are commands, longer sentences are questions', () => {
    for (const t of ["To'xta.", 'Bas!', 'Barno, to‘xtang', 'Стоп', 'stop please', "bo'ldi rahmat"]) expect(isStopCommand(t)).toBe(true);
    for (const t of ["To'xta, ertaga kim keladi?", 'Rahmat', 'Bugun kim kechikdi?', '']) expect(isStopCommand(t)).toBe(false);
  });
});
