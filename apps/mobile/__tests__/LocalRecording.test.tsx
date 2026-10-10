/**
 * Telefondagi (hali yuklanmagan) yozuv sahifasi (spec 3.3-3.4): telefondagi faylni
 * ijro etadi, yuklash kartasi sababni va to'g'ri amalni ko'rsatadi (qayta urinish,
 * qayta kirish, o'chirish), yuklash tugagach server sahifasiga o'tadi. Server
 * yig'ilishi audio hali yo'q paytda ham telefondagi faylni ijro etadi.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import * as ExpoAudio from 'expo-audio';
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Alert, type AlertButton } from 'react-native';

import { ApiError } from '@/api/client';
import MeetingRoute from '@/app/meeting/[id]';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import type { Services } from '@/services';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { meeting } from './fixtures/server';

const mockParams: { id: string; local?: string } = { id: 'c1', local: '1' };

jest.mock('expo-router', () => ({
  router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
  Stack: { Screen: ({ options }: { options?: { headerRight?: () => ReactNode } }) => (options?.headerRight ? options.headerRight() : null) },
  useLocalSearchParams: () => mockParams,
}));

const player = (ExpoAudio as unknown as { __player: Record<string, jest.Mock> }).__player;
const SID = 'a'.repeat(32);
const FILE = 'file:///doc/recordings/c1.aac';

const row = (over: Partial<QueueRow> = {}): QueueRow =>
  newQueueRow({
    clientId: 'c1',
    fileUri: FILE,
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'app',
    startedAt: '2026-10-10T09:05:00Z',
    state: 'stopped',
    durationSec: 192,
    ...over,
  });

async function open(r: QueueRow | null, opts: { fileSize?: number | null; meetings?: ReturnType<typeof fakeMeetingsApi>; tokenFails?: boolean } = {}) {
  const queue = createMemoryQueueStore(r ? [r] : []);
  const base = fakeServices(opts.meetings ? { meetings: opts.meetings } : {});
  if (opts.tokenFails) (base.session.getToken as jest.Mock).mockRejectedValue(new Error('offline'));
  const files = { size: jest.fn(async () => (opts.fileSize === undefined ? 4096 : opts.fileSize)), read: jest.fn(), remove: jest.fn(async () => {}) };
  const services: Services = { ...base, queue, files };
  await render(
    <Providers services={services}>
      <MeetingRoute />
    </Providers>,
  );
  return { services, queue, files };
}

async function pressAlertButton(text: string) {
  const call = (Alert.alert as jest.Mock).mock.calls.at(-1);
  const btn = (call?.[2] as AlertButton[] | undefined)?.find((b) => b.text === text);
  expect(btn).toBeTruthy();
  await act(async () => {
    await btn?.onPress?.();
  });
}

beforeEach(() => {
  mockParams.id = 'c1';
  mockParams.local = '1';
  useSettings.setState({ uiLang: 'uz' });
  useRecorderStore.setState({ machine: initialRecorderState });
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
});

afterEach(() => {
  (Alert.alert as jest.Mock).mockRestore?.();
});

describe('Local recording (not uploaded yet)', () => {
  it('plays the file from the phone with the full player; offline says so honestly', async () => {
    await open(row({ lastError: 'network' }));
    await waitFor(() => expect(screen.getByTestId('player-dock')).toBeTruthy());
    expect(screen.getByTestId('meeting-title')).toHaveTextContent('Yozuv, 14:05');
    expect(screen.getByText('10-oktyabr, 14:05')).toBeTruthy();

    const src = (ExpoAudio.useAudioPlayer as jest.Mock).mock.calls.at(-1)[0];
    expect(src).toEqual({ uri: FILE });
    expect(screen.getByTestId('player-local')).toBeTruthy();

    const card = screen.getByTestId('upload-card');
    expect(within(card).getByText("Internet yo'q")).toBeTruthy();
    expect(within(card).getByText("Yozuv telefonda saqlangan. Internet qaytsa o'zi yuklanadi.")).toBeTruthy();
    expect(screen.queryByTestId('upload-action')).toBeNull(); // tarmoq qaytsa o'zi - tugma kerak emas
    expect(screen.getByText('Xulosa yuklangandan keyin')).toBeTruthy();
    // Eski yolg'on va'da yo'q.
    expect(screen.queryByText(/Internet bo'lganda o'zi yuklanadi/)).toBeNull();

    await fireEvent.press(screen.getByTestId('player-play'));
    expect(player.play).toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId('player-fwd'));
    expect(player.seekTo).toHaveBeenLastCalledWith(15);
    await fireEvent.press(screen.getByTestId('player-speed'));
    expect(player.setPlaybackRate).toHaveBeenLastCalledWith(1.25);
    expect(screen.getByTestId('player-speed')).toHaveTextContent('1.25x');
    await fireEvent(screen.getByTestId('player-track'), 'accessibilityAction', { nativeEvent: { actionName: 'increment' } });
    expect(player.seekTo).toHaveBeenLastCalledWith(15);
  });

  it('failed: retry and delete (delete removes the row and the file, then goes back)', async () => {
    const { services, queue, files } = await open(row({ state: 'failed', lastError: 'too_large' }));
    await waitFor(() => expect(screen.getByTestId('upload-card')).toBeTruthy());
    expect(screen.getByText("Yuklab bo'lmadi")).toBeTruthy();
    expect(screen.getByText('Fayl juda katta')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('upload-action'));
    expect(services.uploader.retry).toHaveBeenCalledWith('c1');

    await fireEvent.press(screen.getByTestId('upload-delete'));
    expect(Alert.alert).toHaveBeenLastCalledWith("O'chirish", "Yozuv hali yuklanmagan. O'chirilsa, qaytarib bo'lmaydi.", expect.any(Array));
    await pressAlertButton("O'chirish");
    await waitFor(() => expect(router.back).toHaveBeenCalled());
    expect(queue.rows.size).toBe(0);
    expect(files.remove).toHaveBeenCalledWith(FILE);
  });

  it('server down: names the retry time and offers "try now"', async () => {
    const at = Date.parse('2099-01-01T07:30:00Z'); // 12:30 Toshkent
    const { services } = await open(row({ lastError: 'timeout', nextAttemptAt: at }));
    await waitFor(() => expect(screen.getByText('Server javob bermayapti')).toBeTruthy());
    expect(screen.getByText('Yozuv telefonda saqlangan. 12:30 da yana urinamiz.')).toBeTruthy();
    expect(screen.getByTestId('upload-action')).toHaveTextContent('Hozir urinish');
    await fireEvent.press(screen.getByTestId('upload-action'));
    expect(services.uploader.retry).toHaveBeenCalledWith('c1');
  });

  it('feature off: says it is not enabled (waiting will not help)', async () => {
    await open(row({ lastError: 'forbidden' }));
    await waitFor(() => expect(screen.getByText('Yuklash yoqilmagan')).toBeTruthy());
    expect(screen.getByTestId('upload-action')).toHaveTextContent('Qayta urinish');
  });

  it('signed out: "sign in again" logs out but keeps the queue', async () => {
    const { services, queue } = await open(row({ lastError: 'auth_required' }));
    await waitFor(() => expect(screen.getByText('Qayta kirish kerak')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('upload-action'));
    await pressAlertButton('Qayta kirish');
    expect(services.session.logout).toHaveBeenCalled();
    expect(queue.rows.size).toBe(1);
  });

  it('uploading shows the percent and a progress bar', async () => {
    await open(row({ state: 'uploading', receivedBytes: 42, totalBytes: 100, serverId: null }));
    await waitFor(() => expect(screen.getByText('Yuklanmoqda 42%')).toBeTruthy());
    expect(screen.getByTestId('upload-progress')).toBeTruthy();
  });

  it('while recording: no player, the card opens the recorder, delete is disabled', async () => {
    await open(row({ state: 'recording' }));
    await waitFor(() => expect(screen.getByTestId('upload-card')).toBeTruthy());
    expect(screen.queryByTestId('player-dock')).toBeNull();
    expect(screen.getByTestId('meeting-menu')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('upload-action'));
    expect(router.push).toHaveBeenCalledWith('/record?src=app');
  });

  it('missing file: says so instead of a dead player', async () => {
    await open(row({ lastError: 'network' }), { fileSize: null });
    await waitFor(() => expect(screen.getByTestId('player-note')).toHaveTextContent('Telefondagi fayl topilmadi'));
    expect(screen.queryByTestId('player-dock')).toBeNull();
  });

  it('⋮ menu deletes after confirmation', async () => {
    const { queue } = await open(row());
    await waitFor(() => expect(screen.getByTestId('meeting-menu')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('meeting-menu'));
    await fireEvent.press(screen.getByTestId('menu-delete'));
    await waitFor(() => expect(Alert.alert).toHaveBeenCalled());
    await pressAlertButton("O'chirish");
    await waitFor(() => expect(queue.rows.size).toBe(0));
    expect(router.back).toHaveBeenCalled();
  });

  it('switches to the server page once the upload is done', async () => {
    const { queue } = await open(row({ state: 'uploading', serverId: SID, receivedBytes: 10, totalBytes: 100 }));
    await waitFor(() => expect(screen.getByTestId('upload-card')).toBeTruthy());
    await act(async () => {
      await queue.update('c1', { state: 'done' });
    });
    await waitFor(() => expect(screen.getByTestId('meeting-title')).toHaveTextContent("Yig'ilish 9-oktyabr, 11:00"));
    expect(screen.getByTestId('tab-summary')).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
  });
});

describe('Playback is stable for the whole visit', () => {
  const status = ExpoAudio.useAudioPlayerStatus as jest.Mock;
  afterEach(() => {
    status.mockReturnValue({ currentTime: 0, duration: 120, playing: false, isLoaded: true, playbackRate: 1 });
  });

  it('upload finishing mid-listen does not stop, swap or restart the player', async () => {
    const { queue } = await open(row({ state: 'uploading', serverId: SID, receivedBytes: 10, totalBytes: 100 }));
    await waitFor(() => expect(screen.getByTestId('player-dock')).toBeTruthy());
    const dock = screen.getByTestId('player-dock');
    await fireEvent.press(screen.getByTestId('player-play'));
    // Ijro ketmoqda (00:42): pleer shu holatni xabar qiladi va manba qulflanadi.
    status.mockReturnValue({ currentTime: 42, duration: 192, playing: true, isLoaded: true, playbackRate: 1 });
    await act(async () => {
      await queue.update('c1', { state: 'uploading', receivedBytes: 99 });
    });
    const useAudioPlayer = ExpoAudio.useAudioPlayer as jest.Mock;
    useAudioPlayer.mockClear();
    player.play.mockClear();
    player.seekTo.mockClear();

    await act(async () => {
      await queue.update('c1', { state: 'done' });
    });
    // Server sahifasi (xulosa) ochildi...
    await waitFor(() => expect(screen.getByTestId('tab-summary')).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
    // ...lekin pleer O'SHA: qayta yaratilmagan, server manbasiga almashmagan, 0:00 ga qaytmagan.
    expect(screen.getByTestId('player-dock')).toBe(dock);
    expect(screen.getByTestId('player-local')).toBeTruthy();
    for (const call of useAudioPlayer.mock.calls) expect(call[0]).toEqual({ uri: FILE });
    expect(player.seekTo).not.toHaveBeenCalled();
    expect(player.play).not.toHaveBeenCalled();
  });

  it('a copy on the phone is preferred over server audio (instant, works offline)', async () => {
    mockParams.id = SID;
    mockParams.local = undefined;
    // Server audio tayyor, telefonda 7 kunlik nusxa ham bor.
    await open(row({ serverId: SID, state: 'done', clientId: '6f1c2a3b-1111-4222-8333-444455556666' }));
    await waitFor(() => expect(screen.getByTestId('player-dock')).toBeTruthy());
    expect((ExpoAudio.useAudioPlayer as jest.Mock).mock.calls.at(-1)[0]).toEqual({ uri: FILE });
    expect(screen.getByTestId('player-local')).toBeTruthy();
  });
});

describe('Detail page edge states', () => {
  it('server page offline, file on the phone: local page with the cause, player still works', async () => {
    mockParams.id = SID;
    mockParams.local = undefined;
    const meetings = fakeMeetingsApi({
      get: jest.fn(async () => {
        throw new ApiError(0, 'network', 'offline');
      }),
    });
    await open(row({ serverId: SID, state: 'done', clientId: '6f1c2a3b-1111-4222-8333-444455556666' }), { meetings });
    await waitFor(() => expect(screen.getByTestId('local-server-failed')).toBeTruthy());
    expect(within(screen.getByTestId('local-server-failed')).getByText("Internet yo'q")).toBeTruthy();
    expect(screen.getByTestId('player-dock')).toBeTruthy();
    expect((ExpoAudio.useAudioPlayer as jest.Mock).mock.calls.at(-1)[0]).toEqual({ uri: FILE });
    // Yuklangan yozuv: "hali yuklanmagan" o'chirish menyusi yo'q.
    expect(screen.queryByTestId('meeting-menu')).toBeNull();
  });

  it('server page offline, nothing on the phone: the error names the cause', async () => {
    mockParams.id = SID;
    mockParams.local = undefined;
    const meetings = fakeMeetingsApi({
      get: jest.fn(async () => {
        throw new ApiError(0, 'network', 'offline');
      }),
    });
    await open(null, { meetings });
    await waitFor(() => expect(screen.getByText("Internet yo'q")).toBeTruthy());
    expect(screen.queryByTestId('player-dock')).toBeNull();
  });

  it('server audio but no token (offline, session gone): the dock says so instead of vanishing', async () => {
    mockParams.id = SID;
    mockParams.local = undefined;
    await open(null, { tokenFails: true });
    await waitFor(() => expect(screen.getByTestId('player-error')).toHaveTextContent('Audio yuklanmadi - internetni tekshiring'));
    expect(screen.queryByTestId('player-dock')).toBeNull();
  });

  it('a link to a recording that is gone: "not found" with a way out, not an endless spinner', async () => {
    await open(null);
    await waitFor(() => expect(screen.getByTestId('recording-not-found')).toBeTruthy());
    expect(screen.getByText('Yozuv topilmadi')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('recording-not-found-back'));
    expect(router.back).toHaveBeenCalled();
  });

  it('feature off: no "summary after upload" promise under the honest card', async () => {
    await open(row({ lastError: 'forbidden' }));
    await waitFor(() => expect(screen.getByText('Yuklash yoqilmagan')).toBeTruthy());
    expect(screen.queryByText('Xulosa yuklangandan keyin')).toBeNull();
  });
});

describe('Deleting a server meeting with an unfinished local upload', () => {
  beforeEach(() => {
    mockParams.id = SID;
    mockParams.local = undefined;
  });
  const uploading = () =>
    meeting({
      status: 'uploading',
      upload: { receivedBytes: 10, totalBytes: 100, maxChunkBytes: 4194304, complete: false },
      audioAvailable: false,
      transcript: { ...meeting().transcript, available: false },
      summaryStatus: 'none',
      primarySummaryId: null,
    });

  async function deleteViaMenu() {
    await waitFor(() => expect(screen.getByTestId('meeting-menu')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('meeting-menu'));
    await fireEvent.press(screen.getByTestId('menu-delete'));
    await waitFor(() => expect(Alert.alert).toHaveBeenCalled());
    await pressAlertButton("O'chirish");
  }

  it('server delete fails (offline): the only full copy on the phone is kept', async () => {
    const meetings = fakeMeetingsApi({
      get: jest.fn(async () => uploading()),
      remove: jest.fn(async () => {
        throw new ApiError(0, 'network', 'offline');
      }),
    });
    const { queue, files } = await open(row({ serverId: SID, state: 'uploading', clientId: '6f1c2a3b-1111-4222-8333-444455556666' }), { meetings });
    await deleteViaMenu();
    await waitFor(() => expect(meetings.remove).toHaveBeenCalledWith(SID));
    expect(queue.rows.size).toBe(1);
    expect(files.remove).not.toHaveBeenCalled();
  });

  it('server delete succeeds: the phone copy goes too (no resurrection), then leaves', async () => {
    const meetings = fakeMeetingsApi({ get: jest.fn(async () => uploading()) });
    const { queue, files } = await open(row({ serverId: SID, state: 'uploading', clientId: '6f1c2a3b-1111-4222-8333-444455556666' }), { meetings });
    await deleteViaMenu();
    await waitFor(() => expect(queue.rows.size).toBe(0));
    expect(files.remove).toHaveBeenCalledWith(FILE);
    await waitFor(() => expect(router.back).toHaveBeenCalled());
  });
});

describe('Server meeting whose audio is not on the server yet', () => {
  beforeEach(() => {
    mockParams.id = SID;
    mockParams.local = undefined;
  });

  it('plays the local file and shows the upload card', async () => {
    const meetings = fakeMeetingsApi({
      get: jest.fn(async () =>
        meeting({
          status: 'uploading',
          upload: { receivedBytes: 10, totalBytes: 100, maxChunkBytes: 4194304, complete: false },
          audioAvailable: false,
          transcript: { ...meeting().transcript, available: false },
          summaryStatus: 'none',
          primarySummaryId: null,
        }),
      ),
    });
    await open(row({ serverId: SID, lastError: 'network', clientId: '6f1c2a3b-1111-4222-8333-444455556666' }), { meetings });
    await waitFor(() => expect(screen.getByTestId('player-dock')).toBeTruthy());
    expect((ExpoAudio.useAudioPlayer as jest.Mock).mock.calls.at(-1)[0]).toEqual({ uri: FILE });
    expect(screen.getByTestId('upload-card')).toBeTruthy();
    expect(screen.getByText("Internet yo'q")).toBeTruthy();
    // Kartadagi sabab yetarli - sarlavhada "Yuklanmoqda" takrorlanmaydi.
    expect(screen.queryByText('Yuklanmoqda')).toBeNull();
  });

  it('expired server audio + local copy: plays the copy, no "only text left" banner', async () => {
    const meetings = fakeMeetingsApi({ get: jest.fn(async () => meeting({ audioAvailable: false })) });
    await open(row({ serverId: SID, state: 'done', clientId: '6f1c2a3b-1111-4222-8333-444455556666' }), { meetings });
    await waitFor(() => expect(screen.getByTestId('player-dock')).toBeTruthy());
    expect((ExpoAudio.useAudioPlayer as jest.Mock).mock.calls.at(-1)[0]).toEqual({ uri: FILE });
    expect(screen.queryByText("Audio saqlash muddati tugagan - faqat matn qoldi")).toBeNull();
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
  });

  it('expired server audio without a copy: banner, no player', async () => {
    const meetings = fakeMeetingsApi({ get: jest.fn(async () => meeting({ audioAvailable: false })) });
    await open(null, { meetings });
    await waitFor(() => expect(screen.getByText("Audio saqlash muddati tugagan - faqat matn qoldi")).toBeTruthy());
    expect(screen.queryByTestId('player-dock')).toBeNull();
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
  });
});
