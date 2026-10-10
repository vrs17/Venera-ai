/**
 * Ovozli savol chat dvigatelida: `sendVoice` xuddi shu suhbatga (chatId) ovoz oqimi bilan
 * ketadi, exchange `input: 'voice'`; `hold` kadrlari birinchi tokengacha yig'iladi;
 * oddiy `send` va qayta yaratish (regenerate) ovoz maydonlarisiz qoladi.
 */
import { useChat } from '@/features/chat/chatStore';

import { fakeChatApi } from './fixtures/fakeServices';
import { controllableStream, flush } from './fixtures/voiceFakes';

// jest-expo'da randomUUID undefined qaytaradi - savollar alohida id olsin.
jest.mock('expo-crypto', () => {
  let n = 0;
  return { randomUUID: () => `ex-${++n}` };
});

function bind(proActive = false) {
  const api = fakeChatApi({ stream: jest.fn(() => new Promise<void>(() => {})) });
  useChat.getState().bind({ api, locale: () => 'uz', proActive: () => proActive });
  return api;
}

beforeEach(() => {
  useChat.getState().abort();
  useChat.setState({ chatId: 'c-voice', exchanges: [], phase: 'idle', epoch: 0 });
});

describe('chatStore.sendVoice', () => {
  it('returns an id and streams on the SAME chatId through the voice stream', async () => {
    const api = bind();
    const voice = controllableStream();
    const id = useChat.getState().sendVoice('  Bugun kim kechikdi? ', voice.fn);
    expect(typeof id).toBe('string');
    const ex = useChat.getState().exchanges.find((e) => e.id === id);
    expect(ex).toMatchObject({ question: 'Bugun kim kechikdi?', input: 'voice', holds: [], status: 'pending' });
    expect(voice.fn).toHaveBeenCalledTimes(1);
    expect(voice.calls[0].question).toBe('Bugun kim kechikdi?');
    expect(voice.calls[0].opts).toMatchObject({ chatId: 'c-voice', mode: 'standard', locale: 'uz' });
    expect(api.stream).not.toHaveBeenCalled();
    expect(useChat.getState().phase).toBe('sending');

    voice.calls[0].onFrame({ type: 'token', text: 'Uch kishi.' });
    voice.calls[0].onFrame({ type: 'done' });
    voice.calls[0].resolve();
    await flush();
    expect(useChat.getState().exchanges[0]).toMatchObject({ status: 'done', answer: 'Uch kishi.' });
    expect(useChat.getState().phase).toBe('idle');
  });

  it('collects hold frames until the first token, then ignores them', () => {
    bind();
    const voice = controllableStream();
    const id = useChat.getState().sendVoice('Savol', voice.fn) as string;
    const f = voice.calls[0].onFrame;
    f({ type: 'hold', text: 'Bir daqiqa', clip: 'kutish-ilk-1', at: 1, topic: 'hrm' });
    f({ type: 'hold', text: 'Hali qidiryapman', clip: '', at: 2 });
    f({ type: 'token', text: 'Javob' });
    f({ type: 'hold', text: 'Kech', clip: 'kutish-3', at: 3 });
    const ex = useChat.getState().exchanges.find((e) => e.id === id);
    expect(ex?.holds).toEqual([
      { text: 'Bir daqiqa', clip: 'kutish-ilk-1', at: 1, topic: 'hrm' },
      { text: 'Hali qidiryapman', clip: null, at: 2, topic: null },
    ]);
  });

  it('is refused (null) while another answer is running; Pro is frozen like send()', () => {
    bind(true);
    const voice = controllableStream();
    expect(useChat.getState().sendVoice('Birinchi', voice.fn)).not.toBeNull();
    expect(voice.calls[0].opts.mode).toBe('pro');
    expect(useChat.getState().exchanges[0].proRequested).toBe(true);
    expect(useChat.getState().sendVoice('Ikkinchi', voice.fn)).toBeNull();
    expect(useChat.getState().sendVoice('   ', voice.fn)).toBeNull();
  });

  it('send() still goes through the plain API with no voice fields', () => {
    const api = bind();
    expect(useChat.getState().send('Matnli savol')).toBe(true);
    expect(api.stream).toHaveBeenCalledTimes(1);
    expect(useChat.getState().exchanges[0]).toMatchObject({ input: 'text', holds: [] });
  });

  it('regenerate of a voice exchange keeps the marker but sends a plain (non-voice) turn', async () => {
    const api = bind();
    const voice = controllableStream();
    const id = useChat.getState().sendVoice('Ovozli savol', voice.fn) as string;
    voice.calls[0].onFrame({ type: 'hold', text: 'Bir daqiqa', clip: 'k-1', at: 1 });
    voice.calls[0].onFrame({ type: 'token', text: 'Javob' });
    voice.calls[0].resolve();
    await flush();
    useChat.getState().regenerate(id);
    expect(api.stream).toHaveBeenCalledTimes(1);
    expect(voice.fn).toHaveBeenCalledTimes(1);
    expect(useChat.getState().exchanges[0]).toMatchObject({ input: 'voice', holds: [], status: 'pending' });
  });

  it('history exchanges are text turns', async () => {
    const api = fakeChatApi({
      get: jest.fn(async (id: string) => ({ chat_id: id, title: '', created_at: null, updated_at: null, messages: [{ role: 'user', content: 'S', created_at: null }, { role: 'assistant', content: 'J', created_at: null }] })),
    });
    useChat.getState().bind({ api, locale: () => 'uz', proActive: () => false });
    await useChat.getState().openHistory('c-old', true);
    expect(useChat.getState().exchanges[0]).toMatchObject({ input: 'text', holds: [] });
  });
});
