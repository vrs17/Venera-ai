/**
 * Yig'ilish sahifasi (RNTL, expo-router testing-library) soxta API bilan:
 * xulosa bo'limlari, transkript dialogi, vazifalar, savol, banner va
 * tahrirlash oqimlari. Tarmoqqa chiqmaydi.
 */
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { renderRouter } from 'expo-router/testing-library';
import type { ReactNode } from 'react';
import { Share } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as ExpoAudio from 'expo-audio';

import MeetingRoute from '@/app/meeting/[id]';
import { useSettings } from '@/features/settings/settingsStore';

import { fakeMeetingsApi, fakeServices, Providers } from './fixtures/fakeServices';
import { meeting, summary, transcript } from './fixtures/server';

const ID = 'a'.repeat(32);

async function open(api = fakeMeetingsApi()) {
  const services = fakeServices({ meetings: api });
  const wrapper = ({ children }: { children: ReactNode }) => <Providers services={services}>{children}</Providers>;
  await renderRouter({ 'meeting/[id]': MeetingRoute }, { initialUrl: `/meeting/${ID}`, wrapper });
  await waitFor(() => expect(screen.getByTestId('meeting-title')).toBeTruthy());
  return { api, services };
}

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

  it('transcript data is used for speaker labels in the dialog', async () => {
    const api = fakeMeetingsApi({ transcript: jest.fn(async () => ({ ...transcript, speakers: transcript.speakers.map((s) => (s.id === 'S2' ? { ...s, name: 'Dilnoza' } : s)) })) });
    await open(api);
    await fireEvent.press(screen.getByTestId('tab-transcript'));
    await waitFor(() => expect(screen.getAllByText('Dilnoza').length).toBeGreaterThan(0));
  });
});
