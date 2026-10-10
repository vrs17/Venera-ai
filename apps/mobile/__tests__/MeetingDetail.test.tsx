/**
 * Yig'ilish sahifasi (RNTL, expo-router testing-library) soxta API bilan:
 * xulosa bo'limlari, transkript dialogi, vazifalar, savol, banner va
 * tahrirlash oqimlari. Tarmoqqa chiqmaydi.
 */
import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import { Stack } from 'expo-router';
import { renderRouter } from 'expo-router/testing-library';
import type { ReactNode } from 'react';
import { Alert, Share, Text, type AlertButton } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as ExpoAudio from 'expo-audio';

import MeetingRoute from '@/app/meeting/[id]';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { meeting, summary, transcript } from './fixtures/server';

const ID = 'a'.repeat(32);

async function open(api = fakeMeetingsApi(), opts: { withHeader?: boolean } = {}) {
  const services = fakeServices({ meetings: api });
  const wrapper = ({ children }: { children: ReactNode }) => <Providers services={services}>{children}</Providers>;
  // Sarlavha (⋮ menyusi) faqat Stack ichida chiziladi.
  const routes: Record<string, () => ReactNode> = { 'meeting/[id]': MeetingRoute };
  if (opts.withHeader) {
    routes._layout = () => <Stack />;
    routes.meetings = () => <Text>meetings-screen</Text>;
  }
  await renderRouter(routes, { initialUrl: `/meeting/${ID}`, wrapper });
  await waitFor(() => expect(screen.getByTestId('meeting-title')).toBeTruthy());
  return { api, services };
}

const player = (ExpoAudio as unknown as { __player: Record<string, jest.Mock> }).__player;

beforeEach(() => {
  useSettings.setState({ uiLang: 'uz' });
});

describe('Meeting detail', () => {
  it('shows the header, player and the Plaud-superset summary sections in layout order', async () => {
    const { api } = await open();
    expect(screen.getByText(/Yig'ilish 9-oktyabr, 11:00/)).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
    for (const key of ['overview', 'actionItems', 'decisions', 'topics', 'openQuestions', 'risks', 'numbers', 'dates', 'nextSteps', 'nextMeeting', 'highlights', 'participants', 'keyPoints', 'keywords', 'sentiment', 'objections']) {
      expect(screen.getByTestId(`section-${key}`)).toBeTruthy();
    }
    expect(screen.getByText("Aziz narxlarni ko'rib chiqdi. 2-ishtirokchi hisobot yuboradi. Aziz rozi bo'ldi.")).toBeTruthy();
    expect(screen.getAllByText('tekshiring').length).toBeGreaterThan(0);
    // Xulosa ostida - qaysi model yozgani (server `generatedBy`).
    expect(screen.getByTestId('summary-provenance')).toHaveTextContent('Tayyorladi: Gemma');
    expect(api.summary).toHaveBeenCalledWith(ID, 'b'.repeat(32));
    // Pleer audio'ni Bearer bilan oladi.
    await waitFor(() => expect(ExpoAudio.useAudioPlayer).toHaveBeenCalled());
    const src = (ExpoAudio.useAudioPlayer as jest.Mock).mock.calls.at(-1)[0];
    expect(src).toEqual({ uri: `https://x.uz/api/v1/meetings/${ID}/audio`, headers: { Authorization: 'Bearer jwt', 'X-Venera-Client': 'mobile' } });
  });

  it('evidence chips seek the player; suggested names can be accepted', async () => {
    const { api } = await open();
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
    await fireEvent.press(screen.getAllByTestId('ev-9.5')[0]);
    const player = (ExpoAudio as unknown as { __player: { seekTo: jest.Mock } }).__player;
    await waitFor(() => expect(player.seekTo).toHaveBeenCalledWith(9.5));
    await fireEvent.press(screen.getByText('Ha'));
    await waitFor(() => expect(api.renameSpeaker).toHaveBeenCalledWith(ID, 'S2', 'Dilnoza'));
  });

  it('copies the summary as text and shares Markdown from the server export', async () => {
    const share = jest.spyOn(Share, 'share').mockResolvedValue({ action: 'sharedAction' });
    const { api } = await open();
    await waitFor(() => expect(screen.getByTestId('summary-copy')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('summary-copy'));
    const copied = (Clipboard.setStringAsync as jest.Mock).mock.calls[0][0] as string;
    expect(copied).toContain('Narxlar va hisobot');
    expect(copied).toContain('## Vazifalar');
    await fireEvent.press(screen.getByTestId('summary-share'));
    await waitFor(() => expect(share).toHaveBeenCalledWith({ message: '# Narxlar', title: 'Narxlar va hisobot' }));
    expect(api.exportSummary).toHaveBeenCalledWith(ID, 'b'.repeat(32), 'md');
  });

  it('summary written by v3 says "Tayyorladi: Barno Core"; no caption when the server does not say', async () => {
    const v3 = fakeMeetingsApi({ summary: jest.fn(async () => summary({ generatedBy: { provider: 'v3', model: 'venera-core' } })) });
    await open(v3);
    await waitFor(() => expect(screen.getByTestId('summary-provenance')).toHaveTextContent('Tayyorladi: Barno Core'));
  });

  it('no provenance caption for an old summary without generatedBy', async () => {
    await open(fakeMeetingsApi({ summary: jest.fn(async () => summary({ generatedBy: null })) }));
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
    expect(screen.queryByTestId('summary-provenance')).toBeNull();
  });

  it('creates a new summary tab from another template', async () => {
    const { api } = await open();
    await waitFor(() => expect(screen.getByTestId('summary-new')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('summary-new'));
    await fireEvent.press(screen.getByText('Bayonnoma'));
    await waitFor(() => expect(api.createSummary).toHaveBeenCalledWith(ID, { template: 'minutes', makePrimary: true }));
  });

  it('transcript tab is a chat-like dialog grouped by speaker; rename works', async () => {
    const { api } = await open();
    await fireEvent.press(screen.getByTestId('tab-transcript'));
    await waitFor(() => expect(screen.getByTestId('bubble-b1')).toBeTruthy());
    expect(screen.getByText("Assalomu alaykum, boshlaymiz. Bugun narxlarni ko'ramiz.")).toBeTruthy();
    expect(screen.getByTestId('bubble-b3')).toBeTruthy();
    expect(screen.queryByTestId('bubble-b2')).toBeNull(); // 1-2 segmentlar bitta pufakchada
    // S3 S1 ga birlashtirilgan - chiplar qatorida ko'rinmaydi.
    expect(screen.getByTestId('speaker-S1')).toBeTruthy();
    expect(screen.queryByTestId('speaker-S3')).toBeNull();
    await fireEvent.press(screen.getByTestId('speaker-S2'));
    await fireEvent.press(screen.getByText("Nomini o'zgartirish"));
    await fireEvent.changeText(screen.getByTestId('prompt-input'), 'Dilnoza');
    await fireEvent.press(screen.getByTestId('prompt-save'));
    await waitFor(() => expect(api.renameSpeaker).toHaveBeenCalledWith(ID, 'S2', 'Dilnoza'));
  });

  it('transcript search filters bubbles', async () => {
    await open();
    await fireEvent.press(screen.getByTestId('tab-transcript'));
    await waitFor(() => expect(screen.getByTestId('bubble-b1')).toBeTruthy());
    await fireEvent.changeText(screen.getByTestId('transcript-search'), 'hisobot');
    await waitFor(() => expect(screen.queryByTestId('bubble-b1')).toBeNull());
    expect(screen.getByTestId('bubble-b3')).toBeTruthy();
  });

  it('action items tab: check off and add a manual item', async () => {
    const { api } = await open();
    await fireEvent.press(screen.getByTestId('tab-actions'));
    await waitFor(() => expect(screen.getByTestId(`ai-check-${'c'.repeat(32)}`)).toBeTruthy());
    expect(screen.getByText('2-ishtirokchi')).toBeTruthy(); // mas'ul bo'yicha guruh
    await fireEvent.press(screen.getByTestId(`ai-check-${'c'.repeat(32)}`));
    await waitFor(() => expect(api.patchActionItem).toHaveBeenCalledWith(ID, 'c'.repeat(32), { status: 'done' }));
    await fireEvent.press(screen.getByTestId('ai-add'));
    await fireEvent.changeText(screen.getByTestId('ai-task'), 'Shartnoma yuborish');
    await fireEvent.press(screen.getByTestId('ai-submit'));
    await waitFor(() => expect(api.addActionItem).toHaveBeenCalledWith(ID, { task: 'Shartnoma yuborish', ownerName: null, dueDate: null }));
  });

  it('ask tab: sends a question and shows grounded answers with citations', async () => {
    const { api } = await open();
    await fireEvent.press(screen.getByTestId('tab-ask'));
    await waitFor(() => expect(screen.getByText('2-ishtirokchi ertaga yuboradi.')).toBeTruthy());
    expect(screen.getByText(/Men ertaga hisobotni yuboraman/)).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('ask-input'), 'Narx qancha?');
    await fireEvent.press(screen.getByTestId('ask-send'));
    await waitFor(() => expect(api.ask).toHaveBeenCalledWith(ID, { question: 'Narx qancha?', language: 'uz' }));
    // Javob kelgach tarix qayta o'qiladi - shundan keyin tezkor chip.
    await waitFor(() => expect(api.questions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('Yuborish')).toBeTruthy()); // mutatsiya tugadi
    await fireEvent.press(screen.getByText('Vazifalar'));
    await waitFor(() => expect(api.ask).toHaveBeenCalledTimes(2));
  });

  it('shows the language warning, router banner and a retryable error', async () => {
    const api = fakeMeetingsApi({
      get: jest.fn(async () =>
        meeting({
          status: 'failed',
          languageWarning: 'mostly_other_language',
          transcript: { ...meeting().transcript, engine: 'router' },
          error: { code: 'stt_timeout', message: "Matnga o'girish vaqti tugadi", stage: 'transcribing', retryable: true, retryAt: null },
        }),
      ),
    });
    await open(api);
    expect(screen.getByTestId('language-warning')).toBeTruthy();
    expect(screen.getByText('Bu tilda spikerlar ajratilmaydi, vaqtlar taxminiy')).toBeTruthy();
    expect(screen.getByText("Matnga o'girish vaqti tugadi")).toBeTruthy();
    await fireEvent.press(screen.getByText('Qayta ishlash'));
    await waitFor(() => expect(api.retry).toHaveBeenCalledWith(ID));
  });

  it('while processing there is no summary yet and polling follows pollAfterSec', async () => {
    const api = fakeMeetingsApi({
      get: jest.fn(async () =>
        meeting({
          status: 'transcribing',
          progress: 42,
          pollAfterSec: 3,
          summaryStatus: 'none',
          primarySummaryId: null,
          transcript: { ...meeting().transcript, available: false },
        }),
      ),
    });
    await open(api);
    expect(screen.getByText("Matnga o'girilmoqda 42%")).toBeTruthy();
    expect(screen.getByText("Ishlanmoqda. Tayyor bo'lganda shu yerda ko'rinadi.")).toBeTruthy();
    expect(api.summaries).not.toHaveBeenCalled();
    // waitFor jest taymerlarini o'zi suradi - server bergan 3 s dan keyin qayta so'raladi.
    await waitFor(() => expect((api.get as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(2), { timeout: 6000 });
  }, 20_000);

  it('tabs carry icons; the header shows date and duration with icons; no status pill when ready', async () => {
    await open();
    for (const icon of ['Sparkles', 'ScrollText', 'ListChecks', 'MessageCircleQuestionMark', 'Calendar', 'Clock']) {
      expect(screen.getAllByTestId(`icon-${icon}`).length).toBeGreaterThan(0);
    }
    expect(screen.getByText('9-oktyabr, 11:00')).toBeTruthy();
    expect(screen.getByText('1:00:00')).toBeTruthy();
    expect(screen.getByText('Vazifalar 2')).toBeTruthy();
    expect(screen.queryByText('Tayyor')).toBeNull();
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
  });

  it('player dock: play, -15/+15, speed cycle and TalkBack adjust', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('player-dock')).toBeTruthy());
    expect(screen.queryByTestId('player-local')).toBeNull(); // server audio - telefon belgisi yo'q
    await fireEvent.press(screen.getByTestId('player-play'));
    expect(player.play).toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId('player-fwd'));
    expect(player.seekTo).toHaveBeenLastCalledWith(15);
    await fireEvent.press(screen.getByTestId('player-back'));
    expect(player.seekTo).toHaveBeenLastCalledWith(0);
    for (const [rate, label] of [
      [1.25, '1.25x'],
      [1.5, '1.5x'],
      [2, '2x'],
      [0.75, '0.75x'],
      [1, '1x'],
    ] as const) {
      await fireEvent.press(screen.getByTestId('player-speed'));
      expect(player.setPlaybackRate).toHaveBeenLastCalledWith(rate);
      expect(screen.getByTestId('player-speed')).toHaveTextContent(label);
    }
    expect(screen.getByTestId('player-speed').props.accessibilityLabel).toBe('Tezlik: 1x');
    await fireEvent(screen.getByTestId('player-track'), 'accessibilityAction', { nativeEvent: { actionName: 'increment' } });
    expect(player.seekTo).toHaveBeenLastCalledWith(15);
    await waitFor(() => expect(screen.getByTestId('summary-body')).toBeTruthy());
  });

  it('transcript: tap a line to play from there; the line being heard is highlighted', async () => {
    (ExpoAudio.useAudioPlayerStatus as jest.Mock).mockReturnValue({ currentTime: 10, duration: 120, playing: true, isLoaded: true, playbackRate: 1 });
    try {
      await open();
      await fireEvent.press(screen.getByTestId('tab-transcript'));
      await waitFor(() => expect(screen.getByTestId('bubble-b3')).toBeTruthy());
      expect(screen.getAllByTestId('icon-Play').length).toBeGreaterThan(0);
      expect(screen.getByTestId('bubble-b3').props.accessibilityState?.selected).toBe(true);
      expect(screen.getByTestId('bubble-b1').props.accessibilityState?.selected).toBeFalsy();
      await fireEvent.press(screen.getByTestId('bubble-b1'));
      await waitFor(() => expect(player.seekTo).toHaveBeenCalledWith(0));
      expect(player.play).toHaveBeenCalled();
    } finally {
      (ExpoAudio.useAudioPlayerStatus as jest.Mock).mockReturnValue({ currentTime: 0, duration: 120, playing: false, isLoaded: true, playbackRate: 1 });
    }
  });

  it('⋮ menu renames and deletes (with confirmation)', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    try {
      const { api } = await open(fakeMeetingsApi(), { withHeader: true });
      await waitFor(() => expect(screen.getByTestId('meeting-menu')).toBeTruthy());
      await fireEvent.press(screen.getByTestId('meeting-menu'));
      await fireEvent.press(screen.getByTestId('menu-rename'));
      // Amal menyu yopilgandan keyin ishlaydi (Android dialog fokus muammosi) - kutamiz.
      await fireEvent.changeText(await screen.findByTestId('prompt-input'), 'Yangi nom');
      await fireEvent.press(screen.getByTestId('prompt-save'));
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith(ID, { title: 'Yangi nom' }));

      await fireEvent.press(screen.getByTestId('meeting-menu'));
      await fireEvent.press(screen.getByTestId('menu-delete'));
      await waitFor(() => expect(alert.mock.calls.at(-1)?.[1]).toBe("Yig'ilish butunlay o'chiriladi (audio, matn, xulosa). Davom etasizmi?"));
      const buttons = alert.mock.calls.at(-1)?.[2] as AlertButton[];
      await act(async () => {
        await buttons.find((b) => b.text === "O'chirish")?.onPress?.();
      });
      await waitFor(() => expect(api.remove).toHaveBeenCalledWith(ID));
      // Deep link'dan ochilgan (orqada ekran yo'q) - ro'yxatga o'tadi, o'chirilgan sahifada qolmaydi.
      await waitFor(() => expect(screen.getByText('meetings-screen')).toBeTruthy());
    } finally {
      alert.mockRestore();
    }
  });

  it('transcript data is used for speaker labels in the dialog', async () => {
    const api = fakeMeetingsApi({ transcript: jest.fn(async () => ({ ...transcript, speakers: transcript.speakers.map((s) => (s.id === 'S2' ? { ...s, name: 'Dilnoza' } : s)) })) });
    await open(api);
    await fireEvent.press(screen.getByTestId('tab-transcript'));
    await waitFor(() => expect(screen.getAllByText('Dilnoza').length).toBeGreaterThan(0));
  });
});
