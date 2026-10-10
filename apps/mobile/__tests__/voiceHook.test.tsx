/**
 * `useVoiceSession` hook: mount'da sessiya boshlanadi (ruxsat -> audio rejim -> mikrofon),
 * `actions` barqaror, ilova fonga o'tsa mikrofon bo'shaydi va qaytganda tiklanadi,
 * unmount'da audio rejim qaytariladi. expo-audio - jest.setup mock'i (pleer yo'q -> jim pleer).
 */
import { act, renderHook } from '@testing-library/react-native';
import * as ExpoAudio from 'expo-audio';
import type { ReactNode } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { useVoiceSession } from '@/features/voice/useVoiceSession';
import { ServicesProvider } from '@/services';

import { fakeServices } from './fixtures/fakeServices';
import { flush } from './fixtures/voiceFakes';

jest.mock('expo-router', () => {
  const React = jest.requireActual('react') as typeof import('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), back: jest.fn() },
    useFocusEffect: (cb: () => void | (() => void)) => React.useEffect(() => cb(), [cb]),
  };
});

type Recorder = { isRecording: boolean; getStatus: jest.Mock; record: jest.Mock; stop: jest.Mock; prepareToRecordAsync: jest.Mock };
const recorder = (ExpoAudio as unknown as { __recorder: Recorder }).__recorder;

let appStateHandler: ((s: AppStateStatus) => void) | null = null;

beforeEach(() => {
  // Jim xona - hook testida VAD hech narsa eshitmasin.
  recorder.getStatus.mockReturnValue({ canRecord: true, isRecording: true, durationMillis: 100, mediaServicesDidReset: false, metering: -70, url: null });
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, cb) => {
    appStateHandler = cb as (s: AppStateStatus) => void;
    return { remove: jest.fn() } as unknown as ReturnType<typeof AppState.addEventListener>;
  });
});

afterEach(() => {
  jest.restoreAllMocks();
  appStateHandler = null;
});

async function mount() {
  const services = fakeServices();
  const wrapper = ({ children }: { children: ReactNode }) => <ServicesProvider services={services}>{children}</ServicesProvider>;
  const hook = await renderHook(() => useVoiceSession(), { wrapper });
  await act(async () => {
    await flush(5);
  });
  return hook;
}

describe('useVoiceSession', () => {
  it('starts listening on mount, keeps actions stable and restores audio on unmount', async () => {
    const { result, rerender, unmount } = await mount();
    expect(result.current.snap.status).toBe('listening');
    expect(ExpoAudio.requestRecordingPermissionsAsync).toHaveBeenCalled();
    expect(ExpoAudio.setAudioModeAsync).toHaveBeenCalledWith(expect.objectContaining({ allowsRecording: true, interruptionMode: 'doNotMix' }));
    expect(recorder.prepareToRecordAsync).toHaveBeenCalledWith(expect.objectContaining({ android: expect.objectContaining({ audioSource: 'voice_communication' }) }));
    expect(recorder.record).toHaveBeenCalled();

    const actions = result.current.actions;
    const subscribeLevel = result.current.subscribeLevel;
    await rerender({});
    expect(result.current.actions).toBe(actions);
    expect(result.current.subscribeLevel).toBe(subscribeLevel);

    await act(async () => {
      result.current.actions.toggleMute();
      await flush(3);
    });
    expect(result.current.snap).toMatchObject({ status: 'muted', micMuted: true });
    expect(recorder.stop).toHaveBeenCalled();

    await unmount();
    await act(async () => {
      await flush(5);
    });
    expect(ExpoAudio.setAudioModeAsync).toHaveBeenLastCalledWith(expect.objectContaining({ allowsRecording: false, shouldRouteThroughEarpiece: false }));
  });

  it('the app going to background suspends the session; coming back resumes it', async () => {
    const { result, unmount } = await mount();
    expect(appStateHandler).not.toBeNull();
    await act(async () => {
      appStateHandler?.('background');
      await flush(3);
    });
    expect(result.current.snap.suspended).toBe(true);
    await act(async () => {
      appStateHandler?.('active');
      await flush(3);
    });
    expect(result.current.snap).toMatchObject({ suspended: false, status: 'listening' });
    await unmount();
  });
});
