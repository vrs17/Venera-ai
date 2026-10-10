/**
 * "Tinglash": bir vaqtda bitta javob; bir xil tugma ikkinchi bosilsa to'xtaydi; boshqasi
 * bosilsa avvalgisi to'xtaydi; pauza/davom; sozlamadagi ovoz ishlatiladi; 501 da toast;
 * yangi suhbat ochilganda o'qish to'xtaydi; faqat uz va o'qiladigan matnda ko'rinadi.
 */
import { renderHook } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { useChat } from '@/features/chat/chatStore';
import { __resetReadAloud, __setReadAloudParts, canReadAloud, PREVIEW_KEY, PREVIEW_TEXT, stopReadAloud, useReadAloud, useReadAloudControls } from '@/features/voice/readAloud';
import { __resetTtsOff } from '@/features/voice/speaker';
import { useVoiceSettings } from '@/features/voice/voiceSettings';
import { ServicesProvider } from '@/services';
import { showToast } from '@/ui/errors';

import { fakeServices } from './fixtures/fakeServices';
import { FakeClock, FakeFiles, FakeMode, FakePlayer, FakeVoiceApi, flush } from './fixtures/voiceFakes';

jest.mock('@/ui/errors', () => ({ ...jest.requireActual('@/ui/errors'), showToast: jest.fn() }));

const ANSWER = "Bugun uch kishi kechikdi. Ali, Vali va Sardor o'z vaqtida kelmadi.";

async function setup() {
  const clock = new FakeClock();
  const api = new FakeVoiceApi();
  const player = new FakePlayer(clock);
  const files = new FakeFiles();
  const mode = new FakeMode();
  __setReadAloudParts(() => ({ api, files, player, mode }));
  const services = fakeServices();
  const wrapper = ({ children }: { children: ReactNode }) => <ServicesProvider services={services}>{children}</ServicesProvider>;
  const { result } = await renderHook(() => useReadAloudControls(), { wrapper });
  return { api, player, mode, controls: () => result.current };
}

beforeEach(() => {
  __resetReadAloud();
  __resetTtsOff();
  useVoiceSettings.setState({ voice: 'uz_female_calm', speed: 'normal' });
});

afterAll(() => {
  __resetReadAloud();
  __setReadAloudParts(null);
});

describe('canReadAloud', () => {
  it('only for an Uzbek UI and a speakable answer', () => {
    expect(canReadAloud(ANSWER, 'uz')).toBe(true);
    expect(canReadAloud(ANSWER, 'ru')).toBe(false);
    expect(canReadAloud('Сегодня трое опоздали.', 'uz')).toBe(false);
    expect(canReadAloud('```\nkod\n```', 'uz')).toBe(false);
    expect(canReadAloud('', 'uz')).toBe(false);
  });
});

describe('read-aloud controls', () => {
  it('toggle reads an answer with the chosen voice; the same key again stops it', async () => {
    const { api, player, mode, controls } = await setup();
    useVoiceSettings.setState({ voice: 'uz_male_news', speed: 'fast' });
    controls().toggle('ex1', ANSWER, 'ab'.repeat(16));
    expect(useReadAloud.getState()).toEqual({ key: 'ex1', phase: 'loading', index: 0, total: null });
    expect(mode.playbackOnly).toHaveBeenCalled();
    expect(api.calls[0]).toMatchObject({ text: 'Bugun uch kishi kechikdi.', opts: { voice: 'uz_male_news', speed: 1.1, turnId: 'ab'.repeat(16) } });

        api.ok(0);
    await flush();
    expect(useReadAloud.getState()).toMatchObject({ key: 'ex1', phase: 'playing', index: 1 });
    expect(player.plays).toHaveLength(1);

    controls().toggle('ex1', ANSWER, null);
    expect(useReadAloud.getState().key).toBeNull();
    expect(player.stops).toBe(1);
  });

  it('a second answer stops the first; total is known once the queue is drained', async () => {
    const { api, player, controls } = await setup();
    controls().toggle('ex1', ANSWER, null);
        api.ok(0);
    await flush();
    controls().toggle('ex2', 'Ikkinchi javob.', null);
    expect(useReadAloud.getState()).toMatchObject({ key: 'ex2', phase: 'loading' });
    expect(api.calls[1].opts.signal?.aborted).toBe(true);
        api.ok(2);
    await flush();
    expect(useReadAloud.getState()).toMatchObject({ key: 'ex2', phase: 'playing', index: 1, total: 1 });
        player.finish();
    await flush();
    expect(useReadAloud.getState().key).toBeNull();
  });

  it('pause and resume keep the position', async () => {
    const { api, player, controls } = await setup();
    controls().toggle('ex1', ANSWER, null);
        api.ok(0);
    await flush();
    controls().pause();
    expect(useReadAloud.getState().phase).toBe('paused');
    expect(player.paused).toBe(true);
    controls().resume();
    expect(useReadAloud.getState().phase).toBe('playing');
    expect(player.paused).toBe(false);
  });

  it('501 shows the "not enabled" toast and returns to idle', async () => {
    const { api, controls } = await setup();
    controls().toggle('ex1', ANSWER, null);
        api.fail(0, 501);
    await flush();
    expect(showToast).toHaveBeenCalled();
    expect(useReadAloud.getState().key).toBeNull();
    expect(canReadAloud(ANSWER, 'uz')).toBe(false);
  });

  it('preview speaks the fixed sample; a new chat or stopReadAloud() stops reading', async () => {
    const { api, player, controls } = await setup();
    controls().preview();
    expect(useReadAloud.getState().key).toBe(PREVIEW_KEY);
    expect(api.calls[0].text).toBe(PREVIEW_TEXT.split('!')[0] + '!');
    useChat.setState((s) => ({ epoch: s.epoch + 1 }));
    expect(useReadAloud.getState().key).toBeNull();
    expect(api.calls[0].opts.signal?.aborted).toBe(true);

    controls().toggle('ex1', ANSWER, null);
        api.ok(1);
    await flush();
    stopReadAloud();
    expect(useReadAloud.getState().key).toBeNull();
    expect(player.stops).toBeGreaterThan(0);
  });
});

describe('read-aloud keeps the screen on only while it plays', () => {
  it('on while loading/playing, off when paused or stopped', async () => {
    const clock = new FakeClock();
    const api = new FakeVoiceApi();
    const player = new FakePlayer(clock);
    const files = new FakeFiles();
    const mode = new FakeMode();
    const keepAwake = jest.fn();
    __setReadAloudParts(() => ({ api, files, player, mode, keepAwake }));
    const services = fakeServices();
    const wrapper = ({ children }: { children: ReactNode }) => <ServicesProvider services={services}>{children}</ServicesProvider>;
    const { result } = await renderHook(() => useReadAloudControls(), { wrapper });
    result.current.toggle('ex1', ANSWER, null);
    expect(keepAwake).toHaveBeenLastCalledWith(true);
    api.ok(0);
    await flush();
    result.current.pause();
    expect(keepAwake).toHaveBeenLastCalledWith(false);
    result.current.resume();
    expect(keepAwake).toHaveBeenLastCalledWith(true);
    result.current.stop();
    expect(keepAwake).toHaveBeenLastCalledWith(false);
    // Chunk fayllari o'z papkasida (jonli suhbat tozalashi ularga tegmaydi)
    expect(player.plays[0]).toMatch(/\/voice-read\//);
  });
});
