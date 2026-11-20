/**
 * Plaud ro'yxatidagi "Audio yuklash": sarlavhadagi tugma va bo'sh holatdagi tugma tizim fayl
 * oynasini (expo-document-picker - mock) ochadi, tanlangan fayllar `imports/` ga tushadi va mavjud
 * `/import` tasdiq ekrani ochiladi ("Ulashish -> Barno" bilan bir yo'l). Hech biri qabul
 * qilinmasa - sababi toast'da. Native import yo'q ilovada, qo'ng'iroqlar tabida va bo'lim
 * yoqilmaganda tugma yo'q.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { router } from 'expo-router';
import type { ReactNode } from 'react';

import { ApiError } from '@/api/client';
import MeetingsScreen from '@/app/meetings';
import type { ImportMetaFile, ImportsDir } from '@/features/calls/pickAudio';
import { useAuth } from '@/features/auth/authStore';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import { showToast } from '@/ui/errors';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { card, config, loginResponse } from './fixtures/server';

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
    Stack: { Screen: ({ options }: { options?: { headerRight?: () => ReactNode } }) => (options?.headerRight ? options.headerRight() : null) },
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
  };
});

// Native import bor/yo'q - testdan boshqariladi (tasdiq ekrani `getImportMeta` ga tayanadi).
const mockNative = { available: true };
jest.mock('@/features/entry/nativeEntry', () => ({
  ...jest.requireActual('@/features/entry/nativeEntry'),
  isCallImportAvailable: jest.fn(() => mockNative.available),
}));

// `imports/` - xotirada (expo-file-system o'rniga). Manba mazmuni URI'dan: `mockSources` (bo'lmasa - m4a).
const mockFiles = new Map<string, Uint8Array>();
const mockMetas = new Map<string, ImportMetaFile>();
const mockSources = new Map<string, Uint8Array>();
const mockMp4 = Uint8Array.from([0, 0, 0, 0x20, 0x66, 0x74, 0x79, 0x70, 0x4d, 0x34, 0x41, 0x20]);
const mockMp3 = Uint8Array.from([0x49, 0x44, 0x33, 4, 0, 0, 0, 0, 0x21, 0x76, 0, 0]);
const mockWav = Uint8Array.from([0x52, 0x49, 0x46, 0x46, 0x24, 0x08, 0, 0, 0x57, 0x41, 0x56, 0x45]);
jest.mock('@/features/calls/pickAudio', () => {
  const actual = jest.requireActual('@/features/calls/pickAudio');
  const dir: ImportsDir = {
    exists: (name) => mockFiles.has(name),
    copyIn: async (src, name) => {
      if (src.includes('broken')) throw new Error('ERR_READ');
      const data = mockSources.get(src) ?? mockMp4;
      mockFiles.set(name, data);
      return data.length;
    },
    head: (name, n) => (mockFiles.get(name) ?? new Uint8Array()).slice(0, n),
    writeMeta: (name, meta) => void mockMetas.set(name, meta),
    readMeta: (name) => (mockMetas.has(name) ? { ...mockMetas.get(name) } : null),
    stat: (name) => (mockFiles.has(name) ? { path: `/data/user/0/app/files/imports/${name}`, size: mockFiles.get(name)!.length } : null),
    remove: (name) => void mockFiles.delete(name),
    freeBytes: () => null,
    sweep: () => {},
  };
  return { ...actual, appImportsDir: jest.fn(() => dir) };
});
jest.mock('@/ui/errors', () => ({ ...jest.requireActual('@/ui/errors'), showToast: jest.fn() }));

const Picker = jest.requireMock('expo-document-picker') as { getDocumentAsync: jest.Mock };
const push = router.push as jest.Mock;
const toast = showToast as jest.Mock;

const picked = (assets: { uri: string; name: string; mimeType?: string; size?: number }[]) => ({
  canceled: false,
  assets: assets.map((a) => ({ size: 1000, mimeType: 'audio/mp4', lastModified: 1_700_000_000_000, ...a })),
});

async function renderList(opts: { cards?: boolean; list?: jest.Mock } = {}) {
  const items = opts.cards ? [{ ...card, status: 'ready' as const, progress: null }] : [];
  const meetings = fakeMeetingsApi({ list: opts.list ?? jest.fn(async () => ({ items, limit: 20, offset: 0, total: items.length })) });
  await render(
    <Providers services={{ ...fakeServices({ meetings }), queue: createMemoryQueueStore() }}>
      <MeetingsScreen />
    </Providers>,
  );
  await waitFor(() => expect(meetings.list).toHaveBeenCalled());
}

const press = async (testID: string) => {
  await act(async () => {
    await fireEvent.press(screen.getByTestId(testID));
  });
};

beforeEach(() => {
  mockNative.available = true;
  mockFiles.clear();
  mockMetas.clear();
  mockSources.clear();
  Picker.getDocumentAsync.mockReset();
  Picker.getDocumentAsync.mockResolvedValue({ canceled: true, assets: null });
  useSettings.setState({ uiLang: 'uz', lastLanguage: 'uz' });
  useRecorderStore.setState({ machine: initialRecorderState });
  useAuth.setState({ status: 'signedIn', user: loginResponse.user, config, expired: false });
});

describe('Plaud: Audio yuklash', () => {
  it('header button opens the audio picker (several files, no cache copy) and hands the files to the /import screen', async () => {
    await renderList({ cards: true });
    const btn = await screen.findByTestId('meetings-upload');
    expect(btn.props.accessibilityLabel).toBe('Audio/video yuklash');
    mockSources.set('content://docs/2', mockMp3);
    Picker.getDocumentAsync.mockResolvedValueOnce(
      picked([
        { uri: 'content://docs/1', name: 'Kengash 6-noyabr.m4a' },
        { uri: 'content://docs/2', name: 'Zoom yozuvi.mp3', mimeType: 'audio/mpeg' },
        { uri: 'content://docs/3', name: 'song.flac', mimeType: 'audio/flac' },
      ]),
    );
    await press('meetings-upload');
    // `application/ogg` ham: ba'zi manbalar Opus'ni shunday ataydi.
    expect(Picker.getDocumentAsync).toHaveBeenCalledWith({ type: ['audio/*', 'application/ogg', 'video/*'], multiple: true, copyToCacheDirectory: false });
    expect(push).toHaveBeenCalledTimes(1);
    const path = push.mock.calls[0][0] as string;
    // Ulashish bilan bir xil havola: tekshirilgan nomlar (mp3 ham), qo'shilmaganlar soni, noyob `n`.
    expect(path).toMatch(/^\/import\?files=share_\d+_0_Kengash_6-noyabr\.m4a,share_\d+_1_Zoom_yozuvi\.mp3&skipped=1&n=\d+$/);
    const names = (/files=([^&]+)/.exec(path)?.[1] ?? '').split(',');
    expect(names.every((n) => mockFiles.has(n))).toBe(true);
    expect(mockMetas.get(names[0])).toMatchObject({ displayName: 'Kengash 6-noyabr.m4a', contentType: 'audio/mp4', source: 'share' });
    expect(mockMetas.get(names[1])).toMatchObject({ displayName: 'Zoom yozuvi.mp3', contentType: 'audio/mpeg', source: 'share' });
    expect(toast).not.toHaveBeenCalled();
  });

  it('empty Plaud: "Audio yuklash" sits next to recording; cancelling the picker does nothing', async () => {
    await renderList();
    await waitFor(() => expect(screen.getByTestId('meetings-empty')).toBeTruthy());
    expect(screen.getByTestId('meetings-empty-record')).toBeTruthy();
    expect(screen.getByTestId('meetings-empty-upload')).toHaveTextContent('Audio/video yuklash');
    await press('meetings-empty-upload');
    expect(Picker.getDocumentAsync).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it('nothing acceptable: an honest toast, no empty confirmation screen', async () => {
    await renderList({ cards: true });
    Picker.getDocumentAsync.mockResolvedValueOnce(picked([{ uri: 'content://docs/3', name: 'note.amr', mimeType: 'audio/amr' }]));
    await press('meetings-upload');
    expect(toast).toHaveBeenCalledWith("Audio qo'shilmadi: faqat .m4a, .aac, .mp3, .wav, .ogg audio yoki .mp4, .mov video qabul qilinadi");
    // ".mp3" deyilgan, ichida WAV - mazmun kengaytmaga zid.
    mockSources.set('content://docs/6', mockWav);
    Picker.getDocumentAsync.mockResolvedValueOnce(picked([{ uri: 'content://docs/6', name: 'yozuv.mp3', mimeType: 'audio/mpeg' }]));
    await press('meetings-upload');
    expect(toast).toHaveBeenLastCalledWith("Audio qo'shilmadi: fayl ichidagi format kengaytmasiga mos emas");
    expect(mockFiles.size).toBe(0);
    Picker.getDocumentAsync.mockResolvedValueOnce(picked([{ uri: 'content://broken/4', name: 'a.m4a' }]));
    await press('meetings-upload');
    expect(toast).toHaveBeenLastCalledWith("Audio qo'shilmadi: faylni o'qib bo'lmadi");
    Picker.getDocumentAsync.mockRejectedValueOnce(new Error('Different document picking in progress'));
    await press('meetings-upload');
    expect(toast).toHaveBeenLastCalledWith("Fayl tanlash oynasini ochib bo'lmadi");
    expect(push).not.toHaveBeenCalled();
  });

  it('while files are being prepared: a spinner instead of the button, so the picker is not opened twice', async () => {
    await renderList({ cards: true });
    let finish: (v: unknown) => void = () => {};
    Picker.getDocumentAsync.mockImplementationOnce(() => new Promise((r) => (finish = r)));
    await press('meetings-upload');
    expect(screen.getByTestId('meetings-upload-busy').props.accessibilityLabel).toBe('Fayllar tayyorlanmoqda...');
    expect(screen.queryByTestId('meetings-upload')).toBeNull();
    await act(async () => finish(picked([{ uri: 'content://docs/5', name: 'b.m4a' }])));
    expect(await screen.findByTestId('meetings-upload')).toBeTruthy();
    expect(Picker.getDocumentAsync).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledTimes(1);
  });

  it('not offered without the native import or when the section is not enabled', async () => {
    mockNative.available = false;
    await renderList({ cards: true });
    await waitFor(() => expect(screen.getByTestId('meetings-list')).toBeTruthy());
    expect(screen.queryByTestId('meetings-upload')).toBeNull();
    await screen.unmount();

    mockNative.available = true;
    await renderList({ cards: true });
    expect(await screen.findByTestId('meetings-upload')).toBeTruthy();
    // "Qo'ng'iroqlar" tabi yo'q (ega qarori 2026-11-12) - yuklash tugmasi doim ko'rinadi.
    expect(screen.queryByTestId('meetings-tab-calls')).toBeNull();
    await screen.unmount();

    await renderList({ list: jest.fn(async () => Promise.reject(new ApiError(403, 'forbidden', 'no'))) });
    await waitFor(() => expect(screen.getByTestId('meetings-error')).toBeTruthy());
    expect(screen.queryByTestId('meetings-upload')).toBeNull();
    expect(screen.queryByTestId('meetings-empty-upload')).toBeNull();
  });
});
