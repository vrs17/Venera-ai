/**
 * Barno ovozi (speaker): bir vaqtda bitta sintez so'rovi, ko'pi bilan 2 tayyor bo'lak;
 * kutish klipi kesilmaydi (javob sintez qilinadi, lekin klip tugagach yangraydi);
 * 503 - qayta urinish, keyin "busy"; 501 - "off" (ilova davomida); stop() so'rovni uzadi
 * va fayllarni o'chiradi; output() klip egri chizig'iga ergashadi.
 */
import { ApiError } from '@/api/client';
import { createSentenceQueue } from '@/features/voice/chunker';
import { __resetTtsOff, createSpeaker, ttsOffThisRun, type Speaker, type SpeakerEvent } from '@/features/voice/speaker';

import { FakeClock, FakeFiles, FakePlayer, FakeVoiceApi, flush, makeWav } from './fixtures/voiceFakes';

const LONG = (n: number) => `${n}-gap: bo'limdagi xodimlar ro'yxati bo'yicha ${'batafsil ma\'lumot '.repeat(8)}va boshqa tafsilotlar, shuningdek ${'qo\'shimcha izohlar '.repeat(3)}keltirilgan.`;

function setup() {
  const clock = new FakeClock();
  const files = new FakeFiles();
  const player = new FakePlayer(clock);
  const api = new FakeVoiceApi();
  const speaker: Speaker = createSpeaker({ api, files, player, clock, settings: () => ({ voice: 'uz_female_calm', speed: 0.95 }) });
  const events: SpeakerEvent[] = [];
  speaker.subscribe((e) => events.push(e));
  const pending = () => api.calls.filter((c) => !(c as { done?: boolean }).done && !c.opts.signal?.aborted).length;
  return { clock, files, player, api, speaker, events, pending };
}

function queueOf(text: string, done = true) {
  const q = createSentenceQueue();
  q.push(text, done);
  return q;
}

afterEach(() => __resetTtsOff());

describe('speaker - answer pipeline', () => {
  it('never has more than one clip request in flight and buffers at most two', async () => {
    const { api, speaker, player, events, pending, files } = setup();
    speaker.speak('k1', queueOf([LONG(1), LONG(2), LONG(3), LONG(4)].join(' ')), 'a'.repeat(32));
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0].text.length).toBeLessThanOrEqual(160);
    expect(api.calls[0].opts).toMatchObject({ voice: 'uz_female_calm', speed: 0.95, turnId: 'a'.repeat(32) });
    await flush();
    expect(api.calls).toHaveLength(1);

    api.ok(0);
    await flush();
    expect(player.plays).toHaveLength(1);
    expect(events.map((e) => e.type)).toEqual(['speech_start', 'chunk']);
    expect(api.calls).toHaveLength(2);
    expect(pending()).toBe(1);

    api.ok(1);
    await flush();
    expect(api.calls).toHaveLength(3);
    expect(pending()).toBe(1);
    api.ok(2);
    await flush();
    // 1 yangrayapti, 2 tayyor - yangi so'rov yo'q
    expect(api.calls).toHaveLength(3);
    expect(pending()).toBe(0);

    player.finish();
    await flush();
    expect(player.plays).toHaveLength(2);
    // Bittasi o'ynaldi -> bufer bo'shadi -> keyingi so'rov
    expect(api.calls).toHaveLength(4);
    for (let i = 0; i < 30 && !events.some((e) => e.type === 'speech_end'); i++) {
      const open = api.calls.findIndex((c) => !(c as { done?: boolean }).done);
      if (open >= 0) api.ok(open);
      else player.finish();
      await flush();
      expect(pending()).toBeLessThanOrEqual(1);
    }
    const end = events[events.length - 1];
    expect(end).toEqual({ type: 'speech_end', key: 'k1', shortened: false, played: api.calls.length });
    expect(api.calls.length).toBeGreaterThanOrEqual(4);
    // O'ynalgan bo'laklar o'chirilgan
    expect([...files.store.keys()].filter((k) => k.includes('/voice/'))).toEqual([]);
  });

  it('waits for more streamed text instead of speaking half a sentence', async () => {
    const { api, speaker, events } = setup();
    const q = createSentenceQueue();
    q.push('Bugun uch', false);
    speaker.speak('k1', q, null);
    expect(api.calls).toHaveLength(0);
    q.push('Bugun uch kishi kechikdi. Ular', false);
    speaker.pump();
    expect(api.calls.map((c) => c.text)).toEqual(['Bugun uch kishi kechikdi.']);
    api.ok(0);
    await flush();
    expect(events.map((e) => e.type)).toEqual(['speech_start', 'chunk']);
  });

  it('an answer with nothing speakable ends at once with played = 0', () => {
    const { api, speaker, events } = setup();
    speaker.speak('k1', queueOf('```\nx\n```'), null);
    expect(api.calls).toHaveLength(0);
    expect(events).toEqual([{ type: 'speech_end', key: 'k1', shortened: false, played: 0 }]);
  });
});

describe('speaker - hold clips', () => {
  it('the answer is synthesized during a hold clip but plays only after it ends', async () => {
    const { api, speaker, player, events, files } = setup();
    speaker.hold({ text: 'Bir daqiqa', clip: 'kutish-1' });
    await flush();
    expect(api.hold).toHaveBeenCalledWith('kutish-1', 'uz_female_calm', expect.anything());
    expect(player.plays).toEqual(['file:///cache/voice-hold/uz_female_calm/kutish-1.wav']);
    expect(events).toEqual([{ type: 'hold_start', text: 'Bir daqiqa' }]);
    expect(speaker.output().source).toBe('hold');

    // Ikkinchi klip shu paytda kelsa - tashlanadi
    speaker.hold({ text: 'Yana', clip: 'kutish-2' });
    await flush();
    expect(api.hold).toHaveBeenCalledTimes(1);

    speaker.speak('k1', queueOf('Bugun uch kishi kechikdi.'), null);
    expect(api.calls).toHaveLength(1);
    api.ok(0);
    await flush();
    expect(player.plays).toHaveLength(1);

    player.finish();
    await flush();
    expect(events.map((e) => e.type)).toEqual(['hold_start', 'hold_end', 'speech_start', 'chunk']);
    expect(player.plays).toHaveLength(2);
    // Klip keshda qoladi (o'chirilmaydi)
    expect(files.store.has('file:///cache/voice-hold/uz_female_calm/kutish-1.wav')).toBe(true);
  });

  it('a cached clip is played from disk; a missing clip or a stale turn stays silent', async () => {
    const { api, speaker, player, files } = setup();
    files.write('voice-hold', 'uz_female_calm/kutish-9.wav', makeWav(500));
    speaker.hold({ text: 'Keshdan', clip: 'kutish-9' });
    await flush();
    expect(api.hold).not.toHaveBeenCalled();
    expect(player.plays).toHaveLength(1);
    player.finish();

    api.holdBytes = null;
    speaker.hold({ text: 'Yo\'q', clip: 'kutish-404' });
    await flush();
    expect(player.plays).toHaveLength(1);

    api.holdBytes = makeWav(300);
    speaker.hold({ text: 'Kech', clip: 'kutish-3' }, () => false);
    await flush();
    expect(player.plays).toHaveLength(1);
  });

  it('no hold clip after the answer started speaking', async () => {
    const { api, speaker } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0);
    await flush();
    speaker.hold({ text: 'Kech', clip: 'kutish-1' });
    await flush();
    expect(api.hold).not.toHaveBeenCalled();
  });

  it('stopHold cuts the clip (tap) and lets a ready answer play', async () => {
    const { api, speaker, player, events } = setup();
    speaker.hold({ text: 'Bir daqiqa', clip: 'kutish-1' });
    await flush();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0);
    await flush();
    speaker.stopHold();
    await flush();
    expect(events.map((e) => e.type)).toEqual(['hold_start', 'hold_end', 'speech_start', 'chunk']);
    expect(player.stops).toBe(1);
  });
});

describe('speaker - errors and stop', () => {
  it('503 is retried after 400 and 1200 ms, then reported as busy', async () => {
    const { api, speaker, clock, events } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.fail(0, 503);
    await flush();
    expect(api.calls).toHaveLength(1);
    await clock.advance(399);
    expect(api.calls).toHaveLength(1);
    await clock.advance(1);
    expect(api.calls).toHaveLength(2);
    api.fail(1, 503);
    await flush();
    await clock.advance(1200);
    expect(api.calls).toHaveLength(3);
    api.fail(2, 503);
    await flush();
    expect(events).toEqual([
      { type: 'error', key: 'k1', code: 'busy' },
      { type: 'speech_end', key: 'k1', shortened: false, played: 0 },
    ]);
  });

  it('a failure after the first chunk still plays the buffered audio to the end', async () => {
    const { api, speaker, player, events } = setup();
    speaker.speak('k1', queueOf([LONG(1), LONG(2)].join(' ')), null);
    api.ok(0);
    await flush();
    api.fail(1, 500);
    await flush();
    expect(events.map((e) => e.type)).toEqual(['speech_start', 'chunk', 'error']);
    expect((events[2] as { code: string }).code).toBe('failed');
    player.finish();
    await flush();
    expect(events[events.length - 1]).toEqual({ type: 'speech_end', key: 'k1', shortened: false, played: 1 });
  });

  it('501 means speech is off for the whole app run', async () => {
    const { api, speaker, events } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.fail(0, 501);
    await flush();
    expect(events[0]).toEqual({ type: 'error', key: 'k1', code: 'off' });
    expect(ttsOffThisRun()).toBe(true);
    events.length = 0;
    speaker.speak('k2', queueOf('Yana javob.'), null);
    expect(api.calls).toHaveLength(1);
    expect(events.map((e) => e.type)).toEqual(['error', 'speech_end']);
    speaker.hold({ text: 'x', clip: 'kutish-1' });
    await flush();
    expect(api.hold).not.toHaveBeenCalled();
  });

  it('stop() aborts the request in flight, stops the player and deletes buffered files', async () => {
    const { api, speaker, player, events, files } = setup();
    speaker.speak('k1', queueOf([LONG(1), LONG(2), LONG(3)].join(' ')), null);
    api.ok(0);
    await flush();
    const playingUri = player.current as string;
    expect(api.calls).toHaveLength(2);
    speaker.stop();
    expect(api.calls[1].opts.signal?.aborted).toBe(true);
    expect(player.stops).toBe(1);
    expect(files.removed).toContain(playingUri);
    expect(speaker.output().source).toBeNull();
    const before = events.length;
    api.ok(1);
    await flush();
    player.finish();
    await flush();
    expect(events).toHaveLength(before);
  });

  it('pause/resume pause the player; nothing is reported as playing while paused', async () => {
    const { api, speaker, player } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0);
    await flush();
    speaker.pause();
    expect(player.paused).toBe(true);
    expect(speaker.output().source).toBeNull();
    speaker.resume();
    expect(player.paused).toBe(false);
    expect(speaker.output().source).toBe('answer');
  });
});

describe('speaker - output()', () => {
  it('follows the clip envelope at the player position', async () => {
    const { api, speaker, clock } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0, makeWav(2000, 8000));
    await flush();
    await clock.advance(500);
    const out = speaker.output();
    expect(out.source).toBe('answer');
    expect(out.clipAgeMs).toBe(500);
    expect(out.db as number).toBeGreaterThan(-16.5);
    expect(out.level).toBeGreaterThan(0.5);
  });

  it('a silent clip reports silence', async () => {
    const { api, speaker, clock } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0, makeWav(2000, 0));
    await flush();
    await clock.advance(400);
    const out = speaker.output();
    expect(out.level).toBe(0);
    expect(out.db as number).toBeLessThan(-90);
  });
});

describe('speaker - review fixes', () => {
  it('a hold clip that arrives after the answer was queued is dropped (the answer never waits for it)', async () => {
    const { api, speaker, player, events } = setup();
    type Hold = { bytes: Uint8Array; sampleRate: number; durationMs: null; truncated: boolean };
    const gate: { release: (v: Hold) => void } = { release: () => {} };
    api.hold.mockImplementationOnce(
      () =>
        new Promise<Hold>((r) => {
          gate.release = r;
        }),
    );
    speaker.hold({ text: 'Bir daqiqa', clip: 'kutish-7' });
    await flush();
    speaker.speak('k1', queueOf('Javob tayyor.'), null);
    gate.release({ bytes: makeWav(2500, 6000), sampleRate: 8000, durationMs: null, truncated: false });
    await flush();
    expect(player.plays).toHaveLength(0);
    api.ok(0);
    await flush();
    expect(player.plays).toHaveLength(1);
    expect(events.map((e) => e.type)).toEqual(['speech_start', 'chunk']);
  });

  it('a player that never reports the end does not hang the queue (watchdog = duration + 1.5 s)', async () => {
    const { api, speaker, player, clock, events } = setup();
    speaker.speak('k1', queueOf('Birinchi gap. Ikkinchi gap.'), null);
    api.ok(0, makeWav(1000));
    await flush();
    api.ok(1, makeWav(1000));
    await flush();
    expect(player.plays).toHaveLength(1);
    await clock.advance(2400);
    expect(player.plays).toHaveLength(1);
    await clock.advance(200);
    expect(player.plays).toHaveLength(2);
    await clock.advance(2600);
    expect(events[events.length - 1]).toMatchObject({ type: 'speech_end', played: 2 });
  });

  it('pause stops the watchdog; resume re-arms it with the time that was left', async () => {
    const { api, speaker, player, clock, events } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0, makeWav(1000));
    await flush();
    await clock.advance(1000);
    speaker.pause();
    await clock.advance(10_000);
    expect(events.map((e) => e.type)).not.toContain('speech_end');
    speaker.resume();
    await clock.advance(1600);
    expect(events[events.length - 1].type).toBe('speech_end');
    expect(player.paused).toBe(false);
  });

  it('400/422 on one chunk skips only that chunk; the rest is still read', async () => {
    const { api, speaker, player, events } = setup();
    speaker.speak('k1', queueOf([LONG(1), LONG(2), LONG(3)].join(' ')), null);
    api.ok(0);
    await flush();
    api.fail(1, 422);
    await flush();
    expect(events.map((e) => e.type)).not.toContain('error');
    expect(api.calls).toHaveLength(3);
    api.ok(2);
    await flush();
    player.finish();
    await flush();
    expect(player.plays).toHaveLength(2);
  });

  it('503 while audio is still playing keeps retrying (2 s, 4 s) instead of dropping the rest', async () => {
    const { api, speaker, clock, events } = setup();
    speaker.speak('k1', queueOf([LONG(1), LONG(2)].join(' ')), null);
    api.ok(0, makeWav(20_000));
    await flush();
    api.fail(1, 503);
    await flush();
    await clock.advance(400);
    api.fail(2, 503);
    await flush();
    await clock.advance(1200);
    api.fail(3, 503);
    await flush();
    await clock.advance(2000);
    expect(api.calls).toHaveLength(5);
    api.fail(4, 503);
    await flush();
    await clock.advance(4000);
    expect(api.calls).toHaveLength(6);
    api.ok(5);
    await flush();
    expect(events.map((e) => e.type)).not.toContain('error');
  });

  it('a network blip is retried like 503', async () => {
    const { api, speaker, clock } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.calls[0].reject(new ApiError(0, 'network', 'x'));
    (api.calls[0] as { done?: boolean }).done = true;
    await flush();
    await clock.advance(400);
    expect(api.calls).toHaveLength(2);
  });

  it('progress() reports what was fully spoken; recentText() what is playing and was just played', async () => {
    const { api, speaker, player } = setup();
    speaker.speak('k1', queueOf('Birinchi gap. Ikkinchi gap.'), null);
    api.ok(0);
    await flush();
    expect(speaker.recentText()).toEqual(['Birinchi gap.']);
    expect(speaker.progress()).toEqual({ key: 'k1', spoken: 0, remaining: true });
    player.finish();
    await flush();
    expect(speaker.progress().spoken).toBe('Birinchi gap.'.length + 1);
    api.ok(1);
    await flush();
    expect(speaker.recentText()).toEqual(['Ikkinchi gap.', 'Birinchi gap.']);
    player.finish();
    await flush();
    expect(speaker.progress()).toEqual({ key: null, spoken: 0, remaining: false });
  });

  it('chunk files go to the speaker\'s own directory', async () => {
    const clock = new FakeClock();
    const files = new FakeFiles();
    const player = new FakePlayer(clock);
    const api = new FakeVoiceApi();
    const speaker = createSpeaker({ api, files, player, clock, settings: () => ({ voice: 'uz_female_calm', speed: 0.95 }), dir: 'voice-read' });
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0);
    await flush();
    expect(player.plays[0]).toMatch(/^file:\/\/\/cache\/voice-read\//);
  });

  it('output() compares in the PEAK domain (mic metering is a peak)', async () => {
    const { api, speaker, clock } = setup();
    speaker.speak('k1', queueOf('Javob.'), null);
    api.ok(0, makeWav(2000, 8000));
    await flush();
    await clock.advance(500);
    // 8000/32768 sinus: RMS ~ -15.2, cho'qqi ~ -12.2 dBFS
    expect(speaker.output().db as number).toBeGreaterThan(-13);
  });
});
