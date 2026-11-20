/**
 * "Jonli suhbat" ekrani (`/live`): saytdagi /barno sahifasi WebView'da (soxta - `jest.setup.js`).
 * Manzil va token (faqat o'z saytimizga), `ready` ga javob, ✕ va "orqaga" (avval qo'ng'iroqni tugatish),
 * 401 dan keyin bir marta yangi token, `close`, mikrofon rad etilsa, sessiya yo'q, sahifa ochilmasa,
 * ilova uzoq fonda qolsa.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { router } from 'expo-router';
import { AppState, BackHandler, Linking } from 'react-native';

import LiveScreen, { BACKGROUND_END_MS } from '@/app/live';
import { END_SCRIPT } from '@/features/live/bridge';
import { useSettings } from '@/features/settings/settingsStore';
import type { Services } from '@/services';

import { fakeServices, Providers } from './fixtures/fakeServices';

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
  };
});

interface WebState {
  last: {
    source: { uri: string };
    originWhitelist: string[];
    injectedJavaScriptBeforeContentLoaded: string;
    mediaPlaybackRequiresUserAction: boolean;
    onMessage: (e: { nativeEvent: { data: string; url: string } }) => void;
    onError: () => void;
  } | null;
  mounts: number;
}
const web = jest.requireMock('react-native-webview') as { __state: WebState; __inject: jest.Mock };
const audio = jest.requireMock('expo-audio') as { requestRecordingPermissionsAsync: jest.Mock };
const back = router.back as jest.Mock;

type BackFn = Parameters<typeof BackHandler.addEventListener>[1];
type StateFn = Parameters<typeof AppState.addEventListener>[1];
let backHandlers: BackFn[] = [];
let stateHandlers: StateFn[] = [];

beforeEach(() => {
  web.__state.last = null;
  web.__state.mounts = 0;
  backHandlers = [];
  stateHandlers = [];
  jest.spyOn(BackHandler, 'addEventListener').mockImplementation((_e, h) => {
    backHandlers.push(h);
    return { remove: () => {} };
  });
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_e, h) => {
    stateHandlers.push(h);
    return { remove: () => {} } as ReturnType<typeof AppState.addEventListener>;
  });
  useSettings.getState().set({ uiLang: 'uz', themePref: 'light' });
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

async function renderLive(services: Services = fakeServices()) {
  await render(
    <Providers services={services}>
      <LiveScreen />
    </Providers>,
  );
  return services;
}

async function message(data: object, url = 'https://x.uz/barno?app=1') {
  await act(async () => {
    web.__state.last?.onMessage({ nativeEvent: { data: JSON.stringify(data), url } });
  });
}

describe('LiveScreen (/live)', () => {
  it('opens /barno in app mode with the token, only on our own origin', async () => {
    await renderLive();
    expect(await screen.findByTestId('live-web')).toBeTruthy();
    const props = web.__state.last!;
    expect(props.source.uri).toBe('https://x.uz/barno?app=1&autostart=1&theme=light&lang=uz');
    expect(props.originWhitelist).toEqual(['https://x.uz']);
    expect(props.injectedJavaScriptBeforeContentLoaded).toContain('"jwt"');
    expect(props.injectedJavaScriptBeforeContentLoaded).toContain('location.origin!=="https://x.uz"');
    // Agent ovozi tugma bosilmasdan ham eshitilsin.
    expect(props.mediaPlaybackRequiresUserAction).toBe(false);
  });

  it('"ready" from our page gets the token; a foreign page gets nothing', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await message({ type: 'ready' });
    await waitFor(() => expect(web.__inject).toHaveBeenCalledWith(expect.stringContaining('"jwt"')));
    web.__inject.mockClear();
    await message({ type: 'ready' }, 'https://evil.example/barno');
    expect(web.__inject).not.toHaveBeenCalled();
    // Buzuq xabar e'tiborsiz.
    await act(async () => {
      web.__state.last?.onMessage({ nativeEvent: { data: '{oops', url: 'https://x.uz/barno' } });
    });
    expect(web.__inject).not.toHaveBeenCalled();
  });

  it('✕ during a call ends it inside the page first, then closes', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await message({ type: 'status', status: 'live' });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('live-close'));
    });
    expect(web.__inject).toHaveBeenCalledWith(END_SCRIPT);
    await waitFor(() => expect(back).toHaveBeenCalledTimes(1));
  });

  it('✕ with no call: closes right away without touching the page', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await message({ type: 'status', status: 'ended' });
    await act(async () => {
      await fireEvent.press(screen.getByTestId('live-close'));
    });
    expect(web.__inject).not.toHaveBeenCalled();
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('Android back: ends a running call (thank-you page stays), closes when there is no call', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await message({ type: 'status', status: 'connecting' });
    let handled: boolean | null | undefined = false;
    await act(async () => {
      handled = backHandlers.at(-1)?.({} as Parameters<BackFn>[0]);
    });
    expect(handled).toBe(true);
    expect(web.__inject).toHaveBeenCalledWith(END_SCRIPT);
    expect(back).not.toHaveBeenCalled();

    await message({ type: 'status', status: 'ended' });
    await act(async () => {
      backHandlers.at(-1)?.({} as Parameters<BackFn>[0]);
    });
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('401 from the page: one token refresh and a fresh page; a second 401 asks to sign in again', async () => {
    const services = await renderLive();
    await screen.findByTestId('live-web');
    expect(web.__state.mounts).toBe(1);
    await message({ type: 'auth' });
    await waitFor(() => expect(services.session.refreshToken).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(web.__state.mounts).toBe(2));
    expect(web.__state.last!.injectedJavaScriptBeforeContentLoaded).toContain('"jwt2"');

    await message({ type: 'auth' });
    expect(await screen.findByTestId('live-auth')).toBeTruthy();
    expect(services.session.refreshToken).toHaveBeenCalledTimes(1);
  });

  it('"close" from the page (the "Yopish" button) closes the screen', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await message({ type: 'close' });
    await waitFor(() => expect(back).toHaveBeenCalledTimes(1));
  });

  it('microphone denied: explanation and settings; allowing it there continues to the call', async () => {
    audio.requestRecordingPermissionsAsync.mockResolvedValueOnce({ granted: false, status: 'denied' });
    const open = jest.spyOn(Linking, 'openSettings').mockResolvedValue();
    await renderLive();
    expect(await screen.findByTestId('live-denied')).toBeTruthy();
    expect(screen.queryByTestId('live-web')).toBeNull();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('live-settings'));
    });
    expect(open).toHaveBeenCalledTimes(1);
    // Sozlamalardan qaytildi (ruxsat endi bor).
    await act(async () => {
      stateHandlers.forEach((h) => h('active'));
    });
    expect(await screen.findByTestId('live-web')).toBeTruthy();
  });

  it('no session: asks to sign in again, the page is not opened', async () => {
    const services = fakeServices();
    (services.session.getToken as jest.Mock).mockRejectedValueOnce(new Error('auth required'));
    await renderLive(services);
    expect(await screen.findByTestId('live-auth')).toBeTruthy();
    expect(screen.queryByTestId('live-web')).toBeNull();
  });

  it('the page failed to load: retry opens it again', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await act(async () => {
      web.__state.last?.onError();
    });
    expect(await screen.findByTestId('live-failed')).toBeTruthy();
    await act(async () => {
      await fireEvent.press(screen.getByTestId('live-retry'));
    });
    expect(await screen.findByTestId('live-web')).toBeTruthy();
    expect(web.__state.mounts).toBe(2);
  });

  it('app in the background during a call: ends it after the grace period; a quick return keeps it', async () => {
    await renderLive();
    await screen.findByTestId('live-web');
    await message({ type: 'status', status: 'live' });
    jest.useFakeTimers();
    // Qisqa chiqish (tizim oynasi) - qo'ng'iroq davom etadi.
    act(() => stateHandlers.forEach((h) => h('background')));
    act(() => jest.advanceTimersByTime(BACKGROUND_END_MS - 1000));
    act(() => stateHandlers.forEach((h) => h('active')));
    act(() => jest.advanceTimersByTime(BACKGROUND_END_MS * 2));
    expect(web.__inject).not.toHaveBeenCalledWith(END_SCRIPT);
    // Uzoq fonda - tugatiladi.
    act(() => stateHandlers.forEach((h) => h('background')));
    act(() => jest.advanceTimersByTime(BACKGROUND_END_MS));
    expect(web.__inject).toHaveBeenCalledWith(END_SCRIPT);
  });
});
