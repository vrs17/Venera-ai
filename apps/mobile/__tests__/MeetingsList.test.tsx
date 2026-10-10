/**
 * Yozuvlar ro'yxati (spec 3.1): bo'sh holat yozishni o'rgatadi, server va telefondagi
 * yozuvlar bitta vaqt chizig'ida (kunlar bo'yicha), yuklash pill'i sababni aytadi,
 * yozuv ketayotganda jonli karta. Navigatsiya `router` mock orqali tekshiriladi.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { router } from 'expo-router';
import type { ReactNode } from 'react';

import { ApiError } from '@/api/client';
import type { MeetingCard } from '@/api/types';
import MeetingsScreen from '@/app/meetings';
import { localHref } from '@/features/meeting/RecordingCard';
import { useAuth } from '@/features/auth/authStore';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { initialRecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import type { Services } from '@/services';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { card as baseCard } from './fixtures/server';

jest.mock('expo-router', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  return {
    router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn(), back: jest.fn(), canGoBack: jest.fn(() => true) },
    // Sarlavha o'ng tugmasi testda ham chizilsin (navigator yo'q).
    Stack: { Screen: ({ options }: { options?: { headerRight?: () => ReactNode } }) => (options?.headerRight ? options.headerRight() : null) },
    useFocusEffect: (cb: () => void) => React.useEffect(cb, [cb]),
  };
});

const push = router.push as jest.Mock;
const DAY = 24 * 60 * 60 * 1000;

const card = (over: Partial<MeetingCard>): MeetingCard => ({ ...baseCard, ...over });
const row = (over: Partial<QueueRow> & { clientId: string }): QueueRow =>
  newQueueRow({
    fileUri: `file:///doc/recordings/${over.clientId}.aac`,
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'app',
    startedAt: new Date().toISOString(),
    state: 'stopped',
    ...over,
  });

async function renderList(opts: { cards?: MeetingCard[]; rows?: QueueRow[]; list?: jest.Mock } = {}) {
  const meetings = fakeMeetingsApi({
    list: opts.list ?? jest.fn(async () => ({ items: opts.cards ?? [], limit: 20, offset: 0, total: (opts.cards ?? []).length })),
  });
  const services: Services = { ...fakeServices({ meetings }), queue: createMemoryQueueStore(opts.rows ?? []) };
  await render(
    <Providers services={services}>
      <MeetingsScreen />
    </Providers>,
  );
  await waitFor(() => expect(meetings.list).toHaveBeenCalled());
  return { services, meetings };
}

beforeEach(() => {
  useSettings.setState({ uiLang: 'uz' });
  useRecorderStore.setState({ machine: initialRecorderState });
  useAuth.setState({ expired: false });
});

afterEach(() => {
  useRecorderStore.setState({ machine: initialRecorderState });
});

describe('Recordings list', () => {
  it('empty state teaches recording: big record CTA and quick-record setup; no FAB', async () => {
    await renderList();
    await waitFor(() => expect(screen.getByTestId('meetings-empty')).toBeTruthy());
    expect(screen.getByText("Hali yozuv yo'q")).toBeTruthy();
    expect(screen.queryByTestId('record-fab')).toBeNull();
    await fireEvent.press(screen.getByTestId('meetings-empty-record'));
    expect(push).toHaveBeenCalledWith('/record?src=app');
    await fireEvent.press(screen.getByTestId('meetings-empty-quick'));
    expect(push).toHaveBeenCalledWith('/settings/quick');
  });

  it('one timeline grouped by day: server cards, a local offline row, status and task pills', async () => {
    const now = Date.now();
    const ready = card({
      id: 'R'.repeat(32),
      clientId: 'cR',
      title: 'Narxlar va hisobot',
      status: 'ready',
      progress: null,
      overview: "Aziz narxlarni ko'rib chiqdi.",
      openActionItems: 3,
      recordedAt: new Date(now - 60_000).toISOString(),
    });
    const processing = card({ id: 'P'.repeat(32), clientId: 'cP', title: 'Kechagi', recordedAt: new Date(now - DAY).toISOString() });
    // Tarmoq xatosi, holat noma'lum (Jest) -> "Internet yo'q".
    const offline = row({ clientId: 'loc1', lastError: 'network', durationSec: 192, startedAt: new Date(now).toISOString() });
    await renderList({ cards: [ready, processing], rows: [offline] });

    await waitFor(() => expect(screen.getByTestId(`meeting-${'R'.repeat(32)}`)).toBeTruthy());
    expect(screen.getByText('Bugun')).toBeTruthy();
    expect(screen.getByText('Kecha')).toBeTruthy();

    const local = screen.getByTestId('local-loc1');
    expect(within(local).getByText("Internet yo'q")).toBeTruthy();
    expect(within(local).getByText('03:12')).toBeTruthy();
    expect(within(local).getByText(/^Yozuv, \d\d:\d\d$/)).toBeTruthy();

    const readyCard = screen.getByTestId(`meeting-${'R'.repeat(32)}`);
    expect(within(readyCard).getByText('3 vazifa')).toBeTruthy();
    expect(within(readyCard).getByText("Aziz narxlarni ko'rib chiqdi.")).toBeTruthy();
    expect(within(readyCard).queryByText('Tayyor')).toBeNull(); // tayyor bo'lsa holat pill'i yo'q
    // Ishlov holati va foiz - BITTA matn.
    expect(within(screen.getByTestId(`meeting-${'P'.repeat(32)}`)).getByText("Matnga o'girilmoqda 42%")).toBeTruthy();

    await fireEvent.press(local);
    expect(push).toHaveBeenLastCalledWith('/meeting/loc1?local=1');
    // Server id bor, lekin server kartasi yo'q (internet yo'q) - baribir telefondagi sahifa (ijro etiladi).
    expect(localHref(row({ clientId: 'x1', serverId: 'S'.repeat(32), state: 'uploading' }))).toBe('/meeting/x1?local=1');
    await fireEvent.press(readyCard);
    expect(push).toHaveBeenLastCalledWith(`/meeting/${'R'.repeat(32)}`);
    await fireEvent.press(screen.getByTestId('record-fab'));
    expect(push).toHaveBeenLastCalledWith('/record?src=app');
    await fireEvent.press(screen.getByTestId('meetings-tasks'));
    expect(push).toHaveBeenLastCalledWith('/action-items');
  });

  it('a server card shows its unfinished upload instead of the server status (one card per recording)', async () => {
    const c = card({ id: 'U'.repeat(32), clientId: 'cU', status: 'uploading', progress: null, title: 'Yuklanayotgan' });
    const uploading = row({ clientId: 'cU', serverId: 'U'.repeat(32), state: 'uploading', receivedBytes: 30, totalBytes: 100 });
    await renderList({ cards: [c], rows: [uploading] });
    const el = await waitFor(() => screen.getByTestId(`meeting-${'U'.repeat(32)}`));
    expect(within(el).getByText('Yuklanmoqda 30%')).toBeTruthy();
    expect(screen.queryByTestId('local-cU')).toBeNull();
  });

  it('while recording: live card with the clock opens the recorder; its row and the FAB are hidden', async () => {
    const at = Date.now() - 65_000;
    useRecorderStore.setState({ machine: { ...initialRecorderState, status: 'recording', clientId: 'live1', startedAt: at, segmentStartedAt: at } });
    const live = row({ clientId: 'live1', state: 'recording' });
    const other = row({ clientId: 'old1', lastError: 'timeout', startedAt: new Date(Date.now() - 5 * 60_000).toISOString() });
    await renderList({ rows: [live, other] });
    await waitFor(() => expect(screen.getByTestId('local-old1')).toBeTruthy());
    expect(screen.getByTestId('meetings-live')).toHaveTextContent(/Yozilmoqda 01:0\d/);
    expect(screen.queryByTestId('local-live1')).toBeNull();
    expect(screen.queryByTestId('record-fab')).toBeNull();
    expect(screen.queryByTestId('meetings-empty')).toBeNull();
    expect(within(screen.getByTestId('local-old1')).getByText('Qayta urinadi')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('meetings-live'));
    expect(push).toHaveBeenLastCalledWith('/record?src=app');
  });

  it('search: the server gets q, local rows are filtered by title, no results says so', async () => {
    const list = jest.fn(async ({ q }: { q?: string }) => ({ items: q ? [] : [card({ title: 'Narxlar' })], limit: 20, offset: 0, total: q ? 0 : 1 }));
    await renderList({ list, rows: [row({ clientId: 'n1', title: "Ko'rik" })] });
    await waitFor(() => expect(screen.getByTestId('local-n1')).toBeTruthy());
    await fireEvent.changeText(screen.getByTestId('meetings-search'), 'KO’RIK');
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ q: 'KO’RIK' })));
    expect(screen.getByTestId('local-n1')).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('meetings-search'), 'yoq narsa');
    await waitFor(() => expect(screen.getByTestId('meetings-no-results')).toBeTruthy());
    expect(screen.queryByTestId('local-n1')).toBeNull();
    expect(screen.queryByTestId('meetings-empty')).toBeNull();
  });

  it('feature disabled (403): one honest "not enabled" state - no "no recordings yet", no record CTA', async () => {
    const list = jest.fn(async () => {
      throw new ApiError(403, 'forbidden', 'no');
    });
    await renderList({ list });
    await waitFor(() => expect(screen.getByTestId('meetings-error')).toBeTruthy());
    expect(screen.getByText('Bu funksiya siz uchun hali yoqilmagan')).toBeTruthy();
    expect(screen.getByText('Administratorga murojaat qiling.')).toBeTruthy();
    expect(screen.queryByTestId('meetings-empty')).toBeNull();
    expect(screen.queryByTestId('meetings-empty-record')).toBeNull();
    expect(screen.queryByTestId('record-fab')).toBeNull();
    expect(screen.queryByTestId('meetings-search')).toBeNull();
  });

  it('list failed (offline/5xx) with nothing local: says it failed, retry works, recording stays offered', async () => {
    let fail = true;
    const list = jest.fn(async () => {
      if (fail) throw new ApiError(0, 'network', 'offline');
      return { items: [card({ title: 'Narxlar' })], limit: 20, offset: 0, total: 1 };
    });
    await renderList({ list });
    await waitFor(() => expect(screen.getByTestId('meetings-error')).toBeTruthy());
    expect(screen.getByText("Yozuvlarni yuklab bo'lmadi")).toBeTruthy();
    // "Hali yozuv yo'q" yolg'on bo'lardi - yozuvlar bor, faqat kelmadi.
    expect(screen.queryByText("Hali yozuv yo'q")).toBeNull();
    // Yozish internetsiz ham ishlaydi - tugma qoladi.
    expect(screen.getByTestId('record-fab')).toBeTruthy();
    fail = false;
    await fireEvent.press(screen.getByTestId('meetings-retry'));
    await waitFor(() => expect(screen.getByText('Narxlar')).toBeTruthy());
    expect(screen.queryByTestId('meetings-error')).toBeNull();
  });

  it('list failed but local rows exist: a small banner above them, not the big state', async () => {
    const list = jest.fn(async () => {
      throw new ApiError(0, 'network', 'offline');
    });
    await renderList({ list, rows: [row({ clientId: 'loc1', lastError: 'network' })] });
    await waitFor(() => expect(screen.getByTestId('meetings-error')).toBeTruthy());
    expect(screen.getByTestId('local-loc1')).toBeTruthy();
    expect(screen.queryByText("Yozuvlarni yuklab bo'lmadi")).toBeNull();
  });

  it('pull to refresh also nudges the uploader', async () => {
    const { services, meetings } = await renderList({ cards: [card({})] });
    const list = screen.getByTestId('meetings-list');
    await act(async () => {
      await list.props.refreshControl.props.onRefresh();
    });
    expect(services.uploader.runOnce).toHaveBeenCalled();
    expect((meetings.list as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
