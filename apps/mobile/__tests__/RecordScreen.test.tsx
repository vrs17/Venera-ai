/**
 * Record ekrani (RNTL) soxta yozuvchi va soxta servislar bilan: deep link
 * qarori, boshqaruv tugmalari, ogohlantirishlar.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { RecordScreen } from '@/app/record';
import { RecorderActionsProvider, useRecorderStore, type RecorderActions, type StartOptions } from '@/features/recorder/RecorderProvider';
import { initialRecorderState, type RecorderState } from '@/features/recorder/recorderMachine';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeServices, Providers } from './fixtures/fakeServices';

const KEY = 'ab'.repeat(32);

function fakeActions(): jest.Mocked<RecorderActions> {
  return {
    start: jest.fn(async (_opts: StartOptions) => true),
    pause: jest.fn(),
    resume: jest.fn(),
    stop: jest.fn(async (_auto?: boolean): Promise<string | null> => 'c1'),
    mark: jest.fn((_note?: string | null) => {}),
    setLastMarkNote: jest.fn((_note: string) => {}),
    reset: jest.fn(),
  };
}

function setMachine(patch: Partial<RecorderState>, extra: Partial<{ levels: number[]; silent: boolean; lastSavedClientId: string | null }> = {}) {
  // Render'dan OLDIN chaqiriladi - act kerak emas.
  useRecorderStore.setState({ machine: { ...initialRecorderState, ...patch }, levels: [], silent: false, lastSavedClientId: null, ...extra });
}

async function renderRecord(params: Record<string, string>, actions = fakeActions(), onSaved?: (id: string) => void) {
  const services = fakeServices({ installKey: KEY });
  // RNTL 14: render/fireEvent asinxron.
  await render(
    <Providers services={services}>
      <RecorderActionsProvider value={actions}>
        <RecordScreen params={params} onSaved={onSaved} />
      </RecorderActionsProvider>
    </Providers>,
  );
  return { actions, services };
}

beforeEach(() => {
  setMachine({});
  useSettings.setState({ uiLang: 'uz', consentSeen: true, batteryHintSeen: true, lastLanguage: 'uz', lastSpeakers: null });
});

describe('Record screen', () => {
  it('auto-starts from the side key / tile when the trusted key matches', async () => {
    const { actions } = await renderRecord({ src: 'launcher', k: KEY });
    await waitFor(() => expect(actions.start).toHaveBeenCalledTimes(1));
    expect(actions.start).toHaveBeenCalledWith({ language: 'uz', template: 'auto', expectedSpeakers: null, source: 'launcher' });
  });

  it('a foreign link only opens the ready state; the big button starts with the chosen options (template always auto)', async () => {
    const { actions } = await renderRecord({ src: 'tile', k: 'cd'.repeat(32) });
    await act(async () => {});
    expect(actions.start).not.toHaveBeenCalled();
    expect(screen.getByText('Ishtirokchilarni yozib olinayotgani haqida ogohlantiring')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('lang-ru'));
    // Shablon tanlovi yo'q (ega qarori 2026-11-12) - xulosa turini Barno o'zi aniqlaydi.
    expect(screen.queryByTestId('tpl-sales_call')).toBeNull();
    expect(screen.queryByText('Xulosa shabloni')).toBeNull();
    await fireEvent.press(screen.getByTestId('spk-3'));
    await fireEvent.press(screen.getByTestId('record-start'));
    expect(actions.start).toHaveBeenCalledWith({ language: 'ru', template: 'auto', expectedSpeakers: 3, source: 'app' });
  });

  it('shows timer, level bars and controls while recording; Muhim adds a mark with an optional note', async () => {
    setMachine({ status: 'recording', clientId: 'c1', startedAt: Date.now() - 65_000, segmentStartedAt: Date.now() - 65_000, accumulatedMs: 0 });
    const { actions } = await renderRecord({ src: 'app' });
    expect(screen.getByTestId('record-timer').props.children).toMatch(/^01:0[5-6]$/);
    expect(screen.getByText('● Yozilmoqda')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('record-pause'));
    expect(actions.pause).toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId('record-mark'));
    expect(actions.mark).toHaveBeenCalledWith(null);
    await fireEvent.changeText(screen.getByTestId('mark-note'), 'narx bo‘yicha qaror');
    await fireEvent.press(screen.getByTestId('mark-note-save'));
    expect(actions.setLastMarkNote).toHaveBeenCalledWith('narx bo‘yicha qaror');
    await fireEvent.press(screen.getByTestId('record-stop'));
    expect(actions.stop).toHaveBeenCalled();
  });

  it('paused state offers Resume and the timeline does not grow', async () => {
    setMachine({ status: 'paused', clientId: 'c1', startedAt: 1, segmentStartedAt: null, accumulatedMs: 754_000, endedAt: null });
    const { actions } = await renderRecord({ src: 'app' });
    expect(screen.getByTestId('record-timer').props.children).toBe('12:34');
    expect(screen.getByText('Pauzada')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('record-resume'));
    expect(actions.resume).toHaveBeenCalled();
  });

  it('a second trusted link while recording just shows it; action=stop stops', async () => {
    setMachine({ status: 'recording', clientId: 'c1', startedAt: Date.now(), segmentStartedAt: Date.now() });
    const a = await renderRecord({ src: 'tile', k: KEY });
    await act(async () => {});
    expect(a.actions.start).not.toHaveBeenCalled();
    await screen.unmount();
    const b = await renderRecord({ src: 'tile', k: KEY, action: 'stop' });
    await waitFor(() => expect(b.actions.stop).toHaveBeenCalledTimes(1));
  });

  it('warns about a silent microphone and the approaching limit', async () => {
    const now = Date.now();
    setMachine({ status: 'recording', clientId: 'c1', startedAt: now, segmentStartedAt: now - 175 * 60_000, maxSec: 180 * 60 }, { silent: true });
    await renderRecord({ src: 'app' });
    expect(screen.getByTestId('record-silent')).toBeTruthy();
    expect(screen.getByTestId('record-limit')).toBeTruthy();
    expect(screen.getByText(/5 daqiqadan keyin yozuv avtomatik to'xtaydi/)).toBeTruthy();
  });

  it('explains blocking permission errors', async () => {
    setMachine({ status: 'notifications_denied' });
    await renderRecord({ src: 'app' });
    expect(screen.getByTestId('record-error')).toBeTruthy();
    expect(screen.getByText(/Bildirishnomaga ruxsat kerak/)).toBeTruthy();
  });

  it('after Stop on this screen shows "Saqlandi, yuklanmoqda" and hands the clientId on', async () => {
    const onSaved = jest.fn();
    const started = Date.now() - 60_000;
    setMachine({ status: 'recording', clientId: 'c1', startedAt: started, segmentStartedAt: started });
    const { actions } = await renderRecord({ src: 'app' }, fakeActions(), onSaved);
    await act(async () => {
      useRecorderStore.setState((st) => ({ machine: { ...st.machine, status: 'stopped', endedAt: Date.now() + 1, segmentStartedAt: null }, lastSavedClientId: 'c1' }));
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith('c1'));
    expect(actions.reset).toHaveBeenCalled();
    expect(screen.getByTestId('record-saved')).toBeTruthy();
    expect(screen.getByText('Saqlandi, yuklanmoqda')).toBeTruthy();
  });

  it('a stop that happened while the screen was closed does not hijack the next side-key start', async () => {
    // Bildirishnomadagi Stop / limit ro'yxat ekranida bo'lgan: `stopped` + lastSaved qolgan.
    const onSaved = jest.fn();
    setMachine({ status: 'stopped', clientId: 'old', endedAt: Date.now() - 5_000 }, { lastSavedClientId: 'old' });
    const actions = fakeActions();
    actions.reset.mockImplementation(() => useRecorderStore.getState().dispatch({ type: 'RESET' }));
    await renderRecord({ src: 'launcher', k: KEY, n: '1001' }, actions, onSaved);
    await waitFor(() => expect(actions.start).toHaveBeenCalledTimes(1));
    expect(actions.start).toHaveBeenCalledWith(expect.objectContaining({ source: 'launcher' }));
    expect(onSaved).not.toHaveBeenCalled();
    expect(useRecorderStore.getState().lastSavedClientId).toBeNull();
    expect(screen.queryByTestId('record-saved')).toBeNull();
  });

  it('every side-key press carries a new nonce, so a repeated link starts again while the screen stays open', async () => {
    const services = fakeServices({ installKey: KEY });
    const actions = fakeActions();
    const tree = (params: Record<string, string>) => (
      <Providers services={services}>
        <RecorderActionsProvider value={actions}>
          <RecordScreen params={params} />
        </RecorderActionsProvider>
      </Providers>
    );
    await render(tree({ src: 'launcher', k: KEY, n: '1' }));
    await waitFor(() => expect(actions.start).toHaveBeenCalledTimes(1));
    // Xuddi shu intent (re-render) - qayta ishlanmaydi.
    await screen.rerender(tree({ src: 'launcher', k: KEY, n: '1' }));
    await act(async () => {});
    expect(actions.start).toHaveBeenCalledTimes(1);
    // Yangi bosish (masalan, ruxsatni yoqib, yon tugmani qayta bosish) - yana boshlanadi.
    await screen.rerender(tree({ src: 'launcher', k: KEY, n: '2' }));
    await waitFor(() => expect(actions.start).toHaveBeenCalledTimes(2));
  });

  it('explains the not-on-screen start failure and offers a retry', async () => {
    setMachine({ status: 'not_foreground' });
    const { actions } = await renderRecord({ src: 'app' });
    expect(screen.getByText(/ilova ekranda ochiq turishi kerak/)).toBeTruthy();
    await fireEvent.press(screen.getByText('Qayta urinish'));
    expect(actions.start).toHaveBeenCalledWith(expect.objectContaining({ source: 'app' }));
  });

  it('first run shows the consent notice once', async () => {
    useSettings.setState({ consentSeen: false });
    await renderRecord({ src: 'app' });
    expect(screen.getByText('Yozishdan oldin')).toBeTruthy();
    await fireEvent.press(screen.getByText('OK'));
    expect(useSettings.getState().consentSeen).toBe(true);
  });
});
