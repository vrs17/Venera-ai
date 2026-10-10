/**
 * VAD (metering, 60 ms kadr): jim xona - hodisa yo'q; gap + 1 s jimlik -> speech_end;
 * qisqa "chirt" -> discard; 60 s -> max_reached; shovqin sathi moslashadi; hysteresis.
 * Bo'lib gapirish: faqat aks-sado hech qachon ishga tushmaydi; gapirishda 300 ms, o'ylashda
 * 600 ms; klip boshidagi 250 ms; ikki marta yolg'on bo'lishdan keyin chegara +6 dB.
 */
import { FRAME_MS } from '@/features/voice/limits';
import { createVad, type Vad, type VadContext, type VadEvent } from '@/features/voice/vad';

const LISTEN: VadContext = { mode: 'listen', outDbMax: null, clipAgeMs: 0, earpiece: false, guard: false };

function feed(vad: Vad, from: number, to: number, db: (t: number) => number, ctx: Partial<VadContext> = {}): { t: number; e: VadEvent }[] {
  const out: { t: number; e: VadEvent }[] = [];
  for (let t = from; t < to; t += FRAME_MS) {
    const e = vad.push({ tMs: t, db: db(t) }, { ...LISTEN, ...ctx });
    if (e) out.push({ t, e });
  }
  return out;
}

/** Jim xonada sathni o'rgatish (floor -55 -> START -40). */
function quietVad(): Vad {
  const vad = createVad();
  feed(vad, 0, 3000, () => -55);
  return vad;
}

describe('VAD - listening', () => {
  it('a quiet room at -55 gives no events and START settles at -40', () => {
    const vad = createVad();
    expect(feed(vad, 0, 5000, () => -55)).toEqual([]);
    expect(vad.startDb).toBe(-40);
  });

  it('600 ms of speech then 1 s of silence -> speech_start and speech_end from the onset', () => {
    const vad = quietVad();
    const ev = feed(vad, 3000, 6000, (t) => (t >= 3600 && t < 4200 ? -20 : -55));
    expect(ev.map((x) => x.e.type)).toEqual(['speech_start', 'speech_end']);
    expect(ev[0].e).toEqual({ type: 'speech_start', atMs: 3600 });
    const end = ev[1].e as Extract<VadEvent, { type: 'speech_end' }>;
    expect(end.fromMs).toBe(3600);
    expect(end.toMs).toBe(4140);
    expect(end.voicedMs).toBe(600);
    // ~1 s jimlikdan keyin
    expect(ev[1].t - end.toMs).toBeGreaterThanOrEqual(1000);
    expect(ev[1].t - end.toMs).toBeLessThan(1000 + FRAME_MS);
  });

  it('a 240 ms blip is discarded (never uploaded)', () => {
    const vad = quietVad();
    const ev = feed(vad, 3000, 5000, (t) => (t >= 3600 && t < 3840 ? -20 : -55));
    expect(ev.map((x) => x.e.type)).toEqual(['speech_start', 'speech_discard']);
  });

  it('61 s of continuous speech -> max_reached', () => {
    const vad = quietVad();
    const ev = feed(vad, 3000, 3000 + 61_000, () => -20);
    // Odam gapirishda davom etsa keyingi gap yangi boshlanish bilan davom etadi
    expect(ev.map((x) => x.e.type).slice(0, 2)).toEqual(['speech_start', 'max_reached']);
    const max = ev[1].e as Extract<VadEvent, { type: 'max_reached' }>;
    expect(max.toMs - max.fromMs).toBeGreaterThanOrEqual(60_000);
  });

  it('the floor adapts to a -38 room (START becomes -24) and that room never triggers', () => {
    const vad = createVad();
    expect(feed(vad, 0, 10_000, () => -38)).toEqual([]);
    expect(vad.floorDb).toBeGreaterThan(-39.5);
    expect(vad.startDb).toBeCloseTo(-24, 1);
    // Odatiy gap (-15) baribir eshitiladi
    expect(feed(vad, 10_000, 10_400, () => -15).map((x) => x.e.type)).toEqual(['speech_start']);
  });

  it('hysteresis holds the utterance through -35 dips', () => {
    const vad = quietVad();
    const ev = feed(vad, 3000, 7000, (t) => {
      if (t < 3600 || t >= 5600) return -55;
      return Math.floor(t / FRAME_MS) % 2 ? -35 : -20;
    });
    expect(ev.map((x) => x.e.type)).toEqual(['speech_start', 'speech_end']);
  });

  it('first-read -160 frames count as silence and do not teach the floor', () => {
    const vad = createVad();
    feed(vad, 0, 2000, () => -160);
    expect(vad.floorDb).toBe(-50);
  });

  it("'off' drops a half-heard utterance; reset() keeps the learned floor", () => {
    const vad = quietVad();
    feed(vad, 3000, 3300, () => -20);
    expect(vad.inSpeech).toBe(true);
    vad.push({ tMs: 3300, db: -20 }, { ...LISTEN, mode: 'off' });
    expect(vad.inSpeech).toBe(false);
    vad.reset();
    expect(vad.startDb).toBe(-40);
  });
});

describe('VAD - barge-in (echo gate)', () => {
  const OUT = -15;
  const speaking = (extra: Partial<VadContext> = {}): Partial<VadContext> => ({ mode: 'speaking', outDbMax: OUT, clipAgeMs: 1000, ...extra });

  it('an echo-only mic (mic = output + coupling) never triggers', () => {
    const vad = quietVad();
    expect(feed(vad, 3000, 13_000, () => OUT - 6, speaking())).toEqual([]);
    // Karnay baland, AEC zaif: aks-sado chiqishdan +2 dB - o'rganilgan bog'lanish ham ushlaydi
    const loud = quietVad();
    expect(feed(loud, 3000, 13_000, () => OUT + 2, speaking())).toEqual([]);
  });

  it('a user 15 dB above the echo for 360 ms triggers while speaking (5 of 6 frames)', () => {
    const vad = quietVad();
    feed(vad, 3000, 4000, () => OUT - 6, speaking());
    const ev = feed(vad, 4000, 4360, () => OUT - 6 + 15, speaking());
    expect(ev).toHaveLength(1);
    expect(ev[0].e).toEqual({ type: 'barge_in', atMs: 4000 });
    expect(ev[0].t).toBe(4000 + 4 * FRAME_MS);
    expect(vad.inSpeech).toBe(true);
  });

  it('while thinking it needs 600 ms (10 of 12 frames)', () => {
    const vad = quietVad();
    const thinking: Partial<VadContext> = { mode: 'thinking', outDbMax: null };
    expect(feed(vad, 3000, 3360, () => -20, thinking)).toEqual([]);
    const ev = feed(vad, 3360, 3800, () => -20, thinking);
    expect(ev.map((x) => x.e.type)).toEqual(['barge_in']);
    expect((ev[0].e as { atMs: number }).atMs).toBe(3000);
  });

  it('no barge-in during the first 250 ms of a clip', () => {
    const vad = quietVad();
    expect(feed(vad, 3000, 3240, () => -5, speaking({ clipAgeMs: 100 }))).toEqual([]);
  });

  it('after barge_in the utterance continues in listen mode and ends normally', () => {
    const vad = quietVad();
    const barge = feed(vad, 3000, 3360, () => -5, speaking());
    expect(barge.map((x) => x.e.type)).toEqual(['barge_in']);
    // Sessiya keyingi kadrda tinglashga o'tadi - odam yana 600 ms gapiradi, keyin jimlik
    const ev = feed(vad, 3360, 5500, (t) => (t < 3960 ? -20 : -55));
    expect(ev.map((x) => x.e.type)).toEqual(['speech_end']);
    expect((ev[0].e as { fromMs: number }).fromMs).toBe(3000);
  });

  it('two discarded barge-ins raise the margin by 6 dB (self-interrupt fallback)', () => {
    const vad = quietVad();
    const nearThreshold = OUT - 6 + 10 + 3; // chegaradan 3 dB baland
    expect(feed(vad, 3000, 3400, () => nearThreshold, speaking()).map((x) => x.e.type)).toEqual(['barge_in']);
    vad.reset();
    vad.noteDiscardAfterBarge();
    expect(vad.bargeExtraDb).toBe(0);
    vad.noteDiscardAfterBarge();
    expect(vad.bargeExtraDb).toBe(6);
    expect(feed(vad, 4000, 5000, () => nearThreshold, speaking())).toEqual([]);
    vad.noteDiscardAfterBarge();
    vad.noteDiscardAfterBarge();
    vad.noteDiscardAfterBarge();
    vad.noteDiscardAfterBarge();
    expect(vad.bargeExtraDb).toBe(12);
  });

  it('earpiece mode uses a lower floor so a quieter voice can interrupt', () => {
    const vad = quietVad();
    const ear = speaking({ earpiece: true, outDbMax: -40 });
    // Quloq: bog'lanish -20, pastki chegara -38: -40-20+10 = -50 -> -38
    expect(feed(vad, 3000, 3400, () => -34, ear).map((x) => x.e.type)).toEqual(['barge_in']);
  });
});

describe('VAD - echo calibration (loud speaker echo, peak metering)', () => {
  /** Barno klipi: o'zgaruvchan chiqish cho'qqisi va mikrofonda aks-sado (+E dB, o'z tebranishi bilan). */
  function playClips(vad: Vad, from: number, clips: number, echoOverOut: number, mode: 'speaking' | 'thinking_hold' = 'speaking', clipMs = 3000) {
    const events: { t: number; e: VadEvent }[] = [];
    for (let c = 0; c < clips; c++) {
      const start = from + c * clipMs;
      for (let t = start; t < start + clipMs; t += FRAME_MS) {
        const out = -14 + 3 * Math.sin(t / 170);
        const mic = out + echoOverOut + 3 * Math.sin(t / 53);
        const e = vad.push({ tMs: t, db: mic }, { mode, outDbMax: out, clipAgeMs: t - start, earpiece: false, guard: false });
        if (e) events.push({ t, e });
      }
    }
    return events;
  }

  it.each([8, 10, 12])('echo %i dB above the output never interrupts an answer clip', (echo) => {
    const vad = quietVad();
    expect(playClips(vad, 3000, 8, echo)).toEqual([]);
    expect(vad.couplingDb as number).toBeGreaterThan(echo - 3);
  });

  it.each([8, 12])('echo %i dB above a HOLD clip never cancels the wait (thinking_hold)', (echo) => {
    const vad = quietVad();
    expect(playClips(vad, 3000, 4, echo, 'thinking_hold', 2800)).toEqual([]);
  });

  it('after calibration a real user (15 dB above the echo) still interrupts', () => {
    const vad = quietVad();
    expect(playClips(vad, 3000, 4, -6)).toEqual([]);
    const start = 15_000;
    let hit: VadEvent | null = null;
    for (let t = start; t < start + 3000 && !hit; t += FRAME_MS) {
      const out = -14 + 3 * Math.sin(t / 170);
      const user = t >= start + 1200 ? out - 6 + 15 + 3 : out - 6;
      hit = vad.push({ tMs: t, db: user }, { mode: 'speaking', outDbMax: out, clipAgeMs: t - start, earpiece: false, guard: false });
    }
    expect(hit?.type).toBe('barge_in');
  });

  it('a user talking during the very first clip start is not counted as a barge (calibration window)', () => {
    const vad = quietVad();
    const ev = feed(vad, 3000, 3600, () => -5, { mode: 'speaking', outDbMax: -14, clipAgeMs: 0 }).length;
    expect(ev).toBe(0);
  });
});

describe('VAD - noisy office: the owner\'s voice level gates colleagues out', () => {
  it('speech_end carries the utterance level (median of voiced frames)', () => {
    const vad = quietVad();
    const ev = feed(vad, 3000, 6000, (t) => (t >= 3600 && t < 4500 ? -12 : -55));
    const end = ev.find((x) => x.e.type === 'speech_end')?.e as Extract<VadEvent, { type: 'speech_end' }>;
    expect(end.levelDb).toBe(-12);
  });

  it('in a noisy room, speech 12+ dB below the learned owner level does not start an utterance', () => {
    const vad = createVad();
    feed(vad, 0, 10_000, () => -36);
    expect(vad.startDb).toBeCloseTo(-22, 0);
    vad.noteUserLevel(-6);
    expect(vad.startDb).toBe(-20);
    // Hamkasb -21 dB - endi gap emas
    expect(feed(vad, 10_000, 12_000, () => -21)).toEqual([]);
    // Egasi -8 dB - eshitiladi
    expect(feed(vad, 12_000, 12_400, () => -8).map((x) => x.e.type)).toEqual(['speech_start']);
  });

  it('opening the screen in a loud office does not turn the room noise into a 60 s "question"', () => {
    const vad = createVad();
    const babble = (t: number) => -34 + 3 * Math.sin(t / 90);
    expect(feed(vad, 0, 65_000, babble)).toEqual([]);
    // Doimiy shovqin ichida ham (sath gap paytida ham ko'tariladi) - "gap" cheksiz cho'zilmaydi.
    const v2 = quietVad();
    const ev = feed(v2, 3000, 70_000, babble).map((x) => x.e.type);
    expect(ev).not.toContain('max_reached');
  });

  it('a long, fluent question in a quiet room is not cut in the middle', () => {
    const vad = quietVad();
    const talk = (t: number) => (t >= 3600 && t < 13_600 ? (Math.floor(t / FRAME_MS) % 6 === 0 ? -42 : -18) : -55);
    const ev = feed(vad, 3000, 16_000, talk).map((x) => x.e.type);
    expect(ev).toEqual(['speech_start', 'speech_end']);
  });

  it('in a quiet room the gate is off (a softer voice is still heard)', () => {
    const vad = quietVad();
    vad.noteUserLevel(-6);
    expect(vad.startDb).toBe(-40);
  });

  it('the floor and the start threshold can rise higher than before in a loud room', () => {
    const vad = createVad();
    feed(vad, 0, 20_000, () => -28);
    expect(vad.startDb).toBe(-18);
  });
});
