/**
 * Ovozli sessiya - soxta mikrofon (dB ssenariysi), STT, chat oqimi, TTS va pleer bilan
 * to'liq aylanishlar: uz savol (kutish klipi -> javob), bo'lib gapirish, ru (ovozsiz),
 * davomli gap, ishonchsiz matn, chat band, mikrofon/ruxsat xatolari, pauza, tugatish.
 */
import { ApiError, StreamAbortedError } from '@/api/client';
import type { TranscriptResponse } from '@/api/chat';
import { useChat } from '@/features/chat/chatStore';
import type { UiLang } from '@/i18n';
import { adtsDurationMs } from '@/features/voice/adts';
import { createChatPort } from '@/features/voice/chatPort';
import { createVoiceSession } from '@/features/voice/session';
import { __resetTtsOff, createSpeaker } from '@/features/voice/speaker';
import { DEFAULT_VOICE_SETTINGS } from '@/features/voice/voiceSettings';

import { fakeChatApi } from './fixtures/fakeServices';
import { controllableStream, FakeClock, FakeFiles, FakeMic, FakeMode, FakePlayer, FakeVoiceApi, flush } from './fixtures/voiceFakes';

jest.mock('expo-crypto', () => {
  let n = 0;
  return { randomUUID: () => `ex-${++n}` };
});

interface SttCall {
  uri: string;
  lang: UiLang;
  bytes: Uint8Array | undefined;
  resolve: (r: TranscriptResponse) => void;
  reject: (e: unknown) => void;
}

function setup(o: { uiLang?: UiLang; meetingActive?: boolean; permission?: boolean } = {}) {
  const clock = new FakeClock();
  const files = new FakeFiles();
  const mic = new FakeMic(clock, files);
  const player = new FakePlayer(clock);
  const api = new FakeVoiceApi();
  const mode = new FakeMode();
  const speaker = createSpeaker({ api, files, player, clock, settings: () => ({ voice: 'uz_female_calm', speed: 0.95 }) });
  const textStream = controllableStream();
  const chatApi = fakeChatApi({ stream: textStream.fn });
  useChat.getState().bind({ api: chatApi, locale: () => o.uiLang ?? 'uz', proActive: () => false });
  const voice = controllableStream();
  const sttCalls: SttCall[] = [];
  const stt = {
    transcribe: jest.fn(
      (uri: string, lang: UiLang, signal: AbortSignal) =>
        new Promise<TranscriptResponse>((resolve, reject) => {
          sttCalls.push({ uri, lang, bytes: files.store.get(uri), resolve, reject });
          signal.addEventListener('abort', () => reject(new StreamAbortedError()));
        }),
    ),
  };
  const keepAwake = jest.fn();
  const stopReadAloud = jest.fn();
  const setEarpiece = jest.fn();
  const session = createVoiceSession({
    mic,
    speaker,
    chat: createChatPort(voice.fn),
    stt,
    mode,
    files,
    clock,
    uiLang: () => o.uiLang ?? 'uz',
    settings: () => DEFAULT_VOICE_SETTINGS,
    setEarpiece,
    meetingActive: () => !!o.meetingActive,
    requestPermission: jest.fn(async () => o.permission ?? true),
    keepAwake,
    stopReadAloud,
  });
  /** Gap oynalari (mutlaq ms) - shu paytda mikrofon -20 dB, aks holda -55. */
  const speech: [number, number, number][] = [];
  mic.dbAt = (t) => speech.find(([a, b]) => t >= a && t < b)?.[2] ?? -55;
  const say = (ms: number, db = -20, from = clock.now()) => speech.push([from, from + ms, db]);
  const snap = () => session.getSnapshot();
  return { clock, files, mic, player, api, mode, speaker, voice, textStream, stt, sttCalls, session, say, snap, keepAwake, stopReadAloud, setEarpiece };
}

type H = ReturnType<typeof setup>;

/** Boshlash va jim xonada 3 s (shovqin sathi o'rganiladi). */
async function listening(h: H) {
  h.session.start();
  await flush();
  expect(h.snap().status).toBe('listening');
  await h.clock.advance(3000);
}

/** Bitta gap: 1.2 s gapirish + ~1 s jimlik -> tanilish. */
async function utter(h: H, ms = 1200) {
  h.say(ms);
  await h.clock.advance(ms + 1100);
}

/** Savol yuborilib, javob kutilayotgan holatgacha. */
async function asked(h: H, text = 'Bugun kim kechikdi?') {
  await listening(h);
  await utter(h);
  expect(h.snap().status).toBe('transcribing');
  h.sttCalls[h.sttCalls.length - 1].resolve({ text });
  await flush();
  expect(h.snap().status).toBe('thinking');
  return h.voice.calls[h.voice.calls.length - 1];
}

beforeEach(() => {
  __resetTtsOff();
  useChat.getState().abort();
  useChat.setState({ chatId: 'c-main', exchanges: [], phase: 'idle', epoch: 0 });
});

describe('voice session - full Uzbek turn', () => {
  it('listen -> speech end -> STT -> same chat -> hold clip -> answer waits for the clip -> speaking -> listening', async () => {
    const h = setup();
    h.session.start();
    await flush();
    expect(h.keepAwake).toHaveBeenCalledWith(true);
    expect(h.stopReadAloud).toHaveBeenCalled();
    expect(h.mode.log).toEqual(['enter:false']);
    expect(h.mic.recording).toBe(true);
    expect(h.snap().status).toBe('listening');
    await h.clock.advance(3000);

    h.say(1200);
    await h.clock.advance(300);
    expect(h.snap().hearing).toBe(true);
    await h.clock.advance(2000);
    expect(h.snap().status).toBe('transcribing');
    // Segment yopilib DARHOL yangisi ochilgan; gap 300 ms oldidan kesib olingan
    expect(h.mic.starts).toBe(2);
    expect(h.mic.recording).toBe(true);
    const call = h.sttCalls[0];
    expect(call.lang).toBe('uz');
    expect(call.uri).toMatch(/^file:\/\/\/cache\/voice\/utt-/);
    const ms = adtsDurationMs(call.bytes as Uint8Array);
    expect(ms).toBeGreaterThan(1400);
    expect(ms).toBeLessThan(2000);

    call.resolve({ text: 'Bugun kim kechikdi?' });
    await flush();
    expect(h.snap().status).toBe('thinking');
    const stream = h.voice.calls[0];
    expect(stream.question).toBe('Bugun kim kechikdi?');
    expect(stream.opts.chatId).toBe('c-main');
    const id = useChat.getState().exchanges[0].id;
    expect(h.snap().turnIds).toEqual([id]);
    expect(useChat.getState().exchanges[0].input).toBe('voice');
    // Ishlatilgan fayl o'chirilgan
    expect(h.files.store.has(call.uri)).toBe(false);

    stream.onFrame({ type: 'hold', text: 'Bir daqiqa, tekshiryapman', clip: 'kutish-ilk-1', at: 1, topic: 'hrm' });
    await flush();
    expect(h.api.hold).toHaveBeenCalledWith('kutish-ilk-1', 'uz_female_calm', expect.anything());
    expect(h.snap().holdText).toBe('Bir daqiqa, tekshiryapman');
    expect(h.player.plays).toHaveLength(1);

    stream.onFrame({ type: 'token', text: 'Bugun uch kishi kechikdi. Ali, Vali va Sardor kech keldi.' });
    stream.onFrame({ type: 'done' });
    stream.resolve();
    await flush();
    // Javobning birinchi gapi klip yangrayotganda SINTEZ qilinadi...
    expect(h.api.calls.map((c) => c.text)).toEqual(['Bugun uch kishi kechikdi.']);
    h.api.ok(0);
    await flush();
    // ...lekin klip kesilmaydi
    expect(h.player.plays).toHaveLength(1);
    expect(h.snap().status).toBe('thinking');

    h.player.finish();
    await flush();
    expect(h.snap()).toMatchObject({ status: 'speaking', speakingId: id, holdText: null });
    expect(h.player.plays).toHaveLength(2);
    h.api.ok(1);
    await flush();
    h.player.finish();
    await flush();
    h.player.finish();
    await flush();
    expect(h.snap()).toMatchObject({ status: 'listening', speakingId: null });
    expect(useChat.getState().exchanges[0]).toMatchObject({ status: 'done', answer: 'Bugun uch kishi kechikdi. Ali, Vali va Sardor kech keldi.' });
  });

  it('barge-in while Barno speaks PAUSES the audio; a real question then stops it and is sent', async () => {
    const h = setup();
    const stream = await asked(h);
    stream.onFrame({ type: 'token', text: "Bugun uch kishi kechikdi. Ular haqida batafsil ma'lumot quyida keltirilgan." });
    stream.onFrame({ type: 'done' });
    stream.resolve();
    await flush();
    h.api.ok(0);
    await flush();
    expect(h.snap().status).toBe('speaking');
    // Barno gapirayotganda mikrofonda faqat aks-sado: bo'lib gapirish yo'q
    await h.clock.advance(800);
    expect(h.snap().status).toBe('speaking');

    h.say(1000, -5);
    await h.clock.advance(400);
    expect(h.snap()).toMatchObject({ status: 'listening', hearing: true });
    expect(h.player.paused).toBe(true);
    expect(h.player.stops).toBe(0);

    await h.clock.advance(1800);
    expect(h.snap().status).toBe('transcribing');
    expect(h.sttCalls).toHaveLength(2);
    // Kesilgan gap Barno ovozini emas, odamni oladi (~1.4 s, butun segment ~4 s emas)
    expect(adtsDurationMs(h.sttCalls[1].bytes as Uint8Array)).toBeLessThan(2000);
    h.sttCalls[1].resolve({ text: 'Ertaga kim kechikadi?' });
    await flush();
    expect(h.player.stops).toBeGreaterThanOrEqual(1);
    expect(h.api.calls[1].opts.signal?.aborted).toBe(true);
    expect(useChat.getState().exchanges[0]).toMatchObject({ status: 'done' });
    expect(h.voice.calls.map((c) => c.question)).toEqual(['Bugun kim kechikdi?', 'Ertaga kim kechikadi?']);
  });

  it('a tap during speech interrupts; the fog level follows the user, then Barno', async () => {
    const h = setup();
    const levels: [number, string][] = [];
    h.session.subscribeLevel((l, src) => levels.push([l, src]));
    const stream = await asked(h);
    expect(levels.some(([l, src]) => src === 'user' && l > 0.3)).toBe(true);
    stream.onFrame({ type: 'token', text: 'Javob tayyor.' });
    stream.onFrame({ type: 'done' });
    stream.resolve();
    await flush();
    h.api.ok(0);
    await flush();
    await h.clock.advance(300);
    expect(levels.slice(-3).every(([, src]) => src === 'barno')).toBe(true);
    expect(levels[levels.length - 1][0]).toBeGreaterThan(0.3);
    h.session.actions.interrupt();
    expect(h.snap().status).toBe('listening');
    expect(h.player.stops).toBe(1);
  });
});

describe('voice session - Russian / English', () => {
  it('ru: STT in Russian, the answer is not spoken, the uz_only note is shown once', async () => {
    const h = setup({ uiLang: 'ru' });
    expect(h.snap().canSpeak).toBe(false);
    const stream = await asked(h, 'Кто опоздал сегодня?');
    expect(h.sttCalls[0].lang).toBe('ru');
    stream.onFrame({ type: 'hold', text: 'x', clip: 'kutish-1', at: 1 });
    stream.onFrame({ type: 'token', text: 'Сегодня опоздали трое.' });
    stream.onFrame({ type: 'done' });
    stream.resolve();
    await flush();
    expect(h.api.clip).not.toHaveBeenCalled();
    expect(h.api.hold).not.toHaveBeenCalled();
    expect(h.snap()).toMatchObject({ status: 'listening', notice: 'uz_only' });
    // 4 s dan keyin eslatma o'chadi
    await h.clock.advance(4100);
    expect(h.snap().notice).toBeNull();
  });
});

describe('voice session - utterance handling', () => {
  it('a pause longer than 1 s mid-question merges both parts into ONE question', async () => {
    const h = setup();
    await listening(h);
    await utter(h, 900);
    expect(h.snap().status).toBe('transcribing');
    // Birinchi qism tanilayotganda odam davom etadi
    h.say(900);
    await h.clock.advance(400);
    expect(h.snap().hearing).toBe(true);
    h.sttCalls[0].resolve({ text: 'Bugun' });
    await flush();
    expect(h.snap().status).toBe('listening');
    expect(h.voice.calls).toHaveLength(0);
    await h.clock.advance(1700);
    expect(h.snap().status).toBe('transcribing');
    h.sttCalls[1].resolve({ text: 'kim kechikdi?' });
    await flush();
    expect(h.voice.calls.map((c) => c.question)).toEqual(['Bugun kim kechikdi?']);
  });

  it('a second part that ended before the first STT returned is queued and joined', async () => {
    const h = setup();
    await listening(h);
    await utter(h, 900);
    h.say(900);
    await h.clock.advance(2100);
    expect(h.snap().status).toBe('transcribing');
    // ikkinchi STT hali boshlanmagan - navbatda
    expect(h.sttCalls).toHaveLength(1);
    h.sttCalls[0].resolve({ text: 'Bugun' });
    await flush();
    expect(h.sttCalls).toHaveLength(2);
    h.sttCalls[1].resolve({ text: 'kim kechikdi?' });
    await flush();
    expect(h.voice.calls.map((c) => c.question)).toEqual(['Bugun kim kechikdi?']);
  });

  it('a low-confidence transcript waits for the user; sendPending sends it', async () => {
    const h = setup();
    await listening(h);
    await utter(h);
    h.sttCalls[0].resolve({ text: 'Bugun kim kechikdi', lowConfidence: true });
    await flush();
    expect(h.snap()).toMatchObject({ status: 'listening', pendingText: 'Bugun kim kechikdi', notice: 'unsure' });
    expect(h.voice.calls).toHaveLength(0);
    h.session.actions.sendPending();
    await flush();
    expect(h.snap()).toMatchObject({ status: 'thinking', pendingText: null });
    expect(h.voice.calls[0].question).toBe('Bugun kim kechikdi');
  });

  it('a blip is never uploaded; silence for 45 s mutes the mic', async () => {
    const h = setup();
    await listening(h);
    h.say(200);
    await h.clock.advance(2000);
    expect(h.sttCalls).toHaveLength(0);
    expect(h.snap().status).toBe('listening');
    await h.clock.advance(45_000);
    expect(h.snap()).toMatchObject({ status: 'muted', micMuted: true, notice: 'auto_muted' });
    expect(h.mic.recording).toBe(false);
    h.session.actions.toggleMute();
    await flush();
    expect(h.snap()).toMatchObject({ status: 'listening', micMuted: false });
    expect(h.mic.recording).toBe(true);
  });

  it('when the chat is busy the question waits and is sent once the chat is free', async () => {
    const h = setup();
    useChat.getState().send('Matnli savol');
    expect(useChat.getState().phase).toBe('sending');
    await listening(h);
    await utter(h);
    h.sttCalls[0].resolve({ text: 'Ovozli savol' });
    await flush();
    expect(h.snap()).toMatchObject({ status: 'listening', pendingText: 'Ovozli savol', notice: 'chat_busy' });
    h.textStream.calls[0].onFrame({ type: 'token', text: 'Javob' });
    h.textStream.calls[0].resolve();
    await flush();
    expect(h.voice.calls.map((c) => c.question)).toEqual(['Ovozli savol']);
    expect(h.snap()).toMatchObject({ status: 'thinking', pendingText: null });
  });
});

describe('voice session - failures and lifecycle', () => {
  it('a running meeting recording refuses to start; denied permission and mic failure are errors', async () => {
    const busy = setup({ meetingActive: true });
    busy.session.start();
    await flush();
    expect(busy.snap()).toMatchObject({ status: 'error', error: 'mic_busy' });
    expect(busy.mic.starts).toBe(0);

    const denied = setup({ permission: false });
    denied.session.start();
    await flush();
    expect(denied.snap()).toMatchObject({ status: 'error', error: 'mic_denied' });

    const broken = setup();
    broken.mic.failNextStart = true;
    broken.session.start();
    await flush();
    expect(broken.snap()).toMatchObject({ status: 'error', error: 'mic_failed' });
    broken.session.actions.retry();
    await flush();
    expect(broken.snap().status).toBe('listening');
  });

  it('a network failure in STT -> offline error; other failures retry by listening', async () => {
    const h = setup();
    await listening(h);
    await utter(h);
    h.sttCalls[0].reject(new ApiError(0, 'timeout', 'x'));
    await flush();
    expect(h.snap()).toMatchObject({ status: 'listening', notice: 'stt_retry' });
    await utter(h);
    h.sttCalls[1].reject(new ApiError(0, 'network', 'x'));
    await flush();
    expect(h.snap()).toMatchObject({ status: 'error', error: 'offline' });
    expect(h.mic.recording).toBe(false);
  });

  it('suspend releases the mic and stops speech; resume listens again', async () => {
    const h = setup();
    await listening(h);
    h.session.suspend();
    await flush();
    expect(h.snap().suspended).toBe(true);
    expect(h.mic.recording).toBe(false);
    h.session.resume();
    await flush();
    expect(h.snap()).toMatchObject({ suspended: false, status: 'listening' });
    expect(h.mic.recording).toBe(true);
  });

  it('END while thinking keeps the chat request running and restores the audio mode', async () => {
    const h = setup();
    const stream = await asked(h);
    await h.session.actions.end();
    await flush();
    expect(stream.opts.signal?.aborted).toBe(false);
    expect(useChat.getState().phase).toBe('sending');
    expect(h.mic.recording).toBe(false);
    expect(h.mode.log).toEqual(['enter:false', 'restore']);
    expect(h.keepAwake).toHaveBeenLastCalledWith(false);
    expect(h.player.disposed).toBe(true);
    expect([...h.files.store.keys()].filter((k) => k.includes('/voice/'))).toEqual([]);
    // Javob baribir chatga tushadi
    stream.onFrame({ type: 'token', text: 'Javob.' });
    stream.resolve();
    await flush();
    expect(useChat.getState().exchanges[0]).toMatchObject({ status: 'done', answer: 'Javob.' });
    expect(h.api.clip).not.toHaveBeenCalled();
    // Ikkinchi end() - zararsiz
    await h.session.actions.end();
  });

  it('switching to the earpiece persists the choice and changes the audio route', async () => {
    const h = setup();
    await listening(h);
    h.session.actions.setEarpiece(true);
    await flush();
    expect(h.snap().earpiece).toBe(true);
    expect(h.setEarpiece).toHaveBeenCalledWith(true);
    expect(h.mode.log).toEqual(['enter:false', 'earpiece:true']);
  });
});

describe('voice session - review fixes', () => {
  /** Javob yangray boshlagan holat (birinchi bo'lak o'ynayapti). */
  async function speaking(h: H, text = "Bugun uch kishi kechikdi. Ular haqida batafsil ma'lumot quyida keltirilgan.") {
    const stream = await asked(h);
    stream.onFrame({ type: 'token', text });
    stream.onFrame({ type: 'done' });
    stream.resolve();
    await flush();
    h.api.ok(0);
    await flush();
    expect(h.snap().status).toBe('speaking');
    await h.clock.advance(800);
    return stream;
  }

  it('a false barge-in (noise) resumes Barno from where she paused - no "repeat" notice', async () => {
    const h = setup();
    await speaking(h);
    h.say(1000, -5);
    await h.clock.advance(2200);
    expect(h.snap().status).toBe('transcribing');
    h.sttCalls[1].resolve({ text: '' });
    await flush();
    expect(h.snap()).toMatchObject({ status: 'speaking', notice: null });
    expect(h.player.paused).toBe(false);
    expect(h.player.stops).toBe(0);
    expect(h.voice.calls).toHaveLength(1);
  });

  it("Barno's own words picked up by the mic are not sent as a question (echo check)", async () => {
    const h = setup();
    await speaking(h);
    h.say(1000, -5);
    await h.clock.advance(2200);
    h.sttCalls[1].resolve({ text: 'Bugun uch kishi kechikdi' });
    await flush();
    expect(h.snap().status).toBe('speaking');
    expect(h.voice.calls).toHaveLength(1);
  });

  it('"to\'xta" only stops the audio; nothing is sent to the agent', async () => {
    const h = setup();
    await speaking(h);
    h.say(1000, -5);
    await h.clock.advance(2200);
    h.sttCalls[1].resolve({ text: "To'xta." });
    await flush();
    expect(h.snap()).toMatchObject({ status: 'listening', speakingId: null });
    expect(h.player.stops).toBeGreaterThanOrEqual(1);
    expect(h.voice.calls).toHaveLength(1);
  });

  it('barge-in while waiting does NOT cancel the request; noise -> the answer is still spoken', async () => {
    const h = setup();
    const stream = await asked(h);
    stream.onFrame({ type: 'hold', text: 'Bir daqiqa, tekshiryapman', clip: 'kutish-ilk-1', at: 1, topic: 'hrm' });
    await flush();
    await h.clock.advance(800);
    h.say(1000, -5);
    await h.clock.advance(800);
    expect(h.snap()).toMatchObject({ status: 'listening', hearing: true });
    expect(stream.opts.signal?.aborted).toBe(false);
    expect(useChat.getState().phase).toBe('sending');
    // Shu paytda javob keladi - tekshiruv tugaguncha o'qilmaydi
    stream.onFrame({ type: 'token', text: 'Bugun uch kishi kechikdi.' });
    stream.onFrame({ type: 'done' });
    stream.resolve();
    await flush();
    expect(h.api.calls).toHaveLength(0);
    await h.clock.advance(1400);
    h.sttCalls[1].resolve({ text: 'x' });
    await flush();
    expect(h.snap().status).toBe('thinking');
    expect(h.api.calls.map((c) => c.text)).toEqual(['Bugun uch kishi kechikdi.']);
  });

  it('a user who continues the question while waiting sends both halves as ONE question', async () => {
    const h = setup();
    const stream = await asked(h, 'Bugun kim');
    await h.clock.advance(500);
    h.say(1000, -5);
    await h.clock.advance(2400);
    expect(h.snap().status).toBe('transcribing');
    h.sttCalls[1].resolve({ text: 'kechikdi?' });
    await flush();
    expect(stream.opts.signal?.aborted).toBe(true);
    expect(useChat.getState().exchanges[0].status).toBe('cancelled');
    expect(h.voice.calls.map((c) => c.question)).toEqual(['Bugun kim', 'Bugun kim kechikdi?']);
  });

  it('the cut follows the FILE timeline (capture latency) so the first syllable is not clipped', async () => {
    const h = setup();
    h.mic.captureLatencyMs = 400;
    await listening(h);
    const onsetAbs = h.clock.now();
    await utter(h);
    const bytes = h.sttCalls[0].bytes as Uint8Array;
    // Kadr to'ldiruvchisi = kadr raqami; kadr i fayl vaqti i*64 ms = devor soati i*64 + 400.
    const firstFrame = bytes[7];
    const onsetFileMs = onsetAbs - h.mic.segStarts[0] - 400;
    expect(firstFrame * 64).toBeLessThanOrEqual(onsetFileMs - 200);
  });

  it('STT upload does not wait for the next mic segment to open', async () => {
    const h = setup();
    await listening(h);
    h.mic.startDelayMs = 300;
    h.say(1200);
    await h.clock.advance(2250);
    expect(h.snap().status).toBe('transcribing');
    expect(h.sttCalls).toHaveLength(1);
    expect(h.mic.recording).toBe(false);
    await h.clock.advance(400);
    expect(h.mic.recording).toBe(true);
  });

  it('keeps the screen on while the conversation is live; off when the mic auto-mutes; on again after unmute', async () => {
    const h = setup();
    await listening(h);
    expect(h.keepAwake.mock.calls).toEqual([[true]]);
    await h.clock.advance(45_000);
    expect(h.snap().status).toBe('muted');
    expect(h.keepAwake).toHaveBeenLastCalledWith(false);
    h.session.actions.toggleMute();
    await flush();
    expect(h.keepAwake).toHaveBeenLastCalledWith(true);
    await h.session.actions.end();
    expect(h.keepAwake).toHaveBeenLastCalledWith(false);
  });

  it('coming back after a pause mid-answer continues from the interrupted chunk, not from the start', async () => {
    const h = setup();
    await speaking(h, 'Birinchi gap. Ikkinchi gap. Uchinchi gap.');
    h.api.ok(1);
    await flush();
    h.player.finish();
    await flush();
    expect(h.player.plays).toHaveLength(2);
    h.session.suspend();
    await flush();
    expect(h.mic.recording).toBe(false);
    h.session.resume();
    await flush();
    expect(h.snap().status).toBe('thinking');
    const texts = h.api.calls.map((c) => c.text);
    expect(texts[texts.length - 1].startsWith('Ikkinchi gap.')).toBe(true);
    // Audio rejim qayta qo'yildi (qo'ng'iroq uni o'zgartirgan bo'lishi mumkin)
    expect(h.mode.log.filter((x) => x.startsWith('enter'))).toHaveLength(2);
  });

  it('a meeting recording started while away blocks the mic on return', async () => {
    const o = { meetingActive: false };
    const h = setup(o);
    await listening(h);
    h.session.suspend();
    await flush();
    o.meetingActive = true;
    h.session.resume();
    await flush();
    expect(h.snap()).toMatchObject({ status: 'error', error: 'mic_busy' });
    expect(h.mic.recording).toBe(false);
  });

  it('while waiting, room noise barely moves the fog (thinking looks different from listening)', async () => {
    const h = setup();
    const levels: [number, string][] = [];
    h.session.subscribeLevel((l, src) => levels.push([l, src]));
    await asked(h);
    await h.clock.advance(2000);
    levels.length = 0;
    // Xona shovqini START dan biroz baland (-38 > -40), lekin bo'lib gapirish chegarasidan past.
    h.say(3000, -38);
    await h.clock.advance(1000);
    expect(h.snap().status).toBe('thinking');
    const max = Math.max(...levels.map(([l]) => l));
    // Tinglashda xuddi shu shovqin ~0.4 ko'rsatardi.
    expect(max).toBeLessThan(0.15);
  });

  it('old crash leftovers are swept on start', async () => {
    const h = setup();
    const sweep = jest.fn();
    (h.files as unknown as { sweepRecordings: jest.Mock }).sweepRecordings = sweep;
    h.session.start();
    await flush();
    expect(sweep).toHaveBeenCalledWith(60 * 60 * 1000);
  });
});

describe('voice session - hold clips after a false barge-in', () => {
  it('an old hold clip is not replayed when waiting resumes after noise', async () => {
    const h = setup();
    const stream = await asked(h);
    stream.onFrame({ type: 'hold', text: 'Bir daqiqa, tekshiryapman', clip: 'kutish-ilk-1', at: 1, topic: 'hrm' });
    await flush();
    expect(h.player.plays).toHaveLength(1);
    await h.clock.advance(800);
    h.say(1000, -5);
    await h.clock.advance(2200);
    h.sttCalls[1].resolve({ text: '' });
    await flush();
    expect(h.snap().status).toBe('thinking');
    expect(h.player.plays).toHaveLength(1);
    // Keyingi (yangi) kutish klipi esa o'ynaladi
    stream.onFrame({ type: 'hold', text: 'Hali qarayapman', clip: 'kutish-2', at: 9, topic: 'hrm' });
    await flush();
    expect(h.player.plays).toHaveLength(2);
  });
});
